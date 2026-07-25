"""Dispatcher: the lock, the schedule table, staleness, and one-agent-at-a-time.

The lock is the load-bearing part of the whole multi-agent design. launchd's own
guard stops a job overlapping itself and does nothing about two DIFFERENT agents
colliding, which on a 16 GB machine means two model contexts and swap.
"""

import multiprocessing
import time
from datetime import datetime, timedelta

import pytest

from pipeline import db
from pipeline.dispatch import Busy, exclusive_lock


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "test.db")


# --------------------------------------------------------------------------
# The lock
# --------------------------------------------------------------------------

def test_second_holder_is_refused_immediately(tmp_path):
    lock = tmp_path / "agent.lock"
    with exclusive_lock(lock):
        started = time.monotonic()
        with pytest.raises(Busy):
            with exclusive_lock(lock):
                pass
        # Non-blocking: it must refuse now, not wait for the first to finish.
        assert time.monotonic() - started < 0.5


def test_lock_is_released_on_exit(tmp_path):
    lock = tmp_path / "agent.lock"
    with exclusive_lock(lock):
        pass
    with exclusive_lock(lock):
        pass  # must not raise


def test_lock_is_released_when_the_holder_raises(tmp_path):
    lock = tmp_path / "agent.lock"
    with pytest.raises(ValueError):
        with exclusive_lock(lock):
            raise ValueError("agent blew up")
    with exclusive_lock(lock):
        pass  # a crashed agent must not wedge the schedule


def _hold_lock(path, ready, release):
    with exclusive_lock(path):
        ready.set()
        release.wait(timeout=10)


def test_lock_excludes_a_separate_process(tmp_path):
    """flock is held per open file description, so this is the case that
    actually matters: two launchd ticks are two processes, not two threads."""
    lock = tmp_path / "agent.lock"
    ctx = multiprocessing.get_context("spawn")
    ready, release = ctx.Event(), ctx.Event()
    proc = ctx.Process(target=_hold_lock, args=(lock, ready, release))
    proc.start()
    try:
        assert ready.wait(timeout=10), "helper process never took the lock"
        with pytest.raises(Busy):
            with exclusive_lock(lock):
                pass
    finally:
        release.set()
        proc.join(timeout=10)


# --------------------------------------------------------------------------
# Schedules
# --------------------------------------------------------------------------

def test_daily_schedule_picks_the_next_occurrence():
    monday_5am = datetime(2026, 7, 27, 5, 0, tzinfo=db.TZ)
    assert db.next_due("daily@06:30", after=monday_5am) == \
        datetime(2026, 7, 27, 6, 30, tzinfo=db.TZ)
    monday_7am = datetime(2026, 7, 27, 7, 0, tzinfo=db.TZ)
    assert db.next_due("daily@06:30", after=monday_7am) == \
        datetime(2026, 7, 28, 6, 30, tzinfo=db.TZ)


def test_weekdays_schedule_skips_the_weekend():
    friday_evening = datetime(2026, 7, 31, 18, 0, tzinfo=db.TZ)  # a Friday
    result = db.next_due("weekdays@07:00,13:00", after=friday_evening)
    assert result.weekday() == 0, "next weekday run is Monday, not Saturday"
    assert (result.hour, result.minute) == (7, 0)


def test_weekdays_schedule_handles_the_second_time_of_day():
    friday_8am = datetime(2026, 7, 31, 8, 0, tzinfo=db.TZ)
    result = db.next_due("weekdays@07:00,13:00", after=friday_8am)
    assert (result.day, result.hour) == (31, 13)


def test_weekly_schedule():
    wednesday = datetime(2026, 7, 29, 12, 0, tzinfo=db.TZ)
    result = db.next_due("weekly@sun18:00", after=wednesday)
    assert result.weekday() == 6 and result.hour == 18


def test_manual_schedule_is_never_automatically_due():
    assert db.next_due("manual") is None


def test_unparseable_schedule_fails_loudly():
    with pytest.raises(ValueError):
        db.next_due("sometimes@maybe")


# --------------------------------------------------------------------------
# The job table
# --------------------------------------------------------------------------

def test_registering_twice_does_not_disturb_a_disabled_job(conn):
    db.upsert_job(conn, "briefing", "daily@06:30")
    conn.execute("UPDATE jobs SET enabled = 0 WHERE name = 'briefing'")
    conn.commit()
    db.upsert_job(conn, "briefing", "daily@06:30")
    row = conn.execute("SELECT enabled FROM jobs WHERE name = 'briefing'").fetchone()
    assert row["enabled"] == 0, "a reinstall must not re-enable what he turned off"


def test_changing_a_schedule_moves_the_next_run(conn):
    db.upsert_job(conn, "briefing", "daily@06:30")
    before = conn.execute("SELECT next_due_at FROM jobs").fetchone()["next_due_at"]
    db.upsert_job(conn, "briefing", "daily@21:00")
    after = conn.execute("SELECT next_due_at FROM jobs").fetchone()["next_due_at"]
    assert before != after


def test_only_one_job_is_claimed_per_tick(conn):
    past = db._iso(db.now() - timedelta(minutes=5))
    for name in ("a", "b", "c"):
        db.upsert_job(conn, name, "daily@06:30")
        conn.execute("UPDATE jobs SET next_due_at = ? WHERE name = ?", (past, name))
    conn.commit()
    claimed = db.claim_due_job(conn)
    assert claimed is not None
    assert claimed["name"] in ("a", "b", "c")


def test_the_most_overdue_job_wins(conn):
    db.upsert_job(conn, "old", "daily@06:30")
    db.upsert_job(conn, "new", "daily@06:30")
    conn.execute("UPDATE jobs SET next_due_at = ? WHERE name = 'old'",
                 (db._iso(db.now() - timedelta(hours=3)),))
    conn.execute("UPDATE jobs SET next_due_at = ? WHERE name = 'new'",
                 (db._iso(db.now() - timedelta(minutes=1)),))
    conn.commit()
    assert db.claim_due_job(conn)["name"] == "old"


def test_nothing_due_returns_nothing(conn):
    db.upsert_job(conn, "later", "daily@06:30")
    conn.execute("UPDATE jobs SET next_due_at = ?",
                 (db._iso(db.now() + timedelta(hours=2)),))
    conn.commit()
    assert db.claim_due_job(conn) is None


def test_a_disabled_job_is_never_claimed(conn):
    db.upsert_job(conn, "paused_job", "daily@06:30")
    conn.execute("UPDATE jobs SET enabled = 0, next_due_at = ?",
                 (db._iso(db.now() - timedelta(hours=1)),))
    conn.commit()
    assert db.claim_due_job(conn) is None


def test_stale_runs_are_dropped_not_delivered_late(conn):
    """A briefing three days late reads as if it were this morning's."""
    db.upsert_job(conn, "briefing", "daily@06:30", max_staleness_seconds=4 * 3600)
    conn.execute("UPDATE jobs SET next_due_at = ?",
                 (db._iso(db.now() - timedelta(days=3)),))
    conn.commit()
    job = db.claim_due_job(conn)
    assert db.is_stale(job) is True


def test_a_recent_miss_is_not_stale(conn):
    db.upsert_job(conn, "briefing", "daily@06:30", max_staleness_seconds=4 * 3600)
    conn.execute("UPDATE jobs SET next_due_at = ?",
                 (db._iso(db.now() - timedelta(minutes=30)),))
    conn.commit()
    assert db.is_stale(db.claim_due_job(conn)) is False


def test_enqueue_makes_a_manual_job_due_now(conn):
    db.upsert_job(conn, "proposal_writer", "manual")
    assert db.claim_due_job(conn) is None
    assert db.enqueue(conn, "proposal_writer") is True
    assert db.claim_due_job(conn)["name"] == "proposal_writer"


def test_enqueueing_an_unknown_job_is_reported_not_swallowed(conn):
    assert db.enqueue(conn, "no_such_agent") is False


def test_rescheduling_moves_the_job_forward(conn):
    db.upsert_job(conn, "briefing", "daily@06:30")
    conn.execute("UPDATE jobs SET next_due_at = ?",
                 (db._iso(db.now() - timedelta(hours=1)),))
    conn.commit()
    db.reschedule(conn, "briefing", "OK", "wrote the briefing")
    row = conn.execute("SELECT * FROM jobs WHERE name = 'briefing'").fetchone()
    assert datetime.fromisoformat(row["next_due_at"]) > db.now()
    assert row["last_status"] == "OK"


# --------------------------------------------------------------------------
# Run history and notes
# --------------------------------------------------------------------------

def test_run_history_is_searchable(conn):
    db.record_run(conn, "inbox_triage", db.now(), "OK",
                  "sorted 4 messages, drafted 2 replies about kubernetes")
    db.record_run(conn, "daily_briefing", db.now(), "OK", "quiet morning")
    hits = db.search_runs(conn, "kubernetes")
    assert len(hits) == 1 and hits[0]["job_name"] == "inbox_triage"


def test_notes_are_stored_and_consumed_once(conn):
    db.add_note(conn, "idea: post about autoscaling defaults nobody revisits")
    assert len(db.unused_notes(conn)) == 1
    note_id = db.unused_notes(conn)[0]["id"]
    db.mark_notes_used(conn, [note_id])
    assert db.unused_notes(conn) == []


def test_every_registered_job_has_a_handler():
    """A schedule row with no code behind it would fail silently at 6:30am."""
    from pipeline.dispatch import JOBS, agent_registry

    registry = agent_registry()
    for name, _, _, _ in JOBS:
        assert name in registry, f"{name} is scheduled but has no handler"
