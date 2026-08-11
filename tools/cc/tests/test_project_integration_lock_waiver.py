"""RC-4 fix #3 -- close the `customized-preserve` waiver hole.

`project_integration.py:539` used to set `absent_required = []`
unconditionally whenever `ownership_mode == "customized-preserve"`, so a
project could reach a `ready` classification without ever proving any of
its required lock paths existed (`EXISTING-VERIFICATION.md` section 2's two
live proofs: `copilot-control-tower` reaching `claude -> ready` with 2 of 4
required paths recorded, and a synthetic minimum -- `CLAUDE.md` + `.mcp.json`
+ an empty-`files` customized-preserve lock -- reaching `claude -> ready`
with zero agents, skills, or commands on disk).

The fix separates two distinct concerns: `customized-preserve` legitimately
waives matching a required path's checksum against the framework's
canonical bytes (that is the whole point of preserving a local edit to it);
it must never also waive that path's EXISTENCE. This file proves the fix
directly against `_verify_lock_entry` (never re-implementing its logic) and
against the full `inspect_project_integration` classification it feeds.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from cc.core.ecosystem.project_integration import (
    _CLAUDE_REQUIRED_LOCK_PATHS,
    _verify_lock_entry,
    inspect_project_integration,
)
from cc.core.ecosystem.project_locking import fingerprint_file_payload

from cc.core.ecosystem import project_integration


def _write(path: Path, value: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    path.chmod(mode)


def _write_marker_files(root: Path) -> None:
    _write(root / "CLAUDE.md", "## Claude Copilot\n\nProject entry.\n")
    _write(root / ".mcp.json", json.dumps({"mcpServers": {}}))


def _entry(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "component": "claude",
        "version": "1.0.0",
        "ownership_mode": "customized-preserve",
        "files": [],
    }
    base.update(overrides)
    return base


def _claude_md_managed_output(root: Path) -> dict[str, str]:
    target = root / "CLAUDE.md"
    mode = target.stat().st_mode & 0o777
    fingerprint = fingerprint_file_payload(target.read_bytes(), mode=mode)
    return {"path": "CLAUDE.md", "kind": "managed-text", "fingerprint": fingerprint}


class TestVerifyLockEntryClosesTheWaiverHole:
    def test_required_path_neither_recorded_nor_on_disk_is_flagged_absent(
        self, tmp_path: Path
    ) -> None:
        ok, _evidence, missing, _fingerprint = _verify_lock_entry(
            tmp_path, "claude", _entry()
        )
        assert ok is False
        detail = " ".join(item["detail"] for item in missing)
        for path in _CLAUDE_REQUIRED_LOCK_PATHS:
            assert path in detail

    def test_required_path_present_on_disk_but_unrecorded_is_not_flagged(
        self, tmp_path: Path
    ) -> None:
        """The customization case: a required path was locally edited (so
        its checksum no longer matches the framework's canonical bytes and
        it was correctly excluded from `files[]`), but it is still
        genuinely present. Preserving it must not read as "absent"."""

        _write_marker_files(tmp_path)
        for path in _CLAUDE_REQUIRED_LOCK_PATHS:
            _write(tmp_path / path, "locally customized\n")

        entry = _entry(managed_outputs=[_claude_md_managed_output(tmp_path)])
        ok, _evidence, missing, _fingerprint = _verify_lock_entry(
            tmp_path, "claude", entry
        )
        assert ok is True, missing

    def test_mixed_recorded_and_present_and_genuinely_missing(
        self, tmp_path: Path
    ) -> None:
        """Reproduces the live `copilot-control-tower` shape: some required
        paths are recorded (framework-pristine), one is present but
        customized (unrecorded, still real), and one is genuinely absent.
        Only the genuinely absent one may fail."""

        recorded_path = ".claude/commands/continue.md"
        _write(tmp_path / recorded_path, "continue\n")
        customized_path = ".claude/commands/protocol.md"
        _write(tmp_path / customized_path, "customized protocol\n")
        # ".claude/fitness-check.sh" and ".claude/hooks/copilot-hook.sh"
        # are never written -- genuinely missing.

        entry = _entry(
            files=[
                {
                    "path": recorded_path,
                    "ownership": "framework",
                    "checksum": "sha256:"
                    + hashlib.sha256(
                        (tmp_path / recorded_path).read_bytes()
                    ).hexdigest(),
                }
            ]
        )
        ok, _evidence, missing, _fingerprint = _verify_lock_entry(
            tmp_path, "claude", entry
        )
        assert ok is False
        detail = " ".join(item["detail"] for item in missing)
        assert ".claude/fitness-check.sh" in detail
        assert ".claude/hooks/copilot-hook.sh" in detail
        assert customized_path not in detail
        assert recorded_path not in detail

    def test_full_mode_is_unaffected_disk_presence_never_substitutes(
        self, tmp_path: Path
    ) -> None:
        """Full mode keeps its existing, stricter discipline: a required
        path must be RECORDED, not merely present on disk -- unchanged by
        this fix, which only touches the `customized-preserve` branch."""

        for path in _CLAUDE_REQUIRED_LOCK_PATHS:
            _write(tmp_path / path, "content\n")
        _write(tmp_path / ".claude/agents/cw.md", "cw\n")

        entry = {
            "component": "claude",
            "version": "1.0.0",
            # ownership_mode absent -> defaults to "full". One unrelated
            # framework file keeps `files[]` non-empty (the required-path
            # loop, not the "no files at all" structural gate, is what
            # this test targets).
            "files": [
                {
                    "path": ".claude/agents/cw.md",
                    "ownership": "framework",
                    "checksum": "sha256:"
                    + hashlib.sha256(b"cw\n").hexdigest(),
                }
            ],
        }
        ok, _evidence, missing, _fingerprint = _verify_lock_entry(
            tmp_path, "claude", entry
        )
        assert ok is False
        detail = " ".join(item["detail"] for item in missing)
        for path in _CLAUDE_REQUIRED_LOCK_PATHS:
            assert path in detail


class TestVerifyLockEntryClosesTheSymlinkAncestorBypass:
    """Security-review follow-up to RC-4: the fix above closed the `[]`
    waiver hole by checking required-path EXISTENCE independently of the
    checksum waiver -- but it treated `_safe_relative_target` returning
    `None` (an unsafe/ancestor-symlink case) as merely inconclusive and
    skipped it rather than counting it absent. Making `.claude` itself a
    symlink (to any target, even an empty directory), with a
    `customized-preserve` entry recording `files: []` and a
    self-consistent `CLAUDE.md` managed-output fingerprint, made every one
    of the four required paths resolve to `None` and reach
    `verified: True, missing: []` -- despite none of them existing at any
    real path. The non-symlink control case (no `.claude` at all) was
    already correctly caught; the symlink was the sole differentiator.
    These paths never nest under the one sanctioned ancestor-symlink
    pattern in this codebase (`.claude/skills` -> the external Knowledge
    hierarchy; see `_verify_internal_skill_link`), so failing closed here
    cannot break it."""

    def test_claude_as_symlink_to_empty_dir_no_longer_bypasses_required_paths(
        self, tmp_path: Path
    ) -> None:
        _write_marker_files(tmp_path)
        elsewhere = tmp_path / "_elsewhere"
        elsewhere.mkdir()
        (tmp_path / ".claude").symlink_to(elsewhere, target_is_directory=True)

        entry = _entry(managed_outputs=[_claude_md_managed_output(tmp_path)])
        ok, _evidence, missing, _fingerprint = _verify_lock_entry(
            tmp_path, "claude", entry
        )
        assert ok is False, "the .claude-symlink bypass must be caught, not waived"
        detail = " ".join(item["detail"] for item in missing)
        for path in _CLAUDE_REQUIRED_LOCK_PATHS:
            assert path in detail

    def test_claude_as_symlink_control_case_no_dot_claude_at_all_is_also_caught(
        self, tmp_path: Path
    ) -> None:
        """The non-symlink control from the security review: no `.claude`
        at all. Kept alongside the symlink case above so that case is
        proven to be the sole differentiator, not an artifact of some
        other difference in the fixture."""
        _write_marker_files(tmp_path)

        entry = _entry(managed_outputs=[_claude_md_managed_output(tmp_path)])
        ok, _evidence, missing, _fingerprint = _verify_lock_entry(
            tmp_path, "claude", entry
        )
        assert ok is False
        detail = " ".join(item["detail"] for item in missing)
        for path in _CLAUDE_REQUIRED_LOCK_PATHS:
            assert path in detail

    def test_codex_plugins_as_symlink_to_empty_dir_no_longer_bypasses_required_paths(
        self, tmp_path: Path
    ) -> None:
        """The same bypass shape against the Codex required paths, which
        nest under `plugins/codex-copilot/` rather than `.claude/`. A
        self-consistent `AGENTS.md` managed-output fingerprint is supplied
        so the "no verified bounded output" structural gate does not mask
        which check actually catches this -- isolating the exact
        required-path bypass this fix closes."""
        agents_md = tmp_path / "AGENTS.md"
        _write(agents_md, "## Codex Copilot\n\n./plugins/codex-copilot\n")
        elsewhere = tmp_path / "_elsewhere"
        elsewhere.mkdir()
        (tmp_path / "plugins").mkdir()
        (tmp_path / "plugins/codex-copilot").symlink_to(
            elsewhere, target_is_directory=True
        )

        mode = agents_md.stat().st_mode & 0o777
        agents_fingerprint = fingerprint_file_payload(
            agents_md.read_bytes(), mode=mode
        )
        entry = {
            "component": "codex",
            "version": "1.0.0",
            "ownership_mode": "customized-preserve",
            "files": [],
            "managed_outputs": [
                {
                    "path": "AGENTS.md",
                    "kind": "managed-text",
                    "fingerprint": agents_fingerprint,
                }
            ],
        }
        ok, _evidence, missing, _fingerprint = _verify_lock_entry(
            tmp_path, "codex", entry
        )
        assert ok is False
        detail = " ".join(item["detail"] for item in missing)
        assert "plugins/codex-copilot/.codex-plugin/plugin.json" in detail
        assert "scripts/copilot-gate.sh" in detail


class TestRecognizedKnowledgeLinkCarveOutIsNarrow:
    """Fixing the symlink-ancestor bypass above by simply failing closed on
    every `None` broke the legitimate `legacy-knowledge-links` recipe family
    (`.claude/commands` -> a configured `paths.knowledge_repo` entry), which
    genuinely nests `.claude/commands/protocol.md` and
    `.claude/commands/continue.md` under a symlink. The fix instead added a
    named recognizer for exactly that shape
    (`_recognized_read_only_knowledge_link` /
    `_required_path_exists_through_recognized_knowledge_link`). These tests
    prove that recognizer is narrow -- it proves existence through the one
    sanctioned link, and nothing else, rather than becoming a new blanket
    carve-out."""

    def test_configured_knowledge_repo_link_proves_required_paths_exist(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "project"
        knowledge = tmp_path / "knowledge-copilot"
        _write(knowledge / ".claude/commands/protocol.md", "shared protocol\n")
        _write(knowledge / ".claude/commands/continue.md", "shared continue\n")
        _write_marker_files(project)
        _write(project / ".claude/fitness-check.sh", "#!/bin/sh\n")
        _write(project / ".claude/hooks/copilot-hook.sh", "#!/bin/sh\n")
        (project / ".claude/commands").symlink_to(
            knowledge / ".claude/commands", target_is_directory=True
        )

        monkeypatch.setattr(
            project_integration,
            "resolve_key",
            lambda key: {"paths.knowledge_repo": [str(knowledge)]}.get(key),
        )

        entry = _entry(
            files=[
                {
                    "path": ".claude/fitness-check.sh",
                    "ownership": "framework",
                    "checksum": "sha256:"
                    + hashlib.sha256(b"#!/bin/sh\n").hexdigest(),
                },
                {
                    "path": ".claude/hooks/copilot-hook.sh",
                    "ownership": "framework",
                    "checksum": "sha256:"
                    + hashlib.sha256(b"#!/bin/sh\n").hexdigest(),
                },
            ],
            managed_outputs=[_claude_md_managed_output(project)],
        )
        ok, _evidence, missing, _fingerprint = _verify_lock_entry(
            project, "claude", entry
        )
        assert ok is True, missing

    def test_dot_claude_commands_link_to_unconfigured_target_still_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A `.claude/commands` symlink that resolves somewhere OTHER than
        the configured `paths.knowledge_repo` (stale, misconfigured, or
        attacker-planted) must still fail closed -- the recognizer checks
        the resolved target, not merely the leaf name `.claude/commands`."""

        project = tmp_path / "project"
        unconfigured = tmp_path / "not-the-knowledge-repo" / "commands"
        _write(unconfigured / "protocol.md", "protocol\n")
        _write(unconfigured / "continue.md", "continue\n")
        _write_marker_files(project)
        (project / ".claude").mkdir(parents=True, exist_ok=True)
        (project / ".claude/commands").symlink_to(
            unconfigured, target_is_directory=True
        )

        monkeypatch.setattr(
            project_integration,
            "resolve_key",
            lambda key: {
                "paths.knowledge_repo": [str(tmp_path / "knowledge-copilot")]
            }.get(key),
        )

        entry = _entry(managed_outputs=[_claude_md_managed_output(project)])
        ok, _evidence, missing, _fingerprint = _verify_lock_entry(
            project, "claude", entry
        )
        assert ok is False
        detail = " ".join(item["detail"] for item in missing)
        assert ".claude/commands/protocol.md" in detail
        assert ".claude/commands/continue.md" in detail


class TestInspectProjectIntegrationNoLongerReadyByWaiver:
    def test_synthetic_minimum_no_longer_classifies_ready(self, tmp_path: Path) -> None:
        """`EXISTING-VERIFICATION.md` section 2 "Proof 2": `CLAUDE.md` +
        `.mcp.json` + a `files: []` customized-preserve lock used to
        classify `claude -> ready` with zero agents, skills, or commands on
        disk. After the fix it must not."""

        _write_marker_files(tmp_path)
        lock = {
            "schema_version": "1.0",
            "components": [
                {
                    "component": "claude",
                    "version": "1.0.0",
                    "ownership_mode": "customized-preserve",
                    "files": [],
                }
            ],
        }
        _write(tmp_path / "copilot.lock.json", json.dumps(lock))

        report = inspect_project_integration(tmp_path, detail=False)
        classification = next(
            item["classification"]
            for item in report["components"]
            if item["component"] == "claude"
        )
        assert classification != "ready"

    def test_dot_claude_symlink_fixture_no_longer_classifies_ready(
        self, tmp_path: Path
    ) -> None:
        """The security review's exact reproduced bypass: make `.claude` a
        symlink (target: any directory, even an empty one), write
        `copilot.lock.json` with `ownership_mode: customized-preserve` and
        `files: []`, and a self-consistent `CLAUDE.md` managed-output
        fingerprint. `_verify_lock_entry` used to return
        `verified: True, missing: []` despite none of the four required
        framework files existing at any real path -- the symlink was the
        sole differentiator from the (correctly caught) no-`.claude`
        control case in `test_synthetic_minimum_no_longer_classifies_ready`
        above."""

        _write_marker_files(tmp_path)
        elsewhere = tmp_path / "_elsewhere"
        elsewhere.mkdir()
        (tmp_path / ".claude").symlink_to(elsewhere, target_is_directory=True)

        lock = {
            "schema_version": "1.0",
            "components": [
                {
                    "component": "claude",
                    "version": "1.0.0",
                    "ownership_mode": "customized-preserve",
                    "files": [],
                    "managed_outputs": [_claude_md_managed_output(tmp_path)],
                }
            ],
        }
        _write(tmp_path / "copilot.lock.json", json.dumps(lock))

        report = inspect_project_integration(tmp_path, detail=False)
        classification = next(
            item["classification"]
            for item in report["components"]
            if item["component"] == "claude"
        )
        assert classification != "ready"

    def test_control_tower_shaped_fixture_no_longer_ready_by_waiver(
        self, tmp_path: Path
    ) -> None:
        """2 of 4 required paths recorded under `customized-preserve`, and
        the other two genuinely absent from disk -- must not classify
        `ready` (matches the live `copilot-control-tower` proof: it is
        `.claude/hooks/copilot-hook.sh` that is missing, RC-1's own
        consequence)."""

        _write_marker_files(tmp_path)
        _write(tmp_path / ".claude/commands/continue.md", "continue\n")
        _write(tmp_path / ".claude/fitness-check.sh", "#!/bin/sh\n")

        lock = {
            "schema_version": "1.0",
            "components": [
                {
                    "component": "claude",
                    "version": "1.0.0",
                    "ownership_mode": "customized-preserve",
                    "files": [
                        {
                            "path": ".claude/commands/continue.md",
                            "ownership": "framework",
                            "checksum": "sha256:"
                            + hashlib.sha256(b"continue\n").hexdigest(),
                        },
                        {
                            "path": ".claude/fitness-check.sh",
                            "ownership": "framework",
                            "checksum": "sha256:"
                            + hashlib.sha256(b"#!/bin/sh\n").hexdigest(),
                        },
                    ],
                }
            ],
        }
        _write(tmp_path / "copilot.lock.json", json.dumps(lock))

        report = inspect_project_integration(tmp_path, detail=False)
        classification = next(
            item["classification"]
            for item in report["components"]
            if item["component"] == "claude"
        )
        assert classification != "ready"

    def test_customized_preserve_with_every_required_path_genuinely_present_stays_ready(
        self, tmp_path: Path
    ) -> None:
        """The honest case must keep working: every required path is
        genuinely on disk (some recorded, one customized-and-unrecorded) --
        this is a legitimate `ready`, not a waiver."""

        _write_marker_files(tmp_path)
        recorded_files = []
        for path in _CLAUDE_REQUIRED_LOCK_PATHS:
            if path == ".claude/commands/protocol.md":
                # Locally customized: present, but deliberately not
                # recorded (its checksum would not match canonical).
                _write(tmp_path / path, "customized\n")
                continue
            content = f"{path}\n"
            _write(tmp_path / path, content)
            recorded_files.append(
                {
                    "path": path,
                    "ownership": "framework",
                    "checksum": "sha256:"
                    + hashlib.sha256(content.encode("utf-8")).hexdigest(),
                }
            )

        lock = {
            "schema_version": "1.0",
            "components": [
                {
                    "component": "claude",
                    "version": "1.0.0",
                    "ownership_mode": "customized-preserve",
                    "files": recorded_files,
                }
            ],
        }
        _write(tmp_path / "copilot.lock.json", json.dumps(lock))

        report = inspect_project_integration(tmp_path, detail=False)
        classification = next(
            item["classification"]
            for item in report["components"]
            if item["component"] == "claude"
        )
        assert classification == "ready"
