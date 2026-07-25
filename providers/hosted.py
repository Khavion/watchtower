"""Hosted provider stub. INTENTIONALLY UNWIRED.

The local llama3.1:8b decision was made knowingly (quality tradeoff accepted).
If SAMPLE-DRAFTS.md convinces Zohaib to switch, implementing generate() here
and flipping `active: hosted` in config/providers.yaml is the entire change —
nothing else in the pipeline may need to know.
"""

from __future__ import annotations

from providers.base import Provider


class HostedProvider(Provider):
    def __init__(self, config: dict):
        self.config = config

    def generate(self, system: str, user: str, max_tokens: int) -> str:
        raise NotImplementedError(
            "hosted provider is intentionally unwired; implement generate() and "
            "set active: hosted in config/providers.yaml to switch")
