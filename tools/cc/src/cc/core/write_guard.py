"""Fail-closed guard against test code escaping its filesystem isolation.

`tests/conftest.py`'s `_isolate_machine_config` fixture redirects
`CC_MACHINE_ROOT` (core/config_paths.py) and `CC_GLOBAL_MEMORY_ROOT`
(core/entry_store.py) at fresh per-test tmp directories, then checksums the
real paths before/after as a DETECTION backstop. Detection alone was proven
insufficient: a probe that cleared `CC_MACHINE_ROOT` and called
`write_config()` directly wrote to the developer's real
`~/.claude/cc/config.json` before the teardown checksum caught it. Aggregate
onboarding's active and legacy layer-manifest paths are covered by the same
prevention + detection contract.

This module is the PREVENTION layer. Every write path that can reach a
machine-config or global-memory location (`core/config.py`'s
`write_config`/`add_to_list_config`/`remove_from_list_config`/
`unset_config`, `core/entry_store.py`'s `_atomic_write`/
`_ensure_entries_dir`/`delete_entry`) calls `assert_write_is_isolated()`
immediately before mutating the filesystem, and as early as possible (before
any `mkdir`, not just before the final `write_text`) so a blocked write
leaves nothing behind, not even an empty directory.

The guard is a no-op outside pytest, gated on `PYTEST_CURRENT_TEST` -- a
sentinel pytest itself sets/clears for the exact duration of each test's
setup/call/teardown. That makes it a much sturdier signal than the
CC_MACHINE_ROOT/CC_GLOBAL_MEMORY_ROOT env vars a test could bypass by
monkeypatching a `*_path()`/`resolve_*()` resolver directly instead of the
env var: a test would have to deliberately `monkeypatch.delenv` pytest's own
bookkeeping variable to defeat this guard, a far more deliberate act than
the demonstrated escape. Under test, it hard-fails any write whose resolved
target path is, or is inside, a fixed denylist of the real locations cc is
known to write -- the real machine config file, the real machine secrets
file, and the real global memory root -- regardless of how the caller
arrived at that path, so it still catches the "monkeypatched the resolver,
not the env var" escape the checksum-only guard missed.
"""

from __future__ import annotations

import os
from pathlib import Path

_TEST_SENTINEL_ENV = "PYTEST_CURRENT_TEST"


class TestIsolationEscapeError(RuntimeError):
    """Raised when code attempts to write to a real, non-isolated cc
    location while a test is running."""


# The exact real, non-isolated locations cc's write paths are known to
# target. Deliberately hardcoded (not resolved via config_paths.py,
# entry_store.py, or onboard.py) so this guard cannot be fooled by the very
# monkeypatching it exists to catch.
#
# Resolved ONCE, at import time, rather than inside `assert_write_is_
# isolated()` on every call: several contract test files (test_layers_
# contract.py, test_update_contract.py, test_projects_contract.py,
# test_deprovision_contract.py, ...) run their OWN autouse fixture that
# monkeypatches `Path.home` to raise if it is ever called during a test, to
# prove the code under test makes zero real-home-dependent decisions. This
# module's own module-level `Path.home()` call happens at import time --
# before pytest has run any test or applied any such monkeypatch -- so it
# captures the real value once, correctly, and never touches `Path.home()`
# again while any test is running (so it can never trip those fixtures,
# even though its raison d'être is exactly "a test bypassed isolation").
_REAL_HOME = Path.home()
_FORBIDDEN_REAL_PATHS: tuple[Path, ...] = (
    _REAL_HOME / ".claude" / "cc" / "config.json",
    _REAL_HOME / ".claude" / "cc" / "secrets.env",
    _REAL_HOME / ".claude" / "memory",
    _REAL_HOME / ".config" / "copilot" / "copilot.layers.yml",
    _REAL_HOME / ".copilot" / "copilot.layers.yml",
    _REAL_HOME / ".copilot-cli" / "copilot.layers.yml",
)


def assert_write_is_isolated(path: Path) -> None:
    """Raise `TestIsolationEscapeError` if `path` resolves to, or inside, a
    real non-isolated cc location while a test is running. No-op outside
    pytest (when `PYTEST_CURRENT_TEST` is unset), so this never affects
    production behavior.
    """
    if _TEST_SENTINEL_ENV not in os.environ:
        return

    resolved = path.expanduser().resolve()
    for forbidden in _FORBIDDEN_REAL_PATHS:
        forbidden_resolved = forbidden.resolve()
        if resolved == forbidden_resolved or forbidden_resolved in resolved.parents:
            raise TestIsolationEscapeError(
                f"Refusing to write {resolved} -- it resolves to, or inside, "
                f"the real {forbidden_resolved}, and a test is currently "
                f"running ({_TEST_SENTINEL_ENV} is set). This is almost "
                "certainly a test that bypassed the CC_MACHINE_ROOT / "
                "CC_GLOBAL_MEMORY_ROOT isolation seam (core/config_paths.py, "
                "core/entry_store.py) -- fix the test, do not remove this "
                "guard."
            )


__all__ = ["TestIsolationEscapeError", "assert_write_is_isolated"]
