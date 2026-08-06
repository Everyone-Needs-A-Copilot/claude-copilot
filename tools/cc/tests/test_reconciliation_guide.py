from __future__ import annotations

import json
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from cc.core.ecosystem.reconciliation import ReconciliationError
from cc.core.ecosystem.reconciliation_guide import (
    build_guide_check_report,
    build_guide_finalize_report,
    build_guide_prepare_report,
    build_guide_start_report,
    build_guide_status_report,
)
from cc.core.ecosystem.reconciliation_types import parse_reconciliation_request


NOW = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
GUIDE_ID = "guide_" + "1" * 32


def _assert_contract(report: dict) -> None:
    schema_path = Path(__file__).parent / "fixtures" / "schemas" / "reconcile.schema.json"
    validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
    assert not list(validator.iter_errors(report))


def _request(root: Path):
    return parse_reconciliation_request(
        {
            "schema_version": "1.0",
            "roots": [str(root)],
            "projects": [
                {
                    "path": str(root / "alpha"),
                    "components": ["claude", "codex"],
                    "recipe_ids": {
                        "claude": "claude-project-setup-v1",
                        "codex": "codex-project-setup-v1",
                    },
                },
                {
                    "path": str(root / "bravo"),
                    "components": ["claude"],
                },
            ],
        }
    )


def _component(name: str, *, state: str = "customized-guided-route") -> dict:
    return {
        "component": name,
        "state": state,
        "selected": True,
        "recommended": True,
        "responsible_actor": "project-author",
        "next_action": f"Complete the {name} project integration.",
        "evidence": [
            {"id": f"{name}-config", "state": "present", "detail": "Config found."}
        ],
        "missing_requirements": [
            {
                "id": f"{name}-current",
                "state": "missing",
                "detail": f"The {name} instructions are not current.",
            }
        ],
        "recipe_options": [],
    }


def _project(path: Path, components: list[str]) -> dict:
    return {
        "path": str(path),
        "root": str(path.parent),
        "name": path.name,
        "scope": {"kind": "product-project", "reason": "product"},
        "inspection_id": "inspect_" + "2" * 32,
        "presence": "both",
        "route": "customized-guided-route",
        "selected_components": components,
        "components": [
            _component(name, state="customized-guided-route" if name in components else "ready")
            for name in ("claude", "codex")
        ],
        "blockers": [],
        "next_action": "Use the guided project route.",
        "dossier": {
            "inspection_id": "inspect_" + "2" * 32,
            "current_evidence": [],
            "missing_requirements": [],
            "preservation": [
                {
                    "kind": "project-file",
                    "path": "CLAUDE.md",
                    "detail": "Preserve project instructions.",
                }
            ],
            "allowed_targets": ["CLAUDE.md", "AGENTS.md", ".claude", ".codex"],
            "prohibited_actions": ["Do not overwrite project-owned instructions."],
            "verification": ["Run a fresh Control Tower check."],
            "stop_conditions": ["Stop if the working tree is dirty."],
        },
    }


def _assessment(root: Path) -> dict:
    alpha = _project(root / "alpha", ["claude", "codex"])
    bravo = _project(root / "bravo", ["claude"])
    return {
        "machine": {"configuration": {"approved_roots": [str(root)]}},
        "projects": [alpha, bravo],
        "default_selection": [
            {
                "path": alpha["path"],
                "components": ["claude", "codex"],
                "category": "new-setup",
                "recipe_ids": {
                    "claude": "claude-project-setup-v1",
                    "codex": "codex-project-setup-v1",
                },
            }
        ],
        "assistant_selection": [
            {
                "path": bravo["path"],
                "components": ["claude"],
                "category": "correction",
            }
        ],
    }


def _verification(root: Path, ready_paths: set[str]):
    def build(request):
        projects = []
        for selection in request.projects:
            ready = selection.path in ready_paths
            projects.append(
                {
                    "path": selection.path,
                    "route": "ready" if ready else "customized-guided-route",
                    "selected_components": list(selection.components),
                    "components": [
                        {
                            "component": name,
                            "state": "ready" if ready else "customized-guided-route",
                            "missing_requirements": (
                                []
                                if ready
                                else [
                                    {
                                        "id": f"{name}-current",
                                        "state": "missing",
                                        "detail": f"The {name} instructions are still not current.",
                                    }
                                ]
                            ),
                            "next_action": (
                                "" if ready else f"Correct the {name} integration."
                            ),
                        }
                        for name in selection.components
                    ],
                    "next_action": "" if ready else "Continue the guided conversation.",
                }
            )
        return {"projects": projects}

    return build


def _prepare(root: Path, state_root: Path) -> dict:
    (root / "alpha").mkdir()
    (root / "bravo").mkdir()
    return build_guide_prepare_report(
        _request(root),
        assessment_builder=lambda: _assessment(root),
        helper_path="/Applications/Copilot Control Tower.app/Contents/Resources/cc",
        state_root=state_root,
        now=NOW,
        guide_id=GUIDE_ID,
    )


def test_prepare_writes_one_private_immutable_root_package(tmp_path: Path) -> None:
    root = tmp_path / "Sites"
    root.mkdir()
    state_root = tmp_path / "state"

    report = _prepare(root, state_root)

    assert report["phase"] == "guide-prepare"
    assert report["result"] == "ready"
    _assert_contract(report)
    assert report["progress"] == {
        "state": "prepared",
        "selected_project_count": 2,
        "verified_project_count": 0,
        "remaining_project_count": 2,
        "needs_conversation_count": 0,
        "last_checked_project": None,
        "detail": "The instruction files and copy prompt are ready.",
    }
    instructions = Path(report["instructions_path"])
    projects = Path(report["projects_path"])
    assert instructions.parent == projects.parent
    assert instructions.parent.parent.parent.parent == root
    assert report["workspace_roots"] == [str(root)]
    assert stat.S_IMODE(instructions.stat().st_mode) == 0o400
    assert stat.S_IMODE(projects.stat().st_mode) == 0o400
    assert "Work through every project" in instructions.read_text(encoding="utf-8")
    assert "normal Claude Code or Codex conversation" in instructions.read_text(
        encoding="utf-8"
    )
    assert "Do not commit, push, reset, clean, stash" in instructions.read_text(
        encoding="utf-8"
    )
    assert "COPILOT_SETUP_HELPER" not in instructions.read_text(encoding="utf-8")
    assert (
        instructions.read_text(encoding="utf-8").count(
            "/Applications/Copilot Control Tower.app/Contents/Resources/cc"
        )
        >= 3
    )
    assert report["instructions_path"] in report["start_prompt"]
    assert "this one conversation" in report["start_prompt"]
    assert "before doing anything" in report["start_prompt"]
    payload = json.loads(projects.read_text(encoding="utf-8"))
    assert [item["path"] for item in payload["projects"]] == [
        str(root / "alpha"),
        str(root / "bravo"),
    ]
    assert payload["workspace_roots"] == [str(root)]
    assert "secret" not in projects.read_text(encoding="utf-8").lower()


def test_prepare_preserves_every_approved_root_for_one_session(tmp_path: Path) -> None:
    first = tmp_path / "Sites"
    second = tmp_path / "ClientSites"
    first.mkdir()
    second.mkdir()
    (first / "alpha").mkdir()
    (second / "bravo").mkdir()
    request = parse_reconciliation_request(
        {
            "schema_version": "1.0",
            "roots": [str(first), str(second)],
            "projects": [
                {
                    "path": str(first / "alpha"),
                    "components": ["claude", "codex"],
                    "recipe_ids": {
                        "claude": "claude-project-setup-v1",
                        "codex": "codex-project-setup-v1",
                    },
                },
                {"path": str(second / "bravo"), "components": ["claude"]},
            ],
        }
    )
    assessment = _assessment(first)
    assessment["machine"]["configuration"]["approved_roots"] = [
        str(first),
        str(second),
    ]
    assessment["projects"][1] = _project(second / "bravo", ["claude"])
    assessment["assistant_selection"][0]["path"] = str(second / "bravo")

    report = build_guide_prepare_report(
        request,
        assessment_builder=lambda: assessment,
        state_root=tmp_path / "state",
        guide_id=GUIDE_ID,
    )

    assert report["workspace_root"] == str(first)
    assert report["workspace_roots"] == [str(first), str(second)]
    assert "`" + str(second) + "`" in Path(report["instructions_path"]).read_text(
        encoding="utf-8"
    )


def test_prepare_omits_approved_roots_without_selected_projects(tmp_path: Path) -> None:
    unused = tmp_path / "Archive"
    selected = tmp_path / "Sites"
    unused.mkdir()
    selected.mkdir()
    (selected / "alpha").mkdir()
    request = parse_reconciliation_request(
        {
            "schema_version": "1.0",
            "roots": [str(unused), str(selected)],
            "projects": [
                {
                    "path": str(selected / "alpha"),
                    "components": ["claude", "codex"],
                    "recipe_ids": {
                        "claude": "claude-project-setup-v1",
                        "codex": "codex-project-setup-v1",
                    },
                }
            ],
        }
    )
    assessment = _assessment(selected)
    assessment["machine"]["configuration"]["approved_roots"] = [
        str(unused),
        str(selected),
    ]
    assessment["projects"] = [assessment["projects"][0]]
    assessment["default_selection"] = [assessment["default_selection"][0]]
    assessment["assistant_selection"] = []

    report = build_guide_prepare_report(
        request,
        assessment_builder=lambda: assessment,
        state_root=tmp_path / "state",
        guide_id=GUIDE_ID,
    )

    assert report["workspace_root"] == str(selected)
    assert report["workspace_roots"] == [str(selected)]
    assert Path(report["instructions_path"]).is_relative_to(selected)
    assert not (unused / ".copilot-control-tower").exists()


def test_prepare_uses_deepest_approved_root_for_nested_roots(tmp_path: Path) -> None:
    broad = tmp_path / "Sites"
    narrow = broad / "ClientSites"
    project = narrow / "alpha"
    project.mkdir(parents=True)
    request = parse_reconciliation_request(
        {
            "schema_version": "1.0",
            "roots": [str(broad), str(narrow)],
            "projects": [
                {
                    "path": str(project),
                    "components": ["claude", "codex"],
                    "recipe_ids": {
                        "claude": "claude-project-setup-v1",
                        "codex": "codex-project-setup-v1",
                    },
                }
            ],
        }
    )
    assessment = _assessment(narrow)
    assessment["machine"]["configuration"]["approved_roots"] = [
        str(broad),
        str(narrow),
    ]
    assessment["projects"] = [assessment["projects"][0]]
    assessment["default_selection"] = [assessment["default_selection"][0]]
    assessment["assistant_selection"] = []

    report = build_guide_prepare_report(
        request,
        assessment_builder=lambda: assessment,
        state_root=tmp_path / "state",
        guide_id=GUIDE_ID,
    )

    assert report["workspace_root"] == str(narrow)
    assert report["workspace_roots"] == [str(narrow)]
    assert not (broad / ".copilot-control-tower").exists()


def test_start_check_finalize_and_status_use_python_owned_progress(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Sites"
    root.mkdir()
    state_root = tmp_path / "state"
    _prepare(root, state_root)

    started = build_guide_start_report(
        GUIDE_ID, "codex", state_root=state_root, now=NOW
    )
    first = build_guide_check_report(
        GUIDE_ID,
        str(root / "alpha"),
        verification_builder=_verification(root, {str(root / "alpha")}),
        state_root=state_root,
        now=NOW,
    )
    status = build_guide_status_report(GUIDE_ID, state_root=state_root, now=NOW)
    partial = build_guide_finalize_report(
        GUIDE_ID,
        verification_builder=_verification(root, {str(root / "alpha")}),
        state_root=state_root,
        now=NOW,
    )
    complete = build_guide_finalize_report(
        GUIDE_ID,
        verification_builder=_verification(
            root, {str(root / "alpha"), str(root / "bravo")}
        ),
        state_root=state_root,
        now=NOW,
    )

    assert started["result"] == "running"
    for report in (started, first, status, partial, complete):
        _assert_contract(report)
    assert first["project"]["state"] == "ready"
    assert status["progress"]["verified_project_count"] == 1
    assert partial["result"] == "action-required"
    assert partial["progress"]["remaining_project_count"] == 1
    unresolved = next(
        item for item in partial["project_status"] if item["state"] != "ready"
    )
    assert unresolved["path"] == str(root / "bravo")
    assert "still not current" in unresolved["reasons"][0]
    assert complete["result"] == "ready"
    assert complete["progress"]["verified_project_count"] == 2


def test_changed_package_is_rejected_before_progress_is_trusted(tmp_path: Path) -> None:
    root = tmp_path / "Sites"
    root.mkdir()
    state_root = tmp_path / "state"
    report = _prepare(root, state_root)
    instructions = Path(report["instructions_path"])
    instructions.chmod(0o600)
    instructions.write_text("changed\n", encoding="utf-8")
    instructions.chmod(0o400)

    with pytest.raises(ReconciliationError, match="changed after Python created"):
        build_guide_status_report(GUIDE_ID, state_root=state_root)


def test_fresh_assessment_prevents_expanded_or_ecosystem_authority(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Sites"
    root.mkdir()
    state_root = tmp_path / "state"
    request = parse_reconciliation_request(
        {
            "schema_version": "1.0",
            "roots": [str(root)],
            "projects": [
                {
                    "path": str(root / "ecosystem"),
                    "components": ["claude", "codex"],
                }
            ],
        }
    )

    with pytest.raises(ReconciliationError, match="fresh assessment"):
        build_guide_prepare_report(
            request,
            assessment_builder=lambda: _assessment(root),
            state_root=state_root,
            guide_id=GUIDE_ID,
        )


def test_check_rejects_project_outside_exact_guide(tmp_path: Path) -> None:
    root = tmp_path / "Sites"
    root.mkdir()
    state_root = tmp_path / "state"
    _prepare(root, state_root)

    with pytest.raises(ReconciliationError, match="not part of this guided"):
        build_guide_check_report(
            GUIDE_ID,
            str(root / "charlie"),
            state_root=state_root,
        )


def test_prepare_rejects_symlinked_reserved_package_root(tmp_path: Path) -> None:
    root = tmp_path / "Sites"
    root.mkdir()
    target = tmp_path / "elsewhere"
    target.mkdir()
    (root / ".copilot-control-tower").symlink_to(target, target_is_directory=True)
    state_root = tmp_path / "state"

    with pytest.raises(Exception, match="symlinked|unavailable"):
        _prepare(root, state_root)
