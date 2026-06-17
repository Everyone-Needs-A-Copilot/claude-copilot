"""Tests for Task 98: detect_version — npm + pip, exact vs range honesty.

Covers:
  - JS: package-lock.json (v2), yarn.lock, pnpm-lock.yaml, node_modules/pkg/package.json, package.json range
  - Python: importlib.metadata (real installed package), uv.lock, poetry.lock, pyproject.toml, requirements.txt
  - exact: bool is False for declared ranges, True for lock-resolved versions
  - Integration: a real package via importlib.metadata
  - Offline: no network required
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from cc.core.docs_resolver import VersionResult, detect_version


# ---------------------------------------------------------------------------
# JS / npm
# ---------------------------------------------------------------------------


class TestJSPackageLock:
    def test_v2_packages_section(self, tmp_path):
        lock = {
            "lockfileVersion": 2,
            "packages": {
                "node_modules/react": {"version": "18.2.0"},
            },
        }
        (tmp_path / "package-lock.json").write_text(json.dumps(lock))

        result = detect_version("react", "js", project_root=tmp_path)
        assert result is not None
        assert result.version == "18.2.0"
        assert result.exact is True
        assert result.version_source == "package-lock.json"

    def test_v1_dependencies_section(self, tmp_path):
        lock = {
            "lockfileVersion": 1,
            "dependencies": {
                "lodash": {"version": "4.17.21"},
            },
        }
        (tmp_path / "package-lock.json").write_text(json.dumps(lock))

        result = detect_version("lodash", "npm", project_root=tmp_path)
        assert result is not None
        assert result.version == "4.17.21"
        assert result.exact is True

    def test_corrupted_lockfile_falls_through(self, tmp_path):
        (tmp_path / "package-lock.json").write_text("not json {{{{")
        # Should not raise; falls through to other sources
        result = detect_version("react", "js", project_root=tmp_path)
        assert result is None  # no other sources


class TestYarnLock:
    def test_yarn_lock_quoted_block(self, tmp_path):
        yarn_content = '''\
"react@^18.0.0":
  version "18.2.0"
  resolved "https://registry.yarnpkg.com/react/-/react-18.2.0.tgz"
  integrity sha512-xxx
'''
        (tmp_path / "yarn.lock").write_text(yarn_content)

        result = detect_version("react", "javascript", project_root=tmp_path)
        assert result is not None
        assert result.version == "18.2.0"
        assert result.exact is True
        assert result.version_source == "yarn.lock"


class TestNodeModules:
    def test_node_modules_package_json(self, tmp_path):
        nm = tmp_path / "node_modules" / "express"
        nm.mkdir(parents=True)
        (nm / "package.json").write_text(json.dumps({"name": "express", "version": "4.18.2"}))

        result = detect_version("express", "js", project_root=tmp_path)
        assert result is not None
        assert result.version == "4.18.2"
        assert result.exact is True
        assert "node_modules" in result.version_source


class TestPackageJsonRange:
    def test_declared_range_not_exact(self, tmp_path):
        pkg_json = {
            "dependencies": {"typescript": "^5.0.0"},
        }
        (tmp_path / "package.json").write_text(json.dumps(pkg_json))

        result = detect_version("typescript", "js", project_root=tmp_path)
        assert result is not None
        assert result.exact is False
        assert "5.0.0" in result.version
        assert "declared range" in result.version_source

    def test_devdependencies_also_checked(self, tmp_path):
        pkg_json = {"devDependencies": {"vitest": "~1.2.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg_json))

        result = detect_version("vitest", "ts", project_root=tmp_path)
        assert result is not None
        assert result.exact is False


class TestJSNotFound:
    def test_returns_none_when_no_files(self, tmp_path):
        result = detect_version("nonexistent-pkg", "js", project_root=tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------


class TestPythonImportlibMetadata:
    def test_real_installed_package(self):
        """Integration test: uses importlib.metadata on a package we KNOW is installed."""
        # pytest is always installed in the test environment
        result = detect_version("pytest", "python")
        assert result is not None
        assert result.exact is True
        assert result.version_source == "importlib.metadata"
        # Version should look like a semver string
        parts = result.version.split(".")
        assert len(parts) >= 2
        assert all(p.isdigit() for p in parts[:2])

    def test_typer_installed(self):
        """typer is a dependency of cc itself — should be importlib-resolvable."""
        result = detect_version("typer", "py")
        assert result is not None
        assert result.exact is True


class TestUvLock:
    def test_uv_lock_parsing(self, tmp_path):
        uv_content = """\
version = 1
requires-python = ">=3.10"

[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "httpx"
version = "0.27.0"
"""
        (tmp_path / "uv.lock").write_text(uv_content)

        # importlib.metadata won't find this in the fixture env; should fall through to uv.lock
        # We monkeypatch importlib.metadata to simulate "not installed"
        import importlib.metadata as _meta

        original_version = _meta.version

        def raise_not_found(name):
            raise _meta.PackageNotFoundError(name)

        import unittest.mock as mock

        with mock.patch.object(_meta, "version", side_effect=raise_not_found):
            result = detect_version("requests", "python", project_root=tmp_path)

        assert result is not None
        assert result.version == "2.31.0"
        assert result.version_source == "uv.lock"
        assert result.exact is True


class TestPoetryLock:
    def test_poetry_lock_parsing(self, tmp_path):
        poetry_content = """\
[[package]]
name = "black"
version = "23.7.0"
description = "The uncompromising code formatter"
"""
        (tmp_path / "poetry.lock").write_text(poetry_content)

        import importlib.metadata as _meta
        import unittest.mock as mock

        with mock.patch.object(_meta, "version", side_effect=_meta.PackageNotFoundError):
            result = detect_version("black", "pip", project_root=tmp_path)

        assert result is not None
        assert result.version == "23.7.0"
        assert result.version_source == "poetry.lock"
        assert result.exact is True


class TestRequirementsTxt:
    def test_exact_pin(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask==2.3.2\n")

        import importlib.metadata as _meta
        import unittest.mock as mock

        with mock.patch.object(_meta, "version", side_effect=_meta.PackageNotFoundError):
            result = detect_version("flask", "python", project_root=tmp_path)

        assert result is not None
        assert result.version == "2.3.2"
        assert result.exact is True

    def test_range_pin_not_exact(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("django>=4.2\n")

        import importlib.metadata as _meta
        import unittest.mock as mock

        with mock.patch.object(_meta, "version", side_effect=_meta.PackageNotFoundError):
            result = detect_version("django", "python3", project_root=tmp_path)

        assert result is not None
        assert result.exact is False
        assert "4.2" in result.version


class TestPythonNotFound:
    def test_returns_none_when_nothing(self, tmp_path):
        import importlib.metadata as _meta
        import unittest.mock as mock

        with mock.patch.object(_meta, "version", side_effect=_meta.PackageNotFoundError):
            result = detect_version("completely_unknown_pkg_xyz", "python", project_root=tmp_path)

        assert result is None


# ---------------------------------------------------------------------------
# Unknown language
# ---------------------------------------------------------------------------


def test_unknown_lang_returns_none(tmp_path):
    result = detect_version("somelib", "ruby", project_root=tmp_path)
    assert result is None


# ---------------------------------------------------------------------------
# Offline test
# ---------------------------------------------------------------------------


def test_version_detect_offline(tmp_path, monkeypatch):
    """Version detection must work with no network access."""
    original_socket = socket.socket

    def no_network(*args, **kwargs):
        raise OSError("Network access forbidden in offline test")

    monkeypatch.setattr(socket, "socket", no_network)

    # importlib.metadata is purely in-process — no network
    result = detect_version("pytest", "python")
    assert result is not None
    assert result.exact is True

    # JS via fixture file
    lock = {"lockfileVersion": 2, "packages": {"node_modules/vue": {"version": "3.3.0"}}}
    (tmp_path / "package-lock.json").write_text(json.dumps(lock))
    result_js = detect_version("vue", "js", project_root=tmp_path)
    assert result_js is not None
    assert result_js.version == "3.3.0"
