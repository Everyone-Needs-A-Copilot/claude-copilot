"""Exercise the real workflow selectors/guards, without running their suites."""

import os
from pathlib import Path
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = [
    (
        "cc-onboard-contract.yml", "onboard-contract", "onboard-contract-gate",
        "cc Onboard Contract gate",
        [".github/workflows/cc-onboard-contract.yml",
         "scripts/package-cc-macos-release.sh", "tools/cc/deep/example.py",
         "tools/tc/example.py"],
    ),
    (
        "time-estimate-check.yml", "check-time-language", "time-language-gate",
        "Time Estimate Language gate",
        [".claude/agents/example.md", ".claude/agents/deep/example.md",
         ".claude/commands/example.md", "templates/example.md",
         "templates/deep/example.md"],
    ),
]


def workflow(filename):
    return yaml.load((ROOT / ".github/workflows" / filename).read_text(),
                     Loader=yaml.BaseLoader)


def git(root, *args):
    result = subprocess.run(
        ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
         "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
        cwd=root, capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def commit_file(root, path, content="fixture\n"):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    git(root, "add", "--", path)
    git(root, "commit", "-qm", "Fixture change")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    base = commit_file(root, "README.md")
    return root, base


def select(document, root, base, head, event="pull_request"):
    step = document["jobs"]["select-paths"]["steps"][-1]
    output = root.parent / "github-output"
    output.unlink(missing_ok=True)
    result = subprocess.run(
        ["bash", "-c", step["run"]], cwd=root,
        env={**os.environ, "CSE_EVENT": event, "CSE_BASE": base, "CSE_HEAD": head,
             "GITHUB_OUTPUT": str(output)},
        capture_output=True, text=True, timeout=5,
    )
    return result, output.read_text() if output.exists() else ""


@pytest.mark.parametrize("filename,suite_id,gate_id,name,paths", WORKFLOWS)
def test_always_started_gate_preserves_branch_scope_and_suite_wiring(
    filename, suite_id, gate_id, name, paths,
):
    document = workflow(filename)
    assert set(document["on"]) == {"pull_request", "push"}
    assert all("paths" not in (trigger or {}) and "paths-ignore" not in (trigger or {})
               for trigger in document["on"].values())
    expected_branches = (["main", "feat/adopt-and-project-setup"]
                         if filename == "cc-onboard-contract.yml" else ["main"])
    assert document["on"]["push"]["branches"] == expected_branches
    if filename == "cc-onboard-contract.yml":
        assert document["on"]["pull_request"]["branches"] == expected_branches
    else:
        assert document["on"]["pull_request"] in ("", None)

    jobs = document["jobs"]
    selector, suite, gate = jobs["select-paths"], jobs[suite_id], jobs[gate_id]
    assert "if" not in selector and "continue-on-error" not in selector
    assert selector["steps"][0]["with"]["fetch-depth"] == "0"
    assert selector["outputs"]["applicable"] == "${{ steps.paths.outputs.applicable }}"
    assert suite["needs"] == "select-paths"
    assert suite["if"] == "needs.select-paths.outputs.applicable == 'true'"
    assert "continue-on-error" not in suite
    assert gate["name"] == name
    assert gate["needs"] == ["select-paths", suite_id]
    assert gate["if"] == "${{ always() }}"
    assert "continue-on-error" not in gate
    assert len(gate["steps"]) == 1
    guard = gate["steps"][0]
    assert "if" not in guard and "continue-on-error" not in guard
    assert guard["env"] == {
        "SELECTOR_RESULT": "${{ needs.select-paths.result }}",
        "APPLICABLE": "${{ needs.select-paths.outputs.applicable }}",
        "SUITE_RESULT": "${{ needs." + suite_id + ".result }}",
    }


@pytest.mark.parametrize("filename,suite_id,gate_id,name,paths", WORKFLOWS)
def test_real_gate_rejects_selector_failure_unknown_or_incomplete_relevant_suite(
    filename, suite_id, gate_id, name, paths,
):
    guard = workflow(filename)["jobs"][gate_id]["steps"][0]["run"]
    cases = [
        ("success", "true", "success", True),
        ("success", "false", "skipped", True),
        ("failure", "false", "skipped", False),
        ("cancelled", "false", "skipped", False),
        ("skipped", "false", "skipped", False),
        ("", "false", "skipped", False),
        ("failure", "true", "success", False),
        ("success", "", "skipped", False),
        ("success", "unknown", "success", False),
        ("success", "true", "skipped", False),
        ("success", "true", "failure", False),
        ("success", "true", "cancelled", False),
        ("success", "true", "", False),
        ("success", "false", "failure", False),
    ]
    for selector, applicable, suite, expected in cases:
        result = subprocess.run(
            ["bash", "-c", guard],
            env={**os.environ, "SELECTOR_RESULT": selector, "APPLICABLE": applicable,
                 "SUITE_RESULT": suite}, capture_output=True, text=True, timeout=5,
        )
        assert (result.returncode == 0) is expected, (selector, applicable, suite)


@pytest.mark.parametrize("filename,suite_id,gate_id,name,paths", WORKFLOWS)
def test_git_selector_covers_original_patterns_and_explicit_irrelevance(
    filename, suite_id, gate_id, name, paths, repository,
):
    root, base = repository
    document = workflow(filename)
    head = commit_file(root, "docs/unrelated.md")
    for event in ("pull_request", "push"):
        result, output = select(document, root, base, head, event)
        assert result.returncode == 0, result.stderr
        assert output == "applicable=false\n"
    for path in paths:
        previous = git(root, "rev-parse", "HEAD")
        head = commit_file(root, path)
        for event in ("pull_request", "push"):
            result, output = select(document, root, previous, head, event)
            assert result.returncode == 0, result.stderr
            assert output == "applicable=true\n", path

    # Removed/renamed relevant files still make their suite applicable.
    previous = head
    git(root, "mv", paths[-1], "moved-unrelated.txt")
    git(root, "commit", "-qm", "Fixture rename")
    result, output = select(document, root, previous, git(root, "rev-parse", "HEAD"))
    assert result.returncode == 0, result.stderr
    assert output == "applicable=true\n"


@pytest.mark.parametrize("filename,suite_id,gate_id,name,paths", WORKFLOWS)
def test_pr_uses_merge_base_and_invalid_selection_never_claims_irrelevance(
    filename, suite_id, gate_id, name, paths, repository,
):
    root, base = repository
    document = workflow(filename)
    head = commit_file(root, "docs/pr-only.md")
    git(root, "checkout", "-q", "--detach", base)
    moved_base = commit_file(root, paths[0])
    result, output = select(document, root, moved_base, head)
    assert result.returncode == 0, result.stderr
    assert output == "applicable=false\n", "Base-only changes are not PR changes"
    for event, bad_base, bad_head in [
        ("pull_request", "", head),
        ("pull_request", "f" * 40, head),
        ("pull_request", base, ""),
        ("pull_request", base, "f" * 40),
        ("workflow_dispatch", base, head),
    ]:
        result, output = select(document, root, bad_base, bad_head, event)
        assert result.returncode != 0
        assert output == ""
    result, output = select(document, root, "0" * 40, head, "push")
    assert result.returncode == 0
    assert output == "applicable=true\n", "New branch must conservatively run the suite"
