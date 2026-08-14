"""Focused CLI orchestration contracts for complete/actionable conformance."""

from __future__ import annotations

from pathlib import Path

from cc.commands import conformance
from cc.core.conformance import roundtrip
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


def test_tier_collection_emits_one_verdict_per_aggregate_capability(
    monkeypatch, tmp_path: Path
):
    framework_root = tmp_path / "framework"
    cc_source_root = framework_root / "tools" / "cc" / "src" / "cc"
    ecosystem = cc_source_root / "core" / "ecosystem"
    ecosystem.mkdir(parents=True)
    (ecosystem / "discovery.py").write_text(
        'def declared(layer):\n    return layer.get("dimensions")\n',
        encoding="utf-8",
    )
    hook_root = framework_root / ".claude" / "hooks"
    hook_root.mkdir(parents=True)
    (hook_root / "pretool-check.sh").write_text(
        '#!/bin/bash\ncc extensions resolve --agent "$AGENT" --json\n',
        encoding="utf-8",
    )
    (framework_root / "plugins").mkdir()
    (framework_root / "scripts").mkdir()

    monkeypatch.setattr(conformance, "resolve_knowledge_repos", lambda: ["/fixture"])
    monkeypatch.setattr(conformance, "_declared_agent_names", lambda _repos: set())
    monkeypatch.setattr(conformance, "_load_validated_layers", lambda: ())
    monkeypatch.setattr(
        conformance.roundtrip,
        "discover_framework_repo_root",
        lambda: framework_root,
    )
    monkeypatch.setattr(
        conformance, "_run_resolver_effectiveness_machine", lambda: ()
    )

    results = conformance._run_tier_layer_machine()
    aggregate_ids = {
        "tier.precedence.commands_dimension_has_no_consumer",
        "tier.effectiveness.extension_resolution_wired_beyond_prose",
    }
    aggregate = [result for result in results if result.id in aggregate_ids]

    assert len(aggregate) == 2
    assert {result.id for result in aggregate} == aggregate_ids
    assert all(result.verdict is Verdict.PASS for result in aggregate)
    assert sum(
        result.id == "tier.precedence.commands_dimension_has_no_consumer"
        for result in aggregate
    ) == 1
    assert sum(
        result.id == "tier.effectiveness.extension_resolution_wired_beyond_prose"
        for result in aggregate
    ) == 1


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


def test_ordinary_full_roundtrip_accepts_immutable_no_git_source(
    monkeypatch, tmp_path: Path
):
    root = tmp_path / "installed-framework"
    start = root / "tools/cc/src/cc/core/conformance"
    start.mkdir(parents=True)
    (start / "roundtrip.py").write_text("# installed source\n", encoding="utf-8")
    (root / "tools/cc/pyproject.toml").write_text(
        "[project]\nname = 'claude-cli'\n", encoding="utf-8"
    )
    (start / "roundtrip.py").chmod(0o444)
    (root / "tools/cc/pyproject.toml").chmod(0o444)
    (root / ".source-commit").write_text(f"{'a' * 40}\n", encoding="ascii")
    (root / ".source-tree").write_text(f"{'b' * 40}\n", encoding="ascii")
    (root / ".source-commit").chmod(0o444)
    (root / ".source-tree").chmod(0o444)
    root.chmod(0o555)

    monkeypatch.setattr(conformance, "_run_tier_layer_machine", lambda: ())
    monkeypatch.setattr(conformance, "_run_stack_layer_machine", lambda: ())
    monkeypatch.setattr(conformance, "_run_repo_layer", lambda **kwargs: ())
    monkeypatch.setattr(conformance, "_run_lock_layer", lambda **kwargs: ())
    monkeypatch.setattr(
        conformance.root_causes, "run_all_root_cause_checks", lambda: ()
    )

    def run_roundtrip_from_installed_source():
        assert roundtrip.discover_framework_repo_root(start=start) == root
        return (_roundtrip_pass(),)

    monkeypatch.setattr(
        conformance, "_run_roundtrip_layer", run_roundtrip_from_installed_source
    )

    results = conformance._collect_results(
        layers=conformance.FULL_CHECK_LAYERS,
        mode=Mode.FULL,
    )

    assert [result.id for result in results] == ["roundtrip.update.is_idempotent"]
