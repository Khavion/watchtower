"""The dispatcher: one tick, one lock, exactly one agent.

    python -m pipeline.dispatch          # one tick; what launchd runs
    python -m pipeline.dispatch --register   # (re)register the job table
    python -m pipeline.dispatch --status     # what is due, what ran last

Why a lock and not launchd's own guard: launchd's ThrottleInterval and
single-instance behaviour stop a job overlapping ITSELF. They do nothing to stop
the briefing agent and the triage agent running at the same moment, which on a
16 GB machine means two model contexts, swap, and a tenfold throughput collapse.
So every agent run passes through one exclusive fcntl.flock. If the lock is
held, this tick exits immediately and silently: the next tick is 60 seconds
away, and queueing would only build the pile-up the lock exists to prevent.

The Cliq poller deliberately takes a DIFFERENT lock, so chat stays responsive
while a long agent runs. Commands that start work enqueue a row here rather than
running it inline, which is what keeps "exactly one agent" true.
"""

from __future__ import annotations

import argparse
import fcntl
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path

from pipeline import db
from pipeline.config import DATA_DIR
from pipeline.logutil import new_run_logger

log = logging.getLogger(__name__)

AGENT_LOCK = DATA_DIR / "agent.lock"
CLIQ_LOCK = DATA_DIR / "cliq.lock"


class Busy(Exception):
    """Another holder has the lock. Not an error: the expected steady state."""


class exclusive_lock:
    """Non-blocking exclusive flock. Released by the OS even on a hard kill,
    which matters for an unattended machine: a crashed agent must not wedge the
    schedule until someone notices."""

    def __init__(self, path: Path):
        self.path = path
        self._fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "w")
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._fh.close()
            self._fh = None
            raise Busy(f"{self.path.name} is held by another process") from exc
        self._fh.write(f"{datetime.now().isoformat()}\n")
        self._fh.flush()
        return self

    def __exit__(self, *exc_info):
        if self._fh:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            self._fh.close()
            self._fh = None
        return False


# --------------------------------------------------------------------------
# The job table. Adding an agent later is one entry here.
# Times confirmed with Zohaib 2026-07-25.
# --------------------------------------------------------------------------

JOBS = [
    # name, schedule, staleness (s), description shown by `agents` in Cliq
    ("daily_briefing", "daily@06:30", 4 * 3600,
     "One plain-English summary of everything, before the workday"),
    ("inbox_triage", "weekdays@07:00,13:00", 3 * 3600,
     "Sorts the Khavion inbox and drafts replies. Never sends"),
    ("procurement_fetch", "weekdays@07:30,14:00", 6 * 3600,
     "Finds and scores public solicitations"),
    ("apollo_enrich", "weekly@mon06:00", 12 * 3600,
     "Finds and scores prospect accounts, drafts outreach"),
    ("marketing_writer", "weekly@sun18:00", 24 * 3600,
     "Writes two LinkedIn drafts from your notes. Never posts"),
    ("proposal_writer", "manual", 3600,
     "Drafts an SOW from a deal. Run it with: proposal <id>"),
]


def register(conn) -> None:
    for name, schedule, staleness, description in JOBS:
        db.upsert_job(conn, name, schedule, description=description,
                      max_staleness_seconds=staleness)


def agent_registry() -> dict:
    """name -> callable(logger) -> summary string.

    Imported lazily and individually so one broken agent cannot stop the others
    from being dispatchable."""
    from agents import briefing, marketing, proposal, triage
    from pipeline import run as pipeline_run

    return {
        "daily_briefing": briefing.run,
        "inbox_triage": triage.run,
        "marketing_writer": marketing.run,
        "proposal_writer": proposal.run,
        "procurement_fetch": lambda log_: str(pipeline_run.job_procurement_fetch()),
        "apollo_enrich": lambda log_: str(pipeline_run.job_apollo_enrich()),
    }


def tick() -> str:
    """One dispatcher tick. Returns a short outcome string for the log."""
    try:
        with exclusive_lock(AGENT_LOCK):
            conn = db.connect()
            job = db.claim_due_job(conn)
            if job is None:
                return "idle"

            name = job["name"]
            if db.is_stale(job):
                # Dropped on purpose: a briefing delivered three days late reads
                # as if it were this morning's, which is worse than none.
                db.reschedule(conn, name, "SKIPPED_STALE",
                              "dropped: past its usefulness window")
                db.record_run(conn, name, db.now(), "SKIPPED_STALE",
                              "run was overdue past max_staleness; dropped")
                return f"{name}: skipped (stale)"

            registry = agent_registry()
            if name not in registry:
                db.reschedule(conn, name, "NO_HANDLER", "no handler registered")
                return f"{name}: no handler"

            started = db.now()
            agent_log, _ = new_run_logger(name)
            try:
                summary = registry[name](agent_log) or ""
                status = "OK"
            except Exception:
                summary = traceback.format_exc(limit=6)
                status = "FAILED"
                agent_log.exception("%s failed", name)

            db.record_run(conn, name, started, status, summary)
            db.reschedule(conn, name, status, summary)
            return f"{name}: {status}"
    except Busy:
        return "busy"


def status() -> str:
    conn = db.connect()
    lines = ["job                 enabled  next due             last run             last"]
    for row in conn.execute("SELECT * FROM jobs ORDER BY name"):
        lines.append(f"{row['name']:<20}{'yes' if row['enabled'] else 'no':<9}"
                     f"{(row['next_due_at'] or 'manual')[:19]:<21}"
                     f"{(row['last_run_at'] or '-')[:19]:<21}"
                     f"{row['last_status'] or '-'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.dispatch")
    parser.add_argument("--register", action="store_true",
                        help="(re)register the job table, then exit")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)

    if args.register:
        register(db.connect())
        print(status())
        return 0
    if args.status:
        print(status())
        return 0

    outcome = tick()
    if outcome not in ("idle", "busy"):
        print(f"{datetime.now().isoformat(timespec='seconds')} {outcome}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
