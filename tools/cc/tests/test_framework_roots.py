"""`cc update` repoints snapshot-pinned framework roots, like the snapshot installer."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

from cc.core.framework_roots import (
    config_with_snapshot_roots,
    sync_machine_config_to_active_runtime,
)
from typer.testing import CliRunner

OLD = "8" * 40
NEW = "a" * 40


def _machine(tmp_path: Path, raw: str | None = None) -> tuple[Path, Path, Path]:
    home = tmp_path / "home"
    copilot = home / ".copilot"
    snaps = copilot / "framework-snapshots"
    for sha in (OLD, NEW):
        (snaps / f"claude-copilot-{sha}").mkdir(parents=True)
    (copilot / "framework-runtime.json").write_text(
        json.dumps({"snapshot": str(snaps / f"claude-copilot-{NEW}")})
    )
    config = home / ".claude" / "cc" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        raw
        if raw is not None
        else json.dumps(
            {
                "paths": {
                    "claude_copilot_root": str(snaps / f"claude-copilot-{OLD}"),
                    "codex_copilot_root": str(snaps / f"claude-copilot-{OLD}"),
                    "repositories_root": "/keep",
                }
            },
            indent=2,
        )
        + "\n"
    )
    return home, config, snaps


def test_cc_update_repoints_stale_snapshot_roots(tmp_path, monkeypatch):
    from cc.main import app

    home, config, snaps = _machine(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CC_MACHINE_ROOT", str(config.parent))
    report = {"schema_version": "1.0", "result": "up-to-date", "changed": [], "blocked": []}
    with mock.patch("cc.commands.update.execute_update", return_value=(report, 0)):
        result = CliRunner().invoke(app, ["update", "--json"])
    assert result.exit_code == 0, result.output
    paths = json.loads(config.read_text())["paths"]
    assert paths["claude_copilot_root"] == str(snaps / f"claude-copilot-{NEW}")
    assert paths["codex_copilot_root"] == str(snaps / f"claude-copilot-{NEW}")
    assert paths["repositories_root"] == "/keep"
    assert config.read_text().startswith('{\n  "paths"')


def test_dry_run_update_does_not_touch_the_config(tmp_path, monkeypatch):
    from cc.main import app

    home, config, _ = _machine(tmp_path)
    before = config.read_bytes()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CC_MACHINE_ROOT", str(config.parent))
    report = {"schema_version": "1.0", "result": "up-to-date", "changed": [], "blocked": []}
    with mock.patch("cc.commands.update.execute_update", return_value=(report, 0)):
        CliRunner().invoke(app, ["update", "--json", "--dry-run"])
    assert config.read_bytes() == before


def test_sync_leaves_owner_paths_missing_manifest_and_foreign_snapshots_alone(tmp_path):
    raw = json.dumps({"paths": {"claude_copilot_root": "/Users/x/checkout"}})
    _, config, _ = _machine(tmp_path, raw)
    copilot = tmp_path / "home" / ".copilot"
    assert sync_machine_config_to_active_runtime(config_path=config, copilot_root=copilot) is False
    assert config.read_text() == raw
    (copilot / "framework-runtime.json").write_text(json.dumps({"snapshot": "/etc"}))
    assert sync_machine_config_to_active_runtime(config_path=config, copilot_root=copilot) is False
    (copilot / "framework-runtime.json").unlink()
    assert sync_machine_config_to_active_runtime(config_path=config, copilot_root=copilot) is False


def test_installer_and_cc_repoint_functions_agree(tmp_path):
    script = Path(__file__).resolve().parents[3] / "scripts/install-framework-snapshot.py"
    spec = importlib.util.spec_from_file_location("installer_parity", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _, _, snaps = _machine(tmp_path)
    new = snaps / f"claude-copilot-{NEW}"
    for raw in (
        json.dumps({"paths": {"claude_copilot_root": str(snaps / f"claude-copilot-{OLD}")}}),
        '{\n    "paths": {\n        "codex_copilot_root": "~/.copilot/framework-snapshots/x"\n    }\n}\n',
        '{"paths": {"claude_copilot_root": "/mine"}}',
    ):
        assert module._config_with_snapshot_roots(raw.encode(), snaps, new) == (
            config_with_snapshot_roots(raw.encode(), snaps, new)
        )
