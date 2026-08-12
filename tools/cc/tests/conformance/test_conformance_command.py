"""Focused CLI orchestration contracts for complete/actionable conformance."""

from __future__ import annotations

from cc.commands import conformance
from cc.core.conformance.types import (
    CheckResult,
    ExpectedToday,
    Layer,
    Mode,
    Scope,
    Severity,
    Verdict,
)


def _roundtrip_pass() -> CheckResult:
    return CheckResult(
        id="roundtrip.update.is_idempotent",
        layer=Layer.ROUNDTRIP,
        severity=Severity.S0,
        scope=Scope.GLOBAL,
        subject="scratch-project",
        assertion="a second update changes nothing",
        verdict=Verdict.PASS,
        expected_today=ExpectedToday.PASS,
    )


def test_default_fast_layers_remain_read_only():
    layers = conformance._resolve_layers(
        None, command="check", output_json=False, mode=Mode.FAST
    )
    assert "roundtrip" not in layers


def test_ordinary_full_layers_include_roundtrip():
    layers = conformance._resolve_layers(
        None, command="check", output_json=False, mode=Mode.FULL
    )
    assert layers == conformance.FULL_CHECK_LAYERS
    assert "roundtrip" in layers


def test_full_collection_runs_sandboxed_roundtrip_and_announces_it(monkeypatch):
    monkeypatch.setattr(conformance, "_run_tier_layer_machine", lambda: ())
    monkeypatch.setattr(conformance, "_run_stack_layer_machine", lambda: ())
    monkeypatch.setattr(conformance, "_run_repo_layer", lambda **kwargs: ())
    monkeypatch.setattr(conformance, "_run_lock_layer", lambda **kwargs: ())
    monkeypatch.setattr(
        conformance.root_causes, "run_all_root_cause_checks", lambda: ()
    )
    monkeypatch.setattr(
        conformance, "_run_roundtrip_layer", lambda: (_roundtrip_pass(),)
    )
    notices: list[str] = []

    results = conformance._collect_results(
        layers=conformance.FULL_CHECK_LAYERS,
        mode=Mode.FULL,
        announce=notices.append,
    )

    assert [result.id for result in results] == ["roundtrip.update.is_idempotent"]
    assert notices == [conformance._ROUNDTRIP_MUTATION_NOTICE]
