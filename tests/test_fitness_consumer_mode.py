"""fitness-check.sh in consumer projects vs the framework repo (FF9, FF11, FF12).

The same script ships into every installed project. These tests pin the
behaviour that made a clean consumer install report 38 framework-caused
failures on 2026-10-06; the end-to-end install case lives in
tools/cc/tests/test_fresh_install_fitness.py.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FITNESS = REPO_ROOT / ".claude" / "fitness-check.sh"
AGENTS = REPO_ROOT / ".claude" / "agents"
SKILLS = REPO_ROOT / ".claude" / "skills"
GET_RE = re.compile(r"cc skill get ([A-Za-z0-9_\-]+)")
PATH_REF_RE = re.compile(r"\.claude/skills/[A-Za-z0-9_\-./]+/SKILL\.md")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ("git", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args),
        cwd=cwd, check=True, capture_output=True,
    )


def _framework(tmp_path: Path, tag: str = "v1.0.0") -> Path:
    fw = tmp_path / "framework"
    shutil.copytree(AGENTS, fw / ".claude" / "agents")
    skill = fw / ".claude" / "skills" / "security" / "stride-dread"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: stride-dread\n---\n")
    shutil.copy2(REPO_ROOT / "VERSION.json", fw / "VERSION.json")
    _git(fw, "init", "-q")
    _git(fw, "config", "user.email", "fixture@example.invalid")
    _git(fw, "config", "user.name", "Fixture")
    _git(fw, "add", "-A")
    _git(fw, "commit", "-qm", "release")
    _git(fw, "tag", "-a", tag, "-m", tag)
    return fw


def _consumer(tmp_path: Path, framework: Path, release_tag: str = "v1.0.0") -> Path:
    project = tmp_path / "consumer"
    (project / ".claude").mkdir(parents=True)
    shutil.copytree(framework / ".claude" / "agents", project / ".claude" / "agents")
    shutil.copytree(REPO_ROOT / ".claude" / "commands", project / ".claude" / "commands")
    shutil.copy2(FITNESS, project / ".claude" / "fitness-check.sh")
    shutil.copy2(REPO_ROOT / "CLAUDE.md", project / "CLAUDE.md")
    (project / "copilot.lock.json").write_text(json.dumps(
        {"components": [{"component": "claude", "release_tag": release_tag, "files": []}]}
    ))
    return project


def _run(project: Path, framework: Path, tmp_path: Path, *, cc_names=None, mode=None):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    cc = fake_bin / "cc"
    if cc_names is None:
        cc.write_text("#!/bin/sh\nexit 1\n")
    else:
        listing = json.dumps([{"name": n} for n in cc_names])
        cc.write_text(f"#!/bin/sh\ncat <<'EOF'\n{listing}\nEOF\n")
    cc.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CC_")}
    env.update(HOME=str(home), PATH=f"{fake_bin}{os.pathsep}{env.get('PATH', '')}",
               CC_COPILOT_PATH=str(framework))
    if mode:
        env["CC_FITNESS_MODE"] = mode
    result = subprocess.run(["bash", ".claude/fitness-check.sh"], cwd=project, env=env,
                            capture_output=True, text=True, timeout=300)
    return result.stdout + result.stderr


def _section(output: str, ff: str) -> str:
    m = re.search(rf"=== {ff}:.*?(?=\n=== FF|\n=====)", output, re.DOTALL)
    assert m, output
    return m.group(0)


def _fails(text: str) -> list[str]:
    return re.findall(r"\[FAIL\] (.*)", text)


# ---- the shipped agents themselves -----------------------------------------


def test_shipped_agents_reference_skills_by_name_and_every_name_exists():
    catalog = {p.parent.name for p in SKILLS.rglob("SKILL.md")}
    names = set()
    for agent in AGENTS.glob("*.md"):
        text = agent.read_text()
        assert not PATH_REF_RE.search(text), (
            f"{agent.name} uses a repo-relative skill path; consumer projects never "
            "receive .claude/skills -- use `cc skill get <name>`"
        )
        names |= set(GET_RE.findall(text))
    assert {"stride-dread", "voice-tone", "design-heuristics", "ux-patterns"} <= names
    assert names <= catalog, f"agents name skills the framework lacks: {names - catalog}"


# ---- FF11 ------------------------------------------------------------------


def test_ff11_fails_repo_relative_skill_paths_even_in_framework_mode(tmp_path):
    fw = _framework(tmp_path)
    project = _consumer(tmp_path, fw)
    (project / ".claude/agents/sec.md").write_text(
        "# sec\n`@include .claude/skills/security/stride-dread/SKILL.md`\n"
    )
    out = _section(_run(project, fw, tmp_path, mode="framework"), "FF11")
    assert any("sec.md: repo-relative skill path" in f and "cc skill get stride-dread" in f
               for f in _fails(out)), out


def test_ff11_resolves_names_through_cc_skill_list(tmp_path):
    fw = _framework(tmp_path)
    project = _consumer(tmp_path, fw)
    for agent in project.glob(".claude/agents/*.md"):
        agent.unlink()  # FF11 only: one agent, so the references are exactly these
    (project / ".claude/agents/sec.md").write_text(
        "`cc skill get stride-dread`\n`cc skill get no-such-skill`\n"
    )
    out = _section(_run(project, fw, tmp_path, cc_names=["stride-dread"]), "FF11")
    assert "sec.md: skill `stride-dread` (cc skill get) resolves via `cc skill list`" in out
    assert _fails(out) == [
        "sec.md: skill `no-such-skill` (cc skill get) not found by `cc skill list` "
        "(project, machine, knowledge)"
    ], out


def test_ff11_falls_back_to_disk_scopes_without_copilot_cc(tmp_path):
    fw = _framework(tmp_path)
    project = _consumer(tmp_path, fw)
    for agent in project.glob(".claude/agents/*.md"):
        agent.unlink()  # FF11 only: one agent, so the references are exactly these
    (project / ".claude/agents/sec.md").write_text("`cc skill get stride-dread`\n")
    out = _section(_run(project, fw, tmp_path), "FF11")
    assert "resolves via on-disk skill scopes" in out
    assert _fails(out) == [], out


# ---- FF9 -------------------------------------------------------------------


def test_ff9_skips_in_consumer_and_still_requires_baseline_in_framework(tmp_path):
    fw = _framework(tmp_path)
    project = _consumer(tmp_path, fw)
    consumer = _section(_run(project, fw, tmp_path), "FF9")
    assert "[SKIP] consumer project" in consumer and _fails(consumer) == []
    framework = _section(_run(project, fw, tmp_path, mode="framework"), "FF9")
    assert any("no context-budget baseline" in f for f in _fails(framework)), framework


def test_mode_is_detected_not_assumed(tmp_path):
    fw = _framework(tmp_path)
    project = _consumer(tmp_path, fw)
    assert "Fitness mode: consumer" in _run(project, fw, tmp_path)
    (project / "tools/cc").mkdir(parents=True)
    (project / "tools/cc/pyproject.toml").write_text("")
    shutil.copy2(REPO_ROOT / "VERSION.json", project / "VERSION.json")
    assert "Fitness mode: framework" in _run(project, fw, tmp_path)


# ---- FF12 ------------------------------------------------------------------


def test_ff12_consumer_compares_project_agents_to_framework_history(tmp_path):
    fw = _framework(tmp_path)
    project = _consumer(tmp_path, fw)
    # A stale machine corpus must not matter: project agents shadow it.
    stale = tmp_path / "home" / ".claude" / "agents"
    stale.mkdir(parents=True)
    (stale / "me.md").write_text("stale machine copy\n")
    # A project's own agent is reported, not failed.
    (project / ".claude/agents/custom.md").write_text("# project agent\n")
    out = _section(_run(project, fw, tmp_path), "FF12")
    assert _fails(out) == [], out
    assert "release_tag v1.0.0 is a tag in the framework repo" in out
    assert "custom.md is a project-defined agent" in out


def test_ff12_consumer_fails_agent_content_of_unknown_origin(tmp_path):
    fw = _framework(tmp_path)
    project = _consumer(tmp_path, fw)
    me = project / ".claude/agents/me.md"
    me.write_text(me.read_text() + "\nhand edit\n")
    fails = _fails(_section(_run(project, fw, tmp_path), "FF12"))
    assert len(fails) == 1 and fails[0].startswith(
        "me.md: the deployed base matches no version this repo has committed"
    ), fails


def test_ff12_consumer_fails_lock_naming_an_untagged_release(tmp_path):
    fw = _framework(tmp_path)
    project = _consumer(tmp_path, fw, release_tag="v1.0.1")
    fails = _fails(_section(_run(project, fw, tmp_path), "FF12"))
    assert fails == [
        f"copilot.lock.json is locked to v1.0.1, which the framework repo at {fw} "
        "has not tagged (fetch tags, or the release was never tagged)"
    ], fails
