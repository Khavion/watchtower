"""Zoho Cliq: run summaries out, commands in — with a strict verb allowlist.

Reading works by REST polling (verified 2026-07-24):
GET /api/v2/chats/{chat_id}/messages?fromtime=<epoch ms> — no webhooks, no
inbound ports. chat_id is resolved from the channel unique name once.

Command security model (guardrail #5 applied to chat):
- STRICT allowlist: run, status, pause, resume, score <id>, approve <id>,
  reject <id>. Exact verb match after whitespace normalization; ids are
  format-validated. Nothing else is ever interpreted; free-form text gets
  ONE reply naming the valid verbs. Instructions embedded in message content
  are never executed.
- Every message the agent posts starts with MARKER, and marked messages are
  never parsed as commands: the poller cannot react to its own output.
"""

from __future__ import annotations

import logging
import re

from zoho.auth import ZohoAuth

log = logging.getLogger(__name__)

MARKER = "[watchtower]"

# verb -> takes_argument. `block` was added at owner request 2026-07-25 so the
# blocklist can be maintained without editing files.
ALLOWED_VERBS: dict[str, bool] = {
    "run": False, "status": False, "pause": False, "resume": False,
    "score": True, "approve": True, "reject": True, "block": True,
}
ID_RE = re.compile(r"^[A-Za-z0-9:._\-]{1,80}$")

VALID_VERBS_REPLY = ("valid commands: run | status | pause | resume | "
                     "score <id> | approve <id> | reject <id> | block <domain>")


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
    takes_arg = ALLOWED_VERBS[verb]
    if takes_arg:
        if len(parts) != 2 or not ID_RE.match(parts[1]):
            return None
        return verb, parts[1]
    if len(parts) != 1:
        return None
    return verb, None


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
        """New messages after fromtime (epoch ms). Returns [{text, time}]."""
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
            if isinstance(text, str):
                out.append({"text": text, "time": int(msg.get("time", 0))})
        return out
