"""Test-only primitives for the bounded reconciliation assistant boundary."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class TreeEntry:
    """Byte/type/mode identity for one path without following symlinks."""

    relative_path: str
    kind: str
    mode: int
    payload_sha256: str


def _entry_payload(path: Path, kind: str) -> bytes:
    if kind == "file":
        return path.read_bytes()
    if kind == "symlink":
        return os.readlink(path).encode("utf-8", errors="surrogateescape")
    return b""


def _walk_without_following(root: Path) -> Iterator[Path]:
    yield root
    if root.is_symlink() or not root.is_dir():
        return
    with os.scandir(root) as children:
        for child in sorted(children, key=lambda item: item.name):
            path = Path(child.path)
            yield path
            if child.is_dir(follow_symlinks=False):
                yield from list(_walk_without_following(path))[1:]


def snapshot_tree(root: Path) -> tuple[TreeEntry, ...]:
    """Return a strict recursive snapshot, including Git metadata and modes."""

    entries: list[TreeEntry] = []
    for path in _walk_without_following(root):
        metadata = path.lstat()
        if stat.S_ISREG(metadata.st_mode):
            kind = "file"
        elif stat.S_ISDIR(metadata.st_mode):
            kind = "directory"
        elif stat.S_ISLNK(metadata.st_mode):
            kind = "symlink"
        else:
            kind = "special"
        entries.append(
            TreeEntry(
                relative_path="."
                if path == root
                else path.relative_to(root).as_posix(),
                kind=kind,
                mode=stat.S_IMODE(metadata.st_mode),
                payload_sha256=hashlib.sha256(
                    _entry_payload(path, kind)
                ).hexdigest(),
            )
        )
    return tuple(entries)


def capture_record(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != (
        "fake-claude.capture.v1"
    ):
        raise AssertionError("The fake Claude capture is not the expected contract.")
    return value


def decoded_stdin(record: dict[str, object]) -> bytes:
    import base64

    value = record.get("stdin_base64")
    if not isinstance(value, str):
        raise AssertionError("The fake Claude capture has no stdin bytes.")
    return base64.b64decode(value, validate=True)
