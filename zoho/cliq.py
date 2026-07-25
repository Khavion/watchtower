"""Zoho Cliq: run summaries out, commands in — with a strict verb allowlist.

Reading works by REST polling (verified 2026-07-24):
GET /api/v2/chats/{chat_id}/messages?fromtime=<epoch ms> — no webhooks, no
inbound ports. chat_id is resolved from the channel unique name once.

Command security model (guardrail #4 applied to chat):
- STRICT allowlist. Exact verb match after whitespace normalization; ids are
  format-validated. Nothing else is ever interpreted; free-form text gets ONE
  reply naming the valid verbs. Instructions embedded in message content are
  never executed.
- Every message the agent posts starts with MARKER, and marked messages are
  never parsed as commands: the poller cannot react to its own output.
- `note` is the one verb that takes free text. That text is STORED, never
  interpreted: it goes into the notes table as raw material for the marketing
  writer, wrapped as data like any other untrusted input. A verb that stores
  is safe in a way a verb that acts would not be.
- OWNER-ONLY verbs (2026-07-25): the VA can run everything except `block`,
  which edits the employer firewall. Sender identity comes from Cliq itself,
  not from anything typed in the message.
"""

from __future__ import annotations

import logging
import re

from zoho.auth import ZohoAuth

log = logging.getLogger(__name__)

MARKER = "[watchtower]"

# verb -> (takes_argument, free_text, owner_only)
ALLOWED_VERBS: dict[str, tuple[bool, bool, bool]] = {
    "run":      (False, False, False),
    "status":   (False, False, False),
    "pause":    (False, False, False),
    "resume":   (False, False, False),
    "agents":   (False, False, False),
    "brief":    (False, False, False),
    "triage":   (False, False, False),
    "write":    (False, False, False),
    "score":    (True,  False, False),
    "approve":  (True,  False, False),
    "reject":   (True,  False, False),
    "proposal": (True,  False, False),
    "note":     (True,  True,  False),
    # Editing the employer firewall is Zohaib's alone. The VA has no reason to
    # touch it and a mistake here is invisible by design.
    "block":    (True,  False, True),
}

ID_RE = re.compile(r"^[A-Za-z0-9:._\-]{1,80}$")
MAX_NOTE_CHARS = 2000

VALID_VERBS_REPLY = (
    "valid commands: run | status | pause | resume | agents | brief | triage | "
    "write | score <id> | approve <id> | reject <id> | proposal <id> | "
    "note <anything> | block <domain>")


def parse_command(text: str) -> tuple[str, str | None] | None:
    """Strict parser. Returns (verb, arg) or None. None means 'not a command':
    the caller replies once with the valid verbs and does nothing else."""
    if not text:
        return None
    cleaned = " ".join(text.strip().split())
    if cleaned.startswith(MARKER):
        return None  # our own output, never a command
    parts = cleaned.split(" ")
    verb = parts[0].lower()
    if verb not in ALLOWED_VERBS:
        return None
    takes_arg, free_text, _ = ALLOWED_VERBS[verb]

    if not takes_arg:
        return (verb, None) if len(parts) == 1 else None

    if free_text:
        # Everything after the verb, kept verbatim as data. Length-capped so a
        # pasted document cannot become a note.
        rest = cleaned[len(parts[0]):].strip()
        return (verb, rest[:MAX_NOTE_CHARS]) if rest else None

    if len(parts) != 2 or not ID_RE.match(parts[1]):
        return None
    return verb, parts[1]


def is_owner_only(verb: str) -> bool:
    entry = ALLOWED_VERBS.get(verb)
    return bool(entry and entry[2])


class ZohoCliq:
    def __init__(self, auth: ZohoAuth | None = None,
                 channel_unique_name: str = "khavionagent"):
        self.auth = auth or ZohoAuth()
        self.channel_unique_name = channel_unique_name
        self._chat_id: str | None = None

    def _base(self) -> str:
        return self.auth.endpoints["cliq"]

    def post(self, text: str) -> None:
        """Post a run summary/reply. Always marked so the poller ignores it."""
        message = text if text.startswith(MARKER) else f"{MARKER} {text}"
        resp = self.auth.request(
            "POST",
            f"{self._base()}/api/v2/channelsbyname/{self.channel_unique_name}/message",
            self.auth.cliq_headers, json={"text": message[:4900]})
        if resp.status_code >= 400:
            log.error("cliq: post failed HTTP %d %s", resp.status_code, resp.text[:150])

    def owner_id(self) -> str | None:
        """The Cliq user id of whoever owns the OAuth token, i.e. Zohaib.

        Derived from the token rather than configured, so he never has to find a
        user id anywhere. Owner-only verbs FAIL CLOSED: if this returns None,
        the firewall-editing command is refused rather than allowed, because an
        unnoticed wrong answer here is exactly the failure that matters."""
        resp = self.auth.request("GET", f"{self._base()}/api/v2/users/me",
                                 self.auth.cliq_headers)
        if resp.status_code != 200:
            log.warning("cliq: could not resolve the token owner (HTTP %d); "
                        "owner-only commands will be refused", resp.status_code)
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        # Zoho wraps single objects inconsistently across products.
        if isinstance(data, dict):
            payload = data.get("data") if isinstance(data.get("data"), dict) else data
            value = payload.get("id") or payload.get("zuid") or payload.get("user_id")
            return str(value) if value else None
        return None

    def chat_id(self) -> str | None:
        if self._chat_id:
            return self._chat_id
        resp = self.auth.request("GET", f"{self._base()}/api/v2/channels",
                                 self.auth.cliq_headers, params={"limit": 100})
        if resp.status_code != 200:
            log.error("cliq: channel list failed HTTP %d", resp.status_code)
            return None
        for channel in resp.json().get("channels", []):
            if channel.get("unique_name") == self.channel_unique_name:
                self._chat_id = channel.get("chat_id")
                return self._chat_id
        log.warning("cliq: channel %r not found; create it in Cliq",
                    self.channel_unique_name)
        return None

    def fetch_messages(self, fromtime_ms: int) -> list[dict]:
        """New messages after fromtime (epoch ms).

        Returns [{text, time, sender_id}]. sender_id comes from Cliq's own
        payload, never from message content, which is what makes owner-only
        verbs meaningful: it cannot be spoofed by typing something."""
        chat = self.chat_id()
        if not chat:
            return []
        resp = self.auth.request(
            "GET", f"{self._base()}/api/v2/chats/{chat}/messages",
            self.auth.cliq_headers,
            params={"fromtime": fromtime_ms, "limit": 100})
        if resp.status_code != 200:
            log.error("cliq: fetch messages failed HTTP %d", resp.status_code)
            return []
        out = []
        for msg in resp.json().get("data", []):
            content = msg.get("content")
            text = content.get("text") if isinstance(content, dict) else content
            if not isinstance(text, str):
                continue
            sender = msg.get("sender") or {}
            out.append({
                "text": text,
                "time": int(msg.get("time", 0)),
                "sender_id": str(sender.get("id") or "") if isinstance(sender, dict) else "",
                "sender_name": str(sender.get("name") or "") if isinstance(sender, dict) else "",
            })
        return out
