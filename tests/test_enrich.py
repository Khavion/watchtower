"""Enrichment against the real (redacted) 2026 api_search shape:
pre-credit firewall/idempotency, 1-credit match, post-match checks, cap halts."""

import logging
from datetime import datetime, timedelta, timezone

import pytest

from pipeline import storage
from pipeline.capgate import CapGate
from pipeline.enrich import run_enrichment
from pipeline.firewall import EmployerFirewall

BLOCKLIST = """| domain | parent_company | reason_code | date_added |
|---|---|---|---|
| blocked-corp.com | Blocked Corp | EMPLOYER_ACCOUNT | 2026-07-24 |
| hidden-block.com | | EMPLOYER_ADJACENT | 2026-07-24 |
"""

# What api_search ACTUALLY returns (verified live 2026-07-24): redacted people.
SEARCH_PAGE = {
    "total_entries": 4,
    "people": [
        {"id": "p1", "first_name": "Ada", "title": "CTO", "has_email": True,
         "organization": {"name": "GoodCo"}},
        {"id": "p2", "first_name": "Bob", "title": "VP of Engineering", "has_email": True,
         "organization": {"name": "Blocked Corp"}},
        {"id": "p3", "first_name": "Cara", "title": "Director of Engineering", "has_email": True,
         "organization": {"name": "StaffCo"}},
        {"id": "p4", "first_name": "Dan", "title": "Head of Platform", "has_email": True,
         "organization": {"name": "SneakyCo"}},
        {"id": "p5", "first_name": "Eve", "title": "Marketing Manager", "has_email": True,
         "organization": {"name": "IrrelevantCo"}},
    ],
}

MATCHES = {
    "p1": {"person": {"id": "p1", "name": "Ada Lovelace", "title": "CTO",
                      "seniority": "c_suite", "email": "ada@goodco.com",
                      "email_status": "verified",
                      "organization": {
                          "id": "o1", "name": "GoodCo", "primary_domain": "goodco.com",
                          "estimated_num_employees": 80, "industry": "software",
                          "country": "United States",
                          "technology_names": ["Amazon AWS", "Kubernetes"],
                          "latest_funding_stage": "Series A",
                          "latest_funding_round_date":
                              (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()}}},
    "p3": {"person": {"id": "p3", "name": "Cara Dir", "title": "Director of Engineering",
                      "email": "cara@staffco.com", "email_status": "verified",
                      "organization": {"name": "StaffCo", "primary_domain": "staffco.com",
                                       "estimated_num_employees": 50,
                                       "short_description": "A staffing and recruiting agency."}}},
    "p4": {"person": {"id": "p4", "name": "Dan Head", "title": "Head of Platform",
                      "email": "dan@hidden-block.com", "email_status": "verified",
                      "organization": {"name": "SneakyCo",
                                       "primary_domain": "hidden-block.com",
                                       "estimated_num_employees": 60}}},
}


class FakeApollo:
    def __init__(self):
        self.match_calls = []

    def people_api_search(self, filters, page=1):
        return SEARCH_PAGE if page == 1 else {"people": []}

    def people_match(self, person_id=None, **kw):
        self.match_calls.append(person_id)
        return MATCHES.get(person_id, {"person": {}})


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def firewall(tmp_path):
    p = tmp_path / "bl.local.md"
    p.write_text(BLOCKLIST)
    return EmployerFirewall(blocklist_path=p)


def _gate(tmp_path, monthly=100, per_run=25):
    return CapGate(caps={"apollo": {"monthly_credit_cap": monthly,
                                    "per_run_credit_cap": per_run},
                         "drafts": {"max_per_day": 25},
                         "accounts": {"min_days_between_touches": 30}},
                   state_path=tmp_path / "state.json")


def test_company_name_blocked_before_any_credit(data_dir, firewall, tmp_path, caplog):
    client = FakeApollo()
    with caplog.at_level(logging.INFO):
        summary = run_enrichment(client=client, gate=_gate(tmp_path), firewall=firewall,
                                 min_days_between=30)
    # "Blocked Corp" is dropped from the candidate list pre-match: no credit.
    assert "p2" not in client.match_calls
    assert summary["firewall_dropped"] >= 1
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "EMPLOYER_ACCOUNT" in joined and "Blocked Corp".lower() not in joined.lower()


def test_domain_blocked_after_match_stores_nothing(data_dir, firewall, tmp_path):
    client = FakeApollo()
    run_enrichment(client=client, gate=_gate(tmp_path), firewall=firewall,
                   min_days_between=30)
    # SneakyCo's name is clean but its domain is blocklisted: credit spent,
    # nothing stored.
    assert "p4" in client.match_calls
    assert not storage.account_path("hidden-block.com").exists()


def test_non_buyer_titles_never_matched(data_dir, firewall, tmp_path):
    client = FakeApollo()
    run_enrichment(client=client, gate=_gate(tmp_path), firewall=firewall,
                   min_days_between=30)
    assert "p5" not in client.match_calls  # Marketing Manager is not a buyer


def test_disqualifier_keywords_drop_staffing(data_dir, firewall, tmp_path):
    client = FakeApollo()
    summary = run_enrichment(client=client, gate=_gate(tmp_path), firewall=firewall,
                             min_days_between=30)
    assert summary["disqualified"] >= 1
    assert not storage.account_path("staffco.com").exists()


def test_recently_seen_by_name_skips_pre_credit(data_dir, firewall, tmp_path):
    recent = {"domain": "goodco.com", "company_name": "GoodCo",
              "fetched_at": datetime.now(timezone.utc).isoformat()}
    storage.save(storage.account_path("goodco.com"), recent)
    client = FakeApollo()
    summary = run_enrichment(client=client, gate=_gate(tmp_path), firewall=firewall,
                             min_days_between=30)
    assert "p1" not in client.match_calls
    assert summary["recently_seen"] >= 1


def test_happy_path_saves_account_with_email_and_trigger(data_dir, firewall, tmp_path):
    client = FakeApollo()
    summary = run_enrichment(client=client, gate=_gate(tmp_path), firewall=firewall,
                             min_days_between=30)
    saved = storage.load(storage.account_path("goodco.com"))
    assert saved is not None
    assert saved["buyer_title"] == "CTO"
    assert saved["buyer_email"] == "ada@goodco.com"  # match includes the reveal
    assert saved["buyer_email_status"] == "verified"
    assert saved["funding_stage"] == "Series A"
    assert "funding_recent" in saved["triggers"]
    assert summary["credits_spent"] == len(client.match_calls)


def test_unconfigured_cap_blocks_enrichment(data_dir, firewall, tmp_path):
    client = FakeApollo()
    summary = run_enrichment(client=client, gate=_gate(tmp_path, monthly=0),
                             firewall=firewall, min_days_between=30)
    assert "halted" in summary
    assert client.match_calls == []


def test_monthly_cap_halts_loudly(data_dir, firewall, tmp_path, caplog):
    client = FakeApollo()
    with caplog.at_level(logging.ERROR):
        summary = run_enrichment(client=client, gate=_gate(tmp_path, monthly=1),
                                 firewall=firewall, min_days_between=30)
    assert summary["credits_spent"] == 1
    assert "halted" in summary
    assert any("cap" in r.message.lower() for r in caplog.records)


def test_match_budget_limits_run(data_dir, firewall, tmp_path):
    client = FakeApollo()
    summary = run_enrichment(client=client, gate=_gate(tmp_path), firewall=firewall,
                             min_days_between=30, match_budget=1)
    assert summary["matched"] == 1
