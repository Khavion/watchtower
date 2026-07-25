"""Enrichment: firewall short-circuit, 30-day idempotency, cap halts, credit economy."""

from datetime import datetime, timedelta, timezone

import pytest

from pipeline import storage
from pipeline.capgate import CapGate
from pipeline.enrich import run_enrichment
from pipeline.firewall import EmployerFirewall

BLOCKLIST = """| domain | parent_company | reason_code | date_added |
|---|---|---|---|
| blocked-corp.com | Blocked Corp | EMPLOYER_ACCOUNT | 2026-07-24 |
"""

SEARCH_PAGE = {
    "people": [
        {"id": "p1", "name": "Ada CTO", "title": "CTO", "seniority": "c_suite",
         "email_status": "verified",
         "organization": {"id": "o1", "name": "GoodCo", "primary_domain": "goodco.com",
                          "estimated_num_employees": 80, "industry": "software",
                          "country": "United States"}},
        {"id": "p2", "name": "Bob VP", "title": "VP of Engineering", "seniority": "vp",
         "email_status": "verified",
         "organization": {"id": "o2", "name": "Blocked Corp", "primary_domain": "blocked-corp.com",
                          "estimated_num_employees": 90}},
        {"id": "p3", "name": "Cara Dir", "title": "Director of Engineering",
         "email_status": "unverified",
         "organization": {"id": "o3", "name": "StaffCo", "primary_domain": "staffco.com",
                          "estimated_num_employees": 50,
                          "short_description": "A staffing and recruiting agency."}},
        {"id": "p4", "name": "Dan Head", "title": "Head of Platform",
         "email_status": "verified",
         "organization": {"id": "o4", "name": "SeenCo", "primary_domain": "seenco.com",
                          "estimated_num_employees": 40}},
    ]
}


class FakeApollo:
    def __init__(self):
        self.enrich_calls = []

    def people_api_search(self, filters, page=1):
        return SEARCH_PAGE if page == 1 else {"people": []}

    def org_enrich(self, domain):
        self.enrich_calls.append(domain)
        return {"organization": {"latest_funding_stage": "Series A",
                                 "latest_funding_round_date":
                                     (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
                                 "technology_names": ["Amazon AWS", "Kubernetes"]}}


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


def test_blocklisted_account_never_stored_or_enriched(data_dir, firewall, tmp_path, caplog):
    import logging
    client = FakeApollo()
    with caplog.at_level(logging.INFO):
        summary = run_enrichment(client=client, gate=_gate(tmp_path), firewall=firewall,
                                 min_days_between=30)
    assert summary["firewall_dropped"] == 1
    assert "blocked-corp.com" not in client.enrich_calls
    assert not storage.account_path("blocked-corp.com").exists()
    # Reason code logged, contents never echoed.
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "EMPLOYER_ACCOUNT" in joined and "blocked-corp" not in joined


def test_disqualifier_keywords_drop_staffing(data_dir, firewall, tmp_path):
    client = FakeApollo()
    summary = run_enrichment(client=client, gate=_gate(tmp_path), firewall=firewall,
                             min_days_between=30)
    assert summary["disqualified"] >= 1
    assert not storage.account_path("staffco.com").exists()


def test_thirty_day_idempotency(data_dir, firewall, tmp_path):
    recent = {"domain": "seenco.com", "company_name": "SeenCo",
              "fetched_at": datetime.now(timezone.utc).isoformat()}
    storage.save(storage.account_path("seenco.com"), recent)
    client = FakeApollo()
    summary = run_enrichment(client=client, gate=_gate(tmp_path), firewall=firewall,
                             min_days_between=30)
    assert summary["recently_seen"] == 1
    assert "seenco.com" not in client.enrich_calls


def test_happy_path_saves_account_with_buyer_and_trigger(data_dir, firewall, tmp_path):
    client = FakeApollo()
    summary = run_enrichment(client=client, gate=_gate(tmp_path), firewall=firewall,
                             min_days_between=30)
    saved = storage.load(storage.account_path("goodco.com"))
    assert saved is not None
    assert saved["buyer_title"] == "CTO"
    assert saved["buyer_email"] is None  # email reveal deferred to draft time
    assert saved["funding_stage"] == "Series A"
    assert "funding_recent" in saved["triggers"]
    assert summary["credits_spent"] == len(client.enrich_calls)


def test_unconfigured_cap_blocks_enrichment(data_dir, firewall, tmp_path):
    client = FakeApollo()
    summary = run_enrichment(client=client, gate=_gate(tmp_path, monthly=0),
                             firewall=firewall, min_days_between=30)
    assert "halted" in summary
    assert client.enrich_calls == []  # nothing spent


def test_monthly_cap_halts_loudly(data_dir, firewall, tmp_path, caplog):
    gate = _gate(tmp_path, monthly=1)
    client = FakeApollo()
    summary = run_enrichment(client=client, gate=gate, firewall=firewall,
                             min_days_between=30)
    # Two eligible orgs but only 1 credit of monthly budget: halt after the first.
    assert summary["credits_spent"] == 1
    assert "halted" in summary
    assert any("cap" in r.message.lower() for r in caplog.records)
