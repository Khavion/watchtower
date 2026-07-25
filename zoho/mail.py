"""Zoho Mail: creates finished outreach emails as DRAFTS in the Drafts folder.

Verified 2026-07-24: POST {mail_base}/api/accounts/{accountId}/messages with
"mode": "draft" saves to Drafts; fromAddress/toAddress/mode are mandatory;
no folderId involved. accountId and the valid fromAddress come from
GET /api/accounts.

THERE IS NO SEND PATH IN THIS MODULE. That is a design guarantee, not an
omission: nothing exists to call by accident. Zohaib reads the draft in
Zoho Mail and presses send himself.
"""

from __future__ import annotations

import logging

from zoho.auth import ZohoAuth

log = logging.getLogger(__name__)


class ZohoMailError(Exception):
    pass


class ZohoMail:
    def __init__(self, auth: ZohoAuth | None = None):
        self.auth = auth or ZohoAuth()
        self._account_id: str | None = None
        self._from_address: str | None = None

    def _base(self) -> str:
        return self.auth.endpoints["mail"]

    def _load_account(self) -> None:
        resp = self.auth.request("GET", f"{self._base()}/api/accounts",
                                 self.auth.mail_headers)
        if resp.status_code != 200:
            raise ZohoMailError(f"accounts lookup failed: HTTP {resp.status_code} "
                                f"{resp.text[:200]}")
        data = (resp.json().get("data") or [])
        if not data:
            raise ZohoMailError("no Zoho Mail account found for this user")
        self._account_id = str(data[0]["accountId"])
        send_details = data[0].get("sendMailDetails") or []
        self._from_address = (send_details[0].get("fromAddress")
                              if send_details else data[0].get("primaryEmailAddress"))
        log.info("mail: using accountId %s", self._account_id)

    def account_id(self) -> str:
        if not self._account_id:
            self._load_account()
        return self._account_id

    def from_address(self) -> str:
        if not self._from_address:
            self._load_account()
        return self._from_address

    def create_draft(self, to_address: str, subject: str, body: str) -> str | None:
        """Creates the draft, correctly addressed and ready to send. Returns the
        message id when the API reports one."""
        if not to_address:
            raise ZohoMailError("create_draft called without a recipient")
        payload = {
            "mode": "draft",
            "fromAddress": self.from_address(),
            "toAddress": to_address,
            "subject": subject,
            "content": body.replace("\n", "<br>"),
            "mailFormat": "html",
        }
        resp = self.auth.request(
            "POST", f"{self._base()}/api/accounts/{self.account_id()}/messages",
            self.auth.mail_headers, json=payload)
        if resp.status_code not in (200, 201):
            raise ZohoMailError(f"draft creation failed: HTTP {resp.status_code} "
                                f"{resp.text[:200]}")
        try:
            data = resp.json().get("data") or {}
            message_id = str(data.get("messageId") or data.get("messageId", "")) or None
        except ValueError:
            message_id = None
        log.info("mail: draft created for %s (%r)", to_address, subject)
        return message_id
