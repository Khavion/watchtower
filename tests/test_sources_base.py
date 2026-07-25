"""Adapter isolation: one source raising must never stop the others."""

import logging

from pipeline.models import RawSolicitation
from sources.base import SourceAdapter, run_all


def _sol(source_id: str, native_id: str) -> RawSolicitation:
    return RawSolicitation(source_id=source_id, native_id=native_id,
                           dedupe_key=f"{source_id}:{native_id}", title="t")


def _adapter(source_id: str, behavior):
    class A(SourceAdapter):
        def fetch(self):
            return behavior(self)
    A.source_id = source_id
    return A({source_id: {"enabled": True}, "defaults": {}})


def test_one_failure_does_not_stop_others(caplog):
    ok1 = _adapter("alpha", lambda self: [_sol("alpha", "1")])
    boom = _adapter("beta", lambda self: (_ for _ in ()).throw(RuntimeError("kaput")))
    ok2 = _adapter("gamma", lambda self: [_sol("gamma", "2")])
    ok3 = _adapter("delta", lambda self: [])

    with caplog.at_level(logging.ERROR):
        results, errors = run_all([ok1, boom, ok2, ok3])

    assert [s.native_id for s in results["alpha"]] == ["1"]
    assert [s.native_id for s in results["gamma"]] == ["2"]
    assert results["delta"] == []
    assert results["beta"] == []
    assert "beta" in errors and "RuntimeError: kaput" in errors["beta"]
    assert any("kaput" in r.message for r in caplog.records)


def test_disabled_adapter_is_skipped_not_run():
    calls = []
    disabled = _adapter("off", lambda self: calls.append(1))
    disabled.own_config["enabled"] = False
    results, errors = run_all([disabled])
    assert results["off"] == [] and not errors and not calls
