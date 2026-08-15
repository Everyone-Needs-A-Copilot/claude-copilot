"""Immutable installed EVAL-01..07 fixture bundle."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from cc.core.evaluation.matrix import build_matrix
from cc.core.evaluation.schema import canonical_sha256

PACKAGED_MATRIX_SHA256 = (
    "0c844795668aa2dc40596975ba5e20d3ee2fe345583149d20c9c8a07ef6688f6"
)
PACKAGED_BUNDLE_SHA256 = (
    "a2f20f40690ff1ca09312b72575bda5d1600539be06663afa689501c8d418698"
)
PACKAGED_PERSONAL_LAYER_SHA256 = (
    "ab0cba88ddde05682c82705bb0b8498b6666ce2e238c143a11c5a4d1d523d357"
)
_MAX_FILE_BYTES = 8 * 1024 * 1024
_PERSONAL_LAYER_FILES = ("doc.md", "snapshot.json")


class PackagedFixtureUnavailable(ValueError):
    """The installed fixture bundle is absent or differs from preregistration."""


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


def _file_sha256(directory_descriptor: int, name: str) -> str:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise PackagedFixtureUnavailable("Platform lacks no-follow protections.")
    descriptor: int | None = None
    try:
        descriptor = os.open(name, os.O_RDONLY | no_follow, dir_fd=directory_descriptor)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > _MAX_FILE_BYTES
        ):
            raise PackagedFixtureUnavailable(
                "Packaged fixture leaves must be bounded regular files."
            )
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_FILE_BYTES:
                raise PackagedFixtureUnavailable(
                    "Packaged fixture leaf exceeds the size limit."
                )
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (
            _stable_identity(before) != _stable_identity(after)
            or total != before.st_size
        ):
            raise PackagedFixtureUnavailable(
                "Packaged fixture leaf changed during verification."
            )
        return digest.hexdigest()
    except PackagedFixtureUnavailable:
        raise
    except OSError as exc:
        raise PackagedFixtureUnavailable(
            "Packaged fixture leaf cannot be read safely."
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _scan_bundle(
    directory_descriptor: int,
    *,
    prefix: str = "",
) -> tuple[list[str], list[dict[str, str]]]:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory_flag is None:
        raise PackagedFixtureUnavailable("Platform lacks no-follow protections.")
    directories: list[str] = []
    files: list[dict[str, str]] = []
    try:
        names = sorted(os.listdir(directory_descriptor))
    except OSError as exc:
        raise PackagedFixtureUnavailable(
            "Packaged fixture directory cannot be enumerated."
        ) from exc
    for name in names:
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            raise PackagedFixtureUnavailable("Packaged fixture name is not canonical.")
        relative = f"{prefix}/{name}" if prefix else name
        try:
            metadata = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        except OSError as exc:
            raise PackagedFixtureUnavailable(
                "Packaged fixture entry is unavailable."
            ) from exc
        if stat.S_ISDIR(metadata.st_mode):
            child: int | None = None
            try:
                child = os.open(
                    name,
                    os.O_RDONLY | directory_flag | no_follow,
                    dir_fd=directory_descriptor,
                )
                opened = os.fstat(child)
                if (opened.st_dev, opened.st_ino) != (
                    metadata.st_dev,
                    metadata.st_ino,
                ):
                    raise PackagedFixtureUnavailable(
                        "Packaged fixture directory identity changed."
                    )
                directories.append(relative)
                nested_directories, nested_files = _scan_bundle(
                    child,
                    prefix=relative,
                )
                directories.extend(nested_directories)
                files.extend(nested_files)
                if _stable_identity(opened) != _stable_identity(os.fstat(child)):
                    raise PackagedFixtureUnavailable(
                        "Packaged fixture directory changed during verification."
                    )
            except PackagedFixtureUnavailable:
                raise
            except OSError as exc:
                raise PackagedFixtureUnavailable(
                    "Packaged fixture directory cannot be opened safely."
                ) from exc
            finally:
                if child is not None:
                    os.close(child)
        elif stat.S_ISREG(metadata.st_mode):
            files.append(
                {
                    "path": relative,
                    "sha256": _file_sha256(directory_descriptor, name),
                }
            )
        else:
            raise PackagedFixtureUnavailable(
                "Packaged fixture tree contains a non-file entry."
            )
    return directories, files


def _bundle_sha256(cases_root: Path) -> str:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory_flag is None:
        raise PackagedFixtureUnavailable("Platform lacks no-follow protections.")
    descriptor: int | None = None
    try:
        expected = cases_root.lstat()
        descriptor = os.open(cases_root, os.O_RDONLY | directory_flag | no_follow)
        actual = os.fstat(descriptor)
        if not stat.S_ISDIR(expected.st_mode) or (expected.st_dev, expected.st_ino) != (
            actual.st_dev,
            actual.st_ino,
        ):
            raise PackagedFixtureUnavailable(
                "Packaged fixture root identity changed during open."
            )
        directories, files = _scan_bundle(descriptor)
        if _stable_identity(actual) != _stable_identity(os.fstat(descriptor)):
            raise PackagedFixtureUnavailable(
                "Packaged fixture root changed during verification."
            )
        return canonical_sha256(
            {
                "schema_version": "evaluation-fixture-bundle-v1",
                "directories": directories,
                "files": files,
            }
        )
    except PackagedFixtureUnavailable:
        raise
    except OSError as exc:
        raise PackagedFixtureUnavailable(
            "Packaged fixture root cannot be opened safely."
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _personal_layer_sha256(personal_root: Path) -> str:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory_flag is None:
        raise PackagedFixtureUnavailable("Platform lacks no-follow protections.")
    descriptor: int | None = None
    try:
        expected = personal_root.lstat()
        descriptor = os.open(personal_root, os.O_RDONLY | directory_flag | no_follow)
        actual = os.fstat(descriptor)
        if not stat.S_ISDIR(expected.st_mode) or (expected.st_dev, expected.st_ino) != (
            actual.st_dev,
            actual.st_ino,
        ):
            raise PackagedFixtureUnavailable(
                "Packaged personal layer root identity changed during open."
            )
        names = sorted(os.listdir(descriptor))
        if names != list(_PERSONAL_LAYER_FILES):
            raise PackagedFixtureUnavailable(
                "Packaged personal layer entries differ from the allowlist."
            )
        files = [
            {"path": name, "sha256": _file_sha256(descriptor, name)}
            for name in _PERSONAL_LAYER_FILES
        ]
        if _stable_identity(actual) != _stable_identity(os.fstat(descriptor)):
            raise PackagedFixtureUnavailable(
                "Packaged personal layer changed during verification."
            )
        return canonical_sha256(
            {
                "schema_version": "evaluation-personal-layer-package-v1",
                "files": files,
            }
        )
    except PackagedFixtureUnavailable:
        raise
    except OSError as exc:
        raise PackagedFixtureUnavailable(
            "Packaged personal layer cannot be read safely."
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def packaged_cases_root() -> Path:
    """Return the verified filesystem root shipped inside the installed package."""

    package_root = Path(__file__).parent
    cases_root = package_root / "cases"
    try:
        package_metadata = package_root.lstat()
        cases_metadata = cases_root.lstat()
    except OSError as exc:
        raise PackagedFixtureUnavailable(
            "Packaged evaluation fixtures are unavailable."
        ) from exc
    if (
        stat.S_ISLNK(package_metadata.st_mode)
        or not stat.S_ISDIR(package_metadata.st_mode)
        or stat.S_ISLNK(cases_metadata.st_mode)
        or not stat.S_ISDIR(cases_metadata.st_mode)
    ):
        raise PackagedFixtureUnavailable(
            "Packaged evaluation fixtures must be real directories."
        )
    if _bundle_sha256(cases_root) != PACKAGED_BUNDLE_SHA256:
        raise PackagedFixtureUnavailable(
            "Packaged evaluation fixture tree differs from preregistration."
        )
    try:
        matrix, _fixtures = build_matrix(cases_root)
    except (OSError, ValueError) as exc:
        raise PackagedFixtureUnavailable(
            "Packaged evaluation fixtures failed verification."
        ) from exc
    if matrix.matrix_sha256 != PACKAGED_MATRIX_SHA256:
        raise PackagedFixtureUnavailable(
            "Packaged evaluation matrix differs from preregistration."
        )
    if _bundle_sha256(cases_root) != PACKAGED_BUNDLE_SHA256:
        raise PackagedFixtureUnavailable(
            "Packaged evaluation fixture tree changed during verification."
        )
    return cases_root


def packaged_personal_layer_root() -> Path:
    """Return the verified fixed synthetic EVAL-07 personal layer package."""

    package_root = Path(__file__).parent
    personal_root = package_root / "personal_layer"
    try:
        package_metadata = package_root.lstat()
        personal_metadata = personal_root.lstat()
    except OSError as exc:
        raise PackagedFixtureUnavailable(
            "Packaged personal layer is unavailable."
        ) from exc
    if (
        stat.S_ISLNK(package_metadata.st_mode)
        or not stat.S_ISDIR(package_metadata.st_mode)
        or stat.S_ISLNK(personal_metadata.st_mode)
        or not stat.S_ISDIR(personal_metadata.st_mode)
    ):
        raise PackagedFixtureUnavailable(
            "Packaged personal layer must be a real directory."
        )
    if _personal_layer_sha256(personal_root) != PACKAGED_PERSONAL_LAYER_SHA256:
        raise PackagedFixtureUnavailable(
            "Packaged personal layer differs from preregistration."
        )
    return personal_root


__all__ = [
    "PACKAGED_BUNDLE_SHA256",
    "PACKAGED_MATRIX_SHA256",
    "PACKAGED_PERSONAL_LAYER_SHA256",
    "PackagedFixtureUnavailable",
    "packaged_cases_root",
    "packaged_personal_layer_root",
]
