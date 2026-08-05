from __future__ import annotations

import multiprocessing
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from cc.core.ecosystem.project_locking import (
    ProjectIdentityMismatch,
    ProjectLockContention,
    inspect_project_identity,
    project_lock,
)

from cc.core.ecosystem import project_locking


def _git(project: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=project, check=True, capture_output=True)


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    (path / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(
        path,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    return path


def _hold_lock(project: str, lock_root: str, ready: str, release: str) -> None:
    with project_lock(project, lock_root=Path(lock_root)):
        Path(ready).write_text("ready", encoding="utf-8")
        while not Path(release).exists():
            time.sleep(0.01)


def test_same_project_aliases_contend_on_one_canonical_lock(tmp_path) -> None:
    project = _repo(tmp_path / "project")
    lock_root = tmp_path / "locks"
    ready = tmp_path / "ready"
    release = tmp_path / "release"
    process = multiprocessing.Process(
        target=_hold_lock,
        args=(str(project), str(lock_root), str(ready), str(release)),
    )
    process.start()
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        alias_parent = tmp_path / "alias-parent"
        alias_parent.mkdir()
        alias = alias_parent / ".." / project.name
        assert (
            inspect_project_identity(alias).lock_key
            == inspect_project_identity(project).lock_key
        )
        with pytest.raises(ProjectLockContention):
            with project_lock(alias, lock_root=lock_root):
                raise AssertionError("the contending process must not enter")
    finally:
        release.write_text("release", encoding="utf-8")
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
    assert process.exitcode == 0


def test_plan_identity_mismatch_refuses_before_opening_project(tmp_path) -> None:
    project = _repo(tmp_path / "project")
    identity = inspect_project_identity(project).as_dict()
    identity["inode"] += 1
    with pytest.raises(ProjectIdentityMismatch):
        with project_lock(
            project, expected_identity=identity, lock_root=tmp_path / "locks"
        ):
            raise AssertionError("mismatched identity must not enter")


def test_symlinked_project_root_is_never_accepted(tmp_path) -> None:
    project = _repo(tmp_path / "project")
    linked = tmp_path / "linked"
    linked.symlink_to(project, target_is_directory=True)
    with pytest.raises(ProjectIdentityMismatch):
        inspect_project_identity(linked)


def test_symlinked_git_directory_is_never_accepted(tmp_path) -> None:
    project = _repo(tmp_path / "project")
    moved = tmp_path / "moved-git"
    (project / ".git").rename(moved)
    (project / ".git").symlink_to(moved, target_is_directory=True)

    with pytest.raises(ProjectIdentityMismatch, match="symlinked"):
        inspect_project_identity(project)


def test_git_worktree_file_resolves_to_a_no_follow_git_directory(tmp_path) -> None:
    project = _repo(tmp_path / "project")
    worktree = tmp_path / "worktree"
    _git(project, "worktree", "add", "-qb", "fixture-worktree", str(worktree))

    identity = inspect_project_identity(worktree)

    assert (worktree / ".git").is_file()
    assert identity.path == str(worktree)


def test_gitfile_with_symlinked_gitdir_ancestor_is_rejected(tmp_path) -> None:
    project = _repo(tmp_path / "project")
    worktree = tmp_path / "worktree"
    _git(project, "worktree", "add", "-qb", "linked-worktree", str(worktree))
    line = (worktree / ".git").read_text(encoding="utf-8").strip()
    actual = Path(line.removeprefix("gitdir: "))
    linked_parent = tmp_path / "linked-git-parent"
    linked_parent.symlink_to(actual.parent, target_is_directory=True)
    (worktree / ".git").write_text(
        f"gitdir: {linked_parent / actual.name}\n", encoding="utf-8"
    )

    with pytest.raises(ProjectIdentityMismatch, match="symlinked or unavailable"):
        inspect_project_identity(worktree)


def test_project_identity_requires_current_user_owned_root(
    tmp_path, monkeypatch
) -> None:
    project = _repo(tmp_path / "project")
    owner_uid = project.stat().st_uid
    monkeypatch.setattr(project_locking, "_effective_uid", lambda: owner_uid + 1)

    with pytest.raises(ProjectIdentityMismatch, match="root is not owned"):
        inspect_project_identity(project)


def test_project_identity_requires_current_user_owned_git_entry(
    tmp_path, monkeypatch
) -> None:
    project = _repo(tmp_path / "project")
    git_entry = project / ".git"
    real_lstat = Path.lstat

    def adversarial_lstat(path):
        metadata = real_lstat(path)
        if path == git_entry:
            return SimpleNamespace(
                st_mode=metadata.st_mode,
                st_uid=metadata.st_uid + 1,
            )
        return metadata

    monkeypatch.setattr(Path, "lstat", adversarial_lstat)

    with pytest.raises(ProjectIdentityMismatch, match="Git entry is not owned"):
        inspect_project_identity(project)


def test_project_identity_requires_current_user_owned_git_directory(
    tmp_path, monkeypatch
) -> None:
    project = _repo(tmp_path / "project")
    git_dir = project / ".git"
    real_stat = project_locking._no_follow_directory_stat

    def adversarial_stat(path):
        metadata = real_stat(path)
        if path == git_dir:
            return SimpleNamespace(
                st_mode=metadata.st_mode,
                st_dev=metadata.st_dev,
                st_ino=metadata.st_ino,
                st_uid=metadata.st_uid + 1,
            )
        return metadata

    monkeypatch.setattr(project_locking, "_no_follow_directory_stat", adversarial_stat)

    with pytest.raises(ProjectIdentityMismatch, match="Git directory is not owned"):
        inspect_project_identity(project)


def test_clean_symbolic_branch_switch_invalidates_reviewed_identity(tmp_path) -> None:
    project = _repo(tmp_path / "project")
    reviewed = inspect_project_identity(project)
    _git(project, "switch", "-qc", "alternate")
    switched = inspect_project_identity(project)

    assert switched.head_oid == reviewed.head_oid
    assert switched.head_ref != reviewed.head_ref
    assert switched.owner_uid == project.stat().st_uid
    assert switched.git_owner_uid == (project / ".git").stat().st_uid
    with pytest.raises(ProjectIdentityMismatch):
        with project_lock(
            project,
            expected_identity=reviewed,
            lock_root=tmp_path / "locks",
        ):
            raise AssertionError("a switched clean branch must not enter")


def test_clean_head_oid_change_invalidates_reviewed_identity(tmp_path) -> None:
    project = _repo(tmp_path / "project")
    reviewed = inspect_project_identity(project)
    (project / "README.md").write_text("second commit\n", encoding="utf-8")
    _git(project, "add", "README.md")
    _git(
        project,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "second fixture",
    )
    advanced = inspect_project_identity(project)

    assert advanced.head_ref == reviewed.head_ref
    assert advanced.head_oid != reviewed.head_oid
    with pytest.raises(ProjectIdentityMismatch):
        with project_lock(
            project,
            expected_identity=reviewed,
            lock_root=tmp_path / "locks",
        ):
            raise AssertionError("a changed clean HEAD must not enter")


def test_clean_detached_head_invalidates_symbolic_reviewed_identity(tmp_path) -> None:
    project = _repo(tmp_path / "project")
    reviewed = inspect_project_identity(project)
    _git(project, "switch", "--detach", "-q", "HEAD")
    detached = inspect_project_identity(project)

    assert detached.head_oid == reviewed.head_oid
    assert reviewed.head_ref is not None
    assert detached.head_ref is None
    with pytest.raises(ProjectIdentityMismatch):
        with project_lock(
            project,
            expected_identity=reviewed,
            lock_root=tmp_path / "locks",
        ):
            raise AssertionError("a detached clean HEAD must not enter")
