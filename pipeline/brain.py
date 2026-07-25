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


STYLE_EXEMPLARS_FILE = "style-exemplars.local.md"


@lru_cache(maxsize=None)
def style_exemplars(brain_dir: Path | None = None) -> list[str]:
    """Zohaib's own real sent emails, used as five-shot style examples.

    Local only and never committed (the filename matches the `*.local*` rule in
    .gitignore) because it is his private correspondence. Pulled from Zoho Mail
    by agents/collect_style.py; absent on a fresh clone, which is fine -- the
    drafter degrades to the written voice rules and says so in the log.

    Each exemplar is separated by a `---` line. Content is passed through the
    employer firewall on load: a sent email of his may well mention an employer
    account, and that must never reach a model's context window.
    """
    path = (brain_dir or BRAIN_DIR) / STYLE_EXEMPLARS_FILE
    if not path.exists():
        return []
    from pipeline.firewall import get_firewall
    firewall = get_firewall()
    out = []
    for chunk in path.read_text().split("\n---\n"):
        chunk = chunk.strip()
        if not chunk or chunk.startswith("#"):
            continue
        if firewall.check_text(chunk):
            # Reason code only; the offending text is never logged or surfaced.
            continue
        out.append(chunk)
    return out


@lru_cache(maxsize=None)
def industry_ranges() -> list[dict]:
    """Stated ranges ABOUT THE FIELD, not claims about work Zohaib did. Kept
    separate from proof_points so a drafter can never present one as a personal
    result (see the 2026-07-25 rewrite of proof.md)."""
    text = read("proof.md")
    for block in re.findall(r"```yaml\s*\n(.*?)```", text, re.DOTALL):
        data = yaml.safe_load(block)
        if isinstance(data, dict) and "industry_ranges" in data:
            return data["industry_ranges"]
    return []


@lru_cache(maxsize=None)
def content_topics() -> list[dict]:
    block = fenced_block(read("content.md"), "yaml")
    data = yaml.safe_load(block) or {}
    return data.get("topics", [])


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
               proof_points, industry_ranges, content_topics, style_exemplars,
               unheld_certifications, rubric):
        # getattr: a caller may have substituted a plain function for one of
        # these (tests do), and a cache flush should never be the thing that
        # raises.
        getattr(fn, "cache_clear", lambda: None)()
