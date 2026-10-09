"""Tests for tc.services.track: committing task state to Git."""

from __future__ import annotations

import subprocess

import pytest

from tc.services.track import BEGIN, ensure_tracked, rendered


def _ignored(repo, path):
    return subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", "--no-index", path]).returncode == 0


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


@pytest.mark.parametrize("existing", ["", ".copilot/\n", ".copilot/tasks.db*\n", "*.db\n", "/.copilot\nnode_modules/\n"])
def test_task_state_committed_side_files_ignored(repo, existing):
    (repo / ".gitignore").write_text(existing)
    assert ensure_tracked(repo) is True
    for path in (".copilot/tasks.db", ".copilot/tasks.db-history", ".copilot/wp/12.md"):
        assert not _ignored(repo, path), path
    for path in (".copilot/tasks.db-wal", ".copilot/tasks.db-shm", ".copilot/tasks.db-history-journal",
                 ".copilot/tasks.db-archive-stamp"):
        assert _ignored(repo, path), path


def test_whole_dir_rule_keeps_other_contents_ignored(repo):
    (repo / ".gitignore").write_text(".copilot/\n")
    ensure_tracked(repo)
    assert _ignored(repo, ".copilot/build-cache/x.bin")


def test_idempotent_and_check_mode(repo):
    (repo / ".gitignore").write_text("node_modules/\n")
    assert ensure_tracked(repo) is True
    text = (repo / ".gitignore").read_text()
    assert ensure_tracked(repo) is False
    assert ensure_tracked(repo, check=True) is False
    assert text.count(BEGIN) == 1


def test_check_does_not_write(repo):
    (repo / ".gitignore").write_text(".copilot/\n")
    assert ensure_tracked(repo, check=True) is True
    assert (repo / ".gitignore").read_text() == ".copilot/\n"


def test_crlf_preserved():
    out = rendered("a\r\nb\r\n")
    assert "\r\n" in out and "\n" not in out.replace("\r\n", "")


def test_tc_init_applies_standard(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from tc.main import app

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".copilot/\n")
    monkeypatch.chdir(tmp_path)
    assert CliRunner().invoke(app, ["init"]).exit_code == 0
    assert not _ignored(tmp_path, ".copilot/tasks.db")
    assert CliRunner().invoke(app, ["db", "track", "--check"]).exit_code == 0
