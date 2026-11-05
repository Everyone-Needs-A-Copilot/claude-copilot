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
    assert paths["codex_copilot_root"] == str(snaps / f"claude-copilot-{OLD}")
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


# --- Codex root: the pinned codex-foundation layer, never a Claude snapshot -----

import subprocess  # noqa: E402

import pytest  # noqa: E402
import yaml  # noqa: E402
from cc.core.ecosystem.reconciliation_recipes import (  # noqa: E402
    _lock_entry,
    validated_source_root,
)
from cc.core.framework_roots import (  # noqa: E402
    codex_foundation_root,
    effective_codex_root,
    names_claude_snapshot,
)


def _plugin(root: Path, version: str) -> None:
    manifest = root / "plugins/codex-copilot/.codex-plugin/plugin.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"name": "codex-copilot", "version": version}))
    gate = root / "scripts/copilot-gate.sh"
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_text("#!/bin/sh\n")


def _foundation(tmp_path: Path, version: str = "0.16.3") -> tuple[Path, Path]:
    repo = tmp_path / "codex-copilot"
    repo.mkdir()
    _plugin(repo, version)
    git = ("git", "-c", "user.name=T", "-c", "user.email=t@t.invalid", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false")
    subprocess.run(("git", "init", "-q", str(repo)), check=True)
    subprocess.run((*git, "-C", str(repo), "add", "-A"), check=True)
    subprocess.run((*git, "-C", str(repo), "commit", "-qm", "r"), check=True)
    subprocess.run((*git, "-C", str(repo), "tag", f"v{version}"), check=True)
    manifest = tmp_path / "copilot.layers.yml"
    manifest.write_text(yaml.safe_dump({"version": 1, "layers": [{
        "id": "codex-foundation", "role": "foundation", "rank": 40, "product": "codex",
        "source": {"repo": "https://example.invalid/codex-copilot.git",
                   "ref": f"v{version}", "path": str(repo)},
        "auth": "anon", "activation": "always", "policy": {"allowed_signers": ["x"]},
    }]}))
    return repo, manifest


def test_claude_snapshot_is_recognised_and_other_paths_are_not(tmp_path):
    snap = f"/h/.copilot/framework-snapshots/claude-copilot-{NEW}"
    assert names_claude_snapshot(snap) and names_claude_snapshot(snap + "/plugins/x")
    assert not names_claude_snapshot("/Volumes/Dev/Sites/CSE/codex-copilot")
    assert not names_claude_snapshot(f"/h/claude-copilot-{NEW}")


def test_codex_root_pointing_at_a_claude_snapshot_resolves_to_the_pinned_foundation(tmp_path):
    repo, manifest = _foundation(tmp_path)
    snap = f"/h/.copilot/framework-snapshots/claude-copilot-{NEW}"
    assert codex_foundation_root(manifest) == repo
    assert effective_codex_root(snap, manifest) == repo
    assert effective_codex_root("/mine/codex", manifest) == "/mine/codex"


def test_foundation_not_at_its_pinned_ref_is_refused(tmp_path):
    repo, manifest = _foundation(tmp_path)
    (repo / "x").write_text("x")
    git = ("git", "-c", "user.name=T", "-c", "user.email=t@t.invalid", "-c", "commit.gpgsign=false")
    subprocess.run(("git", "-C", str(repo), "add", "-A"), check=True)
    subprocess.run((*git, "-C", str(repo), "commit", "-qm", "later"), check=True)
    assert codex_foundation_root(manifest) is None


def test_delivered_codex_files_match_the_recorded_version(tmp_path, monkeypatch):
    """The lock's Codex version and the plugin files delivered come from one release.

    A Claude snapshot bundles Codex 0.16.0; the pinned foundation is 0.16.3.
    """
    repo, manifest = _foundation(tmp_path, "0.16.3")
    bundled = tmp_path / "home/.copilot/framework-snapshots" / f"claude-copilot-{NEW}"
    _plugin(bundled, "0.16.0")
    monkeypatch.setenv("CC_LAYERS_MANIFEST", str(manifest))
    monkeypatch.setenv("CC_PATHS_CODEX_COPILOT_ROOT", str(bundled))
    monkeypatch.setenv("CC_PATHS_MIRRORS_ROOT", str(tmp_path / "mirrors"))
    bundled.chmod(0o755)
    source = validated_source_root("codex")
    assert source == repo.resolve()
    entry = _lock_entry(source, "codex", codex_binding=None)
    delivered = json.loads(
        (source / "plugins/codex-copilot/.codex-plugin/plugin.json").read_text()
    )["version"]
    assert entry["version"] == delivered == "0.16.3"


def test_drift_names_head_pinned_ref_and_that_they_differ(tmp_path):
    from cc.core.framework_roots import codex_foundation_status

    repo, manifest = _foundation(tmp_path)
    (repo / "x").write_text("x")
    git = ("git", "-c", "user.name=T", "-c", "user.email=t@t.invalid", "-c", "commit.gpgsign=false")
    subprocess.run(("git", "-C", str(repo), "add", "-A"), check=True)
    subprocess.run((*git, "-C", str(repo), "commit", "-qm", "later"), check=True)
    head = subprocess.run(("git", "-C", str(repo), "rev-parse", "HEAD"), capture_output=True, text=True, check=True).stdout.strip()
    root, why = codex_foundation_status(manifest)
    assert root is None
    assert head[:12] in why and "v0.16.3" in why and "differ" in why


def test_refusals_carry_the_drift_cause(tmp_path, monkeypatch):
    from cc.core.ecosystem.reconciliation_recipes import RecipeValidationError
    from cc.core.ecosystem.workspaces import ActivationError, _resolved_framework_root

    repo, manifest = _foundation(tmp_path)
    (repo / "x").write_text("x")
    git = ("git", "-c", "user.name=T", "-c", "user.email=t@t.invalid", "-c", "commit.gpgsign=false")
    subprocess.run(("git", "-C", str(repo), "add", "-A"), check=True)
    subprocess.run((*git, "-C", str(repo), "commit", "-qm", "later"), check=True)
    snap = tmp_path / "home/.copilot/framework-snapshots" / f"claude-copilot-{NEW}"
    _plugin(snap, "0.16.0")
    monkeypatch.setenv("CC_LAYERS_MANIFEST", str(manifest))
    monkeypatch.setenv("CC_PATHS_CODEX_COPILOT_ROOT", str(snap))
    monkeypatch.setenv("CC_PATHS_MIRRORS_ROOT", str(tmp_path / "mirrors"))
    with pytest.raises(RecipeValidationError, match=r"pinned ref v0\.16\.3.*differ"):
        validated_source_root("codex")
    with pytest.raises(ActivationError, match=r"pinned ref v0\.16\.3.*differ"):
        _resolved_framework_root("codex", None)


def test_no_module_reads_the_codex_root_key_outside_the_resolver():
    """Every consumer must go through configured_framework_root(); none may read the key."""
    import ast

    src = Path(__file__).resolve().parents[1] / "src/cc"
    allowed = {
        "core/framework_roots.py",  # the resolver
        "core/config.py",  # the default value
        "commands/doctor.py",  # lists keys for the config check
        "core/conformance/dimensions/d02_codex.py",  # evidence label text only
        # Reads the key from an injected config dict, then applies effective_codex_root().
        "core/ecosystem/machine_assessment.py",
    }
    offenders: list[str] = []
    for path in sorted(src.rglob("*.py")):
        rel = path.relative_to(src).as_posix()
        if rel in allowed:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            text = None
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value
            elif isinstance(node, ast.JoinedStr):
                text = "".join(
                    v.value for v in node.values if isinstance(v, ast.Constant)
                )
            if text and "_copilot_root" in text and (
                "codex" in text or text.startswith("paths.")
            ) and "claude_copilot_root" not in text:
                # docstrings/comments-in-strings that merely mention the key are fine
                if len(text) > 80 or "\n" in text:
                    continue
                offenders.append(f"{rel}:{node.lineno}: {text!r}")
    assert not offenders, offenders
