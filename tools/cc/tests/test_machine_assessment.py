from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from cc.core.ecosystem.machine_assessment import build_machine_assessment
from jsonschema import Draft202012Validator


def _validate_machine(payload: dict[str, Any]) -> None:
    schema_path = Path(__file__).parent / "fixtures/schemas/reconcile.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(
        {"$ref": "#/$defs/machine", "$defs": schema["$defs"]}
    )
    validator.validate(payload)


def _healthy_context(tmp_path: Path) -> dict[str, Any]:
    config_path = tmp_path / "machine" / "config.json"
    config_path.parent.mkdir()
    config_path.write_text("{}\n", encoding="utf-8")
    diagnostics_path = config_path.parent / "diagnostics"
    diagnostics_path.mkdir()

    root = tmp_path / "Projects"
    root.mkdir()
    claude = tmp_path / "claude-framework"
    codex = tmp_path / "codex-framework"
    claude.mkdir()
    codex.mkdir()

    executable_dir = tmp_path / "bin"
    executable_dir.mkdir()
    executables: dict[str, Path | None] = {}
    for command in ("cc", "git", "gh", "copilot", "claude", "codex"):
        path = executable_dir / command
        path.write_text("#!/bin/sh\n", encoding="utf-8")
        path.chmod(0o755)
        executables[command] = path

    state: dict[str, Any] = {
        "doctor": {
            "schema_version": "1.0",
            "status": "healthy",
            "offline": False,
            "auth": [],
            "checkers": [
                {
                    "id": "claude-org-sync",
                    "severity": "pass",
                    "layer": "claude-org",
                    "product": "claude",
                    "detail": "Claude layer matches its remote.",
                },
                {
                    "id": "codex-org-sync",
                    "severity": "pass",
                    "layer": "codex-org",
                    "product": "codex",
                    "detail": "Codex layer matches its remote.",
                },
            ],
        },
        "connections": {
            "schema_version": "1.0",
            "result": "ok",
            "detail": None,
            "store": {
                "type": "infisical",
                "reachable": True,
                "scope": "organization",
                "detail": "The organization credential store is reachable.",
            },
            "connections": [{"id": "example", "secret_state": "ready", "missing": []}],
        },
        "config": {
            "paths.claude_copilot_root": str(claude),
            "paths.codex_copilot_root": str(codex),
            "projects.roots": [str(root)],
            "auth.keychain_service": "test.github",
        },
        "root_entries": [{"name": root.name, "path": str(root), "project_count": 0}],
        "identity": {"login": "pablo", "scopes": "read:org repo"},
        "credential": "credential-value-that-must-never-appear",
        "credential_error": None,
        "framework_versions": {"claude": "5.13.3", "codex": "0.6.1"},
        "executables": executables,
    }

    def credential_reader(account: str, *, service: str) -> str | None:
        assert account == "pablo"
        assert service == "test.github"
        if state["credential_error"] is not None:
            raise state["credential_error"]
        return state["credential"]

    kwargs = {
        "doctor_builder": lambda: state["doctor"],
        "connections_builder": lambda: state["connections"],
        "config_reader": lambda: state["config"],
        "config_path_getter": lambda: config_path,
        "diagnostics_path_getter": lambda: diagnostics_path,
        "roots_builder": lambda: state["root_entries"],
        "identity_reader": lambda: state["identity"],
        "credential_reader": credential_reader,
        "executable_resolver": lambda command: state["executables"].get(command),
        "framework_version_reader": (
            lambda path, component: state["framework_versions"].get(component)
        ),
        "helper_version": "2.6.0",
        "executable_version_reader": (lambda command, path: f"{command} version 1.0.0"),
    }
    return {
        "state": state,
        "kwargs": kwargs,
        "config_path": config_path,
        "diagnostics_path": diagnostics_path,
        "root": root,
        "claude": claude,
        "codex": codex,
    }


def test_healthy_machine_is_schema_valid_and_leaks_no_credential(
    tmp_path: Path,
) -> None:
    context = _healthy_context(tmp_path)

    assessment = build_machine_assessment(**context["kwargs"])

    _validate_machine(assessment)
    assert assessment["state"] == "ready"
    assert assessment["helper"]["version"] == "2.6.0"
    assert assessment["authentication"] == {
        "state": "signed-in",
        "credential_state": "present",
        "detail": "A Copilot sign-in and its credential are present.",
    }
    assert assessment["connectivity"]["state"] == "online"
    assert assessment["layers"]["ready"] == assessment["layers"]["total"] == 2
    assert assessment["blockers"] == []
    assert "credential-value-that-must-never-appear" not in json.dumps(assessment)


def test_readable_diagnostics_boundary_adds_no_blocker(tmp_path: Path) -> None:
    context = _healthy_context(tmp_path)

    assessment = build_machine_assessment(**context["kwargs"])

    assert assessment["state"] == "ready"
    assert not any(
        item["code"].startswith("diagnostics-location-")
        for item in assessment["blockers"]
    )


def test_missing_diagnostics_leaf_under_safe_owned_ancestor_is_cli_creatable(
    tmp_path: Path,
) -> None:
    context = _healthy_context(tmp_path)
    missing = context["diagnostics_path"]
    missing.rmdir()
    context["kwargs"]["diagnostics_path_getter"] = lambda: missing

    assessment = build_machine_assessment(**context["kwargs"])

    _validate_machine(assessment)
    assert assessment["state"] == "ready"
    assert not any(
        item["code"].startswith("diagnostics-location-")
        for item in assessment["blockers"]
    )
    assert not missing.exists()


@pytest.mark.parametrize("unsafe", ["not-owned", "unwritable", "symlinked"])
def test_missing_diagnostics_leaf_requires_safe_owned_real_ancestor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe: str
) -> None:
    context = _healthy_context(tmp_path)
    ancestor = tmp_path / "private-state"
    ancestor.mkdir()
    cleanup: Path | None = None
    if unsafe == "not-owned":
        actual_uid = __import__("os").geteuid()
        monkeypatch.setattr(
            "cc.core.ecosystem.machine_assessment.os.geteuid",
            lambda: actual_uid + 1,
        )
        missing = ancestor / "diagnostics"
    elif unsafe == "unwritable":
        cleanup = ancestor
        ancestor.chmod(0o500)
        missing = ancestor / "diagnostics"
    else:
        real = tmp_path / "real-state"
        real.mkdir()
        ancestor.rmdir()
        ancestor.symlink_to(real, target_is_directory=True)
        missing = ancestor / "diagnostics"

    context["kwargs"]["diagnostics_path_getter"] = lambda: missing
    try:
        assessment = build_machine_assessment(**context["kwargs"])
    finally:
        if cleanup is not None:
            cleanup.chmod(0o700)

    _validate_machine(assessment)
    assert assessment["state"] == "action-required"
    assert "diagnostics-location-missing" in {
        item["code"] for item in assessment["blockers"]
    }
    assert not missing.exists()


def test_unwritable_diagnostics_boundary_is_actionable(tmp_path: Path) -> None:
    context = _healthy_context(tmp_path)
    diagnostics_path = context["diagnostics_path"]
    diagnostics_path.chmod(0o500)

    try:
        assessment = build_machine_assessment(**context["kwargs"])
    finally:
        diagnostics_path.chmod(0o700)

    _validate_machine(assessment)
    assert assessment["state"] == "action-required"
    assert "diagnostics-location-unwritable" in {
        item["code"] for item in assessment["blockers"]
    }


def test_symlinked_diagnostics_boundary_is_actionable(tmp_path: Path) -> None:
    context = _healthy_context(tmp_path)
    linked = tmp_path / "linked-diagnostics"
    linked.symlink_to(context["diagnostics_path"], target_is_directory=True)
    context["kwargs"]["diagnostics_path_getter"] = lambda: linked

    assessment = build_machine_assessment(**context["kwargs"])

    _validate_machine(assessment)
    assert assessment["state"] == "action-required"
    assert "diagnostics-location-symlinked" in {
        item["code"] for item in assessment["blockers"]
    }


def test_diagnostics_boundary_reached_through_symlinked_ancestor_is_actionable(
    tmp_path: Path,
) -> None:
    context = _healthy_context(tmp_path)
    real = tmp_path / "real"
    real.mkdir()
    diagnostics = real / "diagnostics"
    diagnostics.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    linked = alias / "diagnostics"
    context["kwargs"]["diagnostics_path_getter"] = lambda: linked

    assessment = build_machine_assessment(**context["kwargs"])

    _validate_machine(assessment)
    assert assessment["state"] == "action-required"
    assert "diagnostics-location-symlinked" in {
        item["code"] for item in assessment["blockers"]
    }
    assert diagnostics.is_dir()


def test_existing_diagnostics_boundary_requires_effective_user_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _healthy_context(tmp_path)
    actual_uid = __import__("os").geteuid()
    monkeypatch.setattr(
        "cc.core.ecosystem.machine_assessment.os.geteuid",
        lambda: actual_uid + 1,
    )

    assessment = build_machine_assessment(**context["kwargs"])

    _validate_machine(assessment)
    assert assessment["state"] == "action-required"
    assert "diagnostics-location-untrusted-owner" in {
        item["code"] for item in assessment["blockers"]
    }


def test_missing_helper_and_framework_source_are_explicit(tmp_path: Path) -> None:
    context = _healthy_context(tmp_path)
    context["kwargs"]["helper_version"] = None
    context["state"]["config"]["paths.claude_copilot_root"] = str(
        tmp_path / "missing-claude"
    )

    assessment = build_machine_assessment(**context["kwargs"])

    assert assessment["state"] == "action-required"
    assert assessment["helper"]["state"] == "missing"
    assert assessment["frameworks"][0]["state"] == "missing"
    assert {item["code"] for item in assessment["blockers"]} >= {
        "helper-missing",
        "claude-framework-missing",
    }


def test_incompatible_helper_and_framework_versions_are_not_ready(
    tmp_path: Path,
) -> None:
    context = _healthy_context(tmp_path)
    context["kwargs"]["helper_version"] = "2.5.2"
    context["state"]["framework_versions"] = {
        "claude": "5.12.9",
        "codex": "0.5.9",
    }

    assessment = build_machine_assessment(**context["kwargs"])

    assert assessment["state"] == "action-required"
    assert assessment["helper"]["state"] == "incompatible"
    assert [item["state"] for item in assessment["frameworks"]] == [
        "incompatible",
        "incompatible",
    ]
    assert {item["code"] for item in assessment["blockers"]} >= {
        "helper-incompatible",
        "claude-framework-incompatible",
        "codex-framework-incompatible",
    }


def test_configured_framework_symlink_uses_its_readable_authoritative_target(
    tmp_path: Path,
) -> None:
    context = _healthy_context(tmp_path)
    linked = tmp_path / "claude-framework-link"
    linked.symlink_to(context["claude"], target_is_directory=True)
    context["state"]["config"]["paths.claude_copilot_root"] = str(linked)

    assessment = build_machine_assessment(**context["kwargs"])

    assert assessment["frameworks"][0]["state"] == "ready"
    assert assessment["frameworks"][0]["path"] == str(linked)


@pytest.mark.parametrize(
    ("identity", "credential", "error", "state", "credential_state", "machine_state"),
    [
        ({}, "unused", None, "signed-out", "absent", "action-required"),
        (
            {"login": "pablo"},
            None,
            None,
            "revoked",
            "absent",
            "action-required",
        ),
        (
            {"login": "pablo"},
            None,
            RuntimeError("keychain unavailable"),
            "could-not-verify",
            "store-unreachable",
            "could-not-verify",
        ),
    ],
)
def test_authentication_distinguishes_signed_out_absent_and_unreachable(
    tmp_path: Path,
    identity: dict[str, Any],
    credential: str | None,
    error: Exception | None,
    state: str,
    credential_state: str,
    machine_state: str,
) -> None:
    context = _healthy_context(tmp_path)
    context["state"]["identity"] = identity
    context["state"]["credential"] = credential
    context["state"]["credential_error"] = error

    assessment = build_machine_assessment(**context["kwargs"])

    assert assessment["authentication"]["state"] == state
    assert assessment["authentication"]["credential_state"] == credential_state
    assert assessment["state"] == machine_state


def test_offline_is_separate_from_valid_sign_in_and_configuration(
    tmp_path: Path,
) -> None:
    context = _healthy_context(tmp_path)
    context["state"]["doctor"]["offline"] = True
    context["state"]["doctor"]["status"] = "offline"

    assessment = build_machine_assessment(**context["kwargs"])

    assert assessment["state"] == "action-required"
    assert assessment["authentication"]["state"] == "signed-in"
    assert assessment["configuration"]["state"] == "ready"
    assert assessment["connectivity"]["state"] == "offline"
    assert "connectivity-offline" in {item["code"] for item in assessment["blockers"]}


@pytest.mark.parametrize(
    ("case", "expected_code", "machine_state"),
    [
        ("absent", "approved-roots-missing", "action-required"),
        ("missing", "approved-root-missing", "action-required"),
        ("unreadable", "approved-root-unreadable", "could-not-verify"),
        ("symlinked", "approved-root-symlinked", "action-required"),
    ],
)
def test_approved_root_failures_remain_distinct(
    tmp_path: Path,
    case: str,
    expected_code: str,
    machine_state: str,
) -> None:
    context = _healthy_context(tmp_path)
    state = context["state"]
    cleanup: Path | None = None
    if case == "absent":
        state["config"]["projects.roots"] = []
        state["root_entries"] = []
    elif case == "missing":
        missing = tmp_path / "missing-projects"
        state["config"]["projects.roots"] = [str(missing)]
        state["root_entries"] = []
    elif case == "unreadable":
        cleanup = context["root"]
        cleanup.chmod(0)
        state["root_entries"] = [
            {"path": str(cleanup), "name": cleanup.name, "state": "unreadable"}
        ]
    else:
        link = tmp_path / "linked-projects"
        link.symlink_to(context["root"], target_is_directory=True)
        state["config"]["projects.roots"] = [str(link)]
        state["root_entries"] = []

    try:
        assessment = build_machine_assessment(**context["kwargs"])
    finally:
        if cleanup is not None:
            cleanup.chmod(0o755)

    assert assessment["state"] == machine_state
    assert expected_code in {item["code"] for item in assessment["blockers"]}


def test_shared_connection_store_failure_does_not_become_signed_out(
    tmp_path: Path,
) -> None:
    context = _healthy_context(tmp_path)
    context["state"]["connections"]["store"]["reachable"] = False
    context["state"]["connections"]["connections"] = [
        {"id": "warehouse", "secret_state": "no-store", "missing": ["TOKEN"]}
    ]

    assessment = build_machine_assessment(**context["kwargs"])

    assert assessment["authentication"]["state"] == "signed-in"
    assert assessment["connectivity"]["state"] == "online"
    assert assessment["state"] == "action-required"
    assert {item["code"] for item in assessment["blockers"]} >= {
        "shared-credential-store-unreachable",
        "connection-no-store-warehouse",
    }
    assert "TOKEN" not in json.dumps(assessment)


def test_unavailable_authoritative_builders_fail_closed_without_exception_detail(
    tmp_path: Path,
) -> None:
    context = _healthy_context(tmp_path)

    def unavailable() -> dict[str, Any]:
        raise RuntimeError("credential-shaped-private-detail")

    context["kwargs"]["doctor_builder"] = unavailable
    context["kwargs"]["connections_builder"] = unavailable

    assessment = build_machine_assessment(**context["kwargs"])

    assert assessment["state"] == "could-not-verify"
    assert {item["code"] for item in assessment["blockers"]} >= {
        "doctor-unavailable",
        "connections-unavailable",
    }
    assert "credential-shaped-private-detail" not in json.dumps(assessment)


def test_machine_assessment_is_strictly_read_only(tmp_path: Path) -> None:
    context = _healthy_context(tmp_path)
    paths = [
        context["config_path"],
        *sorted(tmp_path.rglob("*")),
    ]
    before = {
        str(path): (
            path.lstat().st_mode,
            path.read_bytes() if path.is_file() else None,
            path.lstat().st_mtime_ns,
        )
        for path in paths
    }

    build_machine_assessment(**context["kwargs"])

    after = {
        str(path): (
            path.lstat().st_mode,
            path.read_bytes() if path.is_file() else None,
            path.lstat().st_mtime_ns,
        )
        for path in paths
    }
    assert after == before
