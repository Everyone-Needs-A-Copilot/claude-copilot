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


def _checksum(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def _isolate_machine_config(tmp_path, monkeypatch):
    """Make it structurally impossible for any test to touch the developer's
    real `~/.claude/cc/config.json` / `secrets.env`. Two layers:

    1. PREVENTION -- redirect `CC_MACHINE_ROOT` (the injectable root
       `core/config_paths.py`'s `machine_config_path()`/
       `machine_secrets_path()` honor) at a fresh per-test tmp directory.
       Every call site reaches these two functions eventually (`write_config`,
       `unset_config`, `load_machine_config`, ... across core/config.py,
       commands/config.py, commands/onboard.py, commands/workspaces.py,
       commands/mcp_serve.py, commands/doctor.py), so redirecting the one
       shared root covers all of them without any test opting in.
    2. DETECTION -- checksum the REAL files before and after the test and
       fail loudly if either changed, so a test that somehow bypasses layer 1
       (e.g. by monkeypatching `machine_config_path` directly to return a
       real-home path) is caught immediately rather than silently corrupting
       the developer's machine.

    This exists because of a real incident: a test
    (`test_manifest_repair_is_not_a_checkbox_and_applies_without_any_consent`,
    tests/test_onboard_contract.py) reached `write_config()` through
    `commands/onboard.py` without patching anything, and wrote a pytest
    tmpdir path into a developer's live `~/.claude/cc/config.json`.
    """
    config_before = _checksum(_REAL_MACHINE_CONFIG)
    secrets_before = _checksum(_REAL_MACHINE_SECRETS)
    monkeypatch.setenv("CC_MACHINE_ROOT", str(tmp_path / "machine-config-root"))
    yield
    config_after = _checksum(_REAL_MACHINE_CONFIG)
    secrets_after = _checksum(_REAL_MACHINE_SECRETS)
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
