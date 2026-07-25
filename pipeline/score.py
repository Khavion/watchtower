"""Deterministic scoring against brain/rubric.json. No LLM anywhere in here.

The rubric holds weights, points, thresholds, and the hard_fail list; this
module holds the signal detectors keyed by signal id. Changing scoring
behavior = editing rubric.json. A hard fail zeroes the total regardless of
everything else; the per-criterion breakdown is preserved for the record.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from pipeline import brain
from pipeline.firewall import EmployerFirewall, get_firewall
from pipeline.models import ScoreBreakdown

ONSITE_RE = re.compile(
    r"[^.\n]{0,80}\bon[- ]?site\b[^.\n]{0,120}", re.IGNORECASE)
ONSITE_HARD_RE = re.compile(
    r"\bon[- ]?site\b[^.\n]{0,80}\b(required|mandatory|must|shall|only)\b|"
    r"\b(required|mandatory|must|shall)\b[^.\n]{0,80}\bon[- ]?site\b", re.IGNORECASE)
W2_RE = re.compile(r"\bW-?2\b[^.\n]{0,80}|\bno (1099|corp[- ]to[- ]corp|c2c)\b", re.IGNORECASE)
OUT_OF_SCOPE_RE = re.compile(
    r"staff(ing)? augmentation|staffing services|temporary personnel|temp[- ]to[- ]hire",
    re.IGNORECASE)


def _criterion_score(spec: dict, matches: dict[str, float]) -> tuple[int, dict]:
    """matches: signal id -> 0..1 strength. best_match takes the strongest
    matched signal's points; additive sums matched points (capped 100)."""
    signals = spec.get("signals", {})
    detail = {sid: {"points": pts, "strength": round(matches.get(sid, 0.0), 3)}
              for sid, pts in signals.items()}
    if spec.get("mode") == "best_match":
        value = max((pts * matches.get(sid, 0.0) for sid, pts in signals.items()),
                    default=0.0)
    else:
        value = sum(pts * matches.get(sid, 0.0) for sid, pts in signals.items())
    return int(round(min(100.0, value))), detail


def _build(criteria_spec: dict, all_matches: dict[str, dict[str, float]],
           hard_fails: list[str], rubric: dict) -> ScoreBreakdown:
    total = 0.0
    breakdown = {}
    for name, spec in criteria_spec.items():
        crit_score, detail = _criterion_score(spec, all_matches.get(name, {}))
        weighted = spec["weight"] * crit_score / 100.0
        total += weighted
        breakdown[name] = {"weight": spec["weight"], "criterion_score": crit_score,
                           "weighted": round(weighted, 1), "signals": detail}
    final = 0 if hard_fails else int(round(total))
    return ScoreBreakdown(rubric_version=rubric["version"], total=final,
                          hard_fails=hard_fails, criteria=breakdown)


# ----- accounts -----

def _trigger_strength(account: dict) -> float:
    """Sum of configured weights for observed triggers, funding decayed
    linearly by age when the observed detail carries a parseable date."""
    cfg = brain.triggers().get("triggers", {})
    if not cfg:
        return 0.0
    # Normalize against a two-solid-triggers bar (not the sum of all five):
    # triggers stack, and requiring every signal at once to max the criterion
    # would bury a single fresh funding round, the strongest real-world signal.
    full_bar = 60.0
    got = 0.0
    for trig_id, detail in (account.get("triggers") or {}).items():
        spec = cfg.get(trig_id)
        if not spec:
            continue
        strength = 1.0
        m = re.search(r"(\d{4}-\d{2}-\d{2})", str(detail))
        if m:
            try:
                age = (date.today() - datetime.strptime(m.group(1), "%Y-%m-%d").date()).days
                horizon = int(spec.get("horizon_days", 180))
                strength = max(0.0, 1.0 - age / horizon)
            except ValueError:
                pass
        got += spec.get("weight", 0) * strength
    return min(1.0, got / full_bar)


def score_account(account: dict, firewall: EmployerFirewall | None = None,
                  rubric: dict | None = None) -> ScoreBreakdown:
    firewall = firewall or get_firewall()
    rubric = rubric or brain.rubric()

    employees = account.get("employee_count")
    technologies = " ".join(account.get("technologies") or []).lower()
    industry = (account.get("industry") or "").lower()
    stage = (account.get("funding_stage") or "").lower()
    location_blob = " ".join(account.get("locations") or []).lower()
    email_status = (account.get("buyer_email_status") or "").lower().replace(" ", "_")
    seniority = (account.get("buyer_seniority") or "").lower()
    title = (account.get("buyer_title") or "").lower()

    matches: dict[str, dict[str, float]] = {
        "icp_fit": {
            "employees_in_range": 1.0 if employees and 20 <= employees <= 200 else 0.0,
            "us_based": 1.0 if "united states" in location_blob or not location_blob else 0.5,
            "industry_match": 1.0 if any(k in industry for k in
                                         ("software", "saas", "information technology",
                                          "internet", "computer")) else 0.0,
            "funding_stage_series_a_or_b": 1.0 if ("series a" in stage or "series b" in stage) else 0.0,
        },
        "cloud_footprint": {
            "aws_detected": 1.0 if ("aws" in technologies or "amazon" in technologies) else 0.0,
            "kubernetes_detected": 1.0 if "kubernetes" in technologies else 0.0,
            "other_cloud_detected": 1.0 if any(k in technologies for k in
                                               ("azure", "google cloud", "gcp")) else 0.0,
        },
        "trigger_recency": {"decayed_trigger_sum": _trigger_strength(account)},
        "buyer_seniority": {
            "c_suite": 1.0 if (seniority == "c_suite" or "chief" in title or "cto" in title) else 0.0,
            "vp": 1.0 if (seniority == "vp" or title.startswith("vp") or "vice president" in title) else 0.0,
            "head": 1.0 if (seniority == "head" or title.startswith("head")) else 0.0,
            "director": 1.0 if (seniority == "director" or "director" in title) else 0.0,
        },
        "contactability": {
            "email_verified": 1.0 if email_status == "verified" else 0.0,
            "email_likely_to_engage": 1.0 if "likely" in email_status else 0.0,
            "email_unverified": 1.0 if email_status == "unverified" else 0.0,
            "email_unavailable": 1.0 if email_status == "unavailable" else 0.0,
        },
    }

    hard_fails = []
    if firewall.check_domain(account.get("domain")) or firewall.check_company(
            account.get("company_name")):
        hard_fails.append("blocklist_hit")
    if employees is not None and not (20 <= employees <= 200):
        hard_fails.append("headcount_out_of_range")
    if not account.get("buyer_title") or email_status == "unavailable":
        hard_fails.append("no_reachable_buyer")

    return _build(rubric["account_criteria"], matches, hard_fails, rubric)


# ----- solicitations -----

CAPABILITY_TERMS = ["cloud", "aws", "azure", "kubernetes", "artificial intelligence",
                    "machine learning", " ai ", "llm", "generative", "chatbot", "genai",
                    "data platform", "analytics", "devops", "migration", "modernization",
                    "software development", "it consulting", "architecture"]


def score_solicitation(sol: dict, firewall: EmployerFirewall | None = None,
                       rubric: dict | None = None,
                       min_deadline_days: int = 7) -> ScoreBreakdown:
    firewall = firewall or get_firewall()
    rubric = rubric or brain.rubric()

    text = f" {sol.get('title', '')} {sol.get('description', '')} ".lower()
    notice_type = (sol.get("notice_type") or "").lower()
    source = sol.get("source_id", "")

    hits = sum(1 for term in CAPABILITY_TERMS if term in text)
    is_sought = ("sources sought" in notice_type or "rfi" in notice_type
                 or "special notice" in notice_type)
    is_presol = "presol" in notice_type

    runway = 0.0
    deadline_days = None
    due_raw = sol.get("due_date")
    if due_raw:
        due = due_raw if isinstance(due_raw, date) else datetime.strptime(
            str(due_raw)[:10], "%Y-%m-%d").date()
        deadline_days = (due - date.today()).days
        runway = max(0.0, min(1.0, (deadline_days - min_deadline_days) / (30 - min_deadline_days)))

    matches = {
        "capability_match": {"keyword_hits_scaled": min(1.0, hits / 4.0)},
        "notice_type_fit": {
            "sources_sought_or_rfi": 1.0 if is_sought else 0.0,
            "presolicitation": 1.0 if is_presol else 0.0,
            "full_solicitation": 1.0 if not (is_sought or is_presol) else 0.0,
        },
        "timeline_runway": {"runway_scaled": runway},
        "agency_fit": {
            "texas_state_or_local": 1.0 if source in ("esbd", "university_boards") else 0.0,
            "federal_sources_sought": 1.0 if source == "sam_gov" and is_sought else 0.0,
            "federal_full": 1.0 if source == "sam_gov" and not is_sought else 0.0,
        },
    }

    hard_fails = []
    if (firewall.check_text(sol.get("title", "") + " " + sol.get("description", ""))
            or firewall.check_company(sol.get("agency"))):
        hard_fails.append("blocklist_hit")
    if OUT_OF_SCOPE_RE.search(text):
        hard_fails.append("out_of_scope_boundaries")
    if ONSITE_HARD_RE.search(text):
        hard_fails.append("requires_onsite")
    if W2_RE.search(text):
        hard_fails.append("requires_w2")
    lowered_certs = [c.lower() for c in brain.unheld_certifications()]
    if any(c in text for c in lowered_certs):
        hard_fails.append("requires_unheld_certification")
    if deadline_days is not None and deadline_days < min_deadline_days:
        # Not in the rubric hard_fail list by name; gonogo turns this into a
        # quoted disqualifier. Here it just zeroes runway (already 0).
        pass

    return _build(rubric["solicitation_criteria"], matches, hard_fails, rubric)
