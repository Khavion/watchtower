"""ESBD adapter tests against live-captured fixtures (offline, no network)."""

from datetime import date
from pathlib import Path

from pipeline.models import RawSolicitation
from sources.base import PoliteSession
from sources.esbd import EsbdAdapter, parse_detail_page, parse_list_page

FIXTURES = Path(__file__).parent / "fixtures"

CONFIG = {
    "defaults": {"user_agent": "test", "min_seconds_between_requests": 0},
    "esbd": {
        "enabled": True,
        "list_url": "https://example.test/esbd",
        "detail_url_prefix": "https://example.test/esbd/",
        "max_pages_per_run": 2,
        "detail_budget_per_run": 5,
        "title_prefilter_keywords": ["technology", "software", "cloud"],
        "keywords": ["cloud", "artificial intelligence"],
        "nigp_class_prefixes": ["204", "208", "920"],
    },
}


class FakeSession(PoliteSession):
    def __init__(self, pages: dict):
        super().__init__(user_agent="test", min_interval=0)
        self.pages = pages
        self.calls = []

    def get_text(self, url, params=None):
        self.calls.append((url, params))
        for key, text in self.pages.items():
            if key in url or (params and str(params.get("page")) == key):
                return text
        raise AssertionError(f"unexpected fetch: {url} {params}")


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_parse_list_page_extracts_rows():
    rows = parse_list_page(_fixture("esbd_list_p1.html"))
    assert len(rows) >= 5
    row = next(r for r in rows if r["native_id"] == "27-007")
    assert row["title"] == "Disposal of Surplus Technology Equipment"
    assert row["status"] == "Posted"
    assert row["agency_number"] == "S6014"
    assert row["due_date"] == date(2026, 8, 3)
    assert row["posted_date"] == date(2026, 7, 20)


def test_parse_detail_page_extracts_fields():
    detail = parse_detail_page(_fixture("esbd_detail.html"))
    assert detail["contact_email"] == "sheila.cantu@gccisd.net"
    assert detail["due_date"] == date(2026, 8, 3)
    assert detail["due_time"] == "8:00 PM"
    assert detail["agency_number"] == "S6014"
    assert detail["nigp_codes"][:3] == ["20400", "20300", "20379"]
    assert "Goose Creek" in detail["description"]
    assert any("27-007" in a or a.startswith("ESBD_") for a in detail["attachments"])


def test_adapter_end_to_end_keeps_nigp_match():
    session = FakeSession({
        "esbd/27-007": _fixture("esbd_detail.html"),
        "example.test/esbd": _fixture("esbd_list_p1.html"),
    })
    cfg = {**CONFIG, "esbd": {**CONFIG["esbd"], "max_pages_per_run": 1}}
    adapter = EsbdAdapter(cfg, session=session)
    results = adapter.fetch()
    # 27-007 passes the title prefilter ("technology") and is kept via its
    # 204xx NIGP class; the LLM relevance pass downstream exists to kill
    # exactly this kind of keyword-plausible, actually-irrelevant record.
    assert any(s.native_id == "27-007" for s in results)
    sol = next(s for s in results if s.native_id == "27-007")
    assert sol.dedupe_key == "esbd:27-007"
    assert sol.contact_email == "sheila.cantu@gccisd.net"
    assert sol.nigp_codes[0] == "20400"


def test_keep_filter_drops_no_signal():
    adapter = EsbdAdapter(CONFIG, session=FakeSession({}))
    sol = RawSolicitation(
        source_id="esbd", native_id="x", dedupe_key="esbd:x",
        title="Janitorial services for district offices",
        description="Routine cleaning services.", nigp_codes=["91000"])
    assert not adapter._keep(sol)


def test_skip_keys_prevents_detail_fetch():
    session = FakeSession({"example.test/esbd": _fixture("esbd_list_p1.html")})
    cfg = {**CONFIG, "esbd": {**CONFIG["esbd"], "max_pages_per_run": 1}}
    adapter = EsbdAdapter(cfg, session=session, skip_keys={"esbd:27-007"})
    results = adapter.fetch()
    assert not any(s.native_id == "27-007" for s in results)
    assert not any("27-007" in url for url, _ in session.calls)
