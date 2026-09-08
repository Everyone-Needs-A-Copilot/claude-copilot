"""The shipped lane policy is exercised through the actual cc CLI.

These checks select commands; they deliberately do not launch nested full suites.
Execution/process behavior belongs to tools/cc/tests/test_verify.py.
"""

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc.main import app


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "verification.json"
INITIATIVE = ROOT / "docs/40-initiatives/01-risk-based-verification"
BROAD_PYTEST = {"cc-portable", "tc-portable", "root-portable"}
BROAD = BROAD_PYTEST | {"qa-gate", "subagent-stop"}


def plan(*arguments):
    result = CliRunner().invoke(
        app, ["verify", "plan", "--root", str(ROOT), *arguments, "--json"]
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    ("changed", "expected"),
    [
        ([".claude/agents/qa.md"], {"instruction-policy", "instruction-context"}),
        (["tools/cc/src/cc/core/verification/__init__.py"], {"verification-runner"}),
        (["tools/cc/src/cc/main.py"], BROAD),
        (["tools/cc/src/cc/core/verification/__init__.py", "unmapped/new-module.py"], BROAD | {"verification-runner"}),
        (["docs/40-initiatives/01-risk-based-verification/README.md"], {"verification-contract"}),
        (["tests/test_prd7_ws1.py"], {"root-contracts"}),
    ],
)
def test_real_manifest_selects_affected_checks_and_broadens_unknowns(changed, expected):
    arguments = [item for path in changed for item in ("--changed", path)]
    result = plan(*arguments)
    assert {lane["id"] for lane in result["lanes"]} == expected
    assert all(lane["reasons"] for lane in result["lanes"])
    assert result["kind"] == "verification-plan"
    assert result["schemaVersion"] == 1


def test_no_impact_information_selects_broad_checks():
    assert {lane["id"] for lane in plan()["lanes"]} == BROAD


def test_explicit_lane_is_a_recorded_scope_decision():
    result = plan("--lane", "instruction-context", "--task", "63")
    assert [lane["id"] for lane in result["lanes"]] == ["instruction-context"]
    assert result["selection"]["lanes"] == ["instruction-context"]
    assert str(result["task"]) == "63"
    assert "approved" not in result


def test_unknown_explicit_lane_is_not_an_empty_green_plan():
    result = CliRunner().invoke(
        app, ["verify", "plan", "--root", str(ROOT), "--lane", "not-a-lane", "--json"]
    )
    assert result.exit_code != 0


def test_broad_inventory_uses_directory_discovery_and_no_default_reuse():
    manifest = json.loads(MANIFEST.read_text())
    lanes = {lane["id"]: lane for lane in manifest["lanes"]}
    assert set(manifest["fallbackLanes"]) == BROAD
    assert lanes["cc-portable"]["cwd"] == "tools/cc"
    assert lanes["tc-portable"]["cwd"] == "tools/tc"
    assert lanes["root-portable"]["cwd"] == "."
    for lane_id in BROAD_PYTEST:
        assert "tests/" in lanes[lane_id]["argv"]
        assert lanes[lane_id]["paths"] == []
    assert lanes["qa-gate"]["argv"] == ["bash", "tests/hooks/test-qa-gate-integration.sh"]
    assert lanes["subagent-stop"]["argv"] == ["bash", "tests/hooks/test-subagent-stop.sh"]
    cc_argv = lanes["cc-portable"]["argv"]
    assert cc_argv[cc_argv.index("-m", 2) + 1] == "not machine"
    assert "--ignore=tests/tui" in lanes["root-portable"]["argv"]
    assert sum(lanes[lane]["timeoutSeconds"] for lane in BROAD) == 900
    assert all(lane["hermetic"] is False for lane in lanes.values())
    assert all(lane["timeoutSeconds"] > 0 for lane in lanes.values())
    for lane_id in ("root-contracts", "root-portable"):
        # These are read by the real routing-negative test, not copied constants.
        assert {".claude/fitness-check.sh", "CLAUDE.md", "CHANGELOG.md"}.issubset(lanes[lane_id]["inputs"])
    assert {".github/workflows", "docs/40-initiatives/01-risk-based-verification",
            ".claude/force-delegate-budget-baseline-v1.0.0.json"}.issubset(lanes["root-portable"]["inputs"])


def test_declared_local_inputs_and_working_directories_exist():
    manifest = json.loads(MANIFEST.read_text())
    paths = list(manifest["inputs"])
    for lane in manifest["lanes"]:
        paths.extend(lane.get("inputs", []))
        assert (ROOT / lane["cwd"]).is_dir()
    for relative in paths:
        path = ROOT / relative
        assert path.exists(), relative
        assert path.resolve().is_relative_to(ROOT)


def test_initiative_local_markdown_links_resolve():
    checked = 0
    for document in INITIATIVE.rglob("*.md"):
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document.read_text()):
            if "://" in target or target.startswith("#"):
                continue
            target = target.split("#", 1)[0].strip("<>")
            assert (document.parent / target).exists(), (document, target)
            checked += 1
    assert checked > 0
