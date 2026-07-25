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

# No employer or partner names anywhere: as of the 2026-07-25 owner directive
# ("the work is the proof, not the logo") those are a mechanical violation.
GOOD_DRAFT = """Subject: your EKS spend

Ada, saw GoodCo closed a Series A last month. Post-raise cloud bills usually
jump before anyone owns them. My guess: your EKS nodes are over-provisioned
for the traffic you serve.

I run cloud cost work for funded B2B teams. Autoscaling redesign typically
lands 20 to 70% reductions on compute-heavy workloads. Happy to
pressure-test that guess on a free 30-minute architecture review. Worth a look?"""

BAD_DRAFT = """Subject: quick question

Hi Ada, I hope this finds you well! I wanted to reach out about our
cutting-edge, best-in-class AI solutions — we've helped 500 clients."""

# The old style: leaning on a recognizable employer for credibility.
NAME_DROPPING_DRAFT = """Subject: your EKS spend

Ada, your EKS nodes look over-provisioned. At AWS I ran partner architecture,
and Smart Karpenter with Avesha landed big reductions. Worth a look?"""


class ScriptedProvider(Provider):
    """Drafting is two passes: reply 1 feeds the freeform writer, replies 2+
    are the editor's rewrites. Only the editor's output is ever checked."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def generate(self, system, user, max_tokens, temperature=None):
        self.calls += 1
        return self.replies.pop(0) if self.replies else GOOD_DRAFT

    def model_info(self):
        return "qwen3.5:latest@testdigest"


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


def test_two_pass_structure_only_checks_the_edit_pass(tmp_path, firewall):
    """Pass one is allowed to be messy: it is thinking, not final text. Only the
    editor's output is checked, and pass one runs exactly once."""
    provider = ScriptedProvider([BAD_DRAFT, GOOD_DRAFT])
    result = draft_touch_one(ACCOUNT, provider=provider, gate=_gate(tmp_path),
                             firewall=firewall)
    assert result["status"] == "DRAFTED"
    assert result["attempts"] == 1, "the editor succeeded on its first rewrite"
    assert provider.calls == 2, "one freeform pass, one edit pass"
    assert result["to"] == "ada@goodco.com"
    assert result["model"] == "qwen3.5:latest@testdigest"


def test_editor_retries_then_succeeds(tmp_path, firewall):
    provider = ScriptedProvider([BAD_DRAFT, BAD_DRAFT, GOOD_DRAFT])
    result = draft_touch_one(ACCOUNT, provider=provider, gate=_gate(tmp_path),
                             firewall=firewall)
    assert result["status"] == "DRAFTED"
    assert result["attempts"] == 2


def test_draft_failed_after_three_bad_attempts(tmp_path, firewall):
    provider = ScriptedProvider([BAD_DRAFT, BAD_DRAFT, BAD_DRAFT, BAD_DRAFT])
    result = draft_touch_one(ACCOUNT, provider=provider, gate=_gate(tmp_path),
                             firewall=firewall)
    assert result["status"] == "DRAFT_FAILED"
    assert result["attempts"] == 3
    assert result["violations"]


def test_employer_names_are_rejected(tmp_path, firewall):
    """Owner directive 2026-07-25. Checked mechanically rather than asked for in
    the prompt, because a small model reaches for a recognizable name exactly
    when credibility is thin."""
    from pipeline.draft_outreach import org_name_check

    problems = org_name_check(NAME_DROPPING_DRAFT)
    assert any("aws" in p for p in problems)
    assert any("avesha" in p for p in problems)
    assert org_name_check(GOOD_DRAFT) == []

    provider = ScriptedProvider([NAME_DROPPING_DRAFT] * 4)
    result = draft_touch_one(ACCOUNT, provider=provider, gate=_gate(tmp_path),
                             firewall=firewall)
    assert result["status"] == "DRAFT_FAILED"


def test_approved_product_names_survive_the_employer_check():
    """"Amazon Bedrock" and "Azure OpenAI" are technologies he knows, not
    employers he is borrowing credibility from. The bare names still fail."""
    from pipeline.draft_outreach import org_name_check

    assert org_name_check("I have shipped Amazon Bedrock integrations.") == []
    assert org_name_check("Azure OpenAI in your own VPC.") == []
    assert org_name_check("Adjunct AI faculty at Houston City College.") == []
    assert org_name_check("I worked at Amazon for four years.")
    assert org_name_check("Back at Microsoft we did this.")


def test_draft_cap_halts(tmp_path, firewall):
    gate = CapGate(caps={"apollo": {"monthly_credit_cap": 100, "per_run_credit_cap": 25},
                         "drafts": {"max_per_day": 0},
                         "accounts": {"min_days_between_touches": 30}},
                   state_path=tmp_path / "state.json")
    provider = ScriptedProvider([GOOD_DRAFT])
    result = draft_touch_one(ACCOUNT, provider=provider, gate=gate, firewall=firewall)
    assert result["status"] == "CAP_HALTED"
    assert provider.calls == 0


def test_fabricated_hiring_claim_rejected_without_trigger(tmp_path, firewall):
    """No hiring trigger observed -> a draft claiming 'noticed you are hiring'
    must be rejected (added after live drafts invented job reqs)."""
    from pipeline.draft_outreach import fabrication_check
    no_trigger_account = {**ACCOUNT, "triggers": {}}
    fabricated = "Ada, noticed GoodCo is hiring a Cloud Engineer. My guess: ..."
    problems = fabrication_check(no_trigger_account, fabricated)
    assert any("hiring" in p for p in problems)
    # Funding language is equally off-limits without the funding trigger.
    assert fabrication_check(no_trigger_account, "saw GoodCo closed a Series A round")
    # With the trigger observed, the same language is fine.
    assert fabrication_check(ACCOUNT, "saw GoodCo closed a Series A round") == []


def test_invented_headcount_growth_is_a_fabrication(tmp_path, firewall):
    """Live regression, 2026-07-25: with no hiring trigger observed, a draft
    claimed "your recent influx of engineering headcount". The generic template
    line "new hires ship fast" is fine; a claim about THIS company is not."""
    from pipeline.draft_outreach import fabrication_check

    no_trigger = {**ACCOUNT, "triggers": {}}
    assert fabrication_check(
        no_trigger, "your recent influx of engineering headcount will hit this")
    assert fabrication_check(no_trigger, "with your headcount growth this compounds")
    assert fabrication_check(no_trigger, "your new hires will feel it")
    # The generic industry observation stays allowed: it is not about them.
    assert fabrication_check(
        no_trigger, "In growing teams, new hires ship fast and defaults stay stock.") == []


def test_industry_range_cannot_be_claimed_as_a_personal_result():
    """Live regression, 2026-07-25: "redesigning autoscaling to cut compute costs
    by up to seventy percent" turns a stated industry range into a claim Khavion
    cannot support."""
    from pipeline.draft_outreach import industry_range_check

    assert industry_range_check(
        "I specialize in redesigning autoscaling to cut compute costs by up to "
        "seventy percent.")
    assert industry_range_check("We reduced spend 40% for clients.")
    # Hedged, in the same sentence: allowed, because that is what it truly is.
    assert industry_range_check(
        "Autoscaling redesign typically lands a 20 to 70% reduction.") == []
    assert industry_range_check(
        "My guess: you are 30% over-provisioned for the traffic you serve.") == []


def test_editor_is_told_the_body_is_not_lowercase():
    """Live regression: the model applied the lowercase subject rule to the whole
    email body, which reads as careless."""
    from pipeline.draft_outreach import PASS_TWO_TEMPLATE

    assert "Only the subject line is" in PASS_TWO_TEMPLATE
    assert "normal sentence capitalization" in PASS_TWO_TEMPLATE.lower()


def test_all_lowercase_body_is_rejected():
    """Both candidate models did this during the A/B, so the prompt alone is not
    enough: it needs to be a check."""
    from pipeline.draft_outreach import _capitalisation_check

    assert _capitalisation_check(
        "patrick saw circuit closed a round. post-raise spend jumps. worth a look?")
    assert _capitalisation_check(
        "Patrick, saw Circuit closed a round. Post-raise spend jumps. Worth a look?") == []
    # A single short line is not evidence of anything either way.
    assert _capitalisation_check("worth a look?") == []


def test_no_trigger_account_gets_stack_instruction(tmp_path, firewall):
    from pipeline.draft_outreach import NO_TRIGGER_INSTRUCTION, _pick_variant, _sequence_block
    assert _pick_variant({**ACCOUNT, "triggers": {}}) is None
    assert _sequence_block(None) == NO_TRIGGER_INSTRUCTION
    assert _pick_variant(ACCOUNT) == "A"


def test_unverified_numeric_claim_rejected(tmp_path, firewall):
    invented = GOOD_DRAFT + "\nWe served 500 clients."
    provider = ScriptedProvider([GOOD_DRAFT, invented, GOOD_DRAFT])
    result = draft_touch_one(ACCOUNT, provider=provider, gate=_gate(tmp_path),
                             firewall=firewall)
    assert result["status"] == "DRAFTED" and result["attempts"] == 2


def test_style_exemplars_are_used_when_present(tmp_path, firewall, monkeypatch):
    """Five-shot voice matching is the single biggest free quality lever, so the
    exemplars must actually reach the writing pass, not just exist on disk."""
    from pipeline import brain

    brain.clear_cache()
    monkeypatch.setattr(brain, "style_exemplars",
                        lambda: ["Hey Sam. Short and blunt. Worth a look?"])
    provider = ScriptedProvider([GOOD_DRAFT, GOOD_DRAFT])
    draft_touch_one(ACCOUNT, provider=provider, gate=_gate(tmp_path), firewall=firewall)
    assert provider.calls == 2
    brain.clear_cache()


def test_style_exemplars_absent_is_survivable(tmp_path, firewall, caplog):
    """A fresh clone has no exemplars. That degrades voice matching; it must not
    break drafting, and it must say so out loud."""
    import logging

    with caplog.at_level(logging.WARNING):
        provider = ScriptedProvider([GOOD_DRAFT, GOOD_DRAFT])
        result = draft_touch_one(ACCOUNT, provider=provider, gate=_gate(tmp_path),
                                 firewall=firewall)
    assert result["status"] == "DRAFTED"
    assert any("style exemplars" in r.getMessage() for r in caplog.records)


def test_style_exemplars_are_firewall_scanned(tmp_path):
    """His own sent mail may well mention an employer account. That must never
    reach a model's context window."""
    from pipeline import brain, firewall as fw

    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    (brain_dir / "blocklist.local.md").write_text(BLOCKLIST)
    (brain_dir / brain.STYLE_EXEMPLARS_FILE).write_text(
        "Clean email about scheduling.\n---\nNote about blocked-corp.com renewal.")

    monkey = fw.EmployerFirewall(blocklist_path=brain_dir / "blocklist.local.md")
    fw._instance = monkey
    brain.clear_cache()
    try:
        exemplars = brain.style_exemplars(brain_dir=brain_dir)
        assert len(exemplars) == 1
        assert "blocked-corp" not in " ".join(exemplars)
    finally:
        fw.reset()
        brain.clear_cache()


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
- Cloud cost optimization advisory: audit-first approach [kubernetes_autoscaling] [solutions_architect_years]
- Kubernetes expertise: autoscaling redesign experience [kubernetes_autoscaling]

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
