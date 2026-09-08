"""
Negative tests for FF6 (stale design agent refs) and FF1 (orphan routes).
Run the actual FF1–FF6 shell boundary against disposable source copies.
The full fitness gate (including genuine context-budget failures) remains owned
by smoke-tests.yml; these routing regressions do not certify unrelated checks.
"""

import os
import re
import subprocess
import shutil
from pathlib import Path

import pytest

# Paths relative to repo root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLAUDE_MD = os.path.join(REPO_ROOT, "CLAUDE.md")
FITNESS_SCRIPT = os.path.join(REPO_ROOT, ".claude", "fitness-check.sh")
PROTOCOL_MD = os.path.join(REPO_ROOT, ".claude", "commands", "protocol.md")
AGENTS_DIR = os.path.join(REPO_ROOT, ".claude", "agents")


@pytest.fixture
def routing_copy(tmp_path):
    """Copy only this boundary's inputs, never write to the author's checkout."""
    fixture = tmp_path / "routing"
    (fixture / ".claude").mkdir(parents=True)
    for name in ("agents", "commands"):
        shutil.copytree(Path(REPO_ROOT) / ".claude" / name, fixture / ".claude" / name)
    for name in ("CLAUDE.md", "VERSION.json"):
        shutil.copy2(Path(REPO_ROOT) / name, fixture / name)

    # Execute source, not a Python reimplementation of the detector. Fail closed
    # if the production section boundary moves. No production gate is narrowed.
    source = Path(FITNESS_SCRIPT).read_text()
    boundary = 'section "FF7: Agent Frontmatter Conformance (iteration contract)"'
    assert source.count(boundary) == 1, "Fitness boundary changed; review selection"
    selected = source.split(boundary)[0]
    assert 'section "FF6:' in selected and 'section "FF9:' not in selected
    (fixture / ".claude" / "routing-check.sh").write_text(
        selected + '\n[ "$FAIL_COUNT" -eq 0 ]\n'
    )
    return fixture


def run_fitness_check(fixture):
    """Run the selected production routing boundary, with an explicit cap."""
    result = subprocess.run(
        [
            "bash",
            str(fixture / ".claude" / "routing-check.sh"),
            "--agents-dir",
            str(fixture / ".claude" / "agents"),
            "--commands-dir",
            str(fixture / ".claude" / "commands"),
            "--copilot-path",
            str(fixture),
        ],
        capture_output=True,
        text=True,
        cwd=fixture,
        timeout=15,
    )
    return result.returncode, result.stdout + result.stderr


def read_file(path):
    with open(path, "r") as f:
        return f.read()


# ---- POSITIVE TEST: baseline ----


def test_positive_baseline_routing_checks_pass(routing_copy):
    """Source routing baseline passes; this is not a full fitness verdict."""
    rc, output = run_fitness_check(routing_copy)
    assert (
        rc == 0
    ), f"Expected fitness check to PASS on clean repo but got rc={rc}:\n{output}"
    assert "[FAIL]" not in output
    assert "FF9:" not in output
    assert (
        "FF6" in output or "Stale Design" in output
    ), f"FF6 section not found in output:\n{output}"


# ---- NEGATIVE TEST A: inject "sd → design → ta" ----


def test_negative_a_ff6_routing_stage_design_fails(routing_copy):
    """FF6 negative A: injecting 'sd → design → ta' into CLAUDE.md must cause FF6 to FAIL."""
    target = routing_copy / "CLAUDE.md"
    original = target.read_text()
    bad_content = (
        original
        + "\n\n<!-- QA TEST INJECTION -->\nBuild a feature: sd → design → ta → me → qa\n"
    )
    target.write_text(bad_content)
    rc, output = run_fitness_check(routing_copy)
    assert rc != 0, output
    assert "[FAIL] CLAUDE.md contains 'design' used as a routing stage" in output


# ---- NEGATIVE TEST B: inject "@agent-design" into protocol.md ----


def test_negative_b_ff1_agent_design_in_protocol_fails(routing_copy):
    """FF1 negative B: injecting '@agent-design' into protocol.md must cause FF1 to FAIL."""
    target = routing_copy / ".claude" / "commands" / "protocol.md"
    original = target.read_text()
    bad_content = (
        original
        + "\n\n<!-- QA TEST INJECTION -->\nRoute to @agent-design for visual design.\n"
    )
    target.write_text(bad_content)
    rc, output = run_fitness_check(routing_copy)
    assert rc != 0, output
    assert "[FAIL] @agent-design referenced but" in output


# ---- NEGATIVE TEST C: inject "@agent-bogus" route into an agent file ----


def test_negative_c_orphan_route_in_agent_fails(routing_copy):
    """Orphan route negative C: injecting '@agent-bogus' into uxd.md must cause orphan-route FF to FAIL."""
    target_agent = routing_copy / ".claude" / "agents" / "uxd.md"
    original = read_file(target_agent)
    bad_content = (
        original
        + "\n\n<!-- QA TEST INJECTION -->\n| @agent-bogus | Use when bogus is needed |\n"
    )
    target_agent.write_text(bad_content)
    rc, output = run_fitness_check(routing_copy)
    assert rc != 0, output
    assert "[FAIL] uxd.md → @agent-bogus (UNKNOWN" in output


# ---- VERIFICATION: mutations are copy-local, regardless of author dirt ----


def test_routing_mutations_do_not_touch_author_sources(routing_copy):
    """A deliberately dirty fixture cannot alias any original mutation target."""
    targets = ("CLAUDE.md", ".claude/commands/protocol.md", ".claude/agents/uxd.md")
    originals = {name: (Path(REPO_ROOT) / name).read_bytes() for name in targets}
    for name in targets:
        source, copied = Path(REPO_ROOT) / name, routing_copy / name
        assert not source.samefile(copied)
        copied.write_text(copied.read_text() + "\nQA copy-only mutation\n")
    assert {name: (Path(REPO_ROOT) / name).read_bytes() for name in targets} == originals


# ---- VERIFICATION: current release contract ----


def test_ff6_release_contract_is_tracked_and_shell_valid():
    """Verify the current FF6 release assets, independent of Git history depth.

    Behavior is exercised by the positive and mutation tests above. This
    companion assertion keeps the release assets tracked and the executable
    fitness gate syntactically valid without depending on an old commit object
    that a normal depth-1 CI checkout intentionally does not contain.
    """
    expected_files = ("CLAUDE.md", "CHANGELOG.md", ".claude/fitness-check.sh")
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", *expected_files],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert tracked.returncode == 0, tracked.stderr

    syntax = subprocess.run(
        ["bash", "-n", FITNESS_SCRIPT],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert syntax.returncode == 0, syntax.stderr


# ---- VERIFICATION: VERSION consistency ----


def test_version_json_matches_package_json():
    """VERSION.json.framework must equal package.json.version (mirror must stay in sync)."""
    import json

    with open(os.path.join(REPO_ROOT, "VERSION.json")) as f:
        vj = json.load(f)
    with open(os.path.join(REPO_ROOT, "package.json")) as f:
        pj = json.load(f)
    assert (
        vj["framework"] == pj["version"]
    ), f"VERSION.json.framework ({vj['framework']}) != package.json.version ({pj['version']})"


# ---- VERIFICATION: CHANGELOG has [5.3.0] section ----


def test_changelog_has_5_3_0_section():
    """CHANGELOG.md must have a [5.3.0] section documenting roster restoration + FF6 + distribution fix."""
    content = read_file(os.path.join(REPO_ROOT, "CHANGELOG.md"))
    assert "## [5.3.0]" in content, "CHANGELOG.md missing [5.3.0] section"
    assert (
        "fitness-check" in content.lower() or "FF6" in content
    ), "CHANGELOG.md [5.3.0] section doesn't mention fitness-check/FF6"
    assert (
        "roster" in content.lower() or "16-agent" in content.lower()
    ), "CHANGELOG.md [5.3.0] section doesn't mention roster restoration"


# ---- VERIFICATION: design.md absent ----


def test_design_agent_absent():
    """design.md must NOT exist in agents directory (it was retired)."""
    design_path = os.path.join(AGENTS_DIR, "design.md")
    assert not os.path.exists(
        design_path
    ), f"design.md still present at {design_path} — must be removed"


# ---- VERIFICATION: CLAUDE.md design refs ----


def test_claude_md_no_stale_design_routing():
    """CLAUDE.md must not contain sd→design routing or @agent-design."""
    content = read_file(CLAUDE_MD)
    assert "@agent-design" not in content, "CLAUDE.md contains @agent-design"

    # Check for routing-stage pattern (same logic as FF6 grep)
    routing_pattern = re.compile(
        r"(→\s*design\s*→|→\s*design\s*$|\bdesign\s*→)", re.MULTILINE
    )
    exempt_patterns = [
        "Design chain",
        "Atomic Design",
        "design tokens",
        "service design",
        "visual design",
        "design chain",
    ]
    lines = content.splitlines()
    for line in lines:
        if routing_pattern.search(line):
            # Check if it's an exempted legitimate prose
            is_exempt = any(ep.lower() in line.lower() for ep in exempt_patterns)
            assert (
                is_exempt
            ), f"CLAUDE.md line contains routing-stage 'design': {line!r}"


def test_claude_md_correct_design_chain():
    """CLAUDE.md Use Case Mapping must show sd → uxd → uids → uid → ta → me → qa experience flow."""
    content = read_file(CLAUDE_MD)
    assert (
        "sd → uxd → uids → uid → ta → me → qa" in content
    ), "CLAUDE.md does not contain correct experience flow: sd → uxd → uids → uid → ta → me → qa"


def test_claude_md_specification_workflow_correct():
    """CLAUDE.md Specification Workflow must list (sd, ind, uxd, uids, cco, cw) not (sd, design)."""
    content = read_file(CLAUDE_MD)
    assert (
        "(sd, design)" not in content
    ), "CLAUDE.md still contains old '(sd, design)' in Specification Workflow"
    assert (
        "(sd, ind, uxd, uids, cco, cw)" in content
    ), "CLAUDE.md Specification Workflow doesn't list full specialist list (sd, ind, uxd, uids, cco, cw)"


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
