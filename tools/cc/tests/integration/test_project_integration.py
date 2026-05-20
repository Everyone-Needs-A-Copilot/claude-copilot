"""Integration tests for the cc CLI.

These tests run real cc invocations via subprocess and verify end-to-end
behavior in any git project directory. They are intentionally independent
of each other — no shared state — and clean up any test artifacts.

Run from the copilot repo root:
    pytest tools/cc/tests/integration/ -v

Or from any git project directory:
    pytest /path/to/tools/cc/tests/integration/ -v
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CC = "/Users/pabs/.local/bin/cc"
UNIQUE_TAG = "cc-integration-test"
UNIQUE_CONTENT_PREFIX = "cc-integration-test-entry"


def run(args: list[str], cwd: str | None = None, **kwargs) -> subprocess.CompletedProcess:
    """Run cc with the given args, capture stdout+stderr."""
    return subprocess.run(
        [CC] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
        **kwargs,
    )


def project_root() -> str:
    """Return the git root of the current working directory."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip("Not inside a git repository — integration tests require a git project")
    return result.stdout.strip()


@pytest.fixture(autouse=True)
def cleanup_test_entries():
    """After each test, delete any leftover entries tagged cc-integration-test."""
    yield
    # Best-effort cleanup: list all entries with our tag and delete them
    result = subprocess.run(
        [CC, "memory", "list", "--json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return
    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        return
    for entry in entries:
        tags = entry.get("tags", [])
        if UNIQUE_TAG in tags:
            subprocess.run(
                [CC, "memory", "delete", "--yes", entry["id"]],
                capture_output=True,
            )


# ---------------------------------------------------------------------------
# Installation checks
# ---------------------------------------------------------------------------

class TestInstallation:
    def test_cc_installed(self):
        """cc --version exits 0 from /tmp, proving global install."""
        result = run(["--version"], cwd="/tmp")
        assert result.returncode == 0, f"cc --version failed: {result.stderr}"
        assert "cc version" in result.stdout or "0." in result.stdout

    def test_cc_on_path(self):
        """cc binary resolves on PATH."""
        result = subprocess.run(
            ["bash", "-c", "command -v cc"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, "cc not found on PATH"
        assert "cc" in result.stdout


# ---------------------------------------------------------------------------
# Machine config
# ---------------------------------------------------------------------------

class TestMachineConfig:
    def test_machine_config_readable(self):
        """cc config list --scope machine exits 0."""
        result = run(["config", "list", "--scope", "machine"])
        assert result.returncode == 0, (
            f"cc config list --scope machine failed:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_env_hydration(self):
        """cc env outputs valid shell exports in KEY=VALUE format."""
        result = run(["env"])
        assert result.returncode == 0, f"cc env failed: {result.stderr}"
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        assert len(lines) > 0, "cc env produced no output"
        for line in lines:
            assert line.startswith("export "), (
                f"Line does not start with 'export ': {line!r}"
            )
            assert "=" in line, f"Export line missing '=': {line!r}"


# ---------------------------------------------------------------------------
# Memory — project scope
# ---------------------------------------------------------------------------

class TestMemoryProjectScope:
    def _store_test_entry(self, content: str | None = None) -> dict:
        """Store a tagged test entry and return the JSON result."""
        text = content or f"{UNIQUE_CONTENT_PREFIX} {os.getpid()}"
        result = run([
            "memory", "store",
            "--type", "context",
            "--tags", UNIQUE_TAG,
            "--json",
            text,
        ])
        assert result.returncode == 0, (
            f"store failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        return json.loads(result.stdout.strip())

    def test_memory_store_creates_file(self):
        """store creates a .md file in .claude/memory/entries/."""
        data = self._store_test_entry()
        path = Path(data["path"])
        assert path.exists(), f"Entry file not found: {path}"
        assert path.suffix == ".md"
        assert path.parent.name == "entries"

    def test_memory_file_has_frontmatter(self):
        """The .md file has id, type, and created fields in YAML frontmatter."""
        data = self._store_test_entry()
        path = Path(data["path"])
        text = path.read_text(encoding="utf-8")

        assert text.startswith("---\n"), "File does not start with YAML frontmatter"
        assert f"id: {data['id']}" in text, "id missing from frontmatter"
        assert "type:" in text, "type missing from frontmatter"
        assert "created:" in text, "created missing from frontmatter"

    def test_memory_search_finds_entry(self):
        """search returns the stored entry by content keyword."""
        unique_word = f"xyzzy{os.getpid()}"
        self._store_test_entry(content=f"{UNIQUE_CONTENT_PREFIX} {unique_word}")

        result = run(["memory", "search", unique_word])
        assert result.returncode == 0, f"search failed: {result.stderr}"
        assert unique_word in result.stdout, (
            f"Entry not found in search results:\n{result.stdout}"
        )

    def test_memory_list_shows_entry(self):
        """list shows the stored entry with correct type."""
        self._store_test_entry()
        result = run(["memory", "list", "--type", "context"])
        assert result.returncode == 0, f"list failed: {result.stderr}"
        assert UNIQUE_TAG in result.stdout, (
            f"Tag {UNIQUE_TAG!r} not found in list output:\n{result.stdout}"
        )

    def test_memory_gitignore_exists(self):
        """The .claude/memory/.gitignore file contains memory.db."""
        root = project_root()
        gitignore_path = Path(root) / ".claude" / "memory" / ".gitignore"
        # If it doesn't exist yet, trigger a store to create it
        if not gitignore_path.exists():
            self._store_test_entry()
        assert gitignore_path.exists(), (
            f".gitignore not found at {gitignore_path}"
        )
        content = gitignore_path.read_text(encoding="utf-8")
        assert "memory.db" in content, (
            f"memory.db not in .gitignore:\n{content}"
        )

    def test_memory_entries_dir_tracked(self):
        """The .claude/memory/entries/ directory exists (has .gitkeep or entries)."""
        root = project_root()
        entries_dir = Path(root) / ".claude" / "memory" / "entries"
        # If missing, create via store
        if not entries_dir.exists():
            self._store_test_entry()
        assert entries_dir.exists(), f"entries/ dir not found at {entries_dir}"
        # Should have .gitkeep or at least one .md file
        contents = list(entries_dir.iterdir())
        assert len(contents) > 0, "entries/ directory is completely empty (not even .gitkeep)"

    def test_memory_delete_removes_file(self):
        """delete removes the .md file from disk."""
        data = self._store_test_entry()
        path = Path(data["path"])
        assert path.exists(), "Entry file was not created"

        result = run(["memory", "delete", "--yes", data["id"]])
        assert result.returncode == 0, f"delete failed: {result.stderr}"
        assert not path.exists(), f"Entry file still exists after delete: {path}"


# ---------------------------------------------------------------------------
# Config — two layers
# ---------------------------------------------------------------------------

class TestConfig:
    def test_project_config_or_default(self):
        """cc config list exits 0 whether or not a project config exists."""
        result = run(["config", "list"])
        assert result.returncode == 0, (
            f"cc config list failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_sentinel_resolution(self):
        """cc env emits CC_PATHS_SHARED_DOCS when the value is set, and omits it when absent.

        This test is hermetic: it injects a sentinel value via the CC_PATHS_SHARED_DOCS env
        var (highest-precedence config layer) rather than relying on whatever is stored in
        the developer's machine config file.  The same test therefore passes on every machine
        regardless of local configuration — whether shared_docs is configured, null, or absent.
        """
        test_path = "/tmp/cc-test-shared-docs-sentinel"

        # --- Case 1: value IS configured (via env var) → cc env MUST emit it ---
        env_with = {**os.environ, "CC_PATHS_SHARED_DOCS": test_path}
        result_with = run(["env"], env=env_with)
        assert result_with.returncode == 0, (
            f"cc env failed when CC_PATHS_SHARED_DOCS was set:\n{result_with.stderr}"
        )
        assert "CC_PATHS_SHARED_DOCS" in result_with.stdout, (
            f"CC_PATHS_SHARED_DOCS not emitted by cc env even though it was provided via env var:\n"
            f"{result_with.stdout}"
        )
        assert test_path in result_with.stdout, (
            f"Expected path {test_path!r} not found in cc env output:\n{result_with.stdout}"
        )

        # --- Case 2: value is NOT configured (env var stripped) → test_path must be absent ---
        # This verifies cc env does not hallucinate the key when its value is null/unset.
        env_without = {k: v for k, v in os.environ.items() if k != "CC_PATHS_SHARED_DOCS"}
        result_without = run(["env"], env=env_without)
        assert result_without.returncode == 0, (
            f"cc env failed when CC_PATHS_SHARED_DOCS was absent:\n{result_without.stderr}"
        )
        assert test_path not in result_without.stdout, (
            f"Sentinel test_path {test_path!r} leaked into cc env output without being configured:\n"
            f"{result_without.stdout}"
        )


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

class TestSkills:
    def test_skill_list_exits_zero(self):
        """cc skill list exits 0 (may find 0 or more skills, both are ok)."""
        result = run(["skill", "list"])
        assert result.returncode == 0, (
            f"cc skill list failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

class TestMigration:
    def test_migrate_status_exits_zero(self):
        """cc memory migrate --status exits 0."""
        result = run(["memory", "migrate", "--status"])
        assert result.returncode == 0, (
            f"cc memory migrate --status failed:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# MCP shim
# ---------------------------------------------------------------------------

class TestMcpShim:
    def test_mcp_config_valid_json(self):
        """cc mcp config outputs valid JSON with a 'cc' key."""
        result = run(["mcp", "config"])
        assert result.returncode == 0, f"cc mcp config failed: {result.stderr}"
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            pytest.fail(f"cc mcp config output is not valid JSON: {exc}\n{result.stdout}")
        assert "cc" in data, f"'cc' key missing from mcp config output: {data}"
        entry = data["cc"]
        assert "command" in entry, "'command' missing from cc mcp config entry"
        assert "args" in entry, "'args' missing from cc mcp config entry"
        assert entry["args"] == ["mcp", "serve"], (
            f"Unexpected args: {entry['args']}"
        )
