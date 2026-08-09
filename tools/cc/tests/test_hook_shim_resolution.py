"""Item 1 (enforcement travels) -- the shim's own resolution/fail-open
behavior, its wiring into the recipe/transaction engine, the sticky
opt-out, the `ownership != framework` refusal, and the `cc doctor`
"registered vs. live" checkers.

`tests/hooks/test-shim-e2e.sh` proves the same chain end-to-end at the
shell level (matcher -> shim -> global rules -> deny). This file proves
the PYTHON-side production code that ships the shim to a project and
keeps `.claude/settings.json`'s registration honest -- the two halves
together are the actual coverage the plan calls for.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
from cc.core.ecosystem.mutations import (
    DEFAULT_HOOK_ENTRIES,
    DISABLED_MARKER,
    apply_settings_hook,
    list_sources,
)
from cc.core.ecosystem.project_reconciliation import assess_project, build_project_plans
from cc.core.ecosystem.reconciliation_recipes import _claude_setup as claude_setup
from cc.core.ecosystem.reconciliation_transaction import execute_reconciliation
from cc.core.ecosystem.reconciliation_types import RecipeOperationKind

from cc.commands import doctor as doctor_module
from cc.core.ecosystem import project_integration as integration_module
from cc.core.ecosystem import project_reconciliation as project_module
from cc.core.ecosystem import reconciliation_recipes as recipes

SHIM_SOURCE = Path(__file__).resolve().parents[3] / ".claude/hooks/copilot-hook.sh"


# ---------------------------------------------------------------------------
# Shared fixture helpers (mirrors tests/test_reconciliation_recipes.py's own
# `_write`/`_project`/`_framework_sources`/`_configure_sources` convention).
# ---------------------------------------------------------------------------


def _git(project: Path, *arguments: str) -> None:
    subprocess.run(("git", *arguments), cwd=project, check=True, capture_output=True, text=True)


def _project(tmp_path: Path, name: str = "project") -> Path:
    project = tmp_path / name
    project.mkdir()
    _git(project, "init", "-q")
    _git(project, "config", "user.email", "fixture@example.invalid")
    _git(project, "config", "user.name", "Fixture")
    return project


def _write(path: Path, value: str | bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(value, encoding="utf-8")
    path.chmod(mode)


def _framework_source(tmp_path: Path) -> Path:
    """A real, authoritative claude source -- `copilot-hook.sh` copied
    byte-for-byte from the actual repo file this task vendored, not a
    synthetic stand-in, so `_claude_setup()`'s materialized shim is the
    REAL shim under test."""
    source = tmp_path / "claude-source"
    _write(
        source / "VERSION.json",
        json.dumps({"framework": "5.13.3", "components": {"agents": {"frameworkAgents": ["me"]}}}),
    )
    _write(source / ".claude/commands/protocol.md", "protocol\n")
    _write(source / ".claude/commands/continue.md", "continue\n")
    _write(source / ".claude/fitness-check.sh", "#!/bin/sh\nexit 0\n", 0o755)
    _write(source / ".claude/hooks/copilot-hook.sh", SHIM_SOURCE.read_bytes(), 0o755)
    # A minimal STAND-IN for the real global session-start.sh -- just
    # enough for the shim's own resolution ladder (step 4: exec the
    # delegated script) to succeed end-to-end in tests that exercise
    # "live" enforcement (`cc doctor`'s hooks-enforcement-live checker,
    # TestShimScriptResolution). Deliberately not the real rule logic --
    # those tests live in tests/hooks/test-shim-e2e.sh against the ACTUAL
    # global scripts.
    _write(source / ".claude/hooks/session-start.sh", "#!/usr/bin/env bash\nexit 0\n", 0o755)
    _write(source / ".claude/agents/me.md", "me\n")
    _write(source / ".claude/agents/kc.md", "kc\n")
    return source


def _configure_source(monkeypatch: pytest.MonkeyPatch, claude: Path) -> None:
    def resolve(key: str) -> str | None:
        return str(claude) if key == "paths.claude_copilot_root" else None

    monkeypatch.setattr(recipes, "resolve_key", resolve)
    monkeypatch.setattr(project_module, "resolve_key", resolve)
    monkeypatch.setattr(integration_module, "resolve_key", resolve)


def _apply(project: Path, tmp_path: Path, *, component: str = "claude") -> dict[str, Any]:
    """Mirrors `commands/reconcile.py`'s `apply()` command: the guarded
    transaction (shim copy + settings merge), THEN the best-effort
    `apply_settings_hook()` follow-up that appends the `mutations[]`
    ledger row for content the transaction already wrote (see that
    module's `_adopt_settings_hook_ledger_rows()` docstring for why this
    is two steps, not one)."""
    assessment = assess_project(project, approved_root=tmp_path, selected_components=(component,))
    _, plans = build_project_plans([assessment], {str(project): (component,)})
    receipts = execute_reconciliation(
        [plans[0].transaction_plan()],
        run_id="run_" + "a" * 32,
        root=tmp_path / "transaction-state",
    )
    receipt = receipts[0]
    if component == "claude" and receipt["status"] in {"applied", "unchanged"}:
        apply_settings_hook(
            project,
            entries=DEFAULT_HOOK_ENTRIES,
            source="claude-copilot",
            component="claude",
            applied_by="test",
            _state_root=tmp_path / "settings-hook-state",
        )
    return receipt


# ---------------------------------------------------------------------------
# 1. The shim's OWN resolution/fail-open behavior (subprocess-level, the
#    real shim source, no framework machinery in the loop at all).
# ---------------------------------------------------------------------------


class TestShimScriptResolution:
    def _invoke(
        self, project: Path, event: str, payload: str, *, env_overrides: dict[str, str]
    ) -> subprocess.CompletedProcess:
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project), **env_overrides}
        return subprocess.run(
            ["bash", str(project / ".claude/hooks/copilot-hook.sh"), event],
            input=payload,
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )

    @pytest.fixture
    def project(self, tmp_path: Path) -> Path:
        target = tmp_path / "consumer"
        target.mkdir()
        _write(target / ".claude/hooks/copilot-hook.sh", SHIM_SOURCE.read_bytes(), 0o755)
        return target

    def test_delegates_to_a_present_global_install(self, tmp_path: Path, project: Path) -> None:
        hooks_root = tmp_path / "global/.claude/hooks"
        _write(hooks_root / "session-start.sh", "#!/usr/bin/env bash\nexit 0\n", 0o755)
        result = self._invoke(
            project, "session-start", "", env_overrides={"COPILOT_HOOKS_ROOT": str(hooks_root)}
        )
        assert result.returncode == 0
        assert "unavailable" not in result.stderr

    def test_state_dir_is_per_project_not_the_global_install(
        self, tmp_path: Path, project: Path
    ) -> None:
        hooks_root = tmp_path / "global/.claude/hooks"
        _write(
            hooks_root / "session-start.sh",
            '#!/usr/bin/env bash\nprintf \'%s\' "$COPILOT_HOOK_STATE_DIR" > "$CLAUDE_PROJECT_DIR/state-dir-seen.txt"\n',
            0o755,
        )
        self._invoke(
            project, "session-start", "", env_overrides={"COPILOT_HOOKS_ROOT": str(hooks_root)}
        )
        seen = (project / "state-dir-seen.txt").read_text(encoding="utf-8")
        assert seen == str(project / ".claude/hooks/state")

    @pytest.mark.parametrize("tool_name", ["Read", "Edit", "Write", "Agent"])
    def test_missing_install_fails_open_for_non_bash_tools(
        self, project: Path, tool_name: str
    ) -> None:
        payload = json.dumps({"session_id": "s1", "tool_name": tool_name, "tool_input": {}})
        result = self._invoke(
            project, "pretool-check", payload, env_overrides={"COPILOT_HOOKS_ROOT": "/nonexistent"}
        )
        assert result.returncode == 0
        assert "enforcement is unavailable" in result.stderr

    def test_missing_install_fails_closed_for_bash(self, project: Path) -> None:
        payload = json.dumps(
            {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "echo hi"}}
        )
        result = self._invoke(
            project, "pretool-check", payload, env_overrides={"COPILOT_HOOKS_ROOT": "/nonexistent"}
        )
        assert result.returncode == 2
        assert '"permissionDecision":"deny"' in result.stdout

    def test_fail_open_escape_hatch_downgrades_bash_back_to_open(self, project: Path) -> None:
        payload = json.dumps(
            {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "echo hi"}}
        )
        result = self._invoke(
            project,
            "pretool-check",
            payload,
            env_overrides={"COPILOT_HOOKS_ROOT": "/nonexistent", "COPILOT_HOOKS_FAIL_OPEN": "1"},
        )
        assert result.returncode == 0

    def test_copilot_required_marker_escalates_every_event_to_fail_closed(
        self, project: Path
    ) -> None:
        (project / ".claude/copilot-required").touch()
        payload = json.dumps({"session_id": "s1", "tool_name": "Read", "tool_input": {}})
        result = self._invoke(
            project, "pretool-check", payload, env_overrides={"COPILOT_HOOKS_ROOT": "/nonexistent"}
        )
        assert result.returncode == 2

    def test_copilot_required_marker_refuses_the_fail_open_escape_hatch(
        self, project: Path
    ) -> None:
        (project / ".claude/copilot-required").touch()
        payload = json.dumps(
            {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "echo hi"}}
        )
        result = self._invoke(
            project,
            "pretool-check",
            payload,
            env_overrides={"COPILOT_HOOKS_ROOT": "/nonexistent", "COPILOT_HOOKS_FAIL_OPEN": "1"},
        )
        assert result.returncode == 2

    def test_explicit_but_wrong_hooks_root_is_not_silently_replaced_by_the_ladder(
        self, tmp_path: Path, project: Path
    ) -> None:
        """An explicit (bad) $COPILOT_HOOKS_ROOT must be honored strictly,
        never silently overridden by falling through to
        $HOME/.claude/copilot -- otherwise a broken override could
        masquerade as a healthy install on a machine that happens to have
        one."""
        result = self._invoke(
            project, "session-start", "", env_overrides={"COPILOT_HOOKS_ROOT": "/nonexistent"}
        )
        assert "enforcement is unavailable" in result.stderr

    def test_version_skew_within_declared_range_is_silent(self, tmp_path: Path, project: Path) -> None:
        hooks_root = tmp_path / "global/.claude/hooks"
        _write(hooks_root / "session-start.sh", "#!/usr/bin/env bash\nexit 0\n", 0o755)
        _write(hooks_root / "PROTOCOL_VERSION", "1")
        result = self._invoke(
            project, "session-start", "", env_overrides={"COPILOT_HOOKS_ROOT": str(hooks_root)}
        )
        assert result.returncode == 0
        assert "skew" not in result.stderr

    def test_version_skew_outside_declared_range_is_advisory_not_blocking(
        self, tmp_path: Path, project: Path
    ) -> None:
        hooks_root = tmp_path / "global/.claude/hooks"
        _write(hooks_root / "session-start.sh", "#!/usr/bin/env bash\nexit 0\n", 0o755)
        _write(hooks_root / "PROTOCOL_VERSION", "99")
        result = self._invoke(
            project, "session-start", "", env_overrides={"COPILOT_HOOKS_ROOT": str(hooks_root)}
        )
        assert result.returncode == 0, "skew alone must never block delegation"
        assert "version skew" in result.stderr

    def test_protocol_hard_min_above_this_shims_max_is_treated_as_unreachable(
        self, tmp_path: Path, project: Path
    ) -> None:
        hooks_root = tmp_path / "global/.claude/hooks"
        _write(hooks_root / "session-start.sh", "#!/usr/bin/env bash\nexit 0\n", 0o755)
        _write(hooks_root / "PROTOCOL_HARD_MIN", "99")
        result = self._invoke(
            project, "session-start", "", env_overrides={"COPILOT_HOOKS_ROOT": str(hooks_root)}
        )
        assert result.returncode == 0  # SessionStart is fail-open
        assert "enforcement is unavailable" in result.stderr
        assert "older than the global install's minimum" in result.stderr


# ---------------------------------------------------------------------------
# 2. Recipe-engine wiring: `_claude_setup()`'s emitted operations, and a
#    full `execute_reconciliation()` round trip against a temp project.
# ---------------------------------------------------------------------------


class TestRecipeEngineWiring:
    def test_claude_setup_emits_a_shim_copy_and_a_settings_registration_operation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = _framework_source(tmp_path)
        _configure_source(monkeypatch, source)
        project = _project(tmp_path)

        operations = claude_setup(project, "claude")
        kinds = [op.kind for op in operations]
        assert RecipeOperationKind.REGISTER_SETTINGS_HOOKS in kinds
        shim_ops = [op for op in operations if op.target == ".claude/hooks/copilot-hook.sh"]
        assert len(shim_ops) == 1
        assert shim_ops[0].kind == RecipeOperationKind.COPY_FILE_FROM_SOURCE

        lock_op = next(op for op in operations if op.kind == RecipeOperationKind.UPSERT_LOCK_COMPONENT)
        recorded_paths = {
            f["path"] for f in lock_op.payload["component_entry"]["files"]
        }
        assert ".claude/hooks/copilot-hook.sh" in recorded_paths

    def test_full_apply_materializes_shim_executable_and_merges_foreign_settings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = _framework_source(tmp_path)
        _configure_source(monkeypatch, source)
        project = _project(tmp_path)

        # A human's own Discord Stop hook, convocation-shaped -- must
        # survive byte-for-byte alongside our own registration.
        foreign_settings = {
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "bash notify.sh"}]}
                ]
            },
            "theme": "dark",
        }
        _write(
            project / ".claude/settings.json",
            json.dumps(foreign_settings, indent=2) + "\n",
        )
        _git(project, "add", "-A")
        _git(project, "commit", "-qm", "human settings")

        receipt = _apply(project, tmp_path)
        assert receipt["status"] == "applied"

        shim = project / ".claude/hooks/copilot-hook.sh"
        assert shim.is_file()
        assert stat.S_IMODE(shim.stat().st_mode) == 0o755
        assert shim.read_bytes() == SHIM_SOURCE.read_bytes()

        settings = json.loads((project / ".claude/settings.json").read_text(encoding="utf-8"))
        assert settings["theme"] == "dark"
        assert settings["hooks"]["Stop"] == foreign_settings["hooks"]["Stop"]
        assert "PreToolUse" in settings["hooks"]
        assert "SessionStart" in settings["hooks"]
        assert "SubagentStop" in settings["hooks"]
        assert "UserPromptSubmit" in settings["hooks"]

        sources = list_sources(project)
        classifications = {row["classification"] for row in sources["hooks"]}
        assert classifications == {"ours", "foreign"}

    def test_idempotent_reapply_produces_zero_operations(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = _framework_source(tmp_path)
        _configure_source(monkeypatch, source)
        project = _project(tmp_path)

        first = _apply(project, tmp_path)
        assert first["status"] == "applied"
        _git(project, "add", "-A")
        _git(project, "commit", "-qm", "first apply")

        second_ops = claude_setup(project, "claude")
        non_lock_ops = [
            op for op in second_ops if op.kind != RecipeOperationKind.UPSERT_LOCK_COMPONENT
        ]
        assert non_lock_ops == [], (
            "a fully-registered, unmodified project must plan zero file/settings "
            f"operations on repeat; got {[op.kind for op in non_lock_ops]}"
        )


# ---------------------------------------------------------------------------
# 3. `ownership != framework`: a customized project's locally-modified shim
#    is never claimed/recorded, and is never silently overwritten.
# ---------------------------------------------------------------------------


class TestOwnershipRefusal:
    def test_locally_modified_shim_is_excluded_from_the_customized_lock_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cc.core.ecosystem.reconciliation_recipes import _claude_customized_lock_entry

        source = _framework_source(tmp_path)
        project = _project(tmp_path)
        _write(project / ".claude/hooks/copilot-hook.sh", "#!/bin/sh\n# project-owned edit\nexit 0\n", 0o755)

        entry = _claude_customized_lock_entry(source, project)
        recorded_paths = {f["path"] for f in entry["files"]}
        assert ".claude/hooks/copilot-hook.sh" not in recorded_paths, (
            "a project's own edit to the shim must never be silently claimed as "
            "verified framework content"
        )


# ---------------------------------------------------------------------------
# 4. Sticky opt-out: "removal must survive re-running setup."
# ---------------------------------------------------------------------------


class TestStickyOptOut:
    def test_disabled_marker_blocks_apply_settings_hook(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        (project / DISABLED_MARKER).parent.mkdir(parents=True, exist_ok=True)
        (project / DISABLED_MARKER).touch()

        outcome = apply_settings_hook(
            project,
            entries=DEFAULT_HOOK_ENTRIES,
            source="claude-copilot",
            component="claude",
            applied_by="test",
            _state_root=tmp_path / "state",
        )
        assert outcome.status == "disabled"
        assert not (project / ".claude/settings.json").exists()

    def test_force_bypasses_the_disabled_marker(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        (project / DISABLED_MARKER).parent.mkdir(parents=True, exist_ok=True)
        (project / DISABLED_MARKER).touch()

        outcome = apply_settings_hook(
            project,
            entries=DEFAULT_HOOK_ENTRIES,
            source="claude-copilot",
            component="claude",
            applied_by="test",
            force=True,
            _state_root=tmp_path / "state",
        )
        assert outcome.status == "applied"

    def test_disabled_marker_stops_claude_setup_from_replanning_the_shim_or_registration(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = _framework_source(tmp_path)
        _configure_source(monkeypatch, source)
        project = _project(tmp_path)
        (project / DISABLED_MARKER).parent.mkdir(parents=True, exist_ok=True)
        (project / DISABLED_MARKER).touch()

        operations = claude_setup(project, "claude")
        touched_targets = {op.target for op in operations}
        assert ".claude/hooks/copilot-hook.sh" not in touched_targets
        assert ".claude/settings.json" not in touched_targets
        # Other framework files are unaffected by the opt-out -- it is
        # scoped to hook enforcement, not the whole framework.
        assert ".claude/commands/protocol.md" in touched_targets

    def test_remove_disable_survives_a_subsequent_setup_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cc.core.ecosystem.mutations import remove_settings_hook

        source = _framework_source(tmp_path)
        _configure_source(monkeypatch, source)
        project = _project(tmp_path)

        first = _apply(project, tmp_path)
        assert first["status"] == "applied"
        _git(project, "add", "-A")
        _git(project, "commit", "-qm", "first apply")

        sources = list_sources(project)
        mutation_id = next(
            row["mutation_id"] for row in sources["hooks"] if row["classification"] == "ours"
        )
        removal = remove_settings_hook(
            project, mutation_id=mutation_id, disable=True, _state_root=tmp_path / "settings-state"
        )
        assert removal.status == "removed"
        assert (project / DISABLED_MARKER).is_file()

        settings_after_remove = json.loads(
            (project / ".claude/settings.json").read_text(encoding="utf-8")
        )
        assert "PreToolUse" not in settings_after_remove.get("hooks", {})

        # Re-running setup/repair must NOT resurrect the registration.
        operations = claude_setup(project, "claude")
        assert ".claude/settings.json" not in {op.target for op in operations}


# ---------------------------------------------------------------------------
# 5. `cc doctor`: "registered" (static) vs. "live" (dynamic, actually runs).
# ---------------------------------------------------------------------------


class TestDoctorEnforcementCheckers:
    def test_unregistered_project_reports_both_checkers_failing(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        _write(
            project / "copilot.lock.json",
            json.dumps(
                {
                    "schema_version": "1.0",
                    "components": [{"component": "claude", "version": "1.0.0", "files": []}],
                }
            ),
        )
        checkers = doctor_module._hook_enforcement_checkers(project)
        by_id = {c.id: c for c in checkers}
        assert by_id["hooks-registered-in-project"].severity == "fail"
        assert by_id["hooks-enforcement-live"].severity == "fail"

    def test_project_without_a_lock_emits_no_checkers(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        assert doctor_module._hook_enforcement_checkers(project) == []

    def test_fully_registered_project_with_a_present_install_reports_live(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = _framework_source(tmp_path)
        _configure_source(monkeypatch, source)
        project = _project(tmp_path)
        receipt = _apply(project, tmp_path)
        assert receipt["status"] == "applied"

        # Point the shim's OWN resolution ladder (step 2: `cc config get`,
        # step 3: $HOME/.claude/copilot) at this fixture's source by using
        # the explicit override, matching how the real shim would resolve
        # on a properly-configured machine.
        monkeypatch.setenv("COPILOT_HOOKS_ROOT", str(source / ".claude/hooks"))
        checkers = doctor_module._hook_enforcement_checkers(project)
        by_id = {c.id: c for c in checkers}
        assert by_id["hooks-registered-in-project"].severity == "pass"
        assert by_id["hooks-enforcement-live"].severity == "pass"

    def test_registered_but_install_removed_reports_registered_but_not_live(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = _framework_source(tmp_path)
        _configure_source(monkeypatch, source)
        project = _project(tmp_path)
        receipt = _apply(project, tmp_path)
        assert receipt["status"] == "applied"

        monkeypatch.setenv("COPILOT_HOOKS_ROOT", "/nonexistent")
        checkers = doctor_module._hook_enforcement_checkers(project)
        by_id = {c.id: c for c in checkers}
        assert by_id["hooks-registered-in-project"].severity == "pass"
        assert by_id["hooks-enforcement-live"].severity == "fail"
        assert "not live" in by_id["hooks-enforcement-live"].detail
