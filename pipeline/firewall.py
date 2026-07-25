"""Employer firewall: guardrail #1, as an importable check.

Nothing in this system stores, references, or transmits the employer's
customers, files, credentials, or performance figures. The machine-readable
edge of that rule is brain/blocklist.local.md (never committed, never shown
to any AI tool). Every content-generating function calls this module.

Reporting contract: pass/fail plus reason code ONLY. Blocklist contents are
never echoed to stdout, logs, prompts, LLM context, exceptions, or any API
payload. That is why FirewallViolation carries a reason code and a stage,
and deliberately not the matched text.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from pipeline.config import BRAIN_DIR

log = logging.getLogger(__name__)

BLOCKLIST_PATH = BRAIN_DIR / "blocklist.local.md"

REASON_CODES = {"EMPLOYER_ACCOUNT", "EMPLOYER_ADJACENT", "SUBSIDIARY_OF_BLOCKED", "PERSONAL"}


class FirewallViolation(Exception):
    def __init__(self, reason_code: str, stage: str):
        self.reason_code = reason_code
        self.stage = stage
        super().__init__(f"employer firewall violation ({reason_code}) at stage {stage}")


class EmployerFirewall:
    def __init__(self, blocklist_path: Path | None = None):
        self.path = blocklist_path or BLOCKLIST_PATH
        self._domains: dict[str, str] = {}
        self._companies: dict[str, str] = {}
        self.loaded = False
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            log.warning(
                "employer firewall: %s is MISSING - blocklist checks pass vacuously. "
                "Populate it before production (install.sh enforces this on the Mini).",
                self.path.name)
            return
        for line in self.path.read_text().splitlines():
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 3:
                continue
            domain, parent, code = cells[0].lower(), cells[1], cells[2].upper()
            if code not in REASON_CODES:
                continue  # header, separator, or malformed row
            if domain and domain != "example.com":
                self._domains[domain] = code
            if parent and parent.lower() not in ("", "example corp", "parent_company"):
                self._companies[parent.lower()] = code
        self.loaded = True
        log.info("employer firewall: blocklist loaded (%d domain rules, %d company rules)",
                 len(self._domains), len(self._companies))

    def check_domain(self, domain: str | None) -> str | None:
        """Returns the reason code if the domain (or a parent domain) is blocked."""
        if not domain:
            return None
        d = domain.lower().strip().rstrip(".")
        d = re.sub(r"^https?://", "", d).split("/")[0]
        for blocked, code in self._domains.items():
            if d == blocked or d.endswith("." + blocked):
                return code
        return None

    def check_company(self, name: str | None) -> str | None:
        if not name:
            return None
        lowered = name.lower()
        for blocked, code in self._companies.items():
            if len(blocked) >= 4 and blocked in lowered:
                return code
        return None

    def check_text(self, text: str) -> str | None:
        """Scan generated or outbound text for blocked domains/companies."""
        if not text:
            return None
        lowered = text.lower()
        for blocked, code in self._domains.items():
            if blocked in lowered:
                return code
        for blocked, code in self._companies.items():
            if len(blocked) >= 4 and blocked in lowered:
                return code
        return None

    def assert_clean(self, text: str, stage: str) -> None:
        code = self.check_text(text)
        if code:
            log.error("employer firewall: BLOCKED at stage %s (%s)", stage, code)
            raise FirewallViolation(code, stage)


_instance: EmployerFirewall | None = None


def get_firewall() -> EmployerFirewall:
    """Process-wide firewall instance, loaded lazily so tests can build their own."""
    global _instance
    if _instance is None:
        _instance = EmployerFirewall()
    return _instance
