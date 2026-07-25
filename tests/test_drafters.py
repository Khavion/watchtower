"""Drafters: blocklist short-circuit, voice-check retries, DRAFT_FAILED,
verified-proof enforcement, GO-only outlines with mandatory gap lists."""

import pytest

from pipeline.capgate import CapGate
from pipeline.draft_bid_outline import draft_outline
from pipeline.draft_outreach import draft_touch_one, voice_check
from pipeline.firewall import EmployerFirewall
from pipeline.models import GoNoGoVerdict
from providers.base import Provider

BLOCKLIST = """| domain | parent_company | reason_code | date_added |
|---|---|---|---|
| blocked-corp.com | Blocked Corp | EMPLOYER_ACCOUNT | 2026-07-24 |
"""

GOOD_DRAFT = """Subject: your EKS spend

Ada, saw GoodCo closed a Series A last month. Post-raise AWS bills usually
jump before anyone owns them. My guess: your EKS nodes are over-provisioned
for the traffic you serve.

I run cloud cost work for funded B2B teams. Smart Karpenter, co-created with
Avesha, landed 20 to 70% reductions on compute-heavy workloads. Happy to
pressure-test that guess on a free 30-minute architecture review. Worth a look?"""

BAD_DRAFT = """Subject: quick question

Hi Ada, I hope this finds you well! I wanted to reach out about our
cutting-edge, best-in-class AI solutions — we've helped 500 clients."""


class ScriptedProvider(Provider):
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def generate(self, system, user, max_tokens):
        self.calls += 1
        return self.replies.pop(0) if self.replies else GOOD_DRAFT

    def model_info(self):
        return "llama3.1:8b@testdigest"


@pytest.fixture
def firewall(tmp_path):
    p = tmp_path / "bl.local.md"
    p.write_text(BLOCKLIST)
    return EmployerFirewall(blocklist_path=p)


def _gate(tmp_path):
    return CapGate(caps={"apollo": {"monthly_credit_cap": 100, "per_run_credit_cap": 25},
                         "drafts": {"max_per_day": 25},
                         "accounts": {"min_days_between_touches": 30}},
                   state_path=tmp_path / "state.json")


ACCOUNT = {"domain": "goodco.com", "company_name": "GoodCo",
           "employee_count": 80, "industry": "software",
           "technologies": ["Amazon AWS", "Kubernetes"],
           "buyer_name": "Ada", "buyer_title": "CTO",
           "buyer_email": "ada@goodco.com",
           "triggers": {"funding_recent": "Series A closed 2026-06-24"}}


def test_voice_check_catches_banned_content():
    violations = voice_check("quick question", BAD_DRAFT.split("\n\n", 1)[1])
    kinds = " ".join(violations)
    assert "i hope this finds you well" in kinds
    assert "i wanted to reach out" in kinds
    assert "—" in kinds or "banned character" in kinds
    assert voice_check("your EKS spend", GOOD_DRAFT.split("\n\n", 1)[1]) == []


def test_blocklisted_account_never_reaches_provider(tmp_path, firewall):
    provider = ScriptedProvider([GOOD_DRAFT])
    result = draft_touch_one({**ACCOUNT, "domain": "blocked-corp.com"},
                             provider=provider, gate=_gate(tmp_path), firewall=firewall)
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "EMPLOYER_ACCOUNT"
    assert provider.calls == 0


def test_retry_then_success(tmp_path, firewall):
    provider = ScriptedProvider([BAD_DRAFT, GOOD_DRAFT])
    result = draft_touch_one(ACCOUNT, provider=provider, gate=_gate(tmp_path),
                             firewall=firewall)
    assert result["status"] == "DRAFTED"
    assert result["attempts"] == 2
    assert result["to"] == "ada@goodco.com"
    assert result["model"] == "llama3.1:8b@testdigest"


def test_draft_failed_after_three_bad_attempts(tmp_path, firewall):
    provider = ScriptedProvider([BAD_DRAFT, BAD_DRAFT, BAD_DRAFT])
    result = draft_touch_one(ACCOUNT, provider=provider, gate=_gate(tmp_path),
                             firewall=firewall)
    assert result["status"] == "DRAFT_FAILED"
    assert result["attempts"] == 3
    assert result["violations"]


def test_draft_cap_halts(tmp_path, firewall):
    gate = CapGate(caps={"apollo": {"monthly_credit_cap": 100, "per_run_credit_cap": 25},
                         "drafts": {"max_per_day": 0},
                         "accounts": {"min_days_between_touches": 30}},
                   state_path=tmp_path / "state.json")
    provider = ScriptedProvider([GOOD_DRAFT])
    result = draft_touch_one(ACCOUNT, provider=provider, gate=gate, firewall=firewall)
    assert result["status"] == "CAP_HALTED"
    assert provider.calls == 0


def test_unverified_numeric_claim_rejected(tmp_path, firewall):
    invented = GOOD_DRAFT.replace("20 to 70%", "20 to 70%") + "\nWe served 500 clients."
    provider = ScriptedProvider([invented, GOOD_DRAFT])
    result = draft_touch_one(ACCOUNT, provider=provider, gate=_gate(tmp_path),
                             firewall=firewall)
    assert result["status"] == "DRAFTED" and result["attempts"] == 2


GO = GoNoGoVerdict(verdict="GO", estimated_hours=4, fits_capacity=True,
                   deadline_days=25, reasons=["clean"])
NO_GO = GoNoGoVerdict(verdict="NO_GO", reasons=["bond"])

SOL = {"dedupe_key": "esbd:x", "title": "Cloud advisory services",
       "agency": "Test Agency", "notice_type": "Sources Sought",
       "due_date": "2026-08-20",
       "description": "The agency shall procure cloud cost optimization advisory. "
                      "Vendor must provide kubernetes expertise."}

GOOD_OUTLINE = """## Verdict
GO. Estimated 4 hours, fits capacity, no set-aside.

## Requirement-by-requirement outline
- Cloud cost optimization advisory: audit-first approach [smart_karpenter] [aws_psa]
- Kubernetes expertise: autoscaling redesign experience [smart_karpenter]

## Gaps (what Khavion cannot currently satisfy)
- No federal past performance of record yet.
- No public-sector references; first engagement would need a pilot framing."""

BAD_OUTLINE = """## Verdict
GO.

## Requirement-by-requirement outline
- Everything: we have done this for [mega_client_2019] with 100 agencies."""


def test_outline_runs_only_on_go(firewall):
    provider = ScriptedProvider([GOOD_OUTLINE])
    result = draft_outline(SOL, NO_GO, provider=provider, firewall=firewall)
    assert result["status"] == "SKIPPED"
    assert provider.calls == 0


def test_outline_rejects_invented_proof_then_succeeds(firewall):
    provider = ScriptedProvider([BAD_OUTLINE, GOOD_OUTLINE])
    result = draft_outline(SOL, GO, provider=provider, firewall=firewall)
    assert result["status"] == "DRAFTED"
    assert result["attempts"] == 2
    assert "## Gaps" in result["outline"]


def test_outline_requires_gap_section(firewall):
    no_gaps = GOOD_OUTLINE.split("## Gaps")[0]
    provider = ScriptedProvider([no_gaps, no_gaps, no_gaps])
    result = draft_outline(SOL, GO, provider=provider, firewall=firewall)
    assert result["status"] == "DRAFT_FAILED"
    assert any("Gaps" in p for p in result["problems"])
