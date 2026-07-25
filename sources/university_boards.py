"""University bid boards: UH, Texas A&M System, UT System.

Verified 2026-07-24: these institutions cross-post formal solicitations to
ESBD (state agencies >= $25k; UT System policy >= $50k), so this adapter reads
the same ESBD list pages (shared page cache: no duplicate HTTP when both run
in one session) and filters by the Agency/Texas SmartBuy Member Numbers
extracted live from the ESBD agency dropdown, plus name keywords as a net.

AggieBid (bids.sciquest.com) is server-rendered but robots-disallowed and
redundant with ESBD, so it is not fetched. Sub-$50k UT work lives on Bonfire
portals a requests-only client cannot reach (documented in sources.yaml).

Dedupe keys deliberately share the esbd: namespace: the same posting surfaced
by both adapters is one record downstream, first ingest wins.
"""

from __future__ import annotations

import logging
from datetime import date

from pipeline.models import RawSolicitation
from sources.base import SourceAdapter
from sources.esbd import EsbdAdapter

log = logging.getLogger(__name__)


class UniversityBoardsAdapter(SourceAdapter):
    source_id = "university_boards"

    def __init__(self, config: dict, session=None, skip_keys: set[str] | None = None):
        super().__init__(config, session)
        self.skip_keys = skip_keys or set()
        self._esbd = EsbdAdapter(config, session=self.session, skip_keys=self.skip_keys)

    def _matches(self, row: dict) -> bool:
        numbers = {str(n) for n in self.own_config.get("agency_numbers", {})}
        if str(row.get("agency_number") or "") in numbers:
            return True
        keywords = [k.lower() for k in self.own_config.get("name_keywords", [])]
        title = (row.get("title") or "").lower()
        return any(k in title for k in keywords)

    def fetch(self) -> list[RawSolicitation]:
        rows = self._esbd.list_rows()
        today = date.today()
        candidates = [
            row for row in rows
            if self._matches(row)
            and row.get("status") == "Posted"
            and not (row.get("due_date") and row["due_date"] < today)
            and self._esbd.dedupe_key(row["native_id"]) not in self.skip_keys
        ]
        budget = int(self.own_config.get("detail_budget_per_run", 8))
        if len(candidates) > budget:
            log.warning("university_boards: %d candidates exceed budget %d; "
                        "deferring %d", len(candidates), budget, len(candidates) - budget)
            candidates = candidates[:budget]

        agency_names = {str(k): v for k, v in self.own_config.get("agency_numbers", {}).items()}
        out: list[RawSolicitation] = []
        for row in candidates:
            sol = self._esbd.build_solicitation(row)
            if sol is None:
                continue
            out.append(sol.model_copy(update={
                "source_id": self.source_id,
                "agency": agency_names.get(str(sol.agency_number or "")),
            }))
        log.info("university_boards: %d list rows, %d university matches, %d fetched",
                 len(rows), len(candidates), len(out))
        return out
