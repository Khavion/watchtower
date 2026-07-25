"""Texas ESBD (Electronic State Business Daily) adapter.

Access method: polite scraping of the server-rendered HTML at
https://www.txsmartbuy.gov/esbd, approved by the owner on 2026-07-24 with the
robots.txt tradeoff documented in config/sources.yaml. Verified 2026-07-24:
list pages and detail pages are fully server-rendered; URL query filters
silently no-op, so filtering happens locally; default ordering is
last-updated (bulk re-timestamping reorders old records), so we read several
pages and select on posting/due dates instead of diffing page 1.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from pipeline.models import RawSolicitation
from sources.base import SourceAdapter

log = logging.getLogger(__name__)

# Verbatim capture, zero interpretation: HUB/VetHUB eligibility is
# mid-litigation through 2026 and gonogo routes any hit to NEEDS_HUMAN.
SET_ASIDE_RE = re.compile(
    r"[^.\n]{0,120}\b(HUB\b|VetHUB|set[- ]aside|historically underutilized"
    r"|service[- ]disabled veteran|SDVOSB|veteran[- ]owned)\b[^.\n]{0,200}",
    re.IGNORECASE)

NOTICE_TYPE_RE = re.compile(
    r"\b(RFP|RFQ|RFI|RFO|IFB|ITB|CSP|RFA|Sources Sought)\b", re.IGNORECASE)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    value = _clean(value)
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
    if not m:
        return None
    month, day, year = (int(g) for g in m.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _label_values(root) -> dict[str, str]:
    """Collect <strong>Label:</strong> value pairs, keeping the first
    non-empty value per label (the page contains an empty JS template block
    alongside the rendered one)."""
    out: dict[str, str] = {}
    for strong in root.find_all("strong"):
        label = _clean(strong.get_text()).rstrip(":").strip()
        if not label:
            continue
        parent_text = _clean(strong.parent.get_text())
        strong_text = _clean(strong.get_text())
        value = parent_text[len(strong_text):].strip() if parent_text.startswith(strong_text) else ""
        if not value:
            # Value may live in the next sibling element (description pattern).
            sib = strong.parent.find_next_sibling()
            if sib is not None and sib.find("strong") is None:
                value = _clean(sib.get_text())
        if value and label not in out:
            out[label] = value
    return out


def parse_list_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for row in soup.select("div.esbd-result-row"):
        link = row.select_one(".esbd-result-title a")
        if link is None or not link.get("href"):
            continue
        native_id = link["href"].rstrip("/").rsplit("/", 1)[-1]
        fields = _label_values(row)
        rows.append({
            "native_id": native_id,
            "title": _clean(link.get_text()),
            "solicitation_id": fields.get("Solicitation ID", native_id),
            "status": fields.get("Status"),
            "agency_number": fields.get("Agency/Texas SmartBuy Member Number"),
            "due_date": _parse_date(fields.get("Due Date")),
            "due_time": fields.get("Due Time"),
            "posted_date": _parse_date(fields.get("Posting Date")),
            "last_updated": fields.get("Last Updated"),
        })
    return rows


def parse_detail_page(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("div.esbd-container") or soup
    fields = _label_values(container)

    text = container.get_text("\n", strip=True)
    set_aside = None
    m = SET_ASIDE_RE.search(text)
    if m:
        set_aside = _clean(m.group(0))

    nigp_raw = fields.get("Class/Item Code", "")
    nigp_codes = re.findall(r"\b(\d{3,5})\s*-", nigp_raw)

    description = fields.get("Solicitation Description", "")

    # Attachments render as div rows (.esbd-attachment-row), not a table:
    # cells are [index, name, description].
    attachments = []
    for row in soup.select("div.esbd-attachment-row"):
        cells = [_clean(c.get_text()) for c in row.select("div.pod-attachment-cell")]
        name = next((c for c in cells if c), None)
        if name is None:
            name = _clean(row.get_text())
        if name:
            attachments.append(name)

    notice_type = None
    tm = NOTICE_TYPE_RE.search(fields.get("Solicitation Type", "") or description or text)
    if tm:
        notice_type = tm.group(1).upper()

    return {
        "contact_name": fields.get("Contact Name"),
        "contact_phone": fields.get("Contact Number"),
        "contact_email": fields.get("Contact Email"),
        "bid_response_email": fields.get("Bid Response Email"),
        "due_date": _parse_date(fields.get("Response Due Date")),
        "due_time": fields.get("Response Due Time"),
        "agency_number": fields.get("Agency/Texas SmartBuy Member Number"),
        "posted_date": _parse_date(fields.get("Solicitation Posting Date")),
        "last_modified": fields.get("Last Modified"),
        "nigp_codes": nigp_codes,
        "nigp_raw": nigp_raw,
        "description": description,
        "attachments": attachments,
        "set_aside_text": set_aside,
        "notice_type": notice_type,
    }


class EsbdAdapter(SourceAdapter):
    source_id = "esbd"

    def __init__(self, config: dict, session=None, skip_keys: set[str] | None = None):
        super().__init__(config, session)
        self.skip_keys = skip_keys or set()

    def _title_prefilter(self, title: str) -> bool:
        keywords = self.own_config.get("title_prefilter_keywords", [])
        lowered = title.lower()
        return any(k.lower() in lowered for k in keywords)

    def _keep(self, sol: RawSolicitation) -> bool:
        keywords = [k.lower() for k in self.own_config.get("keywords", [])]
        prefixes = [str(p) for p in self.own_config.get("nigp_class_prefixes", [])]
        haystack = f"{sol.title} {sol.description}".lower()
        if any(k in haystack for k in keywords):
            return True
        return any(code.startswith(p) for code in sol.nigp_codes for p in prefixes)

    def list_rows(self) -> list[dict]:
        """Fetch and parse the configured number of list pages."""
        rows: list[dict] = []
        for page in range(1, int(self.own_config.get("max_pages_per_run", 10)) + 1):
            params = {"page": page} if page > 1 else None
            html = self.session.get_text(self.own_config["list_url"], params=params)
            page_rows = parse_list_page(html)
            if not page_rows:
                break
            rows.extend(page_rows)
        return rows

    def build_solicitation(self, row: dict) -> RawSolicitation | None:
        url = self.own_config["detail_url_prefix"] + row["native_id"]
        try:
            detail = parse_detail_page(self.session.get_text(url))
        except Exception:
            log.exception("esbd: detail fetch/parse failed for %s (continuing)", row["native_id"])
            return None
        return RawSolicitation(
            source_id=self.source_id,
            native_id=row["native_id"],
            dedupe_key=self.dedupe_key(row["native_id"]),
            title=row["title"],
            url=url,
            agency=None,
            agency_number=detail.get("agency_number") or row.get("agency_number"),
            status=row.get("status"),
            notice_type=detail.get("notice_type"),
            posted_date=detail.get("posted_date") or row.get("posted_date"),
            due_date=detail.get("due_date") or row.get("due_date"),
            due_time=detail.get("due_time") or row.get("due_time"),
            description=detail.get("description", ""),
            nigp_codes=detail.get("nigp_codes", []),
            set_aside_text=detail.get("set_aside_text"),
            attachments=detail.get("attachments", []),
            contact_name=detail.get("contact_name"),
            contact_email=detail.get("contact_email"),
            contact_phone=detail.get("contact_phone"),
            raw={"list_row": {k: str(v) for k, v in row.items()},
                 "bid_response_email": detail.get("bid_response_email"),
                 "nigp_raw": detail.get("nigp_raw"),
                 "last_modified": detail.get("last_modified")},
        )

    def _candidates(self, rows: list[dict]) -> list[dict]:
        today = date.today()
        out = []
        for row in rows:
            if row.get("status") != "Posted":
                continue
            if row.get("due_date") and row["due_date"] < today:
                continue
            if self.dedupe_key(row["native_id"]) in self.skip_keys:
                continue
            if not self._title_prefilter(row["title"]):
                continue
            out.append(row)
        return out

    def fetch(self) -> list[RawSolicitation]:
        rows = self.list_rows()
        candidates = self._candidates(rows)
        budget = int(self.own_config.get("detail_budget_per_run", 15))
        if len(candidates) > budget:
            log.warning("esbd: %d candidates exceed detail budget %d; "
                        "deferring %d to the next run",
                        len(candidates), budget, len(candidates) - budget)
            candidates = candidates[:budget]
        kept: list[RawSolicitation] = []
        for row in candidates:
            sol = self.build_solicitation(row)
            if sol is not None and self._keep(sol):
                kept.append(sol)
        log.info("esbd: %d list rows, %d candidates, %d kept", len(rows),
                 len(candidates), len(kept))
        return kept
