"""Commands that copied framework files or locks into projects now refuse.

Old expectation (retired): `cc reconcile *`, `cc conformance *`, `cc update --project|--fanout` and
`cc freshness --all-projects` assessed, planned, applied, verified or reported on per-project framework
copies and `copilot.lock.json`. New expectation: each exits 2 with a stable `retired` error naming
`cc project init` / `cc release`, writes nothing and does not touch the project.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from cc.commands.reconcile import RETIRED_SUBCOMMANDS
from cc.main import app

runner = CliRunner()


def _assert_retired(result, tmp_path):
    assert result.exit_code == 2, result.output
    error = json.loads(result.output)["error"]
    assert error["code"] == "retired"
    assert "cc project init" in error["message"] and "cc release" in error["message"]
    assert not any(tmp_path.iterdir())


@pytest.mark.parametrize("sub", RETIRED_SUBCOMMANDS)
def test_every_reconcile_subcommand_refuses(sub, tmp_path):
    result = runner.invoke(app, ["reconcile", sub, "--project", str(tmp_path), "--json"])
    _assert_retired(result, tmp_path)
    assert f"cc reconcile {sub}" in json.loads(result.output)["error"]["message"]


def test_reconcile_roster_is_the_full_former_surface():
    assert len(RETIRED_SUBCOMMANDS) == 16 and {"apply", "verify", "recover", "plan", "assess"} <= set(RETIRED_SUBCOMMANDS)


@pytest.mark.parametrize("sub", ["check", "report", "baseline", "explain", "list"])
def test_conformance_refuses(sub, tmp_path):
    _assert_retired(runner.invoke(app, ["conformance", sub, "--json"]), tmp_path)


@pytest.mark.parametrize(
    "argv",
    [
        ["update", "--project", "{p}", "--component", "claude", "--json"],
        ["update", "--fanout", "--json"],
        ["freshness", "--all-projects", "--json"],
    ],
)
def test_per_project_update_and_freshness_refuse(argv, tmp_path):
    _assert_retired(runner.invoke(app, [a.format(p=tmp_path) for a in argv]), tmp_path)
