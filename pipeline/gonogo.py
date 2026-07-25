"""Go/no-go: a structured verdict BEFORE any prose is generated.

Optimized for killing bad fits in seconds. A NO_GO with reasons is a success.
Every disqualifier carries the requirement quoted verbatim and where it was
found. Texas set-asides: the HUB program has been in active litigation through
2026 and its eligibility rules have changed more than once, so NOTHING about
HUB/VetHUB eligibility is encoded here — any set-aside language returns
NEEDS_HUMAN with the requirement text verbatim.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

from pipeline import brain
from pipeline.models import Disqualifier, GoNoGoVerdict

log = logging.getLogger(__name__)

# kind -> pattern. Each match becomes a Disqualifier with the sentence quoted.
DISQUALIFIER_PATTERNS: dict[str, re.Pattern] = {
    "bonding": re.compile(
        r"(bid|performance|payment)\s+bond|bond\s+(in the amount|of \$|requirement)|"
        r"\$[\d,]+\s*(bid|performance|payment)?\s*bond", re.IGNORECASE),
    "insurance_minimum": re.compile(
        r"(insurance|liability)[^.\n]{0,80}(minimum|not less than|at least)\s*(of\s*)?\$[\d,]+|"
        r"\$[\d,]+[^.\n]{0,40}(general liability|professional liability|insurance)", re.IGNORECASE),
    "years_in_business": re.compile(
        r"(minimum|at least|no less than)\s+\w+\s*\(?\d*\)?\s+years?[^.\n]{0,40}"
        r"(in business|of experience as a (firm|company)|of corporate existence|of operation)",
        re.IGNORECASE),
    "past_performance": re.compile(
        r"past performance|CPARS|references from\s+\w+\s+similar|"
        r"(three|3|five|5)\s+(similar|comparable)\s+(contracts|projects|engagements)",
        re.IGNORECASE),
    "onsite_required": re.compile(
        r"\bon[- ]?site\b[^.\n]{0,80}\b(required|mandatory|must|shall|only)\b|"
        r"\b(work|services)\s+(must|shall)\s+be\s+performed\s+(at|on)[- ]?site",
        re.IGNORECASE),
    "w2_required": re.compile(r"\bW-?2\b[^.\n]{0,60}", re.IGNORECASE),
}

SET_ASIDE_RE = re.compile(
    r"[^.\n]{0,120}\b(HUB\b|VetHUB|set[- ]aside|historically underutilized|"
    r"service[- ]disabled veteran|SDVOSB|8\(a\)|WOSB|HUBZone|small business set)"
    r"[^.\n]{0,200}", re.IGNORECASE)

PREBID_RE = re.compile(
    r"[^.\n]{0,80}\bpre[- ]?(bid|proposal)\s+(conference|meeting)\b[^.\n]{0,160}",
    re.IGNORECASE)
DATE_IN_TEXT_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2,4})")

# Calendar-effort heuristic by notice type (documented, crude on purpose;
# gonogo's job is the kill decision, not project estimation).
HOURS_BY_TYPE = [
    (re.compile(r"sources sought|rfi|special notice", re.IGNORECASE), 4.0),
    (re.compile(r"presol", re.IGNORECASE), 6.0),
    (re.compile(r"rfq", re.IGNORECASE), 10.0),
    (re.compile(r".", re.IGNORECASE), 20.0),  # RFP / IFB / full solicitations
]


def _sentence_around(text: str, start: int, end: int, cap: int = 300) -> str:
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start)) + 1
    right_dot = text.find(".", end)
    right_nl = text.find("\n", end)
    rights = [r for r in (right_dot, right_nl) if r != -1]
    right = min(rights) + 1 if rights else min(len(text), end + 120)
    return " ".join(text[left:right].split())[:cap]


def _find_disqualifiers(sol: dict, min_deadline_days: int) -> list[Disqualifier]:
    text = f"{sol.get('title', '')}\n{sol.get('description', '')}"
    found: list[Disqualifier] = []

    for kind, pattern in DISQUALIFIER_PATTERNS.items():
        m = pattern.search(text)
        if m:
            found.append(Disqualifier(
                kind=kind,
                requirement_quote=_sentence_around(text, m.start(), m.end()),
                location=f"description offset {m.start()}"))

    for cert in brain.unheld_certifications():
        m = re.search(re.escape(cert), text, re.IGNORECASE)
        if m:
            found.append(Disqualifier(
                kind="unheld_certification",
                requirement_quote=_sentence_around(text, m.start(), m.end()),
                location=f"description offset {m.start()} ({cert})"))

    m = PREBID_RE.search(text)
    if m:
        quote = _sentence_around(text, m.start(), m.end())
        dm = DATE_IN_TEXT_RE.search(quote)
        if dm:
            month, day, year = (int(g) for g in dm.groups())
            year += 2000 if year < 100 else 0
            try:
                when = date(year, month, day)
                if when < date.today():
                    found.append(Disqualifier(
                        kind="prebid_conference_passed",
                        requirement_quote=quote,
                        location=f"description offset {m.start()}"))
            except ValueError:
                pass

    due_raw = sol.get("due_date")
    if due_raw:
        due = due_raw if isinstance(due_raw, date) else datetime.strptime(
            str(due_raw)[:10], "%Y-%m-%d").date()
        days = (due - date.today()).days
        if days < min_deadline_days:
            found.append(Disqualifier(
                kind="deadline_too_close",
                requirement_quote=f"Response due {due.isoformat()} "
                                  f"({days} days out; minimum window {min_deadline_days})",
                location="due_date field"))

    if sol.get("eligibility_flag") == "NOT_YET_ELIGIBLE":
        found.append(Disqualifier(
            kind="not_yet_eligible",
            requirement_quote="Flagged NOT_YET_ELIGIBLE at fetch: full federal "
                              "solicitation carrying past-performance language",
            location="eligibility_flag"))

    return found


def _estimate_hours(sol: dict) -> float:
    notice = sol.get("notice_type") or ""
    base = next(h for p, h in HOURS_BY_TYPE if p.search(notice or "x"))
    extra = max(0, len(sol.get("attachments") or []) - 2) * 2.0
    return min(60.0, base + extra)


def run_gonogo(sol: dict, weekly_capacity_hours: float | None = None,
               min_deadline_days: int | None = None) -> GoNoGoVerdict:
    if weekly_capacity_hours is None or min_deadline_days is None:
        from pipeline.config import caps
        c = caps()
        weekly_capacity_hours = weekly_capacity_hours or float(
            c.get("capacity", {}).get("weekly_capacity_hours", 10))
        min_deadline_days = min_deadline_days or int(
            c.get("gonogo", {}).get("min_deadline_days", 7))

    text = f"{sol.get('title', '')}\n{sol.get('description', '')}"
    disqualifiers = _find_disqualifiers(sol, min_deadline_days)

    set_aside = sol.get("set_aside_text")
    if not set_aside:
        m = SET_ASIDE_RE.search(text)
        if m:
            set_aside = " ".join(m.group(0).split())[:400]

    incumbent = None
    award = (sol.get("raw") or {}).get("award")
    if isinstance(award, dict):
        awardee = award.get("awardee")
        if isinstance(awardee, dict):
            incumbent = awardee.get("name")

    est_hours = _estimate_hours(sol)
    fits = est_hours <= weekly_capacity_hours

    deadline_days = None
    if sol.get("due_date"):
        due_raw = sol["due_date"]
        due = due_raw if isinstance(due_raw, date) else datetime.strptime(
            str(due_raw)[:10], "%Y-%m-%d").date()
        deadline_days = (due - date.today()).days

    reasons: list[str] = []
    if disqualifiers:
        verdict = "NO_GO"
        reasons = [f"{d.kind}: {d.requirement_quote[:120]}" for d in disqualifiers]
    elif set_aside:
        # Zero assumptions about HUB/VetHUB eligibility; a human decides.
        verdict = "NEEDS_HUMAN"
        reasons = [f"set-aside language (verbatim): {set_aside}"]
    elif not fits:
        verdict = "NEEDS_HUMAN"
        reasons = [f"estimated {est_hours:.0f}h response exceeds weekly capacity "
                   f"({weekly_capacity_hours:.0f}h)"]
    else:
        verdict = "GO"
        reasons = ["no disqualifiers found; fits capacity"]

    result = GoNoGoVerdict(
        verdict=verdict, disqualifiers=disqualifiers, set_aside_text=set_aside,
        incumbent=incumbent, estimated_hours=est_hours, fits_capacity=fits,
        deadline_days=deadline_days, reasons=reasons)
    log.info("gonogo %s: %s (%d disqualifiers)", sol.get("dedupe_key"),
             verdict, len(disqualifiers))
    return result
