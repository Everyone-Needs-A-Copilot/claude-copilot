"""Reversible settings-mutation ledger: `mutations[]` inside a project's own
`copilot.lock.json`, plus the pure merge/removal logic that lets the
framework register hooks into a project's `.claude/settings.json` (a file
that is not, and structurally cannot be, a `files[]`/`ownership: framework`
lock entry -- see `project_integration.py`'s `_verify_lock_entry()`, which
rejects any component record containing a non-framework-owned path) without
ever clobbering what a human put there.

WHY THIS BUILDS ON `project_snapshots.py` / `project_locking.py` RATHER THAN
REIMPLEMENTING THEM: those modules already give a mode-0700 durable vault
with fsynced pre-write capture and compare-and-swap restore
(`SnapshotVault`), plus identity-bound cross-process locking and an atomic
mkstemp/fsync/`os.replace` writer (`project_lock`, `AnchoredProject.atomic_write`,
`atomic_json_write`). Porting a `.bak`-file/`os.replace` shell discipline on
top of that would be a second, weaker safety path. This module is
deliberately just two things: (a) the ledger's shape and pure JSON-merge
logic (no filesystem I/O -- independently testable), and (b) a thin
transaction that sequences those existing primitives around one settings
write plus one ledger write.

BACKWARD COMPATIBILITY, ONE INVARIANT THAT MATTERS MORE THAN THE SYNTHESIS
ASSUMED: `project_integration.py`'s `_lock_state()` and
`project_migrations.py`'s legacy-Codex migration probe both hard-require
`raw.get("schema_version") == "1.0"` (an EXACT match, not "at least 1.0") to
classify a project's lock as readable at all. Bumping `schema_version` to
"1.1" on first mutation write -- as the item-2 synthesis proposed -- would
therefore make `cc doctor`/`inspect_project_integration()` and the legacy
migration probe treat that project's lock as `unreadable`/"unsupported
format" the moment a mutation is recorded, which is a regression, not a
migration. So `schema_version` is left untouched at `"1.0"` here; `mutations`
is added as a plain additive top-level array sibling of `components[]`,
exactly like every OTHER unknown key those two readers already silently
ignore (neither one enumerates or closes the top-level key set).

MERGE CONTRACT (`merge_hook_entries` / `remove_hook_entries`): structural,
at the level of `hooks.<Event>` matcher-groups, matching gstack's approach
that a per-entry `spec_fingerprint()` -- `sha256(event + " " + matcher +
" " + command)` -- is the only removal key, never position, never a name.
A user's own same-named hook survives byte-for-byte because we only ever
compare fingerprints and only ever append/prune whole groups we can prove
are ours.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from cc.core.config_paths import machine_diagnostics_root
from cc.core.ecosystem.project_locking import (
    ProjectLockError,
    UnsafeProjectPath,
    atomic_json_write,
    ensure_private_directory,
    fingerprint_missing,
    project_lock,
)
from cc.core.ecosystem.project_snapshots import SnapshotError, SnapshotVault
from cc.core.ecosystem.projects import (
    PROJECT_LOCK_FILENAME,
    read_project_lock,
    serialize_project_lock,
)

SETTINGS_HOOK_KIND = "settings-hook"
MUTATION_SCOPES = ("project", "local")

# Sticky opt-out (design decision: "removal must survive re-running setup --
# do not re-add what someone deliberately removed"). A project-local,
# zero-byte, NOT framework-owned marker -- same posture as the shim's own
# `.claude/copilot-required` strict-mode marker, just the opposite polarity.
# Checked by BOTH entry points that could otherwise re-register hooks: this
# module's own `apply_settings_hook()` (the `cc settings-hook add` path) AND
# `reconciliation_recipes.py::_claude_setup()` (the `cc reconcile apply` /
# `cc update --project` path) -- so neither one silently resurrects a
# registration a human explicitly turned off, regardless of which command
# happens to run next. `cc settings-hook remove --disable` writes this file
# atomically in the same transaction as the removal, making "clean uninstall"
# ONE command rather than two easy-to-forget steps.
DISABLED_MARKER = ".claude/copilot-hooks-disabled"
_MUTATION_ID = re.compile(r"^mut_[0-9a-f]{8}$")
_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
_COPILOT_SOURCE_KEY = "_copilot_source"
_STATE_DIRNAME = "settings-hook"

# The corrected item-0 registration shape (framework matcher fix), with a
# runtime-resolving shim command per item 1's design -- used as the
# default entry set for `cc settings-hook add` when the caller does not
# supply its own. Registering this does not require item 1's shim file to
# exist on disk yet: a mutation records intent, exactly like a lock entry
# can record a file before it is materialized.
DEFAULT_HOOK_ENTRIES: tuple["HookEntrySpec", ...] = ()  # populated below


class MutationLedgerError(RuntimeError):
    """A settings-hook mutation could not be planned, applied, or reverted."""


class MutationConflict(MutationLedgerError):
    """The live target no longer matches what this ledger last recorded."""


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


DEFAULT_HOOK_ENTRIES = (
    HookEntrySpec(
        "SessionStart",
        "startup|resume|clear|compact",
        'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/copilot-hook.sh" session-start',
    ),
    HookEntrySpec(
        "PreToolUse",
        "Bash|Read|Edit|Write|Agent",
        'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/copilot-hook.sh" pretool-check',
    ),
    HookEntrySpec(
        "SubagentStop",
        "me|qa",
        'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/copilot-hook.sh" subagent-stop',
    ),
    HookEntrySpec(
        "UserPromptSubmit",
        "",
        'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/copilot-hook.sh" user-prompt-submit',
    ),
)


def settings_target(scope: str) -> str:
    if scope not in MUTATION_SCOPES:
        raise MutationLedgerError("scope must be 'project' or 'local'.")
    return ".claude/settings.json" if scope == "project" else ".claude/settings.local.json"


def derive_mutation_id(kind: str, source: str, component: Optional[str], target: str) -> str:
    """A stable id derived from (kind, source, component, target) -- NOT
    random -- so re-running `add` against the same spec finds the same
    ledger row instead of minting a duplicate."""
    payload = json.dumps(
        [kind, source, component, target], sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "mut_" + hashlib.sha256(payload).hexdigest()[:8]


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


# ---------------------------------------------------------------------------
# The ledger itself -- `mutations[]` inside a project's `copilot.lock.json`.
# ---------------------------------------------------------------------------


def read_mutations(lock_document: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = lock_document.get("mutations") if isinstance(lock_document, Mapping) else None
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _write_mutations(
    lock_document: Mapping[str, Any], mutations: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    updated = dict(lock_document)
    if mutations:
        updated["mutations"] = list(mutations)
    else:
        updated.pop("mutations", None)
    updated.setdefault("schema_version", "1.0")
    updated.setdefault("components", [])
    return updated


def find_mutation(
    mutations: Sequence[Mapping[str, Any]], mutation_id: str
) -> Optional[dict[str, Any]]:
    for item in mutations:
        if item.get("id") == mutation_id:
            return dict(item)
    return None


# ---------------------------------------------------------------------------
# Transaction: snapshot -> write settings -> record mutation -> fsync.
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_state_root(root: Optional[Path]) -> Path:
    state_root = (root or (machine_diagnostics_root() / _STATE_DIRNAME)).expanduser()
    boundary = state_root if root is not None else machine_diagnostics_root()
    ensure_private_directory(state_root, boundary=boundary)
    return state_root


def _vault_dir(state_root: Path, vault_ref: str) -> Path:
    directory = state_root / "vaults" / vault_ref
    ensure_private_directory(directory, boundary=state_root)
    return directory


def _write_journal(state_root: Path, mutation_id: str, journal: dict[str, Any]) -> Path:
    directory = state_root / "journal"
    ensure_private_directory(directory, boundary=state_root)
    path = directory / f"{mutation_id}.json"
    atomic_json_write(path, journal)
    return path


@dataclass(frozen=True)
class ApplyOutcome:
    status: str  # "applied" | "adopted" | "unchanged" | "conflict" | "blocked" | "disabled"
    mutation: Optional[dict[str, Any]]
    detail: str
    actions: tuple[MergeAction, ...] = ()


def apply_settings_hook(
    project_path: Path | str,
    *,
    entries: Sequence[HookEntrySpec] = DEFAULT_HOOK_ENTRIES,
    source: str,
    component: Optional[str] = None,
    scope: str = "project",
    applied_by: str,
    dry_run: bool = False,
    force: bool = False,
    _state_root: Optional[Path] = None,
) -> ApplyOutcome:
    """Idempotently register `entries` into `<project>/<scope settings file>`,
    recording exactly one `mutations[]` row (id derived from
    `(kind, source, component, target)`) in the project's own
    `copilot.lock.json`.

    Order, and it is the whole crash-safety contract: snapshot the target's
    pre-write state into a durable `SnapshotVault` (survives this process
    exiting -- needed later by `rollback_settings_hook()`), write the
    settings file atomically, THEN write the ledger row atomically. Both
    writes are individually all-or-nothing (`AnchoredProject.atomic_write`'s
    mkstemp/fsync/`os.replace`), so an interruption ANYWHERE never leaves a
    half-written file -- at worst it leaves the settings file carrying our
    `_copilot_source` tag with no matching ledger row yet, which
    `list_sources()` reports as `"orphaned"` rather than `"clean"`.
    """
    target = settings_target(scope)
    state_root = _resolve_state_root(_state_root)
    mutation_id = derive_mutation_id(SETTINGS_HOOK_KIND, source, component, target)

    try:
        with project_lock(project_path, lock_root=state_root / "locks") as anchored:
            if not force and anchored.fingerprint(DISABLED_MARKER) != fingerprint_missing():
                return ApplyOutcome(
                    "disabled",
                    None,
                    f"Hook registration is disabled for this project ({DISABLED_MARKER} "
                    "is present); remove that marker (or run `cc settings-hook add "
                    "--force`) to re-enable it.",
                )
            lock_document = read_project_lock(anchored.path / PROJECT_LOCK_FILENAME)
            mutations = read_mutations(lock_document)
            existing = find_mutation(mutations, mutation_id)
            current_fp = anchored.fingerprint(target)

            if existing is not None:
                recorded_after = existing.get("snapshot", {}).get("fingerprint_after")
                if current_fp != recorded_after:
                    return ApplyOutcome(
                        "conflict",
                        existing,
                        "The settings file changed since this mutation was applied; "
                        "refusing to overwrite it. Run `cc settings-hook rollback` or "
                        "resolve the conflict by hand.",
                    )

            try:
                current_bytes = anchored.read_bytes(target)
            except FileNotFoundError:
                current_bytes = None
            target_existed_before = current_bytes is not None

            try:
                current_settings = (
                    json.loads(current_bytes.decode("utf-8")) if current_bytes else {}
                )
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                return ApplyOutcome(
                    "blocked", None, f"The settings file is not valid JSON: {exc}"
                )
            if not isinstance(current_settings, dict):
                return ApplyOutcome(
                    "blocked", None, "The settings file does not contain a JSON object."
                )

            merged, actions = merge_hook_entries(current_settings, entries, source=source)
            new_bytes = _canonical_settings_bytes(merged)
            file_changes = new_bytes != (current_bytes or b"")

            if existing is not None and not file_changes:
                return ApplyOutcome(
                    "unchanged", existing, "Already applied; no changes needed.", tuple(actions)
                )

            if dry_run:
                status = "applied" if file_changes else "adopted"
                return ApplyOutcome(
                    status,
                    None,
                    "Dry run: no changes were written.",
                    tuple(actions),
                )

            fingerprint_before = current_fp
            vault_ref = f"{mutation_id}/{secrets.token_hex(8)}"
            if file_changes:
                vault = SnapshotVault(_vault_dir(state_root, vault_ref))
                vault.capture(anchored, target)
                _write_journal(
                    state_root,
                    mutation_id,
                    {
                        "schema_version": "1.0",
                        "mutation_id": mutation_id,
                        "target": target,
                        "phase": "settings-planned",
                        "vault_ref": vault_ref,
                    },
                )
                anchored.atomic_write(target, new_bytes)
                _write_journal(
                    state_root,
                    mutation_id,
                    {
                        "schema_version": "1.0",
                        "mutation_id": mutation_id,
                        "target": target,
                        "phase": "settings-written",
                        "vault_ref": vault_ref,
                    },
                )
                fingerprint_after = anchored.fingerprint(target)
            else:
                # Adopting entries that already matched byte-for-byte (e.g.
                # a re-apply after a crash left the file tagged but the
                # ledger row missing) -- no settings write needed.
                vault_ref = None
                fingerprint_after = current_fp

            mutation = {
                "id": mutation_id,
                "kind": SETTINGS_HOOK_KIND,
                "source": source,
                "component": component,
                "target": target,
                "target_existed_before": target_existed_before,
                "applied_at": _utc_now(),
                "applied_by": applied_by,
                "snapshot": {
                    "vault_ref": vault_ref,
                    "fingerprint_before": fingerprint_before,
                    "fingerprint_after": fingerprint_after,
                },
                "entries": [entry.as_dict() for entry in entries],
            }
            new_mutations = [m for m in mutations if m.get("id") != mutation_id]
            new_mutations.append(mutation)
            updated_lock = _write_mutations(lock_document, new_mutations)
            lock_bytes = serialize_project_lock(updated_lock)
            anchored.atomic_write(PROJECT_LOCK_FILENAME, lock_bytes)

            if file_changes:
                _write_journal(
                    state_root,
                    mutation_id,
                    {
                        "schema_version": "1.0",
                        "mutation_id": mutation_id,
                        "target": target,
                        "phase": "completed",
                        "vault_ref": vault_ref,
                    },
                )

            status = "applied" if file_changes else "adopted"
            return ApplyOutcome(status, mutation, f"Mutation {status}.", tuple(actions))
    except (ProjectLockError, UnsafeProjectPath, SnapshotError) as exc:
        return ApplyOutcome("blocked", None, str(exc))


@dataclass(frozen=True)
class RemoveResult:
    status: str  # "removed" | "not-found" | "conflict" | "blocked"
    mutation: Optional[dict[str, Any]]
    detail: str
    removed_entries: tuple[str, ...] = ()
    not_found_entries: tuple[str, ...] = ()


def remove_settings_hook(
    project_path: Path | str,
    *,
    mutation_id: str,
    disable: bool = False,
    _state_root: Optional[Path] = None,
) -> RemoveResult:
    """Surgical removal: strip only the fingerprint-matched inner hooks
    this mutation recorded, then drop its ledger row. Unlike
    `rollback_settings_hook()` this never requires the whole file to still
    match a prior byte-exact snapshot -- entries the user has since hand-
    edited are reported in `not_found_entries` rather than silently
    skipped or forced.

    `disable=True` (`cc settings-hook remove --disable`) additionally
    writes `DISABLED_MARKER` in the SAME locked transaction as the removal
    -- this is the one-command "clean uninstall that survives re-running
    setup": both `apply_settings_hook()` (this module) and
    `reconciliation_recipes.py::_claude_setup()` check for that marker
    before EVER re-registering or re-materializing the shim, so a future
    `cc reconcile apply` / `cc update --project` / `cc settings-hook add`
    does not silently resurrect a registration a human explicitly turned
    off. Without `--disable`, a plain `remove` is NOT sticky by design --
    it is the surgical undo of one registration, not an opt-out; the next
    setup/repair run is free to re-register (matching every other
    framework-owned path's existing "missing means add it back" behavior).
    """
    state_root = _resolve_state_root(_state_root)
    if not _MUTATION_ID.fullmatch(mutation_id):
        return RemoveResult("not-found", None, "Not a valid mutation id.")

    try:
        with project_lock(project_path, lock_root=state_root / "locks") as anchored:
            lock_document = read_project_lock(anchored.path / PROJECT_LOCK_FILENAME)
            mutations = read_mutations(lock_document)
            mutation = find_mutation(mutations, mutation_id)
            if mutation is None:
                return RemoveResult("not-found", None, "No such mutation is recorded.")
            if mutation.get("kind") != SETTINGS_HOOK_KIND:
                return RemoveResult(
                    "blocked", mutation, "This mutation is not a settings-hook mutation."
                )

            target = str(mutation["target"])
            entries = [
                HookEntrySpec(e["event"], e["matcher"], e["command"])
                for e in mutation.get("entries", [])
            ]

            try:
                current_bytes = anchored.read_bytes(target)
            except FileNotFoundError:
                current_bytes = None

            if current_bytes is not None:
                try:
                    current_settings = json.loads(current_bytes.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    return RemoveResult(
                        "blocked", mutation, f"The settings file is not valid JSON: {exc}"
                    )
                if not isinstance(current_settings, dict):
                    return RemoveResult(
                        "blocked", mutation, "The settings file does not contain a JSON object."
                    )
                removal = remove_hook_entries(current_settings, entries)
                if not removal.settings and not mutation.get("target_existed_before", True):
                    anchored.remove(target)
                else:
                    anchored.atomic_write(target, _canonical_settings_bytes(removal.settings))
                removed_entries = removal.removed
                not_found_entries = removal.not_found
            else:
                removed_entries = ()
                not_found_entries = tuple(entry.fingerprint() for entry in entries)

            new_mutations = [m for m in mutations if m.get("id") != mutation_id]
            updated_lock = _write_mutations(lock_document, new_mutations)
            anchored.atomic_write(PROJECT_LOCK_FILENAME, serialize_project_lock(updated_lock))

            detail = "Mutation entries removed and the ledger row dropped."
            if disable:
                anchored.atomic_write(DISABLED_MARKER, b"")
                detail += (
                    f" {DISABLED_MARKER} was written; future setup/repair runs will not "
                    "re-register hooks for this project until that marker is removed."
                )

            return RemoveResult(
                "removed",
                mutation,
                detail,
                removed_entries,
                not_found_entries,
            )
    except (ProjectLockError, UnsafeProjectPath) as exc:
        return RemoveResult("blocked", None, str(exc))


@dataclass(frozen=True)
class RollbackResult:
    status: str  # "restored" | "conflict" | "mismatch" | "unreadable" | "not-found" | "unavailable" | "blocked"
    mutation: Optional[dict[str, Any]]
    detail: str


def rollback_settings_hook(
    project_path: Path | str,
    *,
    mutation_id: str,
    _state_root: Optional[Path] = None,
) -> RollbackResult:
    """Byte-exact revert via `SnapshotVault.restore()`'s compare-and-swap:
    restores the target to precisely its pre-mutation content ONLY if the
    target's current fingerprint still equals what this mutation last wrote
    (`snapshot.fingerprint_after`). If a human (or anything else) has
    edited the file since, the vault reports `"conflict"` and the file is
    left untouched -- skip-and-flag, never a silent overwrite.
    """
    state_root = _resolve_state_root(_state_root)
    if not _MUTATION_ID.fullmatch(mutation_id):
        return RollbackResult("not-found", None, "Not a valid mutation id.")

    try:
        with project_lock(project_path, lock_root=state_root / "locks") as anchored:
            lock_document = read_project_lock(anchored.path / PROJECT_LOCK_FILENAME)
            mutations = read_mutations(lock_document)
            mutation = find_mutation(mutations, mutation_id)
            if mutation is None:
                return RollbackResult("not-found", None, "No such mutation is recorded.")
            if mutation.get("kind") != SETTINGS_HOOK_KIND:
                return RollbackResult(
                    "blocked", mutation, "This mutation is not a settings-hook mutation."
                )

            target = str(mutation["target"])
            snapshot = mutation.get("snapshot", {})
            vault_ref = snapshot.get("vault_ref")
            fingerprint_after = snapshot.get("fingerprint_after")
            if not vault_ref or not fingerprint_after:
                # Nothing was ever written to the file for this mutation
                # (an "adopted" no-op apply) -- just drop the ledger row.
                new_mutations = [m for m in mutations if m.get("id") != mutation_id]
                updated_lock = _write_mutations(lock_document, new_mutations)
                anchored.atomic_write(
                    PROJECT_LOCK_FILENAME, serialize_project_lock(updated_lock)
                )
                return RollbackResult(
                    "restored", mutation, "No file write was recorded; ledger row dropped."
                )

            try:
                vault = SnapshotVault(state_root / "vaults" / vault_ref)
            except SnapshotError as exc:
                return RollbackResult("unavailable", mutation, str(exc))

            outcome = vault.restore(
                anchored, target, expected_current_fingerprint=fingerprint_after
            )
            if outcome.status != "restored":
                return RollbackResult(outcome.status, mutation, outcome.detail)

            new_mutations = [m for m in mutations if m.get("id") != mutation_id]
            updated_lock = _write_mutations(lock_document, new_mutations)
            anchored.atomic_write(PROJECT_LOCK_FILENAME, serialize_project_lock(updated_lock))
            vault.cleanup_contents()

            return RollbackResult("restored", mutation, outcome.detail)
    except (ProjectLockError, UnsafeProjectPath) as exc:
        return RollbackResult("blocked", None, str(exc))


def list_sources(
    project_path: Path | str, *, _state_root: Optional[Path] = None
) -> dict[str, Any]:
    """Read-only report of every hook entry found in every target this
    project's ledger has ever written to, classified `"ours"` (fingerprint
    matches a live ledger row), `"orphaned"` (carries our
    `_copilot_source` tag but no matching ledger row -- the crash-window
    signature described in the module docstring), or `"foreign"` (neither).
    """
    state_root = _resolve_state_root(_state_root)
    with project_lock(project_path, lock_root=state_root / "locks") as anchored:
        lock_document = read_project_lock(anchored.path / PROJECT_LOCK_FILENAME)
        mutations = [
            m for m in read_mutations(lock_document) if m.get("kind") == SETTINGS_HOOK_KIND
        ]
        ledger_fp_index: dict[str, str] = {}
        for mutation in mutations:
            for entry in mutation.get("entries", []):
                fp = entry.get("spec_fingerprint")
                if isinstance(fp, str):
                    ledger_fp_index[fp] = str(mutation["id"])

        targets = sorted({str(m["target"]) for m in mutations}) or [
            settings_target("project")
        ]
        rows: list[dict[str, Any]] = []
        for target in targets:
            try:
                raw = anchored.read_bytes(target)
            except FileNotFoundError:
                continue
            try:
                settings = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                rows.append({"target": target, "status": "unreadable"})
                continue
            hooks = settings.get("hooks") if isinstance(settings, dict) else None
            if not isinstance(hooks, dict):
                continue
            for event, group_list in hooks.items():
                if not isinstance(group_list, list):
                    continue
                for group in group_list:
                    if not isinstance(group, Mapping):
                        continue
                    matcher = _effective_matcher(group)
                    inner_hooks = group.get("hooks")
                    if not isinstance(inner_hooks, list):
                        continue
                    for inner in inner_hooks:
                        if not isinstance(inner, Mapping):
                            continue
                        command = str(inner.get("command", ""))
                        fp = spec_fingerprint(event, matcher, command)
                        mutation_id = ledger_fp_index.get(fp)
                        if mutation_id is not None:
                            classification = "ours"
                        elif inner.get(_COPILOT_SOURCE_KEY):
                            classification = "orphaned"
                        else:
                            classification = "foreign"
                        rows.append(
                            {
                                "target": target,
                                "event": event,
                                "matcher": matcher,
                                "command": command,
                                "classification": classification,
                                "mutation_id": mutation_id,
                            }
                        )
        return {
            "schema_version": "1.0",
            "path": str(anchored.path),
            "hooks": rows,
        }


__all__ = [
    "ApplyOutcome",
    "DEFAULT_HOOK_ENTRIES",
    "HookEntrySpec",
    "MergeAction",
    "MutationConflict",
    "MutationLedgerError",
    "RemovalResult",
    "RemoveResult",
    "RollbackResult",
    "apply_settings_hook",
    "canonical_settings_bytes",
    "derive_mutation_id",
    "find_mutation",
    "list_sources",
    "merge_hook_entries",
    "read_mutations",
    "remove_hook_entries",
    "remove_settings_hook",
    "rollback_settings_hook",
    "settings_target",
    "spec_fingerprint",
]
