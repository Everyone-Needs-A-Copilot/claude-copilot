from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from cc.core.ecosystem.project_migrations import (
    CLAUDE_ENTRY_KIND,
    CODEX_PORTABLE_KIND,
    apply_migration_action,
    build_migration_candidate,
    build_migration_report,
)
from cc.core.config import resolve_key
from cc.core.ecosystem.workspaces import (
    activate_components,
    workspace_status,
    write_install_lock,
)
from jsonschema import Draft202012Validator


def _repo_roots() -> tuple[Path, Path]:
    """Locate this checkout's own root plus the machine's configured
    codex-copilot install.

    `claude_root` is derived from `__file__` itself (this test's own
    containing repo) rather than reconstructed by guessing a sibling
    directory *named* "claude-copilot" -- that guess breaks under a git
    worktree, where the checkout directory is named after the worktree,
    not the repo (e.g. `/private/tmp/some-worktree/...`), so
    `parents[4] / "claude-copilot"` silently resolves to an unrelated (or
    nonexistent) directory instead of this checkout.

    `codex_root` has no `__file__`-relative anchor -- it's a different
    repo entirely -- so it uses the same machine-level config lookup
    (`paths.codex_copilot_root`) that `activate_components` itself falls
    back to when no override is supplied, keeping this test aligned with
    the code under test instead of re-guessing a directory layout.
    """
    claude_root = Path(__file__).resolve().parents[3]
    codex_root = resolve_key("paths.codex_copilot_root")
    if not codex_root:
        raise RuntimeError(
            "paths.codex_copilot_root is not configured on this machine "
            "(cc config set paths.codex_copilot_root /path/to/codex-copilot)"
        )
    return claude_root, Path(str(codex_root)).expanduser()


def _git(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *args),
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )


def _commit_all(project: Path, message: str = "fixture") -> None:
    assert _git(project, "add", "-A").returncode == 0
    result = _git(
        project,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        message,
    )
    assert result.returncode == 0, result.stderr


def _legacy_project(
    tmp_path: Path,
    *,
    legacy_claude_entry: bool = True,
    gate_mode: str = "current-file",
) -> tuple[Path, Path, Path]:
    project = tmp_path / "legacy-project"
    project.mkdir(parents=True)
    assert _git(project, "init", "-q").returncode == 0
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
    config.update(
        {
            "installType": "symlink",
            "keptMetadata": "preserve-me",
        }
    )
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    if legacy_claude_entry:
        claude_path = project / "CLAUDE.md"
        claude_path.write_text(
            claude_path.read_text(encoding="utf-8").replace(
                "## Claude Copilot", "## Earlier Copilot Setup"
            ),
            encoding="utf-8",
        )

    gate = project / "scripts/copilot-gate.sh"
    if gate_mode == "legacy-link":
        gate.unlink()
        gate.symlink_to(external_gate)
    elif gate_mode == "missing":
        gate.unlink()
    elif gate_mode == "missing-directory":
        shutil.rmtree(gate.parent)
    elif gate_mode == "custom-file":
        gate.write_text("#!/bin/sh\necho custom\n", encoding="utf-8")
        lock_path = project / "copilot.lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        codex_entry = next(
            item for item in lock["components"] if item["component"] == "codex"
        )
        codex_entry["files"] = [
            item
            for item in codex_entry["files"]
            if item["path"] != "scripts/copilot-gate.sh"
        ]
        lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    elif gate_mode != "current-file":
        raise AssertionError(gate_mode)

    _commit_all(project)
    return project, claude_root, codex_root


def _workspace(
    project: Path, claude_root: Path, codex_root: Path, tmp_path: Path
) -> dict:
    return workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        claude_root=claude_root,
        codex_root=codex_root,
        detail=True,
    )


def test_census_is_read_only_and_offers_component_scoped_actions(
    tmp_path: Path,
) -> None:
    project, claude_root, codex_root = _legacy_project(tmp_path)
    before_status = _git(project, "status", "--porcelain=v1").stdout
    before_head = _git(project, "rev-parse", "HEAD").stdout

    candidate = build_migration_candidate(
        project,
        _workspace(project, claude_root, codex_root, tmp_path),
        claude_root=claude_root,
        codex_root=codex_root,
    )

    assert candidate["state"] == "eligible"
    assert candidate["automatable"] is True
    assert candidate["migration_kinds"] == [
        CLAUDE_ENTRY_KIND,
        CODEX_PORTABLE_KIND,
    ]
    assert candidate["action"]["id"].startswith("sha256:")
    assert {item["path"] for item in candidate["action"]["will_change"]} >= {
        "CLAUDE.md",
        "plugins/codex-copilot",
        ".claude/skills/codex-copilot",
        ".codex-copilot.json",
        "copilot.lock.json",
    }
    assert _git(project, "status", "--porcelain=v1").stdout == before_status
    assert _git(project, "rev-parse", "HEAD").stdout == before_head


def test_dirty_tree_and_custom_gate_are_held_without_writes(tmp_path: Path) -> None:
    dirty, claude_root, codex_root = _legacy_project(tmp_path / "dirty")
    (dirty / "personal-notes.txt").write_text("unsaved\n", encoding="utf-8")
    dirty_candidate = build_migration_candidate(
        dirty,
        _workspace(dirty, claude_root, codex_root, tmp_path),
        claude_root=claude_root,
        codex_root=codex_root,
    )
    assert dirty_candidate["state"] == "held"
    assert dirty_candidate["reason_code"] == "dirty-working-tree"
    assert (dirty / "personal-notes.txt").read_text(encoding="utf-8") == "unsaved\n"

    custom, claude_root, codex_root = _legacy_project(
        tmp_path / "custom", gate_mode="custom-file"
    )
    gate_before = (custom / "scripts/copilot-gate.sh").read_bytes()
    custom_candidate = build_migration_candidate(
        custom,
        _workspace(custom, claude_root, codex_root, tmp_path),
        claude_root=claude_root,
        codex_root=codex_root,
    )
    assert custom_candidate["state"] == "held"
    assert custom_candidate["reason_code"] == "codex-project-conflict"
    assert (custom / "scripts/copilot-gate.sh").read_bytes() == gate_before


def test_apply_migrates_both_components_preserves_content_and_verifies(
    tmp_path: Path,
) -> None:
    project, claude_root, codex_root = _legacy_project(
        tmp_path, gate_mode="legacy-link"
    )
    claude_before = (project / "CLAUDE.md").read_text(encoding="utf-8")
    lock_before = json.loads(
        (project / "copilot.lock.json").read_text(encoding="utf-8")
    )
    old_claude_lock = next(
        item for item in lock_before["components"] if item["component"] == "claude"
    )
    candidate = build_migration_candidate(
        project,
        _workspace(project, claude_root, codex_root, tmp_path),
        claude_root=claude_root,
        codex_root=codex_root,
    )

    ledger = apply_migration_action(
        project,
        candidate["action"]["id"],
        claude_root=claude_root,
        codex_root=codex_root,
    )

    assert ledger["status"] == "applied"
    assert ledger["verification"] == "ready"
    assert set(ledger["targeted_components"]) == {"claude", "codex"}
    assert (
        ledger["_diagnostic"]["verification_after_apply"]["classification"]
        == "ready"
    )
    assert ledger["_diagnostic"]["source"]["fingerprint"].startswith("sha256:")
    claude_after = (project / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude_after.startswith(claude_before)
    assert "<!-- cc:project-integration:claude:v1:start -->" in claude_after
    assert (project / "plugins/codex-copilot").is_dir()
    assert not (project / "plugins/codex-copilot").is_symlink()
    bridge = project / ".claude/skills/codex-copilot"
    assert bridge.is_symlink()
    assert bridge.resolve() == (project / "plugins/codex-copilot/skills").resolve()
    config = json.loads((project / ".codex-copilot.json").read_text(encoding="utf-8"))
    assert config["installType"] == "copy"
    assert config["keptMetadata"] == "preserve-me"
    lock_after = json.loads((project / "copilot.lock.json").read_text(encoding="utf-8"))
    assert (
        next(item for item in lock_after["components"] if item["component"] == "claude")
        == old_claude_lock
    )
    after = _workspace(project, claude_root, codex_root, tmp_path)
    assert after["classification"] == "ready"


def test_apply_creates_the_gate_directory_when_the_project_has_none(
    tmp_path: Path,
) -> None:
    project, claude_root, codex_root = _legacy_project(
        tmp_path, gate_mode="missing-directory"
    )
    assert not (project / "scripts").exists()
    candidate = build_migration_candidate(
        project,
        _workspace(project, claude_root, codex_root, tmp_path),
        claude_root=claude_root,
        codex_root=codex_root,
    )

    ledger = apply_migration_action(
        project,
        candidate["action"]["id"],
        claude_root=claude_root,
        codex_root=codex_root,
    )

    assert ledger["status"] == "applied"
    assert ledger["verification"] == "ready"
    gate = project / "scripts/copilot-gate.sh"
    assert gate.is_file()
    assert gate.read_bytes() == (codex_root / "scripts/copilot-gate.sh").read_bytes()
    assert "install-project-local-gate" in {
        item["operation"] for item in ledger["completed_actions"]
    }


def test_rollback_removes_only_the_directories_the_migration_created(
    tmp_path: Path,
) -> None:
    project, claude_root, codex_root = _legacy_project(
        tmp_path, gate_mode="missing-directory"
    )
    candidate = build_migration_candidate(
        project,
        _workspace(project, claude_root, codex_root, tmp_path),
        claude_root=claude_root,
        codex_root=codex_root,
    )
    before_status = _git(project, "status", "--porcelain=v1").stdout

    ledger = apply_migration_action(
        project,
        candidate["action"]["id"],
        claude_root=claude_root,
        codex_root=codex_root,
        fail_after=4,
    )

    assert ledger["status"] == "rolled-back"
    assert not (project / "scripts").exists()
    assert _git(project, "status", "--porcelain=v1").stdout == before_status


def test_stale_action_refuses_and_injected_failure_restores_exact_state(
    tmp_path: Path,
) -> None:
    stale, claude_root, codex_root = _legacy_project(tmp_path / "stale")
    stale_candidate = build_migration_candidate(
        stale,
        _workspace(stale, claude_root, codex_root, tmp_path),
        claude_root=claude_root,
        codex_root=codex_root,
    )
    (stale / "CLAUDE.md").write_text("owner changed this\n", encoding="utf-8")
    stale_ledger = apply_migration_action(
        stale,
        stale_candidate["action"]["id"],
        claude_root=claude_root,
        codex_root=codex_root,
    )
    assert stale_ledger["status"] == "blocked"
    assert stale_ledger["completed_actions"] == []
    assert (stale / "CLAUDE.md").read_text(encoding="utf-8") == "owner changed this\n"

    rollback, claude_root, codex_root = _legacy_project(tmp_path / "rollback")
    rollback_candidate = build_migration_candidate(
        rollback,
        _workspace(rollback, claude_root, codex_root, tmp_path),
        claude_root=claude_root,
        codex_root=codex_root,
    )
    before = {
        "status": _git(rollback, "status", "--porcelain=v1").stdout,
        "claude": (rollback / "CLAUDE.md").read_bytes(),
        "plugin": str((rollback / "plugins/codex-copilot").readlink()),
        "bridge": str((rollback / ".claude/skills/codex-copilot").readlink()),
        "config": (rollback / ".codex-copilot.json").read_bytes(),
        "lock": (rollback / "copilot.lock.json").read_bytes(),
    }
    rollback_ledger = apply_migration_action(
        rollback,
        rollback_candidate["action"]["id"],
        claude_root=claude_root,
        codex_root=codex_root,
        fail_after=2,
    )
    assert rollback_ledger["status"] == "rolled-back"
    assert all(
        item["status"] == "rolled-back" for item in rollback_ledger["completed_actions"]
    )
    assert rollback_ledger["_diagnostic"]["exception"]["type"] == "OSError"
    assert rollback_ledger["_diagnostic"]["rollback"]
    assert all(item["restored"] for item in rollback_ledger["_diagnostic"]["rollback"])
    assert rollback_ledger["_diagnostic"]["verification_after_rollback"] is not None
    assert _git(rollback, "status", "--porcelain=v1").stdout == before["status"]
    assert (rollback / "CLAUDE.md").read_bytes() == before["claude"]
    assert str((rollback / "plugins/codex-copilot").readlink()) == before["plugin"]
    assert (
        str((rollback / ".claude/skills/codex-copilot").readlink()) == before["bridge"]
    )
    assert (rollback / ".codex-copilot.json").read_bytes() == before["config"]
    assert (rollback / "copilot.lock.json").read_bytes() == before["lock"]


def test_batch_report_counts_eligible_held_and_residual_rows(tmp_path: Path) -> None:
    eligible, claude_root, codex_root = _legacy_project(tmp_path / "eligible")
    eligible_candidate = build_migration_candidate(
        eligible,
        _workspace(eligible, claude_root, codex_root, tmp_path),
        claude_root=claude_root,
        codex_root=codex_root,
    )

    held, claude_root, codex_root = _legacy_project(tmp_path / "held")
    (held / "mine.txt").write_text("dirty\n", encoding="utf-8")
    held_candidate = build_migration_candidate(
        held,
        _workspace(held, claude_root, codex_root, tmp_path),
        claude_root=claude_root,
        codex_root=codex_root,
    )

    residual = dict(held_candidate)
    residual.update(
        {
            "path": str(tmp_path / "residual"),
            "name": "residual",
            "state": "residual-guidance",
            "reason_code": "no-deterministic-migration",
            "migration_kinds": [],
        }
    )
    report = build_migration_report([eligible_candidate, held_candidate, residual])

    assert report["schema_version"] == "1.1"
    assert report["mode"] == "plan"
    assert report["result"] == "action-required"
    assert report["plan_id"].startswith("sha256:")
    assert report["summary"] == {
        "eligible": 1,
        "held": 1,
        "residual-guidance": 1,
        "total_guided": 3,
    }
    schema_path = (
        Path(__file__).parent / "fixtures/schemas/workspace-migrations.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert not list(Draft202012Validator(schema).iter_errors(report))
