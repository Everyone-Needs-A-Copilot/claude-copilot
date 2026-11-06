"""The `codex-org` lock record is the Codex org-tier plugin overlay.

`codex-copilot`'s setup/update scripts write a `codex-org` component entry
(plugin_name e.g. `codex-copilot-internal`, with an internal symlink under
`.claude/skills/`) beside the `codex` entry. insights-copilot and convoco carry
it today. cc used to treat it as an unknown component and report the whole
lock as unreadable. It is now a recognized overlay: tolerated by every reader
and preserved verbatim by every writer.
"""

from __future__ import annotations

import json
from pathlib import Path

from cc.core.ecosystem.project_integration import _lock_state
from cc.core.ecosystem.reconciliation_recipes import _existing_lock_entries
from cc.core.ecosystem.reconciliation_types import OVERLAY_COMPONENTS

CODEX_ORG = {
    "component": "codex-org",
    "files": [
        {
            "checksum": "sha256:5b85d211e528194509867d4a4d520c57255266b48726865c1ca382b13013eae1",
            "ownership": "framework",
            "path": ".codex-plugin/plugin.json",
        },
        {
            "checksum": "sha256:a04ab22f8f1cbd1b0b339c3bd92d042a8376e43cab733fff24d96502d0fa607c",
            "ownership": "framework",
            "path": "skills/cco/SKILL.md",
        },
    ],
    "managed_outputs": [
        {
            "fingerprint": "sha256:11d45235c530e2f6799ce602e0ea10c7699912f4cb9d41f6e41b630d33c856f9",
            "kind": "internal-symlink",
            "path": ".claude/skills/codex-copilot-internal",
        }
    ],
    "plugin_name": "codex-copilot-internal",
    "version": "1.1.0",
}


def _claude(version: str = "5.33.1") -> dict:
    return {
        "component": "claude",
        "files": [],
        "ownership_mode": "full",
        "release_tag": f"v{version}",
        "version": version,
    }


def _codex(version: str) -> dict:
    return {
        "component": "codex",
        "files": [],
        "managed_outputs": [
            {
                "fingerprint": "sha256:ef93018d64e04f341f5de74439db27416865444794b6b29a4660575d67964f84",
                "kind": "internal-symlink",
                "path": ".claude/skills/codex-copilot",
            }
        ],
        "release_tag": f"v{version}",
        "version": version,
    }


def _write(root: Path, components: list[dict]) -> None:
    (root / "copilot.lock.json").write_text(
        json.dumps({"components": components, "schema_version": "1.0"}), encoding="utf-8"
    )


def test_codex_org_is_a_declared_overlay():
    assert OVERLAY_COMPONENTS == ("codex-org",)


def test_insights_copilot_shape_reads_as_verified(tmp_path):
    _write(tmp_path, [_claude(), _codex("0.15.0"), CODEX_ORG])
    state, entries, fingerprint = _lock_state(tmp_path)
    assert state == "verified"
    assert sorted(entries) == ["claude", "codex"]
    assert {"overlays": ["codex-org"]} in fingerprint


def test_convoco_shape_reads_as_verified(tmp_path):
    _write(tmp_path, [_claude(), _codex("0.9.0"), CODEX_ORG])
    assert _lock_state(tmp_path)[0] == "verified"


def test_lock_without_overlay_fingerprint_is_unchanged(tmp_path):
    _write(tmp_path, [_claude(), _codex("0.15.0")])
    state, _entries, fingerprint = _lock_state(tmp_path)
    assert state == "verified"
    assert fingerprint == ["lock", ["claude", "codex"]]


def test_duplicate_overlay_and_unknown_components_stay_unreadable(tmp_path):
    _write(tmp_path, [_claude(), CODEX_ORG, dict(CODEX_ORG)])
    assert _lock_state(tmp_path)[0] == "unreadable"
    _write(tmp_path, [_claude(), {"component": "mystery"}])
    assert _lock_state(tmp_path)[0] == "unreadable"


def test_recipe_lock_reader_keeps_peers_when_overlay_present(tmp_path):
    _write(tmp_path, [_claude(), _codex("0.15.0"), CODEX_ORG])
    entries = _existing_lock_entries(tmp_path)
    assert sorted(entries) == ["claude", "codex"]
    assert entries["codex"]["managed_outputs"][0]["path"] == ".claude/skills/codex-copilot"


def test_assessment_no_longer_reports_unreadable_lock(tmp_path):
    from cc.core.ecosystem.project_integration import inspect_project_integration

    _write(tmp_path, [_claude(), _codex("0.15.0"), CODEX_ORG])
    blob = json.dumps(inspect_project_integration(tmp_path), default=str)
    assert "readable-project-lock" not in blob
    assert "unreadable-lock" not in blob
    _write(tmp_path, [_claude(), {"component": "mystery"}])
    blob = json.dumps(inspect_project_integration(tmp_path), default=str)
    assert "readable-project-lock" in blob
