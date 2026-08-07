"""Private durable snapshots and compare-and-swap rollback truth.

Every bounded target is captured and fsynced before the first project write.
Snapshot contents live in a mode-0700 transaction vault, never in the redacted
diagnostic.  Rollback accepts the fingerprint written by the transaction and
restores only when the current target still equals that value; a human or peer
edit is reported as ``conflict`` and is never overwritten.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from cc.core.ecosystem.project_locking import (
    AnchoredProject,
    UnsafeProjectPath,
    atomic_json_write,
    ensure_private_directory,
    fsync_directory,
    normalize_relative_target,
)

_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")


class SnapshotError(RuntimeError):
    """A target could not be safely captured or restored."""


@dataclass(frozen=True)
class SnapshotRecord:
    target: str
    kind: str
    mode: Optional[int]
    fingerprint: str
    storage: Optional[str]
    link_value: Optional[str]
    missing_parents: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SnapshotRecord":
        return cls(
            target=str(value["target"]),
            kind=str(value["kind"]),
            mode=int(value["mode"]) if value.get("mode") is not None else None,
            fingerprint=str(value["fingerprint"]),
            storage=str(value["storage"]) if value.get("storage") else None,
            link_value=(
                str(value["link_value"])
                if value.get("link_value") is not None
                else None
            ),
            missing_parents=tuple(value.get("missing_parents", ())),
        )


@dataclass(frozen=True)
class RollbackOutcome:
    target: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


class SnapshotVault:
    """One project transaction's content-bearing durable snapshot store."""

    def __init__(self, root: Path):
        self.root = root.expanduser()
        ensure_private_directory(self.root, boundary=self.root)
        self._metadata_path = self.root / "snapshots.json"
        self._records: dict[str, SnapshotRecord] = {}
        if self._metadata_path.exists():
            self._load()

    @property
    def records(self) -> tuple[SnapshotRecord, ...]:
        return tuple(self._records.values())

    def _load(self) -> None:
        try:
            raw = json.loads(self._metadata_path.read_text(encoding="utf-8"))
            rows = raw["snapshots"]
            if raw.get("schema_version") != "1.0" or not isinstance(rows, list):
                raise ValueError
            loaded = [SnapshotRecord.from_dict(item) for item in rows]
            if any(
                item.kind not in {"missing", "file", "symlink", "directory"}
                or not _FINGERPRINT.fullmatch(item.fingerprint)
                or any(not isinstance(parent, str) for parent in item.missing_parents)
                for item in loaded
            ):
                raise ValueError
            self._records = {item.target: item for item in loaded}
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SnapshotError("The durable transaction snapshot is invalid.") from exc

    def _persist(self) -> None:
        atomic_json_write(
            self._metadata_path,
            {
                "schema_version": "1.0",
                "snapshots": [item.as_dict() for item in self._records.values()],
            },
        )

    def _write_blob(self, payload: bytes) -> str:
        directory = self.root / "blobs"
        ensure_private_directory(directory, boundary=self.root)
        name = f"blob-{secrets.token_hex(16)}"
        path = directory / name
        descriptor = os.open(
            path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        fsync_directory(directory)
        return f"blobs/{name}"

    def capture(self, project: AnchoredProject, target: str) -> SnapshotRecord:
        """Capture one target durably; duplicates are refused, never replaced."""
        normalize_relative_target(target)
        if target in self._records:
            raise SnapshotError("A transaction target was listed more than once.")
        missing_parents = project.missing_parent_paths(target)
        target_stat = project.lstat(target)
        fingerprint = project.fingerprint(target)
        mode: Optional[int] = None
        storage: Optional[str] = None
        link_value: Optional[str] = None
        if target_stat is None:
            kind = "missing"
        elif stat.S_ISREG(target_stat.st_mode):
            kind = "file"
            mode = stat.S_IMODE(target_stat.st_mode)
            storage = self._write_blob(project.read_bytes(target))
        elif stat.S_ISLNK(target_stat.st_mode):
            kind = "symlink"
            link_value = project.readlink(target)
        elif stat.S_ISDIR(target_stat.st_mode):
            kind = "directory"
            mode = stat.S_IMODE(target_stat.st_mode)
            directory = self.root / "trees"
            ensure_private_directory(directory, boundary=self.root)
            name = f"tree-{secrets.token_hex(16)}"
            project.export_tree(target, directory / name)
            storage = f"trees/{name}"
            fsync_directory(directory)
        else:
            raise SnapshotError("A transaction target is a special file.")
        record = SnapshotRecord(
            target=target,
            kind=kind,
            mode=mode,
            fingerprint=fingerprint,
            storage=storage,
            link_value=link_value,
            missing_parents=missing_parents,
        )
        self._records[target] = record
        self._persist()
        return record

    def record_for(self, target: str) -> SnapshotRecord:
        try:
            return self._records[target]
        except KeyError as exc:
            raise SnapshotError(
                "The transaction has no snapshot for this target."
            ) from exc

    def restore(
        self,
        project: AnchoredProject,
        target: str,
        *,
        expected_current_fingerprint: str,
    ) -> RollbackOutcome:
        """Restore exactly one owned output if compare-and-swap still succeeds."""
        record = self.record_for(target)
        try:
            current = project.fingerprint(target)
            if current != expected_current_fingerprint:
                return RollbackOutcome(
                    target,
                    "conflict",
                    "The target changed after this transaction wrote it, so it was left alone.",
                )
            project.remove(target)
            if record.kind == "file":
                if record.storage is None:
                    raise SnapshotError("The saved file payload is unavailable.")
                source = self.root / record.storage
                if source.is_symlink() or not source.is_file():
                    raise SnapshotError("The saved file payload is unavailable.")
                project.atomic_write(
                    target,
                    source.read_bytes(),
                    mode=record.mode or 0o644,
                )
            elif record.kind == "symlink":
                if record.link_value is None:
                    raise SnapshotError("The saved link target is unavailable.")
                project.atomic_symlink(
                    target,
                    record.link_value,
                    allow_external_restore=True,
                )
            elif record.kind == "directory":
                if record.storage is None:
                    raise SnapshotError("The saved directory payload is unavailable.")
                source = self.root / record.storage
                project.install_tree(target, source, mode=record.mode or 0o755)
            elif record.kind != "missing":
                raise SnapshotError("The saved target kind is unsupported.")
            if record.kind == "missing":
                project.remove_empty_parents(target, record.missing_parents)
            restored = project.fingerprint(target)
            if restored != record.fingerprint:
                return RollbackOutcome(
                    target,
                    "mismatch",
                    "The target was restored but did not match its saved fingerprint.",
                )
            return RollbackOutcome(
                target,
                "restored",
                "The target matches its saved pre-transaction fingerprint.",
            )
        except (OSError, SnapshotError, UnsafeProjectPath):
            return RollbackOutcome(
                target,
                "unreadable",
                "The saved target could not be restored and verified.",
            )

    def cleanup_contents(self) -> None:
        """Delete only this vault's owned payloads after a durable terminal receipt."""
        for child in list(self.root.iterdir()):
            if child == self._metadata_path:
                continue
            if child.is_symlink():
                child.unlink()
            elif child.is_dir():
                for descendant in sorted(
                    child.rglob("*"), key=lambda path: len(path.parts), reverse=True
                ):
                    if descendant.is_symlink() or descendant.is_file():
                        descendant.unlink()
                    elif descendant.is_dir():
                        descendant.rmdir()
                child.rmdir()
            else:
                child.unlink()
        fsync_directory(self.root)


__all__ = [
    "RollbackOutcome",
    "SnapshotError",
    "SnapshotRecord",
    "SnapshotVault",
]
