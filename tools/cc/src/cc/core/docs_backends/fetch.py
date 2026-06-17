"""FetchBackend — network fallback, requires the optional 'httpx' extra.

Resolution order within fetch (for both npm and pip):
  1. llms.txt at the package's canonical URL (if known / discoverable)
  2. GitHub raw content at the resolved version tag  → README.md
  3. PyPI JSON API (pip only) for homepage / docs URL

Design invariants:
  - httpx is imported ONLY lazily inside fetch paths.  Checking for it at
    import time is done via importlib.util.find_spec — no ImportError.
  - Must NEVER raise — return None on any failure, including network errors.
  - Short timeout (8 s) so an offline box does not stall the caller.
  - Returns source='fetch' with the resolved version.
  - If httpx is absent the backend reports available=False and the resolver
    silently skips it.  Core cc stays network-free.
"""

from __future__ import annotations

import importlib.util
import logging
import re
from typing import Optional

_log = logging.getLogger(__name__)

_TIMEOUT = 8.0  # seconds — short to fail fast when offline
_MAX_BYTES = 64 * 1024  # 64 KB — cap response size


def _httpx_available() -> bool:
    """Return True if httpx is importable."""
    try:
        return importlib.util.find_spec("httpx") is not None
    except Exception:
        return False


def _get(url: str) -> Optional[bytes]:
    """GET *url*, return raw bytes on 200 OK, None on any failure.

    Never raises.  Uses a short timeout so offline boxes fail fast.
    """
    try:
        import httpx  # lazy — only reached when httpx IS installed

        resp = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True)
        if resp.status_code == 200:
            return resp.content[:_MAX_BYTES]
        return None
    except Exception:
        _log.debug("FetchBackend._get(%r) failed", url, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# npm / GitHub helpers
# ---------------------------------------------------------------------------

_GITHUB_PKG_RE = re.compile(
    r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
)


def _npm_repo_url(pkg: str) -> Optional[str]:
    """Query the npm registry JSON to get the repository URL.

    Returns the GitHub repo URL or None.  Never raises.
    """
    data_bytes = _get(f"https://registry.npmjs.org/{pkg}/latest")
    if data_bytes is None:
        return None
    try:
        import json

        data = json.loads(data_bytes)
        repo = data.get("repository", {})
        if isinstance(repo, str):
            url = repo
        elif isinstance(repo, dict):
            url = repo.get("url", "")
        else:
            url = ""
        # Strip git+ prefix and .git suffix
        url = re.sub(r"^git\+", "", url)
        url = re.sub(r"\.git$", "", url)
        m = _GITHUB_PKG_RE.search(url)
        return f"https://github.com/{m.group(1)}" if m else None
    except Exception:
        return None


def _npm_homepage(pkg: str) -> Optional[str]:
    """Query the npm registry for a package homepage URL."""
    data_bytes = _get(f"https://registry.npmjs.org/{pkg}/latest")
    if data_bytes is None:
        return None
    try:
        import json

        data = json.loads(data_bytes)
        return data.get("homepage")
    except Exception:
        return None


def _github_raw_readme(owner_repo: str, version: str) -> Optional[str]:
    """Try to fetch README.md from a GitHub repo at the given version tag.

    Tries tags: v{version}, {version}.  Falls back to HEAD (main/master).
    Returns decoded text or None.
    """
    readme_names = ["llms.txt", "README.md", "readme.md", "README.rst"]
    tags = [f"v{version}", version, "main", "master"]

    for tag in tags:
        for name in readme_names:
            url = f"https://raw.githubusercontent.com/{owner_repo}/{tag}/{name}"
            raw = _get(url)
            if raw is not None:
                try:
                    return raw.decode("utf-8", errors="replace")
                except Exception:
                    pass
    return None


def _fetch_npm_docs(pkg: str, version: str, topic: str):  # → DocResult | None
    """Fetch npm package docs via the registry API + GitHub raw."""
    from cc.core.docs_resolver import DocResult

    # Step 1: try npm registry llms.txt (convention: <homepage>/llms.txt)
    homepage = _npm_homepage(pkg)
    if homepage:
        for suffix in ["/llms.txt", "llms.txt"]:
            url = homepage.rstrip("/") + "/" + suffix.lstrip("/")
            raw = _get(url)
            if raw is not None:
                try:
                    content = raw.decode("utf-8", errors="replace")
                    return DocResult(
                        package=pkg,
                        version=version,
                        topic=topic,
                        content=content,
                        source="fetch",
                        url=url,
                        cached=False,
                        metadata={"ecosystem": "npm", "fetch_source": "llms.txt"},
                    )
                except Exception:
                    pass

    # Step 2: GitHub raw README at version tag
    repo_url = _npm_repo_url(pkg)
    if repo_url:
        m = _GITHUB_PKG_RE.search(repo_url)
        if m:
            owner_repo = m.group(1)
            content = _github_raw_readme(owner_repo, version)
            if content:
                return DocResult(
                    package=pkg,
                    version=version,
                    topic=topic,
                    content=content,
                    source="fetch",
                    url=f"https://github.com/{owner_repo}",
                    cached=False,
                    metadata={"ecosystem": "npm", "fetch_source": "github-raw"},
                )

    return None


# ---------------------------------------------------------------------------
# pip / PyPI helpers
# ---------------------------------------------------------------------------


def _pypi_metadata(pkg: str) -> Optional[dict]:
    """Query PyPI JSON API for package metadata. Returns the dict or None."""
    raw = _get(f"https://pypi.org/pypi/{pkg}/json")
    if raw is None:
        return None
    try:
        import json

        return json.loads(raw)
    except Exception:
        return None


def _pypi_homepage(pkg: str) -> Optional[str]:
    """Return the homepage URL from PyPI metadata."""
    meta = _pypi_metadata(pkg)
    if meta is None:
        return None
    info = meta.get("info", {})
    # Try project_urls first
    for key in ("Homepage", "Documentation", "Docs"):
        url = (info.get("project_urls") or {}).get(key)
        if url:
            return url
    return info.get("home_page") or None


def _pypi_project_urls(pkg: str) -> list[str]:
    """Return a list of candidate doc URLs from PyPI metadata."""
    meta = _pypi_metadata(pkg)
    if meta is None:
        return []
    info = meta.get("info", {})
    urls = []
    for key, val in (info.get("project_urls") or {}).items():
        if key.lower() in ("documentation", "docs", "homepage"):
            urls.append(val)
    if info.get("home_page"):
        urls.append(info["home_page"])
    return urls


def _pypi_github_repo(pkg: str) -> Optional[str]:
    """Try to find a GitHub repo URL from PyPI metadata."""
    meta = _pypi_metadata(pkg)
    if meta is None:
        return None
    info = meta.get("info", {})
    for val in (info.get("project_urls") or {}).values():
        m = _GITHUB_PKG_RE.search(val or "")
        if m:
            return f"https://github.com/{m.group(1)}"
    home = info.get("home_page") or ""
    m = _GITHUB_PKG_RE.search(home)
    return f"https://github.com/{m.group(1)}" if m else None


def _fetch_python_docs(pkg: str, version: str, topic: str):  # → DocResult | None
    """Fetch Python package docs: llms.txt → GitHub raw → docs site."""
    from cc.core.docs_resolver import DocResult

    # Step 1: try llms.txt from docs site / homepage
    for doc_url in _pypi_project_urls(pkg):
        url = doc_url.rstrip("/") + "/llms.txt"
        raw = _get(url)
        if raw is not None:
            try:
                content = raw.decode("utf-8", errors="replace")
                return DocResult(
                    package=pkg,
                    version=version,
                    topic=topic,
                    content=content,
                    source="fetch",
                    url=url,
                    cached=False,
                    metadata={"ecosystem": "pip", "fetch_source": "llms.txt"},
                )
            except Exception:
                pass

    # Step 2: GitHub raw README at version tag
    repo_url = _pypi_github_repo(pkg)
    if repo_url:
        m = _GITHUB_PKG_RE.search(repo_url)
        if m:
            owner_repo = m.group(1)
            content = _github_raw_readme(owner_repo, version)
            if content:
                return DocResult(
                    package=pkg,
                    version=version,
                    topic=topic,
                    content=content,
                    source="fetch",
                    url=f"https://github.com/{owner_repo}",
                    cached=False,
                    metadata={"ecosystem": "pip", "fetch_source": "github-raw"},
                )

    return None


# ---------------------------------------------------------------------------
# FetchBackend — replaces the Stream-A stub in docs_resolver.py
# ---------------------------------------------------------------------------


class FetchBackend:
    """Fetches package documentation from the network.

    Requires the optional 'httpx' extra.  When httpx is not installed,
    ``available`` is False and the resolver silently skips this backend —
    core cc stays completely network-free.

    When httpx IS available but the machine is offline, fetch operations
    fail fast (short timeout) and return None so the resolver moves on.
    """

    name = "fetch"

    @property
    def available(self) -> bool:
        """False when httpx is not installed; True otherwise."""
        return _httpx_available()

    def fetch(self, pkg: str, version: str, topic: str):  # → DocResult | None
        """Fetch docs for *pkg* from the network.

        Returns DocResult on success, None on miss or any failure.
        Never raises.
        """
        if not self.available:
            return None

        try:
            # Try npm first (checking for package.json-like metadata from registry)
            # then pip.  We detect ecosystem by trying npm registry and PyPI in sequence.
            result = _fetch_npm_docs(pkg, version, topic)
            if result is not None:
                return result
            return _fetch_python_docs(pkg, version, topic)
        except Exception:
            _log.debug("FetchBackend.fetch(%r) raised unexpectedly", pkg, exc_info=True)
            return None
