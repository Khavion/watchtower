"""Employer firewall: block, short-circuit, and never echo blocklist contents.
Tests use a synthetic blocklist ONLY — the real blocklist.local.md is never read."""

import logging

import pytest

from pipeline.firewall import EmployerFirewall, FirewallViolation

SYNTHETIC = """# test blocklist
| domain | parent_company | reason_code | date_added |
|---|---|---|---|
| example.com | Example Corp | EMPLOYER_ACCOUNT | 2026-07-24 |
| blocked-corp.com | Blocked Corp Holdings | EMPLOYER_ACCOUNT | 2026-07-24 |
| sneaky.io | | EMPLOYER_ADJACENT | 2026-07-24 |
"""


@pytest.fixture
def firewall(tmp_path):
    path = tmp_path / "blocklist.local.md"
    path.write_text(SYNTHETIC)
    return EmployerFirewall(blocklist_path=path)


def test_domain_and_subdomain_blocked(firewall):
    assert firewall.check_domain("blocked-corp.com") == "EMPLOYER_ACCOUNT"
    assert firewall.check_domain("app.blocked-corp.com") == "EMPLOYER_ACCOUNT"
    assert firewall.check_domain("BLOCKED-CORP.COM") == "EMPLOYER_ACCOUNT"
    assert firewall.check_domain("sneaky.io") == "EMPLOYER_ADJACENT"
    assert firewall.check_domain("fine-company.com") is None
    # Suffix matching must not over-match lookalikes.
    assert firewall.check_domain("notblocked-corp.com.evil.net") is None


def test_company_name_blocked(firewall):
    assert firewall.check_company("Blocked Corp Holdings LLC") == "EMPLOYER_ACCOUNT"
    assert firewall.check_company("Some Fine Startup") is None


def test_assert_clean_raises_with_reason_code_only(firewall):
    with pytest.raises(FirewallViolation) as exc:
        firewall.assert_clean("We worked with blocked-corp.com on this.", stage="draft")
    assert exc.value.reason_code == "EMPLOYER_ACCOUNT"
    assert exc.value.stage == "draft"
    # The violation must NEVER echo the blocklist contents.
    assert "blocked-corp" not in str(exc.value).lower()


def test_missing_blocklist_warns_and_passes(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        fw = EmployerFirewall(blocklist_path=tmp_path / "nope.local.md")
    assert not fw.loaded
    assert fw.check_domain("anything.com") is None
    assert any("MISSING" in r.message for r in caplog.records)


def test_log_never_contains_blocklist_rows(firewall, caplog):
    with caplog.at_level(logging.DEBUG):
        firewall.check_text("mentioning blocked-corp.com here")
    assert not any("blocked-corp" in r.getMessage().lower() for r in caplog.records)
