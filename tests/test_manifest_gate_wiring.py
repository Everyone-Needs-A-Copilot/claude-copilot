"""Regression contract for the Claude plugin manifest release gate."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_smoke_workflow_runs_manifest_checker() -> None:
    workflow = (REPO_ROOT / ".github/workflows/smoke-tests.yml").read_text(
        encoding="utf-8"
    )

    assert "python .claude-plugin/check-manifest.py" in workflow
