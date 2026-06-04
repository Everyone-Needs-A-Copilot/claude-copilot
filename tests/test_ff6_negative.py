"""
Negative tests for FF6 (stale design agent refs) and FF1 (orphan routes).
These tests:
1. Verify FF6 pattern detection works on CLAUDE.md
2. Inject bad content, check detection fires, restore, check clean
"""

import subprocess
import re
import tempfile
import shutil
import os
import sys

# Paths relative to repo root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLAUDE_MD = os.path.join(REPO_ROOT, "CLAUDE.md")
FITNESS_SCRIPT = os.path.join(REPO_ROOT, ".claude", "fitness-check.sh")
PROTOCOL_MD = os.path.join(REPO_ROOT, ".claude", "commands", "protocol.md")
AGENTS_DIR = os.path.join(REPO_ROOT, ".claude", "agents")


def run_fitness_check():
    """Run the fitness check and return (returncode, stdout)."""
    result = subprocess.run(
        [
            "bash",
            FITNESS_SCRIPT,
            "--agents-dir",
            AGENTS_DIR,
            "--commands-dir",
            os.path.join(REPO_ROOT, ".claude", "commands"),
            "--copilot-path",
            os.path.expanduser("~/.claude/copilot"),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    return result.returncode, result.stdout + result.stderr


def read_file(path):
    with open(path, "r") as f:
        return f.read()


def write_file(path, content):
    with open(path, "w") as f:
        f.write(content)


# ---- POSITIVE TEST: baseline ----


def test_positive_baseline_fitness_check_passes():
    """FF positive: clean repo fitness check should pass."""
    rc, output = run_fitness_check()
    assert (
        rc == 0
    ), f"Expected fitness check to PASS on clean repo but got rc={rc}:\n{output}"
    assert "FITNESS CHECK PASSED" in output, f"Expected PASS in output:\n{output}"
    assert (
        "FF6" in output or "Stale Design" in output
    ), f"FF6 section not found in output:\n{output}"


# ---- NEGATIVE TEST A: inject "sd → design → ta" ----


def test_negative_a_ff6_routing_stage_design_fails():
    """FF6 negative A: injecting 'sd → design → ta' into CLAUDE.md must cause FF6 to FAIL."""
    original = read_file(CLAUDE_MD)
    bad_content = (
        original
        + "\n\n<!-- QA TEST INJECTION -->\nBuild a feature: sd → design → ta → me → qa\n"
    )
    write_file(CLAUDE_MD, bad_content)
    try:
        rc, output = run_fitness_check()
        assert (
            rc != 0
        ), f"Expected fitness check to FAIL with routing-stage 'design' but got rc=0:\n{output}"
        assert (
            "[FAIL]" in output and "design" in output.lower()
        ), f"Expected FF6 FAIL about 'design' routing stage:\n{output}"
    finally:
        write_file(CLAUDE_MD, original)

    # Verify restore: re-run and confirm clean
    rc2, output2 = run_fitness_check()
    assert rc2 == 0, f"After restore, expected PASS but got rc={rc2}:\n{output2}"


# ---- NEGATIVE TEST B: inject "@agent-design" into protocol.md ----


def test_negative_b_ff1_agent_design_in_protocol_fails():
    """FF1 negative B: injecting '@agent-design' into protocol.md must cause FF1 to FAIL."""
    original = read_file(PROTOCOL_MD)
    bad_content = (
        original
        + "\n\n<!-- QA TEST INJECTION -->\nRoute to @agent-design for visual design.\n"
    )
    write_file(PROTOCOL_MD, bad_content)
    try:
        rc, output = run_fitness_check()
        assert (
            rc != 0
        ), f"Expected fitness check to FAIL with @agent-design ref but got rc=0:\n{output}"
        # FF1 checks orphan routes: @agent-design referenced but design.md doesn't exist
        # FF6 also checks for @agent-design in CLAUDE.md — but this injection is in protocol.md
        # FF1 should catch the orphan @agent-design reference
        assert "[FAIL]" in output, f"Expected FAIL in output:\n{output}"
    finally:
        write_file(PROTOCOL_MD, original)

    # Verify restore
    rc2, output2 = run_fitness_check()
    assert rc2 == 0, f"After restore, expected PASS but got rc={rc2}:\n{output2}"


# ---- NEGATIVE TEST C: inject "@agent-bogus" route into an agent file ----


def test_negative_c_orphan_route_in_agent_fails():
    """Orphan route negative C: injecting '@agent-bogus' into uxd.md must cause orphan-route FF to FAIL."""
    target_agent = os.path.join(AGENTS_DIR, "uxd.md")
    original = read_file(target_agent)
    bad_content = (
        original
        + "\n\n<!-- QA TEST INJECTION -->\n| @agent-bogus | Use when bogus is needed |\n"
    )
    write_file(target_agent, bad_content)
    try:
        rc, output = run_fitness_check()
        assert (
            rc != 0
        ), f"Expected fitness check to FAIL with @agent-bogus but got rc=0:\n{output}"
        assert (
            "bogus" in output.lower()
        ), f"Expected 'bogus' to appear in FAIL output:\n{output}"
    finally:
        write_file(target_agent, original)

    # Verify restore
    rc2, output2 = run_fitness_check()
    assert rc2 == 0, f"After restore, expected PASS but got rc={rc2}:\n{output2}"


# ---- VERIFICATION: git status clean ----


def test_git_status_clean_after_restores():
    """Verify all restores left tracked files unmodified (no M or D entries)."""
    result = subprocess.run(
        ["git", "status", "--short"], capture_output=True, text=True, cwd=REPO_ROOT
    )
    # Only fail if there are MODIFIED or DELETED tracked files (M/D), not untracked (??)
    modified_lines = [
        line
        for line in result.stdout.strip().splitlines()
        if line and not line.startswith("??") and not line.startswith("!!")
    ]
    assert (
        not modified_lines
    ), f"Expected no modified tracked files after restores but got:\n" + "\n".join(
        modified_lines
    )


# ---- VERIFICATION: commit structure ----


def test_commit_7f6f081_exists_and_scope():
    """Verify commit 7f6f081 touches only CLAUDE.md, fitness-check.sh, CHANGELOG.md."""
    result = subprocess.run(
        ["git", "show", "--stat", "--format=", "7f6f081"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"git show failed: {result.stderr}"
    files_changed = [
        line.strip().split()[0]
        for line in result.stdout.strip().splitlines()
        if "|" in line
    ]
    expected_files = {"CLAUDE.md", "CHANGELOG.md", ".claude/fitness-check.sh"}
    actual_files = set(files_changed)
    unexpected = actual_files - expected_files
    assert (
        not unexpected
    ), f"Unexpected files in commit 7f6f081: {unexpected}\nAll changed: {actual_files}"
    for expected in expected_files:
        assert (
            expected in actual_files
        ), f"Expected {expected} in commit 7f6f081 but not found. Got: {actual_files}"


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
