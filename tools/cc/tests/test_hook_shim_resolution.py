"""The shim's own resolution/fail-open behavior (`.claude/hooks/copilot-hook.sh`).

`tests/hooks/test-shim-e2e.sh` proves the same chain end-to-end at the shell level
(matcher -> shim -> global rules -> deny). The recipe-engine wiring, sticky opt-out,
ownership refusal and per-project `cc doctor` registered/live checkers that used to live
here were retired with the per-project copy model.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

SHIM_SOURCE = Path(__file__).resolve().parents[3] / ".claude/hooks/copilot-hook.sh"


# ---------------------------------------------------------------------------
# Fixture helper
# ---------------------------------------------------------------------------


def _write(path: Path, value: str | bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(value, encoding="utf-8")
    path.chmod(mode)


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
