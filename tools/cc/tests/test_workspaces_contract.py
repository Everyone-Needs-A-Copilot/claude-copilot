from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest
from cc.commands import workspaces as workspaces_command
from cc.core.ecosystem import project_integration as integration_core
from cc.core.ecosystem import workspaces as core_workspaces
from cc.core.ecosystem.workspaces import (
    RECENTLY_SET_UP_WINDOW_HOURS,
    ActivationError,
    RevertError,
    activate_components,
    associate_personal_project,
    detect_candidate_roots,
    discover_workspaces,
    finish_project_integration,
    forget_root_grant,
    integration_hold,
    is_project_excluded,
    project_id,
    read_integration_holds_registry,
    read_known_projects_registry,
    read_personal_registry,
    recently_set_up,
    record_automatic_setup,
    record_root_grant,
    revert_project,
    undo_status,
    workspace_status,
    write_declaration,
    write_install_lock,
)
from jsonschema import Draft202012Validator

_WORKSPACE_FIXTURES = Path(__file__).parent / "fixtures" / "workspaces"
_WORKSPACE_REPORT_FIXTURES = _WORKSPACE_FIXTURES / "reports"
_WORKSPACE_SCHEMA = (
    Path(__file__).parent / "fixtures" / "schemas" / "workspaces.schema.json"
)
_LEGACY_WORKSPACE_KEYS = {
    "path",
    "name",
    "project_id",
    "state",
    "detail",
    "declared_components",
    "installed_components",
    "recommended_components",
    "personal_profile",
    "setup_policy",
    "policy_detail",
    "can_apply_now",
    "apply_blocked_detail",
    "undo",
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _workspace_schema_validator() -> Draft202012Validator:
    schema = _load_json(_WORKSPACE_SCHEMA)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _workspace_schema_errors(payload: dict) -> list:
    return sorted(
        _workspace_schema_validator().iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )


def _assert_valid_workspace_report(payload: dict) -> None:
    errors = _workspace_schema_errors(payload)
    assert not errors, "\n".join(
        f"{list(error.absolute_path)}: {error.message}" for error in errors
    )


def _apply_fixture_mutation(payload: dict, operation: dict) -> None:
    parts = [
        part.replace("~1", "/").replace("~0", "~")
        for part in operation["path"].split("/")[1:]
    ]
    parent = payload
    for part in parts[:-1]:
        parent = parent[int(part)] if isinstance(parent, list) else parent[part]
    leaf = parts[-1]
    if operation["op"] == "remove":
        if isinstance(parent, list):
            del parent[int(leaf)]
        else:
            del parent[leaf]
    elif operation["op"] == "replace":
        if isinstance(parent, list):
            parent[int(leaf)] = operation["value"]
        else:
            parent[leaf] = operation["value"]
    else:
        raise AssertionError(f"Unsupported fixture mutation: {operation['op']}")


# ---------------------------------------------------------------------------
# Additive 1.1 project-integration contract and synthetic corpus
# ---------------------------------------------------------------------------


def test_workspaces_schema_is_valid_draft_2020_12_and_closed() -> None:
    schema = _load_json(_WORKSPACE_SCHEMA)

    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"] == {"const": "1.1"}
    assert schema["$defs"]["workspace"]["additionalProperties"] is False
    assert schema["$defs"]["componentAssessment"]["additionalProperties"] is False


@pytest.mark.parametrize(
    "report_path",
    sorted(_WORKSPACE_REPORT_FIXTURES.glob("*.json")),
    ids=lambda path: path.name,
)
def test_workspace_1_1_report_fixtures_validate_and_counts_match(
    report_path: Path,
) -> None:
    report = _load_json(report_path)
    _assert_valid_workspace_report(report)

    legacy_counts = Counter(item["state"] for item in report["workspaces"])
    classification_counts = Counter(
        item["classification"] for item in report["workspaces"]
    )
    assert report["summary"] == {
        state: legacy_counts[state]
        for state in ("ready", "setup-available", "activation-required", "blocked")
    } | {"total": len(report["workspaces"])}
    assert report["classification_summary"] == {
        classification: classification_counts[classification]
        for classification in (
            "ready",
            "safe-finish",
            "guided-integration",
            "owner-decision",
            "could-not-verify",
        )
    } | {"total": len(report["workspaces"])}
    assert all(
        _LEGACY_WORKSPACE_KEYS <= set(workspace) for workspace in report["workspaces"]
    )


def test_all_projects_fixture_is_bounded_but_keeps_plan_availability() -> None:
    report = _load_json(_WORKSPACE_REPORT_FIXTURES / "status-all-1.1.json")

    assert {item["classification"] for item in report["workspaces"]} == {
        "ready",
        "safe-finish",
        "guided-integration",
        "owner-decision",
        "could-not-verify",
    }
    assert all(
        item["inspection"]["scope"] == "summary" for item in report["workspaces"]
    )
    assert all(item["integration_plan"] is None for item in report["workspaces"])
    plan_states = {
        item["classification"]: item["plan_available"] for item in report["workspaces"]
    }
    assert plan_states["guided-integration"] is True
    assert plan_states["owner-decision"] is True
    assert plan_states["ready"] is False
    assert plan_states["safe-finish"] is False
    assert plan_states["could-not-verify"] is False


def test_single_project_detail_fixtures_freeze_prompt_and_owner_handoff_shapes() -> (
    None
):
    guided = _load_json(_WORKSPACE_REPORT_FIXTURES / "status-project-guided-1.1.json")[
        "workspaces"
    ][0]
    owner = _load_json(_WORKSPACE_REPORT_FIXTURES / "status-project-owner-1.1.json")[
        "workspaces"
    ][0]

    assert guided["inspection"]["scope"] == "detail"
    assert guided["integration_plan"]["inspection_id"] == guided["inspection"]["id"]
    assert guided["integration_plan"]["prompt"]["version"] == "1"
    assert guided["integration_plan"]["owner_handoff"] is None

    assert owner["inspection"]["scope"] == "detail"
    assert owner["integration_plan"]["inspection_id"] == owner["inspection"]["id"]
    assert owner["integration_plan"]["prompt"] is None
    assert owner["integration_plan"]["owner_handoff"]["version"] == "1"


def test_negative_report_fixtures_fail_closed() -> None:
    negative_corpus = _load_json(_WORKSPACE_FIXTURES / "invalid-report-mutations.json")

    for case in negative_corpus["cases"]:
        report = _load_json(_WORKSPACE_REPORT_FIXTURES / case["base"])
        _apply_fixture_mutation(report, case["operation"])
        assert _workspace_schema_errors(report), (
            f"negative fixture {case['id']} unexpectedly passed validation"
        )


def test_synthetic_layout_corpus_is_closed_representative_and_path_safe() -> None:
    corpus = _load_json(_WORKSPACE_FIXTURES / "project-integration-cases.json")
    cases = corpus["cases"]

    assert corpus["contract"] == {
        "id": "project-integration",
        "version": "1",
        "components": ["claude", "codex"],
    }
    assert {case["expected"]["classification"] for case in cases} == {
        "ready",
        "safe-finish",
        "guided-integration",
        "owner-decision",
        "could-not-verify",
    }
    assert len({case["id"] for case in cases}) == len(cases)
    assert len({tuple(case["capabilities"].values()) for case in cases}) >= 5
    assert (
        next(case for case in cases if case["id"] == "deep-specialization")["expected"][
            "classification"
        ]
        == "guided-integration"
    )
    assert (
        next(case for case in cases if case["id"] == "guidance-only")["expected"][
            "classification"
        ]
        == "guided-integration"
    )

    for case in cases:
        assert set(case["expected"]["components"]) == {"claude", "codex"}
        for entry in case["layout"]:
            path = Path(entry["path"])
            assert not path.is_absolute(), case["id"]
            assert ".." not in path.parts, case["id"]


def _git_init(path: Path, remote: str | None = None) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    if remote:
        subprocess.run(["git", "remote", "add", "origin", remote], cwd=path, check=True)


def test_discovery_finds_unconfigured_git_repositories_without_following_symlinks(
    tmp_path,
):
    root = tmp_path / "approved"
    configured = root / "team" / "configured"
    unconfigured = root / "new-clone"
    _git_init(configured)
    _git_init(unconfigured)
    write_declaration(configured, ("claude",))
    (root / "loop").symlink_to(root)

    assert discover_workspaces(roots=[root], registry=tmp_path / "missing.json") == [
        unconfigured.resolve(),
        configured.resolve(),
    ]


def test_no_roots_means_no_implicit_machine_scan(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "cc.core.ecosystem.workspaces.resolve_key",
        lambda key: [] if key == "projects.roots" else str(tmp_path / "missing.json"),
    )
    assert discover_workspaces() == []


def test_status_distinguishes_shared_declaration_from_real_installation(tmp_path):
    project = tmp_path / "project"
    registry = tmp_path / "personal.json"
    _git_init(project, "git@github.com:Example/Widget.git")
    write_declaration(project, ("claude", "codex"))

    claude_root, codex_root = _repo_roots()
    report = workspace_status(
        project,
        personal_registry=registry,
        which=lambda _name: None,
        claude_root=claude_root,
        codex_root=codex_root,
    )
    assert report["state"] == "activation-required"
    assert report["declared_components"] == ["claude", "codex"]
    assert report["installed_components"] == []
    assert report["recommended_components"] == ["claude", "codex"]


def test_recommendations_use_gui_safe_executable_resolver(monkeypatch, tmp_path):
    claude = tmp_path / "claude"
    claude.write_text("#!/bin/sh\n", encoding="utf-8")
    claude.chmod(0o755)
    monkeypatch.setattr(
        core_workspaces,
        "resolve_executable",
        lambda command: claude if command == "claude" else None,
    )

    assert core_workspaces.recommended_components(tmp_path) == ["claude"]


def test_superficial_markers_never_count_as_ready(tmp_path):
    arbitrary = tmp_path / "arbitrary"
    ready = tmp_path / "ready"
    _git_init(arbitrary)
    _git_init(ready)
    (arbitrary / ".claude").mkdir()
    (arbitrary / ".claude/notes.md").write_text("mine")
    (ready / ".claude/commands").mkdir(parents=True)
    (ready / ".claude/commands/protocol.md").write_text("framework")
    (ready / ".mcp.json").write_text("{}")

    claude_root, codex_root = _repo_roots()
    arbitrary_report = workspace_status(
        arbitrary,
        personal_registry=tmp_path / "a.json",
        claude_root=claude_root,
        codex_root=codex_root,
    )
    marker_report = workspace_status(
        ready,
        personal_registry=tmp_path / "b.json",
        claude_root=claude_root,
        codex_root=codex_root,
    )

    assert arbitrary_report["state"] == "setup-available"
    assert marker_report["state"] == "blocked"
    assert marker_report["classification"] != "ready"
    assert marker_report["installed_components"] == []


def test_project_identity_is_stable_across_github_transport_and_never_exposes_remote(
    tmp_path,
):
    ssh = tmp_path / "ssh"
    https = tmp_path / "https"
    _git_init(ssh, "git@github.com:Example/Widget.git")
    _git_init(https, "https://user:token@github.com/example/widget.git")

    assert project_id(ssh) == project_id(https)
    report = workspace_status(https, personal_registry=tmp_path / "personal.json")
    serialized = json.dumps(report)
    assert "token" not in serialized
    assert "github.com" not in serialized


def test_personal_association_stores_only_opaque_key_and_components(tmp_path):
    registry = tmp_path / "personal-projects.json"
    key = "sha256:" + "a" * 64
    associate_personal_project(key, ("claude",), registry=registry)
    payload = read_personal_registry(registry)

    assert payload == {
        "schema_version": "1.0",
        "projects": {key: {"components": ["claude"]}},
    }
    assert "path" not in registry.read_text()
    assert "remote" not in registry.read_text()


def test_local_only_project_never_gets_fabricated_portable_identity(tmp_path):
    project = tmp_path / "local"
    _git_init(project)
    report = workspace_status(project, personal_registry=tmp_path / "personal.json")
    assert report["project_id"] is None
    assert report["personal_profile"]["state"] == "local-only"


def test_activation_installs_both_products_and_only_then_becomes_ready(tmp_path):
    project = tmp_path / "project"
    _git_init(project, "git@github.com:Example/Activation.git")
    claude_root, codex_root = _repo_roots()

    activated = activate_components(
        project,
        ("claude", "codex"),
        claude_root=claude_root,
        codex_root=codex_root,
    )
    write_install_lock(
        project,
        ("claude", "codex"),
        claude_root=claude_root,
        codex_root=codex_root,
    )
    write_declaration(project, ("claude", "codex"))
    report = workspace_status(project, personal_registry=tmp_path / "personal.json")

    assert activated == ["codex", "claude"]
    assert report["state"] == "ready"
    assert report["installed_components"] == ["claude", "codex"]
    assert (project / "AGENTS.md").is_file()
    assert (project / "CLAUDE.md").is_file()
    lock = json.loads((project / "copilot.lock.json").read_text())
    assert [entry["component"] for entry in lock["components"]] == ["claude", "codex"]
    assert all(entry["files"] for entry in lock["components"])
    assert all(
        file["checksum"].startswith("sha256:")
        for entry in lock["components"]
        for file in entry["files"]
    )


def test_activation_resolves_claude_content_through_the_tier_ladder(tmp_path, monkeypatch):
    """`activate_components` no longer copies the `claude` product's
    protocol/agents from a single root -- when a layer manifest is
    configured, an organization tier's real (substantive) override wins
    for the ONE item it declares, and every other item still resolves to
    the foundation's real content, per (dimension, item) -- never per
    root. This is the keystone-defect fix: `workspaces.py`'s `_claude_plan()`
    now consults `copilot.layers.yml` instead of a single
    `paths.claude_copilot_root`."""
    project = tmp_path / "project"
    _git_init(project, "git@github.com:Example/Ladder.git")
    claude_root, _codex_root = _repo_roots()

    org_root = tmp_path / "org-tier"
    (org_root / "commands").mkdir(parents=True)
    # A real override that fully replaces protocol.md (OVERRIDE semantics
    # replace, never merge) is realistically close in size to what it
    # shadows -- long enough here to clear the substance gate's size-ratio
    # check (core/ecosystem/substance.py) just like genuine company content
    # would, rather than reading as an inert, disproportionately-smaller
    # stub.
    org_override = "# ENAC protocol override\n\n" + (
        "Real, substantive, company-specific instruction content. " * 400
    )
    (org_root / "commands" / "protocol.md").write_text(org_override, encoding="utf-8")

    manifest_path = tmp_path / "copilot.layers.yml"
    manifest_path.write_text(
        "version: 1\n"
        "layers:\n"
        "  - id: claude-organization\n"
        "    role: organization\n"
        "    rank: 30\n"
        "    product: claude\n"
        "    source:\n"
        "      repo: https://example.invalid/org.git\n"
        f"      path: {org_root}\n"
        "    auth: anon\n"
        "    activation: always\n"
        "  - id: claude-foundation\n"
        "    role: foundation\n"
        "    rank: 40\n"
        "    product: claude\n"
        "    source:\n"
        "      repo: https://example.invalid/foundation.git\n"
        f"      path: {claude_root}\n"
        "      subpath: .claude\n"
        "    auth: anon\n"
        "    activation: always\n",
        encoding="utf-8",
    )

    def _fake_resolve_key(key, **_kwargs):
        if key == "layers.manifest":
            return str(manifest_path)
        if key == "paths.mirrors_root":
            return str(tmp_path / "mirrors")
        return None

    monkeypatch.setattr(
        "cc.core.ecosystem.project_sources.resolve_key", _fake_resolve_key
    )

    activate_components(project, ("claude",), claude_root=claude_root)

    # The organization's real override wins for the one item it declares.
    assert (project / ".claude/commands/protocol.md").read_text(encoding="utf-8") == org_override
    # Everything the organization does NOT declare still resolves through
    # the ladder to the foundation's real content -- per-artifact, not
    # per-root: the org's one override does not shrink the install to just
    # what the org contributed.
    assert (project / ".claude/commands/continue.md").read_text(encoding="utf-8") == (
        claude_root / ".claude/commands/continue.md"
    ).read_text(encoding="utf-8")
    assert (project / ".claude/agents/qa.md").read_text(encoding="utf-8") == (
        claude_root / ".claude/agents/qa.md"
    ).read_text(encoding="utf-8")


def test_activation_placeholder_override_does_not_shadow_real_foundation_content(
    tmp_path, monkeypatch
):
    """The trap this fix must not reintroduce: an org-tier `TODO(`
    placeholder scaffold must never win over the foundation's real protocol
    merely by being the nearer tier."""
    project = tmp_path / "project"
    _git_init(project, "git@github.com:Example/Placeholder.git")
    claude_root, _codex_root = _repo_roots()

    org_root = tmp_path / "org-tier"
    (org_root / "commands").mkdir(parents=True)
    real_foundation_protocol = (claude_root / ".claude/commands/protocol.md").read_text(
        encoding="utf-8"
    )
    (org_root / "commands" / "protocol.md").write_text(
        "TODO(pablo): this section is currently a no-op placeholder with zero "
        "invented company content.\n\n" + real_foundation_protocol,
        encoding="utf-8",
    )

    manifest_path = tmp_path / "copilot.layers.yml"
    manifest_path.write_text(
        "version: 1\n"
        "layers:\n"
        "  - id: claude-organization\n"
        "    role: organization\n"
        "    rank: 30\n"
        "    product: claude\n"
        "    source:\n"
        "      repo: https://example.invalid/org.git\n"
        f"      path: {org_root}\n"
        "    auth: anon\n"
        "    activation: always\n"
        "  - id: claude-foundation\n"
        "    role: foundation\n"
        "    rank: 40\n"
        "    product: claude\n"
        "    source:\n"
        "      repo: https://example.invalid/foundation.git\n"
        f"      path: {claude_root}\n"
        "      subpath: .claude\n"
        "    auth: anon\n"
        "    activation: always\n",
        encoding="utf-8",
    )

    def _fake_resolve_key(key, **_kwargs):
        if key == "layers.manifest":
            return str(manifest_path)
        if key == "paths.mirrors_root":
            return str(tmp_path / "mirrors")
        return None

    monkeypatch.setattr(
        "cc.core.ecosystem.project_sources.resolve_key", _fake_resolve_key
    )

    activate_components(project, ("claude",), claude_root=claude_root)

    assert (
        project / ".claude/commands/protocol.md"
    ).read_text(encoding="utf-8") == real_foundation_protocol


def test_empty_project_is_safe_finish_with_closed_component_assessments(tmp_path):
    project = tmp_path / "empty"
    _git_init(project)
    claude_root, codex_root = _repo_roots()

    workspace = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        claude_root=claude_root,
        codex_root=codex_root,
        detail=True,
    )
    report = workspaces_command._report("status", [workspace])

    _assert_valid_workspace_report(report)
    assert workspace["classification"] == "safe-finish"
    assert workspace["state"] == "setup-available"
    assert workspace["responsible_actor"] == "cli"
    assert workspace["can_apply_now"] is True
    assert workspace["safe_action"]["kind"] == "add-missing"
    assert [item["component"] for item in workspace["components"]] == [
        "claude",
        "codex",
    ]
    assert {item["classification"] for item in workspace["components"]} == {
        "safe-finish"
    }


def test_tracked_components_require_checksums_and_entry_evidence_to_be_ready(
    tmp_path,
):
    project = tmp_path / "tracked"
    _git_init(project)
    claude_root, codex_root = _repo_roots()
    activate_components(
        project,
        ("claude", "codex"),
        claude_root=claude_root,
        codex_root=codex_root,
    )
    write_install_lock(
        project,
        ("claude", "codex"),
        claude_root=claude_root,
        codex_root=codex_root,
    )

    ready = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        claude_root=claude_root,
        codex_root=codex_root,
    )
    _assert_valid_workspace_report(workspaces_command._report("status", [ready]))
    assert ready["classification"] == "ready"
    assert ready["installed_components"] == ["claude", "codex"]
    assert all(
        item["recognized_setup"]["variant_id"].endswith("tracked-lock-v1")
        for item in ready["components"]
    )

    (project / ".claude/commands/protocol.md").write_text(
        "project edit after installation",
        encoding="utf-8",
    )
    mismatched = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        claude_root=claude_root,
        codex_root=codex_root,
    )

    assert mismatched["classification"] == "could-not-verify"
    assert mismatched["state"] == "blocked"
    assert mismatched["safe_action"] is None
    assert mismatched["diagnostic"]["mode"] == "read-only"
    assert mismatched["diagnostic"]["inspection_id"] == mismatched["inspection"]["id"]
    diagnostic_prompt = mismatched["diagnostic"]["prompt"]["text"]
    assert "READ-ONLY mode" in diagnostic_prompt
    assert (
        "Do not create, edit, rename, move, or delete project files."
        in diagnostic_prompt
    )
    assert "workspace verify --project" in diagnostic_prompt
    assert str(project) in diagnostic_prompt
    claude = next(
        item for item in mismatched["components"] if item["component"] == "claude"
    )
    assert claude["classification"] == "could-not-verify"
    assert any(
        requirement["id"] == "verified-framework-file"
        for requirement in claude["missing_requirements"]
    )


@pytest.mark.parametrize("gate_mode", ["missing-record", "external-symlink"])
def test_tracked_legacy_linked_project_gets_reviewed_migration_plan_without_writes(
    tmp_path, gate_mode
):
    project = tmp_path / "legacy-linked"
    _git_init(project)
    claude_root, codex_root = _repo_roots()
    activate_components(
        project,
        ("claude", "codex"),
        claude_root=claude_root,
        codex_root=codex_root,
    )
    write_install_lock(
        project,
        ("claude", "codex"),
        claude_root=claude_root,
        codex_root=codex_root,
    )

    external_root = tmp_path / "shared-codex"
    external_plugin = external_root / "plugins/codex-copilot"
    external_plugin.parent.mkdir(parents=True)
    shutil.copytree(codex_root / "plugins/codex-copilot", external_plugin)
    external_gate = external_root / "scripts/copilot-gate.sh"
    external_gate.parent.mkdir()
    shutil.copy2(codex_root / "scripts/copilot-gate.sh", external_gate)
    shutil.rmtree(project / "plugins/codex-copilot")
    (project / "plugins/codex-copilot").symlink_to(external_plugin)
    config_path = project / ".codex-copilot.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["installType"] = "symlink"
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    claude_path = project / "CLAUDE.md"
    claude_path.write_text(
        claude_path.read_text(encoding="utf-8").replace(
            "## Claude Copilot", "## Earlier Copilot Setup"
        ),
        encoding="utf-8",
    )
    if gate_mode == "missing-record":
        lock_path = project / "copilot.lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        codex_lock = next(
            item for item in lock["components"] if item["component"] == "codex"
        )
        codex_lock["files"] = [
            item
            for item in codex_lock["files"]
            if item["path"] != "scripts/copilot-gate.sh"
        ]
        lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    else:
        gate_path = project / "scripts/copilot-gate.sh"
        gate_path.unlink()
        gate_path.symlink_to(external_gate)
    linked_skill = tmp_path / "shared-uids.md"
    linked_skill.write_text("Legacy checkout moved.\n", encoding="utf-8")
    uids_path = external_plugin / "skills/uids/SKILL.md"
    uids_path.unlink()
    uids_path.symlink_to(linked_skill)
    uxd_path = external_plugin / "skills/uxd/SKILL.md"
    uxd_path.write_text(
        uxd_path.read_text(encoding="utf-8") + "\nLegacy checkout moved.\n",
        encoding="utf-8",
    )

    before = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file() and not path.is_symlink() and ".git" not in path.parts
    }
    workspace = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        claude_root=claude_root,
        codex_root=codex_root,
        detail=True,
    )
    after = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file() and not path.is_symlink() and ".git" not in path.parts
    }

    _assert_valid_workspace_report(workspaces_command._report("status", [workspace]))
    assert workspace["classification"] == "guided-integration"
    assert workspace["responsible_actor"] == "project-author"
    assert workspace["plan_available"] is True
    assert workspace["safe_action"] is None
    assert workspace["diagnostic"] is None
    assert before == after
    variants = {
        item["component"]: item["recognized_setup"]["variant_id"]
        for item in workspace["components"]
    }
    assert variants == {
        "claude": "claude-legacy-entry-v1",
        "codex": "codex-legacy-linked-v1",
    }
    codex = next(
        item for item in workspace["components"] if item["component"] == "codex"
    )
    assert any(
        requirement["id"] == "valid-codex-config"
        and "earlier linked installation" in requirement["detail"]
        for requirement in codex["missing_requirements"]
    )
    prompt = workspace["integration_plan"]["prompt"]["text"]
    assert "recognized earlier linked project integration" in prompt
    assert "do not copy through or modify the external link" in prompt
    assert "replace the recognized linked gate" in prompt
    assert "refresh helper-owned lock evidence" in prompt


def test_untracked_recognized_legacy_link_gets_guided_plan(tmp_path):
    project = tmp_path / "untracked-legacy-link"
    _git_init(project)
    claude_root, codex_root = _repo_roots()
    activate_components(
        project,
        ("claude", "codex"),
        claude_root=claude_root,
        codex_root=codex_root,
    )
    write_install_lock(
        project,
        ("claude",),
        claude_root=claude_root,
        codex_root=codex_root,
    )

    external_plugin = tmp_path / "untracked-shared-codex"
    shutil.copytree(codex_root / "plugins/codex-copilot", external_plugin)
    shutil.rmtree(project / "plugins/codex-copilot")
    (project / "plugins/codex-copilot").symlink_to(external_plugin)
    config_path = project / ".codex-copilot.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["installType"] = "symlink"
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    workspace = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        claude_root=claude_root,
        codex_root=codex_root,
        detail=True,
    )

    assert workspace["classification"] == "guided-integration"
    codex = next(
        item for item in workspace["components"] if item["component"] == "codex"
    )
    assert codex["recognized_setup"]["variant_id"] == "codex-legacy-linked-v1"
    assert any(
        requirement["id"] == "lock-record"
        for requirement in codex["missing_requirements"]
    )


def test_unrecognized_external_plugin_link_remains_could_not_verify(tmp_path):
    project = tmp_path / "unrecognized-link"
    _git_init(project)
    claude_root, codex_root = _repo_roots()
    activate_components(
        project,
        ("claude", "codex"),
        claude_root=claude_root,
        codex_root=codex_root,
    )
    write_install_lock(
        project,
        ("claude", "codex"),
        claude_root=claude_root,
        codex_root=codex_root,
    )

    external_plugin = tmp_path / "unrecognized-codex-copilot"
    shutil.copytree(codex_root / "plugins/codex-copilot", external_plugin)
    shutil.rmtree(project / "plugins/codex-copilot")
    (project / "plugins/codex-copilot").symlink_to(external_plugin)
    skill_path = external_plugin / "skills/uids/SKILL.md"
    skill_path.write_text("project-owned change\n", encoding="utf-8")

    workspace = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        claude_root=claude_root,
        codex_root=codex_root,
        detail=True,
    )

    assert workspace["classification"] == "could-not-verify"
    assert workspace["plan_available"] is False
    assert workspace["integration_plan"] is None
    assert workspace["diagnostic"]["mode"] == "read-only"


def test_custom_capability_models_are_guided_regardless_of_their_size(tmp_path):
    claude_root, codex_root = _repo_roots()
    reports = []
    for name, skill_count in (("small", 1), ("deep", 12)):
        project = tmp_path / name
        _git_init(project)
        (project / "CLAUDE.md").write_text("Project-owned Claude routing")
        (project / "AGENTS.md").write_text("Project-owned Codex routing")
        for index in range(skill_count):
            skill = project / f".agents/skills/skill-{index}/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text(f"# Skill {index}\n")
        reports.append(
            workspace_status(
                project,
                personal_registry=tmp_path / f"{name}.json",
                claude_root=claude_root,
                codex_root=codex_root,
                detail=True,
            )
        )

    assert [item["classification"] for item in reports] == [
        "guided-integration",
        "guided-integration",
    ]
    assert [item["capabilities"]["skills"] for item in reports] == [1, 12]
    assert all(item["integration_plan"]["prompt"]["version"] == "1" for item in reports)
    assert all(item["safe_action"] is None for item in reports)


def test_guided_project_can_report_an_individually_safe_component(tmp_path):
    project = tmp_path / "mixed-route"
    _git_init(project)
    (project / "AGENTS.md").write_text("Project-owned Codex routing")
    claude_root, codex_root = _repo_roots()

    workspace = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        claude_root=claude_root,
        codex_root=codex_root,
        detail=True,
    )
    report = workspaces_command._report("status", [workspace])

    _assert_valid_workspace_report(report)
    assert workspace["classification"] == "guided-integration"
    assert workspace["safe_action"] is None
    assert workspace["plan_available"] is True
    claude = next(
        item for item in workspace["components"] if item["component"] == "claude"
    )
    assert claude["classification"] == "safe-finish"
    assert claude["responsible_actor"] == "cli"
    assert claude["safe_action"] is None


def test_owner_declaration_produces_detail_handoff_and_bounded_summary(tmp_path):
    project = tmp_path / "owned"
    _git_init(project)
    owner = project / ".copilot/project-owner.json"
    owner.parent.mkdir()
    owner.write_text(
        json.dumps({"decision_required": True, "owner": "project-owner"}),
        encoding="utf-8",
    )
    claude_root, codex_root = _repo_roots()

    detailed = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        claude_root=claude_root,
        codex_root=codex_root,
        detail=True,
    )
    summary = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        claude_root=claude_root,
        codex_root=codex_root,
        detail=False,
    )

    assert detailed["classification"] == "owner-decision"
    assert detailed["responsible_actor"] == "project-owner"
    assert detailed["integration_plan"]["prompt"] is None
    assert detailed["integration_plan"]["owner_handoff"]["version"] == "1"
    assert summary["inspection"]["scope"] == "summary"
    assert summary["plan_available"] is True
    assert summary["integration_plan"] is None
    _assert_valid_workspace_report(workspaces_command._report("status", [summary]))


def test_external_component_symlink_fails_closed(tmp_path):
    project = tmp_path / "external-link"
    external = tmp_path / "outside"
    _git_init(project)
    external.mkdir()
    link = project / ".claude/skills/codex-copilot"
    link.parent.mkdir(parents=True)
    link.symlink_to(external, target_is_directory=True)
    claude_root, codex_root = _repo_roots()

    report = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        claude_root=claude_root,
        codex_root=codex_root,
    )

    assert report["classification"] == "could-not-verify"
    assert report["state"] == "blocked"
    assert "follow-external-symlink" in report["preservation"]["prohibited_actions"]


def test_malformed_project_lock_fails_closed_for_both_components(tmp_path):
    project = tmp_path / "malformed-lock"
    _git_init(project)
    (project / "copilot.lock.json").write_text(
        json.dumps({"schema_version": "9.0", "components": "not-a-list"}),
        encoding="utf-8",
    )
    claude_root, codex_root = _repo_roots()

    workspace = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        claude_root=claude_root,
        codex_root=codex_root,
        detail=False,
    )
    report = workspaces_command._report("status", [workspace])

    _assert_valid_workspace_report(report)
    assert workspace["classification"] == "could-not-verify"
    assert workspace["diagnostic"] is None
    assert {item["classification"] for item in workspace["components"]} == {
        "could-not-verify"
    }
    assert all(
        item["missing_requirements"][0]["id"] == "readable-project-lock"
        for item in workspace["components"]
    )


def test_safe_finish_empty_project_applies_exact_targets_and_verifies(tmp_path):
    project = tmp_path / "finish-empty"
    _git_init(project)
    claude_root, codex_root = _repo_roots()
    before = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        claude_root=claude_root,
        codex_root=codex_root,
    )
    action = before["safe_action"]

    inspected_before, inspected_after = finish_project_integration(
        project,
        action["id"],
        claude_root=claude_root,
        codex_root=codex_root,
    )
    after = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        claude_root=claude_root,
        codex_root=codex_root,
    )

    assert inspected_before["inspection"]["id"] == action["inspection_id"]
    assert inspected_after["classification"] == "ready"
    assert after["classification"] == "ready"
    assert after["installed_components"] == ["claude", "codex"]
    assert (project / "copilot.lock.json").is_file()
    assert (project / "CLAUDE.md").is_file()
    assert (project / "AGENTS.md").is_file()
    assert after["safe_action"] is None
    _assert_valid_workspace_report(workspaces_command._report("finish", [after]))


def test_safe_finish_refuses_stale_action_without_writes(tmp_path):
    project = tmp_path / "stale"
    _git_init(project)
    claude_root, codex_root = _repo_roots()
    before = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        claude_root=claude_root,
        codex_root=codex_root,
    )
    action_id = before["safe_action"]["id"]
    (project / "AGENTS.md").write_text("Project-owned routing", encoding="utf-8")

    try:
        finish_project_integration(
            project,
            action_id,
            claude_root=claude_root,
            codex_root=codex_root,
        )
    except ActivationError as exc:
        assert "stale or no longer applies" in str(exc)
    else:
        raise AssertionError("a stale safe-finish action must be refused")

    assert (project / "AGENTS.md").read_text(
        encoding="utf-8"
    ) == "Project-owned routing"
    assert not (project / "CLAUDE.md").exists()
    assert not (project / "copilot.lock.json").exists()


def test_safe_finish_rolls_back_all_new_targets_when_lock_write_fails(
    monkeypatch, tmp_path
):
    project = tmp_path / "rollback"
    _git_init(project)
    claude_root, codex_root = _repo_roots()
    before = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        claude_root=claude_root,
        codex_root=codex_root,
    )

    monkeypatch.setattr(
        core_workspaces,
        "write_install_lock",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ActivationError("synthetic lock failure")
        ),
    )
    try:
        finish_project_integration(
            project,
            before["safe_action"]["id"],
            claude_root=claude_root,
            codex_root=codex_root,
        )
    except ActivationError as exc:
        assert str(exc) == "synthetic lock failure"
    else:
        raise AssertionError("the synthetic lock failure must escape")

    assert sorted(path.name for path in project.iterdir()) == [".git"]


def test_safe_finish_adopts_exact_existing_setup_without_rewriting_it(tmp_path):
    project = tmp_path / "adopt"
    _git_init(project)
    claude_root, codex_root = _repo_roots()
    activate_components(
        project,
        ("claude", "codex"),
        claude_root=claude_root,
        codex_root=codex_root,
    )
    before_hashes = {
        path.relative_to(project).as_posix(): core_workspaces._checksum(path)
        for path in project.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }
    before = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        claude_root=claude_root,
        codex_root=codex_root,
    )

    assert before["classification"] == "safe-finish"
    assert before["safe_action"]["kind"] == "adopt-existing"
    finish_project_integration(
        project,
        before["safe_action"]["id"],
        claude_root=claude_root,
        codex_root=codex_root,
    )
    after_hashes = {
        path.relative_to(project).as_posix(): core_workspaces._checksum(path)
        for path in project.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and path.name != "copilot.lock.json"
    }

    assert after_hashes == before_hashes
    assert (project / "copilot.lock.json").is_file()


def test_verify_command_reports_only_authoritative_ready(monkeypatch, capsys, tmp_path):
    project = tmp_path / "verify"
    _git_init(project)
    claude_root, codex_root = _repo_roots()

    def roots(key):
        if key == "paths.claude_copilot_root":
            return str(claude_root)
        if key == "paths.codex_copilot_root":
            return str(codex_root)
        return None

    monkeypatch.setattr(core_workspaces, "resolve_key", roots)
    monkeypatch.setattr(integration_core, "resolve_key", roots)
    before = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        claude_root=claude_root,
        codex_root=codex_root,
    )
    try:
        workspaces_command.verify(project=str(project), output_json=True)
    except Exception as exc:
        assert exc.__class__.__name__ == "Exit"
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["mode"] == "verify"
    assert blocked["result"] == "blocked"

    finish_project_integration(
        project,
        before["safe_action"]["id"],
        claude_root=claude_root,
        codex_root=codex_root,
    )
    workspaces_command.verify(project=str(project), output_json=True)
    ready = json.loads(capsys.readouterr().out)

    _assert_valid_workspace_report(ready)
    assert ready["mode"] == "verify"
    assert ready["result"] == "ready"


def test_finish_command_plans_without_writes_then_applies_and_verifies(
    monkeypatch, capsys, tmp_path
):
    project = tmp_path / "finish-command"
    _git_init(project)
    claude_root, codex_root = _repo_roots()

    def roots(key):
        if key == "paths.claude_copilot_root":
            return str(claude_root)
        if key == "paths.codex_copilot_root":
            return str(codex_root)
        return None

    monkeypatch.setattr(core_workspaces, "resolve_key", roots)
    monkeypatch.setattr(integration_core, "resolve_key", roots)
    workspace = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        claude_root=claude_root,
        codex_root=codex_root,
    )
    action_id = workspace["safe_action"]["id"]

    workspaces_command.finish(
        project=str(project),
        action_id=action_id,
        apply=False,
        output_json=True,
    )
    plan = json.loads(capsys.readouterr().out)
    _assert_valid_workspace_report(plan)
    assert plan["mode"] == "finish"
    assert plan["result"] == "action-required"
    assert not (project / "CLAUDE.md").exists()

    workspaces_command.finish(
        project=str(project),
        action_id=action_id,
        apply=True,
        output_json=True,
    )
    applied = json.loads(capsys.readouterr().out)

    _assert_valid_workspace_report(applied)
    assert applied["mode"] == "finish"
    assert applied["result"] == "applied"
    assert applied["workspaces"][0]["classification"] == "ready"


def test_plan_command_returns_versioned_launch_prompt_without_writes(
    monkeypatch, capsys, tmp_path
):
    project = tmp_path / "guided-plan"
    _git_init(project)
    (project / "CLAUDE.md").write_text("Project-owned Claude routing")
    (project / "AGENTS.md").write_text("Project-owned Codex routing")
    claude_root, codex_root = _repo_roots()
    holds_registry = tmp_path / "holds.json"

    def roots(key):
        if key == "paths.claude_copilot_root":
            return str(claude_root)
        if key == "paths.codex_copilot_root":
            return str(codex_root)
        return None

    monkeypatch.setattr(core_workspaces, "resolve_key", roots)
    monkeypatch.setattr(integration_core, "resolve_key", roots)
    monkeypatch.setattr(
        core_workspaces,
        "default_integration_holds_registry",
        lambda: holds_registry,
    )
    before = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }

    workspaces_command.plan_integration(
        project=str(project),
        output_json=True,
    )
    report = json.loads(capsys.readouterr().out)
    after = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }

    _assert_valid_workspace_report(report)
    workspace = report["workspaces"][0]
    assert report["mode"] == "plan"
    assert report["result"] == "action-required"
    assert workspace["classification"] == "guided-integration"
    assert workspace["integration_plan"]["prompt"]["version"] == "1"
    assert workspace["integration_plan"]["verification"]["command"][:3] == [
        "cc",
        "workspace",
        "verify",
    ]
    assert workspace["integration_plan"]["owner_handoff"] is None
    assert before == after
    assert not holds_registry.exists()


def test_hold_command_persists_only_opaque_owner_decision_state(
    monkeypatch, capsys, tmp_path
):
    project = tmp_path / "guided-hold"
    _git_init(project)
    (project / "CLAUDE.md").write_text("Project-owned Claude routing")
    (project / "AGENTS.md").write_text("Project-owned Codex routing")
    claude_root, codex_root = _repo_roots()
    holds_registry = tmp_path / "holds.json"

    def roots(key):
        if key == "paths.claude_copilot_root":
            return str(claude_root)
        if key == "paths.codex_copilot_root":
            return str(codex_root)
        return None

    monkeypatch.setattr(core_workspaces, "resolve_key", roots)
    monkeypatch.setattr(integration_core, "resolve_key", roots)
    monkeypatch.setattr(
        core_workspaces,
        "default_integration_holds_registry",
        lambda: holds_registry,
    )
    before = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        holds_registry=holds_registry,
        claude_root=claude_root,
        codex_root=codex_root,
    )
    plan_id = before["integration_plan"]["id"]

    workspaces_command.hold_integration(
        project=str(project),
        plan_id=plan_id,
        apply=False,
        output_json=True,
    )
    planned = json.loads(capsys.readouterr().out)
    assert planned["result"] == "action-required"
    assert not holds_registry.exists()

    workspaces_command.hold_integration(
        project=str(project),
        plan_id=plan_id,
        apply=True,
        output_json=True,
    )
    applied = json.loads(capsys.readouterr().out)
    registry_text = holds_registry.read_text(encoding="utf-8")

    _assert_valid_workspace_report(applied)
    assert applied["result"] == "applied"
    assert applied["workspaces"][0]["classification"] == "owner-decision"
    assert applied["workspaces"][0]["integration_plan"]["prompt"] is None
    assert (
        applied["workspaces"][0]["integration_plan"]["owner_handoff"]["version"] == "1"
    )
    assert integration_hold(project, registry=holds_registry) is not None
    assert str(project) not in registry_text
    assert project.name not in registry_text
    assert "prompt" not in registry_text
    assert "owner-decision" in registry_text


def test_hold_rejects_safe_project_and_stale_plan_without_persistence(
    monkeypatch, capsys, tmp_path
):
    project = tmp_path / "hold-refusal"
    _git_init(project)
    claude_root, codex_root = _repo_roots()
    holds_registry = tmp_path / "holds.json"

    def roots(key):
        if key == "paths.claude_copilot_root":
            return str(claude_root)
        if key == "paths.codex_copilot_root":
            return str(codex_root)
        return None

    monkeypatch.setattr(core_workspaces, "resolve_key", roots)
    monkeypatch.setattr(integration_core, "resolve_key", roots)
    monkeypatch.setattr(
        core_workspaces,
        "default_integration_holds_registry",
        lambda: holds_registry,
    )

    try:
        workspaces_command.hold_integration(
            project=str(project),
            plan_id="sha256:" + "0" * 64,
            apply=True,
            output_json=True,
        )
    except Exception as exc:
        assert exc.__class__.__name__ == "Exit"
    report = json.loads(capsys.readouterr().out)

    assert report["result"] == "blocked"
    assert report["workspaces"][0]["classification"] == "safe-finish"
    assert not holds_registry.exists()

    stale_project = tmp_path / "stale-guided-plan"
    _git_init(stale_project)
    (stale_project / "CLAUDE.md").write_text("Project-owned Claude routing")
    (stale_project / "AGENTS.md").write_text("Project-owned Codex routing")
    guided = workspace_status(
        stale_project,
        personal_registry=tmp_path / "personal.json",
        holds_registry=holds_registry,
        claude_root=claude_root,
        codex_root=codex_root,
    )
    old_plan_id = guided["integration_plan"]["id"]
    (stale_project / "AGENTS.md").write_text("Changed project-owned routing")
    try:
        workspaces_command.hold_integration(
            project=str(stale_project),
            plan_id=old_plan_id,
            apply=True,
            output_json=True,
        )
    except Exception as exc:
        assert exc.__class__.__name__ == "Exit"
    stale = json.loads(capsys.readouterr().out)

    assert stale["result"] == "blocked"
    assert not holds_registry.exists()


def test_assistant_self_report_never_changes_guided_classification(tmp_path):
    project = tmp_path / "assistant-claim"
    _git_init(project)
    (project / "CLAUDE.md").write_text("Project-owned Claude routing")
    (project / "AGENTS.md").write_text("Project-owned Codex routing")
    claim = project / ".copilot/assistant-result.json"
    claim.parent.mkdir()
    claim.write_text(
        json.dumps({"result": "ready", "verified": True}),
        encoding="utf-8",
    )
    claude_root, codex_root = _repo_roots()

    report = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        holds_registry=tmp_path / "holds.json",
        claude_root=claude_root,
        codex_root=codex_root,
    )

    assert report["classification"] == "guided-integration"
    assert report["state"] == "blocked"
    assert "trust-assistant-self-report" in report["preservation"]["prohibited_actions"]


def test_successful_cli_verification_clears_completed_owner_hold(
    monkeypatch, capsys, tmp_path
):
    project = tmp_path / "clear-hold"
    _git_init(project)
    (project / "CLAUDE.md").write_text("Project-owned Claude routing")
    (project / "AGENTS.md").write_text("Project-owned Codex routing")
    claude_root, codex_root = _repo_roots()
    holds_registry = tmp_path / "holds.json"

    def roots(key):
        if key == "paths.claude_copilot_root":
            return str(claude_root)
        if key == "paths.codex_copilot_root":
            return str(codex_root)
        return None

    monkeypatch.setattr(core_workspaces, "resolve_key", roots)
    monkeypatch.setattr(integration_core, "resolve_key", roots)
    monkeypatch.setattr(
        core_workspaces,
        "default_integration_holds_registry",
        lambda: holds_registry,
    )
    guided = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        holds_registry=holds_registry,
        claude_root=claude_root,
        codex_root=codex_root,
    )
    workspaces_command.hold_integration(
        project=str(project),
        plan_id=guided["integration_plan"]["id"],
        apply=True,
        output_json=True,
    )
    capsys.readouterr()
    assert integration_hold(project, registry=holds_registry) is not None

    (project / "CLAUDE.md").unlink()
    (project / "AGENTS.md").unlink()
    activate_components(
        project,
        ("claude", "codex"),
        claude_root=claude_root,
        codex_root=codex_root,
    )
    write_install_lock(
        project,
        ("claude", "codex"),
        claude_root=claude_root,
        codex_root=codex_root,
    )
    workspaces_command.verify(project=str(project), output_json=True)
    report = json.loads(capsys.readouterr().out)

    assert report["result"] == "ready"
    assert integration_hold(project, registry=holds_registry) is None
    assert read_integration_holds_registry(holds_registry)["holds"] == {}


def test_activation_collision_blocks_before_any_selected_product_writes(tmp_path):
    project = tmp_path / "project"
    _git_init(project)
    (project / "AGENTS.md").write_text("project-owned")
    claude_root, codex_root = _repo_roots()

    try:
        activate_components(
            project,
            ("claude", "codex"),
            claude_root=claude_root,
            codex_root=codex_root,
        )
    except ActivationError:
        pass
    else:
        raise AssertionError("collision should block activation")

    assert (project / "AGENTS.md").read_text() == "project-owned"
    assert not (project / "CLAUDE.md").exists()
    assert not (project / ".codex-copilot.json").exists()


def test_root_approval_is_explicit_idempotent_and_names_are_for_display(
    monkeypatch, capsys, tmp_path
):
    selected = tmp_path / "Projects"
    selected.mkdir()
    written = []
    monkeypatch.setattr(workspaces_command, "resolve_key", lambda _key: [])
    monkeypatch.setattr(
        workspaces_command,
        "add_to_list_config",
        lambda key, value: written.append((key, value)),
    )
    monkeypatch.setattr(
        core_workspaces,
        "default_known_projects_registry",
        lambda: tmp_path / "known-projects.json",
    )

    workspaces_command.approve_root(path=str(selected), apply=True, output_json=True)
    payload = json.loads(capsys.readouterr().out)

    assert written == [("projects.roots", str(selected.resolve()))]
    assert payload["result"] == "applied"
    assert payload["root"]["name"] == "Projects"
    # The path round-trips to the CLI (e.g. for forget-root) but is never the
    # thing the app renders -- `name` is.
    assert payload["root"]["path"] == str(selected.resolve())


def test_root_approval_refuses_symlink_without_writing(monkeypatch, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    monkeypatch.setattr(workspaces_command, "resolve_key", lambda _key: [])
    monkeypatch.setattr(
        workspaces_command,
        "add_to_list_config",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not write")),
    )

    try:
        workspaces_command.approve_root(path=str(link), apply=True, output_json=True)
    except SystemExit:
        pass
    except Exception as exc:
        # Typer raises its own Exit type rather than built-in SystemExit when
        # command functions are called directly.
        assert exc.__class__.__name__ == "Exit"
    else:
        raise AssertionError("symlink root should be blocked")


# ---------------------------------------------------------------------------
# Candidate root detection ("always find the user's projects")
# ---------------------------------------------------------------------------


def test_detect_candidate_roots_finds_nothing_when_no_conventional_folder_has_a_project(
    monkeypatch, tmp_path
):
    home = tmp_path / "empty-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(core_workspaces, "resolve_key", lambda _key: [])

    assert detect_candidate_roots() == []


def test_detect_candidate_roots_finds_several_conventional_folders(
    monkeypatch, tmp_path
):
    home = tmp_path / "home"
    home.mkdir()
    developer = home / "Developer"
    _git_init(developer / "widget")
    sites = home / "Sites"
    _git_init(sites / "site-one")
    _git_init(sites / "site-two")
    (home / "Projects").mkdir()  # exists, but holds no Git project -- not a candidate
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(core_workspaces, "resolve_key", lambda _key: [])

    candidates = {item["label"]: item for item in detect_candidate_roots()}

    assert set(candidates) == {"Developer", "Sites"}
    assert candidates["Developer"] == {
        "path": str(developer.resolve()),
        "label": "Developer",
        "project_count": 1,
    }
    assert candidates["Sites"]["project_count"] == 2


def test_detect_candidate_roots_excludes_an_already_approved_folder(
    monkeypatch, tmp_path
):
    home = tmp_path / "home"
    home.mkdir()
    developer = home / "Developer"
    _git_init(developer / "widget")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(
        core_workspaces,
        "resolve_key",
        lambda key: [str(developer)] if key == "projects.roots" else [],
    )

    assert detect_candidate_roots() == []


def test_roots_command_reports_no_folders_and_no_candidates(
    monkeypatch, capsys, tmp_path
):
    home = tmp_path / "empty-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(core_workspaces, "resolve_key", lambda _key: [])

    workspaces_command.roots(output_json=True)
    payload = json.loads(capsys.readouterr().out)

    assert payload == {
        "schema_version": "1.1",
        "mode": "status",
        "result": "action-required",
        "roots": [],
        "candidates": [],
    }


def test_roots_command_reports_already_configured_folders_and_new_candidates(
    monkeypatch, capsys, tmp_path
):
    home = tmp_path / "home"
    home.mkdir()
    approved = home / "Work"
    _git_init(approved / "one")
    developer = home / "Developer"
    _git_init(developer / "two")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(
        core_workspaces,
        "resolve_key",
        lambda key: [str(approved)] if key == "projects.roots" else [],
    )

    workspaces_command.roots(output_json=True)
    payload = json.loads(capsys.readouterr().out)

    assert payload["result"] == "ready"
    assert payload["roots"] == [
        {"name": "Work", "path": str(approved.resolve()), "project_count": 1}
    ]
    assert payload["candidates"] == [
        {"path": str(developer.resolve()), "label": "Developer", "project_count": 1}
    ]


# ---------------------------------------------------------------------------
# `configure --apply-all`
# ---------------------------------------------------------------------------


def test_apply_all_plans_every_project_that_needs_setup_and_skips_ready_ones(
    monkeypatch, capsys, tmp_path
):
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    already_ready = tmp_path / "gamma"
    _git_init(alpha)
    _git_init(beta)
    _git_init(already_ready)
    (already_ready / ".claude/commands").mkdir(parents=True)
    (already_ready / ".claude/commands/protocol.md").write_text("framework")
    (already_ready / ".mcp.json").write_text("{}")
    monkeypatch.setattr(
        workspaces_command, "discover_workspaces", lambda: [alpha, already_ready, beta]
    )
    _use_fixture_installers(monkeypatch)

    workspaces_command.configure(
        project=None,
        apply_all=True,
        components="claude",
        share_with_project=False,
        associate_personal=True,
        apply=False,
        output_json=True,
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["mode"] == "plan"
    paths = {item["path"] for item in payload["workspaces"]}
    assert paths == {str(alpha.resolve()), str(beta.resolve())}
    assert payload["summary"]["total"] == 2


def test_apply_all_applies_every_project_and_collects_a_per_project_failure(
    monkeypatch, capsys, tmp_path
):
    ok_project = tmp_path / "ok"
    failing_project = tmp_path / "failing"
    _git_init(ok_project)
    _git_init(failing_project)
    monkeypatch.setattr(
        workspaces_command, "discover_workspaces", lambda: [failing_project, ok_project]
    )
    _use_fixture_installers(monkeypatch)

    def fake_activate(root, components):
        if root == failing_project:
            raise ActivationError(
                "Existing project setup needs review before Claude Copilot can add shared files."
            )
        return list(components)

    monkeypatch.setattr(workspaces_command, "activate_components", fake_activate)
    monkeypatch.setattr(
        workspaces_command, "write_install_lock", lambda *_a, **_k: None
    )

    # One project genuinely failing exits non-zero (result: blocked); the
    # report is still emitted and the other project's own outcome is intact.
    try:
        workspaces_command.configure(
            project=None,
            apply_all=True,
            components="claude",
            share_with_project=False,
            associate_personal=False,
            apply=True,
            output_json=True,
        )
    except Exception as exc:
        assert exc.__class__.__name__ == "Exit"
    payload = json.loads(capsys.readouterr().out)

    by_path = {item["path"]: item for item in payload["workspaces"]}
    assert by_path[str(ok_project.resolve())]["state"] != "blocked"
    assert by_path[str(failing_project.resolve())]["state"] == "blocked"
    assert (
        by_path[str(failing_project.resolve())]["detail"]
        == "Existing project setup needs review before Claude Copilot can add shared files."
    )
    assert payload["result"] == "blocked"


# ---------------------------------------------------------------------------
# `forget-root`
# ---------------------------------------------------------------------------


def test_forget_root_removes_an_approved_folder_and_is_idempotent(
    monkeypatch, capsys, tmp_path
):
    approved = tmp_path / "Projects"
    approved.mkdir()
    configured = [str(approved)]
    written = []
    monkeypatch.setattr(
        workspaces_command, "resolve_key", lambda _key: list(configured)
    )

    def fake_remove(key, value):
        written.append((key, value))
        configured.remove(value)

    monkeypatch.setattr(workspaces_command, "remove_from_list_config", fake_remove)
    monkeypatch.setattr(
        core_workspaces,
        "default_known_projects_registry",
        lambda: tmp_path / "known-projects.json",
    )

    workspaces_command.forget_root(path=str(approved), apply=True, output_json=True)
    payload = json.loads(capsys.readouterr().out)

    assert written == [("projects.roots", str(approved.resolve()))]
    assert payload["result"] == "applied"
    assert payload["root"] == {
        "name": "Projects",
        "path": str(approved.resolve()),
        "state": "removed",
        "detail": "Control Tower stopped looking in this folder. Nothing inside it was changed.",
    }

    # Calling again now that it is already removed is a safe no-op.
    written.clear()
    workspaces_command.forget_root(path=str(approved), apply=True, output_json=True)
    payload_again = json.loads(capsys.readouterr().out)

    assert written == []
    assert payload_again["result"] == "ready"
    assert payload_again["root"]["state"] == "removed"


# ---------------------------------------------------------------------------
# `decline`
# ---------------------------------------------------------------------------


def test_decline_records_the_opt_out_and_is_idempotent(monkeypatch, capsys, tmp_path):
    state = {"declined": False, "roots": []}

    def fake_resolve_key(key):
        if key == "projects.declined":
            return state["declined"]
        if key == "projects.roots":
            return state["roots"]
        return None

    def fake_write_config(key, value):
        assert key == "projects.declined"
        state["declined"] = value

    monkeypatch.setattr(workspaces_command, "resolve_key", fake_resolve_key)
    monkeypatch.setattr(core_workspaces, "resolve_key", fake_resolve_key)
    monkeypatch.setattr(workspaces_command, "write_config", fake_write_config)

    workspaces_command.decline(apply=True, output_json=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"] == "applied"
    assert payload["discovery"]["state"] == "declined"

    # Declining twice is a safe no-op.
    workspaces_command.decline(apply=True, output_json=True)
    payload_again = json.loads(capsys.readouterr().out)
    assert payload_again["result"] == "ready"
    assert payload_again["discovery"]["state"] == "declined"


def test_approving_a_root_reverses_a_previous_decline(monkeypatch, capsys, tmp_path):
    selected = tmp_path / "Projects"
    selected.mkdir()
    state = {"declined": True, "roots": []}
    unset_calls = []

    def fake_resolve_key(key):
        if key == "projects.declined":
            return state["declined"]
        if key == "projects.roots":
            return state["roots"]
        return None

    def fake_unset_config(key):
        unset_calls.append(key)
        state["declined"] = False
        return True

    monkeypatch.setattr(workspaces_command, "resolve_key", fake_resolve_key)
    monkeypatch.setattr(
        workspaces_command,
        "add_to_list_config",
        lambda key, value: state["roots"].append(value),
    )
    monkeypatch.setattr(workspaces_command, "unset_config", fake_unset_config)
    monkeypatch.setattr(
        core_workspaces,
        "default_known_projects_registry",
        lambda: tmp_path / "known-projects.json",
    )

    workspaces_command.approve_root(path=str(selected), apply=True, output_json=True)
    capsys.readouterr()

    assert unset_calls == ["projects.declined"]
    assert state["declined"] is False


# ---------------------------------------------------------------------------
# `revert` / undo
# ---------------------------------------------------------------------------


def test_undo_status_reports_nothing_to_undo_for_a_project_never_set_up(tmp_path):
    project = tmp_path / "plain"
    _git_init(project)

    assert undo_status(project) == {
        "available": False,
        "detail": "There's nothing here to undo yet.",
    }


def test_revert_removes_only_recorded_files_and_excludes_the_project_from_automatic_setup(
    tmp_path,
):
    project = tmp_path / "project"
    _git_init(project, "git@github.com:Example/Revert.git")
    claude_root, codex_root = _repo_roots()

    activate_components(
        project, ("claude", "codex"), claude_root=claude_root, codex_root=codex_root
    )
    write_install_lock(
        project, ("claude", "codex"), claude_root=claude_root, codex_root=codex_root
    )
    exclude_registry = tmp_path / "excluded-projects.json"

    plan = undo_status(project)
    assert plan == {
        "available": True,
        "detail": "Removes only what I added. Your own files are left alone.",
    }

    outcome = revert_project(project, exclude_registry=exclude_registry)

    assert set(outcome["removed"]) == {"claude", "codex"}
    assert (
        outcome["detail"]
        == "Removed. Your own files were left alone, and I won't set this project up again unless you ask."
    )
    assert not (project / ".claude/commands/protocol.md").exists()
    assert not (project / "plugins/codex-copilot/.codex-plugin/plugin.json").exists()
    assert (project / ".git").is_dir()  # the person's own repository is untouched

    lock = json.loads((project / "copilot.lock.json").read_text())
    assert lock["components"] == []
    assert is_project_excluded(project, registry=exclude_registry)

    status_after = workspace_status(project, exclude_registry=exclude_registry)
    assert status_after["installed_components"] == []
    assert status_after["setup_policy"] == "excluded"
    assert status_after["undo"] == {
        "available": False,
        "detail": "There's nothing here to undo yet.",
    }


def test_revert_refuses_when_a_recorded_file_was_edited_since(tmp_path):
    project = tmp_path / "project"
    _git_init(project, "git@github.com:Example/Edited.git")
    claude_root, codex_root = _repo_roots()

    activate_components(
        project, ("claude",), claude_root=claude_root, codex_root=codex_root
    )
    write_install_lock(
        project, ("claude",), claude_root=claude_root, codex_root=codex_root
    )
    (project / ".claude/commands/protocol.md").write_text("edited by the person")

    plan = undo_status(project)
    assert plan == {
        "available": False,
        "detail": "You've changed these files since, so I'll leave them alone.",
    }

    try:
        revert_project(project)
    except RevertError as exc:
        assert str(exc) == "You've changed these files since, so I'll leave them alone."
    else:
        raise AssertionError("an edited recorded file should block revert")

    assert (
        project / ".claude/commands/protocol.md"
    ).read_text() == "edited by the person"


def test_revert_command_plan_then_apply_shapes(monkeypatch, capsys, tmp_path):
    project = tmp_path / "project"
    _git_init(project, "git@github.com:Example/CliRevert.git")
    claude_root, codex_root = _repo_roots()
    _use_fixture_installers(monkeypatch)
    activate_components(
        project, ("claude",), claude_root=claude_root, codex_root=codex_root
    )
    write_install_lock(
        project, ("claude",), claude_root=claude_root, codex_root=codex_root
    )
    monkeypatch.setattr(
        core_workspaces,
        "default_excluded_registry",
        lambda: tmp_path / "excluded-projects.json",
    )

    workspaces_command.revert(project=str(project), apply=False, output_json=True)
    plan_payload = json.loads(capsys.readouterr().out)
    assert plan_payload["mode"] == "plan"
    assert plan_payload["result"] == "action-required"
    assert (
        plan_payload["revert"]["detail"]
        == "Removes only what I added. Your own files are left alone."
    )

    workspaces_command.revert(project=str(project), apply=True, output_json=True)
    apply_payload = json.loads(capsys.readouterr().out)
    assert apply_payload["mode"] == "apply"
    assert apply_payload["result"] == "applied"
    assert apply_payload["revert"]["removed"] == ["claude"]
    assert apply_payload["workspaces"][0]["state"] == "setup-available"
    assert apply_payload["workspaces"][0]["setup_policy"] == "excluded"


# ---------------------------------------------------------------------------
# `setup_policy: "automatic"` for a brand-new project (B3)
# ---------------------------------------------------------------------------


def _repo_roots():
    return (
        Path(__file__).resolve().parents[3],
        Path(__file__).parent / "fixtures" / "codex-installer",
    )


def _use_fixture_installers(monkeypatch):
    claude_root, codex_root = _repo_roots()
    values = {
        "paths.claude_copilot_root": str(claude_root),
        "paths.codex_copilot_root": str(codex_root),
    }
    monkeypatch.setattr(core_workspaces, "resolve_key", values.get)
    monkeypatch.setattr(integration_core, "resolve_key", values.get)


def test_project_present_at_grant_time_is_always_ask(tmp_path):
    root = tmp_path / "Projects"
    existing_project = root / "already-here"
    _git_init(existing_project)
    known_registry = tmp_path / "known-projects.json"
    claude_root, codex_root = _repo_roots()

    record_root_grant(root, registry=known_registry)

    report = workspace_status(
        existing_project,
        personal_registry=tmp_path / "personal.json",
        known_projects_registry=known_registry,
        configured_roots=[root],
        claude_root=claude_root,
        codex_root=codex_root,
    )

    assert report["setup_policy"] == "ask"
    assert report["policy_detail"] == "You'll be asked before anything is added here."


def test_project_created_after_the_root_was_granted_is_automatic(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    known_registry = tmp_path / "known-projects.json"
    claude_root, codex_root = _repo_roots()

    record_root_grant(root, registry=known_registry)  # nothing here yet

    new_project = root / "brand-new"
    _git_init(new_project)  # created after the grant

    report = workspace_status(
        new_project,
        personal_registry=tmp_path / "personal.json",
        known_projects_registry=known_registry,
        configured_roots=[root],
        claude_root=claude_root,
        codex_root=codex_root,
    )

    assert report["can_apply_now"] is True
    assert report["setup_policy"] == "automatic"
    assert (
        report["policy_detail"]
        == "This project is new, so I'll set it up for you without asking."
    )


def test_project_outside_any_granted_root_keeps_the_honest_ask_default(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    known_registry = tmp_path / "known-projects.json"
    record_root_grant(root, registry=known_registry)

    elsewhere = tmp_path / "elsewhere"
    _git_init(elsewhere)

    claude_root, codex_root = _repo_roots()
    report = workspace_status(
        elsewhere,
        personal_registry=tmp_path / "personal.json",
        known_projects_registry=known_registry,
        configured_roots=[root],
        claude_root=claude_root,
        codex_root=codex_root,
    )

    assert report["setup_policy"] == "ask"


def test_dirty_tree_still_holds_so_a_new_project_falls_back_to_ask(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    known_registry = tmp_path / "known-projects.json"
    claude_root, codex_root = _repo_roots()
    record_root_grant(root, registry=known_registry)  # nothing here yet

    new_project = root / "wip"
    _git_init(new_project)
    (new_project / "notes.md").write_text("mid-edit, not committed yet")

    report = workspace_status(
        new_project,
        personal_registry=tmp_path / "personal.json",
        known_projects_registry=known_registry,
        configured_roots=[root],
        claude_root=claude_root,
        codex_root=codex_root,
    )

    # Nothing collides by filename, so `can_apply_now` alone would pass --
    # but the working tree already has unsaved content, so this still
    # falls back to being asked rather than being set up silently.
    assert report["setup_policy"] == "ask"


def test_known_projects_snapshot_survives_a_fresh_read_from_disk(tmp_path):
    root = tmp_path / "Projects"
    existing = root / "already-here"
    _git_init(existing)
    known_registry = tmp_path / "known-projects.json"

    record_root_grant(root, registry=known_registry)

    # A brand-new read from disk, as if the process had restarted: nothing
    # about this snapshot lives only in memory.
    reloaded = read_known_projects_registry(known_registry)
    assert reloaded["roots"][str(root.resolve())] == [str(existing.resolve())]


def test_forgetting_a_root_clears_its_known_projects_snapshot(tmp_path):
    root = tmp_path / "Projects"
    existing = root / "already-here"
    _git_init(existing)
    known_registry = tmp_path / "known-projects.json"

    record_root_grant(root, registry=known_registry)
    assert str(root.resolve()) in read_known_projects_registry(known_registry)["roots"]

    forget_root_grant(root, registry=known_registry)
    assert (
        str(root.resolve()) not in read_known_projects_registry(known_registry)["roots"]
    )


def test_approving_a_root_snapshots_its_existing_projects_as_known(
    monkeypatch, capsys, tmp_path
):
    selected = tmp_path / "Projects"
    existing = selected / "already-here"
    _git_init(existing)
    known_registry = tmp_path / "known-projects.json"
    monkeypatch.setattr(workspaces_command, "resolve_key", lambda _key: [])
    monkeypatch.setattr(workspaces_command, "add_to_list_config", lambda *_args: None)
    monkeypatch.setattr(
        core_workspaces, "default_known_projects_registry", lambda: known_registry
    )

    workspaces_command.approve_root(path=str(selected), apply=True, output_json=True)
    capsys.readouterr()

    snapshot = read_known_projects_registry(known_registry)["roots"][
        str(selected.resolve())
    ]
    assert snapshot == [str(existing.resolve())]


def test_automatic_setup_is_recorded_and_fully_revertible(monkeypatch, tmp_path):
    project = tmp_path / "convoco"
    _git_init(project, "git@github.com:Example/Convoco.git")
    claude_root, codex_root = _repo_roots()
    automatic_registry = tmp_path / "automatic-setups.json"
    exclude_registry = tmp_path / "excluded-projects.json"
    monkeypatch.setattr(
        core_workspaces, "default_automatic_setups_registry", lambda: automatic_registry
    )
    _use_fixture_installers(monkeypatch)

    before = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        claude_root=claude_root,
        codex_root=codex_root,
    )
    before = {**before, "setup_policy": "automatic"}  # a genuinely new project's policy

    # `_apply_selected` is the exact function `configure --apply` uses; it
    # takes the same real activation path for an automatic setup as it does
    # for one the person explicitly asked for, and (per the module-level
    # `default_automatic_setups_registry` patch above) records it the same
    # way `configure --apply` would once the app calls it for a new project.
    error = workspaces_command._apply_selected(
        project, before, ["claude"], share_with_project=False, associate_personal=False
    )

    assert error is None
    assert (project / ".claude/commands/protocol.md").is_file()
    assert recently_set_up(registry=automatic_registry) == [
        {"name": "convoco", "detail": "Set your copilots up in convoco."}
    ]

    outcome = revert_project(
        project,
        exclude_registry=exclude_registry,
        automatic_setups_registry=automatic_registry,
    )

    assert outcome["removed"] == ["claude"]
    assert not (project / ".claude/commands/protocol.md").exists()
    assert is_project_excluded(project, registry=exclude_registry)
    assert recently_set_up(registry=automatic_registry) == []


def test_recently_set_up_populates_and_ages_out(tmp_path):
    registry = tmp_path / "automatic-setups.json"
    project = tmp_path / "convoco"
    _git_init(project)
    start = 1_700_000_000.0

    record_automatic_setup(project, name="Convoco", registry=registry, now=start)

    fresh = recently_set_up(registry=registry, now=start + 3600)
    assert fresh == [{"name": "Convoco", "detail": "Set your copilots up in Convoco."}]

    aged_out = recently_set_up(
        registry=registry, now=start + RECENTLY_SET_UP_WINDOW_HOURS * 3600 + 1
    )
    assert aged_out == []
