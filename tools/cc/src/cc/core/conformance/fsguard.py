"""The read-only tripwire: what makes it safe to run the conformance harness
against the real machine.

`HARNESS-DESIGN.md` §5.3 ("World B — the read-only tripwire") specifies four
mechanisms; this module implements all four:

  1. BEFORE: fingerprint (mtime_ns, size, sha256) every path the run is
     about to read.
  2. DURING: filesystem access that goes through `ReadOnlyFS` raises on any
     write call; git access that goes through `run_git_readonly` raises on
     any subcommand outside a fixed allowlist.
  3. AFTER: re-fingerprint and assert byte-identity; fail loudly naming the
     offending path(s) — this is the actual guarantee. `ReadOnlyFS` and the
     git allowlist are prevention (best-effort); `MachineReadOnlyGuard`'s
     before/after comparison is DETECTION and is what makes the safety
     property correct rather than best-effort, exactly as the brief demands:
     a bypass of layer 2 (e.g. a check that shells out to `subprocess.run`
     directly instead of `run_git_readonly`) is still caught here.
  4. Git safety is an ALLOWLIST, not a denylist (`HARNESS-DESIGN.md`: "git
     worktree list ... would otherwise be tempting, and pruning is a
     mutation").

This mirrors `tests/conftest.py`'s existing `_isolate_machine_config`
fixture (same checksum-before/after-and-fail-loud shape, same guarded real
paths) but generalizes it into a reusable, non-pytest-specific primitive:
`tests/conftest.py`'s fixture guards a FIXED set of paths for every test in
the whole `cc` suite; `MachineReadOnlyGuard` here guards a caller-supplied
set (the specific manifest, tier repos, and project dimension paths ONE
conformance run actually touches) *in addition to* the same fixed core set,
so both `cc conformance check` (a real CLI invocation, not a pytest test)
and `tests/conformance/conftest.py`'s `machine_readonly` fixture can use it.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Iterable, Mapping, Sequence

# ---------------------------------------------------------------------------
# The fixed core guarded set (mirrors tests/conftest.py's
# _isolate_machine_config exactly — same real paths, same reasoning).
# ---------------------------------------------------------------------------


def _home() -> Path:
    # Deliberately NOT going through cc.core.config_paths (which honors
    # CC_MACHINE_ROOT) -- this constant must name the REAL machine paths
    # regardless of any isolation env var a test or caller has set, or the
    # tripwire could be fooled by the exact seam it exists to guard.
    return Path.home()


def default_guarded_machine_paths() -> tuple[Path, ...]:
    """The fixed set: real machine config, real secrets, the real global
    memory root's tracked targets, and all three real `copilot.layers.yml`
    locations."""

    home = _home()
    return (
        home / ".claude" / "cc" / "config.json",
        home / ".claude" / "cc" / "secrets.env",
        home / ".claude" / "memory" / "entries",
        home / ".claude" / "memory" / ".gitignore",
        home / ".claude" / "memory" / "copilot.lock",
        home / ".config" / "copilot" / "copilot.layers.yml",
        home / ".copilot" / "copilot.layers.yml",
        home / ".copilot-cli" / "copilot.layers.yml",
    )


def _fingerprint(path: Path) -> tuple[int, int, str] | None:
    """(mtime_ns, size, sha256) for a file; a directory-wide variant of the
    same for a directory; `None` if the path does not exist. Mirrors
    `tests/conftest.py::_checksum`'s directory-hashing shape (sorted
    relative-path + content pairs) so renames/additions/removals anywhere
    inside a guarded directory are all detected, plus adds mtime/size so a
    same-content-different-timestamp touch is ALSO detected (stricter than
    the existing fixture, which is content-only)."""

    try:
        if not path.exists():
            return None
        if path.is_file():
            stat = path.stat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            return (stat.st_mtime_ns, stat.st_size, digest)
        # Directory.
        hasher = hashlib.sha256()
        total_size = 0
        latest_mtime_ns = 0
        for sub in sorted(path.rglob("*")):
            if sub.is_file():
                sub_stat = sub.stat()
                total_size += sub_stat.st_size
                latest_mtime_ns = max(latest_mtime_ns, sub_stat.st_mtime_ns)
                hasher.update(sub.relative_to(path).as_posix().encode("utf-8"))
                hasher.update(sub.read_bytes())
        return (latest_mtime_ns, total_size, hasher.hexdigest())
    except OSError:
        # Unreadable rather than absent -- still a fingerprint worth
        # comparing (it may become readable, or vice versa, between before
        # and after; either is a change worth failing on).
        return (-1, -1, "unreadable")


class MachineMutationError(AssertionError):
    """The tripwire fired: a guarded real path changed between the
    before-fingerprint and the after-fingerprint. Always names the
    offending path(s) — never a bare "something changed"."""


class MachineReadOnlyGuard:
    """Context manager: fingerprint `paths` (plus, by default, the fixed
    core guarded set) on entry; assert byte-identity on exit; raise
    `MachineMutationError` naming every offending path if anything changed.

    Usage::

        with MachineReadOnlyGuard(extra_paths=[manifest_path, *tier_paths]):
            run_the_checks()

    Deliberately does not distinguish "why" a path changed (a real bug vs.
    legitimate concurrent activity elsewhere on the machine) — for a
    conformance harness that must never lie, the correct response to ANY
    doubt is to fail the whole run loudly, not to guess.
    """

    def __init__(
        self,
        extra_paths: Iterable[Path] = (),
        *,
        include_core_paths: bool = True,
    ) -> None:
        paths: list[Path] = list(extra_paths)
        if include_core_paths:
            paths.extend(default_guarded_machine_paths())
        # De-duplicate while preserving first-seen order (dict trick), since
        # a caller-supplied path may legitimately overlap the core set.
        self._paths: tuple[Path, ...] = tuple(dict.fromkeys(paths))
        self._before: Mapping[Path, tuple[int, int, str] | None] = {}

    def __enter__(self) -> "MachineReadOnlyGuard":
        self._before = {path: _fingerprint(path) for path in self._paths}
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        after = {path: _fingerprint(path) for path in self._paths}
        changed = [
            path for path in self._paths if after[path] != self._before[path]
        ]
        if changed:
            offending = ", ".join(str(path) for path in changed)
            raise MachineMutationError(
                "The conformance harness's read-only tripwire fired: the "
                f"following real path(s) changed during the run: {offending}. "
                "Every conformance check MUST be read-only against the real "
                "machine (World B) — route the write through a tmp_path "
                "fixture instead (World A), or via git clone --local "
                "--no-hardlinks for Layer 5's round-trip. This check never "
                "disables itself even when the run's own checks otherwise "
                "passed."
            )

    @property
    def guarded_paths(self) -> tuple[Path, ...]:
        return self._paths


# ---------------------------------------------------------------------------
# Git plumbing allowlist — prevention layer (the detection layer above is
# what makes this safe rather than best-effort).
# ---------------------------------------------------------------------------

# HARNESS-DESIGN.md §5.3 rule 4, verbatim: "only plumbing that cannot mutate
# is permitted -- rev-parse, merge-base --is-ancestor, rev-list --count,
# for-each-ref, check-ignore, ls-files, status --porcelain. fetch, gc,
# checkout, worktree, and anything writing .git/ are refused by an
# allowlist, not a denylist."
GIT_READONLY_SUBCOMMAND_ALLOWLIST: frozenset[str] = frozenset(
    {
        "rev-parse",
        "merge-base",
        "rev-list",
        "for-each-ref",
        "check-ignore",
        "ls-files",
        "status",
    }
)


class GitCommandNotAllowed(PermissionError):
    """A conformance check tried to run a git subcommand outside the
    read-only plumbing allowlist. Extending the allowlist is a deliberate,
    reviewed change to this module (WP-1 owns `fsguard.py`) — never a
    per-check workaround."""


def assert_git_args_allowed(args: Sequence[str]) -> None:
    """Raise `GitCommandNotAllowed` unless `args` (the argv AFTER the
    literal `git`, e.g. `("rev-parse", "--verify", "HEAD")`) invokes an
    allowlisted read-only subcommand."""

    if not args or args[0] not in GIT_READONLY_SUBCOMMAND_ALLOWLIST:
        subcommand = args[0] if args else "<empty>"
        raise GitCommandNotAllowed(
            f"git subcommand {subcommand!r} is not on the conformance "
            "harness's read-only allowlist "
            f"({sorted(GIT_READONLY_SUBCOMMAND_ALLOWLIST)!r}). A conformance "
            "check must never fetch, gc, checkout, or otherwise mutate a "
            "real repository -- if a new read-only subcommand is genuinely "
            "needed, it is added to GIT_READONLY_SUBCOMMAND_ALLOWLIST in "
            "fsguard.py, never bypassed."
        )


def run_git_readonly(
    args: Sequence[str],
    *,
    cwd: Path,
    timeout: float = 10.0,
) -> subprocess.CompletedProcess[str]:
    """The only sanctioned way a conformance check invokes git against a
    real repository. Validates `args[0]` against the allowlist BEFORE
    spawning anything, then runs `git <args>` with `check=False` (callers
    inspect `.returncode` themselves — a non-zero exit is often the
    INTERESTING answer, e.g. `merge-base --is-ancestor` failing IS the
    RC-3 evidence, not an error to swallow)."""

    assert_git_args_allowed(args)
    return subprocess.run(
        ("git", *args),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# ReadOnlyFS -- an opt-in, explicit-write-refusing filesystem adapter.
# ---------------------------------------------------------------------------


class ReadOnlyViolation(PermissionError):
    """A conformance check called a write-shaped method on `ReadOnlyFS`."""


class ReadOnlyFS:
    """A thin pathlib-shaped adapter that check authors MAY route filesystem
    access through for defense-in-depth (the `MachineReadOnlyGuard` tripwire
    above is what actually enforces read-only-ness; this class exists so a
    check body can *express* "I only read" in its own code, and get an
    immediate, local `ReadOnlyViolation` instead of only finding out at
    context-exit time that something it called mutated a real path).

    Read methods delegate straight to `pathlib.Path`. Every write-shaped
    method raises immediately and never touches the filesystem.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def read_text(self, relative: str, encoding: str = "utf-8") -> str:
        return (self._root / relative).read_text(encoding=encoding)

    def read_bytes(self, relative: str) -> bytes:
        return (self._root / relative).read_bytes()

    def exists(self, relative: str) -> bool:
        return (self._root / relative).exists()

    def is_file(self, relative: str) -> bool:
        return (self._root / relative).is_file()

    def is_dir(self, relative: str) -> bool:
        return (self._root / relative).is_dir()

    def is_symlink(self, relative: str) -> bool:
        return (self._root / relative).is_symlink()

    def stat(self, relative: str) -> os.stat_result:
        return (self._root / relative).stat()

    def iterdir(self, relative: str = ".") -> Iterable[Path]:
        return (self._root / relative).iterdir()

    def rglob(self, pattern: str) -> Iterable[Path]:
        return self._root.rglob(pattern)

    def _refuse(self, method: str) -> None:
        raise ReadOnlyViolation(
            f"ReadOnlyFS.{method}() was called -- conformance checks are "
            "read-only against real subjects. Layer 5's round-trip is the "
            "ONE place mutation is allowed, and only inside a "
            "git-clone --local --no-hardlinks tmp_path clone, never through "
            "this adapter."
        )

    def write_text(self, *_args: object, **_kwargs: object) -> None:
        self._refuse("write_text")

    def write_bytes(self, *_args: object, **_kwargs: object) -> None:
        self._refuse("write_bytes")

    def mkdir(self, *_args: object, **_kwargs: object) -> None:
        self._refuse("mkdir")

    def unlink(self, *_args: object, **_kwargs: object) -> None:
        self._refuse("unlink")

    def rmdir(self, *_args: object, **_kwargs: object) -> None:
        self._refuse("rmdir")

    def rename(self, *_args: object, **_kwargs: object) -> None:
        self._refuse("rename")

    def chmod(self, *_args: object, **_kwargs: object) -> None:
        self._refuse("chmod")

    def symlink_to(self, *_args: object, **_kwargs: object) -> None:
        self._refuse("symlink_to")


__all__ = [
    "GIT_READONLY_SUBCOMMAND_ALLOWLIST",
    "GitCommandNotAllowed",
    "MachineMutationError",
    "MachineReadOnlyGuard",
    "ReadOnlyFS",
    "ReadOnlyViolation",
    "assert_git_args_allowed",
    "default_guarded_machine_paths",
    "run_git_readonly",
]
