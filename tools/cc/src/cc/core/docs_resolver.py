"""Docs resolver: version detection (A2) + SourceBackend seam + layered lookup (A3).

Architecture
------------
- detect_version(pkg, lang)  → VersionResult
  Resolves the installed / declared version of a package before any fetch.
  Returns an honest ``exact: bool`` and ``version_source`` explaining the evidence.

- SourceBackend Protocol (mirrors SearchBackend in memory_index.py)
  Every backend satisfies: fetch(pkg, version, topic) → DocResult | None
  and reports whether it is currently available (e.g. httpx absent → unavailable).

- resolve_docs(pkg, lang, topic)  → DocResult | None
  Walks docs.source_order, skips unavailable backends, returns first hit.
  Cache-first: checks docs_cache before calling any backend (A3 wired here).

Pluggability contract (FF6)
---------------------------
To add a new backend (e.g. Context7):
  1. Create a class that implements SourceBackend.
  2. Register it in _BACKEND_REGISTRY with a string key.
  3. Add that key to docs.source_order in config.
  No resolver, cache, or CLI change is required.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Version detection (Task A2)
# ---------------------------------------------------------------------------


@dataclass
class VersionResult:
    """Resolved version for a package, with provenance metadata."""

    name: str
    version: str
    version_source: str  # e.g. "package-lock.json", "importlib.metadata", "pyproject.toml"
    exact: bool  # False when resolved from a semver range or declared constraint


def _detect_js_version(pkg: str, project_root: Path) -> Optional[VersionResult]:
    """Detect an npm package version via lockfile → node_modules → declared range."""

    # 1. package-lock.json (npm)
    lockfile = project_root / "package-lock.json"
    if lockfile.exists():
        try:
            data = json.loads(lockfile.read_text(encoding="utf-8"))
            # v2/v3 lockfile: packages["node_modules/<pkg>"]
            pkg_key = f"node_modules/{pkg}"
            packages = data.get("packages", {})
            if pkg_key in packages:
                ver = packages[pkg_key].get("version")
                if ver:
                    return VersionResult(name=pkg, version=ver, version_source="package-lock.json", exact=True)
            # v1 lockfile: dependencies.<pkg>.version
            deps = data.get("dependencies", {})
            if pkg in deps:
                ver = deps[pkg].get("version")
                if ver:
                    return VersionResult(name=pkg, version=ver, version_source="package-lock.json", exact=True)
        except (json.JSONDecodeError, OSError):
            pass

    # 2. yarn.lock
    yarnlock = project_root / "yarn.lock"
    if yarnlock.exists():
        try:
            content = yarnlock.read_text(encoding="utf-8")
            # Match blocks like: "pkg@^x.y.z":\n  version "x.y.z"
            pattern = rf'"{re.escape(pkg)}@[^"]*":\n(?:[^\n]*\n)*?\s+version "([^"]+)"'
            m = re.search(pattern, content)
            if m:
                return VersionResult(name=pkg, version=m.group(1), version_source="yarn.lock", exact=True)
            # Also handles bare block without quotes: pkg@^x.y.z:
            pattern2 = rf'^{re.escape(pkg)}@[^\n]+:\n(?:[^\n]*\n)*?\s+version "([^"]+)"'
            m2 = re.search(pattern2, content, re.MULTILINE)
            if m2:
                return VersionResult(name=pkg, version=m2.group(1), version_source="yarn.lock", exact=True)
        except OSError:
            pass

    # 3. pnpm-lock.yaml
    pnpmlock = project_root / "pnpm-lock.yaml"
    if pnpmlock.exists():
        try:
            content = pnpmlock.read_text(encoding="utf-8")
            # packages section: /pkg/x.y.z:
            pattern = rf"/{re.escape(pkg)}/([^\s:]+):"
            m = re.search(pattern, content)
            if m:
                return VersionResult(name=pkg, version=m.group(1), version_source="pnpm-lock.yaml", exact=True)
        except OSError:
            pass

    # 4. node_modules/<pkg>/package.json (installed, exact)
    nm_pkg_json = project_root / "node_modules" / pkg / "package.json"
    if nm_pkg_json.exists():
        try:
            data = json.loads(nm_pkg_json.read_text(encoding="utf-8"))
            ver = data.get("version")
            if ver:
                return VersionResult(name=pkg, version=ver, version_source="node_modules/package.json", exact=True)
        except (json.JSONDecodeError, OSError):
            pass

    # 5. package.json declared range (not exact)
    pkg_json = project_root / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                if pkg in data.get(section, {}):
                    declared = data[section][pkg]
                    # Strip leading range specifiers: ^, ~, >=, <=, >, <, =
                    cleaned = re.sub(r"^[~^>=<v ]+", "", declared)
                    return VersionResult(
                        name=pkg,
                        version=cleaned or declared,
                        version_source="package.json (declared range)",
                        exact=False,
                    )
        except (json.JSONDecodeError, OSError):
            pass

    return None


def _detect_python_version(pkg: str, project_root: Path) -> Optional[VersionResult]:
    """Detect a Python package version via importlib.metadata → lockfiles → requirements."""

    # Normalise package name: PEP 503 (hyphens/underscores/dots → single dash)
    def _normalise(name: str) -> str:
        return re.sub(r"[-_.]+", "-", name).lower()

    normalised = _normalise(pkg)

    # 1. importlib.metadata (installed in current env — most reliable, exact)
    try:
        import importlib.metadata as _meta

        version = _meta.version(pkg)
        return VersionResult(name=pkg, version=version, version_source="importlib.metadata", exact=True)
    except Exception:
        # Try normalised name
        try:
            import importlib.metadata as _meta

            version = _meta.version(normalised)
            return VersionResult(name=pkg, version=version, version_source="importlib.metadata", exact=True)
        except Exception:
            pass

    # 2. uv.lock
    uvlock = project_root / "uv.lock"
    if uvlock.exists():
        try:
            content = uvlock.read_text(encoding="utf-8")
            # TOML-ish: [[package]] blocks with name = "pkg" / version = "x.y.z"
            pkg_blocks = re.split(r"\[\[package\]\]", content)
            for block in pkg_blocks:
                name_m = re.search(r'name\s*=\s*"([^"]+)"', block)
                ver_m = re.search(r'version\s*=\s*"([^"]+)"', block)
                if name_m and ver_m and _normalise(name_m.group(1)) == normalised:
                    return VersionResult(name=pkg, version=ver_m.group(1), version_source="uv.lock", exact=True)
        except OSError:
            pass

    # 3. poetry.lock
    poetrylock = project_root / "poetry.lock"
    if poetrylock.exists():
        try:
            content = poetrylock.read_text(encoding="utf-8")
            pkg_blocks = re.split(r"\[\[package\]\]", content)
            for block in pkg_blocks:
                name_m = re.search(r'name\s*=\s*"([^"]+)"', block)
                ver_m = re.search(r'version\s*=\s*"([^"]+)"', block)
                if name_m and ver_m and _normalise(name_m.group(1)) == normalised:
                    return VersionResult(name=pkg, version=ver_m.group(1), version_source="poetry.lock", exact=True)
        except OSError:
            pass

    # 4. pyproject.toml declared constraint (not exact)
    pyproject = project_root / "pyproject.toml"
    if pyproject.exists():
        try:
            content = pyproject.read_text(encoding="utf-8")
            # Match: "pkg>=x.y" or "pkg==x.y" or "pkg~=x.y" etc.
            pattern = rf'"{re.escape(pkg)}([^"]*)"'
            m = re.search(pattern, content, re.IGNORECASE)
            if m:
                constraint = m.group(1).strip()
                # Extract version number from constraint
                ver_m = re.search(r"[\d][^\s,;\"]*", constraint)
                version_str = ver_m.group(0) if ver_m else constraint
                return VersionResult(
                    name=pkg,
                    version=version_str or constraint,
                    version_source="pyproject.toml (declared constraint)",
                    exact=False,
                )
        except OSError:
            pass

    # 5. requirements.txt / requirements*.txt pinned version
    req_files = sorted(project_root.glob("requirements*.txt"))
    for req_file in req_files:
        try:
            for line in req_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Match: pkg==x.y.z  (exact pin only — not ranges)
                m = re.match(rf"^{re.escape(pkg)}\s*==\s*([^\s;#]+)", line, re.IGNORECASE)
                if m:
                    return VersionResult(
                        name=pkg,
                        version=m.group(1),
                        version_source=req_file.name,
                        exact=True,
                    )
                # Range pin (not exact)
                m2 = re.match(rf"^{re.escape(pkg)}\s*([><=~!][^\s;#]+)", line, re.IGNORECASE)
                if m2:
                    constraint = m2.group(1)
                    ver_m = re.search(r"[\d][^\s,;\"]*", constraint)
                    version_str = ver_m.group(0) if ver_m else constraint
                    return VersionResult(
                        name=pkg,
                        version=version_str,
                        version_source=f"{req_file.name} (declared range)",
                        exact=False,
                    )
        except OSError:
            pass

    return None


def detect_version(
    pkg: str,
    lang: str,
    *,
    project_root: Optional[Path] = None,
) -> Optional[VersionResult]:
    """Detect the installed/declared version of a package.

    Args:
        pkg:          Package name (e.g. "react", "requests").
        lang:         Ecosystem: "js" / "javascript" / "npm"  or  "python" / "py" / "pip".
        project_root: Root directory to scan for lockfiles (defaults to cwd).

    Returns:
        VersionResult or None if version cannot be determined.
    """
    root = project_root or Path.cwd()

    lang_norm = lang.lower().strip()
    if lang_norm in ("js", "javascript", "node", "npm", "ts", "typescript"):
        return _detect_js_version(pkg, root)
    if lang_norm in ("python", "py", "pip", "python3"):
        return _detect_python_version(pkg, root)

    _log.warning("docs.detect_version: unknown lang %r for package %r", lang, pkg)
    return None


# ---------------------------------------------------------------------------
# DocResult — the payload returned by backends and the resolver (A3)
# ---------------------------------------------------------------------------


@dataclass
class DocResult:
    """Documentation lookup result."""

    package: str
    version: str
    topic: str
    content: str
    source: str  # Which backend answered (e.g. "local", "fetch", "context7")
    url: Optional[str] = None
    cached: bool = False
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# SourceBackend Protocol — the pluggable seam (A3 / FF6)
# ---------------------------------------------------------------------------


@runtime_checkable
class SourceBackend(Protocol):
    """Interface every documentation source backend must satisfy.

    Implementations:
        LocalBackend   — searches local project / installed docs (Stream-A)
        FetchBackend   — network fetch (Stream-B2, requires httpx extra)
        (future)       — Context7 or other curated source drops in here
    """

    @property
    def name(self) -> str:
        """Short identifier used in docs.source_order (e.g. 'local', 'fetch')."""
        ...

    @property
    def available(self) -> bool:
        """Return False when this backend cannot operate (e.g. missing optional dep).

        The resolver skips unavailable backends without error.
        """
        ...

    def fetch(self, pkg: str, version: str, topic: str) -> Optional[DocResult]:
        """Attempt to retrieve documentation.

        Returns DocResult on success, None on miss.
        Must NEVER raise — return None on any failure.
        """
        ...


# ---------------------------------------------------------------------------
# Built-in backends (Stream-A stubs — full impl in later streams)
# ---------------------------------------------------------------------------


class LocalBackend:
    """Backend that consults locally-available documentation.

    Reads from the installed package on disk — zero network, version-exact.
    Delegates to cc.core.docs_backends.local.LocalBackend.
    """

    name = "local"
    available = True

    def __init__(self, project_root: Optional[Path] = None) -> None:
        self._project_root = project_root
        self._impl: Optional[object] = None

    def _get_impl(self):
        if self._impl is None:
            from cc.core.docs_backends.local import LocalBackend as _Impl
            self._impl = _Impl(project_root=self._project_root)
        return self._impl

    def fetch(self, pkg: str, version: str, topic: str) -> Optional[DocResult]:
        return self._get_impl().fetch(pkg, version, topic)


class FetchBackend:
    """Backend that fetches docs from the network.

    Requires the 'httpx' optional extra.  Reports unavailable when absent so
    the resolver silently skips it — no ImportError propagates to callers.

    Delegates to cc.core.docs_backends.fetch.FetchBackend.
    """

    name = "fetch"

    @property
    def available(self) -> bool:
        try:
            import importlib

            return importlib.util.find_spec("httpx") is not None
        except Exception:
            return False

    def fetch(self, pkg: str, version: str, topic: str) -> Optional[DocResult]:
        if not self.available:
            return None
        from cc.core.docs_backends.fetch import FetchBackend as _Impl
        return _Impl().fetch(pkg, version, topic)


# ---------------------------------------------------------------------------
# Backend registry — single place to add new backends (FF6)
# ---------------------------------------------------------------------------

_BACKEND_REGISTRY: dict[str, SourceBackend] = {
    "local": LocalBackend(),
    "fetch": FetchBackend(),
}


def register_backend(key: str, backend: SourceBackend) -> None:
    """Register a new backend (e.g. from tests or future plugins).

    Args:
        key:     The string that appears in docs.source_order.
        backend: An object satisfying the SourceBackend protocol.
    """
    _BACKEND_REGISTRY[key] = backend


# ---------------------------------------------------------------------------
# Layered resolver (A3)
# ---------------------------------------------------------------------------


def resolve_docs(
    pkg: str,
    version: str,
    topic: str,
    *,
    source_order: Optional[list[str]] = None,
    cache_dir: Optional[Path] = None,
    refresh: bool = False,
) -> Optional[DocResult]:
    """Layered documentation resolver.

    Checks the cache first, then walks source_order backends in order.
    Skips backends that are unavailable (e.g. network fetch without httpx).
    Cache misses / corruption NEVER block — they are best-effort.

    Args:
        pkg:          Package name.
        version:      Resolved version string.
        topic:        Topic / query string.
        source_order: Override backend order (defaults to docs.source_order config).
        cache_dir:    Override cache directory (used in tests).
        refresh:      If True, bypass cache read (still writes on hit).

    Returns:
        DocResult from the first backend that answers, or None.
    """
    from cc.core.docs_cache import cache_get, cache_put
    from cc.core.docs_paths import docs_source_order

    order = source_order if source_order is not None else docs_source_order()

    # Cache-first (skip if refresh=True)
    if not refresh:
        try:
            cached = cache_get(pkg, version, topic, cache_dir=cache_dir)
            if cached is not None:
                cached.cached = True
                return cached
        except Exception:
            _log.debug("docs cache read failed; continuing to backends", exc_info=True)

    # Walk backends
    for key in order:
        backend = _BACKEND_REGISTRY.get(key)
        if backend is None:
            _log.debug("docs resolver: unknown backend %r in source_order — skipping", key)
            continue
        if not backend.available:
            _log.debug("docs resolver: backend %r unavailable — skipping", key)
            continue
        try:
            result = backend.fetch(pkg, version, topic)
        except Exception:
            _log.debug("docs backend %r raised unexpectedly — skipping", key, exc_info=True)
            result = None

        if result is not None:
            result.source = key
            # Write to cache (best-effort)
            try:
                cache_put(pkg, version, topic, result, cache_dir=cache_dir)
            except Exception:
                _log.debug("docs cache write failed; continuing without cache", exc_info=True)
            return result

    return None
