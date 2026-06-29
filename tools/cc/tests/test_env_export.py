"""Tests for cc env and cc resolve commands."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from cc.main import app

runner = CliRunner()


def invoke(*args):
    return runner.invoke(app, list(args))


# ---------------------------------------------------------------------------
# cc env — shell exports
# ---------------------------------------------------------------------------


def test_env_outputs_shell_exports(monkeypatch):
    """cc env outputs export NAME="value" lines."""
    monkeypatch.setattr(
        "cc.commands.env.get_resolved_config",
        lambda **_: {
            "paths.memory": "/test/memory",
            "memory.embedding_model": "none",
            "paths.shared_docs": None,  # None → skipped
        },
    )

    result = invoke("env")
    assert result.exit_code == 0
    assert 'export CC_PATHS_MEMORY="/test/memory"' in result.output
    assert 'export CC_MEMORY_EMBEDDING_MODEL="none"' in result.output
    # None values not emitted
    assert "CC_PATHS_SHARED_DOCS" not in result.output


def test_env_skips_null_values(monkeypatch):
    """cc env skips keys with None values."""
    monkeypatch.setattr(
        "cc.commands.env.get_resolved_config",
        lambda **_: {
            "paths.shared_docs": None,
            "paths.knowledge_repo": None,
            "memory.embedding_model": "none",
        },
    )

    result = invoke("env")
    assert result.exit_code == 0
    assert "CC_PATHS_SHARED_DOCS" not in result.output
    assert "CC_PATHS_KNOWLEDGE_REPO" not in result.output
    assert "CC_MEMORY_EMBEDDING_MODEL" in result.output


def test_env_emits_knowledge_repo_alias(monkeypatch):
    """CC_KNOWLEDGE_REPO and CC_SHARED_DOCS are emitted as short-form aliases."""
    monkeypatch.setattr(
        "cc.commands.env.get_resolved_config",
        lambda **_: {
            "paths.knowledge_repo": "/vol/copilot/shared-docs",
            "paths.shared_docs": "/vol/copilot/shared-docs",
        },
    )

    result = invoke("env")
    assert result.exit_code == 0
    # Short-form aliases present
    assert 'export CC_KNOWLEDGE_REPO="/vol/copilot/shared-docs"' in result.output
    assert 'export CC_SHARED_DOCS="/vol/copilot/shared-docs"' in result.output
    # Long-form keys also present
    assert 'export CC_PATHS_KNOWLEDGE_REPO="/vol/copilot/shared-docs"' in result.output
    assert 'export CC_PATHS_SHARED_DOCS="/vol/copilot/shared-docs"' in result.output


def test_env_alias_not_emitted_when_source_is_none(monkeypatch):
    """CC_KNOWLEDGE_REPO alias is NOT emitted when paths.knowledge_repo is None."""
    monkeypatch.setattr(
        "cc.commands.env.get_resolved_config",
        lambda **_: {
            "paths.knowledge_repo": None,
            "paths.shared_docs": None,
        },
    )

    result = invoke("env")
    assert result.exit_code == 0
    assert "CC_KNOWLEDGE_REPO" not in result.output
    assert "CC_SHARED_DOCS" not in result.output


def test_env_json_flag(monkeypatch):
    """cc env --json outputs valid JSON."""
    monkeypatch.setattr(
        "cc.commands.env.get_resolved_config",
        lambda **_: {
            "paths.memory": "/json/memory",
            "memory.embedding_model": "none",
        },
    )

    result = invoke("env", "--json")
    assert result.exit_code == 0

    data = json.loads(result.output)
    assert data["CC_PATHS_MEMORY"] == "/json/memory"
    assert data["CC_MEMORY_EMBEDDING_MODEL"] == "none"


def test_env_json_is_valid_json(monkeypatch):
    """cc env --json output parses without error."""
    monkeypatch.setattr(
        "cc.commands.env.get_resolved_config",
        lambda **_: {"paths.memory": "/some/path"},
    )

    result = invoke("env", "--json")
    # Should not raise
    data = json.loads(result.output)
    assert isinstance(data, dict)


def test_env_excludes_secrets_by_default(monkeypatch):
    """cc env without --include-secrets MUST NOT emit secret values."""
    monkeypatch.setattr(
        "cc.commands.env.get_resolved_config",
        lambda **_: {"paths.memory": "/memory"},
    )
    monkeypatch.setattr(
        "cc.commands.env.load_machine_secrets",
        lambda: {"MY_SECRET_TOKEN": "super-secret"},
    )
    monkeypatch.setattr(
        "cc.commands.env.load_project_secrets",
        lambda: {"ANOTHER_SECRET": "also-secret"},
    )

    result = invoke("env")
    assert result.exit_code == 0
    assert "super-secret" not in result.output
    assert "also-secret" not in result.output
    assert "MY_SECRET_TOKEN" not in result.output
    assert "ANOTHER_SECRET" not in result.output


def test_env_includes_secrets_with_flag(monkeypatch):
    """cc env --include-secrets emits secret values."""
    monkeypatch.setattr(
        "cc.commands.env.get_resolved_config",
        lambda **_: {"paths.memory": "/memory"},
    )
    monkeypatch.setattr(
        "cc.commands.env.load_machine_secrets",
        lambda: {"MY_TOKEN": "secret-value"},
    )
    monkeypatch.setattr(
        "cc.commands.env.load_project_secrets",
        lambda: {},
    )

    result = invoke("env", "--include-secrets")
    assert result.exit_code == 0
    assert "MY_TOKEN" in result.output
    assert "secret-value" in result.output


def test_env_handles_spaces_in_values(monkeypatch):
    """Values with spaces are quoted correctly."""
    monkeypatch.setattr(
        "cc.commands.env.get_resolved_config",
        lambda **_: {"paths.memory": "/path/with spaces/memory"},
    )

    result = invoke("env")
    assert result.exit_code == 0
    assert '"/path/with spaces/memory"' in result.output


# ---------------------------------------------------------------------------
# cc resolve <key>
# ---------------------------------------------------------------------------


def test_resolve_key_command(monkeypatch):
    monkeypatch.setattr(
        "cc.main.resolve_key",
        lambda key, scope=None, **_: "/resolved/value",
    )

    result = invoke("resolve", "paths.memory")
    assert result.exit_code == 0
    assert result.output.strip() == "/resolved/value"


def test_resolve_key_json_flag(monkeypatch):
    monkeypatch.setattr(
        "cc.main.resolve_key",
        lambda key, scope=None, **_: "/resolved/value",
    )

    result = invoke("resolve", "paths.memory", "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["key"] == "paths.memory"
    assert data["value"] == "/resolved/value"


def test_resolve_key_exits_nonzero_when_not_set(monkeypatch):
    monkeypatch.setattr(
        "cc.main.resolve_key",
        lambda key, scope=None, **_: None,
    )

    result = invoke("resolve", "paths.missing_key")
    assert result.exit_code != 0


def test_resolve_key_missing_arg():
    result = invoke("resolve")
    # Should fail or show help — not exit 0 silently
    assert result.exit_code != 0
