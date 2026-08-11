from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from cc.core.ecosystem.project_plan_store import PlanRecord
from cc.core.ecosystem.project_reconciliation import assess_project
from cc.core.ecosystem.reconciliation import (
    ReconciliationError,
    assess_reconciliation,
    build_plan_report,
)
from cc.core.ecosystem.reconciliation_recipes import RecipeValidationError
from cc.core.ecosystem.reconciliation_types import parse_reconciliation_request

from cc.core.ecosystem import project_reconciliation as project_module
from cc.core.ecosystem import reconciliation_recipes as recipes


def _request(*, project: str = "/projects/one"):
    return parse_reconciliation_request(
        {
            "schema_version": "1.0",
            "roots": ["/projects"],
            "projects": [{"path": project, "components": ["claude"]}],
        }
    )


def _machine() -> dict:
    return {
        "state": "ready",
        "helper": {
            "state": "ready",
            "version": "2.6.0",
            "path": "/usr/local/bin/cc",
            "detail": "The helper is available.",
        },
        "frameworks": [
            {
                "component": component,
                "state": "ready",
                "path": f"/{component}-framework",
                "version": "1.0.0",
                "detail": f"The {component.title()} framework is ready.",
            }
            for component in ("claude", "codex")
        ],
        "configuration": {
            "state": "ready",
            "path": "/config.json",
            "approved_roots": ["/projects"],
            "detail": "The machine configuration is readable.",
        },
        "authentication": {
            "state": "signed-in",
            "credential_state": "present",
            "detail": "Sign-in is available.",
        },
        "connectivity": {"state": "online", "detail": "Network checks passed."},
        "layers": {
            "state": "ready",
            "ready": 2,
            "total": 2,
            "detail": "Layers are ready.",
        },
        "dependencies": [],
        "blockers": [],
        "next_action": "Nothing needs to be changed.",
    }


def _project(*, path: str = "/projects/one", route: str = "ready") -> dict:
    fingerprint = "sha256:" + ("a" * 64)
    return {
        "path": path,
        "root": "/projects",
        "name": path.rsplit("/", 1)[-1],
        "inspection_id": fingerprint,
        "presence": "claude-only",
        "route": route,
        "selected_components": ["claude"],
        "components": [
            {
                "component": "claude",
                "state": "ready",
                "selected": True,
                "recommended": True,
                "recommendation_reason": "Claude is available.",
                "responsible_actor": "none",
                "evidence": [],
                "missing_requirements": [],
                "next_action": "Nothing needs to be changed.",
                "recipe_options": [],
            },
            {
                "component": "codex",
                "state": "not-selected",
                "selected": False,
                "recommended": False,
                "recommendation_reason": "Codex was not selected.",
                "responsible_actor": "none",
                "evidence": [],
                "missing_requirements": [],
                "next_action": "Nothing needs to be changed.",
                "recipe_options": [],
            },
        ],
        "blockers": [],
        "next_action": "Nothing needs to be changed.",
    }


def _public_plan(*, operations: list | None = None) -> dict:
    return {
        "path": "/projects/one",
        "inspection_id": "sha256:" + ("a" * 64),
        "recipes": [{"component": "claude", "recipe_id": "claude-ready-receipt-v1"}],
        "sources": [],
        "operations": operations or [],
        "preservation": [],
        "prohibited_actions": ["overwrite-project-owned-content"],
        "verification": ["claude-project-integration"],
    }


def _execution_plan(*, operations: list | None = None) -> dict:
    return {"path": "/projects/one", "operations": operations or []}


def _real_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=project, check=True)
    subprocess.run(
        ("git", "config", "user.email", "fixture@example.invalid"),
        cwd=project,
        check=True,
    )
    subprocess.run(("git", "config", "user.name", "Fixture"), cwd=project, check=True)
    return project


def _write(path: Path, value: str, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    path.chmod(mode)


def _claude_source(tmp_path: Path) -> Path:
    source = tmp_path / "claude-source"
    _write(
        source / "VERSION.json",
        json.dumps(
            {
                "framework": "5.13.3",
                "components": {"agents": {"frameworkAgents": ["me"]}},
            }
        ),
    )
    _write(source / ".claude/commands/protocol.md", "protocol\n")
    _write(source / ".claude/commands/continue.md", "continue\n")
    _write(source / ".claude/fitness-check.sh", "#!/bin/sh\nexit 0\n", mode=0o755)
    _write(source / ".claude/hooks/copilot-hook.sh", "#!/bin/sh\nexit 0\n", mode=0o755)
    _write(source / ".claude/agents/me.md", "me\n")
    _write(source / ".claude/agents/kc.md", "kc\n")
    return source


def _empty_integration_report() -> dict:
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


def _real_recipe_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    source: Path,
) -> tuple[Path, dict, dict]:
    project = _real_project(tmp_path)

    def resolve(key: str) -> str | None:
        if key == "paths.claude_copilot_root":
            return str(source)
        return None

    monkeypatch.setattr(recipes, "resolve_key", resolve)
    monkeypatch.setattr(project_module, "resolve_key", resolve)
    monkeypatch.setattr(project_module, "is_project_excluded", lambda _path: False)
    monkeypatch.setattr(
        project_module,
        "inspect_project_integration",
        lambda _path, detail: _empty_integration_report(),
    )
    assessment = assess_project(
        project,
        approved_root=tmp_path,
        selected_components=("claude",),
    )
    machine = _machine()
    machine["configuration"]["approved_roots"] = [str(tmp_path)]
    return project, assessment, machine


def _real_recipe_request(root: Path, project: Path, recipe_id: str):
    return parse_reconciliation_request(
        {
            "schema_version": "1.0",
            "roots": [str(root)],
            "projects": [
                {
                    "path": str(project),
                    "components": ["claude"],
                    "recipe_ids": {"claude": recipe_id},
                }
            ],
        }
    )


def test_real_plan_record_shape_is_supported() -> None:
    record = PlanRecord(
        plan_id="plan_" + ("3" * 32),
        state="reviewed",
        request_fingerprint="sha256:" + ("4" * 64),
        fresh_plan_fingerprint="sha256:" + ("5" * 64),
        binding_fingerprint="sha256:" + ("6" * 64),
        helper_version="2.6.0",
        schema_version="1.0",
        created_at="2026-08-04T18:00:00Z",
        expires_at="2026-08-04T18:15:00Z",
        plans=(_public_plan(),),
        canonical_request=_request().as_dict(),
    )

    report = build_plan_report(
        _request(),
        machine_builder=_machine,
        census_builder=lambda **_kwargs: [_project()],
        plan_builder=lambda **_kwargs: ([_public_plan()], [_execution_plan()]),
        plan_issuer=lambda **_kwargs: record,
        run_id="run_" + ("7" * 32),
    )

    assert report["plan_id"] == record.plan_id
    assert report["expires_at"] == record.expires_at


@pytest.mark.parametrize(
    "recipe_id",
    [
        "unknown-reviewed-recipe-v1",
        "codex-project-update-v1",
        "claude-ineligible-route-v1",
    ],
)
def test_recipe_selection_failures_map_to_typed_invalid_recipe(
    recipe_id: str,
) -> None:
    request = parse_reconciliation_request(
        {
            "schema_version": "1.0",
            "roots": ["/projects"],
            "projects": [
                {
                    "path": "/projects/one",
                    "components": ["claude"],
                    "recipe_ids": {"claude": recipe_id},
                }
            ],
        }
    )

    def reject(**kwargs):
        assert kwargs["recipe_ids"]["/projects/one"]["claude"] == recipe_id
        raise RecipeValidationError("untrusted internal recipe detail")

    with pytest.raises(ReconciliationError) as raised:
        build_plan_report(
            request,
            machine_builder=_machine,
            census_builder=lambda **_kwargs: [_project()],
            plan_builder=reject,
        )

    assert (raised.value.code, raised.value.exit_code) == ("invalid-recipe", 2)
    assert "untrusted internal" not in raised.value.detail


def test_authoritative_recipe_source_failure_maps_to_business_block() -> None:
    def unavailable(**_kwargs):
        raise RecipeValidationError(
            "authoritative source file /private/sentinel was unavailable"
        )

    with pytest.raises(ReconciliationError) as raised:
        build_plan_report(
            _request(),
            machine_builder=_machine,
            census_builder=lambda **_kwargs: [_project()],
            plan_builder=unavailable,
        )

    assert (raised.value.code, raised.value.exit_code) == ("recipe-unavailable", 1)
    assert "/private/sentinel" not in raised.value.detail


@pytest.mark.parametrize(
    "recipe_id",
    [
        "unknown-recipe-v1",
        "codex-project-setup-v1",
        "claude-canonical-entry-v1",
    ],
)
def test_production_recipe_registry_failures_map_to_invalid_recipe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recipe_id: str,
) -> None:
    source = _claude_source(tmp_path)
    project, assessment, machine = _real_recipe_context(
        tmp_path, monkeypatch, source=source
    )
    assert assessment["components"][0]["state"] == "safe-setup-available"

    with pytest.raises(ReconciliationError) as raised:
        build_plan_report(
            _real_recipe_request(tmp_path, project, recipe_id),
            machine_builder=lambda: machine,
            census_builder=lambda **_kwargs: [assessment],
        )

    assert (raised.value.code, raised.value.exit_code) == ("invalid-recipe", 2)
    assert recipe_id not in raised.value.detail


def test_production_recipe_missing_authoritative_source_maps_to_business_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_source = tmp_path / "private-missing-source"
    project, assessment, machine = _real_recipe_context(
        tmp_path, monkeypatch, source=missing_source
    )
    assert assessment["components"][0]["state"] == "source-unavailable"
    assert assessment["route"] == "source-unavailable"
    assert assessment["components"][0]["recommended"] is False

    with pytest.raises(ReconciliationError) as raised:
        build_plan_report(
            _real_recipe_request(
                tmp_path,
                project,
                "claude-project-setup-v1",
            ),
            machine_builder=lambda: machine,
            census_builder=lambda **_kwargs: [assessment],
        )

    assert (raised.value.code, raised.value.exit_code) == ("recipe-unavailable", 1)
    assert str(missing_source) not in raised.value.detail


def test_census_exception_maps_to_safe_invalid_project_authority() -> None:
    def fail_census(**_kwargs):
        raise RuntimeError("/private/project and secret content")

    with pytest.raises(ReconciliationError) as raised:
        build_plan_report(
            _request(),
            machine_builder=_machine,
            census_builder=fail_census,
        )

    assert (raised.value.code, raised.value.exit_code) == (
        "invalid-project-authority",
        2,
    )
    assert "/private/project" not in raised.value.detail
    assert "secret content" not in raised.value.detail


def test_selected_project_must_be_beneath_requested_root() -> None:
    with pytest.raises(ReconciliationError, match="contained"):
        build_plan_report(
            _request(project="/elsewhere/one"),
            machine_builder=_machine,
            census_builder=lambda **_kwargs: [_project(path="/elsewhere/one")],
            plan_builder=lambda **_kwargs: ([], []),
        )


def test_selected_project_must_appear_once_in_fresh_census() -> None:
    with pytest.raises(ReconciliationError, match="every selected project"):
        build_plan_report(
            _request(),
            machine_builder=_machine,
            census_builder=lambda **_kwargs: [],
            plan_builder=lambda **_kwargs: ([], []),
        )


def test_plan_fingerprint_binds_complete_machine_safety_evidence() -> None:
    fingerprints: list[str] = []

    def issue(**kwargs):
        fingerprints.append(kwargs["fresh_plan_fingerprint"])
        return {
            "plan_id": "plan_" + (str(len(fingerprints)) * 32),
            "expires_at": "2026-08-04T18:15:00Z",
        }

    first = _machine()
    second = deepcopy(first)
    second["authentication"]["state"] = "could-not-verify"
    second["authentication"]["detail"] = "The credential store is unavailable."

    for machine in (first, second):
        build_plan_report(
            _request(),
            machine_builder=lambda value=machine: value,
            census_builder=lambda **_kwargs: [_project()],
            plan_builder=lambda **_kwargs: (
                [_public_plan()],
                [_execution_plan()],
            ),
            plan_issuer=issue,
        )

    assert fingerprints[0] != fingerprints[1]


def test_plan_fingerprint_ignores_unselected_census_changes() -> None:
    fingerprints: list[str] = []

    def issue(**kwargs):
        fingerprints.append(kwargs["fresh_plan_fingerprint"])
        return {
            "plan_id": "plan_" + (str(len(fingerprints)) * 32),
            "expires_at": "2026-08-04T18:15:00Z",
        }

    unrelated = _project(path="/projects/unrelated")
    unrelated["selected_components"] = []
    for component in unrelated["components"]:
        component["selected"] = False
    changed_unrelated = deepcopy(unrelated)
    changed_unrelated["route"] = "held"
    changed_unrelated["components"][0]["state"] = "held"

    for peer in (unrelated, changed_unrelated):
        build_plan_report(
            _request(),
            machine_builder=_machine,
            census_builder=lambda peer=peer, **_kwargs: [_project(), peer],
            plan_builder=lambda **_kwargs: (
                [_public_plan()],
                [_execution_plan()],
            ),
            plan_issuer=issue,
        )

    assert fingerprints[0] == fingerprints[1]


def test_unsafe_project_cannot_smuggle_operations_into_a_plan() -> None:
    operation = {
        "id": "op_" + ("8" * 64),
        "kind": "create-file-from-source",
        "component": "claude",
        "target": "CLAUDE.md",
        "description": "Create the portable Claude entry point.",
        "expected_before_fingerprint": "sha256:" + ("9" * 64),
        "source_fingerprint": "sha256:" + ("a" * 64),
    }

    with pytest.raises(ReconciliationError, match="cannot contain operations"):
        build_plan_report(
            _request(),
            machine_builder=_machine,
            census_builder=lambda **_kwargs: [_project(route="held")],
            plan_builder=lambda **_kwargs: (
                [_public_plan(operations=[operation])],
                [{"path": "/projects/one"}],
            ),
        )


def test_unknown_or_duplicate_census_routes_fail_closed() -> None:
    invalid = _project(route="surprising")
    with pytest.raises(ReconciliationError, match="unsupported project route"):
        assess_reconciliation(
            machine_builder=_machine,
            census_builder=lambda **_kwargs: [invalid],
        )

    with pytest.raises(ReconciliationError, match="repeated project path"):
        assess_reconciliation(
            machine_builder=_machine,
            census_builder=lambda **_kwargs: [_project(), _project()],
        )


def test_assessment_authors_component_scoped_safe_default_batch_and_exact_counts() -> None:
    def unselected(path: str, *, presence: str, route: str) -> dict:
        project = _project(path=path, route=route)
        project["presence"] = presence
        project["selected_components"] = []
        for component in project["components"]:
            component.update(
                {
                    "state": "not-present",
                    "selected": False,
                    "recommended": True,
                    "responsible_actor": "person",
                }
            )
        return project

    def selected(
        project: dict,
        *,
        route: str,
        component_states: tuple[str, str],
        recommended: tuple[bool, bool] = (True, True),
    ) -> dict:
        result = deepcopy(project)
        result["route"] = route
        result["selected_components"] = ["claude", "codex"]
        for component, state, is_recommended in zip(
            result["components"], component_states, recommended, strict=True
        ):
            component.update(
                {
                    "state": state,
                    "selected": True,
                    "recommended": is_recommended,
                    "responsible_actor": "cli",
                    "recipe_options": [],
                }
            )
        return result

    new = unselected(
        "/projects/new", presence="none", route="copilot-not-present"
    )
    correction = unselected(
        "/projects/correction", presence="claude-only", route="ready"
    )
    correction["components"][0]["state"] = "ready"
    ready = unselected("/projects/ready", presence="both", route="ready")
    for component in ready["components"]:
        component["state"] = "ready"
    review = unselected(
        "/projects/review", presence="none", route="copilot-not-present"
    )

    baseline = [new, correction, ready, review]
    trial = [
        selected(
            new,
            route="safe-setup-available",
            component_states=("safe-setup-available", "safe-setup-available"),
        ),
        selected(
            correction,
            route="safe-setup-available",
            component_states=("ready", "safe-setup-available"),
        ),
        ready,
        selected(
            review,
            route="held",
            component_states=("held", "held"),
            recommended=(False, False),
        ),
    ]
    trial[1]["selected_components"] = ["codex"]
    trial[1]["components"][0]["selected"] = False

    def census(**kwargs):
        return deepcopy(trial if kwargs.get("selections") else baseline)

    report = assess_reconciliation(
        machine_builder=_machine,
        census_builder=census,
        run_id="run_" + ("9" * 32),
    )

    assert report["default_selection"] == [
        {
            "path": "/projects/new",
            "components": ["claude", "codex"],
            "category": "new-setup",
        },
        {
            "path": "/projects/correction",
            "components": ["codex"],
            "category": "correction",
        },
    ]
    assert report["batch_summary"] == {
        "new_setup": 1,
        "correction": 1,
        "ready": 1,
        "needs_review": 1,
        "selected": 2,
        "total": 4,
        "product_projects": 4,
        "managed_separately": 0,
    }
    assert report["resolution_summary"] == {
        "automatic": 2,
        "claude_assisted": 0,
        "total_actionable": 2,
        "managed_separately": 0,
        "left_unchanged": {
            "held": 1,
            "owner_decision": 0,
            "could_not_verify": 0,
            "excluded": 0,
            "source_unavailable": 0,
            "other": 0,
        },
        "new_setup": 1,
        "correction": 1,
    }
    assert report["summary"]["selected_projects"] == 2
    assert report["machine_summary"] == {
        "state": "ready",
        "title": "This Mac has what it needs.",
        "detail": "Control Tower can safely prepare reviewed project plans.",
    }


def test_safe_component_is_selected_when_sibling_requires_owner_decision() -> None:
    baseline = _project(path="/projects/mixed", route="owner-decision")
    baseline.update({"presence": "both", "selected_components": []})
    baseline["components"][0].update(
        {
            "state": "safe-update-available",
            "selected": False,
            "recommended": True,
        }
    )
    baseline["components"][1].update(
        {
            "state": "owner-decision",
            "selected": False,
            "recommended": False,
        }
    )

    selected = deepcopy(baseline)
    selected.update(
        {"route": "safe-update-available", "selected_components": ["claude"]}
    )
    selected["components"][0].update(
        {
            "state": "safe-update-available",
            "selected": True,
            "recommended": True,
            "recipe_options": [],
        }
    )

    report = assess_reconciliation(
        machine_builder=_machine,
        census_builder=lambda **kwargs: [
            deepcopy(selected if kwargs.get("selections") else baseline)
        ],
    )

    assert report["default_selection"] == [
        {
            "path": "/projects/mixed",
            "components": ["claude"],
            "category": "correction",
        }
    ]


def test_ecosystem_repositories_are_counted_but_never_enter_project_batch() -> None:
    product = _project(path="/projects/product")
    product.update(
        {
            "presence": "both",
            "selected_components": [],
            "scope": {"kind": "product-project"},
        }
    )
    for component in product["components"]:
        component.update({"state": "ready", "selected": False})
    managed = _project(path="/projects/claude-foundation", route="ecosystem-managed")
    managed.update(
        {
            "presence": "unknown",
            "selected_components": [],
            "scope": {
                "kind": "ecosystem-repository",
                "product": "claude",
                "role": "foundation",
                "layer_id": "claude-foundation",
                "repository": "owner/claude-foundation",
            },
        }
    )
    for component in managed["components"]:
        component.update(
            {
                "state": "not-applicable",
                "selected": False,
                "recommended": False,
            }
        )

    report = assess_reconciliation(
        machine_builder=_machine,
        census_builder=lambda **_kwargs: [deepcopy(managed), deepcopy(product)],
    )

    assert report["result"] == "ready"
    assert report["default_selection"] == []
    assert report["batch_summary"] == {
        "new_setup": 0,
        "correction": 0,
        "ready": 1,
        "needs_review": 0,
        "selected": 0,
        "total": 2,
        "product_projects": 1,
        "managed_separately": 1,
    }
    assert report["summary"]["scope_counts"] == {
        "total_repositories": 2,
        "product_projects": 1,
        "ecosystem_repositories": 1,
    }
    assert report["resolution_summary"]["managed_separately"] == 1

    with pytest.raises(ReconciliationError) as raised:
        build_plan_report(
            _request(project="/projects/claude-foundation"),
            machine_builder=_machine,
            census_builder=lambda **_kwargs: [deepcopy(managed)],
        )
    assert raised.value.code == "ecosystem-repository-selected"


def test_left_unchanged_counts_are_typed_dispositions_not_a_residual() -> None:
    routes = (
        "held",
        "owner-decision",
        "could-not-verify",
        "excluded",
        "source-unavailable",
    )
    baseline: list[dict] = []
    trial: list[dict] = []
    for index, route in enumerate(routes):
        project = _project(path=f"/projects/project-{index}", route=route)
        project.update({"presence": "both", "selected_components": []})
        for component in project["components"]:
            component.update(
                {
                    "state": route,
                    "selected": False,
                    "recommended": False,
                }
            )
        baseline.append(project)
        selected = deepcopy(project)
        selected["selected_components"] = ["claude", "codex"]
        for component in selected["components"]:
            component["selected"] = True
        trial.append(selected)

    report = assess_reconciliation(
        machine_builder=_machine,
        census_builder=lambda **kwargs: deepcopy(
            trial if kwargs.get("selections") else baseline
        ),
    )

    assert report["resolution_summary"]["left_unchanged"] == {
        "held": 1,
        "owner_decision": 1,
        "could_not_verify": 1,
        "excluded": 1,
        "source_unavailable": 1,
        "other": 0,
    }
    assert "held" not in {
        key
        for key in report["resolution_summary"]
        if key != "left_unchanged"
    }


def test_ambiguous_custom_recipe_is_never_default_selected() -> None:
    baseline = _project(route="customized-guided-route")
    baseline["presence"] = "both"
    baseline["selected_components"] = []
    for component in baseline["components"]:
        component.update({"selected": False, "state": "customized-guided-route"})

    trial = deepcopy(baseline)
    trial["selected_components"] = ["claude", "codex"]
    for component in trial["components"]:
        component.update(
            {
                "selected": True,
                "recommended": True,
                "state": "customized-guided-route",
                "recipe_options": [
                    {
                        "recipe_id": f"{component['component']}.option-one.v1",
                        "component": component["component"],
                        "summary": "First reviewed route.",
                    },
                    {
                        "recipe_id": f"{component['component']}.option-two.v1",
                        "component": component["component"],
                        "summary": "Second reviewed route.",
                    },
                ],
            }
        )

    report = assess_reconciliation(
        machine_builder=_machine,
        census_builder=lambda **kwargs: [
            deepcopy(trial if kwargs.get("selections") else baseline)
        ],
        run_id="run_" + ("8" * 32),
    )

    assert report["default_selection"] == []
    assert report["batch_summary"]["needs_review"] == 1
