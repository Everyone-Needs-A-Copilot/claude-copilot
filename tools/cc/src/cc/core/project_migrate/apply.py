"""Apply a migration plan with a backup + rollback manifest. Never commits unless asked."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from cc.core.project_init import InitError, init_project
from cc.core.project_init.marker import MARKER_FILENAME, read_marker
from cc.core.project_migrate.known import Known
from cc.core.project_migrate.model import (
    DELETE, EDIT_JSON, EDIT_TEXT, UNLINK, MigrateError, MigrationPlan,
)
from cc.core.project_migrate.planner import plan_migration
from cc.core.project_migrate.util import atomic_write, sha256_bytes, sha256_file

MANIFEST = "manifest.json"
_INIT_FILES = (MARKER_FILENAME, "CLAUDE.md", "AGENTS.md", ".gitignore")


def default_backup_root() -> Path:
    env = os.environ.get("CC_MIGRATE_BACKUP_ROOT")
    return Path(env).expanduser() if env else Path.home() / ".copilot" / "migrations"


class _Recorder:
    def __init__(self, root: Path, backup: Path):
        self.root, self.backup = root, backup
        self.entries: list[dict[str, Any]] = []

    def snapshot(self, rel: str, kind: str) -> dict[str, Any]:
        path = self.root / rel
        entry: dict[str, Any] = {"path": rel, "kind": kind}
        if path.is_symlink():
            entry["link_target"] = os.readlink(path)
        elif path.is_file():
            slot = f"files/{len(self.entries):04d}/{rel}"
            dest = self.backup / slot
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            entry["backup"] = slot
            entry["sha_before"] = sha256_file(path)
            entry["mode"] = path.stat().st_mode & 0o7777
        else:
            entry["absent_before"] = True
        self.entries.append(entry)
        return entry

    def write_manifest(self, extra: dict[str, Any]) -> Path:
        manifest = {"project": str(self.root), "entries": self.entries, **extra}
        target = self.backup / MANIFEST
        atomic_write(target, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(), 0o644)
        return target


def _prune_empty(root: Path, rel: str) -> None:
    d = (root / rel).parent
    while d != root and d.is_dir():
        try:
            d.rmdir()
        except OSError:
            break
        d = d.parent


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)


def apply_migration(
    project: Path | str,
    *,
    plan: Optional[MigrationPlan] = None,
    known: Optional[Known] = None,
    backup_root: Optional[Path | str] = None,
    codex_config: Optional[Path | str] = None,
    packs_root: Optional[Path | str] = None,
    registry: Optional[Path | str] = None,
    commit_branch: Optional[str] = None,
) -> dict[str, Any]:
    """Apply the plan; returns the receipt. Leaves changes uncommitted unless `commit_branch`."""
    root = Path(project).expanduser().resolve()
    plan = plan or plan_migration(root, known=known)
    if plan.refused:
        raise MigrateError("dirty", "uncommitted changes on paths this plan would change: " + ", ".join(plan.dirty))
    drifted = [a.path for a in plan.actions
               if a.detail.get("sha") and not a.path.startswith("~")
               and sha256_file(root / a.path) != a.detail["sha"]]
    if drifted:
        raise MigrateError("drifted", "files changed since the plan was made: " + ", ".join(drifted))

    run_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    backup = Path(backup_root).expanduser() if backup_root else default_backup_root()
    backup = backup / root.name / run_id
    backup.mkdir(parents=True, exist_ok=True)
    rec = _Recorder(root, backup)
    head_before = _git(root, "rev-parse", "HEAD").stdout.strip() if plan.git else ""

    by_kind: dict[str, list[Any]] = {}
    for a in plan.actions:
        by_kind.setdefault(a.kind, []).append(a)
    # Retire the lock files last so a failure midway leaves the checksum record intact.
    deletes = sorted(by_kind.get(DELETE, []), key=lambda a: a.path in ("copilot.lock.json", ".codex-copilot.json"))
    removed_paths: list[str] = []
    try:
        for a in by_kind.get(UNLINK, []):
            rec.snapshot(a.path, "unlinked")
            (root / a.path).unlink()
            removed_paths.append(a.path)
        for a in deletes:
            rec.snapshot(a.path, "deleted")
            (root / a.path).unlink()
            removed_paths.append(a.path)
        for a in by_kind.get(EDIT_JSON, []):
            path = root / a.path
            new = plan.staged[a.path]
            entry = rec.snapshot(a.path, "modified")
            if a.detail.get("delete_file"):
                path.unlink()
                entry["kind"] = "deleted"
                removed_paths.append(a.path)
            else:
                atomic_write(path, new.encode())
                entry["sha_after"] = sha256_file(path)
        for a in by_kind.get(EDIT_TEXT, []):
            path = root / a.path
            entry = rec.snapshot(a.path, "modified")
            atomic_write(path, plan.staged[a.path].encode())
            entry["sha_after"] = sha256_file(path)
        for rel in removed_paths:
            _prune_empty(root, rel)

        # Project init: marker (with activePacks), thin sections, pack links, trust.
        init_entries = {rel: rec.snapshot(rel, "modified") for rel in _INIT_FILES}
        packs = next((a.detail.get("active_packs") for a in plan.actions if a.path == MARKER_FILENAME), None)
        if packs:
            marker = read_marker(root)
            marker["activePacks"] = packs
            atomic_write(root / MARKER_FILENAME,
                         (json.dumps(marker, indent=2, sort_keys=True) + "\n").encode(), 0o644)
        init = init_project(root, codex_config=codex_config, packs_root=packs_root, registry=registry)
        for rel, entry in init_entries.items():
            after = sha256_file(root / rel)
            if entry.get("absent_before"):
                if after is None:
                    rec.entries.remove(entry)
                else:
                    entry["kind"] = "created"
                    entry["sha_after"] = after
            elif after == entry.get("sha_before"):
                rec.entries.remove(entry)
            else:
                entry["sha_after"] = after
    except (InitError, OSError, ValueError) as exc:
        rec.write_manifest({"id": run_id, "status": "failed", "error": str(exc)})
        raise MigrateError("apply-failed", f"{exc}; roll back with the manifest in {backup}") from exc

    changed_paths = sorted({e["path"] for e in rec.entries})
    commit = ""
    branch = ""
    if commit_branch and plan.git:
        branch = commit_branch
        co = _git(root, "checkout", "-b", branch)
        if co.returncode != 0:
            raise MigrateError("git-branch", co.stderr.strip() or "git checkout -b failed")
        _git(root, "add", "-A", "--", *changed_paths)
        cm = _git(root, "commit", "-m", f"chore: migrate to central framework resolution ({run_id})",
                  "-m", "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
        if cm.returncode != 0:
            raise MigrateError("git-commit", cm.stderr.strip() or cm.stdout.strip())
        commit = _git(root, "rev-parse", "HEAD").stdout.strip()

    recovery = [f"cc project migrate {root} --rollback {backup}"]
    if plan.git and head_before:
        recovery.append(f"git -C {root} restore --source={head_before} --staged --worktree -- "
                        + " ".join(changed_paths[:5]) + (" ..." if len(changed_paths) > 5 else ""))
    receipt = {
        "id": run_id, "status": "applied", "backup_dir": str(backup), "head_before": head_before,
        "branch": branch, "commit": commit, "init": init, "changed": changed_paths,
        "counts": plan.counts(), "holds": [h.path for h in plan.holds], "recovery": recovery,
        "note": "Codex trust entry and project registry are machine state and are not reverted by rollback.",
    }
    rec.write_manifest(receipt)
    return receipt
