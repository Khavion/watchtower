"""Readers for brain/ — plain markdown loaded directly into context.
No RAG, no embeddings: fenced blocks give the machine-readable pieces."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import yaml

from pipeline.config import BRAIN_DIR


def read(name: str, brain_dir: Path | None = None) -> str:
    return ((brain_dir or BRAIN_DIR) / name).read_text()


def fenced_block(text: str, lang: str) -> str | None:
    m = re.search(rf"```{lang}\s*\n(.*?)```", text, re.DOTALL)
    return m.group(1) if m else None


@lru_cache(maxsize=None)
def icp_filters() -> dict:
    block = fenced_block(read("icp.md"), "yaml")
    return yaml.safe_load(block)["apollo_filters"]


@lru_cache(maxsize=None)
def icp_disqualifier_keywords() -> list[str]:
    text = read("icp.md")
    for block in re.findall(r"```yaml\s*\n(.*?)```", text, re.DOTALL):
        data = yaml.safe_load(block)
        if isinstance(data, dict) and "disqualifier_keywords" in data:
            return data["disqualifier_keywords"]
    return []


@lru_cache(maxsize=None)
def triggers() -> dict:
    return yaml.safe_load(fenced_block(read("triggers.md"), "yaml"))


@lru_cache(maxsize=None)
def voice_rules() -> dict:
    return json.loads(fenced_block(read("voice.md"), "json"))


@lru_cache(maxsize=None)
def proof_points(verified_only: bool = True) -> list[dict]:
    """Proof entries. Anything not verified: true never reaches generated output."""
    points = []
    text = read("proof.md")
    for block in re.findall(r"```yaml\s*\n(.*?)```", text, re.DOTALL):
        data = yaml.safe_load(block)
        if isinstance(data, dict) and "proof_points" in data:
            points.extend(data["proof_points"])
    if verified_only:
        points = [p for p in points if p.get("verified") is True]
    return points


@lru_cache(maxsize=None)
def unheld_certifications() -> list[str]:
    block = fenced_block(read("boundaries.md"), "yaml")
    data = yaml.safe_load(block) or {}
    return [str(c) for c in data.get("unheld_certifications", [])]


@lru_cache(maxsize=None)
def rubric() -> dict:
    return json.loads(read("rubric.json"))


def clear_cache() -> None:
    for fn in (icp_filters, icp_disqualifier_keywords, triggers, voice_rules,
               proof_points, unheld_certifications, rubric):
        fn.cache_clear()
