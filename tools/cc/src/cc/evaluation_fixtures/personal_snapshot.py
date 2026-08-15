"""Fixed synthetic EVAL-07 personal-layer snapshot and private materializer."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cc import __version__
from cc.core.evaluation.schema import canonical_sha256
from cc.evaluation_fixtures import (
    PACKAGED_BUNDLE_SHA256,
    PACKAGED_MATRIX_SHA256,
    PackagedFixtureUnavailable,
    packaged_personal_layer_root,
)

SNAPSHOT_SCHEMA_VERSION = "task285-eval07-personal-snapshot-v1"
RECEIPT_SCHEMA_VERSION = "task285-eval07-personal-materialization-v1"
PERSONAL_SNAPSHOT_SHA256 = (
    "2cd26a8d1f40fbff0e953685b86d1512691f4e47879427b7f73f642c3249d156"
)
RELEASE_IDENTITY_SHA256 = (
    "834553c2a530658562689645850fbc21f8aabd4af7efbf18ef289e985a9881fa"
)
PACKAGE_IDENTITY_SHA256 = (
    "708f882d9f1cf3fc54e5b0305ce9ce5f6e46efdc8eafb661dd824241b737776b"
)
_PACKAGE_FILES = ("doc.md", "snapshot.json")
_MATERIALIZED_FILES = ("doc.md",)
_MAX_FILE_BYTES = 1024 * 1024
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_AUTHORITY = object()
_ISSUED_RECEIPTS: weakref.WeakValueDictionary[int, "PersonalSnapshotReceipt"] = (
    weakref.WeakValueDictionary()
)


class PersonalSnapshotUnavailable(ValueError):
    """The synthetic snapshot or its private materialization is not exact."""


def _stable_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _require_digest(value: str, field_name: str) -> None:
    if not _DIGEST.fullmatch(value):
        raise PersonalSnapshotUnavailable(f"{field_name} is not a SHA-256 digest.")


def _descriptor_digest(descriptor: int, maximum: int = _MAX_FILE_BYTES) -> str:
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > maximum
        ):
            raise PersonalSnapshotUnavailable(
                "Snapshot leaves must be bounded single-link regular files."
            )
        os.lseek(descriptor, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise PersonalSnapshotUnavailable(
                    "Snapshot leaf exceeds the size limit."
                )
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (
            _stable_identity(before) != _stable_identity(after)
            or total != before.st_size
        ):
            raise PersonalSnapshotUnavailable(
                "Snapshot leaf changed during verification."
            )
        return digest.hexdigest()
    except PersonalSnapshotUnavailable:
        raise
    except OSError as exc:
        raise PersonalSnapshotUnavailable(
            "Snapshot leaf cannot be read safely."
        ) from exc


def _read_leaf(directory_descriptor: int, name: str) -> bytes:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise PersonalSnapshotUnavailable("Platform lacks no-follow protections.")
    descriptor: int | None = None
    try:
        descriptor = os.open(name, os.O_RDONLY | no_follow, dir_fd=directory_descriptor)
        before = os.fstat(descriptor)
        digest = _descriptor_digest(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        content = bytearray()
        while len(content) <= _MAX_FILE_BYTES:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            content.extend(chunk)
        after = os.fstat(descriptor)
        if (
            len(content) > _MAX_FILE_BYTES
            or _stable_identity(before) != _stable_identity(after)
            or hashlib.sha256(content).hexdigest() != digest
        ):
            raise PersonalSnapshotUnavailable(
                "Snapshot leaf changed while it was retained."
            )
        return bytes(content)
    except PersonalSnapshotUnavailable:
        raise
    except OSError as exc:
        raise PersonalSnapshotUnavailable(
            "Snapshot leaf cannot be opened safely."
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _closed_json(raw: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PersonalSnapshotUnavailable(
                    "Snapshot manifest contains a duplicate key."
                )
            result[key] = value
        return result

    try:
        decoded = raw.decode("utf-8")
        value = json.loads(decoded, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersonalSnapshotUnavailable(
            "Snapshot manifest is not canonical JSON."
        ) from exc
    if not isinstance(value, dict):
        raise PersonalSnapshotUnavailable("Snapshot manifest must be an object.")
    return value


def _release_identity_document() -> dict[str, object]:
    return {
        "schema_version": "evaluation-release-identity-v1",
        "component": "cc",
        "version": __version__,
        "release_tag": f"v{__version__}",
    }


def _package_identity_document() -> dict[str, object]:
    return {
        "schema_version": "evaluation-package-identity-v1",
        "distribution": "claude-cli",
        "import_package": "cc",
        "version": __version__,
    }


def _snapshot_identity_document(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "snapshot_sha256"}


def _validate_manifest(value: dict[str, Any], files: dict[str, bytes]) -> None:
    expected_keys = {
        "schema_version",
        "snapshot_id",
        "case_id",
        "revision",
        "fixture_namespace",
        "synthetic_fixture",
        "matrix_sha256",
        "fixture_bundle_sha256",
        "release_identity_sha256",
        "package_identity_sha256",
        "files",
        "snapshot_sha256",
    }
    if set(value) != expected_keys:
        raise PersonalSnapshotUnavailable("Snapshot manifest fields are not closed.")
    expected_literals = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "snapshot_id": "eval-07-synthetic-personal-layer",
        "case_id": "eval-07",
        "revision": 1,
        "fixture_namespace": "SYNTHETIC-EVAL07",
        "synthetic_fixture": True,
        "matrix_sha256": PACKAGED_MATRIX_SHA256,
        "fixture_bundle_sha256": PACKAGED_BUNDLE_SHA256,
        "release_identity_sha256": RELEASE_IDENTITY_SHA256,
        "package_identity_sha256": PACKAGE_IDENTITY_SHA256,
        "snapshot_sha256": PERSONAL_SNAPSHOT_SHA256,
    }
    if any(value.get(key) != item for key, item in expected_literals.items()):
        raise PersonalSnapshotUnavailable(
            "Snapshot manifest differs from its preregistered identity."
        )
    if (
        canonical_sha256(_release_identity_document()) != RELEASE_IDENTITY_SHA256
        or canonical_sha256(_package_identity_document()) != PACKAGE_IDENTITY_SHA256
    ):
        raise PersonalSnapshotUnavailable(
            "Installed release or package identity differs from the snapshot."
        )
    entries = value.get("files")
    if not isinstance(entries, list) or len(entries) != 1:
        raise PersonalSnapshotUnavailable("Snapshot file allowlist is not exact.")
    entry = entries[0]
    if not isinstance(entry, dict) or set(entry) != {
        "path",
        "sha256",
        "media_type",
        "materialized_mode",
    }:
        raise PersonalSnapshotUnavailable("Snapshot file fields are not closed.")
    if (
        entry.get("path") != "doc.md"
        or entry.get("media_type") != "text/markdown"
        or entry.get("materialized_mode") != "0600"
        or set(files) != {"doc.md"}
    ):
        raise PersonalSnapshotUnavailable("Snapshot file allowlist differs.")
    digest = entry.get("sha256")
    if not isinstance(digest, str):
        raise PersonalSnapshotUnavailable("Snapshot file digest is unavailable.")
    _require_digest(digest, "snapshot file digest")
    if hashlib.sha256(files["doc.md"]).hexdigest() != digest:
        raise PersonalSnapshotUnavailable("Snapshot content differs from its manifest.")
    if canonical_sha256(_snapshot_identity_document(value)) != PERSONAL_SNAPSHOT_SHA256:
        raise PersonalSnapshotUnavailable("Snapshot identity digest differs.")


def _load_packaged_snapshot() -> tuple[dict[str, Any], dict[str, bytes]]:
    try:
        root = packaged_personal_layer_root()
    except PackagedFixtureUnavailable as exc:
        raise PersonalSnapshotUnavailable(str(exc)) from exc
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory_flag is None:
        raise PersonalSnapshotUnavailable("Platform lacks no-follow protections.")
    descriptor: int | None = None
    try:
        expected = root.lstat()
        descriptor = os.open(root, os.O_RDONLY | directory_flag | no_follow)
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(expected.st_mode) or (expected.st_dev, expected.st_ino) != (
            opened.st_dev,
            opened.st_ino,
        ):
            raise PersonalSnapshotUnavailable(
                "Snapshot package root changed during open."
            )
        names = sorted(os.listdir(descriptor))
        if names != list(_PACKAGE_FILES):
            raise PersonalSnapshotUnavailable("Snapshot package allowlist differs.")
        manifest = _closed_json(_read_leaf(descriptor, "snapshot.json"))
        files = {"doc.md": _read_leaf(descriptor, "doc.md")}
        if _stable_identity(opened) != _stable_identity(os.fstat(descriptor)):
            raise PersonalSnapshotUnavailable(
                "Snapshot package root changed during verification."
            )
        _validate_manifest(manifest, files)
        return manifest, files
    except PersonalSnapshotUnavailable:
        raise
    except OSError as exc:
        raise PersonalSnapshotUnavailable(
            "Snapshot package cannot be read safely."
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def personal_snapshot_manifest() -> dict[str, Any]:
    """Return a detached, value-suppressing copy of the public manifest."""

    manifest, _files = _load_packaged_snapshot()
    return copy.deepcopy(manifest)


def personal_snapshot_contribution(*, runtime: str) -> tuple[str, dict[str, object]]:
    """Return the exact synthetic Knowledge contribution and content-object receipt."""

    if runtime != "claude":
        raise PersonalSnapshotUnavailable(
            "Synthetic personal evaluation content is Claude-only."
        )
    manifest, files = _load_packaged_snapshot()
    try:
        content = files["doc.md"].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PersonalSnapshotUnavailable(
            "Synthetic personal evaluation content is not UTF-8."
        ) from exc
    source = {
        "layer": "synthetic-personal-knowledge",
        "tier": "personal",
        "repository": "cc/evaluation-fixtures",
        "ref": f"sha256:{manifest['snapshot_sha256']}",
        "tree": manifest["snapshot_sha256"],
        "signer": "SHA256:FIfppOkzwXZUAamELQzYoSUQXiEAmTYiVewHe1ACMZo",
        "contribution": "personal_layer/doc.md",
        "content_sha256": manifest["files"][0]["sha256"],
        "runtime": runtime,
        "adapter_version": "synthetic-personal-snapshot-v1",
    }
    return content, source


@dataclass(frozen=True)
class PersonalSnapshotFileReceipt:
    path: str
    materialized_path: str
    sha256: str
    mode: str

    def __post_init__(self) -> None:
        if self.path != "doc.md" or self.mode != "0600":
            raise PersonalSnapshotUnavailable(
                "Materialized snapshot file is not exact."
            )
        _require_digest(self.sha256, "materialized snapshot file")


class _MaterializationCapability:
    __slots__ = (
        "parent_descriptor",
        "root_descriptor",
        "file_descriptors",
        "root_path",
        "root_name",
        "root_identity",
        "file_identities",
        "file_digests",
        "seal",
    )

    def __init__(
        self,
        *,
        parent_descriptor: int,
        root_descriptor: int,
        file_descriptors: dict[str, int],
        root_path: Path,
        seal: object,
    ) -> None:
        self.parent_descriptor = parent_descriptor
        self.root_descriptor = root_descriptor
        self.file_descriptors = tuple(sorted(file_descriptors.items()))
        self.root_path = root_path
        self.root_name = root_path.name
        self.seal = seal
        self.root_identity = _stable_identity(os.fstat(root_descriptor))
        self.file_identities = tuple(
            (name, _stable_identity(os.fstat(descriptor)))
            for name, descriptor in self.file_descriptors
        )
        self.file_digests = tuple(
            (name, _descriptor_digest(descriptor))
            for name, descriptor in self.file_descriptors
        )

    def validate(self) -> bool:
        try:
            root_before = os.fstat(self.root_descriptor)
            parent_entry = os.stat(
                self.root_name,
                dir_fd=self.parent_descriptor,
                follow_symlinks=False,
            )
            path_entry = self.root_path.lstat()
            if (
                _stable_identity(root_before) != self.root_identity
                or (parent_entry.st_dev, parent_entry.st_ino)
                != (root_before.st_dev, root_before.st_ino)
                or (path_entry.st_dev, path_entry.st_ino)
                != (root_before.st_dev, root_before.st_ino)
                or not stat.S_ISDIR(root_before.st_mode)
                or stat.S_IMODE(root_before.st_mode) != 0o700
                or tuple(sorted(os.listdir(self.root_descriptor)))
                != _MATERIALIZED_FILES
            ):
                return False
            expected_identities = dict(self.file_identities)
            expected_digests = dict(self.file_digests)
            for name, descriptor in self.file_descriptors:
                opened = os.fstat(descriptor)
                path_metadata = os.stat(
                    name,
                    dir_fd=self.root_descriptor,
                    follow_symlinks=False,
                )
                if (
                    _stable_identity(opened) != expected_identities[name]
                    or (path_metadata.st_dev, path_metadata.st_ino)
                    != (opened.st_dev, opened.st_ino)
                    or not stat.S_ISREG(opened.st_mode)
                    or opened.st_nlink != 1
                    or stat.S_IMODE(opened.st_mode) != 0o600
                    or _descriptor_digest(descriptor) != expected_digests[name]
                ):
                    return False
            return (
                _stable_identity(os.fstat(self.root_descriptor)) == self.root_identity
            )
        except (OSError, PersonalSnapshotUnavailable):
            return False

    def close(self) -> None:
        file_descriptors = self.file_descriptors
        root_descriptor = self.root_descriptor
        parent_descriptor = self.parent_descriptor
        self.file_descriptors = ()
        self.root_descriptor = -1
        self.parent_descriptor = -1
        descriptors = [
            *(descriptor for _name, descriptor in file_descriptors),
            root_descriptor,
            parent_descriptor,
        ]
        for descriptor in descriptors:
            if descriptor < 0:
                continue
            try:
                os.close(descriptor)
            except OSError:
                pass

    def __del__(self) -> None:
        self.close()


@dataclass(frozen=True)
class PersonalSnapshotReceipt:
    schema_version: str
    receipt_sha256: str
    snapshot_sha256: str
    matrix_sha256: str
    release_identity_sha256: str
    package_identity_sha256: str
    materialization_sha256: str
    root_path: str
    files: tuple[PersonalSnapshotFileReceipt, ...]
    _capability: _MaterializationCapability = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._authority is not _RECEIPT_AUTHORITY
            or self.schema_version != RECEIPT_SCHEMA_VERSION
            or self.snapshot_sha256 != PERSONAL_SNAPSHOT_SHA256
            or self.matrix_sha256 != PACKAGED_MATRIX_SHA256
            or self.release_identity_sha256 != RELEASE_IDENTITY_SHA256
            or self.package_identity_sha256 != PACKAGE_IDENTITY_SHA256
            or len(self.files) != 1
        ):
            raise PersonalSnapshotUnavailable(
                "Personal snapshot receipt is not verifier-issued."
            )
        for digest in (
            self.receipt_sha256,
            self.snapshot_sha256,
            self.matrix_sha256,
            self.release_identity_sha256,
            self.package_identity_sha256,
            self.materialization_sha256,
        ):
            _require_digest(digest, "personal snapshot receipt")

    def validate(self) -> bool:
        return verify_personal_snapshot_receipt(self)

    def close(self) -> None:
        if _ISSUED_RECEIPTS.get(id(self)) is not self:
            return
        _ISSUED_RECEIPTS.pop(id(self), None)
        self._capability.close()


def _file_receipt_document(value: PersonalSnapshotFileReceipt) -> dict[str, str]:
    return {
        "path": value.path,
        "materialized_path": value.materialized_path,
        "sha256": value.sha256,
        "mode": value.mode,
    }


def _receipt_identity_document(value: PersonalSnapshotReceipt) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "snapshot_sha256": value.snapshot_sha256,
        "matrix_sha256": value.matrix_sha256,
        "release_identity_sha256": value.release_identity_sha256,
        "package_identity_sha256": value.package_identity_sha256,
        "materialization_sha256": value.materialization_sha256,
        "root_path": value.root_path,
        "files": [_file_receipt_document(item) for item in value.files],
    }


def personal_snapshot_receipt_document(
    value: PersonalSnapshotReceipt,
) -> dict[str, object]:
    """Return only safe identities and paths; never return snapshot bytes."""

    if not verify_personal_snapshot_receipt(value):
        raise PersonalSnapshotUnavailable("Personal snapshot receipt is not exact.")
    return {
        **_receipt_identity_document(value),
        "receipt_sha256": value.receipt_sha256,
    }


def verify_personal_snapshot_receipt(value: PersonalSnapshotReceipt) -> bool:
    if (
        not isinstance(value, PersonalSnapshotReceipt)
        or _ISSUED_RECEIPTS.get(id(value)) is not value
        or value._authority is not _RECEIPT_AUTHORITY
        or value._capability.seal is not value._seal
    ):
        return False
    try:
        manifest, _files = _load_packaged_snapshot()
        return bool(
            manifest["snapshot_sha256"] == value.snapshot_sha256
            and value.receipt_sha256
            == canonical_sha256(_receipt_identity_document(value))
            and value._capability.validate()
        )
    except (OSError, PersonalSnapshotUnavailable, TypeError, ValueError):
        return False


def _write_all(descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        try:
            written = os.write(descriptor, content[offset:])
        except OSError as exc:
            raise PersonalSnapshotUnavailable(
                "Private snapshot content could not be materialized."
            ) from exc
        if written <= 0:
            raise PersonalSnapshotUnavailable(
                "Private snapshot materialization made no progress."
            )
        offset += written


def materialize_personal_snapshot(destination: Path) -> PersonalSnapshotReceipt:
    """Create one new exact private directory from fixed packaged synthetic bytes."""

    manifest, packaged_files = _load_packaged_snapshot()
    destination = Path(destination)
    if (
        not destination.is_absolute()
        or destination.name in {"", ".", ".."}
        or any(part in {".", ".."} for part in destination.parts)
    ):
        raise PersonalSnapshotUnavailable(
            "Private snapshot destination must be an absolute canonical path."
        )
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory_flag is None:
        raise PersonalSnapshotUnavailable("Platform lacks no-follow protections.")
    parent_descriptor: int | None = None
    root_descriptor: int | None = None
    file_descriptors: dict[str, int] = {}
    capability: _MaterializationCapability | None = None
    seal = object()
    try:
        parent_expected = destination.parent.lstat()
        parent_descriptor = os.open(
            destination.parent,
            os.O_RDONLY | directory_flag | no_follow,
        )
        parent_opened = os.fstat(parent_descriptor)
        if not stat.S_ISDIR(parent_expected.st_mode) or (
            parent_expected.st_dev,
            parent_expected.st_ino,
        ) != (parent_opened.st_dev, parent_opened.st_ino):
            raise PersonalSnapshotUnavailable(
                "Private snapshot parent identity changed during open."
            )
        try:
            os.stat(
                destination.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        else:
            raise PersonalSnapshotUnavailable(
                "Private snapshot destination already exists."
            )
        os.mkdir(destination.name, 0o700, dir_fd=parent_descriptor)
        root_descriptor = os.open(
            destination.name,
            os.O_RDONLY | directory_flag | no_follow,
            dir_fd=parent_descriptor,
        )
        os.fchmod(root_descriptor, 0o700)
        root_metadata = os.fstat(root_descriptor)
        path_metadata = os.stat(
            destination.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or (root_metadata.st_dev, root_metadata.st_ino)
            != (path_metadata.st_dev, path_metadata.st_ino)
            or stat.S_IMODE(root_metadata.st_mode) != 0o700
        ):
            raise PersonalSnapshotUnavailable(
                "Private snapshot directory is not exact."
            )
        entries = manifest["files"]
        for entry in entries:
            name = str(entry["path"])
            descriptor = os.open(
                name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | no_follow,
                0o600,
                dir_fd=root_descriptor,
            )
            file_descriptors[name] = descriptor
            os.fchmod(descriptor, 0o600)
            _write_all(descriptor, packaged_files[name])
            os.fsync(descriptor)
            if (
                stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o600
                or _descriptor_digest(descriptor) != entry["sha256"]
            ):
                raise PersonalSnapshotUnavailable(
                    "Private snapshot file differs after materialization."
                )
        if tuple(sorted(os.listdir(root_descriptor))) != _MATERIALIZED_FILES:
            raise PersonalSnapshotUnavailable(
                "Private snapshot materialization contains unexpected entries."
            )
        capability = _MaterializationCapability(
            parent_descriptor=parent_descriptor,
            root_descriptor=root_descriptor,
            file_descriptors=file_descriptors,
            root_path=destination,
            seal=seal,
        )
        parent_descriptor = None
        root_descriptor = None
        file_descriptors = {}
        if not capability.validate():
            raise PersonalSnapshotUnavailable(
                "Private snapshot capability failed initial validation."
            )
        file_receipts = tuple(
            PersonalSnapshotFileReceipt(
                str(entry["path"]),
                str(destination / str(entry["path"])),
                str(entry["sha256"]),
                str(entry["materialized_mode"]),
            )
            for entry in entries
        )
        materialization_sha256 = canonical_sha256(
            {
                "schema_version": RECEIPT_SCHEMA_VERSION,
                "snapshot_sha256": PERSONAL_SNAPSHOT_SHA256,
                "matrix_sha256": PACKAGED_MATRIX_SHA256,
                "files": [
                    {
                        "path": item.path,
                        "sha256": item.sha256,
                        "mode": item.mode,
                    }
                    for item in file_receipts
                ],
            }
        )
        provisional = PersonalSnapshotReceipt(
            RECEIPT_SCHEMA_VERSION,
            "0" * 64,
            PERSONAL_SNAPSHOT_SHA256,
            PACKAGED_MATRIX_SHA256,
            RELEASE_IDENTITY_SHA256,
            PACKAGE_IDENTITY_SHA256,
            materialization_sha256,
            str(destination),
            file_receipts,
            capability,
            seal,
            _RECEIPT_AUTHORITY,
        )
        receipt = PersonalSnapshotReceipt(
            **{
                **provisional.__dict__,
                "receipt_sha256": canonical_sha256(
                    _receipt_identity_document(provisional)
                ),
            }
        )
        _ISSUED_RECEIPTS[id(receipt)] = receipt
        return receipt
    except PersonalSnapshotUnavailable:
        raise
    except OSError as exc:
        raise PersonalSnapshotUnavailable(
            "Private snapshot could not be materialized safely."
        ) from exc
    finally:
        if capability is None:
            for descriptor in (
                *file_descriptors.values(),
                root_descriptor,
                parent_descriptor,
            ):
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass


__all__ = [
    "PACKAGE_IDENTITY_SHA256",
    "PERSONAL_SNAPSHOT_SHA256",
    "PersonalSnapshotFileReceipt",
    "PersonalSnapshotReceipt",
    "PersonalSnapshotUnavailable",
    "RELEASE_IDENTITY_SHA256",
    "materialize_personal_snapshot",
    "personal_snapshot_contribution",
    "personal_snapshot_manifest",
    "personal_snapshot_receipt_document",
    "verify_personal_snapshot_receipt",
]
