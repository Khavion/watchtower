"""Ollama provider: local llama3.1:8b over the loopback REST API.

Verified 2026-07-24: Ollama binds 127.0.0.1:11434 by default; POST /api/chat
takes {model, messages, stream, options{num_ctx, temperature, num_predict},
keep_alive} and returns {message: {content}}. The server default num_ctx is
4096, so we always pass ours explicitly.
"""

from __future__ import annotations

import logging

import requests

from providers.base import Provider, ProviderUnavailable

log = logging.getLogger(__name__)


class OllamaProvider(Provider):
    def __init__(self, config: dict):
        self.base_url = config.get("base_url", "http://127.0.0.1:11434").rstrip("/")
        self.model = config.get("model", "llama3.1:8b")
        self.num_ctx = int(config.get("num_ctx", 8192))
        self.temperature = float(config.get("temperature", 0.4))
        self.keep_alive = config.get("keep_alive", "10m")
        self.timeout = int(config.get("timeout_seconds", 180))
        self._model_info: str | None = None

    def generate(self, system: str, user: str, max_tokens: int) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"num_ctx": self.num_ctx,
                        "temperature": self.temperature,
                        "num_predict": max_tokens},
        }
        try:
            resp = requests.post(f"{self.base_url}/api/chat", json=payload,
                                 timeout=self.timeout)
        except requests.RequestException as exc:
            raise ProviderUnavailable(f"ollama unreachable at {self.base_url}: {exc}") from exc
        if resp.status_code != 200:
            raise ProviderUnavailable(
                f"ollama HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()["message"]["content"]
        except (ValueError, KeyError) as exc:
            raise ProviderUnavailable(f"ollama returned unexpected payload: {exc}") from exc

    def model_info(self) -> str:
        if self._model_info is None:
            digest = "unknown-digest"
            try:
                resp = requests.get(f"{self.base_url}/api/tags", timeout=10)
                for m in resp.json().get("models", []):
                    if m.get("name") == self.model:
                        digest = (m.get("digest") or digest)[:12]
                        break
            except (requests.RequestException, ValueError):
                pass
            self._model_info = f"{self.model}@{digest}"
        return self._model_info
