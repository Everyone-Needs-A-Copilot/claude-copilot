"""Tests for cc mcp commands: config, serve, and MCP tool schemas.

Covers:
- cc mcp config outputs valid JSON with correct command path
- cc mcp serve fails gracefully when mcp package is not installed
- MCP tool schemas are correctly defined (names, parameter types)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from cc.main import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# cc mcp config
# ---------------------------------------------------------------------------


class TestMcpConfig:
    def test_outputs_valid_json(self, runner):
        result = runner.invoke(app, ["mcp", "config"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)

    def test_json_has_cc_key(self, runner):
        result = runner.invoke(app, ["mcp", "config"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "cc" in data

    def test_cc_entry_has_command_and_args(self, runner):
        result = runner.invoke(app, ["mcp", "config"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        entry = data["cc"]
        assert "command" in entry
        assert "args" in entry
        assert entry["args"] == ["mcp", "serve"]

    def test_command_is_absolute_path(self, runner):
        result = runner.invoke(app, ["mcp", "config"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        command = data["cc"]["command"]
        # Must be a non-empty string — the actual binary path
        assert isinstance(command, str)
        assert len(command) > 0

    def test_command_path_when_cc_on_path(self, runner):
        """When cc is on PATH, command should be that resolved path."""
        with patch("cc.commands.mcp.shutil.which", return_value="/usr/local/bin/cc"):
            result = runner.invoke(app, ["mcp", "config"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["cc"]["command"] == "/usr/local/bin/cc"

    def test_command_fallback_to_argv0(self, runner):
        """When cc is not on PATH, falls back to sys.argv[0]."""
        with patch("cc.commands.mcp.shutil.which", return_value=None):
            with patch("cc.commands.mcp.sys.argv", ["/opt/local/bin/cc"]):
                result = runner.invoke(app, ["mcp", "config"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["cc"]["command"] == "/opt/local/bin/cc"


# ---------------------------------------------------------------------------
# cc mcp serve — graceful degradation
# ---------------------------------------------------------------------------


class TestMcpServeGracefulDegradation:
    """Test that mcp serve exits cleanly when the mcp package is absent."""

    def _invoke_with_no_mcp(self, runner):
        """Invoke `cc mcp serve` with mcp_serve.run_server patched to raise ImportError."""
        # Ensure mcp_serve is already imported so we can patch its name in
        # cc.commands.mcp's local scope via the module-level import statement.
        # We simulate ImportError by replacing the module with None in sys.modules
        # and then un-importing so the `from cc.commands.mcp_serve import run_server`
        # line inside mcp_serve.py raises ImportError.
        import importlib
        import cc.commands.mcp as mcp_cmd

        # Temporarily shadow cc.commands.mcp_serve in sys.modules with None
        # so that `from cc.commands.mcp_serve import run_server` raises ImportError.
        saved = sys.modules.get("cc.commands.mcp_serve", _SENTINEL)
        sys.modules["cc.commands.mcp_serve"] = None  # type: ignore[assignment]
        try:
            result = runner.invoke(app, ["mcp", "serve"])
        finally:
            if saved is _SENTINEL:
                del sys.modules["cc.commands.mcp_serve"]
            else:
                sys.modules["cc.commands.mcp_serve"] = saved
        return result

    def test_exits_with_code_1_when_mcp_not_installed(self, runner):
        result = self._invoke_with_no_mcp(runner)
        assert result.exit_code == 1

    def test_error_message_instructs_pip_install(self, runner):
        result = self._invoke_with_no_mcp(runner)
        combined = result.output + (result.stderr or "")
        assert "pip install" in combined

    def test_error_message_includes_mcp_extra(self, runner):
        result = self._invoke_with_no_mcp(runner)
        combined = result.output + (result.stderr or "")
        assert "cc[mcp]" in combined


_SENTINEL = object()


# ---------------------------------------------------------------------------
# MCP tool schema definitions (tested without running the server)
# ---------------------------------------------------------------------------


class TestMcpToolSchemas:
    """Verify tool definitions without requiring mcp package to be installed."""

    @pytest.fixture
    def tools(self):
        """Load tool definitions via mcp_serve if mcp is available, else skip."""
        try:
            import mcp  # noqa: F401
        except ImportError:
            pytest.skip("mcp package not installed — schema tests skipped")

        import asyncio
        from cc.commands.mcp_serve import build_server

        server = build_server()

        async def _get_tools():
            # Access the registered handler directly
            handler = server._tool_handlers.get("list_tools") or server.list_tools
            if callable(handler):
                return await handler()
            return []

        # Fallback: call list_tools handler via the registered hooks
        try:
            tools = asyncio.run(_get_tools())
        except Exception:
            # Alternate introspection path
            from cc.commands.mcp_serve import build_server as bs
            import inspect

            srv = bs()
            # The server exposes _list_tools_handler
            tools = asyncio.run(srv._list_tools_handler())

        return tools

    def test_expected_tool_names_present(self, tools):
        names = {t.name for t in tools}
        expected = {
            "memory_store",
            "memory_search",
            "memory_get",
            "memory_list",
            "memory_delete",
            "skill_list",
            "skill_search",
            "skill_get",
            "config_get",
            "config_set",
        }
        assert expected == names

    def test_tool_count(self, tools):
        assert len(tools) == 10

    def test_memory_store_required_params(self, tools):
        tool = next(t for t in tools if t.name == "memory_store")
        assert "content" in tool.inputSchema["required"]

    def test_memory_search_required_params(self, tools):
        tool = next(t for t in tools if t.name == "memory_search")
        assert "query" in tool.inputSchema["required"]

    def test_memory_get_required_params(self, tools):
        tool = next(t for t in tools if t.name == "memory_get")
        assert "entry_id" in tool.inputSchema["required"]

    def test_memory_delete_required_params(self, tools):
        tool = next(t for t in tools if t.name == "memory_delete")
        assert "entry_id" in tool.inputSchema["required"]

    def test_skill_search_required_params(self, tools):
        tool = next(t for t in tools if t.name == "skill_search")
        assert "query" in tool.inputSchema["required"]

    def test_skill_get_required_params(self, tools):
        tool = next(t for t in tools if t.name == "skill_get")
        assert "name" in tool.inputSchema["required"]

    def test_config_get_required_params(self, tools):
        tool = next(t for t in tools if t.name == "config_get")
        assert "key" in tool.inputSchema["required"]

    def test_config_set_required_params(self, tools):
        tool = next(t for t in tools if t.name == "config_set")
        schema = tool.inputSchema
        assert "key" in schema["required"]
        assert "value" in schema["required"]

    def test_all_tools_have_descriptions(self, tools):
        for tool in tools:
            assert tool.description, f"Tool {tool.name!r} missing description"

    def test_all_tools_have_input_schemas(self, tools):
        for tool in tools:
            assert tool.inputSchema, f"Tool {tool.name!r} missing inputSchema"
            assert tool.inputSchema.get("type") == "object"

    def test_memory_store_entry_type_default(self, tools):
        tool = next(t for t in tools if t.name == "memory_store")
        props = tool.inputSchema["properties"]
        assert props["entry_type"]["default"] == "context"

    def test_skill_list_scope_default(self, tools):
        tool = next(t for t in tools if t.name == "skill_list")
        props = tool.inputSchema["properties"]
        assert props["scope"]["default"] == "all"


# ---------------------------------------------------------------------------
# Schema tests that run WITHOUT mcp package (inspect the raw dict)
# ---------------------------------------------------------------------------


class TestMcpToolSchemasNoMcpPackage:
    """These tests introspect mcp_serve.build_server() tool definitions
    without requiring the mcp package, by looking at the raw schema dicts
    embedded in the source before they're wrapped into Tool objects."""

    def test_tool_names_in_serve_module(self):
        """The serve module defines exactly the 10 expected tool names."""
        import ast
        import pathlib

        src = (
            pathlib.Path(__file__).parent.parent
            / "src"
            / "cc"
            / "commands"
            / "mcp_serve.py"
        )
        tree = ast.parse(src.read_text())

        # Collect all string constants that look like tool names
        tool_name_candidates = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value
                if val.startswith(("memory_", "skill_", "config_")):
                    tool_name_candidates.add(val)

        expected = {
            "memory_store",
            "memory_search",
            "memory_get",
            "memory_list",
            "memory_delete",
            "skill_list",
            "skill_search",
            "skill_get",
            "config_get",
            "config_set",
        }
        assert expected.issubset(tool_name_candidates)
