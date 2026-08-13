"""Fail-closed loading for versioned, digest-bound synthetic fixtures."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from cc.core.evaluation.models import EvaluationFixture
from cc.core.evaluation.safety import require_safe_synthetic_text
from cc.core.evaluation.schema import canonical_sha256, validate_document

_MAX_FILE_BYTES = 8 * 1024 * 1024


class FixtureLoadError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedEvidence:
    path: str
    sha256: str
    media_type: str
    content: bytes


@dataclass(frozen=True)
class LoadedFixture:
    fixture: EvaluationFixture
    fixture_sha256: str
    evidence: tuple[VerifiedEvidence, ...]


def load_fixture(case_root: Path) -> LoadedFixture:
    with _open_verified_root(case_root) as root_descriptor:
        raw_case = _read_regular_file(root_descriptor, "case.json")
        value = _load_json_object(raw_case)
        validate_document(value)
        fixture = EvaluationFixture.from_validated_mapping(value)
        _validate_fixture_invariants(fixture)

        require_safe_synthetic_text(
            fixture.problem_statement, location_class="problem-statement"
        )
        verified: list[VerifiedEvidence] = []
        for declared in fixture.evidence_files:
            content = _read_regular_file(root_descriptor, declared.path)
            _require_digest(content, declared.sha256)
            if (
                declared.media_type.startswith("text/")
                or declared.media_type == "application/json"
            ):
                try:
                    text = content.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise FixtureLoadError(
                        "Declared text evidence is not UTF-8."
                    ) from error
                require_safe_synthetic_text(text, location_class="evidence-input")
            verified.append(
                VerifiedEvidence(
                    path=declared.path,
                    sha256=declared.sha256,
                    media_type=declared.media_type,
                    content=content,
                )
            )

        oracle_bytes = _read_regular_file(root_descriptor, fixture.private_oracle.path)
        _require_digest(oracle_bytes, fixture.private_oracle.sha256)
        try:
            oracle_text = oracle_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise FixtureLoadError("Private oracle is not UTF-8.") from error
        require_safe_synthetic_text(oracle_text, location_class="private-oracle")

    return LoadedFixture(
        fixture=fixture,
        fixture_sha256=canonical_sha256(value),
        evidence=tuple(verified),
    )


@contextmanager
def _open_verified_root(case_root: Path):
    try:
        expected = case_root.lstat()
    except OSError as error:
        raise FixtureLoadError("Fixture root is unavailable.") from error
    if stat.S_ISLNK(expected.st_mode) or not stat.S_ISDIR(expected.st_mode):
        raise FixtureLoadError("Fixture root must be a real directory.")
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory is None:
        raise FixtureLoadError("Platform lacks no-follow fixture protections.")
    descriptor: int | None = None
    try:
        descriptor = os.open(case_root, os.O_RDONLY | directory | no_follow)
        actual = os.fstat(descriptor)
        if not stat.S_ISDIR(actual.st_mode) or (actual.st_dev, actual.st_ino) != (
            expected.st_dev,
            expected.st_ino,
        ):
            raise FixtureLoadError("Fixture root identity changed during open.")
        yield descriptor
    except FixtureLoadError:
        raise
    except OSError as error:
        raise FixtureLoadError("Fixture root cannot be opened safely.") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _canonical_relative_path(value: str) -> tuple[str, ...]:
    if (
        value != unicodedata.normalize("NFC", value)
        or "\\" in value
        or any(unicodedata.category(character) in {"Cc", "Cf"} for character in value)
    ):
        raise FixtureLoadError("Fixture path is not canonical.")
    path = PurePosixPath(value)
    parts = path.parts
    if (
        path.is_absolute()
        or not parts
        or any(part in {"", ".", ".."} for part in parts)
        or path.as_posix() != value
    ):
        raise FixtureLoadError("Fixture path must be exact and relative.")
    return parts


def _read_regular_file(root_descriptor: int, relative_path: str) -> bytes:
    parts = _canonical_relative_path(relative_path)
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory is None:
        raise FixtureLoadError("Platform lacks no-follow fixture protections.")

    descriptors: list[int] = []
    try:
        current = os.dup(root_descriptor)
        descriptors.append(current)
        for component in parts[:-1]:
            current = os.open(
                component,
                os.O_RDONLY | directory | no_follow,
                dir_fd=current,
            )
            descriptors.append(current)
        file_descriptor = os.open(parts[-1], os.O_RDONLY | no_follow, dir_fd=current)
        descriptors.append(file_descriptor)
        metadata = os.fstat(file_descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_FILE_BYTES:
            raise FixtureLoadError("Fixture input is not a bounded regular file.")
        chunks: list[bytes] = []
        remaining = _MAX_FILE_BYTES + 1
        while remaining:
            chunk = os.read(file_descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > _MAX_FILE_BYTES:
            raise FixtureLoadError("Fixture input exceeds the size limit.")
        return content
    except FixtureLoadError:
        raise
    except OSError as error:
        raise FixtureLoadError("Fixture input cannot be read safely.") from error
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _load_json_object(content: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise FixtureLoadError("Fixture JSON contains a duplicate field.")
            result[key] = value
        return result

    try:
        value = json.loads(content, object_pairs_hook=reject_duplicates)
    except FixtureLoadError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FixtureLoadError(
            "Fixture case document is not valid UTF-8 JSON."
        ) from error
    if not isinstance(value, dict):
        raise FixtureLoadError("Fixture case document must be an object.")
    return value


def _require_digest(content: bytes, expected: str) -> None:
    if hashlib.sha256(content).hexdigest() != expected:
        raise FixtureLoadError("Fixture content digest mismatch.")


def _validate_fixture_invariants(fixture: EvaluationFixture) -> None:
    evidence_paths = tuple(item.path for item in fixture.evidence_files)
    if len(set(evidence_paths)) != len(evidence_paths):
        raise FixtureLoadError("Fixture evidence paths must be unique.")
    if fixture.private_oracle.path in evidence_paths:
        raise FixtureLoadError("Private oracle cannot be runtime evidence.")
    if any(
        item.fixture_namespace != fixture.fixture_namespace
        for item in fixture.evidence_files
    ):
        raise FixtureLoadError("Synthetic fixture namespace mismatch.")
    for path in (*evidence_paths, fixture.private_oracle.path):
        _canonical_relative_path(path)
