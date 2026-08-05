from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import jsonschema
import pytest
from cc.core.ecosystem.project_reconciliation import (
    ProjectReconciliationError,
    assess_project,
    build_project_census,
    build_project_plans,
)

from cc.core.ecosystem import project_reconciliation as reconciliation

FIXTURES = Path(__file__).parent / "fixtures/project-reconciliation/cases.json"
SCHEMA = Path(__file__).parent / "fixtures/schemas/reconcile.schema.json"


def _project_validator() -> jsonschema.Draft202012Validator:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(
        {"$ref": "#/$defs/project", "$defs": schema["$defs"]}
    )


def _git(project: Path, *arguments: str) -> None:
    subprocess.run(
        ("git", *arguments),
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    )


def _project(tmp_path: Path, name: str = "project") -> Path:
    project = tmp_path / name
    project.mkdir()
    _git(project, "init", "-q")
    _git(project, "config", "user.email", "fixture@example.invalid")
    _git(project, "config", "user.name", "Fixture")
    return project


def _write(path: Path, value: str, mode: int = 0o644) -> None:
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
    _write(source / ".claude/fitness-check.sh", "#!/bin/sh\nexit 0\n", 0o755)
    _write(source / ".claude/agents/me.md", "me\n")
    _write(source / ".claude/agents/kc.md", "kc\n")
    return source


def _draft(component: str, classification: str) -> dict[str, Any]:
    recognized = None
    missing: list[dict[str, str]] = []
    if classification == "safe-finish":
        missing = [
            {
                "id": "component-setup",
                "detail": f"The {component.title()} integration is absent.",
            }
        ]
    elif classification == "guided-integration":
        missing = [
            {
                "id": "customized-entry",
                "detail": f"The {component.title()} entry needs a reviewed merge.",
            }
        ]
    elif classification == "owner-decision":
        missing = [
            {
                "id": "owner-direction",
                "detail": f"The owner must choose the {component.title()} route.",
            }
        ]
    elif classification == "could-not-verify":
        missing = [
            {
                "id": "safe-recorded-path",
                "detail": f"The {component.title()} evidence follows an external symlink.",
            }
        ]
    elif classification == "ready":
        recognized = {
            "variant_id": f"{component}-tracked-lock-v1",
            "evidence": [],
        }
    return {
        "component": component,
        "classification": classification,
        "recognized_setup": recognized,
        "missing_requirements": missing,
    }


def _report(claude: str, codex: str) -> dict[str, Any]:
    return {
        "inspection": {"id": "sha256:" + "1" * 64},
        "components": [_draft("claude", claude), _draft("codex", codex)],
        "preservation": {"must_preserve": []},
    }


@pytest.fixture
def stable_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setattr(reconciliation, "is_project_excluded", lambda path: False)
    monkeypatch.setattr(reconciliation, "resolve_key", lambda key: str(source))
    monkeypatch.setattr(reconciliation, "_source_available", lambda component: True)
    monkeypatch.setattr(
        reconciliation,
        "DEFAULT_RECIPE_REGISTRY",
        SimpleNamespace(
            eligible=lambda **kwargs: [
                SimpleNamespace(
                    recipe_id=f"{kwargs['component']}.fixture.v1",
                    component=kwargs["component"],
                    summary="Fixture route.",
                    assistant_only=True,
                )
            ]
        ),
    )
    return source


def test_fixture_routes_are_an_exact_primary_partition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stable_environment: Path,
) -> None:
    del stable_environment
    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]
    observed: list[str] = []
    for index, case in enumerate(cases):
        project = _project(tmp_path, f"project-{index}")
        monkeypatch.setattr(
            reconciliation,
            "inspect_project_integration",
            lambda path, detail, case=case: _report(case["claude"], case["codex"]),
        )
        assessment = assess_project(
            project,
            approved_root=tmp_path,
            selected_components=case["selected"],
        )
        assert assessment["route"] == case["route"]
        assert assessment["presence"] == case["presence"]
        assert len(assessment["components"]) == 2
        assert assessment["dossier"]["inspection_id"] == assessment["inspection_id"]
        assert assessment["dossier"]["prohibited_actions"]
        assert assessment["dossier"]["verification"]
        assert assessment["dossier"]["stop_conditions"]
        _project_validator().validate(assessment)
        observed.append(assessment["route"])
    assert len(observed) == len(cases)


def test_independent_routes_preserve_safe_component_in_mixed_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stable_environment: Path,
) -> None:
    del stable_environment
    project = _project(tmp_path)
    report = _report("guided-integration", "ready")
    report["components"][0]["recognized_setup"] = {
        "variant_id": "claude-legacy-entry-v1",
        "evidence": [],
    }
    monkeypatch.setattr(
        reconciliation, "inspect_project_integration", lambda path, detail: report
    )
    assessment = assess_project(project, approved_root=tmp_path)
    states = {item["component"]: item["state"] for item in assessment["components"]}
    assert states == {"claude": "safe-update-available", "codex": "ready"}
    assert assessment["route"] == "safe-update-available"


@pytest.mark.parametrize("route", ["setup", "update", "custom"])
def test_recipe_recommendation_requires_authoritative_source_not_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
) -> None:
    project = _project(tmp_path)
    report = _report(
        "safe-finish" if route == "setup" else "guided-integration",
        "ready",
    )
    if route == "update":
        report["components"][0]["recognized_setup"] = {
            "variant_id": "claude-legacy-entry-v1",
            "evidence": [],
        }
    monkeypatch.setattr(reconciliation, "is_project_excluded", lambda path: False)
    monkeypatch.setattr(
        reconciliation, "inspect_project_integration", lambda path, detail: report
    )
    monkeypatch.setattr(reconciliation, "resolve_key", lambda key: None)
    monkeypatch.setattr(
        "cc.core.executables.resolve_executable",
        lambda name: tmp_path / "bin" / name,
    )

    assessment = assess_project(
        project,
        approved_root=tmp_path,
        selected_components=("claude",) if route == "setup" else (),
    )

    claude = assessment["components"][0]
    assert claude["state"] == "source-unavailable"
    assert assessment["route"] == "source-unavailable"
    assert claude["selected"] is (route == "setup")
    assert claude["recommended"] is False
    assert claude["recommendation_reason"] == (
        "No authoritative Claude framework source was verified for the bounded recipe."
    )
    if route == "custom":
        assert claude["recipe_options"] == []


def test_explicit_selection_is_recommended_only_when_recipe_source_is_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    source = _claude_source(tmp_path)
    monkeypatch.setattr(reconciliation, "is_project_excluded", lambda path: False)
    monkeypatch.setattr(
        reconciliation,
        "inspect_project_integration",
        lambda path, detail: _report("safe-finish", "ready"),
    )
    monkeypatch.setattr(
        reconciliation,
        "resolve_key",
        lambda key: str(source) if key == "paths.claude_copilot_root" else None,
    )

    assessment = assess_project(
        project, approved_root=tmp_path, selected_components=("claude",)
    )

    claude = assessment["components"][0]
    assert claude["selected"] is True
    assert claude["recommended"] is True
    assert claude["recommendation_reason"] == (
        "An authoritative Claude framework source is configured for the bounded recipe."
    )


@pytest.mark.parametrize("route", ["setup", "update", "custom"])
@pytest.mark.parametrize("source_shape", ["empty", "incomplete"])
def test_incomplete_recipe_source_is_never_recommended(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    source_shape: str,
) -> None:
    project = _project(tmp_path)
    source = tmp_path / "claude-source"
    source.mkdir()
    if source_shape == "incomplete":
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

    report = _report(
        "safe-finish" if route == "setup" else "guided-integration",
        "ready",
    )
    if route == "update":
        report["components"][0]["recognized_setup"] = {
            "variant_id": "claude-legacy-entry-v1",
            "evidence": [],
        }
    monkeypatch.setattr(reconciliation, "is_project_excluded", lambda path: False)
    monkeypatch.setattr(
        reconciliation, "inspect_project_integration", lambda path, detail: report
    )
    monkeypatch.setattr(
        reconciliation,
        "resolve_key",
        lambda key: str(source) if key == "paths.claude_copilot_root" else None,
    )

    assessment = assess_project(
        project,
        approved_root=tmp_path,
        selected_components=("claude",) if route == "setup" else (),
    )

    claude = assessment["components"][0]
    assert claude["state"] == "source-unavailable"
    assert assessment["route"] == "source-unavailable"
    assert claude["recommended"] is False
    assert claude["recipe_options"] == []
    assert claude["recommendation_reason"] == (
        "No authoritative Claude framework source was verified for the bounded recipe."
    )


@pytest.mark.parametrize("git_state", ["dirty", "detached"])
def test_unstable_projects_are_held_with_exact_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stable_environment: Path,
    git_state: str,
) -> None:
    del stable_environment
    project = _project(tmp_path)
    (project / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(project, "add", "tracked.txt")
    _git(project, "commit", "-qm", "base")
    if git_state == "dirty":
        (project / "tracked.txt").write_text("changed\n", encoding="utf-8")
    else:
        _git(project, "checkout", "--detach", "-q")
    monkeypatch.setattr(
        reconciliation,
        "inspect_project_integration",
        lambda path, detail: _report("safe-finish", "safe-finish"),
    )
    assessment = assess_project(
        project,
        approved_root=tmp_path,
        selected_components=("claude",),
    )
    assert assessment["route"] == "held"
    assert {item["code"] for item in assessment["blockers"]} >= {
        "dirty-working-tree" if git_state == "dirty" else "detached-head"
    }


def test_exclusion_is_primary_and_content_is_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stable_environment: Path,
) -> None:
    del stable_environment
    project = _project(tmp_path)
    project_file = project / "CLAUDE.md"
    project_file.write_text("private project content\n", encoding="utf-8")
    before = project_file.read_bytes()
    monkeypatch.setattr(reconciliation, "is_project_excluded", lambda path: True)
    monkeypatch.setattr(
        reconciliation,
        "inspect_project_integration",
        lambda path, detail: _report("guided-integration", "ready"),
    )
    assessment = assess_project(project, approved_root=tmp_path)
    assert assessment["route"] == "excluded"
    assert all(item["state"] == "excluded" for item in assessment["components"])
    assert project_file.read_bytes() == before
    assert all(
        "private project content" not in json.dumps(item) for item in [assessment]
    )


def test_stable_assessment_id_and_selection_freshness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stable_environment: Path,
) -> None:
    del stable_environment
    project = _project(tmp_path)
    monkeypatch.setattr(
        reconciliation,
        "inspect_project_integration",
        lambda path, detail: _report("safe-finish", "safe-finish"),
    )
    first = assess_project(
        project, approved_root=tmp_path, selected_components=("claude",)
    )
    second = assess_project(
        project, approved_root=tmp_path, selected_components=("claude",)
    )
    assert first == second
    with pytest.raises(ProjectReconciliationError, match="selection changed"):
        build_project_plans([first], {str(project): ("codex",)})

    (project / "new-untracked.txt").write_text(
        "changed after census\n", encoding="utf-8"
    )
    with pytest.raises(ProjectReconciliationError, match="evidence changed"):
        build_project_plans([first], {str(project): ("claude",)})


def test_external_symlink_is_content_free_and_unverifiable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stable_environment: Path,
) -> None:
    del stable_environment
    project = _project(tmp_path)
    external = tmp_path / "outside"
    external.mkdir()
    (project / ".claude/skills").mkdir(parents=True)
    (project / ".claude/skills/codex-copilot").symlink_to(external)
    _git(project, "add", ".claude/skills/codex-copilot")
    _git(project, "commit", "-qm", "external link fixture")
    monkeypatch.setattr(
        reconciliation,
        "inspect_project_integration",
        lambda path, detail: _report("could-not-verify", "safe-finish"),
    )
    assessment = assess_project(project, approved_root=tmp_path)
    assert assessment["route"] == "could-not-verify"
    serialized = json.dumps(assessment, sort_keys=True)
    assert str(external) not in serialized
    assert ".claude/skills" in {
        item["path"] for item in assessment["dossier"]["preservation"]
    }


def test_census_counts_reconcile_from_one_record_per_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stable_environment: Path,
) -> None:
    del stable_environment
    projects = [_project(tmp_path, f"project-{index}") for index in range(3)]
    classifications = {
        projects[0].name: ("ready", "ready"),
        projects[1].name: ("safe-finish", "safe-finish"),
        projects[2].name: ("owner-decision", "safe-finish"),
    }
    monkeypatch.setattr(
        reconciliation, "discover_workspaces", lambda **kwargs: projects
    )
    monkeypatch.setattr(
        reconciliation,
        "inspect_project_integration",
        lambda path, detail: _report(*classifications[Path(path).name]),
    )
    census = build_project_census(roots=(tmp_path,))
    counts = {
        route: sum(item["route"] == route for item in census)
        for route in {item["route"] for item in census}
    }
    assert len(census) == 3
    assert sum(counts.values()) == len(census)
    assert counts == {"ready": 1, "copilot-not-present": 1, "owner-decision": 1}


def test_reverse_component_selection_is_canonicalized_before_census(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stable_environment: Path,
) -> None:
    del stable_environment
    project = _project(tmp_path)
    monkeypatch.setattr(
        reconciliation, "discover_workspaces", lambda **kwargs: [project]
    )
    monkeypatch.setattr(
        reconciliation,
        "inspect_project_integration",
        lambda path, detail: _report("ready", "ready"),
    )

    forward = build_project_census(
        roots=(tmp_path,),
        selections={str(project): ("claude", "codex")},
    )
    reversed_selection = build_project_census(
        roots=(tmp_path,),
        selections={str(project): ("codex", "claude")},
    )

    assert reversed_selection == forward
    assert reversed_selection[0]["selected_components"] == ["claude", "codex"]


def test_disjoint_roots_assign_each_project_once_to_its_exact_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stable_environment: Path,
) -> None:
    del stable_environment
    first_root = tmp_path / "first-root"
    second_root = tmp_path / "second-root"
    first_root.mkdir()
    second_root.mkdir()
    first = _project(first_root, "first-project")
    second = _project(second_root, "second-project")
    monkeypatch.setattr(
        reconciliation, "discover_workspaces", lambda **kwargs: [first, second]
    )
    monkeypatch.setattr(
        reconciliation,
        "inspect_project_integration",
        lambda path, detail: _report("ready", "ready"),
    )

    census = build_project_census(roots=(first_root, second_root))

    assert len(census) == 2
    assert len({item["path"] for item in census}) == 2
    assert {item["path"]: item["root"] for item in census} == {
        str(first): str(first_root),
        str(second): str(second_root),
    }


def test_overlapping_roots_assign_project_to_most_specific_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stable_environment: Path,
) -> None:
    del stable_environment
    broad_root = tmp_path / "projects"
    specific_root = broad_root / "team"
    specific_root.mkdir(parents=True)
    project = _project(specific_root)
    monkeypatch.setattr(
        reconciliation, "discover_workspaces", lambda **kwargs: [project]
    )
    monkeypatch.setattr(
        reconciliation,
        "inspect_project_integration",
        lambda path, detail: _report("ready", "ready"),
    )

    census = build_project_census(roots=(broad_root, specific_root))

    assert len(census) == 1
    assert census[0]["path"] == str(project)
    assert census[0]["root"] == str(specific_root)


def test_selected_project_outside_every_approved_root_fails_closed(
    tmp_path: Path,
    stable_environment: Path,
) -> None:
    del stable_environment
    approved = tmp_path / "approved"
    approved.mkdir()
    outside = _project(tmp_path, "outside")

    with pytest.raises(ProjectReconciliationError, match="outside every"):
        build_project_census(
            roots=(approved,),
            selections={str(outside): ("claude",)},
        )


def test_selected_non_git_path_remains_explicit_could_not_verify(
    tmp_path: Path,
    stable_environment: Path,
) -> None:
    del stable_environment
    folder = tmp_path / "not-git"
    folder.mkdir()
    census = build_project_census(
        roots=(tmp_path,), selections={str(folder): ("claude",)}
    )
    assert len(census) == 1
    assert census[0]["route"] == "could-not-verify"
    assert census[0]["blockers"][0]["code"] == "unreadable-project-identity"


def test_selection_requires_an_explicit_approved_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stable_environment: Path,
) -> None:
    del stable_environment
    project = _project(tmp_path)
    monkeypatch.setattr(reconciliation, "resolve_key", lambda key: None)
    with pytest.raises(ProjectReconciliationError, match="approved root"):
        build_project_census(selections={str(project): ("claude",)})
