"""Per-repo verdict caching for the ~70-repo fast-mode sweep.

`HARNESS-DESIGN.md` §7.2: "Per-repo verdicts are cached in
`$CC_MACHINE_ROOT/conformance-cache.json`, keyed on a fingerprint of (git
HEAD sha, dirty bit, and (mtime_ns, size) of each of the 13 dimension
paths). Unchanged repos reuse their verdict. Typical incremental run
touches 2-5 repos. `--no-cache` for CI, and the cache is keyed on the
harness's own version so a check change invalidates everything."

This module computes that fingerprint and persists/retrieves cached
`CheckResult`s by (repo, fingerprint). It does NOT decide what "the 13
dimension paths" are for a given repo -- that is Layer 3's (WP-4's)
knowledge; this module accepts whatever relative paths the caller supplies.

Cache location honors `CC_MACHINE_ROOT` (via
`cc.core.config_paths.machine_config_path()`'s directory) so the existing
`tests/conftest.py::_isolate_machine_config` autouse fixture already
isolates it in every other test in the suite -- conformance tests get the
same isolation for free by inheriting that fixture (pytest conftest
nesting), and never need to know the real path exists.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from cc.core.config_paths import machine_config_path
from cc.core.conformance.types import CheckResult

# Bump whenever a change to types.py/registry.py/report.py could alter what
# a cached CheckResult MEANS (e.g. a new required field, a redefined
# severity). A stale cache under an old version is simply never read --
# "the cache is keyed on the harness's own version so a check change
# invalidates everything" (HARNESS-DESIGN.md §7.2).
CACHE_SCHEMA_VERSION = "1"

CACHE_FILE_NAME = "conformance-cache.json"


def default_cache_path() -> Path:
    """`$CC_MACHINE_ROOT/conformance-cache.json` (or the real
    `~/.claude/cc/conformance-cache.json` when `CC_MACHINE_ROOT` is unset)."""

    return machine_config_path().parent / CACHE_FILE_NAME


@dataclass(frozen=True)
class RepoFingerprint:
    """A stable, order-independent identity for "has this repo's
    conformance-relevant state changed since it was last checked".

    `git_head` is `None` for a repo with no commits yet (or not a git root
    at all -- callers pass `None` in that case rather than raising).
    `dirty` is `True` when `git status --porcelain` is non-empty. `paths`
    is a tuple of `(relative_path, mtime_ns, size)` triples, one per
    dimension path the caller cares about, sorted by relative path so
    fingerprint computation is deterministic regardless of caller iteration
    order.
    """

    git_head: str | None
    dirty: bool
    paths: tuple[tuple[str, int, int], ...]

    def digest(self) -> str:
        canonical = json.dumps(
            {
                "git_head": self.git_head,
                "dirty": self.dirty,
                "paths": [list(entry) for entry in self.paths],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _git_head(repo: Path) -> str | None:
    result = subprocess.run(
        ("git", "rev-parse", "--verify", "HEAD^{commit}"),
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=10.0,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _git_dirty(repo: Path) -> bool:
    result = subprocess.run(
        ("git", "status", "--porcelain"),
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=10.0,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def compute_repo_fingerprint(
    repo: Path,
    dimension_paths: Iterable[str],
) -> RepoFingerprint:
    """Fingerprint one repo: its git HEAD, dirty bit, and the (mtime_ns,
    size) of each caller-supplied relative path that exists. A missing
    path contributes `(-1, -1)` rather than being omitted, so "the file was
    deleted" is itself a fingerprint change (an omission would silently
    hide exactly that case)."""

    entries: list[tuple[str, int, int]] = []
    for relative in sorted(set(dimension_paths)):
        target = repo / relative
        try:
            stat = target.stat()
            entries.append((relative, stat.st_mtime_ns, stat.st_size))
        except OSError:
            entries.append((relative, -1, -1))

    return RepoFingerprint(
        git_head=_git_head(repo),
        dirty=_git_dirty(repo),
        paths=tuple(entries),
    )


@dataclass(frozen=True)
class CacheEntry:
    fingerprint: str
    results: tuple[CheckResult, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "results": [result.as_dict() for result in self.results],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CacheEntry":
        return cls(
            fingerprint=str(data["fingerprint"]),
            results=tuple(
                CheckResult.from_dict(entry) for entry in data.get("results", [])
            ),
        )


class ConformanceCache:
    """Load/save a `{repo -> CacheEntry}` map. `get()` returns `None` on any
    miss (unknown repo, or a fingerprint mismatch) -- callers always treat a
    miss as "recompute", never as an error.

    `ConformanceCache.disabled()` returns a cache that always misses and
    never persists -- the implementation of `--full`/`--no-cache`, so
    orchestration code (WP-4's `sweep.py`) can use one `ConformanceCache`
    object unconditionally rather than branching on whether caching is on.
    """

    def __init__(self, path: Path, *, enabled: bool = True) -> None:
        self._path = path
        self._enabled = enabled
        self._entries: dict[str, CacheEntry] = {}
        self._version: str | None = None
        if enabled:
            self._load()

    @classmethod
    def disabled(cls) -> "ConformanceCache":
        return cls(Path(), enabled=False)

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Missing or corrupt cache: silently discarded, full recompute
            # (HARNESS-DESIGN.md §10 "Cache is stale or corrupt" row).
            return
        if not isinstance(raw, dict) or raw.get("schema_version") != CACHE_SCHEMA_VERSION:
            return
        entries_raw = raw.get("entries", {})
        if not isinstance(entries_raw, dict):
            return
        loaded: dict[str, CacheEntry] = {}
        for repo, entry_raw in entries_raw.items():
            try:
                loaded[repo] = CacheEntry.from_dict(entry_raw)
            except (KeyError, ValueError, TypeError):
                # One corrupt entry must not discard every other repo's
                # cached verdict.
                continue
        self._entries = loaded

    def get(
        self, repo: Path, fingerprint: RepoFingerprint
    ) -> tuple[CheckResult, ...] | None:
        if not self._enabled:
            return None
        entry = self._entries.get(str(repo))
        if entry is None or entry.fingerprint != fingerprint.digest():
            return None
        return entry.results

    def put(
        self,
        repo: Path,
        fingerprint: RepoFingerprint,
        results: Iterable[CheckResult],
    ) -> None:
        if not self._enabled:
            return
        self._entries[str(repo)] = CacheEntry(
            fingerprint=fingerprint.digest(), results=tuple(results)
        )

    def save(self) -> None:
        if not self._enabled:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "entries": {
                repo: entry.as_dict() for repo, entry in self._entries.items()
            },
        }
        self._path.write_text(
            json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8"
        )

    def __len__(self) -> int:
        return len(self._entries)


__all__ = [
    "CACHE_FILE_NAME",
    "CACHE_SCHEMA_VERSION",
    "CacheEntry",
    "ConformanceCache",
    "RepoFingerprint",
    "compute_repo_fingerprint",
    "default_cache_path",
]
