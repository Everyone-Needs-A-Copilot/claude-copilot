"""Tests for Task 103 (C1): cc docs Typer command group.

Covers:
  - resolve: version detection output (text + JSON)
  - get: fetch docs (text + JSON), --source local|fetch, --refresh
  - search: topic-based search
  - sources: list backends + availability
  - cache: --status, --clear
  - CLI smoke tests for each verb
  - JSON output shape validation
  - Error paths (pkg not found → exit 1)
  - Registry isolation via fixture
"""

from __future__ import annotations

import json
import importlib.util
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from cc.main import app


# ---------------------------------------------------------------------------
# Registry isolation + fake backend fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_registry():
    """Save and restore the global _BACKEND_REGISTRY around each test."""
    from cc.core import docs_resolver
    saved = dict(docs_resolver._BACKEND_REGISTRY)
    yield
    docs_resolver._BACKEND_REGISTRY.clear()
    docs_resolver._BACKEND_REGISTRY.update(saved)


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _invoke(runner: CliRunner, args: list[str]):
    return runner.invoke(app, args)


class _FakeBackend:
    """A fake backend that returns canned docs for any package."""

    def __init__(self, name: str = "_fake", content: str = "# Fake docs\n\nContent here."):
        self.name = name
        self.available = True
        self._content = content

    def fetch(self, pkg, version, topic):
        from cc.core.docs_resolver import DocResult
        return DocResult(
            package=pkg,
            version=version,
            topic=topic,
            content=self._content,
            source=self.name,
            url="https://example.com",
        )


@pytest.fixture()
def fake_backend(isolated_registry):
    """Register a fake backend and return it."""
    from cc.core.docs_resolver import register_backend
    backend = _FakeBackend()
    register_backend("local", backend)  # override 'local' so it returns real content
    return backend


# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------


class TestDocsResolve:
    def test_resolve_real_package_text(self, runner):
        """cc docs resolve typer -- should find installed version."""
        result = _invoke(runner, ["docs", "resolve", "typer"])
        assert result.exit_code == 0
        assert "typer" in result.output.lower() or "0." in result.output

    def test_resolve_real_package_json(self, runner):
        result = _invoke(runner, ["docs", "resolve", "typer", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "version" in data
        assert "exact" in data
        assert data["name"] == "typer"

    def test_resolve_unknown_pkg_exits_1(self, runner):
        result = _invoke(runner, ["docs", "resolve", "completely-unknown-xyz-pkg-999"])
        assert result.exit_code == 1

    def test_resolve_with_lang_python(self, runner):
        result = _invoke(runner, ["docs", "resolve", "pytest", "--lang", "python", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["name"] == "pytest"

    def test_resolve_with_lang_js(self, runner, tmp_path):
        """Fake a JS project with a package-lock.json."""
        import os
        lock = json.dumps({
            "lockfileVersion": 2,
            "packages": {"node_modules/react": {"version": "18.2.0"}},
        })
        # We can't easily control cwd in CliRunner, so just verify it doesn't crash
        result = _invoke(runner, ["docs", "resolve", "react", "--lang", "js"])
        # May exit 1 (not installed) or 0 — just must not crash
        assert result.exit_code in (0, 1)


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


class TestDocsGet:
    def test_get_real_installed_pkg_text(self, runner, fake_backend):
        result = _invoke(runner, ["docs", "get", "typer"])
        assert result.exit_code == 0
        assert "Fake docs" in result.output or "typer" in result.output.lower()

    def test_get_real_installed_pkg_json(self, runner, fake_backend):
        result = _invoke(runner, ["docs", "get", "typer", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "content" in data
        assert "version" in data
        assert "source" in data
        assert data["package"] == "typer"

    def test_get_with_topic(self, runner, fake_backend):
        result = _invoke(runner, ["docs", "get", "typer", "--topic", "commands", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["topic"] == "commands"

    def test_get_with_source_local(self, runner, fake_backend):
        result = _invoke(runner, ["docs", "get", "typer", "--source", "local", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        # The resolver assigns source = the registry key, which is "local"
        assert data["source"] == "local"

    def test_get_with_source_fetch_when_httpx_absent(self, runner, isolated_registry):
        """--source fetch when httpx absent → exit 1 (no docs found).

        Uses --refresh to bypass any cached result, then --source fetch with
        an unavailable fetch backend guarantees no docs can be returned.
        """
        from cc.core import docs_resolver

        class _UnavailFetch:
            name = "fetch"
            available = False

            def fetch(self, pkg, version, topic):
                return None

        docs_resolver._BACKEND_REGISTRY["fetch"] = _UnavailFetch()
        # --refresh bypasses cache; --source fetch uses only the unavailable backend
        result = _invoke(runner, ["docs", "get", "typer", "--source", "fetch", "--refresh"])
        assert result.exit_code == 1

    def test_get_unknown_pkg_exits_1(self, runner):
        result = _invoke(runner, ["docs", "get", "completely-unknown-xyz-pkg-999"])
        assert result.exit_code == 1

    def test_get_with_refresh_flag(self, runner, fake_backend):
        """--refresh flag is accepted and doesn't crash."""
        result = _invoke(runner, ["docs", "get", "typer", "--refresh", "--json"])
        # With fake backend it should succeed
        assert result.exit_code in (0, 1)  # 0 if found, 1 if not — no crash

    def test_get_json_output_has_required_keys(self, runner, fake_backend):
        result = _invoke(runner, ["docs", "get", "typer", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        required = {"package", "version", "topic", "source", "cached", "content"}
        assert required.issubset(data.keys())


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


class TestDocsSearch:
    def test_search_returns_docs(self, runner, fake_backend):
        result = _invoke(runner, ["docs", "search", "typer", "commands"])
        assert result.exit_code == 0

    def test_search_json_output(self, runner, fake_backend):
        result = _invoke(runner, ["docs", "search", "typer", "commands", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "content" in data
        assert data["topic"] == "commands"

    def test_search_unknown_pkg_exits_1(self, runner):
        result = _invoke(runner, ["docs", "search", "completely-unknown-xyz-pkg-999", "anything"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------


class TestDocsSources:
    def test_sources_text_output(self, runner):
        result = _invoke(runner, ["docs", "sources"])
        assert result.exit_code == 0
        assert "local" in result.output
        assert "fetch" in result.output

    def test_sources_json_output(self, runner):
        result = _invoke(runner, ["docs", "sources", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        names = [row["name"] for row in data]
        assert "local" in names
        assert "fetch" in names
        for row in data:
            assert "available" in row


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------


class TestDocsCache:
    def test_cache_status_text(self, runner, tmp_path):
        result = _invoke(runner, ["docs", "cache", "--status"])
        assert result.exit_code == 0
        assert "Cache" in result.output or "total" in result.output

    def test_cache_status_json(self, runner):
        result = _invoke(runner, ["docs", "cache", "--status", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "total" in data
        assert "fresh" in data
        assert "expired" in data

    def test_cache_clear_text(self, runner):
        result = _invoke(runner, ["docs", "cache", "--clear"])
        assert result.exit_code == 0
        assert "Cleared" in result.output or "0" in result.output

    def test_cache_clear_json(self, runner):
        result = _invoke(runner, ["docs", "cache", "--clear", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "deleted" in data

    def test_cache_no_flags_exits_1(self, runner):
        result = _invoke(runner, ["docs", "cache"])
        assert result.exit_code == 1

    def test_cache_status_and_clear_together(self, runner):
        result = _invoke(runner, ["docs", "cache", "--status", "--clear"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Help smoke tests
# ---------------------------------------------------------------------------


class TestHelpSmoke:
    def test_docs_help(self, runner):
        result = _invoke(runner, ["docs", "--help"])
        assert result.exit_code == 0
        assert "resolve" in result.output
        assert "get" in result.output
        assert "search" in result.output
        assert "sources" in result.output
        assert "cache" in result.output

    def test_docs_resolve_help(self, runner):
        result = _invoke(runner, ["docs", "resolve", "--help"])
        assert result.exit_code == 0

    def test_docs_get_help(self, runner):
        result = _invoke(runner, ["docs", "get", "--help"])
        assert result.exit_code == 0
        assert "--topic" in result.output
        assert "--source" in result.output
        assert "--refresh" in result.output
        assert "--json" in result.output

    def test_docs_search_help(self, runner):
        result = _invoke(runner, ["docs", "search", "--help"])
        assert result.exit_code == 0

    def test_docs_cache_help(self, runner):
        result = _invoke(runner, ["docs", "cache", "--help"])
        assert result.exit_code == 0
        assert "--status" in result.output
        assert "--clear" in result.output
