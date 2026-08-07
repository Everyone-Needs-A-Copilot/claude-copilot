"""Deterministic, fail-closed migrations for recognized project integrations.

The project-integration inspector intentionally routes project-owned ambiguity to
``guided-integration``.  This module narrows a subset of those rows back down to
versioned, reversible transformations whose preconditions can be proven without
a model.  Planning is read-only.  Applying requires the exact opaque action id,
re-inspects immediately before mutation, refuses dirty Git trees, and verifies
the targeted component independently before reporting success.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from cc.core.config import resolve_key
from cc.core.ecosystem.project_integration import inspect_project_integration
from cc.core.ecosystem.projects import PROJECT_LOCK_FILENAME, read_project_lock

MIGRATION_SCHEMA_VERSION = "1.1"
CLAUDE_ENTRY_KIND = "claude-canonical-entry-v1"
CODEX_PORTABLE_KIND = "codex-portable-copy-v1"

_CLAUDE_ENTRY_BLOCK = (
    "<!-- cc:project-integration:claude:v1:start -->\n"
    "## Claude Copilot\n\n"
    "This project uses the shared Claude Copilot framework. Preserve the "
    "project-specific instructions in this file and the installed `.claude/` "
    "capabilities.\n"
    "<!-- cc:project-integration:claude:v1:end -->\n"
)

Run = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


def _run(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)


def _opaque_id(payload: Any) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _bytes_checksum(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _file_checksum(path: Path) -> str:
    return _bytes_checksum(path.read_bytes())


def _git_state(root: Path, *, run: Run = _run) -> tuple[Optional[dict[str, Any]], str]:
    top = run(("git", "rev-parse", "--show-toplevel"), root)
    if top.returncode != 0:
        return None, "This folder is not a readable Git working tree."
    try:
        top_level = Path(top.stdout.strip()).resolve()
    except OSError:
        return None, "The Git working-tree root could not be resolved safely."
    if top_level != root:
        return None, "The selected folder is not the Git working-tree root."

    status_result = run(
        ("git", "status", "--porcelain=v1", "--untracked-files=all"), root
    )
    if status_result.returncode != 0:
        return None, "The Git working tree could not be checked safely."
    status_lines = [line for line in status_result.stdout.splitlines() if line]

    head_result = run(("git", "rev-parse", "HEAD"), root)
    head = head_result.stdout.strip() if head_result.returncode == 0 else None
    return {
        "head": head,
        "clean": not status_lines,
        "change_count": len(status_lines),
    }, ""


def _component_variant(workspace: dict[str, Any], component: str) -> Optional[str]:
    for item in workspace.get("components", []):
        if item.get("component") != component:
            continue
        recognized = item.get("recognized_setup")
        if isinstance(recognized, dict):
            variant = recognized.get("variant_id")
            return variant if isinstance(variant, str) else None
    return None


def _configured_source(
    component: str, supplied: Optional[Path | str]
) -> Optional[Path]:
    raw: Any = supplied
    if raw is None:
        raw = resolve_key(f"paths.{component}_copilot_root")
    if not raw:
        return None
    candidate = Path(str(raw)).expanduser()
    try:
        if candidate.is_symlink() or not candidate.is_dir():
            return None
        return candidate.resolve()
    except OSError:
        return None


def _path_fingerprint(path: Path) -> list[Any]:
    try:
        if path.is_symlink():
            return ["symlink", str(path.readlink())]
        if not path.exists():
            return ["missing"]
        if path.is_file():
            return ["file", _file_checksum(path), stat.S_IMODE(path.stat().st_mode)]
        return ["unsupported"]
    except OSError:
        return ["unreadable"]


def _diagnostic_inspection(
    workspace: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Reduce authoritative inspection evidence without copying file contents."""
    if not isinstance(workspace, dict):
        return None
    inspection = workspace.get("inspection")
    components: list[dict[str, Any]] = []
    for item in workspace.get("components", []):
        if not isinstance(item, dict):
            continue
        recognized = item.get("recognized_setup")
        recognized_record = None
        if isinstance(recognized, dict):
            recognized_record = {
                "variant_id": recognized.get("variant_id"),
                "version": recognized.get("version"),
                "evidence": [
                    {
                        "kind": evidence.get("kind"),
                        "path": evidence.get("path"),
                        "state": evidence.get("state"),
                        "detail": evidence.get("detail"),
                    }
                    for evidence in recognized.get("evidence", [])
                    if isinstance(evidence, dict)
                ],
            }
        components.append(
            {
                "component": item.get("component"),
                "classification": item.get("classification"),
                "recognized_setup": recognized_record,
                "missing_requirements": [
                    {
                        "id": requirement.get("id"),
                        "detail": requirement.get("detail"),
                    }
                    for requirement in item.get("missing_requirements", [])
                    if isinstance(requirement, dict)
                ],
            }
        )
    return {
        "inspection_id": inspection.get("id") if isinstance(inspection, dict) else None,
        "classification": workspace.get("classification"),
        "components": components,
    }


def _diagnostic_snapshot(
    path: Path, root: Path, snapshot: "_Snapshot"
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": path.relative_to(root).as_posix(),
        "kind": snapshot.kind,
        "mode": snapshot.mode,
    }
    if snapshot.kind == "file":
        record["checksum"] = _bytes_checksum(bytes(snapshot.payload or b""))
    elif snapshot.kind == "symlink":
        record["target"] = str(snapshot.payload)
    return record


def _parents_are_local(root: Path, target: Path) -> bool:
    current = target.parent
    while current != root:
        try:
            if current.is_symlink():
                return False
        except OSError:
            return False
        if root not in current.parents:
            return False
        current = current.parent
    return True


def _codex_source_snapshot(source: Path) -> tuple[Optional[dict[str, Any]], str]:
    plugin = source / "plugins/codex-copilot"
    gate = source / "scripts/copilot-gate.sh"
    manifest = plugin / ".codex-plugin/plugin.json"
    try:
        if plugin.is_symlink() or not plugin.is_dir():
            return None, "The authoritative Codex plugin source is unavailable."
        if gate.is_symlink() or not gate.is_file():
            return None, "The authoritative Codex verification gate is unavailable."
        raw_manifest: Any = json.loads(manifest.read_text(encoding="utf-8"))
        if (
            not isinstance(raw_manifest, dict)
            or raw_manifest.get("name") != "codex-copilot"
        ):
            return None, "The authoritative Codex plugin manifest is invalid."

        files: list[list[str]] = []
        for candidate in sorted(plugin.rglob("*")):
            if candidate.is_symlink():
                return None, "The authoritative Codex plugin contains a symlink."
            if candidate.is_file():
                files.append(
                    [
                        candidate.relative_to(plugin).as_posix(),
                        _file_checksum(candidate),
                    ]
                )
        if not files:
            return None, "The authoritative Codex plugin is empty."
        return {
            "source": str(source),
            "plugin": str(plugin),
            "gate": str(gate),
            "version": raw_manifest.get("version", "unknown"),
            "fingerprint": _opaque_id(
                {
                    "files": files,
                    "gate": _file_checksum(gate),
                    "version": raw_manifest.get("version"),
                }
            ),
        }, ""
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None, "The authoritative Codex source could not be inspected safely."


def _codex_project_preflight(
    root: Path, source: Path
) -> tuple[Optional[dict[str, Any]], str]:
    plugin = root / "plugins/codex-copilot"
    bridge = root / ".claude/skills/codex-copilot"
    gate = root / "scripts/copilot-gate.sh"
    config_path = root / ".codex-copilot.json"
    lock_path = root / PROJECT_LOCK_FILENAME
    if not all(
        _parents_are_local(root, target)
        for target in (plugin, bridge, gate, config_path, lock_path)
    ):
        return None, "A migration target has a symlinked parent outside the project."
    try:
        if not plugin.is_symlink() or not bridge.is_symlink():
            return None, "The recognized legacy Codex links changed before migration."
        if config_path.is_symlink() or not config_path.is_file():
            return None, "The legacy Codex install metadata is not a local file."
        config: Any = json.loads(config_path.read_text(encoding="utf-8"))
        if not (
            isinstance(config, dict)
            and config.get("installType") == "symlink"
            and config.get("pluginPath") == "./plugins/codex-copilot"
        ):
            return None, "The legacy Codex install metadata changed before migration."

        source_gate = source / "scripts/copilot-gate.sh"
        gate_mode = "missing"
        if gate.is_symlink():
            gate_mode = "legacy-link"
        elif gate.exists():
            if not gate.is_file() or _file_checksum(gate) != _file_checksum(
                source_gate
            ):
                return (
                    None,
                    "This project's setup check is customized, so Control Tower left it alone.",
                )
            gate_mode = "current-file"

        if lock_path.is_symlink():
            return None, "The project lock is a symlink and was left alone."
        lock = read_project_lock(lock_path)
        if lock and (
            lock.get("schema_version") != "1.0"
            or not isinstance(lock.get("components"), list)
        ):
            return None, "The project lock uses an unsupported format."
        return {
            "gate_mode": gate_mode,
            "config": config,
            "fingerprint": {
                "plugin": _path_fingerprint(plugin),
                "bridge": _path_fingerprint(bridge),
                "gate": _path_fingerprint(gate),
                "config": _path_fingerprint(config_path),
                "lock": _path_fingerprint(lock_path),
            },
        }, ""
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None, "The recognized legacy Codex setup could not be inspected safely."


def build_migration_candidate(
    project: Path | str,
    workspace: dict[str, Any],
    *,
    claude_root: Optional[Path | str] = None,
    codex_root: Optional[Path | str] = None,
    run: Run = _run,
) -> dict[str, Any]:
    """Build one content-free migration census row without mutating the project."""
    root = Path(project).expanduser().resolve()
    classification = workspace.get("classification")
    base = {
        "path": str(root),
        "name": root.name,
        "classification": classification,
        "inspection_id": workspace.get("inspection", {}).get("id"),
        "migration_kinds": [],
        "state": "not-needed",
        "automatable": False,
        "reason_code": "not-guided",
        "detail": "This project does not currently need a grouped update.",
        "action": None,
        "verification": {
            "command": [
                "cc",
                "workspace",
                "verify",
                "--project",
                str(root),
                "--json",
            ],
            "expected": "Every migrated component classifies Ready from machine-verifiable evidence.",
        },
    }
    if classification != "guided-integration":
        return base

    variants = {
        component: _component_variant(workspace, component)
        for component in ("claude", "codex")
    }
    kinds: list[str] = []
    will_change: list[dict[str, str]] = []
    stable: dict[str, Any] = {
        "project": str(root),
        "inspection_id": base["inspection_id"],
        "contract": MIGRATION_SCHEMA_VERSION,
    }
    hold_code: Optional[str] = None
    hold_detail = ""

    git_state, git_error = _git_state(root, run=run)
    if git_state is None:
        hold_code, hold_detail = "git-unreadable", git_error
    elif not git_state["clean"]:
        hold_code = "dirty-working-tree"
        hold_detail = f"This project has {git_state['change_count']} local change(s), so Control Tower left it alone."
    stable["git"] = git_state

    if variants["claude"] == "claude-legacy-entry-v1":
        kinds.append(CLAUDE_ENTRY_KIND)
        claude_path = root / "CLAUDE.md"
        if claude_path.is_symlink():
            hold_code = hold_code or "claude-entry-symlink"
            hold_detail = hold_detail or "CLAUDE.md is a symlink and was left alone."
        else:
            will_change.append(
                {
                    "path": "CLAUDE.md",
                    "operation": "create-bounded-entry"
                    if not claude_path.exists()
                    else "append-bounded-entry",
                }
            )
            stable["claude_entry"] = _path_fingerprint(claude_path)

    if variants["codex"] == "codex-legacy-linked-v1":
        kinds.append(CODEX_PORTABLE_KIND)
        source = _configured_source("codex", codex_root)
        if source is None:
            hold_code = hold_code or "codex-source-unavailable"
            hold_detail = (
                hold_detail or "The authoritative Codex source is unavailable."
            )
        else:
            source_snapshot, source_error = _codex_source_snapshot(source)
            project_snapshot, project_error = _codex_project_preflight(root, source)
            if source_snapshot is None:
                hold_code = hold_code or "codex-source-unavailable"
                hold_detail = hold_detail or source_error
            elif project_snapshot is None:
                hold_code = hold_code or "codex-project-conflict"
                hold_detail = hold_detail or project_error
            else:
                stable["codex_source"] = source_snapshot["fingerprint"]
                stable["codex_project"] = project_snapshot["fingerprint"]
                will_change.extend(
                    [
                        {
                            "path": "plugins/codex-copilot",
                            "operation": "replace-recognized-link-with-portable-copy",
                        },
                        {
                            "path": ".claude/skills/codex-copilot",
                            "operation": "replace-recognized-link-with-project-local-bridge",
                        },
                        {
                            "path": ".codex-copilot.json",
                            "operation": "record-portable-copy",
                        },
                        {
                            "path": PROJECT_LOCK_FILENAME,
                            "operation": "refresh-codex-lock-entry",
                        },
                    ]
                )
                if project_snapshot["gate_mode"] != "current-file":
                    will_change.append(
                        {
                            "path": "scripts/copilot-gate.sh",
                            "operation": "install-project-local-gate",
                        }
                    )

    base["migration_kinds"] = kinds
    if not kinds:
        base.update(
            {
                "state": "residual-guidance",
                "reason_code": "no-deterministic-migration",
                "detail": (
                    "This project needs a tailored setup plan. Control Tower did not find a proven automatic update for it."
                ),
            }
        )
        return base
    if hold_code:
        base.update(
            {
                "state": "held",
                "reason_code": hold_code,
                "detail": hold_detail,
            }
        )
        return base

    stable["migration_kinds"] = kinds
    stable["will_change"] = will_change
    action_id = _opaque_id(stable)
    base.update(
        {
            "state": "eligible",
            "automatable": True,
            "reason_code": None,
            "detail": (
                "Control Tower can update this project's recognized older setup without replacing its instructions or tools. Nothing has changed yet."
            ),
            "action": {
                "id": action_id,
                "inspection_id": base["inspection_id"],
                "migration_kinds": kinds,
                "will_change": will_change,
                "will_preserve": workspace.get("preservation", {}).get(
                    "must_preserve", []
                ),
                "will_not_do": workspace.get("preservation", {}).get(
                    "prohibited_actions", []
                ),
            },
        }
    )
    return base


def build_migration_report(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    guided = [
        item for item in candidates if item["classification"] == "guided-integration"
    ]
    summary = {
        state: sum(item["state"] == state for item in guided)
        for state in ("eligible", "held", "residual-guidance")
    }
    summary["total_guided"] = len(guided)
    stable = [
        {
            "path": item["path"],
            "inspection_id": item["inspection_id"],
            "state": item["state"],
            "action_id": item["action"]["id"] if item["action"] else None,
            "reason_code": item["reason_code"],
        }
        for item in candidates
    ]
    plan_id = _opaque_id(
        {"schema_version": MIGRATION_SCHEMA_VERSION, "candidates": stable}
    )
    result = (
        "action-required" if summary["eligible"] else ("blocked" if guided else "ready")
    )
    return {
        "schema_version": MIGRATION_SCHEMA_VERSION,
        "mode": "plan",
        "result": result,
        "plan_id": plan_id,
        "summary": summary,
        "candidates": candidates,
        "ledger": [],
    }


@dataclass(frozen=True)
class _Snapshot:
    kind: str
    payload: Optional[bytes | str]
    mode: Optional[int]


def _capture(path: Path) -> _Snapshot:
    if path.is_symlink():
        return _Snapshot("symlink", str(path.readlink()), None)
    if not path.exists():
        return _Snapshot("missing", None, None)
    if path.is_file():
        return _Snapshot("file", path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
    raise OSError(f"unsupported migration target: {path}")


def _remove_target(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _atomic_write(path: Path, payload: bytes, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.cc-", dir=path.parent
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.chmod(mode)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _create_missing_parents(target: Path, root: Path) -> list[Path]:
    """Create the directories `target` needs, deepest last.

    Returns only the directories this call created, so a rollback can remove
    exactly those and leave pre-existing project directories alone.
    """
    missing: list[Path] = []
    parent = target.parent
    while parent != root and root in parent.parents and not parent.exists():
        missing.append(parent)
        parent = parent.parent
    created: list[Path] = []
    for directory in reversed(missing):
        directory.mkdir()
        created.append(directory)
    return created


def _restore(path: Path, snapshot: _Snapshot) -> None:
    _remove_target(path)
    if snapshot.kind == "missing":
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if snapshot.kind == "symlink":
        path.symlink_to(str(snapshot.payload))
    elif snapshot.kind == "file":
        _atomic_write(path, bytes(snapshot.payload or b""), mode=snapshot.mode or 0o644)


def _installed_codex_files(root: Path) -> list[dict[str, str]]:
    plugin = root / "plugins/codex-copilot"
    paths = [
        *sorted(path for path in plugin.rglob("*") if path.is_file()),
        root / "scripts/copilot-gate.sh",
    ]
    files: list[dict[str, str]] = []
    for path in paths:
        if not path.is_file():
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "ownership": "framework",
                "checksum": _file_checksum(path),
            }
        )
    return files


def _codex_lock_payload(root: Path, version: str) -> bytes:
    lock_path = root / PROJECT_LOCK_FILENAME
    existing = read_project_lock(lock_path)
    entries = [
        entry
        for entry in existing.get("components", [])
        if isinstance(entry, dict) and entry.get("component") != "codex"
    ]
    entries.append(
        {
            "component": "codex",
            "version": version,
            "release_tag": None if version == "unknown" else f"v{version}",
            "files": _installed_codex_files(root),
        }
    )
    entries.sort(key=lambda item: str(item.get("component", "")))
    return (
        json.dumps(
            {"schema_version": "1.0", "components": entries},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _append_claude_entry(path: Path) -> None:
    if path.exists():
        current = path.read_text(encoding="utf-8")
        separator = (
            ""
            if current.endswith("\n\n")
            else ("\n" if current.endswith("\n") else "\n\n")
        )
        payload = (current + separator + _CLAUDE_ENTRY_BLOCK).encode("utf-8")
        mode = stat.S_IMODE(path.stat().st_mode)
    else:
        payload = _CLAUDE_ENTRY_BLOCK.encode("utf-8")
        mode = 0o644
    _atomic_write(path, payload, mode=mode)


def apply_migration_action(
    project: Path | str,
    action_id: str,
    *,
    claude_root: Optional[Path | str] = None,
    codex_root: Optional[Path | str] = None,
    run: Run = _run,
    fail_after: Optional[int] = None,
) -> dict[str, Any]:
    """Apply one exact migration action and return its truthful action ledger."""
    from cc.core.ecosystem.workspaces import workspace_status

    root = Path(project).expanduser().resolve()
    workspace = workspace_status(
        root,
        claude_root=claude_root,
        codex_root=codex_root,
        detail=True,
    )
    candidate = build_migration_candidate(
        root,
        workspace,
        claude_root=claude_root,
        codex_root=codex_root,
        run=run,
    )
    action = candidate.get("action")
    diagnostic: dict[str, Any] = {
        "project": str(root),
        "action_id": action_id,
        "preflight": {
            "inspection_id": candidate.get("inspection_id"),
            "classification": candidate.get("classification"),
            "state": candidate.get("state"),
            "automatable": candidate.get("automatable"),
            "reason_code": candidate.get("reason_code"),
            "migration_kinds": candidate.get("migration_kinds", []),
            "git": _git_state(root, run=run)[0],
            "inspection": _diagnostic_inspection(workspace),
        },
        "targets_before": [],
        "source": None,
        "completed_operations": [],
        "verification_after_apply": None,
        "rollback": [],
        "verification_after_rollback": None,
    }
    if not candidate["automatable"] or not action or action["id"] != action_id:
        return {
            "path": str(root),
            "name": root.name,
            "action_id": action_id,
            "status": "blocked",
            "detail": "This migration action is stale or no longer safe. Nothing was changed.",
            "completed_actions": [],
            "verification": "not-run",
            "_diagnostic": diagnostic,
        }

    kinds = list(action["migration_kinds"])
    target_paths: list[Path] = []
    if CLAUDE_ENTRY_KIND in kinds:
        target_paths.append(root / "CLAUDE.md")
    if CODEX_PORTABLE_KIND in kinds:
        target_paths.extend(
            [
                root / "plugins/codex-copilot",
                root / ".claude/skills/codex-copilot",
                root / "scripts/copilot-gate.sh",
                root / ".codex-copilot.json",
                root / PROJECT_LOCK_FILENAME,
            ]
        )

    try:
        snapshots = {path: _capture(path) for path in target_paths}
    except OSError:
        return {
            "path": str(root),
            "name": root.name,
            "action_id": action_id,
            "status": "blocked",
            "detail": "A bounded migration target could not be backed up. Nothing was changed.",
            "completed_actions": [],
            "verification": "not-run",
            "_diagnostic": diagnostic,
        }
    diagnostic["targets_before"] = [
        _diagnostic_snapshot(path, root, snapshots[path]) for path in target_paths
    ]

    completed: list[dict[str, str]] = []
    created_directories: list[Path] = []
    mutation_count = 0

    def recorded(path: Path, operation: str) -> None:
        nonlocal mutation_count
        completed.append(
            {
                "path": path.relative_to(root).as_posix(),
                "operation": operation,
                "status": "applied",
            }
        )
        diagnostic["completed_operations"] = list(completed)
        mutation_count += 1
        if fail_after is not None and mutation_count >= fail_after:
            raise OSError("injected migration failure")

    try:
        with tempfile.TemporaryDirectory(prefix="cc-project-migrate-") as temporary:
            stage = Path(temporary)
            source_snapshot: Optional[dict[str, Any]] = None
            staged_plugin: Optional[Path] = None
            staged_gate: Optional[Path] = None
            if CODEX_PORTABLE_KIND in kinds:
                source = _configured_source("codex", codex_root)
                if source is None:
                    raise OSError("Codex source disappeared after preflight")
                source_snapshot, source_error = _codex_source_snapshot(source)
                if source_snapshot is None:
                    raise OSError(source_error)
                diagnostic["source"] = {
                    "path": source_snapshot.get("source"),
                    "version": source_snapshot.get("version"),
                    "fingerprint": source_snapshot.get("fingerprint"),
                }
                staged_plugin = stage / "plugins/codex-copilot"
                staged_plugin.parent.mkdir(parents=True)
                shutil.copytree(source / "plugins/codex-copilot", staged_plugin)
                staged_gate = stage / "scripts/copilot-gate.sh"
                staged_gate.parent.mkdir(parents=True)
                shutil.copy2(source / "scripts/copilot-gate.sh", staged_gate)
                staged_snapshot, staged_error = _codex_source_snapshot(stage)
                if (
                    staged_snapshot is None
                    or staged_snapshot["fingerprint"] != source_snapshot["fingerprint"]
                ):
                    raise OSError(
                        staged_error
                        or "The authoritative Codex source changed while it was staged."
                    )
                source_snapshot = staged_snapshot

            if CLAUDE_ENTRY_KIND in kinds:
                claude_path = root / "CLAUDE.md"
                _append_claude_entry(claude_path)
                recorded(claude_path, "write-bounded-claude-entry")

            if CODEX_PORTABLE_KIND in kinds:
                assert source_snapshot is not None
                assert staged_plugin is not None
                assert staged_gate is not None
                plugin = root / "plugins/codex-copilot"
                bridge = root / ".claude/skills/codex-copilot"
                gate = root / "scripts/copilot-gate.sh"
                config_path = root / ".codex-copilot.json"
                lock_path = root / PROJECT_LOCK_FILENAME

                _remove_target(plugin)
                shutil.copytree(staged_plugin, plugin)
                recorded(plugin, "install-portable-codex-plugin")

                _remove_target(bridge)
                created_directories.extend(_create_missing_parents(bridge, root))
                relative = os.path.relpath(plugin / "skills", bridge.parent)
                bridge.symlink_to(relative, target_is_directory=True)
                recorded(bridge, "install-project-local-skill-bridge")

                source_gate = Path(source_snapshot["gate"])
                if snapshots[gate].kind != "file" or _file_checksum(
                    gate
                ) != _file_checksum(source_gate):
                    _remove_target(gate)
                    created_directories.extend(_create_missing_parents(gate, root))
                    shutil.copy2(staged_gate, gate)
                    recorded(gate, "install-project-local-gate")

                config = json.loads(
                    bytes(snapshots[config_path].payload or b"{}").decode("utf-8")
                )
                config["installType"] = "copy"
                config["pluginPath"] = "./plugins/codex-copilot"
                _atomic_write(
                    config_path,
                    (json.dumps(config, indent=2, sort_keys=True) + "\n").encode(
                        "utf-8"
                    ),
                    mode=snapshots[config_path].mode or 0o644,
                )
                recorded(config_path, "record-portable-copy")

                _atomic_write(
                    lock_path,
                    _codex_lock_payload(root, str(source_snapshot["version"])),
                    mode=snapshots[lock_path].mode or 0o644,
                )
                recorded(lock_path, "refresh-codex-lock-entry")

        after = inspect_project_integration(
            root,
            claude_root=claude_root,
            codex_root=codex_root,
            detail=True,
        )
        diagnostic["verification_after_apply"] = _diagnostic_inspection(after)
        by_component = {
            item["component"]: item["classification"] for item in after["components"]
        }
        targeted = []
        if CLAUDE_ENTRY_KIND in kinds:
            targeted.append("claude")
        if CODEX_PORTABLE_KIND in kinds:
            targeted.append("codex")
        if any(by_component.get(component) != "ready" for component in targeted):
            raise OSError(
                "The migrated component did not pass independent verification"
            )
        return {
            "path": str(root),
            "name": root.name,
            "action_id": action_id,
            "status": "applied",
            "detail": "Control Tower updated this project and its independent check passed.",
            "completed_actions": completed,
            "verification": "ready",
            "after_inspection_id": after["inspection"]["id"],
            "targeted_components": targeted,
            "_diagnostic": diagnostic,
        }
    except (OSError, shutil.Error, json.JSONDecodeError, UnicodeDecodeError) as exc:
        diagnostic["exception"] = {
            "type": type(exc).__name__,
            "message": str(exc)[:2000],
        }
        if diagnostic["verification_after_apply"] is None and completed:
            try:
                diagnostic["verification_after_apply"] = _diagnostic_inspection(
                    inspect_project_integration(
                        root,
                        claude_root=claude_root,
                        codex_root=codex_root,
                        detail=True,
                    )
                )
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as verify_exc:
                diagnostic["verification_after_apply"] = {
                    "error_type": type(verify_exc).__name__,
                    "detail": "The post-change inspection could not be completed.",
                }
        restoration_failed = False
        for path in reversed(target_paths):
            try:
                _restore(path, snapshots[path])
                diagnostic["rollback"].append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "restored": True,
                    }
                )
            except OSError as restore_exc:
                restoration_failed = True
                diagnostic["rollback"].append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "restored": False,
                        "error_type": type(restore_exc).__name__,
                        "detail": "The saved target could not be restored.",
                    }
                )
        for directory in sorted(
            set(created_directories), key=lambda item: len(item.parts), reverse=True
        ):
            try:
                directory.rmdir()
            except OSError:
                # Keep any directory that is no longer empty; it holds project work.
                continue
        try:
            diagnostic["verification_after_rollback"] = _diagnostic_inspection(
                inspect_project_integration(
                    root,
                    claude_root=claude_root,
                    codex_root=codex_root,
                    detail=True,
                )
            )
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as verify_exc:
            diagnostic["verification_after_rollback"] = {
                "error_type": type(verify_exc).__name__,
                "detail": "The restored project could not be re-inspected.",
            }
        rolled_back = [{**item, "status": "rolled-back"} for item in completed]
        targeted = []
        if CLAUDE_ENTRY_KIND in kinds:
            targeted.append("claude")
        if CODEX_PORTABLE_KIND in kinds:
            targeted.append("codex")
        return {
            "path": str(root),
            "name": root.name,
            "action_id": action_id,
            "status": "rolled-back"
            if completed and not restoration_failed
            else "blocked",
            "detail": (
                "This project did not pass its independent check, so Control Tower restored every completed change."
                if completed and not restoration_failed
                else "This project could not finish and every completed change could not be restored. Review its diagnostic record before continuing."
                if completed
                else "Control Tower stopped before changing this project."
            ),
            "error": str(exc),
            "completed_actions": rolled_back,
            "verification": "failed" if completed else "not-run",
            "targeted_components": targeted,
            "_diagnostic": diagnostic,
        }
