"""Zoho CRM records (v8 API, Free edition constraints).

Free edition has no custom fields or modules, so:
- Outbound prospects -> Leads, deduped on the account DOMAIN via a criteria
  search on Website (the system dedupe field, Email, may be unrevealed yet).
- Solicitations -> Deals, deduped on Deal_Name via the upsert endpoint
  (Deal_Name is the system duplicate-check field for Deals).
- Score, per-criterion breakdown, rubric version, source, fetch timestamp,
  and the draft link/status travel in Description as a fenced block.

Rule enforced by construction: no field ever states or implies that anything
was sent or submitted. Deals are always created at Stage "Qualification";
draft status vocabulary is DRAFTED/NO_EMAIL/DRAFT_FAILED, never "sent".
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from zoho.auth import ZohoAuth

log = logging.getLogger(__name__)


class ZohoCRMError(Exception):
    pass


# CRM text is read by a non-technical VA: plain short English, no JSON, no
# jargon. The machine-readable record lives in data/ on the machine; the CRM
# never needs it.

CRITERIA_PLAIN = {
    "icp_fit": "company fit",
    "cloud_footprint": "cloud usage",
    "trigger_recency": "recent buying signal",
    "buyer_seniority": "contact's seniority",
    "contactability": "email quality",
    "capability_match": "match to what Khavion sells",
    "notice_type_fit": "type of notice",
    "timeline_runway": "time to respond",
    "agency_fit": "agency fit",
}

HARD_FAIL_PLAIN = {
    "blocklist_hit": "this company is on the do-not-contact list",
    "headcount_out_of_range": "company size is outside 20-200 people",
    "no_reachable_buyer": "no reachable decision-maker",
    "out_of_scope_boundaries": "asks for work Khavion does not sell",
    "requires_onsite": "requires on-site work",
    "requires_w2": "requires W-2 employment",
    "requires_unheld_certification": "requires a certification Khavion does not hold",
}

DISQUALIFIER_PLAIN = {
    "bonding": "a bond is required",
    "insurance_minimum": "an insurance minimum is required",
    "years_in_business": "requires more years in business",
    "past_performance": "requires past performance references",
    "onsite_required": "on-site work is required",
    "w2_required": "W-2 employment is required",
    "unheld_certification": "requires a certification Khavion does not hold",
    "prebid_conference_passed": "the pre-bid meeting already happened",
    "deadline_too_close": "the deadline is too close",
    "not_yet_eligible": "needs federal past performance Khavion does not have yet",
}

DRAFT_STATUS_PLAIN = {
    "DRAFTED": "An email draft is waiting in Zoho Mail Drafts. Nothing was sent.",
    "NO_EMAIL": "No email address found yet, so no draft was written.",
    "BELOW_THRESHOLD": "Score too low for an email draft.",
    "DRAFT_FAILED": "The draft failed quality checks, so none was saved.",
    "BLOCKED": "On the do-not-contact list. No draft.",
    "CAP_HALTED": "Daily draft limit reached; will draft on a later run.",
    "PROVIDER_DOWN": "Drafting tool was offline; will retry on a later run.",
}


def _strengths_weaknesses(breakdown: dict | None) -> str:
    if not breakdown:
        return ""
    strong = [CRITERIA_PLAIN.get(k, k) for k, v in breakdown.items()
              if v.get("criterion_score", 0) >= 70]
    weak = [CRITERIA_PLAIN.get(k, k) for k, v in breakdown.items()
            if v.get("criterion_score", 0) <= 30]
    parts = []
    if strong:
        parts.append("Strong: " + ", ".join(strong) + ".")
    if weak:
        parts.append("Weak: " + ", ".join(weak) + ".")
    return " ".join(parts)


def lead_description(block: dict) -> str:
    lines = [f"Score: {block.get('score_total', '?')} out of 100."]
    sw = _strengths_weaknesses(block.get("score_breakdown"))
    if sw:
        lines.append(sw)
    for reason in block.get("hard_fails") or []:
        lines.append("Do not contact: " + HARD_FAIL_PLAIN.get(reason, reason) + ".")
    for detail in (block.get("triggers") or {}).values():
        lines.append(f"Buying signal: {detail}.")
    if not block.get("triggers"):
        lines.append("No recent buying signal; picked for company fit and cloud usage.")
    status = block.get("draft_status")
    if status:
        lines.append(DRAFT_STATUS_PLAIN.get(status, status))
    fetched = str(block.get("fetched_at") or "")[:10]
    lines.append(f"Found by watchtower via Apollo on {fetched}.")
    return "\n".join(lines)


def deal_description(block: dict) -> str:
    verdict = block.get("gonogo_verdict")
    lines = []
    if verdict == "GO":
        lines.append("Decision: GO. Worth responding.")
    elif verdict == "NO_GO":
        lines.append("Decision: NO GO. Skip this one.")
    elif verdict == "NEEDS_HUMAN":
        lines.append("Decision: NEEDS ZOHAIB. He must read this one himself.")
    for d in block.get("disqualifiers") or []:
        kind = d.get("kind") if isinstance(d, dict) else getattr(d, "kind", "")
        quote = d.get("requirement_quote") if isinstance(d, dict) else getattr(d, "requirement_quote", "")
        lines.append(f"Deal-breaker: {DISQUALIFIER_PLAIN.get(kind, kind)}. "
                     f"The document says: \"{quote}\"")
    if block.get("set_aside_text_verbatim"):
        lines.append("Set-aside language found (Zohaib must judge this): "
                     f"\"{block['set_aside_text_verbatim']}\"")
    if block.get("incumbent"):
        lines.append(f"Current contract holder: {block['incumbent']}.")
    hours = block.get("estimated_hours")
    days = block.get("deadline_days")
    if hours or days is not None:
        bits = []
        if hours:
            bits.append(f"about {int(hours)} hours of work to respond")
        if days is not None:
            bits.append(f"due in {days} days")
        lines.append(("Effort: " + ", ".join(bits) + ".").capitalize())
    lines.append(f"Score: {block.get('score_total', '?')} out of 100.")
    sw = _strengths_weaknesses(block.get("score_breakdown"))
    if sw:
        lines.append(sw)
    source = {"esbd": "Texas ESBD", "sam_gov": "SAM.gov",
              "university_boards": "Texas university boards"}.get(
        block.get("source"), block.get("source") or "")
    link = block.get("url") or ""
    lines.append(f"From {source}. {link}".strip())
    lines.append("Nothing has been submitted.")
    return "\n".join(lines)


class ZohoCRM:
    def __init__(self, auth: ZohoAuth | None = None):
        self.auth = auth or ZohoAuth()

    def _url(self, path: str) -> str:
        return f"{self.auth.api_domain}/crm/v8/{path}"

    def _check(self, resp, action: str) -> dict:
        if resp.status_code == 204:
            return {}
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if resp.status_code >= 400:
            raise ZohoCRMError(f"{action}: HTTP {resp.status_code} {str(payload)[:300]}")
        return payload

    # ----- Leads (prospect accounts, dedupe on domain via Website) -----

    def find_lead_by_domain(self, domain: str) -> str | None:
        criteria = quote(f"(Website:equals:{domain})", safe="():")
        resp = self.auth.request(
            "GET", self._url(f"Leads/search?criteria={criteria}"), self.auth.crm_headers)
        payload = self._check(resp, "lead search")
        data = payload.get("data") or []
        return str(data[0]["id"]) if data else None

    def _write_lead(self, fields: dict, existing_id: str | None) -> str:
        """Insert or update. Zoho picklists vary per org; when it rejects one
        field (INVALID_DATA with details.api_name) we drop that field and retry
        so a strict picklist never sinks the whole record."""
        max_drops = 4
        for attempt in range(max_drops + 1):
            if existing_id:
                resp = self.auth.request("PUT", self._url("Leads"), self.auth.crm_headers,
                                         json={"data": [{"id": existing_id, **fields}]})
            else:
                resp = self.auth.request("POST", self._url("Leads"), self.auth.crm_headers,
                                         json={"data": [fields]})
            try:
                entry = (resp.json().get("data") or [{}])[0]
            except (ValueError, AttributeError):
                entry = {}
            if resp.status_code < 400 and entry.get("code") in (None, "SUCCESS"):
                return existing_id or str(entry["details"]["id"])
            bad = (entry.get("details") or {}).get("api_name")
            if attempt < max_drops and bad and bad in fields and bad != "Last_Name":
                log.warning("crm: Zoho rejected field %s (%s); retrying without it",
                            bad, entry.get("code"))
                fields = {k: v for k, v in fields.items() if k != bad}
                continue
            raise ZohoCRMError(f"lead write rejected (HTTP {resp.status_code}): "
                               f"{str(entry)[:300]}")
        raise ZohoCRMError("lead write failed after dropping rejected fields")

    def upsert_lead(self, account: dict, record_block: dict) -> str:
        buyer = (account.get("buyer_name") or "Unknown Buyer").split()
        fields = {
            "Company": account.get("company_name") or account.get("domain"),
            "Last_Name": buyer[-1] if buyer else "Unknown",
            "First_Name": " ".join(buyer[:-1]) if len(buyer) > 1 else None,
            "Designation": account.get("buyer_title"),
            "Website": account.get("domain"),
            "Email": account.get("buyer_email"),
            "Industry": account.get("industry"),
            "No_of_Employees": account.get("employee_count"),
            "Annual_Revenue": account.get("annual_revenue"),
            "Phone": account.get("org_phone"),
            "City": account.get("city"),
            "State": account.get("state"),
            "Lead_Source": "Khavion watchtower",
            "Description": lead_description(record_block),
        }
        fields = {k: v for k, v in fields.items() if v not in (None, "")}

        existing = self.find_lead_by_domain(account.get("domain", ""))
        if existing is None:
            # Factually true at creation (nothing auto-sends, ever) and never
            # touched on update so Zohaib's manual status edits survive.
            fields["Lead_Status"] = "Not Contacted"
        rec_id = self._write_lead(fields, existing)
        log.info("crm: lead %s for %s", "updated" if existing else "created",
                 account.get("domain"))
        return rec_id

    # ----- Deals (solicitations, dedupe on Deal_Name) -----

    def upsert_deal(self, sol: dict, record_block: dict) -> str:
        deal_name = f"[{sol.get('dedupe_key')}] {sol.get('title', '')}"[:120]
        closing = str(sol.get("due_date") or "")[:10] or None
        verdict = record_block.get("gonogo_verdict")
        next_step = {
            "GO": "Zohaib: review and decide",
            "NO_GO": "Skip (see description)",
            "NEEDS_HUMAN": "Zohaib: read the description",
        }.get(verdict, "Review")
        fields = {
            "Deal_Name": deal_name,
            # Neutral first stage; nothing here may imply submission.
            "Stage": "Qualification",
            "Next_Step": next_step[:100],
            "Type": "New Business",
            "Lead_Source": "Khavion watchtower",
            "Description": deal_description(record_block),
        }
        if closing:
            fields["Closing_Date"] = closing

        # Same drop-rejected-field retry as leads: org picklists vary.
        for attempt in range(4):
            resp = self.auth.request(
                "POST", self._url("Deals/upsert"), self.auth.crm_headers,
                json={"data": [fields], "duplicate_check_fields": ["Deal_Name"]})
            try:
                entry = (resp.json().get("data") or [{}])[0]
            except (ValueError, AttributeError):
                entry = {}
            if resp.status_code < 400 and entry.get("code") == "SUCCESS":
                rec_id = str(entry["details"]["id"])
                log.info("crm: deal %s for %s", entry.get("action", "upserted"),
                         sol.get("dedupe_key"))
                return rec_id
            bad = (entry.get("details") or {}).get("api_name")
            if attempt < 3 and bad and bad in fields and bad not in ("Deal_Name", "Stage"):
                log.warning("crm: Zoho rejected deal field %s; retrying without it", bad)
                fields = {k: v for k, v in fields.items() if k != bad}
                continue
            raise ZohoCRMError(f"deal upsert rejected (HTTP {resp.status_code}): "
                               f"{str(entry)[:300]}")
        raise ZohoCRMError("deal upsert failed after dropping rejected fields")
