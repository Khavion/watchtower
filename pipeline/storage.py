"""Flat-file record storage under data/. One JSON per record.

Solicitations are keyed by dedupe_key across ALL sources (esbd and
university_boards can surface the same posting; first ingest wins).
Accounts are keyed by domain.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

from pipeline.config import DATA_DIR


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def solicitation_path(dedupe_key: str) -> Path:
    return DATA_DIR / "solicitations" / f"{_safe(dedupe_key)}.json"


def account_path(domain: str) -> Path:
    return DATA_DIR / "accounts" / f"{_safe(domain.lower())}.json"


def exists(path: Path) -> bool:
    return path.exists()


def save(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as fh:
        json.dump(record, fh, indent=2, sort_keys=True, default=str)
    tmp.replace(path)


def load(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path) as fh:
        return json.load(fh)


def iter_records(subdir: str) -> Iterator[dict]:
    root = DATA_DIR / subdir
    if not root.exists():
        return
    for p in sorted(root.glob("*.json")):
        with open(p) as fh:
            yield json.load(fh)


def known_solicitation_keys() -> set[str]:
    root = DATA_DIR / "solicitations"
    if not root.exists():
        return set()
    return {rec.get("dedupe_key") for rec in iter_records("solicitations") if rec.get("dedupe_key")}
