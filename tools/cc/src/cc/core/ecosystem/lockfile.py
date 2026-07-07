"""READ-ONLY reader for the per-layer/per-dimension/per-item SHA pins.

ecosystem-architecture.md §9: "SHA-pinned lockfile per layer — the
reproducibility anchor everything else verifies against." This module
NEVER writes anything — `cc resolve` is read-only (no lock, no
materialize; mirrors `cc doctor`'s precedent in doctor.py). If the file is
absent or unreadable, every lookup gracefully degrades to "no recorded
sha" rather than raising, so a first-run machine (no lockfile yet) still
gets a usable `--explain` report (every `winning_sha` simply `None`)
instead of a crash.

NOTE (deferred, tracked): this data lockfile shares its conceptual name
("copilot.lock") with the UNRELATED advisory `flock` mutex file that
core/locking.py already uses for cc's self-serialization
(`resolve_memory_root("global") / "copilot.lock"`). The two are different
files serving different purposes today; this module deliberately does NOT
read/write that mutex file, and instead defaults to a distinct
`copilot.lock.json` path (see `default_lockfile_path()`) so the two never
collide on disk. Resolving the naming collision for real (should the data
lockfile also be called `copilot.lock`, and if so how do the mutex and the
data file coexist) is explicitly out of scope for this read-only slice —
left for whichever later slice actually introduces lockfile *writing*
(materialize).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


def default_lockfile_path() -> Optional[Path]:
    """
    Best-effort default location for the ecosystem lockfile.

    PROVISIONAL (owner to confirm once the materialize slice lands): lives
    at `<repo root>/copilot.lock.json`. Returns None (treated identically
    to "file absent") when there is no repo root to anchor to, rather than
    guessing a location.
    """
    from cc.core.config_paths import repo_root

    root = repo_root()
    if root is None:
        return None
    return root / "copilot.lock.json"


def read_lockfile(path: Optional[Path | str]) -> dict[str, dict[str, dict[str, str]]]:
    """
    Read the per-layer/per-dimension/per-item SHA pins.

    Shape: `{layer_id: {dimension: {item_name: sha}}}`.

    Read-only: never creates, writes, or locks anything. Returns `{}` if
    `path` is `None`, does not exist, or fails to parse as a JSON object —
    a missing/corrupt lockfile degrades to "no recorded SHAs" (every
    `winning_sha` / override-stale comparison falls back to `None`/unknown)
    rather than raising.
    """
    if path is None:
        return {}

    resolved = Path(path).expanduser()
    if not resolved.exists():
        return {}

    try:
        data: Any = json.loads(resolved.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    if not isinstance(data, dict):
        return {}

    return data
