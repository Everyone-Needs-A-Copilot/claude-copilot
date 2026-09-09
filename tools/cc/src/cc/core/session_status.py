"""Read-only projection of existing owners' observations, not session authority."""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
import stat
import time

from cc import __version__
from cc.core.runtime_evidence import build_runtime_report
from cc.core.verification import ARTIFACT_ROOT, VerificationError, read_status

_MAX_JSON_BYTES = 2 * 1024 * 1024
_MAX_RUNS = 200
_MAX_ARTIFACT_ENTRIES = 512
_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
_SAFE_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}\Z")


def _safe_path(project: Path, path: Path, *, directory: bool = False) -> bool:
    """Do not follow symlinks or special files when reading observation sources."""
    for relative in [path.relative_to(project), *path.relative_to(project).parents]:
        candidate = project / relative
        if candidate.is_symlink():
            return False
    if not path.exists():
        return True
    metadata = path.stat()
    return stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode) and metadata.st_size <= _MAX_JSON_BYTES


def _runtime_observations(project: Path) -> dict:
    unknown = [{"runtime": name, "installed": "unknown", "registered": "unknown",
                "activated": "unknown", "running": "unknown", "blocked": "unknown"}
               for name in ("claude", "codex")]
    try:
        directories = [project / "plugins/codex-copilot/hooks", project / ".claude/hooks"]
        if not all(_safe_path(project, path, directory=True) for path in directories):
            raise ValueError("unsafe runtime observation directory")
        paths = [project / name for name in ("AGENTS.md", "CLAUDE.md", "copilot.lock.json",
                 ".claude/settings.json", ".claude/settings.local.json", ".codex/config.toml",
                 ".codex-copilot.json", "plugins/codex-copilot/hooks/hooks.json")]
        paths += [path for directory in directories for path in directory.glob("*.sh")]
        if not all(_safe_path(project, path) for path in paths):
            raise ValueError("unsafe runtime observation file")
        observed = build_runtime_report(project, exercise=False)
        runtimes = [{"runtime": entry["runtime"],
                     "installed": "files-present" if entry["installed"] else "not-observed",
                     "registered": "project-declaration-present" if entry["declared"] else "not-observed", "activated": "unknown",
                     "running": "unknown", "blocked": "unknown"} for entry in observed["runtimes"]]
        return {"state": "observed", "runtimes": runtimes, "evidence": "project-files-only",
                "limitation": "File presence and hook registration do not establish verified installation, activation, trust or live dispatch."}
    except (OSError, ValueError, TypeError, KeyError):
        return {"state": "unavailable", "runtimes": unknown,
                "reason": "Project runtime evidence is unsafe or unreadable; no probes were attempted."}


def _number(value: object) -> float | None:
    return float(value) if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def _bounded_artifacts(directory: Path) -> None:
    """Bound existing owner's integrity hashing; never expose the hashed logs."""
    size = 0
    for index, path in enumerate(directory.rglob("*")):
        if index >= _MAX_ARTIFACT_ENTRIES or path.is_symlink():
            raise VerificationError("unsafe or excessive artifact inventory")
        metadata = path.stat()
        if stat.S_ISREG(metadata.st_mode):
            size += metadata.st_size
        elif not stat.S_ISDIR(metadata.st_mode):
            raise VerificationError("special artifact file")
        if size > _MAX_ARTIFACT_BYTES:
            raise VerificationError("artifact byte limit exceeded")


def _verification_observation(project: Path, now: float) -> dict:
    directory = project / ARTIFACT_ROOT
    try:
        if not _safe_path(project, directory, directory=True):
            raise VerificationError("unsafe artifact directory")
        if not directory.exists():
            return {"state": "not-observed", "run": None}
        candidates = []
        for index, child in enumerate(directory.iterdir()):
            if index >= _MAX_RUNS:
                raise VerificationError("run inventory exceeds bounded view")
            if not _SAFE_ID.fullmatch(child.name) or not _safe_path(project, child, directory=True):
                raise VerificationError("unsafe run directory")
            path = child / "status.json"
            if path.exists() or path.is_symlink():
                if not _safe_path(project, path):
                    raise VerificationError("unsafe status file")
                candidates.append((path.stat().st_mtime_ns, child.name))
        if not candidates:
            return {"state": "not-observed", "run": None}
        _, run_id = max(candidates)
        _bounded_artifacts(directory / run_id)
        raw_status = json.loads((directory / run_id / "status.json").read_text())
        if not isinstance(raw_status, dict):
            raise VerificationError("invalid raw status")
        reference = raw_status.get("reusedFrom")
        if reference:
            if not isinstance(reference, str) or not _SAFE_ID.fullmatch(reference) or not _safe_path(project, directory / reference, directory=True):
                raise VerificationError("unsafe execution reference")
            _bounded_artifacts(directory / reference)
        report = read_status(project, run_id)
        plan_path = directory / run_id / "plan.json"
        if not _safe_path(project, plan_path):
            raise VerificationError("unsafe plan")
        plan = json.loads(plan_path.read_text())
        if (not isinstance(plan, dict) or plan.get("schemaVersion") != 1 or plan.get("kind") != "verification-plan"
            or not isinstance(plan.get("lanes"), list) or not plan["lanes"]
            or any(not isinstance(lane, dict) or not isinstance(lane.get("id"), str)
                   or not _SAFE_ID.fullmatch(lane["id"]) or _number(lane.get("timeoutSeconds")) is None
                   for lane in plan["lanes"])):
            raise VerificationError("invalid saved plan metadata")
        started = _number(report.get("startedAt"))
        observed_at = _number(report.get("finishedAt") if report["status"] != "running" else report.get("heartbeatAt", report.get("startedAt")))
        wall = round(observed_at - started, 3) if started is not None and observed_at is not None and observed_at >= started else None
        current = report.get("current", {})
        if not isinstance(current, dict):
            raise VerificationError("invalid current operation metadata")
        lane_id = current.get("id")
        current_lane = {"id": lane_id, "elapsedSeconds": _number(current.get("elapsedSeconds")),
                        "capSeconds": _number(current.get("timeoutSeconds"))} if isinstance(lane_id, str) and _SAFE_ID.fullmatch(lane_id) else None
        selection = plan.get("selection", {})
        if not isinstance(selection, dict):
            raise VerificationError("invalid selection metadata")
        scope = selection.get("scope")
        task = report.get("task")
        task_id = str(task) if isinstance(task, (str, int)) and re.fullmatch(r"(?:TASK-?)?[0-9]+", str(task)) else None
        return {"state": "observed", "run": {
            "id": run_id, "task": task_id, "lastStatus": report["status"],
            "lastObservedAt": observed_at, "observationAgeSeconds": round(max(0, now - observed_at), 3) if observed_at is not None else None,
            "processLiveness": "unknown", "needsAttention": report["status"] in {"failed", "incomplete"},
            "wallSecondsLastObserved": wall, "executionReused": bool(report.get("reusedFrom")),
            "currentLaneLastObserved": current_lane,
            "plan": {"scope": scope if scope in {"git-base-discovery", "declared-paths", "unknown-impact"} else "unknown",
                     "lanes": [{"id": lane["id"], "capSeconds": lane["timeoutSeconds"]} for lane in plan["lanes"]],
                     "capSeconds": plan.get("timeoutSeconds")},
            "artifactPath": str(directory / run_id),
        }, "limitation": "Last observed execution evidence, not live process state or tc task approval; wall time is one interval, not a sum with lane times or reused execution."}
    except (OSError, ValueError, TypeError, KeyError):
        return {"state": "unavailable", "run": None,
                "reason": "Latest verification evidence is missing, malformed, unsafe or over the bounded view limit; inspect it with cc verify status."}


def build_session_status(project: Path) -> dict:
    """Inspect one explicit project; no writes, probes, subprocesses or inference."""
    project = project.expanduser().resolve()
    if not project.is_dir():
        raise ValueError("Project must be an existing directory")
    now = time.time()
    return {
        "schemaVersion": 1, "kind": "session-status", "project": str(project),
        "observedAt": now, "readOnly": True,
        "cc": {"installed": True, "version": __version__, "evidence": "executing-local-package"},
        "foundation": _runtime_observations(project),
        "verification": _verification_observation(project, now),
        "metrics": {"agentTimeSeconds": None, "contextTokens": None, "modelTokens": None,
                    "apiCostEstimate": None, "subscriptionCharge": None},
        "limitations": ["Agent activation, running and blocked states require runtime-origin evidence and remain unknown here.",
                        "Unknown metrics are not zero; API estimates do not establish subscription billing.",
                        "No quota probe, credential-store access, command execution or raw log/settings/environment output.",
                        "View limits: 200 run directories; selected and reused artifact sets each at most 512 entries and 64 MiB. Integrity checks read log bytes, never output them."],
    }
