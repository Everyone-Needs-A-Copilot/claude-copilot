"""Tests for cc config CLI subcommands: get, set, unset, list, where, init."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc.main import app

runner = CliRunner()


def invoke(*args):
    return runner.invoke(app, list(args))


# ---------------------------------------------------------------------------
# cc config help
# ---------------------------------------------------------------------------


def test_config_help_lists_commands():
    result = invoke("config", "--help")
    assert result.exit_code == 0
    assert "get" in result.output
    assert "set" in result.output
    assert "list" in result.output
    assert "where" in result.output
    assert "init" in result.output
    assert "doctor" in result.output
    assert "validate" in result.output
    assert "export" in result.output


# ---------------------------------------------------------------------------
# cc config get
# ---------------------------------------------------------------------------


def test_config_get_returns_value(monkeypatch, tmp_path):
    cfg = {"paths": {"memory": "/test/memory"}}
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(cfg))

    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.load_project_config", lambda: {})

    result = invoke("config", "get", "paths.memory")
    assert result.exit_code == 0
    assert "/test/memory" in result.output


def test_config_get_raw_flag(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"paths": {"memory": "/raw/memory"}}))
    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.load_project_config", lambda: {})

    result = invoke("config", "get", "paths.memory", "--raw")
    assert result.exit_code == 0
    assert result.output.strip() == "/raw/memory"


def test_config_get_json_flag(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"paths": {"memory": "/json/memory"}}))
    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.load_project_config", lambda: {})

    result = invoke("config", "get", "paths.memory", "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["value"] == "/json/memory"
    assert data["key"] == "paths.memory"


def test_config_get_unset_key(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({}))
    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.load_project_config", lambda: {})

    result = invoke("config", "get", "paths.shared_docs")
    assert result.exit_code == 0
    assert "not set" in result.output


# ---------------------------------------------------------------------------
# cc config set
# ---------------------------------------------------------------------------


def test_config_set_writes_to_machine(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)

    result = invoke("config", "set", "paths.memory", "/set/memory")
    assert result.exit_code == 0

    data = json.loads(cfg_file.read_text())
    assert data["paths"]["memory"] == "/set/memory"


def test_config_set_project_flag(monkeypatch, tmp_path):
    cfg_file = tmp_path / "project_config.json"

    monkeypatch.setattr("cc.core.config_paths.project_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.project_config_path", lambda: cfg_file)

    result = invoke("config", "set", "paths.memory", "/proj/memory", "--project")
    assert result.exit_code == 0

    data = json.loads(cfg_file.read_text())
    assert data["paths"]["memory"] == "/proj/memory"


def test_config_set_output_mentions_layer(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)

    result = invoke("config", "set", "paths.memory", "/m")
    assert "machine" in result.output


# ---------------------------------------------------------------------------
# cc config list
# ---------------------------------------------------------------------------


def test_config_list_machine_scope(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"paths": {"memory": "/list/memory"}}))
    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr(
        "cc.core.config.load_machine_config",
        lambda: {"paths": {"memory": "/list/memory"}},
    )

    result = invoke("config", "list", "--scope", "machine")
    assert result.exit_code == 0
    assert "paths.memory" in result.output
    assert "/list/memory" in result.output


def test_config_list_json_flag(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "cc.commands.config.get_resolved_config",
        lambda **_: {"paths.memory": "/list/mem", "memory.embedding_model": "none"},
    )

    result = invoke("config", "list", "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "paths.memory" in data


# ---------------------------------------------------------------------------
# cc config where
# ---------------------------------------------------------------------------


def test_config_where_shows_source(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"paths": {"memory": "/where/memory"}}))
    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr(
        "cc.core.config.load_machine_config",
        lambda: {"paths": {"memory": "/where/memory"}},
    )
    monkeypatch.setattr("cc.core.config.load_project_config", lambda: {})

    result = invoke("config", "where", "paths.memory")
    assert result.exit_code == 0
    assert "machine" in result.output


def test_config_where_json_flag(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "cc.commands.config.where_key",
        lambda key: {"value": "/test", "source": "machine", "reason": "machine config"},
    )
    result = invoke("config", "where", "paths.memory", "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["source"] == "machine"


# ---------------------------------------------------------------------------
# cc config init
# ---------------------------------------------------------------------------


def test_config_init_machine_creates_file(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.commands.config.machine_config_path", lambda: cfg_file)

    result = invoke("config", "init", "--machine")
    assert result.exit_code == 0
    assert cfg_file.exists()

    data = json.loads(cfg_file.read_text())
    assert "paths" in data


def test_config_init_does_not_overwrite_existing(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"paths": {"memory": "/existing"}}))
    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.commands.config.machine_config_path", lambda: cfg_file)

    result = invoke("config", "init", "--machine")
    assert result.exit_code == 0
    assert "Already exists" in result.output

    # File unchanged
    data = json.loads(cfg_file.read_text())
    assert data["paths"]["memory"] == "/existing"


# ---------------------------------------------------------------------------
# cc config validate
# ---------------------------------------------------------------------------


def test_config_validate_passes_valid_json(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"paths": {"memory": "/valid"}}))
    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.commands.config.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.commands.config.project_config_path", lambda: None)

    result = invoke("config", "validate")
    assert result.exit_code == 0


def test_config_validate_fails_invalid_json(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text("{invalid json}")
    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.commands.config.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.commands.config.project_config_path", lambda: None)

    result = invoke("config", "validate")
    assert result.exit_code == 3


# ---------------------------------------------------------------------------
# Round-trip: set → get
# ---------------------------------------------------------------------------


def test_round_trip_set_get(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.load_project_config", lambda: {})

    invoke("config", "set", "paths.memory", "/roundtrip/memory")
    result = invoke("config", "get", "paths.memory", "--raw")

    assert result.exit_code == 0
    assert result.output.strip() == "/roundtrip/memory"
