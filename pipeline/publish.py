"""Publishing: the only place records leave the machine for Zoho.

Defense in depth: the firewall is re-checked here even though upstream
stages already enforced it — a blocklisted record must never reach a Zoho
API payload regardless of how it got this far. Dry-run never constructs a
Zoho client at all, so zero writes is structural, not behavioral.
"""

from __future__ import annotations

import logging

from pipeline.firewall import EmployerFirewall, get_firewall

log = logging.getLogger(__name__)


class PublishBlocked(Exception):
    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(f"publish blocked by employer firewall ({reason_code})")


def _record_block_for_account(account: dict, score: dict, draft: dict) -> dict:
    return {
        "kind": "prospect_account",
        "domain": account.get("domain"),
        "score_total": score.get("total"),
        "score_breakdown": score.get("criteria"),
        "hard_fails": score.get("hard_fails"),
        "rubric_version": score.get("rubric_version"),
        "triggers": account.get("triggers"),
        "source": "apollo",
        "fetched_at": str(account.get("fetched_at")),
        "draft_status": draft.get("status"),          # DRAFTED / NO_EMAIL / DRAFT_FAILED
        "draft_message_id": draft.get("message_id"),
        "draft_variant": draft.get("variant"),
        "draft_model": draft.get("model"),
        "suspicious_content": account.get("suspicious_content", False),
    }


def _record_block_for_solicitation(sol: dict, score: dict, verdict: dict,
                                   outline: dict | None) -> dict:
    return {
        "kind": "solicitation",
        "dedupe_key": sol.get("dedupe_key"),
        "source": sol.get("source_id"),
        "url": sol.get("url"),
        "score_total": score.get("total"),
        "score_breakdown": score.get("criteria"),
        "hard_fails": score.get("hard_fails"),
        "rubric_version": score.get("rubric_version"),
        "gonogo_verdict": verdict.get("verdict"),
        "gonogo_reasons": verdict.get("reasons"),
        "disqualifiers": verdict.get("disqualifiers"),
        "set_aside_text_verbatim": verdict.get("set_aside_text"),
        "incumbent": verdict.get("incumbent"),
        "estimated_hours": verdict.get("estimated_hours"),
        "deadline_days": verdict.get("deadline_days"),
        "classification": sol.get("classification"),
        "fetched_at": str(sol.get("fetched_at")),
        "outline_status": (outline or {}).get("status"),
        "suspicious_content": sol.get("suspicious_content", False),
    }


def publish_account(account: dict, score: dict, draft: dict,
                    crm=None, mail=None,
                    firewall: EmployerFirewall | None = None) -> dict:
    """CRM lead + (when a clean draft with an address exists) the Mail draft.
    Returns {crm_id, mail_message_id}."""
    firewall = firewall or get_firewall()
    code = (firewall.check_domain(account.get("domain"))
            or firewall.check_company(account.get("company_name")))
    if code:
        log.error("publish: account blocked by firewall (%s); nothing written", code)
        raise PublishBlocked(code)

    result: dict = {"crm_id": None, "mail_message_id": None}

    if draft.get("status") == "DRAFTED" and draft.get("to") and draft.get("body"):
        firewall.assert_clean(f"{draft.get('subject', '')}\n{draft['body']}",
                              stage="publish_mail_draft")
        if mail is not None:
            result["mail_message_id"] = mail.create_draft(
                draft["to"], draft.get("subject", ""), draft["body"])
            draft = {**draft, "message_id": result["mail_message_id"]}

    if crm is not None:
        block = _record_block_for_account(account, score, draft)
        result["crm_id"] = crm.upsert_lead(account, block)
    return result


def publish_solicitation(sol: dict, score: dict, verdict: dict,
                         outline: dict | None = None, crm=None,
                         firewall: EmployerFirewall | None = None) -> dict:
    firewall = firewall or get_firewall()
    code = firewall.check_company(sol.get("agency")) or firewall.check_text(
        sol.get("title", ""))
    if code:
        log.error("publish: solicitation blocked by firewall (%s); nothing written", code)
        raise PublishBlocked(code)

    result: dict = {"crm_id": None}
    if crm is not None:
        block = _record_block_for_solicitation(sol, score, verdict, outline)
        result["crm_id"] = crm.upsert_deal(sol, block)
    return result
