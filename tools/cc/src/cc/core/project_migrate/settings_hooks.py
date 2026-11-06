"""Remove framework hook registrations from a project's .claude/settings.json."""

from __future__ import annotations

import json
from typing import Any, Optional

from cc.core.project_migrate.known import LockRecord

FRAMEWORK_SOURCE = "claude-copilot"
_SHIM = "copilot-hook.sh"


def _is_framework(hook: Any, lock_commands: set[str]) -> Optional[bool]:
    """True: framework-owned. False: not ours. None: looks like the shim but unproven."""
    if not isinstance(hook, dict):
        return False
    if hook.get("_copilot_source") == FRAMEWORK_SOURCE:
        return True
    cmd = hook.get("command")
    if isinstance(cmd, str):
        if cmd in lock_commands:
            return True
        if _SHIM in cmd:
            return None
    return False


def strip_framework_hooks(text: str, lock: Optional[LockRecord]):
    """Returns (new_text, removed_count, ambiguous_commands, empty_after).

    `new_text` is None when nothing changes. Non-framework keys and hooks are
    preserved; empty groups and events are pruned only where we removed entries.
    """
    try:
        data = json.loads(text)
    except ValueError:
        return None, 0, [], False
    if not isinstance(data, dict) or not isinstance(data.get("hooks"), dict):
        return None, 0, [], False
    commands = set(lock.hook_commands) if lock else set()
    removed = 0
    ambiguous: list[str] = []
    hooks = data["hooks"]
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        new_groups = []
        for group in groups:
            inner = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(inner, list):
                new_groups.append(group)
                continue
            kept = []
            for hook in inner:
                verdict = _is_framework(hook, commands)
                if verdict is True:
                    removed += 1
                else:
                    if verdict is None:
                        ambiguous.append(str(hook.get("command")))
                    kept.append(hook)
            if len(kept) == len(inner):
                new_groups.append(group)
            elif kept:
                new_groups.append({**group, "hooks": kept})
        if new_groups:
            hooks[event] = new_groups
        else:
            del hooks[event]
    if removed == 0:
        return None, 0, ambiguous, False
    if not hooks:
        del data["hooks"]
    new_text = json.dumps(data, indent=2) + "\n" if data else ""
    return new_text, removed, ambiguous, not data
