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
from cc.core.project_init.codex_trust import default_codex_config
from cc.core.project_init.marker import MARKER_FILENAME, read_marker, write_marker
from cc.core.project_init.registry import default_registry
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
    if env:
        return Path(env).expanduser()
    from cc.core.project_init.homes import copilot_home

    return copilot_home() / "migrations"


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

    def snapshot_external(self, path: Path) -> dict[str, Any]:
        """Machine-state file outside the project (Codex config, project registry, lock files)."""
        entry: dict[str, Any] = {"path": str(path), "kind": "external"}
        if path.is_file() and not path.is_symlink():
            slot = f"external/{len(self.entries):04d}/{path.name}"
            dest = self.backup / slot
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            entry["backup"] = slot
            entry["sha_before"] = sha256_file(path)
            entry["mode"] = path.stat().st_mode & 0o7777
        else:
            entry["absent_before"] = True
        entry["made_dirs"] = [str(d) for d in _missing_ancestors(path.parent)]
        self.entries.append(entry)
        return entry

    def write_manifest(self, extra: dict[str, Any]) -> Path:
        manifest = {"project": str(self.root), "entries": self.entries, **extra}
        target = self.backup / MANIFEST
        atomic_write(target, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(), 0o644)
        return target


def _missing_ancestors(directory: Path) -> list[Path]:
    """Directories on the way to `directory` that do not exist yet, shallowest first."""
    out: list[Path] = []
    d = directory
    while not (d.exists() or d.is_symlink()) and d != d.parent:
        out.append(d)
        d = d.parent
    return out[::-1]


def _pack_dirs(root: Path, packs: list[dict[str, Any]]) -> list[Path]:
    """The skills folders project init links pack skills into (derived from activePacks)."""
    out: list[Path] = []
    for pack in packs:
        if isinstance(pack, dict):
            d = Path(os.path.normpath(root / str(pack.get("activatedBy") or ".") / "skills"))
            if d not in out and _is_inside(d, root):
                out.append(d)
    return out


def _link_state(dirs: list[Path]) -> dict[str, str]:
    state: dict[str, str] = {}
    for d in dirs:
        if d.is_dir():
            for child in d.iterdir():
                if child.is_symlink():
                    state[str(child)] = os.readlink(child)
    return state


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


def _nearest_existing(path: Path) -> Path:
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def _preflight(root: Path, plan: MigrationPlan, backup: Path, commit_branch: Optional[str]) -> None:
    """Check every apply precondition before the first write."""
    if commit_branch and plan.git:
        if _git(root, "check-ref-format", "--branch", commit_branch).returncode != 0:
            raise MigrateError("git-branch", f"'{commit_branch}' is not a valid branch name; nothing was changed")
        if _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{commit_branch}").returncode == 0:
            raise MigrateError("git-branch", f"branch '{commit_branch}' already exists; choose another name. "
                                             "Nothing was changed")
        if _git(root, "rev-parse", "--verify", "--quiet", "HEAD").returncode != 0:
            raise MigrateError("git-branch", "the repository has no commit to branch from; nothing was changed")
    seen: set[str] = set()
    for a in plan.actions:
        if a.kind in (DELETE, UNLINK, EDIT_JSON, EDIT_TEXT):
            gone = a.kind in (DELETE, UNLINK) and not (root / a.path).is_symlink() and not (root / a.path).is_file()
            if a.path in seen or gone:
                raise MigrateError("plan-stale", f"the plan is not applicable ({a.path} is "
                                   f"{'planned twice' if a.path in seen else 'missing'}); nothing was changed")
            seen.add(a.path)
    unwritable: list[str] = []
    init_files = (MARKER_FILENAME,) if plan.source_repo else _INIT_FILES
    targets = {a.path for a in plan.actions if not a.path.startswith("~")} | set(init_files)
    for rel in sorted(targets):
        path = root / rel
        parent = path.parent if (path.exists() or path.is_symlink() or rel in _INIT_FILES) else _nearest_existing(path.parent)
        if not os.access(parent, os.W_OK | os.X_OK) or (path.is_file() and not os.access(path, os.R_OK)):
            unwritable.append(rel)
    if unwritable:
        raise MigrateError("not-writable", "cannot write: " + ", ".join(unwritable) + "; nothing was changed")
    anchor = _nearest_existing(backup.parent)
    if not anchor.is_dir() or not os.access(anchor, os.W_OK | os.X_OK):
        raise MigrateError("backup-unwritable", f"backup location {backup} is not writable; nothing was changed")
    if _is_inside(backup, root):
        raise MigrateError("backup-inside-project", f"backup location {backup} is inside the project; "
                                                    "nothing was changed")


def _is_inside(path: Path, root: Path) -> bool:
    try:
        Path(os.path.realpath(path)).relative_to(os.path.realpath(root))
        return True
    except ValueError:
        return False


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
    allow_missing_codex: bool = False,
    source_repo: bool = False,
    release_dir: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Apply the plan; returns the receipt. Leaves changes uncommitted unless `commit_branch`.

    Every precondition is checked before the first write. Any failure after that point
    rolls the project back from the manifest before the error is raised.
    """
    root = Path(project).expanduser().resolve()
    plan = plan or plan_migration(root, known=known, allow_missing_codex=allow_missing_codex,
                                  source_repo=source_repo, release_dir=release_dir)
    if plan.errors:
        raise MigrateError("plan-error", "; ".join(plan.errors))
    if plan.dirty:
        raise MigrateError("dirty", "uncommitted changes on paths this plan would change: " + ", ".join(plan.dirty))
    drifted = [a.path for a in plan.actions
               if a.detail.get("sha") and not a.path.startswith("~")
               and sha256_file(root / a.path) != a.detail["sha"]]
    if drifted:
        raise MigrateError("drifted", "files changed since the plan was made: " + ", ".join(drifted))

    run_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    backup = Path(backup_root).expanduser() if backup_root else default_backup_root()
    backup = backup / root.name / run_id
    _preflight(root, plan, backup, commit_branch)
    backup.mkdir(parents=True, exist_ok=True)
    rec = _Recorder(root, backup)
    head_before = _git(root, "rev-parse", "HEAD").stdout.strip() if plan.git else ""
    start_branch = _git(root, "branch", "--show-current").stdout.strip() if plan.git else ""
    created_branch = False

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
        init_files = (MARKER_FILENAME,) if plan.source_repo else _INIT_FILES
        init_entries = {rel: rec.snapshot(rel, "modified") for rel in init_files}
        packs = next((a.detail.get("active_packs") for a in plan.actions if a.path == MARKER_FILENAME), None)
        if packs:
            marker = read_marker(root)
            marker["activePacks"] = packs
            atomic_write(root / MARKER_FILENAME, (json.dumps(marker, indent=2, sort_keys=True) + "\n").encode(),
                         init_entries[MARKER_FILENAME].get("mode", 0o644))
        cfg = Path(codex_config).expanduser() if codex_config else default_codex_config()
        reg = Path(registry).expanduser() if registry else default_registry()
        pack_dirs = [] if plan.source_repo else _pack_dirs(root, read_marker(root).get("activePacks") or [])
        dirs_before = {d: d.is_dir() for d in pack_dirs}
        made_dirs = [d for pd in pack_dirs for d in _missing_ancestors(pd)]
        links_before = _link_state(pack_dirs)
        externals = {} if plan.source_repo else {p: rec.snapshot_external(p) for p in (
            cfg, cfg.with_name(cfg.name + ".bak"), cfg.with_name(cfg.name + ".lock"),
            reg, reg.with_name(reg.name + ".lock"))}
        if plan.source_repo:  # marker only: the repo's own CLAUDE.md/AGENTS.md, .gitignore and trust are not ours
            init = {"result": "changed" if write_marker(root) else "unchanged", "project": str(root),
                    "changed": [MARKER_FILENAME], "source_repo": True}
        else:
            init = init_project(root, codex_config=cfg, packs_root=packs_root, registry=reg)
        for path, entry in externals.items():
            after = sha256_file(path)
            if after == entry.get("sha_before") and (after is not None or entry.get("absent_before")) \
                    and not entry["made_dirs"]:
                rec.entries.remove(entry)
            else:
                entry["sha_after"] = after
        for d in dict.fromkeys(made_dirs):
            if d.is_dir():
                rec.entries.append({"path": d.relative_to(root).as_posix(), "kind": "created-dir"})
        for link, target in sorted(_link_state(pack_dirs).items()):
            before = links_before.get(link)
            if before != target:
                rec.entries.append({"path": Path(link).relative_to(root).as_posix(), "kind": "created-link",
                                    "link_after": target, "link_before": before})
        for rel, entry in init_entries.items():
            if "mode" in entry and (root / rel).is_file() and not (root / rel).is_symlink():
                os.chmod(root / rel, entry["mode"])  # project init writes through temp files: keep the file's own mode
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

        changed_paths = sorted({e["path"] for e in rec.entries
                                if e["kind"] not in ("external", "created-dir", "created-link")})
        commit = ""
        branch = ""
        if commit_branch and plan.git:
            branch = commit_branch
            co = _git(root, "checkout", "-b", branch)
            if co.returncode != 0:
                raise MigrateError("git-branch", co.stderr.strip() or "git checkout -b failed")
            created_branch = True
            _git(root, "add", "-A", "--", *changed_paths)
            cm = _git(root, "commit", "-m", f"chore: migrate to central framework resolution ({run_id})",
                      "-m", "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
            if cm.returncode != 0:
                raise MigrateError("git-commit", cm.stderr.strip() or cm.stdout.strip())
            commit = _git(root, "rev-parse", "HEAD").stdout.strip()
    except Exception as exc:  # noqa: BLE001 - any mid-apply failure must undo the writes
        rec.write_manifest({"id": run_id, "status": "failed", "error": str(exc)})
        if created_branch:
            _git(root, "checkout", start_branch or head_before)
            _git(root, "branch", "-D", commit_branch or "")
        try:
            from cc.core.project_migrate.rollback import rollback_migration

            result = rollback_migration(backup)
            tail = (f"rolled back automatically ({len(result['restored'])} restored"
                    + (f", conflicts: {result['conflicts']}" if result["conflicts"] else "") + ")")
        except Exception as rb:  # noqa: BLE001
            tail = f"AUTOMATIC ROLLBACK FAILED ({rb}); roll back with the manifest in {backup}"
        code = exc.code if isinstance(exc, MigrateError) else "apply-failed"
        raise MigrateError(code, f"{getattr(exc, 'message', exc)}; {tail}") from exc

    recovery = [f"cc project migrate {root} --rollback --manifest {backup}"]
    if plan.git and head_before:
        recovery.append(f"git -C {root} restore --source={head_before} --staged --worktree -- "
                        + " ".join(changed_paths[:5]) + (" ..." if len(changed_paths) > 5 else ""))
    receipt = {
        "id": run_id, "status": "applied", "backup_dir": str(backup), "head_before": head_before,
        "branch": branch, "commit": commit, "init": init, "changed": changed_paths,
        "counts": plan.counts(), "holds": [{"path": h.path, "reason": h.reason} for h in plan.holds], "recovery": recovery,
        "note": "Rollback also reverts the Codex trust entry and project registry entry made by this run.",
    }
    rec.write_manifest(receipt)
    return receipt
