"""LocalBackend — reads documentation from the installed package on disk.

Search order for each ecosystem:
  npm/JS:  node_modules/<pkg>/llms.txt
           node_modules/<pkg>/README.md  (or readme.md, README.rst, README)
           node_modules/<pkg>/package.json#description
           node_modules/<pkg>/index.d.ts  (first 100 lines)
  pip/Python:
           <site-packages>/<pkg_top_level>/llms.txt
           <dist-info>/METADATA  (contains the long description / README)
           module.__doc__

Design invariants:
  - Zero network.  All I/O is local filesystem reads.
  - Must NEVER raise — return None on any failure.
  - Returns DocResult with source='local' and the exact installed version.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import logging
import re
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)

# Maximum bytes to read from any single file to avoid slurping huge blobs.
_MAX_BYTES = 64 * 1024  # 64 KB


# ---------------------------------------------------------------------------
# Helpers — npm / JS
# ---------------------------------------------------------------------------


def _npm_pkg_dir(pkg: str, project_root: Path) -> Optional[Path]:
    """Return the node_modules/<pkg> directory if it exists."""
    candidate = project_root / "node_modules" / pkg
    if candidate.is_dir():
        return candidate
    return None


def _read_npm_version(pkg_dir: Path) -> Optional[str]:
    """Read the version from node_modules/<pkg>/package.json."""
    import json

    pkg_json = pkg_dir / "package.json"
    if not pkg_json.exists():
        return None
    try:
        data = json.loads(pkg_json.read_bytes()[:_MAX_BYTES])
        return data.get("version")
    except Exception:
        return None


def _read_npm_description(pkg_dir: Path) -> Optional[str]:
    """Read the description from node_modules/<pkg>/package.json."""
    import json

    pkg_json = pkg_dir / "package.json"
    if not pkg_json.exists():
        return None
    try:
        data = json.loads(pkg_json.read_bytes()[:_MAX_BYTES])
        desc = data.get("description", "")
        homepage = data.get("homepage", "")
        return f"{desc}\n\nHomepage: {homepage}".strip() if desc else None
    except Exception:
        return None


def _find_npm_readme(pkg_dir: Path) -> Optional[Path]:
    """Find the first README-like file in the package directory."""
    candidates = [
        "llms.txt",
        "README.md",
        "readme.md",
        "Readme.md",
        "README.rst",
        "readme.rst",
        "README.txt",
        "readme.txt",
        "README",
        "readme",
    ]
    for name in candidates:
        p = pkg_dir / name
        if p.exists() and p.is_file():
            return p
    return None


def _npm_typing_snippet(pkg_dir: Path) -> Optional[str]:
    """Return up to the first 80 lines of the main .d.ts file as a doc snippet."""
    # Try index.d.ts first, then types/ or typings/
    candidates = [
        pkg_dir / "index.d.ts",
        pkg_dir / "dist" / "index.d.ts",
        pkg_dir / "types" / "index.d.ts",
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
                return "\n".join(lines[:80])
            except Exception:
                continue
    return None


def _fetch_npm(pkg: str, version: str, topic: str, project_root: Path):  # → DocResult | None
    """Read npm package docs from node_modules."""
    from cc.core.docs_resolver import DocResult

    pkg_dir = _npm_pkg_dir(pkg, project_root)
    if pkg_dir is None:
        return None

    installed_ver = _read_npm_version(pkg_dir) or version

    # Priority 1: llms.txt or README
    readme_path = _find_npm_readme(pkg_dir)
    if readme_path is not None:
        try:
            content = readme_path.read_text(encoding="utf-8", errors="replace")[:_MAX_BYTES]
            return DocResult(
                package=pkg,
                version=installed_ver,
                topic=topic,
                content=content,
                source="local",
                url=None,
                cached=False,
                metadata={"file": str(readme_path), "ecosystem": "npm"},
            )
        except Exception:
            pass

    # Priority 2: package.json description + typing snippet
    parts: list[str] = []
    desc = _read_npm_description(pkg_dir)
    if desc:
        parts.append(desc)
    snippet = _npm_typing_snippet(pkg_dir)
    if snippet:
        parts.append(f"## Type Definitions (excerpt)\n\n```typescript\n{snippet}\n```")

    if parts:
        return DocResult(
            package=pkg,
            version=installed_ver,
            topic=topic,
            content="\n\n".join(parts),
            source="local",
            url=None,
            cached=False,
            metadata={"ecosystem": "npm", "source_type": "package.json"},
        )

    return None


# ---------------------------------------------------------------------------
# Helpers — pip / Python
# ---------------------------------------------------------------------------


def _normalise_pkg_name(name: str) -> str:
    """PEP 503 normalisation: replace runs of [-_.] with a single hyphen, lowercase."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _find_dist_info(pkg: str) -> Optional[Path]:
    """Return the dist-info directory for the installed package, or None."""
    try:
        files = importlib.metadata.files(pkg)
        if files is None:
            return None
        for fp in files:
            s = str(fp)
            if ".dist-info" in s and s.endswith("METADATA"):
                return fp.locate().parent  # dist-info directory
    except Exception:
        pass
    return None


def _read_dist_metadata(dist_info: Path) -> Optional[str]:
    """Read METADATA from dist-info; extract the long description (the README part)."""
    meta_path = dist_info / "METADATA"
    if not meta_path.exists():
        return None
    try:
        content = meta_path.read_text(encoding="utf-8", errors="replace")[:_MAX_BYTES]
        # The METADATA file is RFC-822 headers followed by a blank line, then the body (README).
        # Find the first double-newline to get the long description.
        if "\n\n" in content:
            headers_raw, _, body = content.partition("\n\n")
            if body.strip():
                return body.strip()
        # Fallback: return header summary fields
        summary = ""
        for line in content.splitlines():
            if line.startswith("Summary:"):
                summary = line[len("Summary:"):].strip()
                break
        return summary or content[:2000]
    except Exception:
        return None


def _find_top_level_package_dir(pkg: str, site_packages: Path) -> Optional[Path]:
    """Try to locate the importable package directory inside site-packages."""
    # Try normalised variations
    candidates = [
        pkg,
        pkg.replace("-", "_"),
        pkg.replace("_", "-"),
        _normalise_pkg_name(pkg).replace("-", "_"),
    ]
    for name in candidates:
        p = site_packages / name
        if p.is_dir():
            return p
    return None


def _find_python_llms_txt(pkg: str, site_packages: Path) -> Optional[Path]:
    """Look for llms.txt in the package directory."""
    pkg_dir = _find_top_level_package_dir(pkg, site_packages)
    if pkg_dir is None:
        return None
    p = pkg_dir / "llms.txt"
    return p if p.exists() else None


def _module_docstring(pkg: str) -> Optional[str]:
    """Import the package (if already available) and return its __doc__."""
    try:
        mod_name = pkg.replace("-", "_")
        spec = importlib.util.find_spec(mod_name)
        if spec is None:
            return None
        # Already in sys.modules? Use cached.
        import sys
        mod = sys.modules.get(mod_name)
        if mod is not None:
            return getattr(mod, "__doc__", None)
        # Try importing without side effects via spec
        mod = importlib.import_module(mod_name)
        return getattr(mod, "__doc__", None)
    except Exception:
        return None


def _get_site_packages() -> Optional[Path]:
    """Return the site-packages path for the current environment."""
    try:
        import site
        sp_dirs = site.getsitepackages()
        for d in sp_dirs:
            p = Path(d)
            if p.exists():
                return p
    except Exception:
        pass
    # Fallback: infer from importlib.metadata
    try:
        files = importlib.metadata.files("pip")
        if files:
            for fp in files:
                if ".dist-info" in str(fp):
                    return fp.locate().parent.parent
    except Exception:
        pass
    return None


def _fetch_python(pkg: str, version: str, topic: str):  # → DocResult | None
    """Read Python package docs from the installed environment."""
    from cc.core.docs_resolver import DocResult

    # 1. Installed version via importlib.metadata (exact)
    try:
        installed_ver = importlib.metadata.version(pkg)
    except Exception:
        try:
            installed_ver = importlib.metadata.version(_normalise_pkg_name(pkg))
        except Exception:
            installed_ver = version

    site_packages = _get_site_packages()

    # Priority 1: llms.txt in the package directory
    if site_packages:
        llms_path = _find_python_llms_txt(pkg, site_packages)
        if llms_path is not None:
            try:
                content = llms_path.read_text(encoding="utf-8", errors="replace")[:_MAX_BYTES]
                return DocResult(
                    package=pkg,
                    version=installed_ver,
                    topic=topic,
                    content=content,
                    source="local",
                    url=None,
                    cached=False,
                    metadata={"file": str(llms_path), "ecosystem": "pip"},
                )
            except Exception:
                pass

    # Priority 2: dist-info METADATA (long description / README)
    dist_info = _find_dist_info(pkg)
    if dist_info is None:
        # Try normalised name
        try:
            dist_info = _find_dist_info(_normalise_pkg_name(pkg))
        except Exception:
            pass

    if dist_info is not None:
        body = _read_dist_metadata(dist_info)
        if body:
            return DocResult(
                package=pkg,
                version=installed_ver,
                topic=topic,
                content=body,
                source="local",
                url=None,
                cached=False,
                metadata={"ecosystem": "pip", "source_type": "dist-info/METADATA"},
            )

    # Priority 3: module __doc__
    doc = _module_docstring(pkg)
    if doc and doc.strip():
        return DocResult(
            package=pkg,
            version=installed_ver,
            topic=topic,
            content=doc.strip(),
            source="local",
            url=None,
            cached=False,
            metadata={"ecosystem": "pip", "source_type": "module.__doc__"},
        )

    return None


# ---------------------------------------------------------------------------
# LocalBackend — replaces the Stream-A stub in docs_resolver.py
# ---------------------------------------------------------------------------


class LocalBackend:
    """Reads documentation from the locally installed package on disk.

    Supports npm (node_modules) and pip (site-packages).
    Zero network.  Returns exact installed version.
    """

    name = "local"
    available = True

    def __init__(self, project_root: Optional[Path] = None) -> None:
        self._project_root = project_root

    def fetch(self, pkg: str, version: str, topic: str):  # → DocResult | None
        """Read docs for *pkg* from the local filesystem.

        Returns DocResult on success, None on miss.
        Never raises.
        """
        try:
            root = self._project_root or Path.cwd()
            # Try npm first if node_modules exists nearby
            pkg_dir = _npm_pkg_dir(pkg, root)
            if pkg_dir is not None:
                result = _fetch_npm(pkg, version, topic, root)
                if result is not None:
                    return result

            # Try Python (works regardless of project_root)
            return _fetch_python(pkg, version, topic)

        except Exception:
            _log.debug("LocalBackend.fetch(%r) raised unexpectedly", pkg, exc_info=True)
            return None
