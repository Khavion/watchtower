"""Cap enforcement. Every cap in config/caps.yaml is checked here.

Contract: exceeding a cap HALTS that pipeline with CapExceeded and logs it.
It never degrades silently — no partial quiet continuation, no auto-raise.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from pipeline import state
from pipeline.config import caps as load_caps

log = logging.getLogger(__name__)


class CapExceeded(Exception):
    """A configured cap was hit. The affected pipeline must stop, loudly."""


class CapGate:
    def __init__(self, caps: dict | None = None, state_path=None):
        self.caps = caps or load_caps()
        self.state_path = state_path

    # ----- Apollo credits -----

    def _month_key(self) -> str:
        return date.today().strftime("%Y-%m")

    def apollo_credits_used_this_month(self) -> int:
        st = state.load(self.state_path)
        ledger = st.get("apollo_credit_ledger", {})
        return int(ledger.get(self._month_key(), 0))

    def check_apollo_budget(self, planned_credits: int, run_spent: int = 0) -> None:
        cfg = self.caps.get("apollo", {})
        monthly_cap = int(cfg.get("monthly_credit_cap", 0))
        per_run_cap = int(cfg.get("per_run_credit_cap", 0))
        if monthly_cap <= 0:
            raise CapExceeded(
                "apollo.monthly_credit_cap is 0 (unconfigured); enrichment is blocked "
                "until Phase 1 sets it in config/caps.yaml")
        used = self.apollo_credits_used_this_month()
        if used + planned_credits > monthly_cap:
            raise CapExceeded(
                f"Apollo monthly credit cap would be exceeded: {used} used + "
                f"{planned_credits} planned > {monthly_cap}. HALTING enrichment.")
        if run_spent + planned_credits > per_run_cap:
            raise CapExceeded(
                f"Apollo per-run credit cap would be exceeded: {run_spent} spent + "
                f"{planned_credits} planned > {per_run_cap}. HALTING this run.")

    def record_apollo_credits(self, credits: int) -> None:
        if credits <= 0:
            return
        st = state.load(self.state_path)
        ledger = st.setdefault("apollo_credit_ledger", {})
        ledger[self._month_key()] = int(ledger.get(self._month_key(), 0)) + credits
        state.save(st, self.state_path)
        log.info("apollo credit ledger: +%d -> %d this month", credits,
                 ledger[self._month_key()])

    # ----- Drafts per day -----

    def check_draft_budget(self) -> None:
        cap = int(self.caps.get("drafts", {}).get("max_per_day", 25))
        st = state.load(self.state_path)
        used = state.daily_count(st, "drafts_created")
        if used >= cap:
            raise CapExceeded(
                f"draft cap reached ({used}/{cap} today). HALTING drafting until tomorrow.")

    def record_draft(self) -> None:
        st = state.load(self.state_path)
        state.bump_daily_counter(st, "drafts_created")
        state.save(st, self.state_path)

    # ----- Account touch spacing -----

    def touch_allowed(self, last_touched_iso: str | None) -> bool:
        if not last_touched_iso:
            return True
        min_days = int(self.caps.get("accounts", {}).get("min_days_between_touches", 30))
        try:
            last = datetime.fromisoformat(last_touched_iso)
        except ValueError:
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - last).days >= min_days
