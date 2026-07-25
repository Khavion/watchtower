"""Small persistent state: pause flag, credit ledgers, poll cursors, daily counters.
Single JSON file, atomic writes. Not a database on purpose."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path

from pipeline.config import DATA_DIR

STATE_PATH = DATA_DIR / "state.json"


def load(path: Path | None = None) -> dict:
    p = path or STATE_PATH
    if not p.exists():
        return {}
    with open(p) as fh:
        return json.load(fh)


def save(state: dict, path: Path | None = None) -> None:
    p = path or STATE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".state-")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(state, fh, indent=2, sort_keys=True, default=str)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def bump_daily_counter(state: dict, key: str, amount: int = 1) -> int:
    """Per-day counter (auto-resets when the date changes). Returns new value."""
    today = date.today().isoformat()
    counter = state.setdefault("daily_counters", {}).setdefault(key, {})
    if counter.get("date") != today:
        counter["date"] = today
        counter["count"] = 0
    counter["count"] += amount
    return counter["count"]


def daily_count(state: dict, key: str) -> int:
    counter = state.get("daily_counters", {}).get(key, {})
    return counter.get("count", 0) if counter.get("date") == date.today().isoformat() else 0
