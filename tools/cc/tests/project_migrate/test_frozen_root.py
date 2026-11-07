"""Frozen scans never treat PyInstaller's temporary parents as framework roots."""
import json
import sys

import pytest
from typer.testing import CliRunner

from cc.commands.project import project_app
from cc.core.project_migrate import known
from cc.core.project_migrate.model import MigrateError


def _framework(root):
    (root / "tools" / "cc").mkdir(parents=True)
    (root / "VERSION.json").write_text('{"framework":"5.35.2"}\n')


def test_source_checkout_uses_its_actual_framework_root(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    root = known.default_claude_root()
    assert (root / "tools/cc/src/cc/core/project_migrate/known.py").resolve() == known.Path(known.__file__).resolve()


def test_frozen_helper_uses_only_active_central_framework(tmp_path, monkeypatch):
    home = tmp_path / ".copilot"
    release = home / "releases" / "candidate"
    root = release / "claude-copilot"
    _framework(root)
    (home / "current").symlink_to("releases/candidate")
    monkeypatch.setenv("COPILOT_HOME", str(home))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(known, "__file__", str(tmp_path / "private/var/extraction/cc/core/project_migrate/known.py"))
    assert known.default_claude_root() == root


@pytest.mark.parametrize("kind", ["missing", "outside", "linked-component", "invalid-root"])
def test_frozen_missing_or_escaping_framework_fails_closed(tmp_path, monkeypatch, kind):
    home = tmp_path / ".copilot"
    home.mkdir()
    monkeypatch.setenv("COPILOT_HOME", str(home))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    if kind != "missing":
        release = tmp_path / "outside" if kind == "outside" else home / "releases/candidate"
        release.mkdir(parents=True)
        if kind == "linked-component":
            _framework(tmp_path / "foreign")
            (release / "claude-copilot").symlink_to(tmp_path / "foreign")
        elif kind != "invalid-root":
            _framework(release / "claude-copilot")
        (home / "current").symlink_to(release)
    with pytest.raises(MigrateError, match="Publish or restore a verified release"):
        known.default_claude_root()
    result = CliRunner().invoke(project_app, ["migrate", "--scan", "--all", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "framework-unavailable"
