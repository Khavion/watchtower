"""SAM.gov Get Opportunities Public API v2 adapter.

Verified 2026-07-24 against https://open.gsa.gov/api/get-opportunities-public-api/:
- GET https://api.sam.gov/opportunities/v2/search, api_key required per call.
- postedFrom/postedTo are MANDATORY, MM/dd/yyyy, max 1-year span.
- `limit` must be passed explicitly (the server default is 1).
- ptype codes: r=Sources Sought, s=Special Notice (RFIs conventionally live
  under both, there is no dedicated RFI code), o=Solicitation, k=Combined
  Synopsis/Solicitation, p=Presolicitation.
- The record's `description` field is a URL costing one extra keyed call.
- Basic personal keys: 10 requests/day, reset midnight UTC, 429 on breach.
  The daily budget here is enforced through pipeline.state and never
  degrades silently.

Strategy: aggressively favor Sources Sought / RFI-style notices (what a firm
with no federal past performance can actually answer); full solicitations are
fetched but flagged NOT_YET_ELIGIBLE when past-performance language appears.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

from pipeline import state
from pipeline.models import RawSolicitation
from sources.base import SourceAdapter, SourceError

log = logging.getLogger(__name__)

KEYCHAIN_SERVICE = "khavion-sam-api-key"
KEYCHAIN_ACCOUNT = "khavion"
STATE_KEY = "sam_api_calls"

PAST_PERFORMANCE_RE = re.compile(
    r"past performance|relevant experience of the offeror|CPARS", re.IGNORECASE)

# (group name, ptype codes). Primary first: those get budget priority.
NOTICE_GROUPS = [("primary", None), ("secondary", None)]


def _parse_any_date(value) -> date | None:
    if not value:
        return None
    value = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value[:19], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


class SamGovAdapter(SourceAdapter):
    source_id = "sam_gov"

    def __init__(self, config: dict, session=None, skip_keys: set[str] | None = None,
                 api_key: str | None = None, daily_cap: int | None = None,
                 state_path=None):
        super().__init__(config, session)
        self.skip_keys = skip_keys or set()
        self._api_key = api_key
        self._daily_cap = daily_cap
        self.state_path = state_path

    @property
    def daily_cap(self) -> int:
        if self._daily_cap is None:
            from pipeline.config import caps
            self._daily_cap = int(caps().get("sources", {}).get("sam_max_calls_per_day", 8))
        return self._daily_cap

    def api_key(self) -> str:
        if self._api_key:
            return self._api_key
        import keyring
        value = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
        if not value:
            raise SourceError(
                f"{KEYCHAIN_SERVICE} missing from Keychain; run deploy/setup_credentials.py sam")
        self._api_key = value
        return value

    def _daily_calls_left(self) -> int:
        st = state.load(self.state_path)
        return self.daily_cap - state.daily_count(st, STATE_KEY)

    def _record_call(self) -> None:
        st = state.load(self.state_path)
        state.bump_daily_counter(st, STATE_KEY)
        state.save(st, self.state_path)

    def _keyed_get_json(self, url: str, params: dict) -> dict:
        if self._daily_calls_left() <= 0:
            raise SourceError(
                f"sam_gov: daily call cap ({self.daily_cap}) reached; HALTING this "
                "source for today (cap enforced, never silent)")
        self._record_call()
        resp = self.session.get(url, params={**params, "api_key": self.api_key()})
        try:
            return resp.json()
        except ValueError as exc:
            raise SourceError(f"sam_gov: non-JSON response from {url}") from exc

    def _search(self, ptypes: list[str], naics: str) -> list[dict]:
        own = self.own_config
        today = date.today()
        params = {
            "limit": 100,
            "postedFrom": (today - timedelta(days=int(own.get("lookback_days", 3)))).strftime("%m/%d/%Y"),
            "postedTo": today.strftime("%m/%d/%Y"),
            "ptype": ptypes,
            "ncode": naics,
        }
        payload = self._keyed_get_json(own["base_url"], params)
        return payload.get("opportunitiesData") or []

    def _to_solicitation(self, item: dict, group: str) -> RawSolicitation:
        native_id = item.get("noticeId") or item.get("solicitationNumber") or "unknown"
        title = item.get("title") or "(untitled)"
        set_aside = item.get("typeOfSetAsideDescription") or item.get("typeOfSetAside") or None
        # SAM records negatives explicitly ("No Set aside used", "None"):
        # those are the absence of a set-aside, not set-aside language.
        if set_aside and re.match(r"^\s*(no\b|none\b)", str(set_aside), re.IGNORECASE):
            set_aside = None
        eligibility = None
        if group == "secondary" and PAST_PERFORMANCE_RE.search(title):
            eligibility = "NOT_YET_ELIGIBLE"
        return RawSolicitation(
            source_id=self.source_id,
            native_id=native_id,
            dedupe_key=self.dedupe_key(native_id),
            title=title,
            url=item.get("uiLink") or "",
            agency=item.get("fullParentPathName") or item.get("organizationName"),
            status="Posted" if str(item.get("active", "")).lower() in ("yes", "true") else item.get("active"),
            notice_type=item.get("type"),
            posted_date=_parse_any_date(item.get("postedDate")),
            due_date=_parse_any_date(item.get("responseDeadLine")),
            naics_codes=[str(c) for c in ([item.get("naicsCode")] if not isinstance(
                item.get("naicsCode"), list) else item.get("naicsCode")) if c],
            set_aside_text=set_aside,
            eligibility_flag=eligibility,
            raw={"award": item.get("award"), "baseType": item.get("baseType"),
                 "description_url": item.get("description"),
                 "solicitationNumber": item.get("solicitationNumber"),
                 "notice_group": group},
        )

    def _fill_description(self, sol: RawSolicitation) -> None:
        url = sol.raw.get("description_url")
        if not url:
            return
        try:
            payload = self._keyed_get_json(url, {})
        except SourceError as exc:
            log.warning("sam_gov: description fetch skipped for %s (%s)", sol.native_id, exc)
            return
        text = payload.get("description") if isinstance(payload, dict) else None
        sol.description = str(text or "")
        if (sol.raw.get("notice_group") == "secondary"
                and sol.eligibility_flag is None
                and PAST_PERFORMANCE_RE.search(sol.description)):
            sol.eligibility_flag = "NOT_YET_ELIGIBLE"

    def fetch(self) -> list[RawSolicitation]:
        own = self.own_config
        budget = int(own.get("max_calls_per_run", 4))
        naics_list = [str(n) for n in own.get("naics", ["541512"])]
        groups = [("primary", [str(p) for p in own.get("ptypes_primary", ["r", "s"])]),
                  ("secondary", [str(p) for p in own.get("ptypes_secondary", ["o", "k", "p"])])]

        collected: dict[str, RawSolicitation] = {}
        # Lead NAICS gets full coverage (primary + secondary) before any budget
        # goes to additional NAICS codes; without this, a small daily quota is
        # consumed entirely by primary searches and secondary notices plus
        # description fetches never happen (observed live 2026-07-24).
        lead, rest = naics_list[0], naics_list[1:]
        plan = [(g, pt, lead) for (g, pt) in groups] + \
               [(g, pt, n) for (g, pt) in groups for n in rest]
        plan = plan[:max(1, budget - 2)]  # reserve calls for description fetches
        for group, ptypes, naics in plan:
            if budget <= 0:
                log.warning("sam_gov: per-run call budget exhausted; remaining "
                            "queries deferred to next run")
                break
            try:
                items = self._search(ptypes, naics)
            except SourceError as exc:
                log.error("sam_gov: search halted: %s", exc)
                break
            budget -= 1
            for item in items:
                sol = self._to_solicitation(item, group)
                if sol.dedupe_key in self.skip_keys:
                    continue
                collected.setdefault(sol.dedupe_key, sol)

        # Spend remaining budget on description fetches, newest first.
        fresh = sorted(collected.values(),
                       key=lambda s: s.posted_date or date.min, reverse=True)
        for sol in fresh:
            if budget <= 0:
                break
            self._fill_description(sol)
            budget -= 1

        log.info("sam_gov: %d new solicitations", len(fresh))
        return fresh
