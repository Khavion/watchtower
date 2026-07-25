"""Source adapter contract + polite HTTP session.

Every adapter implements fetch() -> list[RawSolicitation], carries a stable
source_id, and produces dedupe keys. Adapters are independent: one raising
must never stop the others (run_all guarantees it).
"""

from __future__ import annotations

import logging
import time
import traceback
from abc import ABC, abstractmethod

import requests

from pipeline.models import RawSolicitation

log = logging.getLogger(__name__)


class SourceError(Exception):
    """Raised by adapters for unrecoverable per-source failures."""


class RequestBudgetExceeded(SourceError):
    """The per-run HTTP request budget for this source was hit. Halt, never degrade silently."""


class PoliteSession:
    """requests.Session wrapper enforcing the documented politeness contract:
    real identifying User-Agent, minimum interval between requests, bounded
    retries with exponential backoff, and a hard per-run request budget.

    An optional shared `page_cache` (url+params -> text) lets two adapters that
    read the same pages in one run (esbd + university_boards) fetch them once.
    """

    def __init__(self, user_agent: str, min_interval: float = 5.0,
                 timeout: int = 30, max_retries: int = 3,
                 backoff_factor: float = 2.0, max_requests: int | None = None,
                 page_cache: dict | None = None):
        self._session = requests.Session()
        self._session.headers["User-Agent"] = user_agent
        self.min_interval = min_interval
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.max_requests = max_requests
        self.request_count = 0
        self.page_cache = page_cache
        self._last_request_at = 0.0

    def get_text(self, url: str, params: dict | None = None) -> str:
        cache_key = (url, tuple(sorted((params or {}).items())))
        if self.page_cache is not None and cache_key in self.page_cache:
            return self.page_cache[cache_key]
        resp = self.get(url, params=params)
        text = resp.text
        if self.page_cache is not None:
            self.page_cache[cache_key] = text
        return text

    def get(self, url: str, params: dict | None = None) -> requests.Response:
        if self.max_requests is not None and self.request_count >= self.max_requests:
            raise RequestBudgetExceeded(
                f"request budget ({self.max_requests}) exhausted before GET {url}")

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._respect_interval()
            try:
                self.request_count += 1
                resp = self._session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
                log.warning("GET %s failed (%s), attempt %d/%d", url, exc,
                            attempt + 1, self.max_retries + 1)
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                last_error = SourceError(f"HTTP {resp.status_code} from {url}")
                wait = self.backoff_factor ** (attempt + 1)
                log.warning("HTTP %d from %s, backing off %.0fs", resp.status_code, url, wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        raise SourceError(f"GET {url} failed after {self.max_retries + 1} attempts") from last_error

    def _respect_interval(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request_at = time.monotonic()


class SourceAdapter(ABC):
    """One procurement source. Subclasses set source_id and implement fetch()."""

    source_id: str = "override-me"

    def __init__(self, config: dict, session: PoliteSession | None = None):
        self.config = config
        defaults = config.get("defaults", {})
        own = config.get(self.source_id, {})
        self.own_config = own
        self.session = session or PoliteSession(
            user_agent=defaults.get("user_agent", "KhavionWatchtower/1.0"),
            min_interval=defaults.get("min_seconds_between_requests", 5),
            timeout=defaults.get("timeout_seconds", 30),
            max_retries=defaults.get("max_retries", 3),
            backoff_factor=defaults.get("backoff_factor", 2.0),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.own_config.get("enabled", False))

    def dedupe_key(self, native_id: str) -> str:
        return f"{self.source_id}:{native_id}"

    @abstractmethod
    def fetch(self) -> list[RawSolicitation]:
        ...


def run_all(adapters: list[SourceAdapter],
            logger: logging.Logger | None = None
            ) -> tuple[dict[str, list[RawSolicitation]], dict[str, str]]:
    """Run every enabled adapter, isolating failures. Returns (results, errors)
    keyed by source_id; errors carry the full stack trace text."""
    lg = logger or log
    results: dict[str, list[RawSolicitation]] = {}
    errors: dict[str, str] = {}
    for adapter in adapters:
        if not adapter.enabled:
            reason = adapter.own_config.get("reason", "disabled in sources.yaml")
            lg.info("source %s disabled, skipping (%s)",
                    adapter.source_id, " ".join(str(reason).split())[:140])
            results[adapter.source_id] = []
            continue
        try:
            items = adapter.fetch()
            results[adapter.source_id] = items
            lg.info("source %s returned %d solicitations", adapter.source_id, len(items))
        except Exception:
            trace = traceback.format_exc()
            errors[adapter.source_id] = trace
            results[adapter.source_id] = []
            lg.error("source %s FAILED (other sources continue):\n%s",
                     adapter.source_id, trace)
    return results, errors
