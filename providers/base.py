"""LLM provider abstraction. Exactly one interface; switching providers means
changing `active` in config/providers.yaml and nothing else."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ProviderUnavailable(Exception):
    """The provider cannot be reached (e.g. Ollama daemon down). Callers mark
    work UNCLASSIFIED/DRAFT_FAILED and continue; they never improvise."""


class Provider(ABC):
    @abstractmethod
    def generate(self, system: str, user: str, max_tokens: int) -> str:
        ...

    def model_info(self) -> str:
        """Model name + version/digest, logged with every decision."""
        return "unknown"


def get_provider(config: dict | None = None) -> Provider:
    if config is None:
        from pipeline.config import providers as load_providers
        config = load_providers()
    active = config.get("active", "ollama")
    if active == "ollama":
        from providers.ollama import OllamaProvider
        return OllamaProvider(config.get("ollama", {}))
    if active == "hosted":
        from providers.hosted import HostedProvider
        return HostedProvider(config.get("hosted", {}))
    raise ValueError(f"unknown provider {active!r} in providers.yaml")
