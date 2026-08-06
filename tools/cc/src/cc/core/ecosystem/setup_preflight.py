"""Bounded active preparation before project reconciliation.

The preflight owns two routine mutations the desktop app must never
reimplement: local checkpoint commits for eligible Product projects and
download-only fast-forwards for shared Copilot repositories.  It never pushes.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

from cc.commands.onboard import build_shared_repository_refresh_report
from cc.core.ecosystem.project_locking import (
    ProjectLockError,
    project_lock,
)
from cc.core.ecosystem.reconciliation import assess_reconciliation
from cc.core.ecosystem.reconciliation_types import RECONCILIATION_SCHEMA_VERSION

AssessBuilder = Callable[[], dict[str, Any]]
RefreshBuilder = Callable[[], dict[str, Any]]

_IN_PROGRESS_MARKERS = (
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "BISECT_LOG",
    "rebase-apply",
    "rebase-merge",
)


def _git(
    root: Path, *arguments: str, timeout: float = 120.0
) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment.update({"LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"})
    return subprocess.run(
        (
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            *arguments,
        ),
        cwd=root,
        env=environment,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _output(result: subprocess.CompletedProcess[bytes]) -> str:
    return result.stdout.decode("utf-8", errors="replace").strip()


def _hold(path: str, code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "project": path, "detail": detail}


def _restore_index(index_path: Path, payload: bytes | None, mode: int | None) -> None:
    if payload is None:
        try:
            index_path.unlink()
        except FileNotFoundError:
            pass
        return
    with tempfile.NamedTemporaryFile(dir=index_path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    if mode is not None:
        os.chmod(temporary, mode)
    os.replace(temporary, index_path)


def _checkpoint_project(project: Mapping[str, Any], run_id: str) -> dict[str, Any]:
    raw_path = project.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        return {"status": "held", "hold": _hold("unknown", "invalid-project-path", "The project path was not valid.")}
    root = Path(raw_path)
    try:
        with project_lock(root):
            branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
            if branch.returncode != 0:
                return {"status": "held", "hold": _hold(raw_path, "detached-head", "Attach the project to its intended branch before setup saves it.")}

            conflicts = _git(root, "diff", "--name-only", "--diff-filter=U", "-z")
            if conflicts.returncode != 0 or conflicts.stdout:
                return {"status": "held", "hold": _hold(raw_path, "unmerged-work", "Resolve the project's merge conflicts before setup saves it.")}

            for marker in _IN_PROGRESS_MARKERS:
                marker_result = _git(root, "rev-parse", "--git-path", marker)
                if marker_result.returncode != 0:
                    return {"status": "held", "hold": _hold(raw_path, "git-state-unreadable", "Git's current operation state could not be verified.")}
                marker_path = Path(_output(marker_result))
                if not marker_path.is_absolute():
                    marker_path = root / marker_path
                if marker_path.exists():
                    return {"status": "held", "hold": _hold(raw_path, "git-operation-in-progress", "Finish the project's current Git operation before setup saves it.")}

            status = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
            if status.returncode != 0:
                return {"status": "held", "hold": _hold(raw_path, "git-status-unreadable", "The project's current work could not be inspected safely.")}
            if not status.stdout:
                return {"status": "current"}

            name = _git(root, "config", "user.name")
            email = _git(root, "config", "user.email")
            if name.returncode != 0 or email.returncode != 0 or not _output(name) or not _output(email):
                return {"status": "held", "hold": _hold(raw_path, "git-identity-missing", "Set this project's Git user name and email before setup saves it.")}

            old_head = _git(root, "rev-parse", "HEAD")
            if old_head.returncode != 0:
                return {"status": "held", "hold": _hold(raw_path, "git-head-unreadable", "The project's current revision could not be confirmed.")}
            before_sha = _output(old_head)

            index_result = _git(root, "rev-parse", "--git-path", "index")
            if index_result.returncode != 0:
                return {"status": "held", "hold": _hold(raw_path, "git-index-unreadable", "The project's Git index could not be located.")}
            index_path = Path(_output(index_result))
            if not index_path.is_absolute():
                index_path = root / index_path
            try:
                index_payload = index_path.read_bytes()
                index_mode: int | None = index_path.stat().st_mode & 0o777
            except FileNotFoundError:
                index_payload = None
                index_mode = None
            except OSError:
                return {"status": "held", "hold": _hold(raw_path, "git-index-unreadable", "The project's Git index could not be backed up safely.")}

            staged = _git(root, "add", "-A", "--", ".")
            if staged.returncode != 0:
                _restore_index(index_path, index_payload, index_mode)
                return {"status": "held", "hold": _hold(raw_path, "git-stage-failed", "Git could not prepare all current project work for a local checkpoint.")}

            commit = _git(
                root,
                "commit",
                "-m",
                "chore: save work before Copilot setup",
                "-m",
                f"Copilot-Setup-Run: {run_id}",
            )
            if commit.returncode != 0:
                _restore_index(index_path, index_payload, index_mode)
                return {"status": "held", "hold": _hold(raw_path, "git-commit-failed", "Git did not accept the local checkpoint. Existing work and the prior index were preserved.")}

            new_head = _git(root, "rev-parse", "HEAD")
            if new_head.returncode != 0 or _output(new_head) == before_sha:
                return {"status": "held", "hold": _hold(raw_path, "git-commit-unverified", "Git returned from the checkpoint without a verifiable new revision.")}
            after_sha = _output(new_head)
            after_status = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
            residual = after_status.returncode != 0 or bool(after_status.stdout)
            return {
                "status": "checkpointed",
                "action": {
                    "kind": "project-checkpoint",
                    "target": raw_path,
                    "outcome": "completed",
                    "summary": f"Saved current work in {project.get('name') or root.name} as a local Git commit.",
                    "branch": _output(branch),
                    "from_sha": before_sha,
                    "to_sha": after_sha,
                    "pushed": False,
                    "residual_work": residual,
                },
                "hold": (
                    _hold(raw_path, "work-remains-after-checkpoint", "Another process created additional work during the checkpoint; that work was left in place.")
                    if residual
                    else None
                ),
            }
    except (OSError, subprocess.SubprocessError, ProjectLockError):
        return {"status": "held", "hold": _hold(raw_path, "project-checkpoint-unavailable", "The project changed or could not be locked safely, so setup left it alone.")}


def build_setup_prepare_report(
    *,
    assess_builder: AssessBuilder = assess_reconciliation,
    refresh_builder: RefreshBuilder = build_shared_repository_refresh_report,
) -> dict[str, Any]:
    """Save eligible Product work, refresh shared sources, then reassess."""
    initial = assess_builder()
    run_id = str(initial.get("run_id") or "prepare")
    actions: list[dict[str, Any]] = []
    holds: list[dict[str, Any]] = []
    checkpointed = 0
    current = 0

    for project in initial.get("projects", []):
        if not isinstance(project, Mapping):
            continue
        if project.get("scope", {}).get("kind") != "product-project":
            continue
        blockers = project.get("blockers", [])
        if not any(
            isinstance(blocker, Mapping) and blocker.get("code") == "dirty-working-tree"
            for blocker in blockers
        ):
            continue
        outcome = _checkpoint_project(project, run_id)
        if outcome["status"] == "checkpointed":
            checkpointed += 1
            actions.append(outcome["action"])
        elif outcome["status"] == "current":
            current += 1
        if outcome.get("hold"):
            holds.append(outcome["hold"])

    try:
        refresh = refresh_builder()
    except Exception:
        refresh = {
            "result": "blocked",
            "mode": "download-only",
            "completed_actions": [],
            "layers": [],
            "authority": {"setup_access": "download-only", "author_capable": 0, "read_only": 0, "unknown": 0},
            "summary": {"checked": 0, "updated": 0, "current": 0, "held": 1},
            "holds": [{"code": "shared-refresh-unavailable", "detail": "Shared Copilot repositories could not be refreshed safely."}],
        }
    actions.extend(refresh.get("completed_actions", []))
    holds.extend(refresh.get("holds", []))
    assessment = assess_builder()

    refresh_summary = refresh.get("summary", {})
    updated = int(refresh_summary.get("updated", 0))
    result = "partial" if holds or assessment.get("result") != "ready" else "applied" if actions else "ready"
    return {
        "schema_version": RECONCILIATION_SCHEMA_VERSION,
        "phase": "prepare",
        "result": result,
        "run_id": run_id,
        "generated_at": assessment.get("generated_at"),
        "completed_actions": actions,
        "project_checkpoints": {
            "checkpointed": checkpointed,
            "became_current": current,
            "held": sum("project" in hold for hold in holds),
            "pushed": 0,
        },
        "ecosystem_refresh": {
            "mode": "download-only",
            **refresh_summary,
        },
        "authority": refresh.get(
            "authority",
            {"setup_access": "download-only", "author_capable": 0, "read_only": 0, "unknown": 0},
        ),
        "holds": holds,
        "assessment": assessment,
        "summary": {
            "headline": "The routine work is done." if actions else "Your projects are checked.",
            "detail": f"I saved work in {checkpointed} project(s) and downloaded {updated} shared Copilot update(s). Nothing was pushed.",
        },
        "next_actions": assessment.get("next_actions", []),
    }


__all__ = ["build_setup_prepare_report"]
