"""Guarded executor for immutable reconciliation recipe plans.

Planning code emits typed, immutable recipe operations and performs no writes.
``transaction_plan_from_recipe`` converts that data to the executor's closed
operation vocabulary. ``execute_reconciliation`` then owns identity binding,
locking, containment, source verification, durable snapshots, an fsynced
journal, actual filesystem mutation, fresh verification, compare-and-swap
rollback, and one durable project receipt before advancing a batch.

The optional boundary observer exists only for deterministic tests. It is an
in-process callback, is never exposed as a CLI flag, and cannot change an
operation. Production mutation never accepts a Path/shutil callback.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from cc.core.config_paths import machine_diagnostics_root
from cc.core.ecosystem.project_locking import (
    AnchoredProject,
    BoundaryObserver,
    ProjectIdentity,
    ProjectIdentityMismatch,
    ProjectLockContention,
    ProjectLockError,
    UnsafeProjectPath,
    atomic_json_write,
    ensure_private_directory,
    fingerprint_file_payload,
    fingerprint_symlink,
    fsync_directory,
    inspect_project_identity,
    normalize_relative_target,
    project_lock,
)
from cc.core.ecosystem.project_snapshots import (
    RollbackOutcome,
    SnapshotError,
    SnapshotVault,
)
from cc.core.ecosystem.reconciliation_diagnostics import append_project_receipt
from cc.core.ecosystem.reconciliation_types import RecipeOperationKind

_RUN_ID = re.compile(r"^run_[0-9a-f]{32}$")
_PROJECT_JOURNAL_DIR = re.compile(r"^project-[0-9a-f]{64}$")
_OPERATION_ID = re.compile(r"^op_[0-9a-f]{64}$")
_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMPONENTS = {"claude", "codex"}
_KINDS = {item.value for item in RecipeOperationKind}


class ReconciliationTransactionError(RuntimeError):
    """A transaction guard or typed operation refused to proceed."""


class DurableReceiptUnavailable(ReconciliationTransactionError):
    """A project outcome could not be fsynced before advancing the batch."""


Verifier = Callable[[AnchoredProject], bool]


@dataclass(frozen=True)
class TransactionOperation:
    id: str
    kind: str
    component: str
    target: str
    expected_before_fingerprint: str
    source_fingerprint: Optional[str]
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectPreflightSpec:
    inspection_id: str
    selected_components: tuple[str, ...]


@dataclass(frozen=True)
class ProjectTransactionPlan:
    path: str
    expected_identity: ProjectIdentity | Mapping[str, Any]
    operations: tuple[TransactionOperation, ...]
    verification: Optional[Verifier] = None
    inspection_id: Optional[str] = None
    preflight: Optional[ProjectPreflightSpec] = None
    sources: tuple[dict[str, str], ...] = ()


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "as_dict"):
        value = value.as_dict()
    if not isinstance(value, Mapping):
        raise ReconciliationTransactionError("A recipe payload must be an object.")
    try:
        return json.loads(json.dumps(dict(value), sort_keys=True, ensure_ascii=True))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ReconciliationTransactionError(
            "A recipe payload is not JSON-compatible."
        ) from exc


def _lock_component_entries(
    operation: TransactionOperation,
) -> tuple[dict[str, Any], ...]:
    raw = operation.payload.get("component_entry")
    if isinstance(raw, Mapping):
        candidates: Sequence[Any] = (raw,)
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        candidates = raw
    else:
        raise ReconciliationTransactionError("A lock component entry is invalid.")
    entries: list[dict[str, Any]] = []
    components: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ReconciliationTransactionError("A lock component entry is invalid.")
        component = candidate.get("component")
        if component not in _COMPONENTS or component in components:
            raise ReconciliationTransactionError("Lock component entries are invalid.")
        components.add(str(component))
        entries.append(dict(candidate))
    if not entries:
        raise ReconciliationTransactionError("A lock component entry is invalid.")
    return tuple(entries)


def _targeted_components(
    operations: Sequence[TransactionOperation],
) -> frozenset[str]:
    components = {operation.component for operation in operations}
    for operation in operations:
        if operation.kind == RecipeOperationKind.UPSERT_LOCK_COMPONENT.value:
            components.update(
                str(entry["component"]) for entry in _lock_component_entries(operation)
            )
    return frozenset(components)


def _validate_operation(operation: TransactionOperation) -> TransactionOperation:
    if not _OPERATION_ID.fullmatch(operation.id):
        raise ReconciliationTransactionError("A recipe operation id is invalid.")
    if operation.kind not in _KINDS or operation.component not in _COMPONENTS:
        raise ReconciliationTransactionError(
            "A recipe operation uses an unsupported type."
        )
    normalize_relative_target(operation.target)
    if not _FINGERPRINT.fullmatch(operation.expected_before_fingerprint):
        raise ReconciliationTransactionError("A recipe before-fingerprint is invalid.")
    if operation.source_fingerprint is not None and not _FINGERPRINT.fullmatch(
        operation.source_fingerprint
    ):
        raise ReconciliationTransactionError("A recipe source fingerprint is invalid.")
    return operation


def transaction_plan_from_recipe(
    recipe_plan: Any, *, verifier: Optional[Verifier] = None
) -> ProjectTransactionPlan:
    """Detach one immutable planner object into validated transaction data."""
    path = _value(recipe_plan, "path")
    if not isinstance(path, str) or not path:
        raise ReconciliationTransactionError("A recipe plan has no project path.")
    expected_identity = _value(recipe_plan, "expected_identity")
    if expected_identity is None:
        expected_identity = _value(recipe_plan, "root_identity")
    if expected_identity is None:
        expected_identity = inspect_project_identity(path)
    raw_operations = _value(recipe_plan, "operations", ())
    if not isinstance(raw_operations, Sequence) or isinstance(
        raw_operations, (str, bytes)
    ):
        raise ReconciliationTransactionError("A recipe plan has invalid operations.")
    operations: list[TransactionOperation] = []
    for raw in raw_operations:
        raw_kind = _value(raw, "kind")
        kind = getattr(raw_kind, "value", raw_kind)
        target = _value(raw, "target", _value(raw, "relative_target"))
        payload = _value(raw, "payload", {})
        operation = TransactionOperation(
            id=str(_value(raw, "id")),
            kind=str(kind),
            component=str(_value(raw, "component")),
            target=str(target),
            expected_before_fingerprint=str(_value(raw, "expected_before_fingerprint")),
            source_fingerprint=(
                str(_value(raw, "source_fingerprint"))
                if _value(raw, "source_fingerprint") is not None
                else None
            ),
            payload=_mapping(payload),
        )
        operations.append(_validate_operation(operation))
    if len({operation.id for operation in operations}) != len(operations):
        raise ReconciliationTransactionError("A recipe plan repeats an operation id.")
    if len({operation.target for operation in operations}) != len(operations):
        raise ReconciliationTransactionError(
            "A project plan must combine changes to the same target into one operation."
        )
    raw_sources = _value(recipe_plan, "sources", ())
    if not isinstance(raw_sources, Sequence) or isinstance(raw_sources, (str, bytes)):
        raise ReconciliationTransactionError(
            "A recipe plan has invalid source bindings."
        )
    sources: list[dict[str, str]] = []
    seen_source_components: set[str] = set()
    for raw_source in raw_sources:
        if not isinstance(raw_source, Mapping) or set(raw_source) != {
            "component",
            "version",
            "fingerprint",
        }:
            raise ReconciliationTransactionError(
                "A recipe plan has invalid source bindings."
            )
        component = raw_source.get("component")
        version = raw_source.get("version")
        fingerprint = raw_source.get("fingerprint")
        if (
            component not in _COMPONENTS
            or component in seen_source_components
            or not isinstance(version, str)
            or not version
            or not isinstance(fingerprint, str)
            or not _FINGERPRINT.fullmatch(fingerprint)
        ):
            raise ReconciliationTransactionError(
                "A recipe plan has invalid source bindings."
            )
        seen_source_components.add(str(component))
        sources.append(
            {
                "component": str(component),
                "version": version,
                "fingerprint": fingerprint,
            }
        )
    allowed_targets = _value(recipe_plan, "allowed_targets", ())
    if (
        not isinstance(allowed_targets, Sequence)
        or isinstance(allowed_targets, (str, bytes))
        or any(operation.target not in allowed_targets for operation in operations)
    ):
        raise ReconciliationTransactionError(
            "A recipe operation is outside its reviewed preservation boundary."
        )
    if verifier is None:
        targeted_components = _targeted_components(operations)

        def verifier(anchored: AnchoredProject) -> bool:
            from cc.core.ecosystem.project_integration import (
                inspect_project_integration,
            )

            report = inspect_project_integration(anchored.path, detail=True)
            states = {
                str(item.get("component")): str(item.get("classification"))
                for item in report.get("components", [])
                if isinstance(item, Mapping)
            }
            return all(
                states.get(component) == "ready" for component in targeted_components
            )

    inspection_id = _value(recipe_plan, "inspection_id")
    raw_selected = _value(recipe_plan, "selected_components")
    if (
        not isinstance(inspection_id, str)
        or not _FINGERPRINT.fullmatch(inspection_id)
        or not isinstance(raw_selected, Sequence)
        or isinstance(raw_selected, (str, bytes))
        or not raw_selected
        or any(component not in _COMPONENTS for component in raw_selected)
        or len(raw_selected) != len(set(raw_selected))
    ):
        raise ReconciliationTransactionError(
            "A recipe plan has invalid fresh-preflight evidence."
        )
    preflight = ProjectPreflightSpec(
        inspection_id=inspection_id,
        selected_components=tuple(str(component) for component in raw_selected),
    )

    return ProjectTransactionPlan(
        path=path,
        expected_identity=expected_identity,
        operations=tuple(operations),
        verification=verifier,
        inspection_id=inspection_id,
        preflight=preflight,
        sources=tuple(sources),
    )


def fingerprint_recipe_source(
    path: Path | str, *, tree: bool = False, mode: Optional[int] = None
) -> str:
    """Shared source fingerprint used by planners and the guarded executor."""
    source = Path(path).expanduser()
    if tree:
        descriptor = _open_source_descriptor(source, directory=True)
        try:
            manifest = _capture_tree_manifest(descriptor)
        finally:
            os.close(descriptor)
        return _tree_fingerprint(manifest, mode=mode or 0o755)
    content, _ = _read_source_file(source)
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _open_source_descriptor(source: Path, *, directory: bool) -> int:
    if not source.is_absolute():
        raise ReconciliationTransactionError("Recipe sources must be absolute paths.")
    descriptor = os.open(
        "/",
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        for index, part in enumerate(source.parts[1:]):
            final = index == len(source.parts[1:]) - 1
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            if not final or directory:
                flags |= getattr(os, "O_DIRECTORY", 0)
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        source_stat = os.fstat(descriptor)
        if directory and not stat.S_ISDIR(source_stat.st_mode):
            raise ReconciliationTransactionError("A recipe tree source is unavailable.")
        if not directory and not stat.S_ISREG(source_stat.st_mode):
            raise ReconciliationTransactionError("A recipe file source is unavailable.")
        return descriptor
    except (OSError, ReconciliationTransactionError) as exc:
        os.close(descriptor)
        if isinstance(exc, ReconciliationTransactionError):
            raise
        raise ReconciliationTransactionError(
            "A recipe source is symlinked or unavailable."
        ) from exc


def _read_descriptor(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _read_source_file(source: Path) -> tuple[bytes, int]:
    descriptor = _open_source_descriptor(source, directory=False)
    try:
        source_stat = os.fstat(descriptor)
        return _read_descriptor(descriptor), stat.S_IMODE(source_stat.st_mode)
    finally:
        os.close(descriptor)


def _write_staged_file(path: Path, content: bytes, mode: int) -> None:
    descriptor = os.open(
        path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _capture_tree_manifest(
    descriptor: int,
    *,
    destination: Optional[Path] = None,
    prefix: str = "",
) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for name in sorted(os.listdir(descriptor)):
        item = f"{prefix}/{name}" if prefix else name
        source_stat = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        mode = stat.S_IMODE(source_stat.st_mode)
        if stat.S_ISREG(source_stat.st_mode):
            child = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=descriptor,
            )
            try:
                content = _read_descriptor(child)
            finally:
                os.close(child)
            rows.append([item, "file", mode, hashlib.sha256(content).hexdigest()])
            if destination is not None:
                _write_staged_file(destination / name, content, mode)
        elif stat.S_ISDIR(source_stat.st_mode):
            rows.append([item, "directory", mode])
            child = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=descriptor,
            )
            child_destination = destination / name if destination is not None else None
            if child_destination is not None:
                child_destination.mkdir(mode=mode)
                child_destination.chmod(mode)
            try:
                rows.extend(
                    _capture_tree_manifest(
                        child,
                        destination=child_destination,
                        prefix=item,
                    )
                )
            finally:
                os.close(child)
            if child_destination is not None:
                fsync_directory(child_destination)
        else:
            raise ReconciliationTransactionError(
                "A recipe tree source contains a symlink or special file."
            )
    return rows


def _tree_fingerprint(manifest: Sequence[Sequence[Any]], *, mode: int) -> str:
    encoded = json.dumps(
        ["directory", mode, list(manifest)],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _stage_tree_source(source: Path, destination: Path, *, mode: int) -> str:
    ensure_private_directory(destination, boundary=destination.parent)
    descriptor = _open_source_descriptor(source, directory=True)
    try:
        manifest = _capture_tree_manifest(descriptor, destination=destination)
    finally:
        os.close(descriptor)
    fsync_directory(destination)
    return _tree_fingerprint(manifest, mode=mode)


def _closed_payload(operation: TransactionOperation) -> dict[str, Any]:
    payload = dict(operation.payload)
    kind = operation.kind
    allowed: set[str]
    required: set[str]
    if kind in {
        RecipeOperationKind.CREATE_FILE_FROM_SOURCE.value,
        RecipeOperationKind.COPY_FILE_FROM_SOURCE.value,
    }:
        required, allowed = {"source_path"}, {"source_path", "mode"}
    elif kind in {
        RecipeOperationKind.COPY_TREE_FROM_SOURCE.value,
        RecipeOperationKind.REPLACE_RECOGNIZED_SYMLINK_WITH_COPY.value,
    }:
        required, allowed = {"source_path"}, {"source_path"}
    elif kind == RecipeOperationKind.APPEND_MANAGED_BLOCK.value:
        required, allowed = {"block"}, {"block", "mode"}
    elif kind == RecipeOperationKind.MERGE_JSON_KEYS.value:
        required, allowed = {"keys"}, {"keys"}
    elif kind == RecipeOperationKind.CREATE_INTERNAL_RELATIVE_SYMLINK.value:
        required, allowed = {"link_target"}, {"link_target"}
    elif kind == RecipeOperationKind.UPSERT_LOCK_COMPONENT.value:
        required, allowed = {"component_entry"}, {
            "component_entry",
            "replace_ecosystem_lock",
        }
    elif kind in {
        RecipeOperationKind.WRITE_PROJECT_DECLARATION.value,
        RecipeOperationKind.ASSOCIATE_PERSONAL_PROJECT.value,
    }:
        required, allowed = {"document"}, {"document"}
    elif kind == RecipeOperationKind.REGISTER_SETTINGS_HOOKS.value:
        required, allowed = {"entries", "source"}, {"entries", "source"}
    else:
        raise ReconciliationTransactionError("A typed recipe operation is unsupported.")
    if set(payload) != allowed.intersection(payload) or not required <= set(payload):
        raise ReconciliationTransactionError(
            "A typed recipe payload has unsupported fields."
        )
    return payload


def _existing_mode(project: AnchoredProject, target: str, fallback: int) -> int:
    target_stat = project.lstat(target)
    if target_stat is not None and stat.S_ISREG(target_stat.st_mode):
        return stat.S_IMODE(target_stat.st_mode)
    return fallback


def _canonical_document(value: Any) -> bytes:
    if not isinstance(value, Mapping):
        raise ReconciliationTransactionError("A typed JSON document must be an object.")
    return (json.dumps(dict(value), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _looks_like_ecosystem_lock(raw: Any) -> bool:
    if not isinstance(raw, dict) or not raw or "components" in raw:
        return False
    metadata = [
        value.get("_meta")
        for value in raw.values()
        if isinstance(value, dict) and isinstance(value.get("_meta"), dict)
    ]
    return len(metadata) == len(raw) and all(
        item.get("product") in {"knowledge", "cli", "claude", "codex"}
        and isinstance(item.get("role"), str)
        and item.get("tier") in {"personal", "department", "organization", "foundation"}
        and (
            item.get("source_sha") is None
            or (
                isinstance(item.get("source_sha"), str)
                and len(item["source_sha"]) == 40
            )
        )
        for item in metadata
    )


@dataclass(frozen=True)
class _PreparedMutation:
    expected_after: str
    apply: Callable[[], None]


def _prepare_mutation(
    project: AnchoredProject,
    operation: TransactionOperation,
    *,
    staging_root: Path,
) -> _PreparedMutation:
    payload = _closed_payload(operation)
    kind = operation.kind
    target = operation.target
    if kind in {
        RecipeOperationKind.CREATE_FILE_FROM_SOURCE.value,
        RecipeOperationKind.COPY_FILE_FROM_SOURCE.value,
    }:
        source = Path(str(payload["source_path"])).expanduser()
        content, source_mode = _read_source_file(source)
        mode = int(payload.get("mode", source_mode))
        if (
            "sha256:" + hashlib.sha256(content).hexdigest()
            != operation.source_fingerprint
        ):
            raise ReconciliationTransactionError(
                "A recipe file source changed after review."
            )
        return _PreparedMutation(
            fingerprint_file_payload(content, mode=mode),
            lambda: project.atomic_write(target, content, mode=mode),
        )
    if kind in {
        RecipeOperationKind.COPY_TREE_FROM_SOURCE.value,
        RecipeOperationKind.REPLACE_RECOGNIZED_SYMLINK_WITH_COPY.value,
    }:
        source = Path(str(payload["source_path"])).expanduser()
        mode = int(payload.get("mode", 0o755))
        staged = staging_root / operation.id
        expected = _stage_tree_source(source, staged, mode=mode)
        if expected != operation.source_fingerprint:
            raise ReconciliationTransactionError(
                "A recipe tree source changed after review."
            )
        return _PreparedMutation(
            expected,
            lambda: project.install_tree(target, staged, mode=mode),
        )
    if kind == RecipeOperationKind.APPEND_MANAGED_BLOCK.value:
        block = payload["block"]
        if not isinstance(block, str) or not block:
            raise ReconciliationTransactionError(
                "A managed block must be non-empty text."
            )
        try:
            current = project.read_bytes(target)
        except FileNotFoundError:
            current = b""
        block_bytes = block.encode("utf-8")
        if block_bytes in current:
            content = current
        else:
            separator = (
                b""
                if not current or current.endswith(b"\n\n")
                else (b"\n" if current.endswith(b"\n") else b"\n\n")
            )
            content = current + separator + block_bytes
        mode = int(payload.get("mode", _existing_mode(project, target, 0o644)))
        return _PreparedMutation(
            fingerprint_file_payload(content, mode=mode),
            lambda: project.atomic_write(target, content, mode=mode),
        )
    if kind == RecipeOperationKind.MERGE_JSON_KEYS.value:
        keys = payload["keys"]
        if not isinstance(keys, Mapping):
            raise ReconciliationTransactionError("JSON merge keys must be an object.")
        try:
            current_json = json.loads(project.read_bytes(target).decode("utf-8"))
        except FileNotFoundError:
            current_json = {}
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ReconciliationTransactionError(
                "The target JSON is unreadable."
            ) from exc
        if not isinstance(current_json, dict):
            raise ReconciliationTransactionError("The target JSON is not an object.")
        current_json.update(dict(keys))
        content = _canonical_document(current_json)
        mode = int(payload.get("mode", _existing_mode(project, target, 0o644)))
        return _PreparedMutation(
            fingerprint_file_payload(content, mode=mode),
            lambda: project.atomic_write(target, content, mode=mode),
        )
    if kind == RecipeOperationKind.CREATE_INTERNAL_RELATIVE_SYMLINK.value:
        link_target = payload["link_target"]
        if not isinstance(link_target, str) or not link_target:
            raise ReconciliationTransactionError("An internal link target is invalid.")
        return _PreparedMutation(
            fingerprint_symlink(link_target),
            lambda: project.atomic_symlink(target, link_target),
        )
    if kind == RecipeOperationKind.UPSERT_LOCK_COMPONENT.value:
        entries = _lock_component_entries(operation)
        try:
            document = json.loads(project.read_bytes(target).decode("utf-8"))
        except FileNotFoundError:
            document = {"schema_version": "1.0", "components": []}
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ReconciliationTransactionError(
                "The project lock is unreadable."
            ) from exc
        if not isinstance(document, dict) or not isinstance(document.get("components"), list):
            if payload.get("replace_ecosystem_lock") is True and _looks_like_ecosystem_lock(document):
                document = {"schema_version": "1.0", "components": []}
            else:
                raise ReconciliationTransactionError(
                    "The project lock has an unsupported shape."
                )
        components = {str(entry["component"]) for entry in entries}
        document["components"] = [
            item
            for item in document["components"]
            if not isinstance(item, dict) or item.get("component") not in components
        ] + list(entries)
        document["components"].sort(key=lambda item: str(item.get("component", "")))
        content = _canonical_document(document)
        mode = int(payload.get("mode", _existing_mode(project, target, 0o644)))
        return _PreparedMutation(
            fingerprint_file_payload(content, mode=mode),
            lambda: project.atomic_write(target, content, mode=mode),
        )
    if kind in {
        RecipeOperationKind.WRITE_PROJECT_DECLARATION.value,
        RecipeOperationKind.ASSOCIATE_PERSONAL_PROJECT.value,
    }:
        content = _canonical_document(payload["document"])
        mode = int(payload.get("mode", _existing_mode(project, target, 0o644)))
        return _PreparedMutation(
            fingerprint_file_payload(content, mode=mode),
            lambda: project.atomic_write(target, content, mode=mode),
        )
    if kind == RecipeOperationKind.REGISTER_SETTINGS_HOOKS.value:
        # Delegates structural merge to item-2's PURE function
        # (`mutations.merge_hook_entries`) rather than reimplementing it --
        # a settings file is NOT a framework-owned path (see this module's
        # own header on why `.claude/settings.json` structurally cannot be
        # a `files[]`/`ownership: framework` lock entry), so it gets the
        # SAME atomic-write/snapshot/rollback guarantee every other
        # operation in this engine gets, without a second, weaker merge
        # path. This operation writes ONLY the settings file -- the
        # `mutations[]` ledger row is intentionally NOT written here (an
        # engine invariant enforced by `execute_reconciliation()`: one
        # operation per target, and `copilot.lock.json` already has its
        # own `UPSERT_LOCK_COMPONENT` operation in the same plan). The
        # ledger row is appended by a follow-up, lock-free call to
        # `apply_settings_hook(..., dry_run=False)` made AFTER this whole
        # transaction commits (see `commands/reconcile.py`'s `apply()`) --
        # it will find the file already in its post-merge state and take
        # the existing `"adopted"` branch (ledger-only write, matching the
        # crash-window semantics `apply_settings_hook()` already documents
        # for exactly this "content written, ledger row still needed"
        # state), never a second settings write.
        from cc.core.ecosystem.mutations import (
            HookEntrySpec,
            canonical_settings_bytes,
            merge_hook_entries,
        )

        raw_entries = payload["entries"]
        if not isinstance(raw_entries, Sequence) or isinstance(raw_entries, (str, bytes)):
            raise ReconciliationTransactionError(
                "register-settings-hooks entries must be a list."
            )
        entries = tuple(
            HookEntrySpec(
                str(item["event"]), str(item["matcher"]), str(item["command"])
            )
            for item in raw_entries
        )
        source = str(payload["source"])
        try:
            current_settings = json.loads(project.read_bytes(target).decode("utf-8"))
        except FileNotFoundError:
            current_settings = {}
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ReconciliationTransactionError(
                "The settings target is not valid JSON."
            ) from exc
        if not isinstance(current_settings, dict):
            raise ReconciliationTransactionError(
                "The settings target does not contain a JSON object."
            )
        merged, _actions = merge_hook_entries(current_settings, entries, source=source)
        content = canonical_settings_bytes(merged)
        mode = int(payload.get("mode", _existing_mode(project, target, 0o644)))
        return _PreparedMutation(
            fingerprint_file_payload(content, mode=mode),
            lambda: project.atomic_write(target, content, mode=mode),
        )
    raise ReconciliationTransactionError("A typed recipe operation is unsupported.")


def _state_root(root: Optional[Path]) -> Path:
    return (root or (machine_diagnostics_root() / "reconciliation")).expanduser()


def _journal_directory(root: Path, run_id: str, project: str) -> Path:
    key = hashlib.sha256(project.encode("utf-8")).hexdigest()
    directory = root / "transactions" / run_id / f"project-{key}"
    ensure_private_directory(directory, boundary=root)
    return directory


def _observe(observer: Optional[BoundaryObserver], event: str, **context: Any) -> None:
    if observer is not None:
        observer(event, context)


def _write_journal(path: Path, journal: dict[str, Any]) -> None:
    atomic_json_write(path, journal)


def _cleanup_staged_sources(directory: Path) -> None:
    staging = directory / "prepared-sources"
    if not staging.exists():
        return
    SnapshotVault(staging).cleanup_contents()
    staging.rmdir()
    fsync_directory(directory)


def _receipt(
    path: str,
    status: str,
    completed: Sequence[str],
    verification: str,
    rollback: Sequence[RollbackOutcome],
) -> dict[str, Any]:
    details = {
        "applied": "Every targeted operation completed and fresh verification passed.",
        "blocked": "The project was left unchanged because a transaction guard refused it.",
        "rolled-back": "The project did not pass and every transaction-owned output was restored.",
        "incomplete-rollback": "At least one transaction-owned output could not be restored safely.",
        "unchanged": "The reviewed plan required no project mutation.",
    }
    return {
        "path": path,
        "status": status,
        "detail": details[status],
        "completed_operation_ids": list(completed),
        "verification": verification,
        "rollback": [item.as_dict() for item in rollback],
    }


def _exception_code(error: Exception) -> str:
    if isinstance(error, ProjectLockContention):
        return "lock-contention"
    if isinstance(error, ProjectIdentityMismatch):
        return "stale-plan"
    if isinstance(error, UnsafeProjectPath):
        return "unsafe-path"
    message = str(error).lower()
    if "preflight" in message:
        return "stale-plan"
    if "verification" in message:
        return "verification-failed"
    if "source" in message and "changed" in message:
        return "source-changed"
    if "fingerprint" in message:
        return "mutation-mismatch"
    if "path" in message or "symlink" in message or "escape" in message:
        return "unsafe-path"
    return "unexpected"


def _diagnostic_receipt(
    receipt: Mapping[str, Any],
    plan: ProjectTransactionPlan,
    project: AnchoredProject,
    vault: SnapshotVault,
    *,
    verification_state: str,
    error: Optional[Exception] = None,
) -> dict[str, Any]:
    evidence = {
        "preflight": {
            "identity_fingerprint": project.identity.fingerprint,
            "inspection_id": plan.inspection_id,
            "classification": "eligible",
            "components": [
                {
                    "component": component,
                    "classification": "selected",
                    "requirement_ids": [],
                }
                for component in sorted(_targeted_components(plan.operations))
            ],
        },
        "sources": [dict(source) for source in plan.sources],
        "targets": [
            {
                "target": snapshot.target,
                "kind": snapshot.kind,
                "before_fingerprint": snapshot.fingerprint,
            }
            for snapshot in vault.records
        ],
        "planned_operation_ids": [operation.id for operation in plan.operations],
        "post_apply_verification": [
            {
                "component": component,
                "state": verification_state,
                "evidence_ids": [],
            }
            for component in sorted(_targeted_components(plan.operations))
        ],
        "exception": (
            {
                "type": type(error).__name__,
                "code": _exception_code(error),
            }
            if error is not None
            else None
        ),
    }
    return {**dict(receipt), "diagnostic_evidence": evidence}


def _blocked_diagnostic_receipt(
    receipt: Mapping[str, Any],
    plan: ProjectTransactionPlan,
    error: Exception,
) -> dict[str, Any]:
    try:
        identity_fingerprint = ProjectIdentity.from_value(
            plan.expected_identity
        ).fingerprint
    except ProjectIdentityMismatch:
        identity_fingerprint = None
    components = _targeted_components(plan.operations)
    return {
        **dict(receipt),
        "diagnostic_evidence": {
            "preflight": {
                "identity_fingerprint": identity_fingerprint,
                "inspection_id": plan.inspection_id,
                "classification": "blocked",
                "components": [
                    {
                        "component": component,
                        "classification": "selected",
                        "requirement_ids": [],
                    }
                    for component in sorted(components)
                ],
            },
            "sources": [dict(source) for source in plan.sources],
            "targets": [
                {
                    "target": operation.target,
                    "kind": "uninspected",
                    "before_fingerprint": operation.expected_before_fingerprint,
                }
                for operation in plan.operations
            ],
            "planned_operation_ids": [operation.id for operation in plan.operations],
            "post_apply_verification": [],
            "exception": {
                "type": type(error).__name__,
                "code": _exception_code(error),
            },
        },
    }


def _rollback(
    project: AnchoredProject,
    vault: SnapshotVault,
    journal: dict[str, Any],
    *,
    observer: Optional[BoundaryObserver],
) -> list[RollbackOutcome]:
    outcomes: list[RollbackOutcome] = []
    for operation in reversed(journal["operations"]):
        if operation["status"] == "restored":
            outcomes.append(
                RollbackOutcome(
                    str(operation["target"]),
                    "restored",
                    "The target matches its saved pre-transaction fingerprint.",
                )
            )
            continue
        if operation["status"] not in {
            "applying",
            "completed",
            "rollback-failed",
        }:
            continue
        current = project.fingerprint(operation["target"])
        if operation["status"] == "applying" and current == operation["before"]:
            continue
        if current == operation["before"]:
            outcome = RollbackOutcome(
                str(operation["target"]),
                "restored",
                "The target matches its saved pre-transaction fingerprint.",
            )
        else:
            _observe(observer, "before-rollback", operation_id=operation["id"])
            outcome = vault.restore(
                project,
                operation["target"],
                expected_current_fingerprint=operation["after"],
            )
        outcomes.append(outcome)
        operation["rollback"] = outcome.as_dict()
        operation["status"] = (
            "restored" if outcome.status == "restored" else "rollback-failed"
        )
        _write_journal(Path(journal["journal_path"]), journal)
        _observe(
            observer,
            "after-rollback",
            operation_id=operation["id"],
            status=outcome.status,
        )
    return outcomes


def _owned_operation_ids(
    project: AnchoredProject, operations: Sequence[Mapping[str, Any]]
) -> list[str]:
    owned: list[str] = []
    for operation in operations:
        status = operation.get("status")
        if status == "completed":
            owned.append(str(operation["id"]))
        elif (
            status == "applying"
            and isinstance(operation.get("after"), str)
            and project.fingerprint(str(operation.get("target")))
            == operation.get("after")
        ):
            owned.append(str(operation["id"]))
    return owned


def _recovery_owned_operation_ids(
    project: AnchoredProject,
    operations: Sequence[Mapping[str, Any]],
    persisted: Optional[Mapping[str, Any]],
) -> list[str]:
    persisted_ids = (
        persisted.get("completed_operation_ids", [])
        if isinstance(persisted, Mapping)
        else []
    )
    persisted_set = {str(item) for item in persisted_ids if isinstance(item, str)}
    owned: list[str] = []
    for operation in operations:
        operation_id = str(operation.get("id"))
        status = operation.get("status")
        if operation_id in persisted_set or status in {
            "completed",
            "rollback-failed",
            "restored",
        }:
            owned.append(operation_id)
        elif (
            status == "applying"
            and isinstance(operation.get("after"), str)
            and project.fingerprint(str(operation.get("target")))
            == operation.get("after")
        ):
            owned.append(operation_id)
    return owned


def _journal_rollback_outcomes(
    operations: Sequence[Mapping[str, Any]], completed: Sequence[str]
) -> list[RollbackOutcome]:
    completed_set = set(completed)
    outcomes: list[RollbackOutcome] = []
    for operation in reversed(operations):
        if operation.get("id") not in completed_set:
            continue
        raw = operation.get("rollback")
        if isinstance(raw, Mapping) and raw.get("status") in {
            "restored",
            "mismatch",
            "conflict",
            "unreadable",
        }:
            outcomes.append(
                RollbackOutcome(
                    str(operation.get("target")),
                    str(raw["status"]),
                    str(raw.get("detail") or "Recovery outcome was persisted."),
                )
            )
        else:
            outcomes.append(
                RollbackOutcome(
                    str(operation.get("target")),
                    "unreadable",
                    "The saved target could not be restored and verified.",
                )
            )
    return outcomes


def _verify_closed_preflight(
    project: AnchoredProject, plan: ProjectTransactionPlan
) -> None:
    spec = plan.preflight
    if spec is None:
        return
    from cc.core.ecosystem.project_reconciliation import assess_project

    assessment = assess_project(
        project.path,
        approved_root=project.path,
        selected_components=spec.selected_components,
        detail=True,
    )
    selected = assessment.get("selected_components")
    allowed_routes = {
        "customized-guided-route",
        "safe-setup-available",
        "safe-update-available",
    }
    components = {
        str(item.get("component")): item
        for item in assessment.get("components", [])
        if isinstance(item, Mapping)
    }
    selected_are_actionable = bool(spec.selected_components) and all(
        components.get(component, {}).get("selected") is True
        and components.get(component, {}).get("recommended") is True
        and components.get(component, {}).get("state") in allowed_routes
        for component in spec.selected_components
    )
    if (
        assessment.get("inspection_id") != spec.inspection_id
        or not isinstance(selected, list)
        or tuple(selected) != spec.selected_components
        or (
            assessment.get("route") not in allowed_routes
            and not selected_are_actionable
        )
    ):
        raise ReconciliationTransactionError(
            "Fresh project preflight no longer matches the reviewed plan."
        )


def _execute_project(
    plan: ProjectTransactionPlan,
    *,
    run_id: str,
    state_root: Path,
    observer: Optional[BoundaryObserver],
) -> dict[str, Any]:
    completed: list[str] = []
    try:
        with project_lock(
            plan.path,
            expected_identity=plan.expected_identity,
            lock_root=state_root / "locks",
        ) as project:
            _observe(observer, "lock-acquired", project=plan.path)
            _verify_closed_preflight(project, plan)
            _observe(observer, "preflight-verified", project=plan.path)
            directory = _journal_directory(state_root, run_id, plan.path)
            journal_path = directory / "journal.json"
            vault = SnapshotVault(directory / "snapshots")
            operations = [
                {
                    "id": operation.id,
                    "kind": operation.kind,
                    "target": operation.target,
                    "before": operation.expected_before_fingerprint,
                    "after": None,
                    "status": "pending",
                    "rollback": None,
                }
                for operation in plan.operations
            ]
            journal: dict[str, Any] = {
                "schema_version": "1.0",
                "run_id": run_id,
                "project": plan.path,
                "identity": project.identity.as_dict(),
                "phase": "preparing",
                "operations": operations,
                "verification": "not-run",
                "journal_path": str(journal_path),
            }
            _write_journal(journal_path, journal)
            _observe(observer, "journal-created", project=plan.path)
            prepared: dict[str, _PreparedMutation] = {}
            staging_root = directory / "prepared-sources"
            for operation, row in zip(plan.operations, operations):
                snapshot = vault.capture(project, operation.target)
                _observe(observer, "snapshot-persisted", operation_id=operation.id)
                if snapshot.fingerprint != operation.expected_before_fingerprint:
                    raise ReconciliationTransactionError(
                        "A project target changed after the reviewed plan."
                    )
                mutation = _prepare_mutation(
                    project,
                    operation,
                    staging_root=staging_root,
                )
                row["after"] = mutation.expected_after
                prepared[operation.id] = mutation
                _write_journal(journal_path, journal)
                if operation.source_fingerprint is not None:
                    _observe(
                        observer,
                        "source-captured",
                        operation_id=operation.id,
                    )
            journal["phase"] = "prepared"
            _write_journal(journal_path, journal)
            _observe(observer, "transaction-prepared", project=plan.path)

            try:
                for operation, row in zip(plan.operations, operations):
                    row["status"] = "applying"
                    journal["phase"] = "applying"
                    _write_journal(journal_path, journal)
                    _observe(observer, "before-mutation", operation_id=operation.id)
                    prepared[operation.id].apply()
                    _observe(observer, "after-output-write", operation_id=operation.id)
                    current = project.fingerprint(operation.target)
                    if current != row["after"]:
                        raise ReconciliationTransactionError(
                            "A typed operation did not produce its planned fingerprint."
                        )
                    row["status"] = "completed"
                    completed.append(operation.id)
                    _write_journal(journal_path, journal)
                    _observe(observer, "after-mutation", operation_id=operation.id)

                journal["phase"] = "verifying"
                _write_journal(journal_path, journal)
                _observe(observer, "before-verification", project=plan.path)
                if plan.verification is None or plan.verification(project) is not True:
                    raise ReconciliationTransactionError(
                        "Fresh project verification did not pass."
                    )
                journal["verification"] = "ready"
                journal["phase"] = "verified"
                _write_journal(journal_path, journal)
                _observe(observer, "after-verification", project=plan.path)
                _cleanup_staged_sources(directory)
                receipt = _receipt(plan.path, "applied", completed, "ready", [])
                reference = append_project_receipt(
                    run_id,
                    _diagnostic_receipt(
                        receipt,
                        plan,
                        project,
                        vault,
                        verification_state="ready",
                    ),
                    root=state_root,
                )
                if reference.state != "available":
                    raise ReconciliationTransactionError(
                        "The verified project receipt could not be saved durably."
                    )
                _observe(observer, "receipt-durable", project=plan.path)
                journal["diagnostic_state"] = reference.state
                journal["phase"] = "completed"
                _write_journal(journal_path, journal)
                _observe(observer, "receipt-persisted", project=plan.path)
                vault.cleanup_contents()
                return receipt
            except Exception as error:
                completed = _owned_operation_ids(project, operations)
                journal["verification"] = "failed" if completed else "not-run"
                journal["phase"] = "rolling-back"
                _write_journal(journal_path, journal)
                outcomes = _rollback(
                    project,
                    vault,
                    journal,
                    observer=observer,
                )
                rollback_ok = all(item.status == "restored" for item in outcomes)
                status = (
                    "rolled-back"
                    if completed and rollback_ok
                    else "incomplete-rollback"
                    if outcomes and not rollback_ok
                    else "blocked"
                )
                receipt = _receipt(
                    plan.path,
                    status,
                    completed,
                    "failed" if completed else "not-run",
                    outcomes,
                )
                _cleanup_staged_sources(directory)
                reference = append_project_receipt(
                    run_id,
                    _diagnostic_receipt(
                        receipt,
                        plan,
                        project,
                        vault,
                        verification_state=("failed" if completed else "not-run"),
                        error=error,
                    ),
                    root=state_root,
                )
                journal["diagnostic_state"] = reference.state
                if reference.state != "available":
                    journal["phase"] = "recovery-required"
                    _write_journal(journal_path, journal)
                    raise DurableReceiptUnavailable(
                        "The project outcome could not be saved durably."
                    )
                journal["phase"] = status
                _write_journal(journal_path, journal)
                _observe(observer, "receipt-persisted", project=plan.path)
                if status != "incomplete-rollback":
                    vault.cleanup_contents()
                return receipt
    except DurableReceiptUnavailable:
        raise
    except (
        ProjectLockError,
        SnapshotError,
        ReconciliationTransactionError,
        OSError,
    ) as error:
        receipt = _receipt(plan.path, "blocked", completed, "not-run", [])
        reference = append_project_receipt(
            run_id,
            _blocked_diagnostic_receipt(receipt, plan, error),
            root=state_root,
        )
        if reference.state != "available":
            raise DurableReceiptUnavailable(
                "The blocked project receipt could not be saved durably."
            ) from error
        return receipt


def execute_reconciliation(
    plans: Sequence[ProjectTransactionPlan],
    *,
    run_id: str,
    observer: Optional[BoundaryObserver] = None,
    root: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Execute independent guarded project transactions and return their ledger."""
    if not _RUN_ID.fullmatch(run_id):
        raise ReconciliationTransactionError("The reconciliation run id is invalid.")
    state_root = _state_root(root)
    boundary = state_root if root is not None else machine_diagnostics_root()
    ensure_private_directory(state_root, boundary=boundary)
    ledger: list[dict[str, Any]] = []
    for plan in plans:
        if not isinstance(plan, ProjectTransactionPlan):
            raise ReconciliationTransactionError(
                "The guarded executor accepts only transaction plans."
            )
        validated = tuple(
            _validate_operation(operation) for operation in plan.operations
        )
        for operation in validated:
            _closed_payload(operation)
        if len({operation.id for operation in validated}) != len(validated):
            raise ReconciliationTransactionError(
                "A transaction plan repeats an operation id."
            )
        if len({operation.target for operation in validated}) != len(validated):
            raise ReconciliationTransactionError(
                "A transaction plan repeats a mutation target."
            )
        ledger.append(
            _execute_project(
                plan,
                run_id=run_id,
                state_root=state_root,
                observer=observer,
            )
        )
    return ledger


def _plain_persisted_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value[key]
        for key in (
            "path",
            "status",
            "detail",
            "completed_operation_ids",
            "verification",
            "rollback",
        )
    }


def _interrupted_evidence(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **dict(receipt),
        "diagnostic_evidence": {
            "preflight": {
                "identity_fingerprint": None,
                "inspection_id": None,
                "classification": "blocked",
                "components": [],
            },
            "sources": [],
            "targets": [],
            "planned_operation_ids": [],
            "post_apply_verification": [],
            "exception": {
                "type": "TransactionError",
                "code": "interrupted",
            },
        },
    }


def _journal_for_run(
    state_root: Path, run_id: str
) -> dict[str, tuple[Path, dict[str, Any]]]:
    run_directory = state_root / "transactions" / run_id
    ensure_private_directory(run_directory, boundary=state_root)
    result: dict[str, tuple[Path, dict[str, Any]]] = {}
    for child in sorted(run_directory.iterdir(), key=lambda item: item.name):
        if not _PROJECT_JOURNAL_DIR.fullmatch(child.name):
            continue
        try:
            child_stat = child.lstat()
        except OSError as exc:
            raise ReconciliationTransactionError(
                "A recovery journal directory is unavailable."
            ) from exc
        if child.is_symlink() or not stat.S_ISDIR(child_stat.st_mode):
            raise ReconciliationTransactionError(
                "A recovery journal directory is unsafe."
            )
        ensure_private_directory(child, boundary=state_root)
        path = child / "journal.json"
        if not path.exists():
            continue
        try:
            path_stat = path.lstat()
        except OSError as exc:
            raise ReconciliationTransactionError(
                "A recovery journal is unavailable."
            ) from exc
        if path.is_symlink() or not stat.S_ISREG(path_stat.st_mode):
            raise ReconciliationTransactionError("A recovery journal is unsafe.")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ReconciliationTransactionError(
                "A recovery journal is unreadable."
            ) from exc
        project = raw.get("project") if isinstance(raw, Mapping) else None
        if (
            not isinstance(raw, dict)
            or raw.get("run_id") != run_id
            or not isinstance(project, str)
            or project in result
        ):
            raise ReconciliationTransactionError("A recovery journal is invalid.")
        result[project] = (path, raw)
    return result


def recover_transaction_run(
    run_id: str,
    *,
    root: Optional[Path] = None,
    observer: Optional[BoundaryObserver] = None,
) -> list[dict[str, Any]]:
    """Recover exactly one private run by rollback/reuse, never recipe execution."""
    from cc.core.ecosystem.project_plan_store import load_recovery_context
    from cc.core.ecosystem.reconciliation_diagnostics import (
        ReconciliationDiagnosticError,
        load_run_project_receipts,
    )

    context = load_recovery_context(run_id, root=root)
    if context.owner_live:
        raise ReconciliationTransactionError(
            "The interrupted run is still owned by a live process."
        )
    operation_paths = {
        str(plan["path"])
        for plan in context.plans
        if isinstance(plan.get("operations"), list) and plan["operations"]
    }
    if context.state == "outcome-recorded":
        return [
            dict(item) for item in context.ledger if item.get("path") in operation_paths
        ]
    if context.state not in {"claiming", "applying", "recovered-projects"} or (
        context.state == "claiming" and context.plan_state == "reviewed"
    ):
        raise ReconciliationTransactionError(
            "The reconciliation run has no recoverable transaction authority."
        )
    state_root = _state_root(root)
    boundary = state_root if root is not None else machine_diagnostics_root()
    ensure_private_directory(state_root, boundary=boundary)
    journals = _journal_for_run(state_root, run_id)
    if any(path not in context.project_paths for path in journals):
        raise ReconciliationTransactionError(
            "A recovery journal names an unreviewed project."
        )
    try:
        persisted_rows = load_run_project_receipts(run_id, root=state_root)
    except ReconciliationDiagnosticError as exc:
        raise ReconciliationTransactionError(
            "Persisted recovery receipts are invalid."
        ) from exc
    persisted = {str(item["path"]): item for item in persisted_rows}
    if any(path not in context.project_paths for path in persisted):
        raise ReconciliationTransactionError(
            "A persisted receipt names an unreviewed project."
        )

    terminal = {"completed", "blocked", "rolled-back", "recovered"}
    receipts: list[dict[str, Any]] = []
    for project_path in context.project_paths:
        if project_path not in operation_paths:
            continue
        journal_entry = journals.get(project_path)
        persisted_receipt = persisted.get(project_path)
        if journal_entry is None:
            if persisted_receipt is not None:
                receipts.append(_plain_persisted_receipt(persisted_receipt))
                continue
            receipt = _receipt(project_path, "blocked", [], "not-run", [])
            append_project_receipt(
                run_id,
                _interrupted_evidence(receipt),
                root=state_root,
            )
            receipts.append(receipt)
            continue

        journal_path, raw = journal_entry
        if (
            persisted_receipt is not None
            and persisted_receipt.get("status") == "applied"
            and raw.get("phase") in {"verified", "completed"}
            and raw.get("verification") == "ready"
        ):
            operation_ids = [
                str(item.get("id"))
                for item in raw.get("operations", [])
                if isinstance(item, Mapping)
            ]
            if persisted_receipt.get("completed_operation_ids") != operation_ids:
                raise ReconciliationTransactionError(
                    "A durable applied receipt does not match its journal."
                )
            _cleanup_staged_sources(journal_path.parent)
            receipts.append(_plain_persisted_receipt(persisted_receipt))
            continue
        if raw.get("phase") in terminal:
            _cleanup_staged_sources(journal_path.parent)
            if persisted_receipt is not None:
                receipts.append(_plain_persisted_receipt(persisted_receipt))
                continue
            completed = [
                str(item.get("id"))
                for item in raw.get("operations", [])
                if isinstance(item, Mapping) and item.get("status") == "completed"
            ]
            receipt = _receipt(
                project_path,
                "incomplete-rollback",
                completed,
                "failed" if completed else "not-run",
                [],
            )
            append_project_receipt(
                run_id,
                _interrupted_evidence(receipt),
                root=state_root,
            )
            receipts.append(receipt)
            continue

        try:
            identity = ProjectIdentity.from_value(raw["identity"])
            with project_lock(
                project_path,
                expected_identity=identity,
                lock_root=state_root / "locks",
            ) as project:
                raw_operations = [
                    item
                    for item in raw.get("operations", [])
                    if isinstance(item, Mapping)
                ]
                completed = _recovery_owned_operation_ids(
                    project,
                    raw_operations,
                    persisted_receipt,
                )
                vault = SnapshotVault(journal_path.parent / "snapshots")
                raw["journal_path"] = str(journal_path)
                raw["phase"] = "recovering"
                _write_journal(journal_path, raw)
                outcomes = _rollback(
                    project,
                    vault,
                    raw,
                    observer=observer,
                )
                ok = all(item.status == "restored" for item in outcomes)
                status = (
                    "rolled-back"
                    if ok and completed
                    else "incomplete-rollback"
                    if outcomes and not ok
                    else "blocked"
                )
                receipt = _receipt(
                    project_path,
                    status,
                    completed,
                    "failed" if completed else "not-run",
                    outcomes,
                )
                _cleanup_staged_sources(journal_path.parent)
                reference = append_project_receipt(
                    run_id,
                    _interrupted_evidence(receipt),
                    root=state_root,
                )
                raw["diagnostic_state"] = reference.state
                raw["phase"] = (
                    "recovered" if status != "incomplete-rollback" else status
                )
                _write_journal(journal_path, raw)
                if status != "incomplete-rollback":
                    vault.cleanup_contents()
                receipts.append(receipt)
        except (
            OSError,
            ValueError,
            KeyError,
            ProjectLockError,
            SnapshotError,
        ):
            if persisted_receipt is not None:
                receipt = _plain_persisted_receipt(persisted_receipt)
            else:
                raw_operations = [
                    item
                    for item in raw.get("operations", [])
                    if isinstance(item, Mapping)
                ]
                completed = [
                    str(item.get("id"))
                    for item in raw_operations
                    if item.get("status")
                    in {"completed", "rollback-failed", "restored"}
                ]
                receipt = _receipt(
                    project_path,
                    "incomplete-rollback" if completed else "blocked",
                    completed,
                    "failed" if completed else "not-run",
                    _journal_rollback_outcomes(raw_operations, completed),
                )
            append_project_receipt(
                run_id,
                _interrupted_evidence(receipt),
                root=state_root,
            )
            receipts.append(receipt)
    return receipts


def recover_incomplete_transactions(
    *,
    root: Optional[Path] = None,
    observer: Optional[BoundaryObserver] = None,
) -> list[dict[str, Any]]:
    """Recover fsynced incomplete journals without re-running recipe code."""
    state_root = _state_root(root)
    boundary = state_root if root is not None else machine_diagnostics_root()
    try:
        ensure_private_directory(state_root, boundary=boundary)
    except ProjectLockError:
        return []
    from cc.core.ecosystem.project_plan_store import (
        incomplete_run_ids,
        load_recovery_context,
        record_recovered_projects,
    )

    receipts: list[dict[str, Any]] = []
    for run_id in incomplete_run_ids(root=state_root):
        context = load_recovery_context(run_id, root=state_root)
        if context.owner_live or context.state == "outcome-recorded":
            continue
        if context.state == "claiming" and context.plan_state == "reviewed":
            continue
        recovered = recover_transaction_run(
            run_id,
            root=state_root,
            observer=observer,
        )
        outcome = (
            "incomplete-rollback"
            if any(item["status"] == "incomplete-rollback" for item in recovered)
            else "rolled-back"
            if any(item["status"] == "rolled-back" for item in recovered)
            else "applied"
            if all(item["status"] in {"applied", "unchanged"} for item in recovered)
            else "blocked"
        )
        record_recovered_projects(run_id, outcome, recovered, root=state_root)
        receipts.extend(recovered)
    return receipts


__all__ = [
    "DurableReceiptUnavailable",
    "ProjectPreflightSpec",
    "ProjectTransactionPlan",
    "ReconciliationTransactionError",
    "TransactionOperation",
    "execute_reconciliation",
    "fingerprint_recipe_source",
    "recover_incomplete_transactions",
    "recover_transaction_run",
    "transaction_plan_from_recipe",
]
