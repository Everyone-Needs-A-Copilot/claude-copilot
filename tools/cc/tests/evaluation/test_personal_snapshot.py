from __future__ import annotations

import copy
import json
import os
import shutil
import stat
from dataclasses import replace
from pathlib import Path

import cc.evaluation_fixtures as evaluation_fixtures
import cc.evaluation_fixtures.personal_snapshot as personal_snapshot
import pytest
from cc.evaluation_fixtures import (
    PACKAGED_BUNDLE_SHA256,
    PACKAGED_MATRIX_SHA256,
    PACKAGED_PERSONAL_LAYER_SHA256,
    PackagedFixtureUnavailable,
    packaged_personal_layer_root,
)
from cc.evaluation_fixtures.personal_snapshot import (
    PERSONAL_SNAPSHOT_SHA256,
    PersonalSnapshotUnavailable,
    materialize_personal_snapshot,
    personal_snapshot_manifest,
    personal_snapshot_receipt_document,
    verify_personal_snapshot_receipt,
)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def test_packaged_snapshot_materializes_exact_private_content_and_safe_receipt(
    tmp_path: Path,
) -> None:
    manifest = personal_snapshot_manifest()
    destination = tmp_path / "private-personal-layer"
    receipt = materialize_personal_snapshot(destination)

    assert manifest["snapshot_sha256"] == PERSONAL_SNAPSHOT_SHA256
    assert manifest["matrix_sha256"] == PACKAGED_MATRIX_SHA256
    assert manifest["fixture_bundle_sha256"] == PACKAGED_BUNDLE_SHA256
    assert manifest["synthetic_fixture"] is True
    assert manifest["files"] == [
        {
            "path": "doc.md",
            "sha256": "b46a92c3c7195834e5c76f18e23d1a1bbc69283e32bfadb3cf725cda7294fcad",
            "media_type": "text/markdown",
            "materialized_mode": "0600",
        }
    ]
    assert _mode(destination) == 0o700
    assert _mode(destination / "doc.md") == 0o600
    assert tuple(item.name for item in destination.iterdir()) == ("doc.md",)
    assert receipt.validate()
    assert verify_personal_snapshot_receipt(receipt)

    document = personal_snapshot_receipt_document(receipt)
    serialized = json.dumps(document, sort_keys=True)
    assert document["root_path"] == str(destination)
    assert document["files"][0]["materialized_path"] == str(destination / "doc.md")
    assert "PERSONAL_ONLY" not in serialized
    assert "terse decision brief" not in serialized
    assert "content" not in document
    assert set(document) == {
        "schema_version",
        "receipt_sha256",
        "snapshot_sha256",
        "matrix_sha256",
        "release_identity_sha256",
        "package_identity_sha256",
        "materialization_sha256",
        "root_path",
        "files",
    }

    source = packaged_personal_layer_root() / "doc.md"
    assert (destination / "doc.md").read_bytes() == source.read_bytes()
    text = source.read_text(encoding="utf-8")
    assert "\r" not in text
    assert len([line for line in text.splitlines() if line]) == 5


@pytest.mark.parametrize("kind", ("file", "directory", "symlink"))
def test_materializer_rejects_every_preexisting_destination(
    tmp_path: Path,
    kind: str,
) -> None:
    destination = tmp_path / "already-present"
    if kind == "file":
        destination.write_text("occupied", encoding="utf-8")
    elif kind == "directory":
        destination.mkdir()
    else:
        destination.symlink_to("missing-target")

    with pytest.raises(PersonalSnapshotUnavailable, match="already exists"):
        materialize_personal_snapshot(destination)


@pytest.mark.parametrize(
    "mutation",
    (
        "extra-file",
        "extra-symlink",
        "content",
        "file-mode",
        "directory-mode",
        "hardlink",
        "file-replacement",
        "path-replacement",
    ),
)
def test_retained_receipt_rejects_mutation_and_identity_substitution(
    tmp_path: Path,
    mutation: str,
) -> None:
    destination = tmp_path / "private-personal-layer"
    receipt = materialize_personal_snapshot(destination)
    document = destination / "doc.md"

    if mutation == "extra-file":
        (destination / "extra.txt").write_text("extra", encoding="utf-8")
    elif mutation == "extra-symlink":
        (destination / "extra-link").symlink_to("doc.md")
    elif mutation == "content":
        document.write_text("mutated", encoding="utf-8")
    elif mutation == "file-mode":
        document.chmod(0o640)
    elif mutation == "directory-mode":
        destination.chmod(0o750)
    elif mutation == "hardlink":
        os.link(document, tmp_path / "second-link")
    elif mutation == "file-replacement":
        retained = tmp_path / "retained-doc.md"
        document.rename(retained)
        document.write_bytes(retained.read_bytes())
        document.chmod(0o600)
    else:
        retained = tmp_path / "retained-root"
        destination.rename(retained)
        destination.mkdir(mode=0o700)
        document.write_bytes((retained / "doc.md").read_bytes())
        document.chmod(0o600)

    assert not receipt.validate()
    with pytest.raises(PersonalSnapshotUnavailable, match="not exact"):
        personal_snapshot_receipt_document(receipt)


def test_receipt_copy_and_replace_cannot_reuse_retained_authority(
    tmp_path: Path,
) -> None:
    receipt = materialize_personal_snapshot(tmp_path / "private-personal-layer")

    copied = copy.copy(receipt)
    assert not verify_personal_snapshot_receipt(copied)
    assert not verify_personal_snapshot_receipt(replace(receipt))
    copied.close()
    assert verify_personal_snapshot_receipt(receipt)
    detached = personal_snapshot_manifest()
    detached["snapshot_sha256"] = "0" * 64
    assert personal_snapshot_manifest()["snapshot_sha256"] == PERSONAL_SNAPSHOT_SHA256


def test_receipt_double_close_never_closes_reused_unrelated_descriptors(
    tmp_path: Path,
) -> None:
    receipt = materialize_personal_snapshot(tmp_path / "private-personal-layer")
    capability = receipt._capability
    retained = {
        capability.parent_descriptor,
        capability.root_descriptor,
        *(descriptor for _name, descriptor in capability.file_descriptors),
    }

    receipt.close()
    unrelated: list[int] = []
    try:
        while not retained.issubset(unrelated):
            unrelated.append(os.open("/dev/null", os.O_RDONLY))
            assert len(unrelated) <= max(retained) + len(retained) + 8

        receipt.close()

        for descriptor in retained:
            os.fstat(descriptor)
    finally:
        for descriptor in unrelated:
            os.close(descriptor)


@pytest.mark.parametrize(
    "mutation",
    ("extra", "directory", "symlink", "cache", "pyc", "content"),
)
def test_packaged_snapshot_allowlist_and_hash_reject_source_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    source_package = Path(evaluation_fixtures.__file__).parent
    copied_package = tmp_path / "evaluation_fixtures"
    shutil.copytree(source_package, copied_package, symlinks=True)
    personal_root = copied_package / "personal_layer"
    if mutation == "extra":
        (personal_root / "extra.txt").write_text("extra", encoding="utf-8")
    elif mutation == "directory":
        (personal_root / "extra-directory").mkdir()
    elif mutation == "symlink":
        (personal_root / "extra-link").symlink_to("doc.md")
    elif mutation == "cache":
        cache = personal_root / "__pycache__"
        cache.mkdir()
        (cache / "snapshot.cpython-312.pyc").write_bytes(b"synthetic-pyc")
    elif mutation == "pyc":
        (personal_root / "snapshot.pyc").write_bytes(b"synthetic-pyc")
    else:
        (personal_root / "doc.md").write_text("substituted", encoding="utf-8")
    monkeypatch.setattr(
        evaluation_fixtures,
        "__file__",
        str(copied_package / "__init__.py"),
    )

    with pytest.raises(
        PackagedFixtureUnavailable,
        match="allowlist|differs from preregistration",
    ):
        packaged_personal_layer_root()


def test_materialization_never_discovers_home_or_real_personal_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_home = Path.home()
    package_parent = packaged_personal_layer_root().parent
    opened_absolute_paths: list[Path] = []
    original_open = personal_snapshot.os.open

    def guarded_open(path, flags, *args, **kwargs):
        candidate = Path(path) if isinstance(path, (str, os.PathLike)) else None
        if candidate is not None and candidate.is_absolute():
            opened_absolute_paths.append(candidate)
            assert not candidate.is_relative_to(real_home)
        return original_open(path, flags, *args, **kwargs)

    def forbidden_home(*_args, **_kwargs):
        raise AssertionError("personal snapshot attempted home discovery")

    monkeypatch.setenv("HOME", str(tmp_path / "sentinel-home"))
    monkeypatch.setattr(personal_snapshot.os, "open", guarded_open)
    monkeypatch.setattr(Path, "home", forbidden_home)

    receipt = materialize_personal_snapshot(tmp_path / "private-personal-layer")

    assert receipt.validate()
    assert opened_absolute_paths
    assert all(
        path.is_relative_to(package_parent) or path.is_relative_to(tmp_path)
        for path in opened_absolute_paths
    )


def test_personal_snapshot_package_identity_and_wheel_source_allowlist() -> None:
    root = packaged_personal_layer_root()
    source_names = {item.name for item in root.iterdir()}

    assert source_names == {"doc.md", "snapshot.json"}
    assert (
        evaluation_fixtures._personal_layer_sha256(root)
        == PACKAGED_PERSONAL_LAYER_SHA256
    )
    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    assert root.is_relative_to(pyproject.parent / "src" / "cc")
    assert 'packages = ["src/cc"]' in pyproject.read_text(encoding="utf-8")
