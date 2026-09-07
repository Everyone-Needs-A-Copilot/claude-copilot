"""Explicit runtime diagnostics; installation and direct probes are not enforcement.

No persistent verdict cache and no model/runtime dispatch. A fresh report binds
selected project files, hook bytes and effective disable switches. Native adapters
may be directly probed only when the caller opts in; they never grant runtime trust.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from cc.core.evaluation.schema import canonical_sha256


def _fingerprint(project: Path, paths: list[Path]) -> dict[str, Any]:
    files = []
    for path in sorted(set(paths)):
        try:
            if not path.is_file():
                raise OSError("not a regular file")
            raw = path.read_bytes()
            item = {"path": str(path.relative_to(project)), "resolved": str(path.resolve()),
                    "sha256": hashlib.sha256(raw).hexdigest(), "executable": os.access(path, os.X_OK)}
        except OSError:
            item = {"path": str(path.relative_to(project)), "missing": True}
        files.append(item)
    switches = {k: v for k, v in sorted(os.environ.items())
                if k.startswith("COPILOT_") and (v == "off" or k == "COPILOT_HOOKS_ROOT")}
    return {"files": files, "switches": switches,
            "sha256": canonical_sha256({"project": str(project), "files": files, "switches": switches})}


def _probe_codex(hooks: Path) -> list[dict[str, Any]]:
    """Exercise native payload contracts in disposable state, not a Codex session."""
    results = []
    with tempfile.TemporaryDirectory(prefix="cc-hook-probe-") as scratch:
        env = {**os.environ, "CODEX_COPILOT_HOOK_STATE_DIR": scratch}
        def invoke(name: str, payload: dict) -> dict:
            result = subprocess.run(["/bin/bash", str(hooks / name)], input=json.dumps(payload),
                                    text=True, capture_output=True, env=env, timeout=5, cwd=scratch)
            if result.returncode:
                raise ValueError("hook-command-failed")
            value = json.loads(result.stdout) if result.stdout.strip() else {}
            if not isinstance(value, dict):
                raise ValueError("hook-result-not-object")
            return value
        try:
            value = invoke("user-prompt-protocol.sh", {"prompt": "This backend API is failing."})
            passed = value.get("hookSpecificOutput", {}).get("hookEventName") == "UserPromptSubmit" and "$qa" in value.get("hookSpecificOutput", {}).get("additionalContext", "")
            results.append({"control": "routing", "passed": passed})
        except (OSError, ValueError, subprocess.TimeoutExpired):
            results.append({"control": "routing", "passed": False})
        try:
            value = invoke("subagent-return-contract.sh", {})
            passed = "three sentences" in value.get("hookSpecificOutput", {}).get("additionalContext", "")
            results.append({"control": "subagent-return-contract", "passed": passed})
        except (OSError, ValueError, subprocess.TimeoutExpired):
            results.append({"control": "subagent-return-contract", "passed": False})
        try:
            post = {"hook_event_name": "PostToolUse", "session_id": "cc-diagnostic", "tool_name": "Bash", "tool_input": {"command": "git status"}, "tool_response": {"exit_code": 1, "output": "failed"}}
            invoke("debug-circuit-breaker.sh", post)
            invoke("debug-circuit-breaker.sh", post)
            value = invoke("debug-circuit-breaker.sh", {**post, "hook_event_name": "PreToolUse"})
            results.append({"control": "debug-circuit-breaker", "passed": value.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"})
        except (OSError, ValueError, subprocess.TimeoutExpired):
            results.append({"control": "debug-circuit-breaker", "passed": False})
    return results


def build_runtime_report(project: Path, *, exercise: bool = False) -> dict[str, Any]:
    project = project.resolve()
    if not project.is_dir():
        raise ValueError("Project must be a directory")
    hooks = project / "plugins/codex-copilot/hooks"
    registry = hooks / "hooks.json"
    paths = [project / "AGENTS.md", project / "CLAUDE.md", project / "copilot.lock.json",
             project / ".claude/settings.json", project / ".claude/settings.local.json",
             project / ".codex/config.toml", project / ".codex-copilot.json", registry]
    paths += list(hooks.glob("*.sh")) + list((project / ".claude/hooks").glob("*.sh"))
    before = _fingerprint(project, paths)
    declared = False
    try:
        entries = json.loads(registry.read_text())["hooks"]
        declared = isinstance(entries, dict) and all(entries.get(name) for name in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStart"))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    installed = declared and all((hooks / name).is_file() for name in
                                ("user-prompt-protocol.sh", "debug-circuit-breaker.sh", "subagent-return-contract.sh"))
    probes = _probe_codex(hooks) if exercise and installed else []
    after = _fingerprint(project, paths)
    stable = before["sha256"] == after["sha256"]
    exercised = bool(probes) and all(p["passed"] for p in probes) and stable
    claude_declared = False
    try:
        claude_declared = bool(json.loads((project / ".claude/settings.json").read_text()).get("hooks"))
    except (OSError, ValueError, AttributeError):
        pass
    return {"schema_version": "1.0", "project": str(project), "identity": after,
            "identity_stable_during_probe": stable,
            "runtimes": [
                {"runtime": "codex", "declared": declared, "installed": installed,
                 "trusted": "unknown", "exercised": exercised, "probes": probes,
                 "exercise_scope": "direct-hook-contract" if probes else "not-exercised",
                 "runtime_enforced": "unknown"},
                {"runtime": "claude", "declared": claude_declared,
                 "installed": (project / ".claude/hooks/copilot-hook.sh").is_file(),
                 "trusted": "unknown", "exercised": False,
                 "exercise_scope": "use-doctor-registration-and-shim-resolution-checks",
                 "runtime_enforced": "unknown"}],
            "boundary": "Project-local diagnostic only. Trust, global runtime configuration and actual lifecycle dispatch require runtime-origin evidence; file presence and direct probes cannot establish them. No previous result is reused."}
