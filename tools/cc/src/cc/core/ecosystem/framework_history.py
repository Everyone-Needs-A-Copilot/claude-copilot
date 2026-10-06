"""Every version the framework has ever committed for the paths it installs.

An update must refuse to overwrite project content it does not own. But a
release that starts managing a path the project already holds as an *older
framework copy* (the lock never recorded it, typically because an earlier
release shipped the file without tracking it) is not a collision: the bytes on
disk are framework content, and replacing them with the current version is the
update. This module answers "has the framework ever committed exactly these
bytes at this path?" so the update boundary can tell the two apart.

The answer comes from the framework's own Git history, captured in two ways:

- An installed snapshot carries `.framework-history.json`, written by
  `scripts/install-framework-snapshot.py` from the source repository at
  install time (snapshots have no `.git`).
- A development checkout has no marker and is read from Git directly.

Neither source available means an empty history, which keeps the original
strict behaviour: every unrecorded, differing file is a conflict.

`scripts/install-framework-snapshot.py` carries a standard-library copy of
`collect_history()` because it runs before any cc environment exists; keep the
two in step.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Mapping

HISTORY_MARKER = ".framework-history.json"
HISTORY_SCHEMA_VERSION = 1
# The paths a project install copies from the framework.
HISTORY_PATHSPECS: tuple[str, ...] = (
    ".claude/agents",
    ".claude/commands",
    ".claude/fitness-check.sh",
    ".claude/hooks/copilot-hook.sh",
)
_NULL_BLOB = "0" * 40


def collect_history(repo: Path, commit: str = "HEAD") -> dict[str, list[str]]:
    """Map each framework-installed path to the sha256 of every committed version."""
    log = subprocess.run(
        (
            "git", "-C", str(repo), "log", "--format=", "--raw", "--no-abbrev",
            "--no-renames", commit, "--", *HISTORY_PATHSPECS,
        ),
        check=True, capture_output=True, text=True, timeout=120,
    ).stdout
    blobs: dict[str, set[str]] = {}
    for line in log.splitlines():
        if not line.startswith(":") or "\t" not in line:
            continue
        meta, path = line.split("\t", 1)
        new_blob = meta.split()[3]
        if new_blob != _NULL_BLOB:
            blobs.setdefault(path, set()).add(new_blob)
    unique = sorted({blob for ids in blobs.values() for blob in ids})
    digests: dict[str, str] = {}
    if unique:
        batch = subprocess.run(
            ("git", "-C", str(repo), "cat-file", "--batch"),
            input="".join(f"{blob}\n" for blob in unique).encode("ascii"),
            check=True, capture_output=True, timeout=120,
        ).stdout
        offset = 0
        for blob in unique:
            header_end = batch.index(b"\n", offset)
            size = int(batch[offset:header_end].split()[2])
            start = header_end + 1
            digests[blob] = "sha256:" + hashlib.sha256(batch[start:start + size]).hexdigest()
            offset = start + size + 1
    return {path: sorted({digests[b] for b in ids}) for path, ids in sorted(blobs.items())}


@lru_cache(maxsize=8)
def _history_for(source: str, _marker_mtime_ns: int | None) -> Mapping[str, frozenset[str]]:
    # The marker's mtime is part of the cache key so a new release written to
    # the same source root is never answered from an older one's history.
    root = Path(source)
    marker = root / HISTORY_MARKER
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        if payload.get("schema_version") != HISTORY_SCHEMA_VERSION:
            return {}
        paths = payload["paths"]
    except FileNotFoundError:
        if not (root / ".git").exists():
            return {}
        try:
            paths = collect_history(root)
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return {}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}
    if not isinstance(paths, dict):
        return {}
    return {
        str(path): frozenset(str(digest) for digest in digests)
        for path, digests in paths.items()
        if isinstance(digests, list)
    }


def is_prior_framework_version(source: Path, relative: str, checksum: str) -> bool:
    """Whether the framework has ever committed exactly these bytes at this path."""
    try:
        mtime: int | None = (Path(source) / HISTORY_MARKER).stat().st_mtime_ns
    except OSError:
        mtime = None
    return checksum in _history_for(str(source), mtime).get(relative, frozenset())
