"""Publish: firewall re-check blocks writes; drafts land as drafts; CRM blocks
never imply sending."""

import pytest

from pipeline.firewall import EmployerFirewall
from pipeline.publish import PublishBlocked, publish_account, publish_solicitation
from zoho.crm import deal_description, lead_description

BLOCKLIST = """| domain | parent_company | reason_code | date_added |
|---|---|---|---|
| blocked-corp.com | Blocked Corp | EMPLOYER_ACCOUNT | 2026-07-24 |
"""


@pytest.fixture
def firewall(tmp_path):
    p = tmp_path / "bl.local.md"
    p.write_text(BLOCKLIST)
    return EmployerFirewall(blocklist_path=p)


class FakeCRM:
    def __init__(self):
        self.leads = []
        self.deals = []

    def upsert_lead(self, account, block):
        self.leads.append((account, block))
        return "lead-1"

    def upsert_deal(self, sol, block):
        self.deals.append((sol, block))
        return "deal-1"


class FakeMail:
    def __init__(self):
        self.drafts = []

    def create_draft(self, to, subject, body):
        self.drafts.append((to, subject, body))
        return "msg-42"


ACCOUNT = {"domain": "goodco.com", "company_name": "GoodCo",
           "buyer_name": "Ada Lovelace", "fetched_at": "2026-07-24T12:00:00"}
SCORE = {"total": 85, "criteria": {}, "hard_fails": [], "rubric_version": "1.0.0"}
DRAFT = {"status": "DRAFTED", "subject": "your EKS spend",
         "body": "Ada, quick observation...", "to": "ada@goodco.com",
         "variant": "A", "model": "llama3.1:8b@x"}


def test_publish_account_writes_lead_and_mail_draft(firewall):
    crm, mail = FakeCRM(), FakeMail()
    result = publish_account(ACCOUNT, SCORE, DRAFT, crm=crm, mail=mail, firewall=firewall)
    assert result == {"crm_id": "lead-1", "mail_message_id": "msg-42"}
    assert mail.drafts[0][0] == "ada@goodco.com"
    _, block = crm.leads[0]
    assert block["draft_status"] == "DRAFTED"
    # No vocabulary implying sending exists in the record block.
    assert "sent" not in str(block).lower() and "submitted" not in str(block).lower()


def test_publish_blocked_account_writes_nothing(firewall):
    crm, mail = FakeCRM(), FakeMail()
    with pytest.raises(PublishBlocked) as exc:
        publish_account({**ACCOUNT, "domain": "blocked-corp.com"}, SCORE, DRAFT,
                        crm=crm, mail=mail, firewall=firewall)
    assert exc.value.reason_code == "EMPLOYER_ACCOUNT"
    assert not crm.leads and not mail.drafts


def test_no_email_draft_skips_mail_but_records_lead(firewall):
    crm, mail = FakeCRM(), FakeMail()
    result = publish_account(ACCOUNT, SCORE, {"status": "NO_EMAIL"}, crm=crm,
                             mail=mail, firewall=firewall)
    assert result["mail_message_id"] is None
    assert crm.leads and not mail.drafts


def test_publish_solicitation_records_verdict_verbatim(firewall):
    crm = FakeCRM()
    sol = {"dedupe_key": "esbd:s1", "source_id": "esbd", "title": "Cloud work",
           "agency": "Fine Agency", "fetched_at": "2026-07-24"}
    verdict = {"verdict": "NO_GO",
               "reasons": ["bonding: shall furnish a $500,000 performance bond"],
               "disqualifiers": [{"kind": "bonding",
                                  "requirement_quote": "shall furnish a $500,000 performance bond",
                                  "location": "description offset 42"}],
               "set_aside_text": None, "incumbent": None,
               "estimated_hours": 20, "deadline_days": 21}
    publish_solicitation(sol, SCORE, verdict, crm=crm, firewall=firewall)
    _, block = crm.deals[0]
    assert block["gonogo_verdict"] == "NO_GO"
    assert "$500,000 performance bond" in str(block["disqualifiers"])


def test_descriptions_are_plain_english_no_json():
    """A non-technical VA reads these: plain sentences, no JSON, no jargon."""
    lead_text = lead_description({
        "score_total": 69, "fetched_at": "2026-07-24T12:00:00",
        "score_breakdown": {"cloud_footprint": {"criterion_score": 100},
                            "trigger_recency": {"criterion_score": 2}},
        "triggers": {"funding_recent": "Angel closed 2026-02-01"},
        "draft_status": "DRAFTED", "hard_fails": []})
    assert "Score: 69 out of 100." in lead_text
    assert "Buying signal: Angel closed 2026-02-01." in lead_text
    assert "waiting in Zoho Mail Drafts" in lead_text
    assert "cloud usage" in lead_text          # criterion translated to plain words
    for techy in ("{", "}", '":', "icp_fit", "rubric", "DRAFTED"):
        assert techy not in lead_text

    deal_text = deal_description({
        "score_total": 54, "gonogo_verdict": "NO_GO", "source": "esbd",
        "url": "https://example.test/x", "estimated_hours": 20, "deadline_days": 10,
        "disqualifiers": [{"kind": "bonding",
                           "requirement_quote": "shall furnish a $500,000 performance bond"}],
        "set_aside_text_verbatim": None, "incumbent": "Incumbent Corp"})
    assert "Decision: NO GO. Skip this one." in deal_text
    assert "a bond is required" in deal_text
    assert '"shall furnish a $500,000 performance bond"' in deal_text
    assert "Current contract holder: Incumbent Corp." in deal_text
    assert "Nothing has been submitted." in deal_text
    for techy in ("{", "}", "gonogo", "verdict", "NO_GO"):
        assert techy not in deal_text
