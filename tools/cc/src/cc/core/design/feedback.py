"""Opt-in native feedback. A hook reminder never changes task QA state."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from cc.core.entry_store import _atomic_write
from cc.core.locking import copilot_lock, LockContentionError
from .contracts import local_path, read_json, source_records
from cc.core.evaluation.schema import canonical_sha256
from .tools import audit, EXTENSIONS, tool_status

COMMANDS = {
    "claude": '"$HOME/.local/bin/cc" design feedback --runtime claude',
    "codex": '"$HOME/.local/bin/cc" design feedback --runtime codex',
}


def configure(root: Path, runtime: str, *, enabled: bool) -> dict:
    if runtime not in COMMANDS:
        raise ValueError("runtime must be claude or codex")
    target = local_path(root, ".copilot/design-feedback.json", exists=False)
    manifest_name = ".claude/settings.local.json" if runtime == "claude" else ".codex/hooks.json"
    manifest_path = local_path(root, manifest_name, exists=False)
    lock = local_path(root, ".copilot/design-feedback.lock", exists=False)
    with copilot_lock(path=lock):
        config = read_json(target) if target.exists() else {"schema_version": "1.0"}
        if enabled:
            if not tool_status()["available"]:
                raise ValueError("Install/register the machine-pinned detector before enabling automatic feedback")
            manifest = read_json(manifest_path) if manifest_path.exists() else {}
            hooks = manifest.setdefault("hooks", {})
            if not isinstance(hooks, dict):
                raise ValueError("Existing hook manifest has an invalid hooks object")
            entries = hooks.setdefault("PostToolUse", [])
            if not isinstance(entries, list):
                raise ValueError("Existing PostToolUse manifest is malformed")
            command = COMMANDS[runtime]
            exists = any(isinstance(e, dict) and isinstance(e.get("hooks"), list) and
                         any(isinstance(h, dict) and h.get("command") == command for h in e["hooks"]) for e in entries)
            if not exists:
                entries.append({"matcher": "Edit|Write|MultiEdit|apply_patch", "hooks": [{"type": "command", "command": command, "timeout": 5}]})
                _atomic_write(manifest_path, json.dumps(manifest, indent=2) + "\n")
        runtimes = config.setdefault("runtimes", {})
        if not isinstance(runtimes, dict):
            raise ValueError("Feedback runtimes must be an object")
        runtimes[runtime] = enabled
        _atomic_write(target, json.dumps(config, indent=2) + "\n")
    return {"enabled": enabled, "runtime": runtime, "config": str(target), "manifest": str(manifest_path),
            "boundary": "Registration is not runtime trust or dispatch. Verify a real native edit event; disabling preserves other hooks and QA gates."}


def _event_targets(event: dict, runtime: str) -> list[str]:
    tool = str(event.get("tool_name", ""))
    inputs = event.get("tool_input")
    if not isinstance(inputs, dict):
        inputs = {"input": inputs} if isinstance(inputs, str) else {}
    if tool in ("Edit", "Write", "MultiEdit"):
        path = inputs.get("file_path", inputs.get("path"))
        return [path] if isinstance(path, str) else []
    if runtime == "codex" and tool.endswith("apply_patch"):
        # Native Codex lifecycle hooks normalize apply_patch into command;
        # input/patch remain supported for older adapters and explicit replay.
        patch = inputs.get("command", inputs.get("input", inputs.get("patch", "")))
        if isinstance(patch, str):
            return re.findall(r"^\*\*\* (?:Add|Update) File: (.+)$", patch, re.MULTILINE)[:8]
    return []


def feedback(root: Path, event: dict, runtime: str) -> dict | None:
    if runtime not in COMMANDS:
        raise ValueError("runtime must be claude or codex")
    config_path = local_path(root, ".copilot/design-feedback.json", exists=False)
    if os.environ.get("CC_DESIGN_FEEDBACK") == "off" or not config_path.exists():
        return None
    config = read_json(config_path)
    if not isinstance(config.get("runtimes"), dict) or config["runtimes"].get(runtime) is not True:
        return None
    if event.get("hook_event_name") != "PostToolUse":
        return None
    names = _event_targets(event, runtime)
    names = list(dict.fromkeys(names))
    sources = []
    for name in names:
        path = local_path(root, name)
        if path.suffix.lower() in EXTENSIONS:
            sources.append(path.relative_to(root.resolve()).as_posix())
    if not sources:
        return None
    session = event.get("session_id")
    if not isinstance(session, str) or not session:
        return envelope("Design feedback skipped: native session identity missing; QA still requires an explicit audit.")
    sid = hashlib.sha256((runtime + ":" + session).encode()).hexdigest()
    state_path = local_path(root, f".copilot/design-feedback/{sid}.json", exists=False)
    lock = local_path(root, f".copilot/design-feedback/{sid}.lock", exists=False)
    try:
        with copilot_lock(path=lock):
            state = read_json(state_path) if state_path.exists() else {"seen": {}}
            if not isinstance(state.get("seen"), dict):
                raise ValueError("Malformed design feedback state")
            tool = tool_status()
            pin = tool.get("sha256", "unavailable")
            fingerprints = {n: canonical_sha256(source_records(root, [n])) + ":" + pin for n in sources}
            pending = [n for n in sources if state["seen"].get(n) != fingerprints[n]]
            if not pending:
                return None
            result = audit(root, pending, timeout=2)
            if result["status"] != "completed":
                return envelope(f"Design feedback {result['status']}; run an explicit design audit during QA. No approval granted.")
            for name in pending:
                state["seen"][name] = fingerprints[name]
            state["seen"] = dict(list(state["seen"].items())[-128:])
            _atomic_write(state_path, json.dumps(state, indent=2) + "\n")
            if not result["findings"]:
                return None
            findings = result["findings"]
            summary = "; ".join(f"{f['antipattern']}: {f['file']}:{f['line']}" for f in findings[:4])
            return envelope(f"Design detector found {len(findings)} candidate issue(s): {summary}. Verify in context; aesthetic findings do not override the brief. Store full evidence with cc design audit; tc QA remains required.")
    except LockContentionError:
        return envelope("Design feedback is busy; complete the explicit design audit during QA.")


def envelope(message: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": message[:1400]}}
