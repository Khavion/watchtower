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

import json
import logging
from urllib.parse import quote

from zoho.auth import ZohoAuth

log = logging.getLogger(__name__)


class ZohoCRMError(Exception):
    pass


def description_block(payload: dict) -> str:
    """Human-readable summary first (that is what the CRM card shows), then the
    machine-regular block."""
    lines = []
    if payload.get("score_total") is not None:
        lines.append(f"SCORE {payload['score_total']}/100 "
                     f"(rubric {payload.get('rubric_version', '?')})")
    if payload.get("gonogo_verdict"):
        lines.append(f"GO/NO-GO: {payload['gonogo_verdict']}")
    if payload.get("triggers"):
        lines.append("Triggers: " + "; ".join(
            f"{k}: {v}" for k, v in payload["triggers"].items()))
    if payload.get("draft_status"):
        lines.append(f"Outreach draft: {payload['draft_status']} "
                     "(sending is always manual, in Zoho Mail)")
    if payload.get("hard_fails"):
        lines.append("Hard fails: " + ", ".join(payload["hard_fails"]))
    header = "\n".join(lines)
    return (header + "\n\n--- watchtower record (do not edit below) ---\n"
            + json.dumps(payload, indent=2, sort_keys=True, default=str)[:29000])


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
            "Description": description_block(record_block),
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
        fields = {
            "Deal_Name": deal_name,
            # Neutral first stage; nothing here may imply submission.
            "Stage": "Qualification",
            "Description": description_block(record_block),
        }
        if closing:
            fields["Closing_Date"] = closing
        resp = self.auth.request(
            "POST", self._url("Deals/upsert"), self.auth.crm_headers,
            json={"data": [fields], "duplicate_check_fields": ["Deal_Name"]})
        payload = self._check(resp, "deal upsert")
        entry = payload["data"][0]
        if entry.get("code") != "SUCCESS":
            raise ZohoCRMError(f"deal upsert rejected: {str(entry)[:300]}")
        rec_id = str(entry["details"]["id"])
        log.info("crm: deal %s for %s", entry.get("action", "upserted"),
                 sol.get("dedupe_key"))
        return rec_id
