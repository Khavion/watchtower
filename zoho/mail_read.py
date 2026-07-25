"""Zoho Mail, READ side. Lists folders and messages and fetches message bodies.

Separate module from zoho/mail.py on purpose. mail.py contains the draft-writing
path and, by construction, no send function; keeping reading out of it means
that guarantee stays easy to verify by opening one short file.

THERE IS STILL NO SEND PATH ANYWHERE. Triage reads and drafts replies; Zohaib
presses send in Zoho Mail. Zoho's free plan has no SMTP and their usage policy
bans automated sending, so this is a technical fact as much as a policy.

Scopes required (added to the grant line 2026-07-25):
    ZohoMail.messages.READ, ZohoMail.folders.READ
"""

from __future__ import annotations

import html
import logging
import re

from zoho.auth import ZohoAuth

log = logging.getLogger(__name__)


class ZohoMailReadError(Exception):
    pass


_TAG_RE = re.compile(r"<[^>]+>")
_QUOTED_RE = re.compile(
    r"(?:^-{2,}\s*original message|^on .{0,80}wrote:|^from:\s|^_{5,}|^>{1,})",
    re.IGNORECASE | re.MULTILINE)


def to_plain_text(content: str, drop_quoted: bool = True) -> str:
    """HTML to readable text, and optionally cut the quoted reply chain.

    Quoted history is dropped before anything reaches a model: it is mostly
    someone else's words, it eats the context window, and on a 16 GB machine
    context is the scarcest thing there is."""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", content or "")
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()
    if drop_quoted:
        match = _QUOTED_RE.search(text)
        if match and match.start() > 0:
            text = text[:match.start()].strip()
    return text


class ZohoMailReader:
    def __init__(self, auth: ZohoAuth | None = None):
        self.auth = auth or ZohoAuth()
        self._account_id: str | None = None
        self._folders: dict[str, str] | None = None

    def _base(self) -> str:
        return self.auth.endpoints["mail"]

    def _get(self, path: str, **params):
        resp = self.auth.request("GET", f"{self._base()}{path}",
                                 self.auth.mail_headers, params=params or None)
        if resp.status_code == 403:
            raise ZohoMailReadError(
                "Zoho refused a mail read (HTTP 403). The access token predates the "
                "mail-read scopes; re-run deploy/setup_credentials.py zoho with the "
                "scope line it prints.")
        if resp.status_code != 200:
            raise ZohoMailReadError(f"GET {path} failed: HTTP {resp.status_code} "
                                    f"{resp.text[:200]}")
        try:
            return resp.json().get("data")
        except ValueError as exc:
            raise ZohoMailReadError(f"GET {path} returned non-JSON") from exc

    def account_id(self) -> str:
        if not self._account_id:
            data = self._get("/api/accounts")
            if not data:
                raise ZohoMailReadError("no Zoho Mail account found for this user")
            self._account_id = str(data[0]["accountId"])
        return self._account_id

    def folders(self) -> dict[str, str]:
        """{lowercased folder name: folderId}."""
        if self._folders is None:
            data = self._get(f"/api/accounts/{self.account_id()}/folders") or []
            self._folders = {str(f.get("folderName", "")).lower(): str(f.get("folderId"))
                             for f in data if f.get("folderId")}
        return self._folders

    def folder_id(self, name: str) -> str | None:
        return self.folders().get(name.lower())

    def list_messages(self, folder: str = "inbox", limit: int = 25,
                      unread_only: bool = False) -> list[dict]:
        """Message headers, newest first. Bodies are fetched separately so a
        listing costs one call regardless of how many messages come back."""
        fid = self.folder_id(folder)
        if not fid:
            log.warning("mail_read: no folder named %r (have: %s)",
                        folder, ", ".join(sorted(self.folders()))[:200])
            return []
        params = {"folderId": fid, "limit": max(1, min(int(limit), 200)), "start": 1}
        if unread_only:
            params["status"] = "unread"
        data = self._get(f"/api/accounts/{self.account_id()}/messages/view",
                         **params) or []
        out = []
        for m in data:
            out.append({
                "message_id": str(m.get("messageId")),
                "folder_id": str(m.get("folderId") or fid),
                "subject": m.get("subject") or "(no subject)",
                "from": m.get("fromAddress") or m.get("sender") or "",
                "to": m.get("toAddress") or "",
                "received_at": m.get("receivedTime") or m.get("sentDateInGMT") or "",
                "has_attachment": bool(m.get("hasAttachment")),
                "unread": str(m.get("status")) == "0" or m.get("isUnread") is True,
            })
        return out

    def message_body(self, message: dict, max_chars: int = 6000) -> str:
        """Plain-text body for one message, quoted history removed."""
        try:
            data = self._get(
                f"/api/accounts/{self.account_id()}/folders/"
                f"{message['folder_id']}/messages/{message['message_id']}/content")
        except ZohoMailReadError as exc:
            log.warning("mail_read: body fetch failed for %s (%s)",
                        message.get("subject", "")[:60], exc)
            return ""
        content = (data or {}).get("content") if isinstance(data, dict) else None
        return to_plain_text(content or "")[:max_chars]

    def sent_messages_with_bodies(self, limit: int = 15) -> list[dict]:
        """Zohaib's own sent mail: the source of the style exemplars."""
        folder = "sent" if self.folder_id("sent") else "sent items"
        out = []
        for msg in self.list_messages(folder=folder, limit=limit):
            body = self.message_body(msg)
            if body:
                out.append({**msg, "body": body})
        return out
