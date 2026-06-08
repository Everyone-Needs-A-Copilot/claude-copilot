"""Tests for Task 101 (B2): FetchBackend — network fallback with httpx.

Covers:
  - httpx absent → available=False, fetch returns None (not an error)
  - httpx present + mock HTTP → returns DocResult with source='fetch'
  - httpx present + offline/timeout → returns None gracefully
  - npm: llms.txt → GitHub raw README resolution order
  - pip: llms.txt → GitHub raw README resolution order
  - Never raises under any conditions
  - Registry isolation via fixture
"""

from __future__ import annotations

import importlib.util
import json
import socket
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from cc.core.docs_backends.fetch import FetchBackend, _httpx_available, _get
from cc.core.docs_resolver import DocResult


# ---------------------------------------------------------------------------
# Registry isolation fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_registry():
    """Save and restore the global _BACKEND_REGISTRY around each test."""
    from cc.core import docs_resolver
    saved = dict(docs_resolver._BACKEND_REGISTRY)
    yield
    docs_resolver._BACKEND_REGISTRY.clear()
    docs_resolver._BACKEND_REGISTRY.update(saved)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_httpx_get(responses: dict[str, bytes | None]):
    """Create a mock for httpx.get that returns preset responses by URL.

    responses: {url: bytes} — if value is None, simulate a 404.
    """
    def _fake_get(url, *, timeout=None, follow_redirects=False):
        raw = responses.get(url)
        resp = MagicMock()
        if raw is None:
            resp.status_code = 404
            resp.content = b""
        else:
            resp.status_code = 200
            resp.content = raw
        return resp

    return _fake_get


# ---------------------------------------------------------------------------
# httpx absent → unavailable
# ---------------------------------------------------------------------------


class TestHttpxAbsent:
    def test_available_false_when_httpx_absent(self, monkeypatch):
        """FetchBackend.available is False when httpx is not importable."""
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
        backend = FetchBackend()
        assert backend.available is False

    def test_fetch_returns_none_when_httpx_absent(self, monkeypatch):
        """fetch() returns None (not an error) when httpx is missing."""
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
        backend = FetchBackend()
        result = backend.fetch("requests", "2.31.0", "session")
        assert result is None

    def test_available_true_when_httpx_present(self):
        """If httpx IS installed, available should be True."""
        # Only run if httpx is actually installed; skip otherwise
        if not importlib.util.find_spec("httpx"):
            pytest.skip("httpx not installed in this environment")
        backend = FetchBackend()
        assert backend.available is True

    def test_httpx_available_helper(self, monkeypatch):
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
        assert _httpx_available() is False

    def test_httpx_available_helper_when_present(self):
        if not importlib.util.find_spec("httpx"):
            pytest.skip("httpx not installed")
        assert _httpx_available() is True


# ---------------------------------------------------------------------------
# httpx present + mock HTTP → happy-path tests
# ---------------------------------------------------------------------------


class TestFetchNpmMocked:
    """Tests for npm fetch path using mocked httpx."""

    def _requires_httpx(self):
        if not importlib.util.find_spec("httpx"):
            pytest.skip("httpx not installed — mocked httpx test requires real import")

    def test_npm_llms_txt_returned(self, monkeypatch):
        self._requires_httpx()
        import httpx

        npm_meta = json.dumps({
            "homepage": "https://reactjs.org",
            "repository": {"url": "git+https://github.com/facebook/react.git"},
        }).encode()

        responses = {
            "https://registry.npmjs.org/react/latest": npm_meta,
            "https://reactjs.org/llms.txt": b"# React llms docs\n\nHooks, components.",
        }
        monkeypatch.setattr(httpx, "get", _mock_httpx_get(responses))

        backend = FetchBackend()
        result = backend.fetch("react", "18.2.0", "hooks")

        assert result is not None
        assert result.source == "fetch"
        assert "llms" in result.content.lower() or "React" in result.content
        assert result.metadata.get("fetch_source") == "llms.txt"

    def test_npm_github_raw_fallback(self, monkeypatch):
        self._requires_httpx()
        import httpx

        npm_meta = json.dumps({
            "homepage": "https://expressjs.com",
            "repository": {"url": "git+https://github.com/expressjs/express.git"},
        }).encode()

        # llms.txt not found → fall through to GitHub raw README
        responses = {
            "https://registry.npmjs.org/express/latest": npm_meta,
            "https://expressjs.com/llms.txt": None,  # 404
            "https://raw.githubusercontent.com/expressjs/express/v4.18.2/llms.txt": None,
            "https://raw.githubusercontent.com/expressjs/express/v4.18.2/README.md": b"# Express\n\nFast web framework.",
        }
        monkeypatch.setattr(httpx, "get", _mock_httpx_get(responses))

        backend = FetchBackend()
        result = backend.fetch("express", "4.18.2", "routing")

        assert result is not None
        assert result.source == "fetch"
        assert "Express" in result.content
        assert result.metadata.get("fetch_source") == "github-raw"

    def test_npm_all_miss_returns_none(self, monkeypatch):
        self._requires_httpx()
        import httpx

        # Everything returns 404
        monkeypatch.setattr(httpx, "get", _mock_httpx_get({}))

        backend = FetchBackend()
        result = backend.fetch("totally-unknown-pkg", "1.0.0", "topic")
        assert result is None


class TestFetchPythonMocked:
    """Tests for pip fetch path using mocked httpx."""

    def _requires_httpx(self):
        if not importlib.util.find_spec("httpx"):
            pytest.skip("httpx not installed — mocked httpx test requires real import")

    def test_pip_llms_txt_returned(self, monkeypatch):
        self._requires_httpx()
        import httpx

        pypi_meta = json.dumps({
            "info": {
                "project_urls": {"Documentation": "https://docs.example.com"},
                "home_page": "https://example.com",
            }
        }).encode()

        responses = {
            "https://pypi.org/pypi/mylib/json": pypi_meta,
            "https://docs.example.com/llms.txt": b"# mylib llms docs\n\nUsage.",
        }
        monkeypatch.setattr(httpx, "get", _mock_httpx_get(responses))

        backend = FetchBackend()
        result = backend.fetch("mylib", "1.0.0", "usage")

        assert result is not None
        assert result.source == "fetch"
        assert result.metadata.get("fetch_source") == "llms.txt"

    def test_pip_github_raw_fallback(self, monkeypatch):
        self._requires_httpx()
        import httpx

        pypi_meta = json.dumps({
            "info": {
                "project_urls": {"Source": "https://github.com/myorg/mylib"},
                "home_page": "https://github.com/myorg/mylib",
            }
        }).encode()

        responses = {
            "https://pypi.org/pypi/mylib/json": pypi_meta,
            "https://github.com/myorg/mylib/llms.txt": None,
            "https://raw.githubusercontent.com/myorg/mylib/v1.0.0/llms.txt": None,
            "https://raw.githubusercontent.com/myorg/mylib/v1.0.0/README.md": b"# mylib\n\nA Python library.",
        }
        monkeypatch.setattr(httpx, "get", _mock_httpx_get(responses))

        backend = FetchBackend()
        result = backend.fetch("mylib", "1.0.0", "api")

        assert result is not None
        assert result.source == "fetch"
        assert "mylib" in result.content
        assert result.metadata.get("fetch_source") == "github-raw"

    def test_pip_all_miss_returns_none(self, monkeypatch):
        self._requires_httpx()
        import httpx

        monkeypatch.setattr(httpx, "get", _mock_httpx_get({}))

        backend = FetchBackend()
        result = backend.fetch("completely-unknown-pkg-xyz", "1.0.0", "api")
        assert result is None


# ---------------------------------------------------------------------------
# Offline / timeout degradation
# ---------------------------------------------------------------------------


class TestOfflineDegradation:
    def test_fetch_returns_none_when_offline(self, monkeypatch):
        """When offline, FetchBackend returns None without raising."""
        if not importlib.util.find_spec("httpx"):
            pytest.skip("httpx not installed")

        import httpx

        def _raise_connect(*args, **kwargs):
            raise httpx.ConnectError("Network unreachable")

        monkeypatch.setattr(httpx, "get", _raise_connect)

        backend = FetchBackend()
        result = backend.fetch("requests", "2.31.0", "session")
        assert result is None

    def test_fetch_returns_none_on_timeout(self, monkeypatch):
        """Timeout causes FetchBackend to return None, not raise."""
        if not importlib.util.find_spec("httpx"):
            pytest.skip("httpx not installed")

        import httpx

        def _raise_timeout(*args, **kwargs):
            raise httpx.TimeoutException("Timed out")

        monkeypatch.setattr(httpx, "get", _raise_timeout)

        backend = FetchBackend()
        result = backend.fetch("requests", "2.31.0", "session")
        assert result is None

    def test_get_helper_returns_none_on_exception(self, monkeypatch):
        """_get() helper returns None on any exception."""
        if not importlib.util.find_spec("httpx"):
            pytest.skip("httpx not installed")

        import httpx

        monkeypatch.setattr(httpx, "get", lambda *a, **kw: (_ for _ in ()).throw(OSError("no network")))

        result = _get("https://example.com/llms.txt")
        assert result is None


# ---------------------------------------------------------------------------
# Never raises contract
# ---------------------------------------------------------------------------


class TestNeverRaises:
    def test_fetch_never_raises_httpx_absent(self, monkeypatch):
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
        backend = FetchBackend()
        # Should not raise under any circumstances
        result = backend.fetch("anything", "1.0.0", "topic")
        assert result is None

    def test_available_never_raises(self, monkeypatch):
        """available property never raises."""
        def _raise(*args, **kwargs):
            raise Exception("broken")
        monkeypatch.setattr(importlib.util, "find_spec", _raise)
        backend = FetchBackend()
        # Should return False, not raise
        try:
            available = backend.available
            assert available is False
        except Exception:
            pytest.fail("FetchBackend.available raised an exception")


# ---------------------------------------------------------------------------
# Resolver integration: fetch skipped when httpx absent
# ---------------------------------------------------------------------------


class TestResolverSkipsFetchWhenHttpxAbsent:
    def test_resolver_skips_fetch_backend_when_httpx_absent(self, tmp_path, monkeypatch):
        """When httpx is absent, the resolver skips 'fetch' silently."""
        from cc.core.docs_resolver import resolve_docs, register_backend, DocResult

        monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

        class _FallbackBackend:
            name = "_test_fallback_fetch"
            available = True

            def fetch(self, pkg, version, topic):
                return DocResult(pkg, version, topic, "fallback content", "_test_fallback_fetch")

        register_backend("_test_fallback_fetch", _FallbackBackend())

        result = resolve_docs(
            "somepkg", "1.0.0", "topic",
            source_order=["fetch", "_test_fallback_fetch"],
            cache_dir=tmp_path,
        )
        assert result is not None
        assert result.source == "_test_fallback_fetch"
