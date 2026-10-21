"""A fresh canonical install must pass the installed project's own fitness check.

Regression for 2026-10-06: a clean consumer install (every lock checksum
matching, hooks firing, agents byte-identical to the framework) failed its own
`.claude/fitness-check.sh` with 38 failures, every one of them framework-caused:
agents pointed at repo-relative `.claude/skills/...` files the installer never
ships (FF11), FF9 demanded a framework-only context-budget baseline, and FF12
compared the project against the machine's stale ~/.claude/agents while
searching the PROJECT's git for agent history.

This drives the real installer (the canonical plan/apply transaction) from a
tagged release fixture built out of this working tree, then runs the installed
script exactly as a consumer would, with a fresh HOME and no usable `cc`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from cc.core.ecosystem.canonical_transaction import build_canonical_project_request
from cc.core.ecosystem.project_plan_store import issue_plan
from cc.core.ecosystem.reconciliation import build_apply_report, build_plan_report

from tests.test_canonical_project_transaction import (
    _census,
    _configure_sources,
    _git_project,
    _machine,
    _reference_sources,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
_IGNORE = shutil.ignore_patterns(
    "worktrees", "memory", "settings.local.json", "__pycache__", "*.pyc", ".DS_Store"
)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _framework_release(tmp_path: Path) -> tuple[Path, str]:
    """This working tree's installable framework content, committed and tagged."""
    framework = tmp_path / "framework"
    framework.mkdir()
    shutil.copytree(REPO_ROOT / ".claude", framework / ".claude", ignore=_IGNORE, symlinks=True)
    shutil.copytree(REPO_ROOT / "templates", framework / "templates", ignore=_IGNORE)
    for name in ("VERSION.json", "CLAUDE.md"):
        shutil.copy2(REPO_ROOT / name, framework / name)
    version = json.loads((framework / "VERSION.json").read_text())["framework"]
    _git(framework, "init", "-q")
    _git(framework, "config", "user.email", "fixture@example.invalid")
    _git(framework, "config", "user.name", "Fixture")
    _git(framework, "add", "-A")
    _git(framework, "commit", "-qm", f"release {version}")
    _git(framework, "tag", "-a", f"v{version}", "-m", f"release {version}")
    return framework, version


def _install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, framework: Path) -> Path:
    _, codex, _ = _reference_sources(tmp_path)
    _configure_sources(monkeypatch, framework, codex)
    authority = tmp_path / "projects"
    project = _git_project(authority, "consumer")
    request = build_canonical_project_request(project, approved_roots=(authority,))
    state_root = tmp_path / "transaction-state"

    def machine_builder() -> dict[str, Any]:
        return _machine(authority.resolve())

    census_builder = _census(project, authority.resolve())
    plan = build_plan_report(
        request,
        machine_builder=machine_builder,
        census_builder=census_builder,
        plan_issuer=lambda **kwargs: issue_plan(**kwargs, root=state_root),
    )
    applied = build_apply_report(
        request,
        plan["plan_id"],
        machine_builder=machine_builder,
        census_builder=census_builder,
        state_root=state_root,
    )
    assert applied["result"] == "applied", applied
    return project


def _run_fitness(project: Path, framework: Path, tmp_path: Path) -> subprocess.CompletedProcess:
    # A fresh machine: empty HOME (no ~/.claude/skills, no stale
    # ~/.claude/agents) and a `cc` that is not Copilot's (the macOS compiler
    # case), so skill names must resolve from the framework catalog on disk.
    home = tmp_path / "fresh-home"
    home.mkdir(exist_ok=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    fake_cc = fake_bin / "cc"
    fake_cc.write_text("#!/bin/sh\necho 'clang: error: no input files' >&2\nexit 1\n")
    fake_cc.chmod(0o755)
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("CC_")},
        "HOME": str(home),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
        "CC_COPILOT_PATH": str(framework),
    }
    return subprocess.run(
        ["bash", ".claude/fitness-check.sh"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def _failures(output: str) -> list[str]:
    return re.findall(r"^\s*\[FAIL\] (.*)$", output, re.MULTILINE)


def test_fresh_install_passes_its_own_fitness_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    framework, version = _framework_release(tmp_path)
    project = _install(tmp_path, monkeypatch, framework)

    lock = json.loads((project / "copilot.lock.json").read_text())
    claude = next(c for c in lock["components"] if c["component"] == "claude")
    assert claude["release_tag"] == f"v{version}"
    assert not (project / ".claude/skills/security").exists(), (
        "the installer does not ship framework skills; agents must not need it to"
    )

    result = _run_fitness(project, framework, tmp_path)
    output = result.stdout + result.stderr
    assert _failures(output) == [], output
    assert result.returncode == 0, output
    assert "Fitness mode: consumer" in output
    assert "[SKIP] consumer project -- the context budget" in output
    assert f"release_tag v{version} is a tag in the framework repo" in output
    assert "skill `stride-dread`" in output


def test_lock_naming_an_untagged_release_fails_fitness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 2026-10-06 state: a project locked to a version that was released
    by version-bump merge but never tagged."""
    framework, version = _framework_release(tmp_path)
    project = _install(tmp_path, monkeypatch, framework)
    _git(framework, "tag", "-d", f"v{version}")

    result = _run_fitness(project, framework, tmp_path)
    failures = _failures(result.stdout)
    assert result.returncode == 1
    assert failures == [
        f"copilot.lock.json is locked to v{version}, which the framework repo at "
        f"{framework} has not tagged (fetch tags, or the release was never tagged)"
    ], result.stdout
