"""Structural coverage/required-status checks, not a hosted CI execution claim.

No test inventory allowlist: owners collect directories and future test files
inherit coverage. Explicit pre-existing root exclusions remain visible. Remote
branch rules referencing workflow identity still require a separate policy audit.
"""

import os
from pathlib import Path
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
CHECK_NAME = "Conformance harness (World-A fixtures + committed baseline)"
ROOT_EXCLUSIONS = ("tests/tui/", "tests/unit/", "tests/integration/")


def workflow(name):
    # BaseLoader preserves GitHub's `on` key (rather than YAML 1.1 boolean True).
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


def commands(job):
    return [line.strip() for step in job.get("steps", [])
            for line in step.get("run", "").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def assert_ci_ownership(suites, manual):
    for event in ("push", "pull_request"):
        assert suites["on"][event] == {"branches": ["main"]}
    jobs = suites["jobs"]
    owner = jobs["cc-tests"]
    assert owner["runs-on"] == "ubuntu-latest"
    assert "if" not in owner and "continue-on-error" not in owner
    test_steps = [step for step in owner["steps"] if "python -m pytest" in step.get("run", "")]
    assert len(test_steps) == 1
    step = test_steps[0]
    assert step.get("working-directory") == "tools/cc"
    assert "if" not in step and "continue-on-error" not in step
    assert commands({"steps": [step]}) == ['python -m pytest tests/ -m "not machine"']
    portable_runs = [candidate for job in jobs.values() for candidate in job.get("steps", [])
                     if candidate.get("working-directory") == "tools/cc"
                     and "python -m pytest" in candidate.get("run", "")]
    assert portable_runs == test_steps, "The cc portable inventory has duplicate owners"

    gate = jobs["conformance-suite"]
    assert gate["name"] == CHECK_NAME
    assert gate["needs"] == "cc-tests"
    assert gate["if"] == "${{ always() }}"
    assert "continue-on-error" not in gate
    assert len(gate["steps"]) == 1
    guard = gate["steps"][0]
    assert "if" not in guard and "continue-on-error" not in guard
    assert guard["env"]["CC_TEST_RESULT"] == "${{ needs.cc-tests.result }}"
    assert guard["run"] == 'test "$CC_TEST_RESULT" = success'

    assert set(manual["on"]) == {"workflow_dispatch"}
    assert all(job.get("name") != CHECK_NAME for job in manual["jobs"].values())
    assert not any("pytest tests/conformance" in line
                   for document in (suites, manual)
                   for job in document["jobs"].values() for line in commands(job))


def test_portable_conformance_has_one_owner_and_preserved_required_check():
    assert_ci_ownership(workflow("pytest-suites.yml"), workflow("conformance.yml"))


@pytest.mark.parametrize("defect", ["deleted-discovery", "narrowed-discovery", "skip-owner",
                                       "skip-gate", "forgive-failure", "wrong-dependency",
                                       "duplicate-automatic-trigger", "duplicate-owner"])
def test_ownership_audit_rejects_missing_coverage_or_false_green(defect):
    suites, manual = workflow("pytest-suites.yml"), workflow("conformance.yml")
    owner = suites["jobs"]["cc-tests"]
    gate = suites["jobs"]["conformance-suite"]
    if defect == "deleted-discovery":
        owner["steps"] = [s for s in owner["steps"] if "pytest" not in s.get("run", "")]
    elif defect == "narrowed-discovery":
        owner["steps"][-1]["run"] = 'python -m pytest tests/conformance/ -m "not machine"'
    elif defect == "skip-owner":
        owner["if"] = "false"
    elif defect == "skip-gate":
        gate["if"] = "${{ success() }}"
    elif defect == "forgive-failure":
        gate["steps"][0]["run"] += " || true"
    elif defect == "wrong-dependency":
        gate["needs"] = "root-tests"
    elif defect == "duplicate-owner":
        suites["jobs"]["another-cc-run"] = owner
    else:
        manual["on"]["pull_request"] = {"branches": ["main"]}
    with pytest.raises(AssertionError):
        assert_ci_ownership(suites, manual)


@pytest.mark.parametrize("result", ["success", "failure", "cancelled", "skipped", ""])
def test_required_check_executes_the_real_guard_for_every_dependency_result(result):
    guard = workflow("pytest-suites.yml")["jobs"]["conformance-suite"]["steps"][0]["run"]
    process = subprocess.run(["bash", "-c", guard], env={**os.environ, "CC_TEST_RESULT": result},
                             capture_output=True, text=True, timeout=5)
    assert (process.returncode == 0) is (result == "success")


def owned_inventory(root):
    """Directory discovery matching the existing pytest ownership boundaries."""
    found = set()
    for relative in ("tests", "tools/cc/tests", "tools/tc/tests", ".claude/skills"):
        for path in (root / relative).rglob("test_*.py"):
            name = path.relative_to(root).as_posix()
            if not name.startswith(ROOT_EXCLUSIONS):
                found.add(name)
    # Vendored suite is explicitly discovered because root conftest ignores it.
    found.update(p.relative_to(root).as_posix() for p in (root / "tests/tui").glob("test_*.py"))
    return found


def test_discovery_union_preserves_existing_roots_and_mac_os_contract():
    jobs = workflow("pytest-suites.yml")["jobs"]
    assert 'python -m pytest tests/ --ignore=tests/tui -p no:cov' in commands(jobs["root-tests"])
    assert 'python -m pytest tests/' in commands(jobs["tc-tests"])
    assert 'python -m pytest .claude/skills -q' in commands(jobs["skill-test-scripts"])
    assert any("find tests/tui -maxdepth 1 -type f -name 'test_*.py'" in line
               for line in commands(jobs["vendored-monitor-tests"]))
    assert 'python -m pytest $files' in commands(jobs["vendored-monitor-tests"])
    for owner in ("root-tests", "tc-tests", "skill-test-scripts", "vendored-monitor-tests"):
        assert "if" not in jobs[owner] and "continue-on-error" not in jobs[owner]
    mac = workflow("cc-onboard-contract.yml")["jobs"]["onboard-contract"]
    assert mac["runs-on"] == "macos-latest"
    assert "python -m pytest" in "\n".join(commands(mac))
    # Passing selected FF1–6 tests never certifies the separate full fitness gate.
    smoke = workflow("smoke-tests.yml")
    assert any("./.claude/fitness-check.sh" == line
               for job in smoke["jobs"].values() for line in commands(job))

    intended = {p.relative_to(ROOT).as_posix()
                for directory in ("tests", "tools/cc/tests", "tools/tc/tests", ".claude/skills")
                for p in (ROOT / directory).rglob("test_*.py")
                if not p.relative_to(ROOT).as_posix().startswith(("tests/unit/", "tests/integration/"))}
    assert owned_inventory(ROOT) == intended
    assert any(name.startswith("tools/cc/tests/conformance/") for name in intended)


def test_new_tests_join_discovered_inventory_without_a_workflow_edit(tmp_path):
    before = owned_inventory(tmp_path)
    additions = {"tests/test_new_behavior.py", "tools/cc/tests/conformance/test_new_case.py",
                 "tools/tc/tests/test_new_case.py", ".claude/skills/example/scripts/test_new_case.py",
                 "tests/tui/test_new_case.py"}
    for name in additions:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_discovered():\n    assert True\n")
    assert owned_inventory(tmp_path) - before == additions
