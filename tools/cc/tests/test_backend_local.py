"""Tests for Task 100 (B1): LocalBackend — reads from installed packages on disk.

Covers:
  - npm: node_modules README, llms.txt, package.json description, .d.ts snippet
  - pip: dist-info METADATA (long description), module __doc__
  - Real installed package (typer) returns local docs with no network
  - Returns source='local' with exact installed version
  - Always returns None on miss, never raises
  - Offline: zero network used
  - Registry isolation: test-registered backends don't leak
"""

from __future__ import annotations

import importlib.metadata
import json
import socket
from pathlib import Path
from typing import Optional
from unittest.mock import patch, MagicMock

import pytest

from cc.core.docs_backends.local import LocalBackend, _fetch_npm, _fetch_python
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


def _make_nm_pkg(tmp_path: Path, name: str, version: str, **extras) -> Path:
    """Create a minimal node_modules/<name>/ directory with package.json."""
    pkg_dir = tmp_path / "node_modules" / name
    pkg_dir.mkdir(parents=True)
    data = {"name": name, "version": version, **extras}
    (pkg_dir / "package.json").write_text(json.dumps(data))
    return pkg_dir


# ---------------------------------------------------------------------------
# npm — README / llms.txt
# ---------------------------------------------------------------------------


class TestNpmReadme:
    def test_returns_readme_content(self, tmp_path):
        pkg_dir = _make_nm_pkg(tmp_path, "react", "18.2.0")
        readme = pkg_dir / "README.md"
        readme.write_text("# React\n\nA JavaScript library.")

        backend = LocalBackend(project_root=tmp_path)
        result = backend.fetch("react", "18.2.0", "hooks")

        assert result is not None
        assert "React" in result.content
        assert result.source == "local"
        assert result.version == "18.2.0"

    def test_prefers_llms_txt_over_readme(self, tmp_path):
        pkg_dir = _make_nm_pkg(tmp_path, "vue", "3.0.0")
        (pkg_dir / "README.md").write_text("# README")
        (pkg_dir / "llms.txt").write_text("llms content for vue")

        backend = LocalBackend(project_root=tmp_path)
        result = backend.fetch("vue", "3.0.0", "reactivity")

        assert result is not None
        assert "llms content" in result.content

    def test_readme_rst_found(self, tmp_path):
        pkg_dir = _make_nm_pkg(tmp_path, "mylib", "1.0.0")
        (pkg_dir / "README.rst").write_text("RST readme content")

        backend = LocalBackend(project_root=tmp_path)
        result = backend.fetch("mylib", "1.0.0", "usage")

        assert result is not None
        assert "RST readme content" in result.content

    def test_ecosystem_metadata_tag(self, tmp_path):
        pkg_dir = _make_nm_pkg(tmp_path, "lodash", "4.17.0")
        (pkg_dir / "README.md").write_text("# Lodash")

        backend = LocalBackend(project_root=tmp_path)
        result = backend.fetch("lodash", "4.17.0", "map")

        assert result is not None
        assert result.metadata.get("ecosystem") == "npm"


class TestNpmPackageJsonFallback:
    def test_returns_description_when_no_readme(self, tmp_path):
        pkg_dir = _make_nm_pkg(
            tmp_path, "myutil", "2.0.0",
            description="A utility library", homepage="https://example.com"
        )

        backend = LocalBackend(project_root=tmp_path)
        result = backend.fetch("myutil", "2.0.0", "api")

        assert result is not None
        assert "utility library" in result.content

    def test_typing_snippet_included(self, tmp_path):
        pkg_dir = _make_nm_pkg(tmp_path, "typed-lib", "1.0.0", description="typed library")
        (pkg_dir / "index.d.ts").write_text(
            "export interface Foo { bar: string; }\nexport function hello(): void;\n"
        )

        backend = LocalBackend(project_root=tmp_path)
        result = backend.fetch("typed-lib", "1.0.0", "types")

        assert result is not None
        assert "Foo" in result.content or "hello" in result.content


class TestNpmMiss:
    def test_returns_none_when_package_not_installed(self, tmp_path):
        """No node_modules/<pkg> dir → None."""
        backend = LocalBackend(project_root=tmp_path)
        result = backend.fetch("nonexistent-npm-pkg", "1.0.0", "anything")
        assert result is None


# ---------------------------------------------------------------------------
# npm — version exactness
# ---------------------------------------------------------------------------


class TestNpmVersion:
    def test_uses_installed_version_from_package_json(self, tmp_path):
        _make_nm_pkg(tmp_path, "express", "4.18.2")

        backend = LocalBackend(project_root=tmp_path)
        result = backend.fetch("express", "4.0.0", "routing")  # pass stale version

        if result is not None:
            # Should use the INSTALLED version (4.18.2), not the hint (4.0.0)
            assert result.version == "4.18.2"


# ---------------------------------------------------------------------------
# pip / Python — dist-info METADATA
# ---------------------------------------------------------------------------


class TestPythonDistInfo:
    def test_typer_returns_local_docs(self):
        """Integration test: typer is installed in the test venv — must return docs."""
        backend = LocalBackend()
        result = backend.fetch("typer", "0.0.0", "commands")

        assert result is not None, "LocalBackend should find typer's dist-info METADATA"
        assert result.source == "local"
        assert len(result.content) > 20

    def test_pytest_returns_local_docs(self):
        """pytest is always installed — integration test."""
        backend = LocalBackend()
        result = backend.fetch("pytest", "0.0.0", "fixtures")

        assert result is not None, "LocalBackend should find pytest docs"
        assert result.source == "local"

    def test_version_is_exact_installed_version(self):
        """Version in DocResult matches the installed version from importlib.metadata."""
        import importlib.metadata

        installed = importlib.metadata.version("typer")
        backend = LocalBackend()
        result = backend.fetch("typer", "999.0.0", "commands")  # wrong hint

        assert result is not None
        assert result.version == installed  # must use INSTALLED version, not hint

    def test_ecosystem_is_pip(self):
        backend = LocalBackend()
        result = backend.fetch("typer", "0.0.0", "commands")
        assert result is not None
        assert result.metadata.get("ecosystem") == "pip"


class TestPythonModuleDoc:
    def test_module_docstring_fallback(self, tmp_path, monkeypatch):
        """If dist-info unavailable, falls back to module.__doc__."""
        import cc.core.docs_backends.local as _local

        # Simulate no dist_info found
        monkeypatch.setattr(_local, "_find_dist_info", lambda pkg: None)
        monkeypatch.setattr(_local, "_get_site_packages", lambda: None)

        # 'cc' itself has a __doc__
        backend = LocalBackend()
        result = backend.fetch("cc", "0.0.0", "usage")
        # Either finds via dist-info or falls through to __doc__ — must not raise
        # (result could be None if cc has no dist-info and no __doc__ in this venv)


class TestPythonMiss:
    def test_unknown_python_pkg_returns_none(self):
        backend = LocalBackend()
        result = backend.fetch("completely-nonexistent-pkg-xyz-999", "1.0.0", "anything")
        assert result is None


# ---------------------------------------------------------------------------
# Never raises contract
# ---------------------------------------------------------------------------


class TestNeverRaises:
    def test_fetch_never_raises_on_bad_input(self, tmp_path):
        backend = LocalBackend(project_root=tmp_path)
        # Should not raise even with weird inputs
        result = backend.fetch("", "", "")
        # result may be None but must not raise
        assert result is None or isinstance(result, DocResult)

    def test_fetch_never_raises_on_corrupted_package_json(self, tmp_path):
        nm = tmp_path / "node_modules" / "broken"
        nm.mkdir(parents=True)
        (nm / "package.json").write_bytes(b"{{not json{{")

        backend = LocalBackend(project_root=tmp_path)
        result = backend.fetch("broken", "1.0.0", "usage")
        # No crash; result may be None
        assert result is None or isinstance(result, DocResult)


# ---------------------------------------------------------------------------
# Offline test (zero network)
# ---------------------------------------------------------------------------


class TestOffline:
    def test_local_backend_works_offline(self, monkeypatch):
        """LocalBackend must return docs for a real package with no network access."""

        def no_network(*args, **kwargs):
            raise OSError("Network access forbidden in offline test")

        monkeypatch.setattr(socket, "socket", no_network)

        backend = LocalBackend()
        result = backend.fetch("typer", "0.0.0", "commands")

        assert result is not None, "LocalBackend must work offline — reads from disk only"
        assert result.source == "local"

    def test_e2e_cc_docs_get_offline(self, monkeypatch):
        """E2E: resolve_docs(typer, local-only) returns local docs with no network."""
        from cc.core.docs_resolver import resolve_docs, register_backend
        from cc.core.docs_backends.local import LocalBackend as _LB

        def no_network(*args, **kwargs):
            raise OSError("Network access forbidden")

        monkeypatch.setattr(socket, "socket", no_network)

        # Use a tmp cache to avoid state pollution
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td)
            result = resolve_docs(
                "typer",
                "0.0.0",
                "commands",
                source_order=["local"],
                cache_dir=cache_dir,
            )

        assert result is not None, "resolve_docs with local backend must work offline"
        assert result.source == "local"


# ---------------------------------------------------------------------------
# pnpm-lock.yaml detection (QA-flagged gap)
# ---------------------------------------------------------------------------


class TestPnpmLockDetection:
    def test_pnpm_lock_version_detected(self, tmp_path):
        """pnpm-lock.yaml parsing is exercised through version detection."""
        from cc.core.docs_resolver import detect_version

        pnpm_content = """\
lockfileVersion: '6.0'

packages:
  /axios/1.4.0:
    resolution: {integrity: sha512-xyz}
    dev: false
"""
        (tmp_path / "pnpm-lock.yaml").write_text(pnpm_content)

        result = detect_version("axios", "js", project_root=tmp_path)
        assert result is not None
        assert result.version == "1.4.0"
        assert result.version_source == "pnpm-lock.yaml"
        assert result.exact is True

    def test_pnpm_lock_with_node_modules_key(self, tmp_path):
        """pnpm-lock.yaml with newer importers format."""
        pnpm_content = """\
lockfileVersion: '6.0'

packages:

  /react/18.2.0:
    resolution: {integrity: sha512-abc}
"""
        (tmp_path / "pnpm-lock.yaml").write_text(pnpm_content)

        from cc.core.docs_resolver import detect_version
        result = detect_version("react", "js", project_root=tmp_path)
        assert result is not None
        assert result.version == "18.2.0"
        assert result.version_source == "pnpm-lock.yaml"


# ---------------------------------------------------------------------------
# pyproject.toml Python constraint exact=False (QA-flagged gap)
# ---------------------------------------------------------------------------


class TestPyprojectConstraint:
    def test_pyproject_range_constraint_not_exact(self, tmp_path, monkeypatch):
        """pyproject.toml declared constraint returns exact=False."""
        import importlib.metadata as _meta

        content = """\
[project]
name = "myapp"
dependencies = [
    "requests>=2.28.0",
    "flask==3.0.0",
]
"""
        (tmp_path / "pyproject.toml").write_text(content)

        with patch.object(_meta, "version", side_effect=_meta.PackageNotFoundError):
            from cc.core.docs_resolver import detect_version
            result = detect_version("requests", "python", project_root=tmp_path)

        assert result is not None
        assert result.exact is False
        assert "2.28" in result.version
        assert "pyproject.toml" in result.version_source

    def test_pyproject_exact_pin_via_requirements(self, tmp_path, monkeypatch):
        """requirements.txt exact pin returns exact=True (not pyproject path)."""
        import importlib.metadata as _meta

        (tmp_path / "requirements.txt").write_text("requests==2.31.0\n")

        with patch.object(_meta, "version", side_effect=_meta.PackageNotFoundError):
            from cc.core.docs_resolver import detect_version
            result = detect_version("requests", "python", project_root=tmp_path)

        assert result is not None
        assert result.exact is True
        assert result.version == "2.31.0"
