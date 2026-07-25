"""Ollama provider: the local workhorse model over the loopback REST API.

Verified 2026-07-24: Ollama binds 127.0.0.1:11434 by default; POST /api/chat
takes {model, messages, stream, options{num_ctx, temperature, num_predict},
keep_alive} and returns {message: {content}}.

Verified 2026-07-25 on the Mac Mini (Ollama 0.31.1, qwen3.5 9.7B Q4_K_M):

- The server default num_ctx is 4096 regardless of what the model advertises,
  so we ALWAYS pass ours explicitly. Long solicitations were being silently
  truncated before the model ever saw them.
- The workhorse model has a thinking mode. Left on, its reasoning arrives in a
  separate `thinking` field and, on some prompts, leaks into `content`. We send
  `think: false` and additionally strip any <think> block defensively, because
  a reasoning trace inside a cold email is a quality failure the voice checker
  would not necessarily catch.
- `format` accepts a real JSON Schema and constrains decoding to match it. That
  is how classification gets a parseable verdict instead of a regex guess.
"""

from __future__ import annotations

import json
import logging
import re

import requests

from providers.base import Provider, ProviderUnavailable

log = logging.getLogger(__name__)

# Defensive: strip a reasoning block if a future model emits one inline despite
# think=false. Non-greedy, tolerant of an unterminated block at end of output.
_THINK_RE = re.compile(r"<think>.*?(?:</think>|\Z)", re.DOTALL | re.IGNORECASE)


def strip_thinking(text: str) -> str:
    return _THINK_RE.sub("", text or "").strip()


class OllamaProvider(Provider):
    def __init__(self, config: dict):
        self.base_url = config.get("base_url", "http://127.0.0.1:11434").rstrip("/")
        self.model = config.get("model", "qwen3.5:latest")
        self.num_ctx = int(config.get("num_ctx", 16384))
        self.temperature = float(config.get("temperature", 0.4))
        self.keep_alive = config.get("keep_alive", "24h")
        self.timeout = int(config.get("timeout_seconds", 300))
        self.think = bool(config.get("think", False))
        self._model_info: str | None = None

    def _chat(self, system: str, user: str, max_tokens: int,
              temperature: float | None = None,
              schema: dict | None = None) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "stream": False,
            "think": self.think,
            "keep_alive": self.keep_alive,
            "options": {
                "num_ctx": self.num_ctx,
                "temperature": self.temperature if temperature is None else temperature,
                "num_predict": max_tokens,
            },
        }
        if schema is not None:
            payload["format"] = schema
        try:
            resp = requests.post(f"{self.base_url}/api/chat", json=payload,
                                 timeout=self.timeout)
        except requests.RequestException as exc:
            raise ProviderUnavailable(f"ollama unreachable at {self.base_url}: {exc}") from exc
        if resp.status_code != 200:
            raise ProviderUnavailable(
                f"ollama HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return strip_thinking(resp.json()["message"]["content"])
        except (ValueError, KeyError) as exc:
            raise ProviderUnavailable(f"ollama returned unexpected payload: {exc}") from exc

    def generate(self, system: str, user: str, max_tokens: int,
                 temperature: float | None = None) -> str:
        return self._chat(system, user, max_tokens, temperature=temperature)

    def generate_json(self, system: str, user: str, schema: dict,
                      max_tokens: int = 400, temperature: float = 0.0) -> dict:
        """Schema-constrained generation. Decoding itself is constrained, so the
        result parses or the provider is genuinely broken -- there is no
        'guess from the prose' fallback, by design."""
        raw = self._chat(system, user, max_tokens, temperature=temperature,
                         schema=schema)
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise ProviderUnavailable(
                f"ollama returned non-JSON under a schema constraint: {raw[:200]!r}") from exc

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
