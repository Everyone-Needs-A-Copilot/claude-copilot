"""Tests for cc CLI top-level commands and subgroup registration."""

from cc import __version__


def test_version_command(cli):
    """cc version prints the version string."""
    result = cli(["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_version_flag(cli):
    """cc --version prints the version string."""
    result = cli(["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_subgroups(cli):
    """cc --help lists all registered subcommand groups."""
    result = cli(["--help"])
    assert result.exit_code == 0
    assert "memory" in result.output
    assert "skill" in result.output
    assert "config" in result.output
    assert "mcp" in result.output
    assert "env" in result.output


def test_memory_help(cli):
    """cc memory --help exits cleanly and lists memory subcommands."""
    result = cli(["memory", "--help"])
    assert result.exit_code == 0
    assert "store" in result.output
    assert "search" in result.output
    assert "list" in result.output
    assert "index" in result.output


def test_skill_help(cli):
    """cc skill --help exits cleanly and lists skill subcommands (evaluate removed per TASK-29)."""
    result = cli(["skill", "--help"])
    assert result.exit_code == 0
    assert "get" in result.output
    assert "search" in result.output
    assert "list" in result.output
    assert "evaluate" not in result.output


def test_config_help(cli):
    """cc config --help exits cleanly and lists config subcommands."""
    result = cli(["config", "--help"])
    assert result.exit_code == 0
    assert "get" in result.output
    assert "set" in result.output
    assert "list" in result.output
    assert "doctor" in result.output


def test_mcp_help(cli):
    """cc mcp --help exits cleanly and lists mcp subcommands."""
    result = cli(["mcp", "--help"])
    assert result.exit_code == 0
    assert "serve" in result.output
    assert "config" in result.output


def test_env_emits_exports(cli):
    """cc env exits 0 and outputs export lines."""
    result = cli(["env"])
    assert result.exit_code == 0
    # Should contain at least one export line (memory path default is always set)
    assert "export CC_" in result.output


def test_env_json_flag(cli):
    """cc env --json exits 0 and outputs valid JSON."""
    import json
    result = cli(["env", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, dict)


def test_memory_store_requires_content_arg(cli):
    """cc memory store without required content argument exits non-zero."""
    result = cli(["memory", "store"])
    assert result.exit_code != 0
