"""SQLite: job schedules, run history, and Zohaib's raw notes.

Deliberately the cheapest thing that works (AGENTS-PLAN.md C3). One file, no
server, no Docker, no vector store: every one of those costs RAM this machine
needs for the model. FTS5 ships with Python's sqlite3, so full-text search over
run history is free. Embeddings stay unbuilt until keyword search demonstrably
misses something.

Why schedules live here and not in launchd plists: adding an agent later should
be one row, not a new plist plus a reload. launchd runs one dumb tick; this
table decides what is actually due.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pipeline.config import DATA_DIR

DB_PATH = DATA_DIR / "watchtower.db"
TZ = ZoneInfo("America/Chicago")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    name                  TEXT PRIMARY KEY,
    schedule              TEXT NOT NULL,   -- see parse_schedule()
    enabled               INTEGER NOT NULL DEFAULT 1,
    next_due_at           TEXT,            -- ISO local time; NULL = manual only
    last_run_at           TEXT,
    last_status           TEXT,
    last_summary          TEXT,
    -- A briefing three days late is worse than no briefing: past this many
    -- seconds the run is dropped and rescheduled rather than delivered stale.
    max_staleness_seconds INTEGER NOT NULL DEFAULT 10800,
    description           TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name    TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT,
    summary     TEXT
);
CREATE INDEX IF NOT EXISTS runs_job_started ON runs(job_name, started_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS runs_fts USING fts5(
    job_name, summary, content='runs', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS runs_ai AFTER INSERT ON runs BEGIN
    INSERT INTO runs_fts(rowid, job_name, summary)
    VALUES (new.id, new.job_name, COALESCE(new.summary, ''));
END;
CREATE TRIGGER IF NOT EXISTS runs_au AFTER UPDATE ON runs BEGIN
    INSERT INTO runs_fts(runs_fts, rowid, job_name, summary)
    VALUES ('delete', old.id, old.job_name, COALESCE(old.summary, ''));
    INSERT INTO runs_fts(rowid, job_name, summary)
    VALUES (new.id, new.job_name, COALESCE(new.summary, ''));
END;

-- Raw material Zohaib types into Cliq with `note ...`. Stored as data, never
-- interpreted as instructions. The marketing writer reads from here first.
CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    text       TEXT NOT NULL,
    used_at    TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    text, content='notes', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, text) VALUES (new.id, new.text);
END;
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=30)
    conn.row_factory = sqlite3.Row
    # WAL so the Cliq poller can read while an agent writes. They hold separate
    # locks and genuinely do run at the same time.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


def now() -> datetime:
    return datetime.now(TZ)


# --------------------------------------------------------------------------
# Schedules
#
# Format, chosen so a human can read the table directly:
#   daily@06:30            every day at 06:30
#   weekdays@07:00,13:00   Mon-Fri, at each listed time
#   weekly@sun18:00        Sundays at 18:00
#   every@300              every 300 seconds
#   manual                 never auto-due; runs only when enqueued
# --------------------------------------------------------------------------

_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def next_due(schedule: str, after: datetime | None = None) -> datetime | None:
    """Next fire time strictly after `after`. None means manual-only."""
    after = after or now()
    spec = (schedule or "").strip().lower()

    if spec in ("", "manual"):
        return None

    kind, _, rest = spec.partition("@")

    if kind == "every":
        return after + timedelta(seconds=max(30, int(rest)))

    if kind == "weekly":
        # e.g. sun18:00 -> day name is the first three characters, then a clock
        target_dow = _WEEKDAYS[rest[:3]]
        hour, minute = (int(x) for x in rest[3:].split(":"))
        candidate = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = (target_dow - candidate.weekday()) % 7
        candidate += timedelta(days=days_ahead)
        if candidate <= after:
            candidate += timedelta(days=7)
        return candidate

    if kind in ("daily", "weekdays"):
        times = []
        for chunk in rest.split(","):
            hour, minute = (int(x) for x in chunk.split(":"))
            times.append((hour, minute))
        # Search forward day by day. Bounded at 14 days, which is far past any
        # real schedule and stops a malformed spec spinning.
        for day_offset in range(0, 15):
            day = after + timedelta(days=day_offset)
            if kind == "weekdays" and day.weekday() > 4:
                continue
            for hour, minute in sorted(times):
                candidate = day.replace(hour=hour, minute=minute,
                                        second=0, microsecond=0)
                if candidate > after:
                    return candidate
        return None

    raise ValueError(f"unparseable schedule {schedule!r}")


# --------------------------------------------------------------------------
# Job registry
# --------------------------------------------------------------------------

def upsert_job(conn: sqlite3.Connection, name: str, schedule: str,
               description: str = "", max_staleness_seconds: int = 10800,
               enabled: bool = True) -> None:
    """Register or re-register a job. Existing enabled/next_due state is kept so
    a reinstall never silently re-enables something Zohaib turned off, and never
    fires a backlog."""
    row = conn.execute("SELECT name, schedule FROM jobs WHERE name = ?", (name,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO jobs (name, schedule, enabled, next_due_at, "
            "max_staleness_seconds, description) VALUES (?, ?, ?, ?, ?, ?)",
            (name, schedule, int(enabled),
             _iso(next_due(schedule)), max_staleness_seconds, description))
    else:
        # Schedule changes take effect; enabled state is the operator's.
        new_due = _iso(next_due(schedule)) if row["schedule"] != schedule else None
        if new_due:
            conn.execute("UPDATE jobs SET schedule = ?, next_due_at = ?, "
                         "max_staleness_seconds = ?, description = ? WHERE name = ?",
                         (schedule, new_due, max_staleness_seconds, description, name))
        else:
            conn.execute("UPDATE jobs SET max_staleness_seconds = ?, description = ? "
                         "WHERE name = ?", (max_staleness_seconds, description, name))
    conn.commit()


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def enqueue(conn: sqlite3.Connection, name: str) -> bool:
    """Mark a job due immediately (what a Cliq command does). Returns False if
    the job is unknown, so a typo is reported rather than silently swallowed."""
    row = conn.execute("SELECT name FROM jobs WHERE name = ?", (name,)).fetchone()
    if row is None:
        return False
    conn.execute("UPDATE jobs SET next_due_at = ?, enabled = 1 WHERE name = ?",
                 (_iso(now()), name))
    conn.commit()
    return True


def claim_due_job(conn: sqlite3.Connection, at: datetime | None = None) -> sqlite3.Row | None:
    """The single job to run this tick: the most overdue one. Returns None when
    nothing is due. The caller already holds the exclusive agent lock."""
    at = at or now()
    return conn.execute(
        "SELECT * FROM jobs WHERE enabled = 1 AND next_due_at IS NOT NULL "
        "AND next_due_at <= ? ORDER BY next_due_at ASC LIMIT 1",
        (_iso(at),)).fetchone()


def is_stale(job: sqlite3.Row, at: datetime | None = None) -> bool:
    """A run whose moment has passed. Dropping it beats delivering a stale
    briefing that reads as if it were this morning's."""
    at = at or now()
    due = datetime.fromisoformat(job["next_due_at"])
    return (at - due).total_seconds() > job["max_staleness_seconds"]


def reschedule(conn: sqlite3.Connection, name: str, status: str,
               summary: str = "", at: datetime | None = None) -> None:
    at = at or now()
    row = conn.execute("SELECT schedule FROM jobs WHERE name = ?", (name,)).fetchone()
    conn.execute(
        "UPDATE jobs SET next_due_at = ?, last_run_at = ?, last_status = ?, "
        "last_summary = ? WHERE name = ?",
        (_iso(next_due(row["schedule"], after=at)), _iso(at), status,
         summary[:2000], name))
    conn.commit()


def record_run(conn: sqlite3.Connection, job_name: str, started_at: datetime,
               status: str, summary: str) -> None:
    conn.execute(
        "INSERT INTO runs (job_name, started_at, finished_at, status, summary) "
        "VALUES (?, ?, ?, ?, ?)",
        (job_name, _iso(started_at), _iso(now()), status, summary[:4000]))
    conn.commit()


def recent_runs(conn: sqlite3.Connection, since_hours: int = 24) -> list[sqlite3.Row]:
    cutoff = _iso(now() - timedelta(hours=since_hours))
    return conn.execute(
        "SELECT * FROM runs WHERE started_at >= ? ORDER BY started_at DESC",
        (cutoff,)).fetchall()


def search_runs(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT r.* FROM runs_fts f JOIN runs r ON r.id = f.rowid "
        "WHERE runs_fts MATCH ? ORDER BY r.started_at DESC LIMIT ?",
        (query, limit)).fetchall()


# --------------------------------------------------------------------------
# Notes
# --------------------------------------------------------------------------

def add_note(conn: sqlite3.Connection, text: str) -> int:
    cur = conn.execute("INSERT INTO notes (created_at, text) VALUES (?, ?)",
                       (_iso(now()), text))
    conn.commit()
    return cur.lastrowid


def unused_notes(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM notes WHERE used_at IS NULL ORDER BY created_at ASC LIMIT ?",
        (limit,)).fetchall()


def mark_notes_used(conn: sqlite3.Connection, ids: list[int]) -> None:
    if not ids:
        return
    conn.executemany("UPDATE notes SET used_at = ? WHERE id = ?",
                     [(_iso(now()), i) for i in ids])
    conn.commit()
