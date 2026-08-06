from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
from cc.core.ecosystem.project_locking import fingerprint_file_payload
from cc.core.ecosystem.project_reconciliation import assess_project, build_project_plans
from cc.core.ecosystem.reconciliation_recipes import (
    DEFAULT_RECIPE_REGISTRY,
    RecipeValidationError,
    build_recipe_plan,
)
from cc.core.ecosystem.reconciliation_transaction import execute_reconciliation
from cc.core.ecosystem.reconciliation_types import ComponentRoute

from cc.core.ecosystem import project_integration as integration
from cc.core.ecosystem import project_reconciliation as reconciliation
from cc.core.ecosystem import reconciliation_recipes as recipes


def _git(project: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", *arguments),
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _project(tmp_path: Path, name: str) -> Path:
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


def _framework_sources(tmp_path: Path) -> tuple[Path, Path]:
    claude = tmp_path / "claude-source"
    codex = tmp_path / "codex-source"
    _write(
        claude / "VERSION.json",
        json.dumps(
            {
                "framework": "5.13.3",
                "components": {"agents": {"frameworkAgents": ["me"]}},
            }
        ),
    )
    _write(claude / ".claude/commands/protocol.md", "protocol\n")
    _write(claude / ".claude/commands/continue.md", "continue\n")
    _write(claude / ".claude/fitness-check.sh", "#!/bin/sh\nexit 0\n", 0o755)
    _write(claude / ".claude/agents/me.md", "me\n")
    _write(claude / ".claude/agents/kc.md", "kc\n")

    _write(
        codex / "plugins/codex-copilot/.codex-plugin/plugin.json",
        json.dumps({"name": "codex-copilot", "version": "0.6.1"}),
    )
    _write(codex / "plugins/codex-copilot/skills/me/SKILL.md", "skill\n")
    _write(codex / "scripts/copilot-gate.sh", "#!/bin/sh\nexit 0\n", 0o755)
    return claude, codex


def _configure_sources(
    monkeypatch: pytest.MonkeyPatch, claude: Path, codex: Path
) -> None:
    def resolve(key: str) -> str | None:
        return {
            "paths.claude_copilot_root": str(claude),
            "paths.codex_copilot_root": str(codex),
        }.get(key)

    monkeypatch.setattr(integration, "resolve_key", resolve)
    monkeypatch.setattr(reconciliation, "resolve_key", resolve)
    monkeypatch.setattr(recipes, "resolve_key", resolve)
    monkeypatch.setattr(reconciliation, "is_project_excluded", lambda path: False)


def _source_files(source: Path, component: str) -> dict[str, Path]:
    if component == "claude":
        return {
            relative: source / relative
            for relative in (
                ".claude/commands/protocol.md",
                ".claude/commands/continue.md",
                ".claude/fitness-check.sh",
                ".claude/agents/me.md",
                ".claude/agents/kc.md",
            )
        }
    plugin = source / "plugins/codex-copilot"
    files = {
        path.relative_to(source).as_posix(): path
        for path in sorted(plugin.rglob("*"))
        if path.is_file()
    }
    files["scripts/copilot-gate.sh"] = source / "scripts/copilot-gate.sh"
    return files


def _checksum(path: Path) -> str:
    payload = (
        ("symlink:" + str(path.readlink())).encode()
        if path.is_symlink()
        else path.read_bytes()
    )
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _lock_entry(
    project: Path,
    source: Path,
    component: str,
    *,
    omit: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    version = "5.13.3" if component == "claude" else "0.6.1"
    return {
        "component": component,
        "version": version,
        "release_tag": f"v{version}",
        "files": [
            {
                "path": relative,
                "ownership": "framework",
                "checksum": _checksum(project / relative),
            }
            for relative in _source_files(source, component)
            if relative not in omit
        ],
    }


def _write_lock(project: Path, entries: list[dict[str, Any]]) -> None:
    _write(
        project / "copilot.lock.json",
        json.dumps({"schema_version": "1.0", "components": entries}, indent=2) + "\n",
    )


def _install_current(
    project: Path,
    claude_source: Path,
    codex_source: Path,
    components: tuple[str, ...],
    *,
    claude_lock_omit: frozenset[str] = frozenset(),
) -> None:
    entries: list[dict[str, Any]] = []
    if "claude" in components:
        for relative, source in _source_files(claude_source, "claude").items():
            target = project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        _write(project / "CLAUDE.md", "# Project\n\n## Claude Copilot\n")
        _write(project / ".mcp.json", '{"mcpServers": {}}\n')
        entries.append(
            _lock_entry(
                project,
                claude_source,
                "claude",
                omit=claude_lock_omit,
            )
        )
    if "codex" in components:
        shutil.copytree(
            codex_source / "plugins/codex-copilot",
            project / "plugins/codex-copilot",
        )
        gate = project / "scripts/copilot-gate.sh"
        gate.parent.mkdir(parents=True)
        shutil.copy2(codex_source / "scripts/copilot-gate.sh", gate)
        _write(
            project / "AGENTS.md",
            "# Project\n\n## Codex Copilot\n\nUse ./plugins/codex-copilot.\n",
        )
        _write(
            project / ".codex-copilot.json",
            json.dumps(
                {
                    "installType": "copy",
                    "pluginPath": "./plugins/codex-copilot",
                }
            )
            + "\n",
        )
        bridge = project / ".claude/skills/codex-copilot"
        bridge.parent.mkdir(parents=True, exist_ok=True)
        bridge.symlink_to("../../plugins/codex-copilot/skills")
        entries.append(_lock_entry(project, codex_source, "codex"))
    _write_lock(project, entries)


def _install_legacy_codex(project: Path, codex_source: Path) -> None:
    plugin = project / "plugins/codex-copilot"
    plugin.parent.mkdir(parents=True, exist_ok=True)
    plugin.symlink_to(codex_source / "plugins/codex-copilot")
    bridge = project / ".claude/skills/codex-copilot"
    bridge.parent.mkdir(parents=True, exist_ok=True)
    bridge.symlink_to(codex_source / "plugins/codex-copilot/skills")
    _write(
        project / "AGENTS.md",
        "# Project\n\n## Codex Copilot\n\nUse ./plugins/codex-copilot.\n",
    )
    _write(
        project / ".codex-copilot.json",
        json.dumps(
            {
                "installType": "symlink",
                "pluginPath": "./plugins/codex-copilot",
            }
        )
        + "\n",
    )


def _commit(project: Path) -> None:
    _git(project, "add", "-A")
    _git(project, "commit", "-qm", "fixture")


def _tree_manifest(project: Path) -> tuple[tuple[Any, ...], ...]:
    rows: list[tuple[Any, ...]] = []
    for directory, names, files in os.walk(project, followlinks=False):
        root = Path(directory)
        if root == project:
            names[:] = [name for name in names if name != ".git"]
        for name in sorted((*names, *files)):
            path = root / name
            relative = path.relative_to(project).as_posix()
            metadata = path.lstat()
            mode = stat.S_IMODE(metadata.st_mode)
            if stat.S_ISLNK(metadata.st_mode):
                rows.append((relative, "symlink", mode, str(path.readlink())))
            elif stat.S_ISDIR(metadata.st_mode):
                rows.append((relative, "directory", mode))
            elif stat.S_ISREG(metadata.st_mode):
                rows.append(
                    (
                        relative,
                        "file",
                        mode,
                        hashlib.sha256(path.read_bytes()).hexdigest(),
                    )
                )
            else:
                rows.append((relative, "special", mode))
    return tuple(sorted(rows))


def _component(assessment: dict[str, Any], name: str) -> dict[str, Any]:
    return next(
        component
        for component in assessment["components"]
        if component["component"] == name
    )


def _build_artifact_case(
    case: str,
    project: Path,
    tmp_path: Path,
    claude_source: Path,
    codex_source: Path,
) -> None:
    if case == "claude-entry":
        _write(project / "CLAUDE.md", "# Project-owned Claude routing\n")
    elif case == "codex-entry":
        _write(project / "AGENTS.md", "# Project-owned Codex routing\n")
    elif case == "mcp-config":
        _write(
            project / ".mcp.json",
            json.dumps({"mcpServers": {"project-tool": {"command": "project-tool"}}}),
        )
    elif case == "skill-bridge":
        outside = tmp_path / "outside-skills"
        outside.mkdir()
        bridge = project / ".claude/skills/codex-copilot"
        bridge.parent.mkdir(parents=True)
        bridge.symlink_to(outside)
    elif case == "plugin":
        _install_current(project, claude_source, codex_source, ("codex",))
        (project / "copilot.lock.json").unlink()
        _write(project / "plugins/codex-copilot/project-owned.md", "custom plugin\n")
    elif case == "gate":
        _install_current(project, claude_source, codex_source, ("codex",))
        (project / "copilot.lock.json").unlink()
        _write(project / "scripts/copilot-gate.sh", "#!/bin/sh\nexit 42\n", 0o755)
    elif case == "config":
        _install_current(project, claude_source, codex_source, ("codex",))
        (project / "copilot.lock.json").unlink()
        _write(
            project / ".codex-copilot.json",
            json.dumps(
                {
                    "installType": "custom",
                    "pluginPath": "./custom-plugin",
                    "projectSetting": "preserve-me",
                }
            ),
        )
    elif case == "config-unreadable":
        _install_current(project, claude_source, codex_source, ("codex",))
        (project / "copilot.lock.json").unlink()
        _write(project / ".codex-copilot.json", "{not-json\n")
    elif case == "lock-evidence":
        _install_current(project, claude_source, codex_source, ("claude",))
        _write(project / ".claude/commands/protocol.md", "changed after lock\n")
    elif case == "owner-policy":
        _write(project / "CLAUDE.md", "# Project-owned Claude routing\n")
        _write(
            project / ".copilot/project-owner.json",
            json.dumps({"decision_required": True, "owner": "project-owner"}),
        )
    else:
        raise AssertionError(f"unknown artifact fixture: {case}")


@pytest.mark.parametrize(
    ("case", "component_name", "expected_state", "expected_actor", "recipe_id"),
    [
        (
            "claude-entry",
            "claude",
            "customized-guided-route",
            "project-author",
            "claude.customized-preserve-entry.v1",
        ),
        (
            "codex-entry",
            "codex",
            "customized-guided-route",
            "project-author",
            "codex.customized-preserve-entry.v1",
        ),
        (
            "mcp-config",
            "claude",
            "customized-guided-route",
            "project-author",
            "claude.customized-preserve-entry.v1",
        ),
        ("skill-bridge", "codex", "could-not-verify", "person", None),
        (
            "plugin",
            "codex",
            "owner-decision",
            "project-owner",
            None,
        ),
        (
            "gate",
            "codex",
            "owner-decision",
            "project-owner",
            None,
        ),
        (
            "config",
            "codex",
            "customized-guided-route",
            "project-author",
            "codex.customized-merge-config.v1",
        ),
        (
            "config-unreadable",
            "codex",
            "owner-decision",
            "project-owner",
            None,
        ),
        ("lock-evidence", "claude", "could-not-verify", "person", None),
        ("owner-policy", "claude", "owner-decision", "project-owner", None),
    ],
)
def test_artifact_family_routes_and_plans_are_authoritative_and_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    component_name: str,
    expected_state: str,
    expected_actor: str,
    recipe_id: str | None,
) -> None:
    claude_source, codex_source = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude_source, codex_source)
    project = _project(tmp_path, f"artifact-{case}")
    _build_artifact_case(case, project, tmp_path, claude_source, codex_source)
    _commit(project)
    before = _tree_manifest(project)

    report = integration.inspect_project_integration(project, detail=True)
    selection = {str(project): (component_name,)}
    assessment = assess_project(
        project,
        approved_root=tmp_path,
        selected_components=(component_name,),
    )
    component = _component(assessment, component_name)
    inspected_component = next(
        item for item in report["components"] if item["component"] == component_name
    )
    expected_inspection = {
        "claude-entry": (
            "guided-integration",
            ("compatible-claude-entry", "valid-mcp-marker"),
        ),
        "codex-entry": (
            "guided-integration",
            (
                "compatible-codex-entry",
                "valid-codex-config",
                "valid-plugin-manifest",
                "internal-skill-link",
            ),
        ),
        "mcp-config": ("guided-integration", ("compatible-claude-entry",)),
        "skill-bridge": (
            "could-not-verify",
            (
                "compatible-codex-entry",
                "valid-codex-config",
                "valid-plugin-manifest",
                "internal-skill-link",
            ),
        ),
        "plugin": (
            "guided-integration",
            ("project-owned-component-content",),
        ),
        "gate": (
            "guided-integration",
            ("project-owned-component-content",),
        ),
        "config": ("guided-integration", ("valid-codex-config",)),
        "config-unreadable": ("could-not-verify", ("valid-codex-config",)),
        "lock-evidence": ("could-not-verify", ("verified-framework-file",)),
        "owner-policy": ("owner-decision", ("owner-direction",)),
    }[case]
    expected_preserved_path = {
        "claude-entry": "CLAUDE.md",
        "codex-entry": "AGENTS.md",
        "mcp-config": ".mcp.json",
        "skill-bridge": ".claude/skills",
        "plugin": "plugins",
        "gate": "scripts/copilot-gate.sh",
        "config": ".codex-copilot.json",
        "config-unreadable": ".codex-copilot.json",
        "lock-evidence": "copilot.lock.json",
        "owner-policy": ".copilot/project-owner.json",
    }[case]

    assert inspected_component["classification"] == expected_inspection[0]
    assert inspected_component["recognized_setup"] is None
    assert (
        tuple(item["id"] for item in inspected_component["missing_requirements"])
        == expected_inspection[1]
    )
    assert component["state"] == expected_state
    assert component["responsible_actor"] == expected_actor
    assert component["selected"] is True
    assert assessment["route"] == expected_state
    assert assessment["blockers"]
    assert expected_preserved_path in {
        item["path"] for item in assessment["dossier"]["preservation"]
    }
    if recipe_id is None:
        assert component["recipe_options"] == []
        explicit = None
    else:
        assert component["recommended"] is True
        assert component["recipe_options"] == [
            {
                "recipe_id": recipe_id,
                "component": component_name,
                "summary": DEFAULT_RECIPE_REGISTRY.require(
                    recipe_id,
                    component=component_name,
                    route=ComponentRoute(expected_state),
                    root=project,
                    assessment=component,
                    dossier=assessment["dossier"],
                ).summary,
            }
        ]
        explicit = {str(project): {component_name: recipe_id}}

    public, internal = build_project_plans([assessment], selection, explicit)

    assert public[0]["recipes"] == [
        {"component": component_name, "recipe_id": recipe_id}
        if recipe_id is not None
        else {
            "component": component_name,
            "recipe_id": f"{component_name}-{expected_state}-receipt-v1",
        }
    ]
    assert internal[0].path == str(project)
    if recipe_id is None:
        assert public[0]["sources"] == []
        assert internal[0].operations == ()
    else:
        assert [source["component"] for source in public[0]["sources"]] == [
            component_name
        ]
        assert internal[0].operations
        assert {operation.component for operation in internal[0].operations} == {
            component_name
        }
    assert _tree_manifest(project) == before
    assert _git(project, "status", "--porcelain=v1") == ""


def _build_recognized_family(
    family: str,
    project: Path,
    claude_source: Path,
    codex_source: Path,
) -> None:
    if family == "current-claude-only":
        _install_current(project, claude_source, codex_source, ("claude",))
    elif family == "current-codex-only":
        _install_current(project, claude_source, codex_source, ("codex",))
    elif family == "current-both":
        _install_current(project, claude_source, codex_source, ("claude", "codex"))
    elif family == "legacy-claude-entry-only":
        _install_current(project, claude_source, codex_source, ("claude",))
        _write(project / "CLAUDE.md", "# Earlier Claude integration\n")
    elif family == "legacy-claude-lock-only":
        _install_current(
            project,
            claude_source,
            codex_source,
            ("claude",),
            claude_lock_omit=frozenset({".claude/fitness-check.sh"}),
        )
    elif family == "legacy-codex-only":
        _install_legacy_codex(project, codex_source)
    elif family == "legacy-both":
        _install_current(project, claude_source, codex_source, ("claude",))
        _write(project / "CLAUDE.md", "# Earlier Claude integration\n")
        _install_legacy_codex(project, codex_source)
    elif family == "mixed-ready-custom":
        _install_current(project, claude_source, codex_source, ("claude",))
        _write(project / "AGENTS.md", "# Project-owned Codex routing\n")
    else:
        raise AssertionError(f"unknown recognized family: {family}")


@pytest.mark.parametrize(
    ("family", "presence", "route", "states", "variants"),
    [
        (
            "current-claude-only",
            "claude-only",
            "ready",
            {"claude": "ready", "codex": "not-present"},
            {"claude": "claude-tracked-lock-v1"},
        ),
        (
            "current-codex-only",
            "codex-only",
            "ready",
            {"claude": "not-present", "codex": "ready"},
            {"codex": "codex-tracked-lock-v1"},
        ),
        (
            "current-both",
            "both",
            "ready",
            {"claude": "ready", "codex": "ready"},
            {
                "claude": "claude-tracked-lock-v1",
                "codex": "codex-tracked-lock-v1",
            },
        ),
        (
            "legacy-claude-entry-only",
            "claude-only",
            "safe-update-available",
            {"claude": "safe-update-available", "codex": "not-present"},
            {"claude": "claude-legacy-entry-v1"},
        ),
        (
            "legacy-claude-lock-only",
            "claude-only",
            "safe-update-available",
            {"claude": "safe-update-available", "codex": "not-present"},
            {"claude": "claude-legacy-lock-v1"},
        ),
        (
            "legacy-codex-only",
            "codex-only",
            "safe-update-available",
            {"claude": "not-present", "codex": "safe-update-available"},
            {"codex": "codex-legacy-linked-v1"},
        ),
        (
            "legacy-both",
            "both",
            "safe-update-available",
            {
                "claude": "safe-update-available",
                "codex": "safe-update-available",
            },
            {
                "claude": "claude-legacy-entry-v1",
                "codex": "codex-legacy-linked-v1",
            },
        ),
        (
            "mixed-ready-custom",
            "both",
            "customized-guided-route",
            {"claude": "ready", "codex": "customized-guided-route"},
            {"claude": "claude-tracked-lock-v1"},
        ),
    ],
)
def test_current_legacy_and_mixed_families_use_real_project_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    presence: str,
    route: str,
    states: dict[str, str],
    variants: dict[str, str],
) -> None:
    claude_source, codex_source = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude_source, codex_source)
    project = _project(tmp_path, family)
    _build_recognized_family(family, project, claude_source, codex_source)
    _commit(project)
    before = _tree_manifest(project)

    assessment = assess_project(project, approved_root=tmp_path)
    report = integration.inspect_project_integration(project, detail=True)

    assert assessment["presence"] == presence
    assert assessment["route"] == route
    assert {
        component["component"]: component["state"]
        for component in assessment["components"]
    } == states
    observed_variants = {
        component["component"]: next(
            (
                item["state"]
                for item in component["evidence"]
                if item["id"] == "recognized-setup"
            ),
            None,
        )
        for component in assessment["components"]
    }
    assert {name: observed_variants[name] for name in variants} == variants
    expected_missing = {
        "current-claude-only": {"claude": (), "codex": ("component-setup",)},
        "current-codex-only": {"claude": ("component-setup",), "codex": ()},
        "current-both": {"claude": (), "codex": ()},
        "legacy-claude-entry-only": {
            "claude": ("compatible-claude-entry",),
            "codex": ("component-setup",),
        },
        "legacy-claude-lock-only": {
            "claude": ("required-lock-path",),
            "codex": ("component-setup",),
        },
        "legacy-codex-only": {
            "claude": ("component-setup",),
            "codex": ("valid-codex-config", "internal-skill-link", "lock-record"),
        },
        "legacy-both": {
            "claude": ("compatible-claude-entry",),
            "codex": ("valid-codex-config", "internal-skill-link", "lock-record"),
        },
        "mixed-ready-custom": {
            "claude": (),
            "codex": (
                "compatible-codex-entry",
                "valid-codex-config",
                "valid-plugin-manifest",
                "internal-skill-link",
            ),
        },
    }[family]
    assert {
        item["component"]: tuple(
            requirement["id"] for requirement in item["missing_requirements"]
        )
        for item in report["components"]
    } == expected_missing
    assert _tree_manifest(project) == before
    assert _git(project, "status", "--porcelain=v1") == ""


@pytest.mark.parametrize(
    ("case", "component_name", "recipe_id", "managed_path"),
    [
        (
            "claude-entry",
            "claude",
            "claude.customized-preserve-entry.v1",
            "CLAUDE.md",
        ),
        (
            "config",
            "codex",
            "codex.customized-merge-config.v1",
            ".codex-copilot.json",
        ),
        (
            "codex-entry",
            "codex",
            "codex.customized-preserve-entry.v1",
            "AGENTS.md",
        ),
    ],
)
def test_custom_family_apply_verifies_and_repeats_without_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    component_name: str,
    recipe_id: str,
    managed_path: str,
) -> None:
    claude_source, codex_source = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude_source, codex_source)
    project = _project(tmp_path, f"apply-{case}")
    _build_artifact_case(case, project, tmp_path, claude_source, codex_source)
    _write(
        project / "copilot.project.json",
        json.dumps(
            {
                "schema_version": "1.0",
                "components": [component_name],
                "projectOwnedSetting": "preserve-me",
            }
        ),
    )
    _commit(project)

    assessment = assess_project(
        project,
        approved_root=tmp_path,
        selected_components=(component_name,),
    )
    _, plans = build_project_plans(
        [assessment],
        {str(project): (component_name,)},
        {str(project): {component_name: recipe_id}},
    )
    receipts = execute_reconciliation(
        [plans[0].transaction_plan()],
        run_id="run_" + ("a" if component_name == "claude" else "b") * 32,
        root=tmp_path / "transaction-state",
    )

    assert receipts[0]["status"] == "applied"
    verified = integration.inspect_project_integration(project, detail=True)
    assert (
        next(
            item["classification"]
            for item in verified["components"]
            if item["component"] == component_name
        )
        == "ready"
    )
    declaration = json.loads(
        (project / "copilot.project.json").read_text(encoding="utf-8")
    )
    assert declaration["projectOwnedSetting"] == "preserve-me"
    if case == "claude-entry":
        assert "# Project-owned Claude routing" in (project / "CLAUDE.md").read_text(
            encoding="utf-8"
        )
    elif case == "codex-entry":
        assert "# Project-owned Codex routing" in (project / "AGENTS.md").read_text(
            encoding="utf-8"
        )
    else:
        config = json.loads(
            (project / ".codex-copilot.json").read_text(encoding="utf-8")
        )
        assert config["projectSetting"] == "preserve-me"
        assert config["installType"] == "copy"

    lock = json.loads((project / "copilot.lock.json").read_text(encoding="utf-8"))
    entry = next(
        item for item in lock["components"] if item["component"] == component_name
    )
    managed = {item["path"]: item for item in entry["managed_outputs"]}
    assert managed_path in managed
    assert "copilot.project.json" in managed

    repeat = assess_project(
        project,
        approved_root=tmp_path,
        selected_components=(component_name,),
    )
    assert repeat["route"] == "ready"
    assert _component(repeat, component_name)["state"] == "ready"
    public, repeat_plans = build_project_plans(
        [repeat], {str(project): (component_name,)}
    )
    assert public[0]["operations"] == []
    assert repeat_plans[0].operations == ()
    assert _git(project, "status", "--porcelain=v1")


def test_claude_setup_records_every_file_copied_from_agent_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude_source, codex_source = _framework_sources(tmp_path)
    _write(claude_source / ".claude/agents/manifest.json", '{"agents": []}\n')
    _write(claude_source / ".claude/agents/_archive/retired.md", "retired\n")
    _configure_sources(monkeypatch, claude_source, codex_source)
    project = _project(tmp_path, "claude-full-agent-tree")
    _git(project, "commit", "--allow-empty", "-qm", "fixture")

    assessment = assess_project(
        project,
        approved_root=tmp_path,
        selected_components=("claude",),
    )
    _, plans = build_project_plans([assessment], {str(project): ("claude",)})
    receipts = execute_reconciliation(
        [plans[0].transaction_plan()],
        run_id="run_" + "c" * 32,
        root=tmp_path / "transaction-state",
    )

    assert receipts[0]["status"] == "applied"
    lock = json.loads((project / "copilot.lock.json").read_text(encoding="utf-8"))
    files = {item["path"] for item in lock["components"][0]["files"]}
    assert ".claude/agents/manifest.json" in files
    assert ".claude/agents/_archive/retired.md" in files

    repeat = assess_project(
        project,
        approved_root=tmp_path,
        selected_components=("claude",),
    )
    assert repeat["route"] == "ready"
    assert _component(repeat, "claude")["state"] == "ready"
    public, repeat_plans = build_project_plans([repeat], {str(project): ("claude",)})
    assert public[0]["operations"] == []
    assert repeat_plans[0].operations == ()
    assert _git(project, "status", "--porcelain=v1")


def test_stale_custom_recipe_ids_are_rejected_against_current_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude_source, codex_source = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude_source, codex_source)

    config_project = _project(tmp_path, "stale-config")
    _build_artifact_case(
        "config", config_project, tmp_path, claude_source, codex_source
    )
    _commit(config_project)
    config_assessment = assess_project(
        config_project,
        approved_root=tmp_path,
        selected_components=("codex",),
    )
    _write(config_project / ".codex-copilot.json", '["now-not-an-object"]\n')
    with pytest.raises(RecipeValidationError, match="no longer applies"):
        build_recipe_plan(
            config_assessment,
            ("codex",),
            explicit_recipe_ids={"codex": "codex.customized-merge-config.v1"},
        )

    entry_project = _project(tmp_path, "stale-entry")
    _build_artifact_case(
        "codex-entry", entry_project, tmp_path, claude_source, codex_source
    )
    _commit(entry_project)
    entry_assessment = assess_project(
        entry_project,
        approved_root=tmp_path,
        selected_components=("codex",),
    )
    _write(entry_project / "plugins/codex-copilot/project-owned.md", "owner\n")
    with pytest.raises(RecipeValidationError, match="no longer applies"):
        build_recipe_plan(
            entry_assessment,
            ("codex",),
            explicit_recipe_ids={"codex": "codex.customized-preserve-entry.v1"},
        )


def test_ready_project_with_unrelated_dirty_path_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude_source, codex_source = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude_source, codex_source)
    project = _project(tmp_path, "unrelated-dirty")
    _install_current(project, claude_source, codex_source, ("claude",))
    _commit(project)
    _write(project / "notes/private.txt", "unrelated\n")

    assessment = assess_project(
        project, approved_root=tmp_path, selected_components=("claude",)
    )
    assert assessment["route"] == "held"
    assert _component(assessment, "claude")["state"] == "held"
    _, plans = build_project_plans([assessment], {str(project): ("claude",)})
    assert plans[0].operations == ()


def test_modified_managed_entry_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude_source, codex_source = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude_source, codex_source)
    project = _project(tmp_path, "modified-managed-entry")
    _install_current(project, claude_source, codex_source, ("claude",))
    lock_path = project / "copilot.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    entry = lock["components"][0]
    claude_entry = project / "CLAUDE.md"
    entry["managed_outputs"] = [
        {
            "path": "CLAUDE.md",
            "kind": "managed-text",
            "fingerprint": fingerprint_file_payload(
                claude_entry.read_bytes(),
                mode=stat.S_IMODE(claude_entry.stat().st_mode),
            ),
        }
    ]
    _write(lock_path, json.dumps(lock, indent=2) + "\n")
    _commit(project)
    _write(project / "CLAUDE.md", "# changed after managed evidence\n")

    assessment = assess_project(
        project, approved_root=tmp_path, selected_components=("claude",)
    )
    assert assessment["route"] == "held"
    assert _component(assessment, "claude")["recipe_options"] == []


def test_ready_project_with_renamed_unrelated_path_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude_source, codex_source = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude_source, codex_source)
    project = _project(tmp_path, "renamed-dirty")
    _install_current(project, claude_source, codex_source, ("claude",))
    _write(project / "notes.txt", "owner notes\n")
    _commit(project)
    _git(project, "mv", "notes.txt", "renamed-notes.txt")

    assessment = assess_project(
        project, approved_root=tmp_path, selected_components=("claude",)
    )
    assert assessment["route"] == "held"
    assert _component(assessment, "claude")["state"] == "held"


def test_detached_ready_project_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude_source, codex_source = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude_source, codex_source)
    project = _project(tmp_path, "detached-ready")
    _install_current(project, claude_source, codex_source, ("claude",))
    _commit(project)
    _git(project, "checkout", "--detach", "-q")

    assessment = assess_project(
        project, approved_root=tmp_path, selected_components=("claude",)
    )
    assert assessment["route"] == "held"
    assert any(blocker["code"] == "detached-head" for blocker in assessment["blockers"])


@pytest.mark.parametrize(
    "payload",
    [
        b"M  missing-terminator",
        b"R  new.txt\0",
        b"ZZ invalid.txt\0",
        b"?? same\0?? same\0",
    ],
)
def test_porcelain_parser_fails_closed_on_malformed_status(payload: bytes) -> None:
    with pytest.raises(Exception):
        reconciliation._parse_porcelain_status(payload)


def test_porcelain_parser_records_both_rename_and_copy_paths() -> None:
    assert reconciliation._parse_porcelain_status(
        b"R  renamed.txt\0original.txt\0C  copied.txt\0source.txt\0"
    ) == ("renamed.txt", "original.txt", "copied.txt", "source.txt")


def test_unparseable_git_status_holds_a_ready_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude_source, codex_source = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude_source, codex_source)
    project = _project(tmp_path, "malformed-status")
    _install_current(project, claude_source, codex_source, ("claude",))
    _commit(project)
    original_run = subprocess.run

    def malformed_status(arguments: Any, *args: Any, **kwargs: Any) -> Any:
        if tuple(arguments[:2]) == ("git", "status"):
            return subprocess.CompletedProcess(
                arguments, 0, stdout=b"bad\0", stderr=b""
            )
        return original_run(arguments, *args, **kwargs)

    monkeypatch.setattr(reconciliation.subprocess, "run", malformed_status)
    assessment = assess_project(
        project, approved_root=tmp_path, selected_components=("claude",)
    )
    assert assessment["route"] == "held"
    assert _component(assessment, "claude")["state"] == "held"


def test_forged_managed_output_cannot_authorize_unrelated_dirt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude_source, codex_source = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude_source, codex_source)
    project = _project(tmp_path, "forged-managed-output")
    _install_current(project, claude_source, codex_source, ("claude",))
    _commit(project)
    secret = project / "secret.txt"
    _write(secret, "project secret\n")
    lock_path = project / "copilot.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["components"][0]["managed_outputs"] = [
        {
            "path": "secret.txt",
            "kind": "managed-text",
            "fingerprint": fingerprint_file_payload(secret.read_bytes(), mode=0o644),
        }
    ]
    _write(lock_path, json.dumps(lock, indent=2) + "\n")

    assessment = assess_project(
        project, approved_root=tmp_path, selected_components=("claude",)
    )
    assert assessment["route"] == "held"
    assert _component(assessment, "claude")["recipe_options"] == []


def test_lock_framework_path_with_symlink_ancestor_is_never_repeat_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude_source, codex_source = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude_source, codex_source)
    project = _project(tmp_path, "symlink-ancestor")
    _install_current(project, claude_source, codex_source, ("claude",))
    _commit(project)
    outside = tmp_path / "outside"
    _write(outside / "secret.txt", "outside\n")
    (project / "linked").symlink_to(outside, target_is_directory=True)
    lock_path = project / "copilot.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["components"][0]["files"].append(
        {
            "path": "linked/secret.txt",
            "ownership": "framework",
            "checksum": _checksum(outside / "secret.txt"),
        }
    )
    _write(lock_path, json.dumps(lock, indent=2) + "\n")

    assessment = assess_project(
        project, approved_root=tmp_path, selected_components=("claude",)
    )
    assert assessment["route"] == "held"
    assert _component(assessment, "claude")["recipe_options"] == []


def test_symlinked_project_lock_is_never_repeat_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude_source, codex_source = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude_source, codex_source)
    project = _project(tmp_path, "symlinked-lock")
    _install_current(project, claude_source, codex_source, ("claude",))
    _commit(project)
    lock_path = project / "copilot.lock.json"
    outside_lock = tmp_path / "outside-lock.json"
    shutil.copy2(lock_path, outside_lock)
    lock_path.unlink()
    lock_path.symlink_to(outside_lock)

    assessment = assess_project(
        project, approved_root=tmp_path, selected_components=("claude",)
    )
    assert assessment["route"] == "held"
    assert _component(assessment, "claude")["recipe_options"] == []


def test_forged_reversed_declaration_order_is_held_even_with_matching_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude_source, codex_source = _framework_sources(tmp_path)
    _configure_sources(monkeypatch, claude_source, codex_source)
    project = _project(tmp_path, "reversed-declaration")
    _install_current(project, claude_source, codex_source, ("claude", "codex"))
    declaration_path = project / "copilot.project.json"
    _write(
        declaration_path,
        json.dumps(
            {"schema_version": "1.0", "components": ["claude", "codex"]},
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    lock_path = project / "copilot.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["components"][0]["managed_outputs"] = [
        {
            "path": "copilot.project.json",
            "kind": "merged-json",
            "fingerprint": fingerprint_file_payload(
                declaration_path.read_bytes(),
                mode=stat.S_IMODE(declaration_path.stat().st_mode),
            ),
        }
    ]
    _write(lock_path, json.dumps(lock, indent=2) + "\n")
    _commit(project)

    _write(
        declaration_path,
        json.dumps(
            {"schema_version": "1.0", "components": ["codex", "claude"]},
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    managed = lock["components"][0]["managed_outputs"][0]
    managed["fingerprint"] = fingerprint_file_payload(
        declaration_path.read_bytes(),
        mode=stat.S_IMODE(declaration_path.stat().st_mode),
    )
    _write(lock_path, json.dumps(lock, indent=2) + "\n")

    assessment = assess_project(
        project,
        approved_root=tmp_path,
        selected_components=("claude", "codex"),
    )
    assert assessment["route"] == "held"
