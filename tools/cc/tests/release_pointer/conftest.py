"""Fixtures: a real git repo with tags, fake signature verifier, temp HOME."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cc.core.release.engine import build, layout


def git(root: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", "-C", str(root), "-c", "commit.gpgsign=false",
                           "-c", "tag.gpgsign=false", *args],
                          check=True, capture_output=True, text=True, env=env).stdout.strip()


@pytest.fixture
def home(tmp_path):
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "tools" / "tc").mkdir(parents=True)
    (root / "tools" / "tc" / "tc-limits").write_text("#!/bin/sh\necho tc-limits-ran\n")
    os.chmod(root / "tools" / "tc" / "tc-limits", 0o755)
    (root / "VERSION").write_text("1\n")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "one")
    git(root, "tag", "-a", "v1", "-m", "v1")
    (root / "VERSION").write_text("2\n")
    git(root, "commit", "-qam", "two")
    git(root, "tag", "-a", "v2", "-m", "v2")
    return root


@pytest.fixture
def live(tmp_path):
    out = {}
    for name in ("knowledge", "claude", "codex", "cli"):
        directory = tmp_path / f"live-{name}"
        directory.mkdir()
        (directory / "marker.txt").write_text(name)
        out[name] = directory
    return out


def fake_verifier(src):
    commit = git(Path(src.source), "rev-parse", f"{src.ref}^{{commit}}")
    return build.VerifiedTag(commit=commit, signer="SHA256:test")


def fake_post_build(release_dir, components):
    python = release_dir / layout.CC_VENV_PYTHON_RELATIVE
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text(f"#!/bin/sh\necho cc-from-{release_dir.name}\n")
    os.chmod(python, 0o755)


@pytest.fixture
def make_sources(repo, live):
    def _make(claude_ref="v1"):
        out = []
        for name in layout.all_component_names():
            if name == layout.COMPONENT_CONTROL_TOWER:
                out.append(build.ComponentSource(name, "framework", layout.KIND_RECORD, version="0.6.11"))
            elif name.endswith("/personal"):
                product = name.split("/")[0]
                out.append(build.ComponentSource(name, "personal", layout.KIND_LIVE, ref="main",
                                                 source=str(live[product])))
            else:
                ref = claude_ref if name == layout.COMPONENT_CLAUDE else "v1"
                out.append(build.ComponentSource(name, "x", layout.KIND_SIGNED, version=ref, ref=ref,
                                                 source=str(repo), allowed_signers=("SHA256:test",)))
        return out
    return _make


@pytest.fixture
def make_release(home, make_sources):
    counter = {"n": 0}

    def _build(claude_ref="v1", **kwargs):
        counter["n"] += 1
        now = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=counter["n"])
        kwargs.setdefault("verifier", fake_verifier)
        kwargs.setdefault("post_build", fake_post_build)
        return build.build_release(make_sources(claude_ref), home, now=now, **kwargs)
    return _build
