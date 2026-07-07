"""Tests for cc config doctor health checks."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc.commands.doctor import build_doctor_report, run_doctor, NOT_IN_REPO
from cc.main import app

runner = CliRunner()


def invoke(*args):
    return runner.invoke(app, list(args))


# ---------------------------------------------------------------------------
# run_doctor unit tests (mock-FS via tmp_path)
# ---------------------------------------------------------------------------


def test_doctor_clean_when_configs_exist(tmp_path):
    machine_cfg = tmp_path / "machine" / "config.json"
    machine_cfg.parent.mkdir(parents=True)
    machine_cfg.write_text('{"paths": {"memory": "/tmp/memory"}}')

    project_cfg = tmp_path / "project" / "config.json"
    project_cfg.parent.mkdir(parents=True)
    project_cfg.write_text("{}")

    # Use resolved cfg with no path issues
    resolved_cfg = {"paths.memory": str(tmp_path)}  # tmp_path exists

    result = run_doctor(
        _machine_cfg_path=machine_cfg,
        _project_cfg_path=project_cfg,
        _resolved_cfg=resolved_cfg,
    )

    # tmp_path exists so no path warnings
    assert result.errors == []
    # No gitignore warning because machine config is fresh in tmp (no .gitignore check needed
    # when machine cfg exists but parent has no gitignore → expect that warning)


def test_doctor_warns_missing_machine_config(tmp_path):
    machine_cfg = tmp_path / "nonexistent" / "config.json"  # does not exist
    project_cfg = tmp_path / "project_config.json"
    project_cfg.write_text("{}")

    result = run_doctor(
        _machine_cfg_path=machine_cfg,
        _project_cfg_path=project_cfg,
        _resolved_cfg={},
    )

    assert any("Machine config missing" in w for w in result.warnings)
    assert result.errors == []


def test_doctor_warns_missing_project_config(tmp_path):
    machine_cfg = tmp_path / "machine_config.json"
    machine_cfg.write_text("{}")
    # Create gitignore to suppress that warning
    (tmp_path / ".gitignore").write_text("config.json\n")

    project_cfg = tmp_path / "nonexistent_project.json"  # does not exist

    result = run_doctor(
        _machine_cfg_path=machine_cfg,
        _project_cfg_path=project_cfg,
        _resolved_cfg={},
    )

    assert any("Project config missing" in w for w in result.warnings)


def test_doctor_warns_path_not_found(tmp_path):
    machine_cfg = tmp_path / "machine_config.json"
    machine_cfg.write_text("{}")
    (tmp_path / ".gitignore").write_text("x\n")

    project_cfg = tmp_path / "project_config.json"
    project_cfg.write_text("{}")

    nonexistent = "/tmp/does-not-exist-at-all-9999999"
    resolved_cfg = {"paths.shared_docs": nonexistent}

    result = run_doctor(
        _machine_cfg_path=machine_cfg,
        _project_cfg_path=project_cfg,
        _resolved_cfg=resolved_cfg,
    )

    assert any("Path not found" in w for w in result.warnings)


def test_doctor_no_warnings_for_null_paths(tmp_path):
    machine_cfg = tmp_path / "machine_config.json"
    machine_cfg.write_text("{}")
    (tmp_path / ".gitignore").write_text("x\n")

    project_cfg = tmp_path / "project_config.json"
    project_cfg.write_text("{}")

    # None paths should NOT produce path-not-found warnings
    resolved_cfg = {"paths.shared_docs": None, "paths.knowledge_repo": None}

    result = run_doctor(
        _machine_cfg_path=machine_cfg,
        _project_cfg_path=project_cfg,
        _resolved_cfg=resolved_cfg,
    )

    path_warnings = [w for w in result.warnings if "Path not found" in w]
    assert path_warnings == []


# ---------------------------------------------------------------------------
# checker product attribution (optional, best-effort)
# ---------------------------------------------------------------------------


def test_doctor_json_attributes_knowledge_repo_checker_to_knowledge_product(tmp_path):
    """`paths.knowledge_repo` is unambiguously owned by Knowledge Copilot --
    its config-path checker must carry `product: "knowledge"`."""
    machine_cfg = tmp_path / "machine_config.json"
    machine_cfg.write_text("{}")
    (tmp_path / ".gitignore").write_text("x\n")

    project_cfg = tmp_path / "project_config.json"
    project_cfg.write_text("{}")

    resolved_cfg = {"paths.knowledge_repo": str(tmp_path)}

    report = build_doctor_report(
        _machine_cfg_path=machine_cfg,
        _project_cfg_path=project_cfg,
        _resolved_cfg=resolved_cfg,
    )

    knowledge_checker = next(
        c for c in report["checkers"] if c["id"] == "config-path:paths.knowledge_repo"
    )
    assert knowledge_checker["product"] == "knowledge"


def test_doctor_json_unattributable_checkers_omit_product(tmp_path):
    """Checkers with no clear single-product ownership (e.g. machine-config)
    must never carry a fabricated `product` -- absent, not guessed."""
    machine_cfg = tmp_path / "machine_config.json"
    machine_cfg.write_text("{}")

    project_cfg = tmp_path / "project_config.json"
    project_cfg.write_text("{}")

    report = build_doctor_report(
        _machine_cfg_path=machine_cfg,
        _project_cfg_path=project_cfg,
        _resolved_cfg={},
    )

    machine_config_checker = next(
        c for c in report["checkers"] if c["id"] == "machine-config"
    )
    assert "product" not in machine_config_checker


def test_doctor_warns_no_gitignore(tmp_path):
    """Warns if machine config exists but its parent has no .gitignore."""
    machine_cfg = tmp_path / "config.json"
    machine_cfg.write_text("{}")
    # Deliberately no .gitignore in tmp_path

    project_cfg = tmp_path / "project_config.json"
    project_cfg.write_text("{}")

    result = run_doctor(
        _machine_cfg_path=machine_cfg,
        _project_cfg_path=project_cfg,
        _resolved_cfg={},
    )

    assert any(".gitignore" in w for w in result.warnings)


def test_doctor_not_in_repo(tmp_path):
    """When NOT_IN_REPO sentinel is passed, emits not-in-repo warning."""
    machine_cfg = tmp_path / "machine_config.json"
    machine_cfg.write_text("{}")
    (tmp_path / ".gitignore").write_text("x\n")

    result = run_doctor(
        _machine_cfg_path=machine_cfg,
        _project_cfg_path=NOT_IN_REPO,
        _resolved_cfg={},
    )

    assert any("git repository" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# CLI integration test
# ---------------------------------------------------------------------------


def test_config_doctor_command_accessible():
    """cc config doctor is a registered command."""
    result = invoke("config", "doctor", "--help")
    assert result.exit_code == 0
    assert (
        "doctor" in result.output.lower()
        or "check" in result.output.lower()
        or "health" in result.output.lower()
    )
