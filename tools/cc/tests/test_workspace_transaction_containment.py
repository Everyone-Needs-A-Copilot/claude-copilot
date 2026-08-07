from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from cc.core.ecosystem.project_locking import (
    UnsafeProjectPath,
    ensure_private_directory,
    normalize_relative_target,
    project_lock,
)

from cc.core.ecosystem import project_locking


def _repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=path, check=True)
    return path


@pytest.mark.parametrize(
    "target",
    [
        "/absolute",
        "../escape",
        "safe/../../escape",
        "./dot",
        "",
        "nul\x00x",
        "win\\path",
    ],
)
def test_lexical_path_traversal_is_rejected(target: str) -> None:
    with pytest.raises(UnsafeProjectPath):
        normalize_relative_target(target)


def test_symlinked_parent_cannot_redirect_write_outside_project(tmp_path) -> None:
    project = _repo(tmp_path / "project")
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / "linked").symlink_to(outside, target_is_directory=True)
    with project_lock(project, lock_root=tmp_path / "locks") as anchored:
        with pytest.raises(UnsafeProjectPath):
            anchored.atomic_write("linked/escaped.txt", b"must-not-write")
    assert list(outside.iterdir()) == []


def test_internal_relative_link_may_walk_up_but_never_escape_root(tmp_path) -> None:
    project = _repo(tmp_path / "project")
    (project / "plugins/skills").mkdir(parents=True)
    with project_lock(project, lock_root=tmp_path / "locks") as anchored:
        anchored.atomic_symlink(
            ".claude/skills/copilot",
            "../../plugins/skills",
        )
        assert anchored.readlink(".claude/skills/copilot") == "../../plugins/skills"
        with pytest.raises(UnsafeProjectPath):
            anchored.atomic_symlink("top-link", "../outside")


def test_private_state_rejects_symlink_in_boundary_ancestry(tmp_path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    parent = tmp_path / "private-parent"
    parent.mkdir()
    (parent / "linked").symlink_to(outside, target_is_directory=True)
    target = parent / "linked/state/transactions"

    with pytest.raises(UnsafeProjectPath, match="ancestor"):
        ensure_private_directory(target, boundary=parent / "linked/state")

    assert list(outside.iterdir()) == []


def test_private_state_rejects_boundary_not_owned_by_effective_user(
    tmp_path, monkeypatch
) -> None:
    boundary = tmp_path / "state"
    boundary.mkdir()
    boundary_stat = boundary.stat()
    real_fstat = project_locking.os.fstat

    def adversarial_fstat(descriptor):
        metadata = real_fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino) == (
            boundary_stat.st_dev,
            boundary_stat.st_ino,
        ):
            return SimpleNamespace(st_uid=metadata.st_uid + 1)
        return metadata

    monkeypatch.setattr(project_locking.os, "fstat", adversarial_fstat)

    with pytest.raises(UnsafeProjectPath, match="not owned"):
        ensure_private_directory(boundary / "transactions", boundary=boundary)

    assert not (boundary / "transactions").exists()
