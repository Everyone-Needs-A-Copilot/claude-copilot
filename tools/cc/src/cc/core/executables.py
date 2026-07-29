"""Deterministic resolution for command-line tools used by ``cc``.

Desktop callers such as Finder and launchd do not inherit an interactive
shell's PATH. Machine inventory must not change merely because the same signed
``cc`` binary was launched by Control Tower instead of a terminal.

Resolution therefore keeps the caller's PATH as the first choice, then checks
a small registry of conventional absolute install locations and bounded Node
version-manager roots. Every successful answer is an executable, canonical
absolute path; callers never spawn a bare command name.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Callable, Iterable

Which = Callable[[str], str | None]

STANDARD_EXECUTABLE_PATHS: dict[str, tuple[str, ...]] = {
    "gh": (
        "~/.local/bin/gh",
        "/opt/homebrew/bin/gh",
        "/usr/local/bin/gh",
    ),
    "copilot": (
        "~/.local/bin/copilot",
        "/opt/homebrew/bin/copilot",
        "/usr/local/bin/copilot",
    ),
    "claude": (
        "~/.local/bin/claude",
        "~/.volta/bin/claude",
        "~/.asdf/shims/claude",
        "~/.local/share/mise/shims/claude",
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
    ),
    "codex": (
        "~/.local/bin/codex",
        "~/.volta/bin/codex",
        "~/.asdf/shims/codex",
        "~/.local/share/mise/shims/codex",
        "/opt/homebrew/bin/codex",
        "/usr/local/bin/codex",
    ),
    "node": (
        "~/.local/bin/node",
        "~/.volta/bin/node",
        "~/.asdf/shims/node",
        "~/.local/share/mise/shims/node",
        "/opt/homebrew/bin/node",
        "/usr/local/bin/node",
    ),
}

NODE_VERSION_MANAGER_GLOBS = (
    ".nvm/versions/node/*/bin/{command}",
    ".fnm/node-versions/*/installation/bin/{command}",
)


def _canonical_executable(candidate: str | Path) -> Path | None:
    path = Path(candidate).expanduser()
    try:
        if not path.is_file() or not os.access(path, os.X_OK):
            return None
        return path.resolve(strict=True)
    except OSError:
        return None


def _natural_path_key(path: Path) -> tuple[tuple[int, int | str], ...]:
    """Sort versioned paths deterministically, with numeric parts numerically."""

    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", str(path))
        if part
    )


def _node_version_manager_candidates(command: str) -> tuple[Path, ...]:
    candidates: list[Path] = []
    for pattern in NODE_VERSION_MANAGER_GLOBS:
        candidates.extend(Path.home().glob(pattern.format(command=command)))
    return tuple(sorted(set(candidates), key=_natural_path_key, reverse=True))


def resolve_executable(
    command: str,
    *,
    which: Which = shutil.which,
    standard_paths: Iterable[str | Path] | None = None,
) -> Path | None:
    """Resolve ``command`` without making GUI launches depend on shell PATH.

    ``standard_paths`` is an explicit test/integration seam. Production callers
    omit it and use the closed registry above; an unknown command remains
    PATH-only and fails honestly when it cannot be resolved.
    """

    from_path = which(command)
    if from_path:
        resolved = _canonical_executable(from_path)
        if resolved is not None:
            return resolved

    candidates = (
        tuple(standard_paths)
        if standard_paths is not None
        else STANDARD_EXECUTABLE_PATHS.get(command, ())
    )
    for candidate in candidates:
        resolved = _canonical_executable(candidate)
        if resolved is not None:
            return resolved
    if command in {"claude", "codex", "node"}:
        for candidate in _node_version_manager_candidates(command):
            resolved = _canonical_executable(candidate)
            if resolved is not None:
                return resolved
    return None
