from __future__ import annotations

import subprocess
from pathlib import Path

from cc.core.ecosystem.project_locking import project_lock
from cc.core.ecosystem.project_snapshots import SnapshotVault


def _repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=path, check=True)
    return path


def test_snapshot_vault_restores_file_link_directory_and_missing(tmp_path) -> None:
    project = _repo(tmp_path / "project")
    (project / "file.txt").write_text("before\n", encoding="utf-8")
    (project / "link").symlink_to("../external")
    tree = project / "tree"
    tree.mkdir()
    (tree / "nested.txt").write_text("nested\n", encoding="utf-8")

    with project_lock(project, lock_root=tmp_path / "locks") as anchored:
        vault = SnapshotVault(tmp_path / "vault")
        original = {
            target: vault.capture(anchored, target)
            for target in ("file.txt", "link", "tree", "missing.txt")
        }
        anchored.atomic_write("file.txt", b"after\n")
        anchored.atomic_symlink("link", "file.txt")
        anchored.remove("tree")
        anchored.atomic_write("tree/replacement.txt", b"replacement\n")
        anchored.atomic_write("missing.txt", b"created\n")

        outcomes = []
        for target in original:
            outcomes.append(
                vault.restore(
                    anchored,
                    target,
                    expected_current_fingerprint=anchored.fingerprint(target),
                )
            )
        assert [item.status for item in outcomes] == ["restored"] * 4
        assert anchored.read_bytes("file.txt") == b"before\n"
        assert anchored.readlink("link") == "../external"
        assert anchored.read_bytes("tree/nested.txt") == b"nested\n"
        assert anchored.lstat("missing.txt") is None


def test_compare_and_swap_rollback_never_overwrites_later_edit(tmp_path) -> None:
    project = _repo(tmp_path / "project")
    (project / "owned.txt").write_text("before\n", encoding="utf-8")
    with project_lock(project, lock_root=tmp_path / "locks") as anchored:
        vault = SnapshotVault(tmp_path / "vault")
        vault.capture(anchored, "owned.txt")
        anchored.atomic_write("owned.txt", b"transaction-output\n")
        transaction_fingerprint = anchored.fingerprint("owned.txt")
        anchored.atomic_write("owned.txt", b"human-edit\n")
        outcome = vault.restore(
            anchored,
            "owned.txt",
            expected_current_fingerprint=transaction_fingerprint,
        )
        assert outcome.status == "conflict"
        assert anchored.read_bytes("owned.txt") == b"human-edit\n"


def test_nested_missing_snapshot_restores_absent_ancestors_exactly(tmp_path) -> None:
    project = _repo(tmp_path / "project")
    with project_lock(project, lock_root=tmp_path / "locks") as anchored:
        vault = SnapshotVault(tmp_path / "vault")
        record = vault.capture(anchored, ".claude/commands/protocol.md")

        assert record.kind == "missing"
        assert record.missing_parents == (".claude", ".claude/commands")
        anchored.atomic_write(".claude/commands/protocol.md", b"managed\n")
        outcome = vault.restore(
            anchored,
            ".claude/commands/protocol.md",
            expected_current_fingerprint=anchored.fingerprint(
                ".claude/commands/protocol.md"
            ),
        )

        assert outcome.status == "restored"
        assert (
            anchored.fingerprint(".claude/commands/protocol.md") == record.fingerprint
        )
    assert not (project / ".claude").exists()


def test_nested_rollback_never_removes_parent_with_peer_content(tmp_path) -> None:
    project = _repo(tmp_path / "project")
    with project_lock(project, lock_root=tmp_path / "locks") as anchored:
        vault = SnapshotVault(tmp_path / "vault")
        vault.capture(anchored, ".claude/commands/protocol.md")
        anchored.atomic_write(".claude/commands/protocol.md", b"managed\n")
        anchored.atomic_write(".claude/commands/human.md", b"human\n")
        outcome = vault.restore(
            anchored,
            ".claude/commands/protocol.md",
            expected_current_fingerprint=anchored.fingerprint(
                ".claude/commands/protocol.md"
            ),
        )

        assert outcome.status == "restored"
        assert anchored.read_bytes(".claude/commands/human.md") == b"human\n"
    assert (project / ".claude/commands").is_dir()
