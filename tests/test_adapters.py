"""SAM.gov, university_boards, houston_local adapters + real-adapter isolation."""

import json
import logging
from datetime import date
from pathlib import Path

import pytest

from sources.base import PoliteSession, SourceError, run_all
from sources.esbd import EsbdAdapter
from sources.houston_local import HoustonLocalAdapter
from sources.sam_gov import SamGovAdapter
from sources.university_boards import UniversityBoardsAdapter

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeSamSession(PoliteSession):
    """Serves search results split by ptype group, and description payloads."""

    def __init__(self):
        super().__init__(user_agent="test", min_interval=0)
        self.calls = []
        data = json.loads(_fixture("sam_search.json"))["opportunitiesData"]
        self.by_type = {item["noticeId"]: item for item in data}

    def get(self, url, params=None):
        self.calls.append((url, params))
        if "noticedesc" in url:
            notice = url.split("noticeid=")[-1]
            text = {"abc123": "The Government seeks capability statements for cloud "
                              "migration and AI advisory services.",
                    "def456": "Offerors shall demonstrate past performance on three "
                              "similar contracts."}[notice]
            return FakeResponse({"description": text})
        ptypes = params.get("ptype", [])
        if "r" in ptypes:
            items = [self.by_type["abc123"]]
        else:
            items = [self.by_type["def456"]]
        return FakeResponse({"totalRecords": len(items), "opportunitiesData": items})


SAM_CONFIG = {
    "defaults": {"user_agent": "test", "min_seconds_between_requests": 0},
    "sam_gov": {
        "enabled": True,
        "base_url": "https://api.sam.gov/opportunities/v2/search",
        "ptypes_primary": ["r", "s"],
        "ptypes_secondary": ["o", "k", "p"],
        "naics": ["541512"],
        "lookback_days": 3,
        "max_calls_per_run": 4,
    },
}


def test_sam_fetch_parses_and_flags(tmp_path):
    session = FakeSamSession()
    adapter = SamGovAdapter(SAM_CONFIG, session=session, api_key="test-key",
                            daily_cap=10, state_path=tmp_path / "state.json")
    results = adapter.fetch()

    assert {s.native_id for s in results} == {"abc123", "def456"}
    sourced = {s.native_id: s for s in results}

    sought = sourced["abc123"]
    assert sought.notice_type == "Sources Sought"
    assert sought.posted_date == date(2026, 7, 22)
    assert sought.due_date == date(2026, 8, 15)
    assert sought.naics_codes == ["541512"]
    assert "cloud migration" in sought.description.lower()
    assert sought.eligibility_flag is None

    full = sourced["def456"]
    # Set-aside text is stored verbatim, never interpreted.
    assert full.set_aside_text == "Total Small Business Set-Aside (FAR 19.5)"
    # Secondary-group notice whose description demands past performance.
    assert full.eligibility_flag == "NOT_YET_ELIGIBLE"
    assert full.raw["award"]["awardee"]["name"] == "Incumbent Corp LLC"

    search_calls = [(u, p) for u, p in session.calls if "noticedesc" not in u]
    assert len(search_calls) == 2
    for _, params in search_calls:
        assert params["limit"] == 100
        assert params["api_key"] == "test-key"
        # Mandatory MM/dd/yyyy window.
        assert len(params["postedFrom"].split("/")) == 3
    desc_calls = [(u, p) for u, p in session.calls if "noticedesc" in u]
    assert len(desc_calls) == 2 and all(p["api_key"] == "test-key" for _, p in desc_calls)


def test_sam_negative_set_aside_normalized_to_none(tmp_path):
    session = FakeSamSession()
    session.by_type["def456"]["typeOfSetAsideDescription"] = "No Set aside used"
    session.by_type["def456"]["typeOfSetAside"] = None
    adapter = SamGovAdapter(SAM_CONFIG, session=session, api_key="k",
                            daily_cap=10, state_path=tmp_path / "state.json")
    results = adapter.fetch()
    full = next(s for s in results if s.native_id == "def456")
    assert full.set_aside_text is None


def test_sam_daily_cap_halts_loudly(tmp_path, caplog):
    session = FakeSamSession()
    adapter = SamGovAdapter(SAM_CONFIG, session=session, api_key="k",
                            daily_cap=1, state_path=tmp_path / "state.json")
    with caplog.at_level(logging.WARNING):
        results = adapter.fetch()
    # One search happened, then the cap halted the source (no silent degrade).
    assert {s.native_id for s in results} == {"abc123"}
    assert any("cap" in r.message and "HALTING" in r.message for r in caplog.records)


UNI_CONFIG = {
    "defaults": {"user_agent": "test", "min_seconds_between_requests": 0},
    "esbd": {
        "enabled": True,
        "list_url": "https://example.test/esbd",
        "detail_url_prefix": "https://example.test/esbd/",
        "max_pages_per_run": 1,
    },
    "university_boards": {
        "enabled": True,
        "agency_numbers": {"S6014": "Test ISD (stands in for a university)"},
        "name_keywords": [],
        "detail_budget_per_run": 4,
    },
}


class FakePageSession(PoliteSession):
    def __init__(self, pages):
        super().__init__(user_agent="test", min_interval=0)
        self.pages = pages

    def get_text(self, url, params=None):
        for key, text in self.pages.items():
            if key in url:
                return text
        raise AssertionError(f"unexpected fetch {url}")


def test_university_adapter_filters_by_agency_number():
    session = FakePageSession({
        "esbd/27-007": _fixture("esbd_detail.html"),
        "example.test/esbd": _fixture("esbd_list_p1.html"),
    })
    adapter = UniversityBoardsAdapter(UNI_CONFIG, session=session)
    results = adapter.fetch()
    assert len(results) >= 1
    sol = next(s for s in results if s.native_id == "27-007")
    assert sol.source_id == "university_boards"
    # Shared dedupe namespace with esbd: same posting = one record downstream.
    assert sol.dedupe_key == "esbd:27-007"
    assert sol.agency == "Test ISD (stands in for a university)"


def test_houston_disabled_returns_nothing_enabled_fails_loudly():
    disabled = HoustonLocalAdapter({"houston_local": {"enabled": False}, "defaults": {}})
    results, errors = run_all([disabled])
    assert results["houston_local"] == [] and not errors

    enabled = HoustonLocalAdapter({"houston_local": {"enabled": True}, "defaults": {}})
    with pytest.raises(SourceError, match="no machine-readable"):
        enabled.fetch()


def test_real_adapter_isolation_one_of_four_failing(tmp_path):
    """Acceptance gate #6 with the real four adapter classes."""

    class BoomSession(PoliteSession):
        def __init__(self):
            super().__init__(user_agent="test", min_interval=0)

        def get_text(self, url, params=None):
            raise RuntimeError("esbd exploded")

    esbd_cfg = {"defaults": {}, "esbd": {"enabled": True,
                "list_url": "https://x/esbd", "detail_url_prefix": "https://x/esbd/"}}
    esbd = EsbdAdapter(esbd_cfg, session=BoomSession())
    sam = SamGovAdapter(SAM_CONFIG, session=FakeSamSession(), api_key="k",
                        daily_cap=10, state_path=tmp_path / "s.json")
    uni = UniversityBoardsAdapter(UNI_CONFIG, session=FakePageSession({
        "esbd/27-007": _fixture("esbd_detail.html"),
        "example.test/esbd": _fixture("esbd_list_p1.html"),
    }))
    houston = HoustonLocalAdapter({"houston_local": {"enabled": False}, "defaults": {}})

    results, errors = run_all([esbd, sam, uni, houston])

    assert set(errors) == {"esbd"} and "esbd exploded" in errors["esbd"]
    assert results["esbd"] == []
    assert len(results["sam_gov"]) == 2
    assert len(results["university_boards"]) >= 1
    assert results["houston_local"] == []
