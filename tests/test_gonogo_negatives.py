"""Negated set-aside phrasing must not trigger NEEDS_HUMAN; real ones must."""

from datetime import date, timedelta

from pipeline.gonogo import run_gonogo

BASE = {
    "source_id": "sam_gov", "dedupe_key": "sam_gov:n1",
    "title": "Cloud advisory sources sought",
    "notice_type": "Sources Sought",
    "due_date": (date.today() + timedelta(days=30)).isoformat(),
    "attachments": [],
}


def test_no_set_aside_used_is_not_needs_human():
    sol = {**BASE, "set_aside_text": "No Set aside used",
           "description": "Remote cloud advisory, no special requirements."}
    verdict = run_gonogo(sol, weekly_capacity_hours=10, min_deadline_days=7)
    assert verdict.verdict == "GO"


def test_negated_sentence_in_description_is_not_needs_human():
    sol = {**BASE, "description": "There is no set-aside for this procurement. "
                                  "Remote cloud advisory services requested."}
    verdict = run_gonogo(sol, weekly_capacity_hours=10, min_deadline_days=7)
    assert verdict.verdict == "GO"


def test_real_set_aside_still_needs_human():
    sol = {**BASE, "set_aside_text": "Total Small Business Set-Aside (FAR 19.5)",
           "description": "Remote cloud advisory."}
    verdict = run_gonogo(sol, weekly_capacity_hours=10, min_deadline_days=7)
    assert verdict.verdict == "NEEDS_HUMAN"


def test_negation_with_hub_mention_still_needs_human():
    sol = {**BASE, "set_aside_text":
           "This is not a small business set-aside; however VetHUB participation applies.",
           "description": "Remote advisory."}
    verdict = run_gonogo(sol, weekly_capacity_hours=10, min_deadline_days=7)
    assert verdict.verdict == "NEEDS_HUMAN"
