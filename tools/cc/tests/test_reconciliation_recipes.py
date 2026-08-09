from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from cc.core.ecosystem.project_locking import fingerprint_missing
from cc.core.ecosystem.project_reconciliation import assess_project, build_project_plans
from cc.core.ecosystem.reconciliation_recipes import (
    DEFAULT_RECIPE_REGISTRY,
    RecipeDefinition,
    RecipeOperation,
    RecipeRegistry,
    RecipeValidationError,
    authoritative_source_available,
    build_recipe_plan,
    validated_source_root,
)
from cc.core.ecosystem.reconciliation_transaction import (
    execute_reconciliation,
    transaction_plan_from_recipe,
)
from cc.core.ecosystem.reconciliation_types import ComponentRoute, RecipeOperationKind

from cc.core.ecosystem import project_integration as integration_module
from cc.core.ecosystem import project_reconciliation as project_module
from cc.core.ecosystem import reconciliation_recipes as recipes

SCHEMA = Path(__file__).parent / "fixtures/schemas/reconcile.schema.json"


def _git(project: Path, *arguments: str) -> None:
    subprocess.run(
        ("git", *arguments),
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    )


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-q")
    _git(project, "config", "user.email", "fixture@example.invalid")
    _git(project, "config", "user.name", "Fixture")
    return project


def _write(path: Path, value: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    path.chmod(mode)


def _framework_sources(tmp_path: Path) -> tuple[Path, Path]:
    claude = tmp_path / "claude-source"
    codex = tmp_path / "codex-source"
    _write(
        claude / "VERSION.json",
        json.dumps(
            {
                "framework": "5.13.3",
                "version": "wrong-generic-version",
                "components": {"agents": {"frameworkAgents": ["me"]}},
            }
        ),
    )
    _write(claude / ".claude/commands/protocol.md", "protocol\n")
    _write(claude / ".claude/commands/continue.md", "continue\n")
    _write(claude / ".claude/fitness-check.sh", "#!/bin/sh\nexit 0\n", 0o755)
    _write(claude / ".claude/hooks/copilot-hook.sh", "#!/bin/sh\nexit 0\n", 0o755)
    _write(claude / ".claude/agents/me.md", "me\n")
    _write(claude / ".claude/agents/kc.md", "kc\n")

    _write(
        codex / "plugins/codex-copilot/.codex-plugin/plugin.json",
        json.dumps({"name": "codex-copilot", "version": "0.6.1"}),
    )
    _write(codex / "plugins/codex-copilot/skills/me/SKILL.md", "skill\n")
    _write(codex / "scripts/copilot-gate.sh", "#!/bin/sh\nexit 0\n", 0o755)
    return claude, codex


def _empty_report(path: Path) -> dict[str, Any]:
    return {
        "inspection": {"id": "sha256:" + "2" * 64},
        "components": [
            {
                "component": component,
                "classification": "safe-finish",
                "recognized_setup": None,
                "missing_requirements": [
                    {
                        "id": "component-setup",
                        "detail": f"The {component.title()} integration is absent.",
                    }
                ],
            }
            for component in ("claude", "codex")
        ],
        "preservation": {"must_preserve": []},
    }


def _configure_sources(
    monkeypatch: pytest.MonkeyPatch, claude: Path, codex: Path
) -> None:
    def resolve(key: str) -> str | None:
        if key == "paths.claude_copilot_root":
            return str(claude)
        if key == "paths.codex_copilot_root":
            return str(codex)
        return None

    monkeypatch.setattr(recipes, "resolve_key", resolve)
    monkeypatch.setattr(project_module, "resolve_key", resolve)
    monkeypatch.setattr(integration_module, "resolve_key", resolve)
    monkeypatch.setattr(project_module, "is_project_excluded", lambda path: False)


def test_configured_framework_compatibility_symlink_resolves_to_verified_source(
    tmp_path: Path,
) -> None:
    claude, _ = _framework_sources(tmp_path)
    compatibility_link = tmp_path / "installed-claude-source"
    compatibility_link.symlink_to(claude, target_is_directory=True)

    assert validated_source_root("claude", compatibility_link) == claude.resolve()
    assert authoritative_source_available("claude", compatibility_link) is True


def test_configured_framework_symlink_rejects_unprotected_target(
    tmp_path: Path,
) -> None:
    claude, _ = _framework_sources(tmp_path)
    claude.chmod(0o777)
    compatibility_link = tmp_path / "installed-claude-source"
    compatibility_link.symlink_to(claude, target_is_directory=True)

    assert authoritative_source_available("claude", compatibility_link) is False
    with pytest.raises(RecipeValidationError):
        validated_source_root("claude", compatibility_link)


def _selected_assessment(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    monkeypatch.setattr(
        project_module,
        "inspect_project_integration",
        lambda path, detail: _empty_report(Path(path)),
    )
    return assess_project(
        project,
        approved_root=project.parent,
        selected_components=("claude", "codex"),
    )


def _project_plan_validator() -> jsonschema.Draft202012Validator:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(
        {"$ref": "#/$defs/projectPlan", "$defs": schema["$defs"]}
    )


def test_both_component_plan_is_closed_unique_and_schema_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    claude, codex = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude, codex)
    assessment = _selected_assessment(project, monkeypatch)

    public, internal = build_project_plans(
        [assessment], {str(project): ("claude", "codex")}
    )
    assert len(public) == len(internal) == 1
    _project_plan_validator().validate(public[0])
    assert "expected_identity" not in public[0]
    assert "expected_identity" in internal[0].transaction_spec()
    targets = [operation.target for operation in internal[0].operations]
    assert len(targets) == len(set(targets))
    lock = next(
        operation
        for operation in internal[0].operations
        if operation.kind == RecipeOperationKind.UPSERT_LOCK_COMPONENT
    )
    entries = lock.payload["component_entry"]
    assert [entry["component"] for entry in entries] == ["claude", "codex"]
    assert {entry["component"]: entry["version"] for entry in entries} == {
        "claude": "5.13.3",
        "codex": "0.6.1",
    }
    transaction = internal[0].transaction_plan()
    assert (
        transaction.expected_identity.fingerprint
        == internal[0].expected_identity.fingerprint
    )


def test_claude_repair_records_only_matching_existing_agent_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    claude, codex = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude, codex)
    _write(project / ".claude/agents/me.md", "me\n")

    operations = recipes._claude_setup(project, "claude")
    lock_operation = next(
        operation
        for operation in operations
        if operation.kind == RecipeOperationKind.UPSERT_LOCK_COMPONENT
    )
    recorded = {
        item["path"] for item in lock_operation.payload["component_entry"]["files"]
    }

    assert ".claude/agents/me.md" in recorded
    assert ".claude/agents/kc.md" not in recorded
    assert not any(
        operation.target == ".claude/agents/kc.md" for operation in operations
    )


@pytest.mark.parametrize(
    "route",
    [
        "ready",
        "not-present",
        "not-selected",
        "held",
        "owner-decision",
        "could-not-verify",
        "excluded",
    ],
)
def test_zero_operation_receipts_validate_for_every_non_action_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
) -> None:
    project = _project(tmp_path)
    claude, codex = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude, codex)
    assessment = _selected_assessment(project, monkeypatch)
    assessment["route"] = route
    for component in assessment["components"]:
        component["state"] = route
    monkeypatch.setattr(
        project_module, "assess_project", lambda *args, **kwargs: assessment
    )
    public, internal = build_project_plans(
        [assessment], {str(project): ("claude", "codex")}
    )
    assert public[0]["operations"] == []
    _project_plan_validator().validate(public[0])
    with pytest.raises(RecipeValidationError, match="cannot be executed"):
        internal[0].transaction_plan()


def test_unknown_recipe_operation_and_target_fail_closed(tmp_path: Path) -> None:
    fingerprint = "sha256:" + "0" * 64
    with pytest.raises(RecipeValidationError, match="closed set"):
        RecipeOperation(
            id="op_" + "0" * 64,
            kind="shell",  # type: ignore[arg-type]
            component="claude",
            target="CLAUDE.md",
            description="invalid",
            expected_before_fingerprint=fingerprint,
            source_fingerprint=None,
            payload={},
        )
    with pytest.raises(RecipeValidationError, match="relative to the project"):
        RecipeOperation(
            id="op_" + "0" * 64,
            kind=RecipeOperationKind.APPEND_MANAGED_BLOCK,
            component="claude",
            target="../../outside",
            description="invalid",
            expected_before_fingerprint=fingerprint,
            source_fingerprint=None,
            payload={"block": "bounded"},
        )


def test_unknown_or_mismatched_explicit_recipe_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    claude, codex = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude, codex)
    assessment = _selected_assessment(project, monkeypatch)
    with pytest.raises(RecipeValidationError, match="does not apply"):
        build_project_plans(
            [assessment],
            {str(project): ("claude", "codex")},
            {str(project): {"claude": "codex-project-setup-v1"}},
        )
    with pytest.raises(RecipeValidationError, match="not in the reviewed registry"):
        build_project_plans(
            [assessment],
            {str(project): ("claude", "codex")},
            {str(project): {"claude": "unknown-recipe-v1"}},
        )
    assert "unknown-recipe-v1" not in DEFAULT_RECIPE_REGISTRY.ids


def test_production_custom_recipes_are_component_scoped_and_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    claude, codex = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude, codex)
    report = _empty_report(project)
    for component in report["components"]:
        component["classification"] = "guided-integration"
        component["missing_requirements"] = (
            [
                {
                    "id": "compatible-claude-entry",
                    "detail": "The Claude entry needs a reviewed merge.",
                },
                {
                    "id": "valid-mcp-marker",
                    "detail": "The Claude MCP marker is missing.",
                },
            ]
            if component["component"] == "claude"
            else [
                {
                    "id": identifier,
                    "detail": "The Codex setup target is missing.",
                }
                for identifier in (
                    "compatible-codex-entry",
                    "valid-codex-config",
                    "valid-plugin-manifest",
                    "internal-skill-link",
                )
            ]
        )
    monkeypatch.setattr(
        project_module,
        "inspect_project_integration",
        lambda path, detail: report,
    )
    assessment = assess_project(
        project,
        approved_root=tmp_path,
        selected_components=("claude", "codex"),
    )
    assert assessment["route"] == "customized-guided-route"
    recipe_ids = {
        component["component"]: component["recipe_options"][0]["recipe_id"]
        for component in assessment["components"]
    }
    assert all(component["recipe_options"] for component in assessment["components"])

    with pytest.raises(RecipeValidationError, match="requires one reviewed"):
        build_project_plans([assessment], {str(project): ("claude", "codex")})

    public, internal = build_project_plans(
        [assessment],
        {str(project): ("claude", "codex")},
        {str(project): recipe_ids},
    )
    assert public[0]["recipes"] == [
        {
            "component": "claude",
            "recipe_id": "claude.customized-preserve-entry.v1",
        },
        {
            "component": "codex",
            "recipe_id": "codex.customized-preserve-entry.v1",
        },
    ]
    assert internal[0].operations
    assert {source["component"] for source in public[0]["sources"]} == {
        "claude",
        "codex",
    }
    assert {source["version"] for source in public[0]["sources"]} == {
        "5.13.3",
        "0.6.1",
    }
    assert {operation.component for operation in internal[0].operations} == {
        "claude",
        "codex",
    }
    _project_plan_validator().validate(public[0])


def test_reviewed_custom_recipe_uses_only_typed_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    claude, codex = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude, codex)
    assessment = _selected_assessment(project, monkeypatch)
    assessment["selected_components"] = ["claude"]
    assessment["components"][0]["state"] = "customized-guided-route"
    assessment["components"][1]["selected"] = False
    assessment["components"][1]["state"] = "not-selected"

    def reviewed_builder(root: Path, component: str) -> tuple[RecipeOperation, ...]:
        del root
        return (
            RecipeOperation(
                id="op_" + "c" * 64,
                kind=RecipeOperationKind.APPEND_MANAGED_BLOCK,
                component=component,
                target="CLAUDE.md",
                description="Append one reviewed bounded custom-project entry.",
                expected_before_fingerprint=fingerprint_missing(),
                source_fingerprint=None,
                payload={"block": "## Claude Copilot\n"},
            ),
        )

    registry = RecipeRegistry(
        (
            RecipeDefinition(
                "claude-reviewed-custom-entry-v1",
                "claude",
                frozenset({ComponentRoute.CUSTOMIZED_GUIDED_ROUTE}),
                reviewed_builder,
            ),
        )
    )
    plan = build_recipe_plan(
        assessment,
        ("claude",),
        explicit_recipe_ids={"claude": "claude-reviewed-custom-entry-v1"},
        registry=registry,
    )
    assert [operation.kind for operation in plan.operations] == [
        RecipeOperationKind.APPEND_MANAGED_BLOCK,
        RecipeOperationKind.MERGE_JSON_KEYS,
    ]
    assert plan.transaction_spec()["selected_components"] == ["claude"]
    _project_plan_validator().validate(plan.public_dict())


def test_single_component_recipe_preserves_peer_declaration_and_project_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    _write(
        project / "copilot.project.json",
        json.dumps(
            {
                "schema_version": "1.0",
                "components": ["claude", "codex"],
                "project_owned_note": "preserve me",
            }
        ),
    )
    claude, codex = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude, codex)
    assessment = _selected_assessment(project, monkeypatch)
    assessment["presence"] = "both"
    assessment["route"] = "customized-guided-route"
    assessment["selected_components"] = ["claude"]
    assessment["components"][0]["state"] = "customized-guided-route"
    assessment["components"][1]["selected"] = False
    assessment["components"][1]["state"] = "ready"

    def reviewed_builder(root: Path, component: str) -> tuple[RecipeOperation, ...]:
        del root
        return (
            RecipeOperation(
                id="op_" + "d" * 64,
                kind=RecipeOperationKind.APPEND_MANAGED_BLOCK,
                component=component,
                target="CLAUDE.md",
                description="Append one reviewed bounded custom-project entry.",
                expected_before_fingerprint=fingerprint_missing(),
                source_fingerprint=None,
                payload={"block": "## Claude Copilot\n"},
            ),
        )

    registry = RecipeRegistry(
        (
            RecipeDefinition(
                "claude-reviewed-custom-entry-v1",
                "claude",
                frozenset({ComponentRoute.CUSTOMIZED_GUIDED_ROUTE}),
                reviewed_builder,
            ),
        )
    )
    plan = build_recipe_plan(
        assessment,
        ("claude",),
        explicit_recipe_ids={"claude": "claude-reviewed-custom-entry-v1"},
        registry=registry,
    )
    declaration = plan.operations[-1]
    assert declaration.kind == RecipeOperationKind.MERGE_JSON_KEYS
    assert declaration.payload["keys"]["components"] == ["claude", "codex"]

    monkeypatch.setattr(
        project_module, "assess_project", lambda *args, **kwargs: assessment
    )
    receipt = execute_reconciliation(
        [transaction_plan_from_recipe(plan, verifier=lambda _: True)],
        run_id="run_" + "d" * 32,
        root=tmp_path / "transaction-state",
    )[0]
    assert receipt["status"] == "applied"
    declaration_document = json.loads(
        (project / "copilot.project.json").read_text(encoding="utf-8")
    )
    assert declaration_document["components"] == ["claude", "codex"]
    assert declaration_document["project_owned_note"] == "preserve me"


def test_both_component_apply_and_repeat_proposes_zero_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    claude, codex = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude, codex)
    monkeypatch.setattr(
        project_module,
        "inspect_project_integration",
        integration_module.inspect_project_integration,
    )
    assessment = assess_project(
        project,
        approved_root=tmp_path,
        selected_components=("claude", "codex"),
    )
    assert assessment["route"] == "safe-setup-available"
    _, plans = build_project_plans([assessment], {str(project): ("claude", "codex")})

    state = tmp_path / "transaction-state"
    receipts = execute_reconciliation(
        [plans[0].transaction_plan()],
        run_id="run_" + "a" * 32,
        root=state,
    )
    assert receipts[0]["status"] == "applied"
    diagnostic = json.loads(
        (
            state
            / "diagnostics/reconciliation-run_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json"
        ).read_text(encoding="utf-8")
    )
    assert {
        source["component"]: source["version"]
        for source in diagnostic["projects"][0]["evidence"]["sources"]
    } == {"claude": "5.13.3", "codex": "0.6.1"}
    assert all(
        source["fingerprint"].startswith("sha256:")
        for source in diagnostic["projects"][0]["evidence"]["sources"]
    )
    verified = project_module.inspect_project_integration(project, detail=True)
    assert {item["classification"] for item in verified["components"]} == {"ready"}

    _configure_sources(monkeypatch, claude, codex)
    repeat = assess_project(
        project,
        approved_root=tmp_path,
        selected_components=("claude", "codex"),
    )
    public, repeat_plans = build_project_plans(
        [repeat], {str(project): ("claude", "codex")}
    )
    assert public[0]["operations"] == []
    assert repeat_plans[0].operations == ()


def test_sequential_claude_then_codex_apply_moves_shared_declaration_evidence_and_repeats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    _write(
        project / "copilot.project.json",
        json.dumps(
            {
                "schema_version": "1.0",
                "components": ["claude"],
                "project_owned_note": "preserve through both applies",
            }
        ),
    )
    _git(project, "add", "-A")
    _git(project, "commit", "-qm", "initial declaration")
    claude, codex = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude, codex)
    monkeypatch.setattr(
        project_module,
        "inspect_project_integration",
        integration_module.inspect_project_integration,
    )

    claude_assessment = assess_project(
        project, approved_root=tmp_path, selected_components=("claude",)
    )
    _, claude_plans = build_project_plans(
        [claude_assessment], {str(project): ("claude",)}
    )
    first = execute_reconciliation(
        [claude_plans[0].transaction_plan()],
        run_id="run_" + "c" * 32,
        root=tmp_path / "transaction-state",
    )
    assert first[0]["status"] == "applied"
    _git(project, "add", "-A")
    _git(project, "commit", "-qm", "apply Claude")

    codex_assessment = assess_project(
        project, approved_root=tmp_path, selected_components=("codex",)
    )
    assert codex_assessment["route"] == "safe-setup-available"
    _, codex_plans = build_project_plans([codex_assessment], {str(project): ("codex",)})
    second = execute_reconciliation(
        [codex_plans[0].transaction_plan()],
        run_id="run_" + "d" * 32,
        root=tmp_path / "transaction-state",
    )
    assert second[0]["status"] == "applied"

    lock = json.loads((project / "copilot.lock.json").read_text(encoding="utf-8"))
    entries = {entry["component"]: entry for entry in lock["components"]}
    assert "copilot.project.json" not in {
        output["path"] for output in entries["claude"].get("managed_outputs", [])
    }
    assert [
        output["path"]
        for output in entries["codex"].get("managed_outputs", [])
        if output["path"] == "copilot.project.json"
    ] == ["copilot.project.json"]
    declaration = json.loads(
        (project / "copilot.project.json").read_text(encoding="utf-8")
    )
    assert declaration["components"] == ["claude", "codex"]
    assert declaration["project_owned_note"] == "preserve through both applies"

    repeat = assess_project(
        project,
        approved_root=tmp_path,
        selected_components=("claude", "codex"),
    )
    assert repeat["route"] == "ready"
    public, repeat_plans = build_project_plans(
        [repeat], {str(project): ("claude", "codex")}
    )
    assert public[0]["operations"] == []
    assert repeat_plans[0].operations == ()


def test_changed_source_blocks_without_project_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    claude, codex = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude, codex)
    assessment = _selected_assessment(project, monkeypatch)
    _, plans = build_project_plans([assessment], {str(project): ("claude", "codex")})
    (codex / "scripts/copilot-gate.sh").write_text("changed\n", encoding="utf-8")
    receipts = execute_reconciliation(
        [plans[0].transaction_plan()],
        run_id="run_" + "b" * 32,
        root=tmp_path / "transaction-state",
    )
    assert receipts[0]["status"] == "blocked"
    assert not (project / "CLAUDE.md").exists()
    assert not (project / "AGENTS.md").exists()
