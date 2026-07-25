"""Go/no-go: disqualifier parsing with verbatim quotes, set-aside -> NEEDS_HUMAN."""

from datetime import date, timedelta

from pipeline.gonogo import run_gonogo

BASE = {
    "source_id": "esbd", "dedupe_key": "esbd:t1",
    "title": "Cloud modernization services",
    "notice_type": "RFP",
    "due_date": (date.today() + timedelta(days=30)).isoformat(),
    "attachments": [],
}


def test_bond_requirement_is_no_go_with_quote():
    sol = {**BASE, "description":
           "Scope includes cloud migration. The successful Offeror shall furnish "
           "a $500,000 performance bond within ten days of award. Work is remote."}
    verdict = run_gonogo(sol, weekly_capacity_hours=10, min_deadline_days=7)
    assert verdict.verdict == "NO_GO"
    bond = next(d for d in verdict.disqualifiers if d.kind == "bonding")
    assert "$500,000 performance bond" in bond.requirement_quote
    assert "offset" in bond.location


def test_set_aside_returns_needs_human_verbatim():
    sol = {**BASE, "description":
           "This solicitation is designated as a VetHUB set-aside per current "
           "Comptroller rules. Cloud consulting services requested."}
    verdict = run_gonogo(sol, weekly_capacity_hours=10, min_deadline_days=7)
    assert verdict.verdict == "NEEDS_HUMAN"
    assert "VetHUB" in (verdict.set_aside_text or "")
    assert any("verbatim" in r for r in verdict.reasons)


def test_clean_solicitation_is_go():
    sol = {**BASE, "notice_type": "Sources Sought",
           "description": "Remote cloud cost optimization advisory, "
                          "no special requirements."}
    verdict = run_gonogo(sol, weekly_capacity_hours=10, min_deadline_days=7)
    assert verdict.verdict == "GO"
    assert verdict.fits_capacity is True


def test_deadline_too_close_is_no_go():
    sol = {**BASE, "due_date": (date.today() + timedelta(days=2)).isoformat(),
           "description": "Simple advisory work."}
    verdict = run_gonogo(sol, weekly_capacity_hours=10, min_deadline_days=7)
    assert verdict.verdict == "NO_GO"
    assert any(d.kind == "deadline_too_close" for d in verdict.disqualifiers)


def test_past_performance_and_incumbent():
    sol = {**BASE,
           "description": "Offerors shall demonstrate past performance on three "
                          "similar contracts of comparable scope.",
           "raw": {"award": {"awardee": {"name": "Incumbent Corp LLC"}}}}
    verdict = run_gonogo(sol, weekly_capacity_hours=10, min_deadline_days=7)
    assert verdict.verdict == "NO_GO"
    assert any(d.kind == "past_performance" for d in verdict.disqualifiers)
    assert verdict.incumbent == "Incumbent Corp LLC"


def test_big_rfp_exceeding_capacity_needs_human():
    sol = {**BASE, "attachments": [f"a{i}.pdf" for i in range(12)],
           "description": "Large cloud program, no disqualifying requirements."}
    verdict = run_gonogo(sol, weekly_capacity_hours=10, min_deadline_days=7)
    assert verdict.estimated_hours > 10
    assert verdict.verdict == "NEEDS_HUMAN"
    assert verdict.fits_capacity is False


def test_prebid_conference_already_passed():
    past = (date.today() - timedelta(days=5)).strftime("%m/%d/%Y")
    sol = {**BASE, "description":
           f"A mandatory pre-bid conference was held on {past} at the agency. "
           "Proposals due as scheduled."}
    verdict = run_gonogo(sol, weekly_capacity_hours=10, min_deadline_days=7)
    assert any(d.kind == "prebid_conference_passed" for d in verdict.disqualifiers)
    assert verdict.verdict == "NO_GO"
