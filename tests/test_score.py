"""Deterministic rubric scoring: breakdowns, weights, hard-fail zeroing."""

from datetime import date, timedelta

import pytest

from pipeline.firewall import EmployerFirewall
from pipeline.score import score_account, score_solicitation

BLOCKLIST = """| domain | parent_company | reason_code | date_added |
|---|---|---|---|
| blocked-corp.com | Blocked Corp | EMPLOYER_ACCOUNT | 2026-07-24 |
"""


@pytest.fixture
def firewall(tmp_path):
    p = tmp_path / "bl.local.md"
    p.write_text(BLOCKLIST)
    return EmployerFirewall(blocklist_path=p)


GOOD_ACCOUNT = {
    "domain": "goodco.com", "company_name": "GoodCo",
    "employee_count": 80, "industry": "software",
    "locations": ["United States"],
    "technologies": ["Amazon AWS", "Kubernetes"],
    "funding_stage": "Series A",
    "triggers": {"funding_recent": f"Series A closed {(date.today() - timedelta(days=30)).isoformat()}"},
    "buyer_title": "CTO", "buyer_seniority": "c_suite",
    "buyer_email_status": "verified",
}


def test_good_account_scores_high_with_breakdown(firewall):
    result = score_account(GOOD_ACCOUNT, firewall=firewall)
    assert result.total >= 80
    assert result.hard_fails == []
    assert set(result.criteria) == {"icp_fit", "cloud_footprint", "trigger_recency",
                                    "buyer_seniority", "contactability"}
    assert result.criteria["cloud_footprint"]["criterion_score"] >= 80
    assert result.rubric_version == "1.0.0"


def test_blocklisted_account_scores_zero(firewall):
    account = {**GOOD_ACCOUNT, "domain": "blocked-corp.com", "company_name": "Blocked Corp"}
    result = score_account(account, firewall=firewall)
    assert result.total == 0
    assert "blocklist_hit" in result.hard_fails
    # Breakdown preserved even when zeroed.
    assert result.criteria["icp_fit"]["criterion_score"] > 0


def test_headcount_out_of_range_hard_fails(firewall):
    result = score_account({**GOOD_ACCOUNT, "employee_count": 5000}, firewall=firewall)
    assert result.total == 0 and "headcount_out_of_range" in result.hard_fails


def test_unreachable_buyer_hard_fails(firewall):
    result = score_account({**GOOD_ACCOUNT, "buyer_email_status": "unavailable"},
                           firewall=firewall)
    assert result.total == 0 and "no_reachable_buyer" in result.hard_fails


def test_trigger_decay_reduces_score(firewall):
    fresh = score_account(GOOD_ACCOUNT, firewall=firewall)
    stale = {**GOOD_ACCOUNT, "triggers": {
        "funding_recent": f"Series A closed {(date.today() - timedelta(days=170)).isoformat()}"}}
    assert score_account(stale, firewall=firewall).criteria["trigger_recency"][
        "criterion_score"] < fresh.criteria["trigger_recency"]["criterion_score"]


SOL = {
    "source_id": "esbd", "dedupe_key": "esbd:x", "title": "Cloud migration and AI advisory",
    "description": "Agency seeks cloud architecture, kubernetes and machine learning consulting.",
    "notice_type": "RFP",
    "due_date": (date.today() + timedelta(days=30)).isoformat(),
}


def test_solicitation_scores_and_notice_type(firewall):
    result = score_solicitation(SOL, firewall=firewall)
    assert result.total > 40
    sought = score_solicitation({**SOL, "notice_type": "Sources Sought"}, firewall=firewall)
    assert sought.total > result.total  # sources sought outranks full solicitation


def test_solicitation_w2_and_certification_hard_fail(firewall):
    w2 = score_solicitation({**SOL, "description": "Contractor personnel must be W-2 employees."},
                            firewall=firewall)
    assert w2.total == 0 and "requires_w2" in w2.hard_fails

    cert = score_solicitation({**SOL, "description": "Vendor must hold CMMC level 2."},
                              firewall=firewall)
    assert cert.total == 0 and "requires_unheld_certification" in cert.hard_fails


def test_solicitation_onsite_hard_fail(firewall):
    onsite = score_solicitation(
        {**SOL, "description": "All work shall be performed on-site at the agency office."},
        firewall=firewall)
    assert onsite.total == 0 and "requires_onsite" in onsite.hard_fails
