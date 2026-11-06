"""COPILOT_HOME isolation: no `cc release` command may touch the real home when it is set.

Incident 2026-11-06 (WP-295): a QA rollback with only COPILOT_HOME set moved the real ~/.copilot/current.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc.commands.release import release_app
from cc.core.release.engine import build, layout, pointer

from .conftest import fake_post_build, fake_verifier

runner = CliRunner()


def snapshot(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for dirpath, dirs, files in os.walk(root):
        for name in dirs + files:
            p = Path(dirpath, name)
            rel = str(p.relative_to(root))
            out[rel] = ("link:" + os.readlink(p)) if p.is_symlink() else (
                "dir" if p.is_dir() else p.read_bytes().hex())
    return out


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A sentinel 'real' home that must never change, and an isolated home selected by COPILOT_HOME."""
    real = tmp_path / "real"
    (real / ".copilot" / "releases" / "REAL").mkdir(parents=True)
    (real / ".copilot" / "current").symlink_to(real / ".copilot" / "releases" / "REAL")
    (real / ".copilot" / "release-history.jsonl").write_text('{"action": "flip", "release": "REAL"}\n')
    (real / ".local" / "bin").mkdir(parents=True)
    (real / ".codex").mkdir()
    iso = tmp_path / "iso"
    iso.mkdir()
    monkeypatch.setenv("HOME", str(real))
    monkeypatch.setenv("COPILOT_HOME", str(iso / ".copilot"))
    monkeypatch.setenv("CODEX_HOME", str(real / ".codex"))  # ambient real value must not leak in
    return real, iso


def run(*args: str):
    return runner.invoke(release_app, list(args))


def test_every_subcommand_leaves_the_real_home_untouched(machine, tmp_path):
    real, iso = machine
    before = snapshot(real)
    assert layout.copilot_home() == iso / ".copilot"
    assert layout.bin_dir() == iso / ".local" / "bin"
    assert layout.links_receipt_path() == iso / ".copilot" / "links-receipt.json"
    for cmd in (("status",), ("history",), ("prune",), ("shims",), ("doctor",)):
        run(*cmd)
        assert snapshot(real) == before, cmd
    assert (iso / ".local" / "bin" / "cc").is_file()  # shims went to the isolated home
    bad = tmp_path / "pins.json"
    bad.write_text("{}")
    for cmd in (("build", "--pins", str(bad)), ("publish", "--pins", str(bad))):
        run(*cmd)
        assert snapshot(real) == before, cmd


def test_flip_and_rollback_move_only_the_isolated_pointer(machine, make_sources, tmp_path):
    real, iso = machine
    first = build.build_release(make_sources("v1"), None, verifier=fake_verifier, post_build=fake_post_build)
    second = build.build_release(make_sources("v2"), None, verifier=fake_verifier, post_build=fake_post_build)
    assert (iso / ".copilot" / "releases" / first.release_id).is_dir()
    before = snapshot(real)
    assert run("flip", first.release_id).exit_code == 0
    assert run("flip", second.release_id).exit_code == 0
    assert run("rollback").exit_code == 0
    assert pointer.current_release_id() == first.release_id
    assert pointer.current_release_id(iso) == first.release_id
    assert [r["action"] for r in json.loads(run("history").output)][-3:] == ["flip", "flip", "rollback"]
    assert snapshot(real) == before
    for rel in (first, second):  # temp releases are read-only; let pytest clean them up
        for dirpath, _, files in os.walk(iso / ".copilot" / "releases" / rel.release_id):
            os.chmod(dirpath, 0o700)
            for f in files:
                if not os.path.islink(os.path.join(dirpath, f)):
                    os.chmod(os.path.join(dirpath, f), 0o600)


def test_codex_home_defaults_into_the_isolated_home(machine):
    from cc.core.release.codex import step

    real, iso = machine
    assert step.default_codex_home() == iso / ".codex"


@pytest.mark.parametrize("cmd", [("status",), ("history",), ("flip", "x"), ("rollback",), ("shims",), ("doctor",),
                                 ("prune",), ("build", "--pins", "p"), ("publish", "--pins", "p")])
def test_unusable_copilot_home_refuses_before_acting(machine, monkeypatch, tmp_path, cmd):
    real, _ = machine
    monkeypatch.setenv("COPILOT_HOME", str(tmp_path / "somewhere"))
    before = snapshot(real)
    result = run(*cmd)
    assert result.exit_code == 1 and "COPILOT_HOME" in (result.output + (result.stderr if result.stderr_bytes else ""))
    assert snapshot(real) == before


def test_explicit_home_still_wins_over_the_environment(machine, tmp_path):
    other = tmp_path / "other"
    assert layout.copilot_home(other) == other / ".copilot"
