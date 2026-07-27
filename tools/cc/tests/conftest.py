"""Shared test fixtures for cc CLI tests."""

import hashlib
from pathlib import Path

import pytest
from cc.main import app
from typer.testing import CliRunner

# The REAL machine config/secrets paths -- deliberately resolved WITHOUT
# going through `cc.core.config_paths` (so this check can never be fooled
# by the very env var it's guarding against). Used only to prove nothing
# wrote here; never read for any other purpose.
_REAL_MACHINE_CONFIG = Path.home() / ".claude" / "cc" / "config.json"
_REAL_MACHINE_SECRETS = Path.home() / ".claude" / "cc" / "secrets.env"

# The REAL "global" memory root -- deliberately resolved WITHOUT going
# through `cc.core.entry_store` (same reasoning as above). This directory
# is also where Claude Code's own per-project auto-memory databases live
# (dozens of them, ~megabytes), so this check does NOT hash the whole tree
# -- that would (a) be needlessly slow across ~1000 tests and (b) produce
# false positives from legitimate concurrent Claude Code activity writing
# to sibling project directories while the suite runs. Instead it checksums
# only the specific paths cc's OWN code is known to write under this root:
# `entries/` (core/entry_store.py's `store_entry`/`delete_entry`),
# `.gitignore` (`_ensure_entries_dir`), and `copilot.lock`
# (core/locking.py's `lock_path()`). None of these exist today, and they
# must stay that way (or byte-identical, if they legitimately exist later)
# for the suite to pass.
_REAL_GLOBAL_MEMORY_ROOT = Path.home() / ".claude" / "memory"
_GLOBAL_MEMORY_TARGETS = ("entries", ".gitignore", "copilot.lock")


def _checksum(path: Path) -> str | None:
    if not path.exists():
        return None
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    # Directory: hash of sorted (relative path, content) pairs so renames,
    # additions, and removals anywhere inside are all detected.
    hasher = hashlib.sha256()
    for sub in sorted(path.rglob("*")):
        if sub.is_file():
            hasher.update(sub.relative_to(path).as_posix().encode("utf-8"))
            hasher.update(sub.read_bytes())
    return hasher.hexdigest()


def _global_memory_checksums() -> dict[str, str | None]:
    return {
        name: _checksum(_REAL_GLOBAL_MEMORY_ROOT / name)
        for name in _GLOBAL_MEMORY_TARGETS
    }


@pytest.fixture(autouse=True)
def _isolate_machine_config(tmp_path, monkeypatch):
    """Make it structurally impossible for any test to touch the developer's
    real `~/.claude/cc/config.json` / `secrets.env`, or the real "global"
    memory root (`~/.claude/memory`). Two layers:

    1. PREVENTION -- redirect `CC_MACHINE_ROOT` (the injectable root
       `core/config_paths.py`'s `machine_config_path()`/
       `machine_secrets_path()` honor) and `CC_GLOBAL_MEMORY_ROOT` (the
       injectable root `core/entry_store.py`'s `resolve_memory_root("global")`
       honors) at fresh per-test tmp directories. Every call site reaches
       these functions eventually (`write_config`, `unset_config`,
       `load_machine_config`, `store_entry`, `delete_entry`,
       `core/locking.py`'s `lock_path()`, ... across core/config.py,
       core/entry_store.py, core/locking.py, commands/config.py,
       commands/onboard.py, commands/workspaces.py, commands/memory.py,
       commands/mcp_serve.py, commands/doctor.py), so redirecting the two
       shared roots covers all of them without any test opting in.
    2. DETECTION -- checksum the REAL files/paths before and after the test
       and fail loudly if any changed, so a test that somehow bypasses
       layer 1 (e.g. by monkeypatching `machine_config_path` or
       `resolve_memory_root` directly to return a real-home path) is caught
       immediately rather than silently corrupting the developer's machine.

    This exists because of a real incident: a test
    (`test_manifest_repair_is_not_a_checkbox_and_applies_without_any_consent`,
    tests/test_onboard_contract.py) reached `write_config()` through
    `commands/onboard.py` without patching anything, and wrote a pytest
    tmpdir path into a developer's live `~/.claude/cc/config.json`. The
    `CC_GLOBAL_MEMORY_ROOT` half closes the structurally identical gap in
    `resolve_memory_root("global")` (no injectable root existed at all
    before this fix) before any test trips over it for real -- that root
    also backs `core/locking.py`'s `copilot_lock()`, and the real directory
    already holds dozens of real cross-project entries, a larger blast
    radius than the config-file incident.
    """
    config_before = _checksum(_REAL_MACHINE_CONFIG)
    secrets_before = _checksum(_REAL_MACHINE_SECRETS)
    global_memory_before = _global_memory_checksums()
    monkeypatch.setenv("CC_MACHINE_ROOT", str(tmp_path / "machine-config-root"))
    monkeypatch.setenv("CC_GLOBAL_MEMORY_ROOT", str(tmp_path / "global-memory-root"))
    yield
    config_after = _checksum(_REAL_MACHINE_CONFIG)
    secrets_after = _checksum(_REAL_MACHINE_SECRETS)
    global_memory_after = _global_memory_checksums()
    assert config_after == config_before, (
        "A test wrote to the real ~/.claude/cc/config.json. Route the write "
        "through the CC_MACHINE_ROOT seam (core/config_paths.py) instead of "
        "Path.home() -- never disable this check."
    )
    assert secrets_after == secrets_before, (
        "A test wrote to the real ~/.claude/cc/secrets.env. Route the write "
        "through the CC_MACHINE_ROOT seam (core/config_paths.py) instead of "
        "Path.home() -- never disable this check."
    )
    assert global_memory_after == global_memory_before, (
        "A test wrote to the real ~/.claude/memory (global scope). Route "
        "the write through the CC_GLOBAL_MEMORY_ROOT seam "
        "(core/entry_store.py's resolve_memory_root) instead of "
        "Path.home() -- never disable this check."
    )


@pytest.fixture
def runner() -> CliRunner:
    """Typer test runner."""
    return CliRunner()


@pytest.fixture
def cli(runner: CliRunner):
    """Return a callable that invokes CLI commands.

    Usage:
        result = cli(["version"])
    """

    def invoke(*args, **kwargs):
        return runner.invoke(app, *args, **kwargs)

    return invoke
