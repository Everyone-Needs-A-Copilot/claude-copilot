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
    env = {
        k: v for k, v in os.environ.items()
        if not k.startswith("CC_") and k != "CLAUDE_CONFIG_DIR"
    }
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


# ---- customized-preserve installs -------------------------------------------
# A project that keeps its own agent tree carries no framework agents; they are
# deployed once at user level (~/.claude/agents). Contract: the roster resolves
# project-first then user-level, project-owned agents are not held to the
# framework agent contract, and nothing else is relaxed.


def _preserve_consumer(tmp_path: Path, fw: Path) -> Path:
    project = tmp_path / "preserve"
    (project / ".claude/agents").mkdir(parents=True)
    shutil.copytree(REPO_ROOT / ".claude" / "commands", project / ".claude" / "commands")
    shutil.copy2(FITNESS, project / ".claude" / "fitness-check.sh")
    shutil.copy2(REPO_ROOT / "CLAUDE.md", project / "CLAUDE.md")
    # A project-owned agent: no `model`, no framework blocks, routes to a roster agent.
    (project / ".claude/agents/studio-own.md").write_text(
        "---\nname: studio-own\ndescription: project agent\ntools: Read\n---\n"
        "# studio-own\nRoutes to @agent-me.\n"
    )
    (project / "copilot.lock.json").write_text(json.dumps({"components": [
        {"component": "claude", "release_tag": "v1.0.0", "files": [],
         "ownership_mode": "customized-preserve"}
    ]}))
    user_agents = tmp_path / "home" / ".claude" / "agents"
    shutil.copytree(fw / ".claude" / "agents", user_agents)
    return project


def test_preserve_install_accepts_user_level_framework_agents(tmp_path):
    fw = _framework(tmp_path)
    project = _preserve_consumer(tmp_path, fw)
    out = _run(project, fw, tmp_path)
    assert "Install ownership: customized-preserve" in out
    assert re.search(r"FITNESS CHECK PASSED", out), "\n".join(_fails(out))
    assert "studio-own.md is a project-defined agent" in out


def test_preserve_install_still_fails_a_roster_agent_missing_everywhere(tmp_path):
    fw = _framework(tmp_path)
    project = _preserve_consumer(tmp_path, fw)
    (tmp_path / "home/.claude/agents/me.md").unlink()
    fails = _fails(_run(project, fw, tmp_path))
    assert any(f.startswith("me.md MISSING") for f in fails), fails
    assert any("@agent-me referenced but" in f for f in fails), fails


def test_standard_install_does_not_accept_user_level_framework_agents(tmp_path):
    fw = _framework(tmp_path)
    project = _preserve_consumer(tmp_path, fw)
    lock = json.loads((project / "copilot.lock.json").read_text())
    lock["components"][0]["ownership_mode"] = "full"
    (project / "copilot.lock.json").write_text(json.dumps(lock))
    fails = _fails(_run(project, fw, tmp_path))
    assert any(f.startswith("me.md MISSING") for f in fails), fails


def test_preserve_install_holds_a_framework_agent_it_carries_to_the_blocks(tmp_path):
    fw = _framework(tmp_path)
    project = _preserve_consumer(tmp_path, fw)
    shutil.copy2(fw / ".claude/agents/me.md", project / ".claude/agents/me.md")
    shutil.copytree(fw / ".claude/agents/_shared", project / ".claude/agents/_shared")
    me = project / ".claude/agents/me.md"
    me.write_text(me.read_text().replace("## Runtime Precedence", "## Runtime Precedence\nedited", 1))
    fails = _fails(_run(project, fw, tmp_path))
    assert any("me.md: Runtime Precedence block differs from canonical" in f for f in fails), fails


def test_preserve_install_still_validates_a_project_agent_model_when_declared(tmp_path):
    fw = _framework(tmp_path)
    project = _preserve_consumer(tmp_path, fw)
    own = project / ".claude/agents/studio-own.md"
    own.write_text(own.read_text().replace("tools: Read", "tools: Read\nmodel: gpt"))
    fails = _fails(_section(_run(project, fw, tmp_path), "FF7"))
    assert fails == ["studio-own.md: model 'gpt' not one of sonnet|opus"], fails


def test_consumer_ceiling_excludes_project_defined_agents(tmp_path):
    fw = _framework(tmp_path)
    corpus = sum(p.stat().st_size for p in (fw / ".claude/agents").glob("*.md"))
    baseline = {"thresholds": {"agent_corpus_ceiling_bytes": corpus + 1000}}
    (fw / ".claude/context-budget-baseline-test.json").write_text(json.dumps(baseline))
    _git(fw, "add", "-A")
    _git(fw, "commit", "-qm", "baseline")
    project = _preserve_consumer(tmp_path, fw)
    (project / ".claude/agents/studio-big.md").write_text("x" * 50_000)
    out = _section(_run(project, fw, tmp_path), "FF12")
    assert _fails(out) == [], out
    assert "within the absolute ceiling" in out


# ---- project-owned agents in a standard install ----------------------------


def test_standard_install_does_not_hold_project_agents_to_the_framework_contract(tmp_path):
    """spanish-copilot / small-business-copilot / voice-copilot, 2026-10-06: the
    projects' own agents (and an `owner: project` override of a roster name)
    failed FF4/FF7/FF8/FF10/FF12 for lacking framework-only blocks and keys."""
    fw = _framework(tmp_path)
    project = _consumer(tmp_path, fw)
    (project / ".claude/agents/tutor.md").write_text(
        "---\nname: tutor\nowner: project\ndescription: project tutor\ntools: Read\n---\n# tutor\n"
    )
    (project / ".claude/agents/aqa.md").write_text(
        "---\nname: aqa\ndescription: no owner key, not in the roster\ntools: Read\n"
        "validationRules: [x]\n---\n# aqa\n"
    )
    (project / ".claude/agents/cco.md").write_text(
        "---\nname: cco\nowner: project\ndescription: our own creative lens\ntools: Read\n---\n# cco\n"
    )
    out = _run(project, fw, tmp_path)
    for ff in ("FF4", "FF7", "FF8", "FF10", "FF12"):
        fails = _fails(_section(out, ff))
        assert fails == [], (ff, fails)
    assert "tutor.md: project-owned agent -- framework frontmatter contract not applied" in out
    assert "cco.md is project-owned (owner: project); the framework's cco.md is not deployed here by design" in out


def test_standard_install_still_holds_unmarked_framework_agents_to_the_blocks(tmp_path):
    fw = _framework(tmp_path)
    project = _consumer(tmp_path, fw)
    me = project / ".claude/agents/me.md"
    me.write_text(me.read_text().replace("## Runtime Precedence", "## Runtime Precedence\nedited", 1))
    fails = _fails(_section(_run(project, fw, tmp_path), "FF8"))
    assert any("me.md: Runtime Precedence block differs from canonical" in f for f in fails), fails
