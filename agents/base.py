"""Shared agent plumbing: the model, Cliq, and the plain-English rule.

Two constraints shape everything here.

The model: one resident model serves every agent (AGENTS-PLAN.md). Agents never
choose or swap models; they call `generate()` and get whatever
config/providers.yaml says is loaded. A swap costs 3-10 seconds and risks
pushing 16 GB into swap.

The reader: a non-technical VA reads what these agents write into Zoho, and
Zohaib reads it in Cliq. So every user-visible string goes through
`plain_english()`, which strips the things a model reaches for when it is
uncertain: markdown scaffolding, JSON, field names, tracebacks.
"""

from __future__ import annotations

import logging
import re

from pipeline import brain, sanitize
from providers import Provider, ProviderUnavailable, get_provider

log = logging.getLogger(__name__)

# Small models emit malformed tool calls past about five tools, so no agent in
# this package gets more than five capabilities. This is a design ceiling that
# exists to be noticed if someone tries to raise it.
MAX_TOOLS_PER_AGENT = 5


class AgentSkipped(Exception):
    """The agent had nothing to do. A normal outcome, not a failure."""


def model(provider: Provider | None = None) -> Provider:
    return provider or get_provider()


def generate(provider: Provider, system: str, user: str, max_tokens: int = 700,
             temperature: float | None = None) -> str:
    """One model call, with untrusted material already wrapped by the caller."""
    try:
        return provider.generate(system, user, max_tokens=max_tokens,
                                 temperature=temperature)
    except ProviderUnavailable as exc:
        raise AgentSkipped(f"the local model is not responding ({exc})") from exc


def as_data(text: str, label: str = "data") -> str:
    """Wrap fetched content so it is unmistakably data, never instructions.
    Everything an agent reads from the outside world goes through this."""
    cleaned = sanitize.neutralize(text or "")
    sanitize.scan(cleaned, context=label)
    return f"<data>\n{cleaned}\n</data>"


_MARKDOWN_NOISE = re.compile(r"^\s{0,3}#{1,6}\s*|\*\*|__|^\s*```.*$", re.MULTILINE)
_FIELD_NAMES = re.compile(r"\b[a-z_]+_(?:id|key|at|count|status)\b")


def plain_english(text: str, max_chars: int = 3500) -> str:
    """Make model output safe for a non-technical reader.

    Deliberately blunt. If a model returns JSON or a traceback because it got
    confused, the VA must not be the one to discover that in the CRM."""
    out = (text or "").strip()
    if out.startswith("{") or out.startswith("["):
        return "The summary could not be written in plain language this time."
    out = _MARKDOWN_NOISE.sub("", out)
    out = _FIELD_NAMES.sub("", out)
    out = re.sub(r"—", ",", out)                    # banned character, house style
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r"[ \t]{2,}", " ", out).strip()
    return out[:max_chars]


def voice_violations(text: str) -> list[str]:
    """The banned-phrase and employer-name rules apply to everything the system
    writes, not only cold email. A briefing that says 'circling back' is still
    wrong, and a LinkedIn post naming an employer is worse than wrong."""
    from pipeline.draft_outreach import org_name_check

    rules = brain.voice_rules()
    lowered = (text or "").lower()
    problems = [f"banned phrase: {p!r}" for p in rules.get("banned_phrases", [])
                if p.lower() in lowered]
    problems += org_name_check(text, rules)
    return problems


def cliq_post(message: str, log_: logging.Logger | None = None) -> None:
    """Post to the channel. Never raises: a failed post must not fail the run
    whose result it was reporting."""
    logger = log_ or log
    try:
        from pipeline import config
        from zoho.auth import ZohoAuth
        from zoho.cliq import ZohoCliq

        channel = config.schedule().get("cliq", {}).get("channel_unique_name",
                                                        "khavionagent")
        ZohoCliq(ZohoAuth(), channel).post(message)
    except Exception:
        logger.exception("cliq post failed (the run itself is unaffected)")
