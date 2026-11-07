"""User-level hook registration for central resolution.

Registers the framework hook shim once in `~/.claude/settings.json` (receipt-scoped,
backed up, reversible) plus the pure fingerprint-keyed merge/removal logic that never
touches an entry it did not add. The retired per-project half of this module (a
`mutations[]` ledger inside a project's `copilot.lock.json`, `cc settings-hook
add|remove|rollback|list-sources`) was removed in the retire-copy-model task: projects
no longer carry hook registrations, and `cc project migrate` strips the old ones.

MERGE CONTRACT (`merge_hook_entries` / `remove_hook_entries`): structural, at the level of
`hooks.<Event>` matcher-groups. A per-entry `spec_fingerprint()` --
`sha256(event + " " + matcher + " " + command)` -- is the only removal key, never position,
never a name. A user's own same-named hook survives byte-for-byte.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


_COPILOT_SOURCE_KEY = "_copilot_source"


class MutationLedgerError(RuntimeError):
    """A settings-hook mutation could not be planned, applied, or reverted."""


def spec_fingerprint(event: str, matcher: str, command: str) -> str:
    """`sha256(event + " " + matcher + " " + command)` -- the one removal
    key. Matching on this triple (never on array position, never on a
    name) is what makes a user's own same-named hook structurally
    untouchable by `remove_hook_entries()`."""
    payload = f"{event} {matcher} {command}".encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class HookEntrySpec:
    event: str
    matcher: str
    command: str

    def fingerprint(self) -> str:
        return spec_fingerprint(self.event, self.matcher, self.command)

    def as_dict(self) -> dict[str, str]:
        return {
            "event": self.event,
            "matcher": self.matcher,
            "command": self.command,
            "spec_fingerprint": self.fingerprint(),
        }


# ---------------------------------------------------------------------------
# Pure JSON merge / removal -- no filesystem I/O, independently testable.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MergeAction:
    event: str
    matcher: str
    command: str
    spec_fingerprint: str
    action: str  # "added" | "unchanged" | "upgraded"


def _effective_matcher(group: Mapping[str, Any]) -> str:
    value = group.get("matcher", "")
    return value if isinstance(value, str) else ""


def merge_hook_entries(
    settings: Mapping[str, Any],
    entries: Sequence[HookEntrySpec],
    *,
    source: str,
) -> tuple[dict[str, Any], list[MergeAction]]:
    """Structurally merge `entries` into `settings["hooks"]` at the
    matcher-group level. Never reads, reorders, or touches any sibling key
    (`permissions`, `statusLine`, `enabledMcpjsonServers`, ...) and never
    indexes into or replaces an existing group -- only ever appends a new
    group or, for a group this same `source` previously wrote, updates its
    command in place. A user's own group with the same `(event, matcher)`
    but no `_copilot_source` tag is left alone and a separate group is
    appended beside it.

    Deliberately preserves key insertion order (no `sort_keys`): `settings`
    is user-authored, and reordering it would produce a large, unrelated
    diff. Returns a freshly built dict (never mutates its argument) plus
    one `MergeAction` per requested entry.
    """
    if not isinstance(settings, Mapping):
        raise MutationLedgerError("The settings document must be a JSON object.")
    result: dict[str, Any] = dict(settings)
    hooks = result.get("hooks")
    if hooks is None:
        hooks = {}
    elif not isinstance(hooks, dict):
        raise MutationLedgerError("The settings 'hooks' key is not an object.")
    else:
        hooks = dict(hooks)
    result["hooks"] = hooks

    actions: list[MergeAction] = []
    for entry in entries:
        fp = entry.fingerprint()
        raw_group_list = hooks.get(entry.event)
        if raw_group_list is None:
            group_list: list[Any] = []
        elif isinstance(raw_group_list, list):
            group_list = list(raw_group_list)
        else:
            raise MutationLedgerError(
                f"The settings hooks.{entry.event} key is not an array."
            )
        hooks[entry.event] = group_list

        matched = False
        upgrade_index: Optional[int] = None
        upgrade_inner_index: Optional[int] = None
        for group_index, group in enumerate(group_list):
            if not isinstance(group, Mapping):
                continue
            inner_hooks = group.get("hooks")
            if not isinstance(inner_hooks, list):
                continue
            matcher = _effective_matcher(group)
            for inner_index, inner in enumerate(inner_hooks):
                if not isinstance(inner, Mapping):
                    continue
                inner_fp = spec_fingerprint(
                    entry.event, matcher, str(inner.get("command", ""))
                )
                if inner_fp == fp:
                    matched = True
                    break
                if matcher == entry.matcher and inner.get(_COPILOT_SOURCE_KEY) == source:
                    upgrade_index, upgrade_inner_index = group_index, inner_index
            if matched:
                break

        if matched:
            actions.append(
                MergeAction(entry.event, entry.matcher, entry.command, fp, "unchanged")
            )
            continue

        if upgrade_index is not None and upgrade_inner_index is not None:
            group_list[upgrade_index] = dict(group_list[upgrade_index])
            inner_list = list(group_list[upgrade_index]["hooks"])
            inner_list[upgrade_inner_index] = {
                **dict(inner_list[upgrade_inner_index]),
                "command": entry.command,
                _COPILOT_SOURCE_KEY: source,
            }
            group_list[upgrade_index]["hooks"] = inner_list
            actions.append(
                MergeAction(entry.event, entry.matcher, entry.command, fp, "upgraded")
            )
            continue

        new_group: dict[str, Any] = {}
        if entry.matcher:
            new_group["matcher"] = entry.matcher
        new_group["hooks"] = [
            {
                "type": "command",
                "command": entry.command,
                _COPILOT_SOURCE_KEY: source,
            }
        ]
        group_list.append(new_group)
        actions.append(MergeAction(entry.event, entry.matcher, entry.command, fp, "added"))

    return result, actions


@dataclass(frozen=True)
class RemovalResult:
    settings: dict[str, Any]
    removed: tuple[str, ...]
    not_found: tuple[str, ...]


def remove_hook_entries(
    settings: Mapping[str, Any],
    entries: Sequence[HookEntrySpec],
) -> RemovalResult:
    """The inverse of `merge_hook_entries()`: strip only inner hooks whose
    `spec_fingerprint` is in `entries`, prune any matcher-group left empty,
    then prune the `hooks` key itself if it is now empty. Never touches an
    entry whose fingerprint does not match -- a user hand-edit that changed
    the command (or removed it already) is reported in `not_found` rather
    than silently ignored, so a caller can flag it instead of claiming a
    clean removal that did not actually happen.
    """
    if not isinstance(settings, Mapping):
        raise MutationLedgerError("The settings document must be a JSON object.")
    result: dict[str, Any] = dict(settings)
    hooks = result.get("hooks")
    wanted = {entry.fingerprint(): entry for entry in entries}
    found: set[str] = set()

    if isinstance(hooks, dict):
        new_hooks: dict[str, Any] = {}
        for event, group_list in hooks.items():
            if not isinstance(group_list, list):
                new_hooks[event] = group_list
                continue
            new_groups: list[Any] = []
            for group in group_list:
                if not isinstance(group, Mapping):
                    new_groups.append(group)
                    continue
                inner_hooks = group.get("hooks")
                if not isinstance(inner_hooks, list):
                    new_groups.append(group)
                    continue
                matcher = _effective_matcher(group)
                kept_inner = []
                for inner in inner_hooks:
                    fp = (
                        spec_fingerprint(event, matcher, str(inner.get("command", "")))
                        if isinstance(inner, Mapping)
                        else None
                    )
                    if fp is not None and fp in wanted:
                        found.add(fp)
                        continue
                    kept_inner.append(inner)
                if kept_inner:
                    new_group = dict(group)
                    new_group["hooks"] = kept_inner
                    new_groups.append(new_group)
                # else: this group is now empty -- drop it entirely.
            if new_groups:
                new_hooks[event] = new_groups
            # else: drop the now-empty event key entirely.
        if new_hooks:
            result["hooks"] = new_hooks
        else:
            result.pop("hooks", None)

    not_found = tuple(
        entry.fingerprint() for entry in entries if entry.fingerprint() not in found
    )
    removed = tuple(fp for fp in wanted if fp in found)
    return RemovalResult(result, removed, not_found)


def canonical_settings_bytes(settings: Mapping[str, Any]) -> bytes:
    """No `sort_keys` -- see `merge_hook_entries()`'s docstring: a user's
    settings file must never be reordered on our account.

    Public (not `_`-prefixed) so `reconciliation_recipes.py`/
    `reconciliation_transaction.py`'s `RegisterOperationKind.
    REGISTER_SETTINGS_HOOKS` operation can byte-for-byte reproduce what
    this module would itself write -- the two paths MUST agree, because
    `apply_settings_hook()` is later invoked in `"adopt"` mode to append
    the `mutations[]` ledger row for content the recipe engine already
    wrote (see that function's docstring on the crash-window `"orphaned"`
    -> `"adopted"` design this reuses deliberately, not accidentally).
    """
    return (json.dumps(dict(settings), indent=2) + "\n").encode("utf-8")


# Backward-compatible private alias -- kept because this module's own
# functions below were written against the underscored name.
_canonical_settings_bytes = canonical_settings_bytes


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# User-level registration (~/.claude/settings.json), central resolution.
#
# Registers the five framework hook events ONCE for every project; the shim
# itself (copilot-hook.sh, reached through ~/.copilot/current) gates on the
# project marker, so projects carry no registration. Safety contract: back up
# first, atomic replace, never touch a key we did not add, receipt-scoped
# reversal. Callers inject `home`; nothing here reads the real home implicitly.
# ---------------------------------------------------------------------------

USER_SOURCE = "claude-copilot-user"
USER_ENV: dict[str, str] = {"SLASH_COMMAND_TOOL_CHAR_BUDGET": "100000"}
USER_RECEIPT_NAME = "user-settings-receipt.json"
_USER_SHIM = "$HOME/.copilot/current/claude-copilot/.claude/hooks/copilot-hook.sh"

_USER_EVENTS: tuple[tuple[str, str, str], ...] = (
    ("SessionStart", "startup|resume|clear|compact", "session-start"),
    ("PreToolUse", "Bash|Read|Edit|Write|Agent", "pretool-check"),
    ("SubagentStop", ".*", "subagent-stop"),
    ("UserPromptSubmit", "", "user-prompt-submit"),
    ("PreCompact", "", "pre-compact-handoff"),
)


def _user_command(event_name: str) -> str:
    """Stable command string (identical across releases). Runs the shim through
    the release pointer; if the pointer/file is absent it exits 0 (never blocks)
    unless the project opted into fail-closed with .claude/copilot-required."""
    return (
        f'f="{_USER_SHIM}"; '
        f'if [ -f "$f" ]; then exec bash "$f" {event_name}; fi; '
        'if [ -f "${CLAUDE_PROJECT_DIR:-.}/.claude/copilot-required" ]; then '
        'echo "[copilot-hook] release pointer missing; run cc release status" >&2; exit 2; fi; '
        "exit 0"
    )


def user_hook_entries() -> tuple[HookEntrySpec, ...]:
    return tuple(HookEntrySpec(e, m, _user_command(n)) for e, m, n in _USER_EVENTS)


@dataclass(frozen=True)
class UserSettingsOutcome:
    status: str  # applied | unchanged | removed | not-installed | blocked
    detail: str
    backup: Optional[str] = None
    env_added: tuple[str, ...] = ()
    settings_path: Optional[str] = None


def user_settings_path(home: Path | str) -> Path:
    return Path(home) / ".claude" / "settings.json"


def _user_receipt_path(home: Path | str) -> Path:
    return Path(home) / ".copilot" / USER_RECEIPT_NAME


def _atomic_replace(path: Path, data: bytes) -> None:
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_user_settings(path: Path) -> tuple[Optional[dict[str, Any]], Optional[bytes], str]:
    if not path.exists():
        return {}, None, ""
    raw = path.read_bytes()
    try:
        doc = json.loads(raw.decode("utf-8")) if raw.strip() else {}
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, raw, f"settings.json is not valid JSON: {exc}"
    if not isinstance(doc, dict):
        return None, raw, "settings.json does not contain a JSON object"
    return doc, raw, ""


def _backup(path: Path, raw: Optional[bytes]) -> Optional[str]:
    if raw is None:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = path.with_name(f"{path.name}.copilot-backup-{stamp}")
    backup.write_bytes(raw)
    backup.chmod(0o600)
    return str(backup)


def apply_user_settings(home: Path | str, *, dry_run: bool = False) -> UserSettingsOutcome:
    """Idempotently register the shim entries and the skill-listing budget in
    `<home>/.claude/settings.json`. An existing value for the env key is the
    owner's and is left alone."""
    path = user_settings_path(home)
    doc, raw, error = _read_user_settings(path)
    if doc is None:
        return UserSettingsOutcome("blocked", error, settings_path=str(path))
    merged, _ = merge_hook_entries(doc, user_hook_entries(), source=USER_SOURCE)
    env = merged.get("env")
    if env is None:
        env = {}
    elif not isinstance(env, dict):
        return UserSettingsOutcome("blocked", "settings 'env' is not an object", settings_path=str(path))
    else:
        env = dict(env)
    env_added = tuple(k for k in USER_ENV if k not in env)
    for key in env_added:
        env[key] = USER_ENV[key]
    merged["env"] = env
    new_bytes = canonical_settings_bytes(merged)
    if raw is not None and new_bytes == raw:
        return UserSettingsOutcome("unchanged", "Already registered.", settings_path=str(path))
    # Canonical rewrite of an owner-formatted file that otherwise matches: still a change.
    if dry_run:
        return UserSettingsOutcome("applied", "Dry run: nothing written.", env_added=env_added, settings_path=str(path))
    receipt_path = _user_receipt_path(home)
    prior = {}
    if receipt_path.exists():
        try:
            prior = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prior = {}
    backup = _backup(path, raw)
    receipt = {
        "schema_version": "1.0",
        "source": USER_SOURCE,
        "settings": str(path),
        "applied_at": _utc_now(),
        "env_added": sorted(set(env_added) | set(prior.get("env_added", []))),
        "entries": [e.as_dict() for e in user_hook_entries()],
        "backup": backup,
        "settings_existed_before": raw is not None or bool(prior.get("settings_existed_before")),
    }
    _atomic_replace(receipt_path, (json.dumps(receipt, indent=2) + "\n").encode("utf-8"))
    _atomic_replace(path, new_bytes)
    return UserSettingsOutcome("applied", "User-level hooks registered.", backup, env_added, str(path))


def remove_user_settings(home: Path | str) -> UserSettingsOutcome:
    """Reverse `apply_user_settings`: strip only our fingerprinted entries and
    only the env keys the receipt says we added (and still hold our value)."""
    path = user_settings_path(home)
    doc, raw, error = _read_user_settings(path)
    if doc is None:
        return UserSettingsOutcome("blocked", error, settings_path=str(path))
    receipt_path = _user_receipt_path(home)
    receipt: dict[str, Any] = {}
    if receipt_path.exists():
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            receipt = {}
    result = remove_hook_entries(doc, user_hook_entries())
    out = dict(result.settings)
    removed_env: list[str] = []
    env = out.get("env")
    if isinstance(env, dict):
        env = dict(env)
        for key in receipt.get("env_added", []):
            if key in USER_ENV and env.get(key) == USER_ENV[key]:
                del env[key]
                removed_env.append(key)
        if env:
            out["env"] = env
        else:
            out.pop("env", None)
    if not result.removed and not removed_env:
        return UserSettingsOutcome("not-installed", "Nothing to remove.", settings_path=str(path))
    backup = _backup(path, raw)
    _atomic_replace(path, canonical_settings_bytes(out))
    receipt_path.unlink(missing_ok=True)
    return UserSettingsOutcome("removed", "User-level hooks removed.", backup, tuple(removed_env), str(path))


__all__ = [
    "HookEntrySpec",
    "MergeAction",
    "MutationLedgerError",
    "RemovalResult",
    "USER_ENV",
    "UserSettingsOutcome",
    "apply_user_settings",
    "canonical_settings_bytes",
    "merge_hook_entries",
    "remove_hook_entries",
    "remove_user_settings",
    "spec_fingerprint",
    "user_hook_entries",
    "user_settings_path",
]
