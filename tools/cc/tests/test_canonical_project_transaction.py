from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from cc.core.ecosystem import (
    codex_plugin_source,
    entitlement,
    policy,
    project_integration,
    project_reconciliation,
)
from cc.core.ecosystem import reconciliation_recipes as recipes
from cc.core.ecosystem import (
    reconciliation_transaction as transaction_module,
)
from cc.core.ecosystem.canonical_transaction import (
    build_canonical_project_request,
    canonical_project_request_json,
    inspect_canonical_prerequisites,
)
from cc.core.ecosystem.project_plan_store import issue_plan
from cc.core.ecosystem.project_reconciliation import assess_project
from cc.core.ecosystem.reconciliation import (
    ReconciliationError,
    build_apply_report,
    build_plan_report,
    build_verify_report,
    prepare_reconciliation,
)
from cc.core.ecosystem.reconciliation_recipes import build_recipe_plan
from cc.core.ecosystem.reconciliation_transaction import execute_reconciliation
from cc.core.ecosystem.reconciliation_types import RequestValidationError


def _git_project(root: Path, name: str = "project") -> Path:
    project = root / name
    project.mkdir(parents=True)
    subprocess.run(("git", "init", "-q"), cwd=project, check=True)
    subprocess.run(
        ("git", "config", "user.email", "fixture@example.invalid"),
        cwd=project,
        check=True,
    )
    subprocess.run(("git", "config", "user.name", "Fixture"), cwd=project, check=True)
    return project.resolve()


def _write(path: Path, content: str, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)


def _reference_sources(tmp_path: Path) -> tuple[Path, Path, tuple[str, ...]]:
    commands = (
        "protocol.md",
        "continue.md",
        "pause.md",
        "map.md",
        "memory.md",
        "extensions.md",
        "orchestrate.md",
    )
    claude = tmp_path / "claude-source"
    _write(
        claude / "VERSION.json",
        json.dumps(
            {
                "framework": "5.13.3",
                "components": {
                    "commands": {"projectCommands": list(commands)},
                    "agents": {"frameworkAgents": ["me", "qa"]},
                },
            }
        ),
    )
    for command in commands:
        _write(claude / ".claude/commands" / command, f"{command}\n")
    for agent in ("me", "qa", "kc"):
        _write(claude / ".claude/agents" / f"{agent}.md", f"{agent}\n")
    _write(claude / ".claude/fitness-check.sh", "#!/bin/sh\nexit 0\n", mode=0o755)
    _write(
        claude / ".claude/hooks/copilot-hook.sh",
        "#!/bin/sh\nexit 0\n",
        mode=0o755,
    )

    codex = tmp_path / "codex-source"
    _write(
        codex / "plugins/codex-copilot/.codex-plugin/plugin.json",
        json.dumps({"name": "codex-copilot", "version": "0.6.1"}),
    )
    _write(codex / "plugins/codex-copilot/skills/me/SKILL.md", "skill\n")
    _write(codex / "scripts/copilot-gate.sh", "#!/bin/sh\nexit 0\n", mode=0o755)
    return claude, codex, commands


def _signed_codex_ladder(tmp_path: Path) -> tuple[Path, Path, str, str]:
    unsigned = tmp_path / "unsigned-personal"
    _write(unsigned / "plugins/codex-copilot/SKILL.md", "unsigned\n")

    signed = tmp_path / "signed-organization"
    signed.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=signed, check=True)
    subprocess.run(
        ("git", "config", "user.email", "enac-foundation"), cwd=signed, check=True
    )
    subprocess.run(
        ("git", "config", "user.name", "Fixture Signer"), cwd=signed, check=True
    )
    key = tmp_path / "signing-key"
    subprocess.run(
        ("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)), check=True
    )
    subprocess.run(("git", "config", "gpg.format", "ssh"), cwd=signed, check=True)
    subprocess.run(
        ("git", "config", "user.signingkey", str(key)), cwd=signed, check=True
    )
    _write(
        signed / "plugins/codex-copilot/.codex-plugin/plugin.json",
        json.dumps({"name": "codex-copilot", "version": "9.9.9"}),
    )
    _write(signed / "plugins/codex-copilot/skills/tier/SKILL.md", "signed tier\n")
    _write(signed / "plugins/other/skills/tier/SKILL.md", "other signed tree\n")
    _write(signed / ".gitignore", "*.ignored\n")
    subprocess.run(("git", "add", "-A"), cwd=signed, check=True)
    subprocess.run(("git", "commit", "-qm", "signed plugin"), cwd=signed, check=True)
    subprocess.run(
        ("git", "tag", "-s", "v9.9.9", "-m", "signed release"), cwd=signed, check=True
    )
    public_key = (tmp_path / "signing-key.pub").read_text(encoding="utf-8").strip()
    fingerprint = subprocess.run(
        ("ssh-keygen", "-lf", str(tmp_path / "signing-key.pub")),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()[1]
    manifest = tmp_path / "copilot.layers.yml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "layers": [
                    {
                        "id": "codex-personal",
                        "role": "personal",
                        "rank": 10,
                        "product": "codex",
                        "source": {
                            "repo": "fixture:personal",
                            "ref": "main",
                            "path": str(unsigned),
                        },
                        "auth": "personal",
                        "activation": "always",
                        "policy": {"allowed_signers": []},
                    },
                    {
                        "id": "codex-organization",
                        "role": "organization",
                        "rank": 20,
                        "product": "codex",
                        "source": {
                            "repo": "fixture-org/codex-organization",
                            "ref": "v9.9.9",
                            "path": str(signed),
                        },
                        "auth": "work",
                        "activation": "always",
                        "policy": {"allowed_signers": [fingerprint]},
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return manifest, signed, fingerprint, public_key


def _configure_signed_ladder(
    monkeypatch: pytest.MonkeyPatch, manifest: Path, fingerprint: str, public_key: str
) -> None:
    state_path = manifest.parent / "entitlements.json"
    organization = next(
        layer
        for layer in yaml.safe_load(manifest.read_text(encoding="utf-8"))["layers"]
        if layer["id"] == "codex-organization"
    )
    decision = entitlement.observe_layer(
        organization,
        login="fixture-user",
        token="fixture-token",
        get_json=lambda _url, _token: 200,
        state_path=state_path,
    )
    assert decision.eligible
    monkeypatch.setattr(entitlement, "entitlement_state_path", lambda: state_path)
    monkeypatch.setattr(entitlement, "current_login", lambda: "fixture-user")
    monkeypatch.setattr(
        codex_plugin_source,
        "resolve_key",
        lambda key: (
            str(manifest)
            if key == "layers.manifest"
            else str(manifest.parent / "mirrors")
        ),
    )
    monkeypatch.setattr(
        policy, "FOUNDATION_SSH_SIGNING_KEYS", {fingerprint: public_key}
    )


def _configure_sources(
    monkeypatch: pytest.MonkeyPatch, claude: Path, codex: Path
) -> None:
    def resolve(key: str) -> str | None:
        return {
            "paths.claude_copilot_root": str(claude),
            "paths.codex_copilot_root": str(codex),
        }.get(key)

    monkeypatch.setattr(recipes, "resolve_key", resolve)
    monkeypatch.setattr(project_integration, "resolve_key", resolve)
    monkeypatch.setattr(project_reconciliation, "resolve_key", resolve)
    monkeypatch.setattr(
        project_reconciliation,
        "inspect_project_integration",
        project_integration.inspect_project_integration,
    )
    monkeypatch.setattr(
        project_reconciliation, "is_project_excluded", lambda _path: False
    )


def _machine(root: Path) -> dict[str, Any]:
    return {
        "state": "ready",
        "helper": {
            "state": "ready",
            "version": "2.12.2",
            "path": "/fixture/cc",
            "detail": "The helper is ready.",
        },
        "frameworks": [
            {
                "component": component,
                "state": "ready",
                "path": f"/{component}",
                "version": "1.0.0",
                "detail": "The source is ready.",
            }
            for component in ("claude", "codex")
        ],
        "configuration": {
            "state": "ready",
            "path": "/fixture/config.json",
            "approved_roots": [str(root)],
            "detail": "The approved root is ready.",
        },
        "authentication": {
            "state": "signed-in",
            "credential_state": "present",
            "detail": "Authentication is ready.",
        },
        "connectivity": {"state": "online", "detail": "Connectivity is ready."},
        "layers": {"state": "ready", "ready": 2, "total": 2, "detail": "Ready."},
        "dependencies": [],
        "blockers": [],
        "next_action": "Run the transaction.",
    }


def _census(project: Path, root: Path):
    def build(**kwargs: Any) -> list[dict[str, Any]]:
        selections = kwargs.get("selections") or {}
        return [
            assess_project(
                project,
                approved_root=root,
                selected_components=tuple(selections[str(project)]),
            )
        ]

    return build


def _snapshot(root: Path) -> dict[str, tuple[str, bytes | str, int]]:
    result: dict[str, tuple[str, bytes | str, int]] = {}
    for path in sorted(root.rglob("*")):
        if ".git" in path.relative_to(root).parts or (
            path.is_dir() and not path.is_symlink()
        ):
            continue
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            result[relative] = ("symlink", str(path.readlink()), 0)
        else:
            result[relative] = ("file", path.read_bytes(), path.stat().st_mode & 0o777)
    return result


def test_clean_project_request_selects_one_transaction_for_both_components(
    tmp_path: Path,
) -> None:
    project = _git_project(tmp_path)

    request = build_canonical_project_request(project, approved_roots=(tmp_path,))

    assert request.roots == (str(tmp_path.resolve()),)
    assert request.projects[0].path == str(project)
    assert request.projects[0].components == ("claude", "codex")


def test_degraded_existing_project_uses_the_same_request_shape(tmp_path: Path) -> None:
    project = _git_project(tmp_path)
    (project / ".claude").mkdir()
    (project / ".claude/commands").mkdir()
    (project / ".claude/commands/protocol.md").write_text(
        "partial setup\n", encoding="utf-8"
    )

    payload = json.loads(
        canonical_project_request_json(project, approved_roots=(tmp_path,))
    )

    assert payload["projects"] == [
        {"path": str(project), "components": ["claude", "codex"]}
    ]


def test_dirty_project_is_held_and_request_build_never_changes_owned_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _git_project(tmp_path)
    owned = project / "human-notes.md"
    owned.write_text("do not change\n", encoding="utf-8")
    before = owned.read_bytes()

    build_canonical_project_request(project, approved_roots=(tmp_path,))
    monkeypatch.setattr(
        project_reconciliation, "is_project_excluded", lambda _path: False
    )
    monkeypatch.setattr(
        project_reconciliation, "_source_available", lambda _component: True
    )
    assessment = assess_project(
        project,
        approved_root=tmp_path,
        selected_components=("claude", "codex"),
    )

    assert owned.read_bytes() == before
    assert not (project / "copilot.lock.json").exists()
    assert not (project / ".claude").exists()
    assert assessment["route"] == "held"
    assert any(item["code"] == "dirty-working-tree" for item in assessment["blockers"])


def test_never_widens_authority_outside_approved_root(tmp_path: Path) -> None:
    project = _git_project(tmp_path / "projects")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()

    with pytest.raises(RequestValidationError, match="approved project folder"):
        build_canonical_project_request(project, approved_roots=(unrelated,))


def test_nearest_approved_root_is_selected(tmp_path: Path) -> None:
    group = tmp_path / "group"
    project = _git_project(group)

    request = build_canonical_project_request(project, approved_roots=(tmp_path, group))

    assert request.roots == (str(group.resolve()),)


@pytest.mark.parametrize("components", [(), ("claude", "claude"), ("other",)])
def test_invalid_component_selection_is_rejected(
    tmp_path: Path, components: tuple[str, ...]
) -> None:
    project = _git_project(tmp_path)

    with pytest.raises(RequestValidationError, match="supported components"):
        build_canonical_project_request(
            project, components=components, approved_roots=(tmp_path,)
        )


def test_setup_and_update_commands_are_thin_canonical_adapters() -> None:
    repository = Path(__file__).parents[3]
    commands = [
        repository / ".claude/commands/setup-project.md",
        repository / ".claude/commands/update-project.md",
    ]

    for command in commands:
        text = command.read_text(encoding="utf-8")
        assert "canonical_project_request_json" in text
        assert "inspect_canonical_prerequisites" in text
        assert 'reconcile plan --request "$REQUEST_FILE"' in text
        assert 'reconcile apply --request "$REQUEST_FILE"' in text
        assert 'reconcile verify --request "$REQUEST_FILE"' in text
        assert "grep -q '^cc version'" in text
        assert "command -v tc" in text
        assert "Claude Copilot machine setup is required" in text
        assert "scripts/setup-project.sh" not in text
        assert "rm -rf" not in text
        assert "cp ~/.claude" not in text

    setup_text = commands[0].read_text(encoding="utf-8")
    assert "former partial `minimal` / `quick start` profile is retired" in setup_text


def test_prerequisite_fact_rejects_system_compiler_and_names_machine_setup(
    tmp_path: Path,
) -> None:
    def which(name: str) -> str | None:
        return {"cc": "/usr/bin/cc", "tc": None}.get(name)

    def run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            ("/usr/bin/cc", "--version"), 0, "Apple clang version 17\n", ""
        )

    report = inspect_canonical_prerequisites(
        which=which, run=run, home=tmp_path / "empty-home"
    )

    assert report == {
        "ready": False,
        "cc": {"state": "missing-or-wrong-program", "path": None},
        "tc": {"state": "missing", "path": None},
        "responsible_actor": "person",
        "next_action": "Complete Claude Copilot machine setup in ~/.claude/copilot with /setup, open a fresh shell, then retry the project transaction.",
    }


def test_complete_canonical_transaction_applies_verifies_and_repeats_zero_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude, codex, commands = _reference_sources(tmp_path)
    _configure_sources(monkeypatch, claude, codex)
    authority = tmp_path / "projects"
    project = _git_project(authority)
    request = build_canonical_project_request(project, approved_roots=(authority,))
    state_root = tmp_path / "transaction-state"

    def machine_builder() -> dict[str, Any]:
        return _machine(authority.resolve())

    census_builder = _census(project, authority.resolve())

    def plan_issuer(**kwargs: Any) -> Any:
        return issue_plan(**kwargs, root=state_root)

    plan = build_plan_report(
        request,
        machine_builder=machine_builder,
        census_builder=census_builder,
        plan_issuer=plan_issuer,
    )
    assert plan["result"] == "action-required"
    assert plan["plans"][0]["operations"]

    applied = build_apply_report(
        request,
        plan["plan_id"],
        machine_builder=machine_builder,
        census_builder=census_builder,
        state_root=state_root,
    )
    verified = build_verify_report(
        request,
        machine_builder=machine_builder,
        census_builder=census_builder,
    )
    assert applied["result"] == "applied"
    assert verified["result"] == "ready"

    expected = {
        *(f".claude/commands/{command}" for command in commands),
        ".claude/agents/me.md",
        ".claude/agents/qa.md",
        ".claude/agents/kc.md",
        ".claude/fitness-check.sh",
        ".claude/hooks/copilot-hook.sh",
        ".claude/settings.json",
        ".claude/cc/config.json",
        ".claude/memory/entries/.gitkeep",
        ".claude/memory/.gitignore",
        "CLAUDE.md",
        ".mcp.json",
        "AGENTS.md",
        "plugins/codex-copilot/.codex-plugin/plugin.json",
        "plugins/codex-copilot/skills/me/SKILL.md",
        ".claude/skills/codex-copilot",
        "scripts/copilot-gate.sh",
        ".codex-copilot.json",
        "copilot.lock.json",
        "copilot.project.json",
    }
    assert expected <= set(_snapshot(project))
    lock_before = (project / "copilot.lock.json").read_bytes()
    before_repeat = _snapshot(project)

    repeat_plan = build_plan_report(
        request,
        machine_builder=machine_builder,
        census_builder=census_builder,
        plan_issuer=plan_issuer,
    )
    assert repeat_plan["result"] == "ready"
    assert repeat_plan["plans"][0]["operations"] == []
    repeat_apply = build_apply_report(
        request,
        repeat_plan["plan_id"],
        machine_builder=machine_builder,
        census_builder=census_builder,
        state_root=state_root,
    )
    assert repeat_apply["result"] == "applied"
    assert repeat_apply["ledger"][0]["status"] == "unchanged"
    assert _snapshot(project) == before_repeat
    assert (project / "copilot.lock.json").read_bytes() == lock_before


def test_canonical_degraded_repair_converges_and_dirty_unknown_work_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude, codex, _commands = _reference_sources(tmp_path)
    _configure_sources(monkeypatch, claude, codex)
    authority = tmp_path / "projects"
    project = _git_project(authority)
    request = build_canonical_project_request(project, approved_roots=(authority,))
    state_root = tmp_path / "transaction-state"

    def machine_builder() -> dict[str, Any]:
        return _machine(authority.resolve())

    census_builder = _census(project, authority.resolve())

    def plan_issuer(**kwargs: Any) -> Any:
        return issue_plan(**kwargs, root=state_root)

    initial = build_plan_report(
        request,
        machine_builder=machine_builder,
        census_builder=census_builder,
        plan_issuer=plan_issuer,
    )
    assert (
        build_apply_report(
            request,
            initial["plan_id"],
            machine_builder=machine_builder,
            census_builder=census_builder,
            state_root=state_root,
        )["result"]
        == "applied"
    )
    canonical_lock = (project / "copilot.lock.json").read_bytes()
    subprocess.run(("git", "add", "-A"), cwd=project, check=True)
    subprocess.run(("git", "commit", "-qm", "reference"), cwd=project, check=True)

    missing = project / ".claude/commands/pause.md"
    missing.unlink()
    subprocess.run(("git", "add", "-A"), cwd=project, check=True)
    subprocess.run(("git", "commit", "-qm", "degraded"), cwd=project, check=True)
    degraded = build_plan_report(
        request,
        machine_builder=machine_builder,
        census_builder=census_builder,
        plan_issuer=plan_issuer,
    )
    targets = {item["target"] for item in degraded["plans"][0]["operations"]}
    assert ".claude/commands/pause.md" in targets
    repaired = build_apply_report(
        request,
        degraded["plan_id"],
        machine_builder=machine_builder,
        census_builder=census_builder,
        state_root=state_root,
    )
    assert repaired["result"] == "applied"
    assert missing.read_bytes() == (claude / ".claude/commands/pause.md").read_bytes()
    assert (project / "copilot.lock.json").read_bytes() == canonical_lock

    human = project / "human-notes.md"
    human.write_text("preserve me\n", encoding="utf-8")
    before = _snapshot(project)
    repeat = build_plan_report(
        request,
        machine_builder=machine_builder,
        census_builder=census_builder,
        plan_issuer=plan_issuer,
    )
    assert repeat["result"] == "ready"
    assert repeat["plans"][0]["operations"] == []
    assert _snapshot(project) == before

    dirty_project = _git_project(authority, "dirty-project")
    dirty_note = dirty_project / "human-notes.md"
    dirty_note.write_text("never destroy\n", encoding="utf-8")
    dirty_before = _snapshot(dirty_project)
    dirty_request = build_canonical_project_request(
        dirty_project, approved_roots=(authority,)
    )
    dirty_census = _census(dirty_project, authority.resolve())
    held = build_plan_report(
        dirty_request,
        machine_builder=machine_builder,
        census_builder=dirty_census,
        plan_issuer=plan_issuer,
    )
    assert held["result"] == "blocked"
    assert held["projects"][0]["route"] == "held"
    assert held["plans"][0]["operations"] == []
    assert _snapshot(dirty_project) == dirty_before


def test_signed_codex_ladder_excludes_unsigned_nearer_tier_and_rejects_extra_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, signed, fingerprint, public_key = _signed_codex_ladder(tmp_path)
    _configure_signed_ladder(monkeypatch, manifest, fingerprint, public_key)

    source = codex_plugin_source.resolve_codex_plugin_source()

    assert source is not None
    assert source.layer == "codex-organization"
    assert source.ref == "v9.9.9"
    assert source.signer == fingerprint
    assert len(source.tree) == 40
    assert source.path == (signed / "plugins/codex-copilot").resolve()

    # Ignored files are still bytes the transaction would copy. They must not
    # bypass the signed tree merely because ordinary `git status` hides them.
    _write(source.path / "payload.ignored", "malicious addition\n")
    with pytest.raises(
        codex_plugin_source.CodexPluginSourceError,
        match="authorized signed release",
    ):
        codex_plugin_source.resolve_codex_plugin_source()
    (source.path / "payload.ignored").unlink()
    shutil.rmtree(source.path)
    source.path.symlink_to("other")
    with pytest.raises(
        codex_plugin_source.CodexPluginSourceError,
        match="unavailable|protected|authorized signed release",
    ):
        codex_plugin_source.resolve_codex_plugin_source()


def test_revoked_codex_tier_is_excluded_until_live_reauthorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, _signed, fingerprint, public_key = _signed_codex_ladder(tmp_path)
    _configure_signed_ladder(monkeypatch, manifest, fingerprint, public_key)
    state_path = manifest.parent / "entitlements.json"
    organization = next(
        layer
        for layer in yaml.safe_load(manifest.read_text(encoding="utf-8"))["layers"]
        if layer["id"] == "codex-organization"
    )
    assert codex_plugin_source.resolve_codex_plugin_source() is not None

    revoked = entitlement.observe_layer(
        organization,
        login="fixture-user",
        token="fixture-token",
        get_json=lambda _url, _token: 404,
        state_path=state_path,
    )
    assert revoked.state == "revoked"
    assert codex_plugin_source.resolve_codex_plugin_source() is None

    restored = entitlement.observe_layer(
        organization,
        login="fixture-user",
        token="fixture-token",
        get_json=lambda _url, _token: 200,
        state_path=state_path,
    )
    assert restored.state == "entitled"
    assert codex_plugin_source.resolve_codex_plugin_source() is not None


def test_signed_tier_canonical_transaction_provenance_repair_repeat_and_never_destroy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude, codex, _commands = _reference_sources(tmp_path)
    manifest, signed, fingerprint, public_key = _signed_codex_ladder(tmp_path)
    _configure_sources(monkeypatch, claude, codex)
    _configure_signed_ladder(monkeypatch, manifest, fingerprint, public_key)
    authority = tmp_path / "projects"
    project = _git_project(authority)
    request = build_canonical_project_request(project, approved_roots=(authority,))
    state_root = tmp_path / "state"

    def machine_builder() -> dict[str, Any]:
        return _machine(authority.resolve())

    census_builder = _census(project, authority.resolve())

    def plan_issuer(**kwargs: Any) -> Any:
        return issue_plan(**kwargs, root=state_root)

    plan = build_plan_report(
        request,
        machine_builder=machine_builder,
        census_builder=census_builder,
        plan_issuer=plan_issuer,
    )
    plugin_operation = next(
        operation
        for operation in plan["plans"][0]["operations"]
        if operation["target"] == "plugins/codex-copilot"
    )
    assert plugin_operation["kind"] == "copy-tree-from-source"
    applied = build_apply_report(
        request,
        plan["plan_id"],
        machine_builder=machine_builder,
        census_builder=census_builder,
        state_root=state_root,
    )
    assert applied["result"] == "applied"
    assert (
        project / "plugins/codex-copilot/skills/tier/SKILL.md"
    ).read_text() == "signed tier\n"
    lock = json.loads((project / "copilot.lock.json").read_text(encoding="utf-8"))
    codex_entry = next(
        item for item in lock["components"] if item["component"] == "codex"
    )
    assert codex_entry["provenance"] == {
        "layer": "codex-organization",
        "ref": "v9.9.9",
        "tree": subprocess.run(
            ("git", "rev-parse", "v9.9.9^{commit}:plugins/codex-copilot"),
            cwd=signed,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip(),
        "signer": fingerprint,
    }

    before_repeat = _snapshot(project)
    repeat = build_plan_report(
        request,
        machine_builder=machine_builder,
        census_builder=census_builder,
        plan_issuer=plan_issuer,
    )
    assert repeat["plans"][0]["operations"] == []
    assert (
        build_apply_report(
            request,
            repeat["plan_id"],
            machine_builder=machine_builder,
            census_builder=census_builder,
            state_root=state_root,
        )["ledger"][0]["status"]
        == "unchanged"
    )
    assert _snapshot(project) == before_repeat

    subprocess.run(("git", "add", "-A"), cwd=project, check=True)
    subprocess.run(
        ("git", "commit", "-qm", "canonical install"), cwd=project, check=True
    )
    missing = project / "plugins/codex-copilot/skills/tier/SKILL.md"
    missing.unlink()
    subprocess.run(("git", "add", "-A"), cwd=project, check=True)
    subprocess.run(
        ("git", "commit", "-qm", "known degradation"), cwd=project, check=True
    )
    repair = build_plan_report(
        request,
        machine_builder=machine_builder,
        census_builder=census_builder,
        plan_issuer=plan_issuer,
    )
    assert repair["result"] == "action-required", json.dumps(repair, indent=2)
    assert "plugins/codex-copilot" in {
        operation["target"] for operation in repair["plans"][0]["operations"]
    }
    assert (
        build_apply_report(
            request,
            repair["plan_id"],
            machine_builder=machine_builder,
            census_builder=census_builder,
            state_root=state_root,
        )["result"]
        == "applied"
    )
    assert missing.read_text(encoding="utf-8") == "signed tier\n"

    missing.write_text("project customization\n", encoding="utf-8")
    tampered_verification = build_verify_report(
        request,
        machine_builder=machine_builder,
        census_builder=census_builder,
    )
    assert tampered_verification["result"] != "ready"
    assert tampered_verification["projects"][0]["components"][1]["state"] != "ready"
    subprocess.run(("git", "add", "-A"), cwd=project, check=True)
    subprocess.run(
        ("git", "commit", "-qm", "customized plugin"), cwd=project, check=True
    )
    customized_before = _snapshot(project)
    customized = build_plan_report(
        request,
        machine_builder=machine_builder,
        census_builder=census_builder,
        plan_issuer=plan_issuer,
    )
    assert customized["result"] == "blocked"
    assert customized["plans"][0]["operations"] == []
    assert _snapshot(project) == customized_before

    dirty_project = _git_project(authority, "dirty-tier-project")
    _write(dirty_project / "owner.txt", "never destroy\n")
    dirty_before = _snapshot(dirty_project)
    dirty_request = build_canonical_project_request(
        dirty_project, approved_roots=(authority,)
    )
    held = build_plan_report(
        dirty_request,
        machine_builder=machine_builder,
        census_builder=_census(dirty_project, authority.resolve()),
        plan_issuer=plan_issuer,
    )
    assert held["result"] == "blocked"
    assert _snapshot(dirty_project) == dirty_before


def test_executor_revalidates_signed_tier_before_any_project_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude, codex, _commands = _reference_sources(tmp_path)
    manifest, signed, fingerprint, public_key = _signed_codex_ladder(tmp_path)
    _configure_sources(monkeypatch, claude, codex)
    _configure_signed_ladder(monkeypatch, manifest, fingerprint, public_key)
    authority = tmp_path / "projects"
    project = _git_project(authority)
    state_root = tmp_path / "state"
    assessment = assess_project(
        project,
        approved_root=authority.resolve(),
        selected_components=("claude", "codex"),
    )
    recipe_plan = build_recipe_plan(assessment, ("claude", "codex"))
    before = _snapshot(project)
    plugin = signed / "plugins/codex-copilot"
    shutil.rmtree(plugin)
    plugin.symlink_to("other")

    ledger = execute_reconciliation(
        [recipe_plan.transaction_plan()],
        run_id="run_" + "a" * 32,
        root=state_root,
    )

    assert ledger[0]["status"] == "blocked"
    assert _snapshot(project) == before


def test_canonical_executor_entitlement_lease_blocks_live_revocation_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude, codex, _commands = _reference_sources(tmp_path)
    manifest, _signed, fingerprint, public_key = _signed_codex_ladder(tmp_path)
    _configure_sources(monkeypatch, claude, codex)
    _configure_signed_ladder(monkeypatch, manifest, fingerprint, public_key)
    authority = tmp_path / "projects"
    project = _git_project(authority)
    request = build_canonical_project_request(project, approved_roots=(authority,))
    state_root = tmp_path / "state"
    def machine_builder() -> dict[str, Any]:
        return _machine(authority.resolve())

    census_builder = _census(project, authority.resolve())

    def plan_issuer(**kwargs: Any) -> Any:
        return issue_plan(**kwargs, root=state_root)
    plan = build_plan_report(
        request,
        machine_builder=machine_builder,
        census_builder=census_builder,
        plan_issuer=plan_issuer,
    )
    prepared = prepare_reconciliation(
        request,
        machine_builder=machine_builder,
        census_builder=census_builder,
    )
    private = prepared.execution_plans[0].entitlement_bindings
    assert private
    public_bytes = json.dumps(plan, sort_keys=True)
    assert "fixture-user" not in public_bytes
    assert "entitlements.json" not in public_bytes
    before = _snapshot(project)
    state_path = manifest.parent / "entitlements.json"
    organization = next(
        layer
        for layer in yaml.safe_load(manifest.read_text(encoding="utf-8"))["layers"]
        if layer["id"] == "codex-organization"
    )

    def revoke_then_execute(plans: Any, **kwargs: Any) -> Any:
        revoked = entitlement.observe_layer(
            organization,
            login="fixture-user",
            token="fixture-token",
            get_json=lambda _url, _token: 404,
            state_path=state_path,
        )
        assert revoked.state == "revoked"
        return execute_reconciliation(plans, root=state_root, **kwargs)

    applied = build_apply_report(
        request,
        plan["plan_id"],
        machine_builder=machine_builder,
        census_builder=census_builder,
        state_root=state_root,
        transaction_executor=revoke_then_execute,
    )
    assert applied["result"] == "blocked"
    assert applied["ledger"][0]["status"] == "blocked"
    assert applied["ledger"][0]["completed_operation_ids"] == []
    assert _snapshot(project) == before


def test_canonical_executor_entitlement_lease_blocks_old_denial_after_reauthorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude, codex, _commands = _reference_sources(tmp_path)
    manifest, _signed, fingerprint, public_key = _signed_codex_ladder(tmp_path)
    _configure_sources(monkeypatch, claude, codex)
    _configure_signed_ladder(monkeypatch, manifest, fingerprint, public_key)
    state_path = manifest.parent / "entitlements.json"
    organization = next(
        layer
        for layer in yaml.safe_load(manifest.read_text(encoding="utf-8"))["layers"]
        if layer["id"] == "codex-organization"
    )
    assert entitlement.observe_layer(
        organization,
        login="fixture-user",
        token="fixture-token",
        get_json=lambda _url, _token: 404,
        state_path=state_path,
    ).state == "revoked"
    authority = tmp_path / "projects"
    project = _git_project(authority)
    request = build_canonical_project_request(project, approved_roots=(authority,))
    state_root = tmp_path / "state"
    def machine_builder() -> dict[str, Any]:
        return _machine(authority.resolve())

    census_builder = _census(project, authority.resolve())

    def plan_issuer(**kwargs: Any) -> Any:
        return issue_plan(**kwargs, root=state_root)
    plan = build_plan_report(
        request,
        machine_builder=machine_builder,
        census_builder=census_builder,
        plan_issuer=plan_issuer,
    )
    before = _snapshot(project)

    def reauthorize_then_execute(plans: Any, **kwargs: Any) -> Any:
        restored = entitlement.observe_layer(
            organization,
            login="fixture-user",
            token="fixture-token",
            get_json=lambda _url, _token: 200,
            state_path=state_path,
        )
        assert restored.state == "entitled"
        return execute_reconciliation(plans, root=state_root, **kwargs)

    applied = build_apply_report(
        request,
        plan["plan_id"],
        machine_builder=machine_builder,
        census_builder=census_builder,
        state_root=state_root,
        transaction_executor=reauthorize_then_execute,
    )
    assert applied["result"] == "blocked"
    assert applied["ledger"][0]["completed_operation_ids"] == []
    assert _snapshot(project) == before


def test_canonical_public_sources_need_no_entitlement_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude, codex, _commands = _reference_sources(tmp_path)
    _configure_sources(monkeypatch, claude, codex)
    monkeypatch.setattr(recipes, "resolve_codex_plugin_source_with_bindings", lambda: (None, ()))
    authority = tmp_path / "projects"
    project = _git_project(authority)
    assessment = assess_project(
        project,
        approved_root=authority.resolve(),
        selected_components=("claude", "codex"),
    )
    recipe = build_recipe_plan(assessment, ("claude", "codex"))
    transaction = recipe.transaction_plan()
    assert recipe.entitlement_bindings == ()
    assert transaction.entitlement_bindings == ()


def test_planner_derives_fingerprint_and_lock_from_signed_object_during_mutation_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _claude, codex, _commands = _reference_sources(tmp_path)
    manifest, signed, fingerprint, public_key = _signed_codex_ladder(tmp_path)
    _configure_signed_ladder(monkeypatch, manifest, fingerprint, public_key)
    project = _git_project(tmp_path / "projects")
    real_verify = codex_plugin_source.verify_git_item_provenance

    def verify_then_mutate(*args: Any, **kwargs: Any) -> Any:
        subprocess.run(
            ("git", "checkout", "-q", "v9.9.9", "--", "plugins/codex-copilot"),
            cwd=signed,
            check=True,
        )
        verified = real_verify(*args, **kwargs)
        plugin = signed / "plugins/codex-copilot"
        shutil.rmtree(plugin)
        shutil.copytree(signed / "plugins/other", plugin)
        return verified

    monkeypatch.setattr(
        codex_plugin_source, "verify_git_item_provenance", verify_then_mutate
    )

    def resolve_recipe_key(key: str) -> str | None:
        return str(codex) if key == "paths.codex_copilot_root" else None

    monkeypatch.setattr(recipes, "resolve_key", resolve_recipe_key)

    operations = recipes._codex_setup(project, "codex")
    copy = next(item for item in operations if item.target == "plugins/codex-copilot")
    lock_operation = next(
        item for item in operations if item.kind.value == "upsert-lock-component"
    )
    lock_entry = lock_operation.payload["component_entry"]
    signed_skill = next(
        item
        for item in lock_entry["files"]
        if item["path"] == "plugins/codex-copilot/skills/tier/SKILL.md"
    )

    assert lock_entry["version"] == "9.9.9"
    assert lock_entry["release_tag"] == "v9.9.9"
    assert (
        copy.source_fingerprint
        == policy.read_git_tree_snapshot(
            signed, lock_entry["provenance"]["tree"]
        ).fingerprint()
    )
    assert (
        signed_skill["checksum"]
        == "sha256:" + hashlib.sha256(b"signed tier\n").hexdigest()
    )
    assert (
        signed / "plugins/codex-copilot/skills/tier/SKILL.md"
    ).read_text() == "other signed tree\n"


def test_executor_stages_signed_object_not_post_verification_worktree_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude, codex, _commands = _reference_sources(tmp_path)
    manifest, signed, fingerprint, public_key = _signed_codex_ladder(tmp_path)
    _configure_sources(monkeypatch, claude, codex)
    _configure_signed_ladder(monkeypatch, manifest, fingerprint, public_key)
    authority = tmp_path / "projects"
    project = _git_project(authority)
    assessment = assess_project(
        project,
        approved_root=authority.resolve(),
        selected_components=("claude", "codex"),
    )
    recipe_plan = build_recipe_plan(assessment, ("claude", "codex"))
    real_revalidate = transaction_module.revalidate_git_item_provenance

    def revalidate_then_mutate(*args: Any, **kwargs: Any) -> bool:
        assert real_revalidate(*args, **kwargs)
        plugin = signed / "plugins/codex-copilot"
        shutil.rmtree(plugin)
        shutil.copytree(signed / "plugins/other", plugin)
        return True

    monkeypatch.setattr(
        transaction_module,
        "revalidate_git_item_provenance",
        revalidate_then_mutate,
    )
    ledger = execute_reconciliation(
        [recipe_plan.transaction_plan()],
        run_id="run_" + "b" * 32,
        root=tmp_path / "state",
    )

    assert ledger[0]["status"] == "applied"
    assert (
        project / "plugins/codex-copilot/skills/tier/SKILL.md"
    ).read_text() == "signed tier\n"
    assert (
        signed / "plugins/codex-copilot/skills/tier/SKILL.md"
    ).read_text() == "other signed tree\n"


def test_provenance_lock_never_downgrades_when_manifest_disappears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude, codex, _commands = _reference_sources(tmp_path)
    manifest, _signed, fingerprint, public_key = _signed_codex_ladder(tmp_path)
    _configure_sources(monkeypatch, claude, codex)
    _configure_signed_ladder(monkeypatch, manifest, fingerprint, public_key)
    authority = tmp_path / "projects"
    project = _git_project(authority)
    request = build_canonical_project_request(project, approved_roots=(authority,))
    state_root = tmp_path / "state"

    def machine_builder() -> dict[str, Any]:
        return _machine(authority.resolve())

    census_builder = _census(project, authority.resolve())

    def issue(**kwargs: Any) -> Any:
        return issue_plan(**kwargs, root=state_root)

    plan = build_plan_report(
        request,
        machine_builder=machine_builder,
        census_builder=census_builder,
        plan_issuer=issue,
    )
    assert (
        build_apply_report(
            request,
            plan["plan_id"],
            machine_builder=machine_builder,
            census_builder=census_builder,
            state_root=state_root,
        )["result"]
        == "applied"
    )
    lock_before = (project / "copilot.lock.json").read_bytes()
    subprocess.run(("git", "add", "-A"), cwd=project, check=True)
    subprocess.run(("git", "commit", "-qm", "signed install"), cwd=project, check=True)
    (project / "plugins/codex-copilot/skills/tier/SKILL.md").unlink()
    subprocess.run(("git", "add", "-A"), cwd=project, check=True)
    subprocess.run(("git", "commit", "-qm", "degraded"), cwd=project, check=True)
    before = _snapshot(project)
    monkeypatch.setattr(codex_plugin_source, "resolve_key", lambda _key: None)

    assessment = assess_project(
        project,
        approved_root=authority.resolve(),
        selected_components=("claude", "codex"),
    )
    assert assessment["components"][1]["state"] == "source-unavailable"
    with pytest.raises(
        ReconciliationError, match="no verified framework recipe source"
    ):
        build_plan_report(
            request,
            machine_builder=machine_builder,
            census_builder=census_builder,
            plan_issuer=issue,
        )
    assert (project / "copilot.lock.json").read_bytes() == lock_before
    assert _snapshot(project) == before
