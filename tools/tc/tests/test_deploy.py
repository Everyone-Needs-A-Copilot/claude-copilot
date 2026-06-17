"""Tests for `tc deploy wait` command."""

from __future__ import annotations

import json
import os
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_task(cli) -> int:
    result = cli(["task", "create", "--title", "Deploy Task", "--json"])
    return json.loads(result.output)["id"]


def _make_trigger_response(deployment_uuid: str = "deploy-uuid-123"):
    """Return a mock CompletedProcess for a successful trigger."""
    m = MagicMock()
    m.returncode = 0
    m.stdout = json.dumps(
        {"deployment_uuid": deployment_uuid, "message": "Deployment triggered."}
    )
    m.stderr = ""
    return m


def _make_status_response(status: str = "finished", logs_url: Optional[str] = None):
    """Return a mock CompletedProcess for a status poll."""
    payload: dict = {"status": status}
    if logs_url:
        payload["logs_url"] = logs_url
    m = MagicMock()
    m.returncode = 0
    m.stdout = json.dumps(payload)
    m.stderr = ""
    return m


def _make_ok_response(stdout: str = "ok"):
    m = MagicMock()
    m.returncode = 0
    m.stdout = stdout
    m.stderr = ""
    return m


def _make_error_response(returncode: int = 1, stderr: str = "error"):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = ""
    m.stderr = stderr
    return m


# ---------------------------------------------------------------------------
# Mock factory: availability check → trigger → poll(s)
# All tests mock tc.commands.deploy._run_copilot to avoid intercepting
# unrelated subprocess calls (git, etc.).
# ---------------------------------------------------------------------------


def _copilot_mock(
    *,
    check_ok: bool = True,
    trigger_uuid: str = "dep-uuid",
    poll_status: str = "finished",
    poll_logs_url: Optional[str] = None,
    trigger_returncode: int = 0,
    trigger_stdout: Optional[str] = None,
):
    """Return a side_effect callable for _run_copilot.

    Call order:
      0 → availability check (coolify deploy --help)
      1 → trigger (coolify deploy trigger ...)
      2+ → poll (coolify deploy get ...)
    """
    call_count = 0

    def side_effect(args):
        nonlocal call_count
        idx = call_count
        call_count += 1

        if idx == 0:
            # availability check
            if check_ok:
                return _make_ok_response("help text")
            else:
                return _make_error_response(1, "not found")

        if idx == 1:
            # trigger
            if trigger_stdout is not None:
                m = MagicMock()
                m.returncode = trigger_returncode
                m.stdout = trigger_stdout
                m.stderr = ""
                return m
            if trigger_returncode != 0:
                return _make_error_response(trigger_returncode, "connection refused")
            return _make_trigger_response(trigger_uuid)

        # poll
        return _make_status_response(poll_status, poll_logs_url)

    return side_effect


# ---------------------------------------------------------------------------
# CLI check helper
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _get_deploy_cli — config resolution
# ---------------------------------------------------------------------------


def _inject_cc_config_mock(resolve_key_return_value):
    """Context manager: inject a fake cc.core.config into sys.modules.

    The tc test environment does not install the cc package, so we inject
    a lightweight module stub instead of using ``patch("cc.core.config..."``.
    Returns a context manager that cleans up after itself.
    """
    import sys
    import types
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        originals = {}
        for name in ("cc", "cc.core", "cc.core.config"):
            originals[name] = sys.modules.get(name)

        cc_mod = types.ModuleType("cc")
        cc_core_mod = types.ModuleType("cc.core")
        cc_config_mod = types.ModuleType("cc.core.config")
        cc_config_mod.resolve_key = lambda key: (
            resolve_key_return_value if key == "deploy.cli" else None
        )
        sys.modules["cc"] = cc_mod
        sys.modules["cc.core"] = cc_core_mod
        sys.modules["cc.core.config"] = cc_config_mod
        try:
            yield
        finally:
            for name, orig in originals.items():
                if orig is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = orig

    return _ctx()


class TestGetDeployCli:
    """_get_deploy_cli resolves the CLI command from env / cc config / default."""

    def test_default_when_nothing_configured(self):
        """No env var, no cc config → default (python -m copilot_cli) is used."""
        from tc.commands.deploy import _get_deploy_cli, _DEPLOY_CLI_DEFAULT
        import shlex

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CC_DEPLOY_CLI", None)
            # cc not importable in this env → falls back to default
            result = _get_deploy_cli()
        assert result == shlex.split(_DEPLOY_CLI_DEFAULT)

    def test_env_var_overrides_default(self):
        """CC_DEPLOY_CLI env var wins over everything."""
        from tc.commands.deploy import _get_deploy_cli

        with patch.dict(os.environ, {"CC_DEPLOY_CLI": "my-deploy-tool --profile prod"}):
            result = _get_deploy_cli()
        assert result == ["my-deploy-tool", "--profile", "prod"]

    def test_env_var_overrides_cc_config(self):
        """CC_DEPLOY_CLI beats cc config even when cc config is set."""
        from tc.commands.deploy import _get_deploy_cli

        with patch.dict(os.environ, {"CC_DEPLOY_CLI": "env-tool"}):
            with _inject_cc_config_mock("config-tool"):
                result = _get_deploy_cli()
        assert result == ["env-tool"]

    def test_cc_config_overrides_default(self):
        """deploy.cli from cc config overrides the built-in default."""
        from tc.commands.deploy import _get_deploy_cli

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CC_DEPLOY_CLI", None)
            with _inject_cc_config_mock("custom-cli deploy"):
                result = _get_deploy_cli()
        assert result == ["custom-cli", "deploy"]

    def test_cc_import_failure_falls_back_to_default(self):
        """If cc.core.config raises ImportError, fall back to built-in default."""
        from tc.commands.deploy import _get_deploy_cli, _DEPLOY_CLI_DEFAULT
        import shlex

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CC_DEPLOY_CLI", None)
            # Inject a stub that raises on import of resolve_key
            with _inject_cc_config_mock(None):
                import sys

                # Overwrite the stub's resolve_key to raise
                sys.modules["cc.core.config"].resolve_key = MagicMock(
                    side_effect=ImportError("cc not found")
                )
                result = _get_deploy_cli()
        assert result == shlex.split(_DEPLOY_CLI_DEFAULT)

    def test_run_copilot_uses_configured_cli(self):
        """_run_copilot prepends the configured CLI prefix."""
        from tc.commands.deploy import _run_copilot

        with patch("tc.commands.deploy._get_deploy_cli", return_value=["my-cli"]):
            with patch("tc.commands.deploy.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                _run_copilot(["arg1", "arg2"])
        mock_run.assert_called_once()
        called_cmd = mock_run.call_args[0][0]
        assert called_cmd == ["my-cli", "arg1", "arg2"]


class TestCliAvailabilityCheck:
    """_check_cli_available exits with code 4 when copilot_cli is absent."""

    def test_exits_4_when_cli_unavailable(self, cli):
        """When copilot_cli check fails, deploy wait exits with code 4."""
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.return_value = _make_error_response(1, "not found")
            result = cli(["deploy", "wait", "my-app"])
        assert result.exit_code == 4

    def test_dry_run_skips_cli_check(self, cli):
        """--dry-run skips the availability check entirely."""
        # No mocking needed — dry-run does not call _run_copilot at all
        result = cli(["deploy", "wait", "my-app", "--dry-run"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


class TestDeployWaitSuccess:
    """Deploy succeeds and WP is stored."""

    def test_success_exits_0(self, cli):
        task_id = _setup_task(cli)
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.side_effect = _copilot_mock()
            result = cli(
                [
                    "deploy",
                    "wait",
                    "my-app",
                    "--task-id",
                    str(task_id),
                    "--json",
                ]
            )
        assert result.exit_code == 0

    def test_success_json_output(self, cli):
        task_id = _setup_task(cli)
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.side_effect = _copilot_mock(
                trigger_uuid="uuid-abc",
                poll_logs_url="https://coolify/logs/uuid-abc",
            )
            result = cli(
                [
                    "deploy",
                    "wait",
                    "my-app",
                    "--task-id",
                    str(task_id),
                    "--json",
                ]
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["deploy_status"] == "success"
        assert data["deployment_uuid"] == "uuid-abc"
        assert data["app_id"] == "my-app"
        assert data["test_status"] == "skipped"
        assert data["wp_id"] is not None

    def test_success_stores_deploy_report_wp(self, cli):
        task_id = _setup_task(cli)
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.side_effect = _copilot_mock(trigger_uuid="uuid-xyz")
            cli(
                [
                    "deploy",
                    "wait",
                    "my-app",
                    "--task-id",
                    str(task_id),
                    "--json",
                ]
            )
        # Verify WP was stored with correct type
        wp_list = cli(["wp", "list", "--type", "deploy_report", "--json"])
        wps = json.loads(wp_list.output)
        assert len(wps) == 1
        assert wps[0]["type"] == "deploy_report"

    def test_success_wp_content_is_valid_json(self, cli):
        task_id = _setup_task(cli)
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.side_effect = _copilot_mock(trigger_uuid="uuid-content")
            result = cli(
                [
                    "deploy",
                    "wait",
                    "my-app",
                    "--task-id",
                    str(task_id),
                    "--env",
                    "production",
                    "--json",
                ]
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        wp_result = cli(["wp", "get", str(data["wp_id"]), "--json"])
        wp_data = json.loads(wp_result.output)
        report = json.loads(wp_data["content"])
        assert report["app_id"] == "my-app"
        assert report["deploy_status"] == "success"
        assert report["environment"] == "production"
        assert report["deployment_uuid"] == "uuid-content"

    def test_human_readable_output(self, cli):
        task_id = _setup_task(cli)
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.side_effect = _copilot_mock()
            result = cli(
                [
                    "deploy",
                    "wait",
                    "my-app",
                    "--task-id",
                    str(task_id),
                ]
            )
        assert result.exit_code == 0
        assert "OK" in result.output
        assert "my-app" in result.output

    def test_no_task_id_skips_wp_storage(self, cli):
        """When --task-id is omitted, no WP is stored."""
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.side_effect = _copilot_mock()
            result = cli(["deploy", "wait", "my-app", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["wp_id"] is None

    def test_branch_flag_overrides_git(self, cli):
        task_id = _setup_task(cli)
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.side_effect = _copilot_mock()
            result = cli(
                [
                    "deploy",
                    "wait",
                    "my-app",
                    "--branch",
                    "release/v2",
                    "--task-id",
                    str(task_id),
                    "--json",
                ]
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["branch"] == "release/v2"

    def test_env_flag_stored_in_wp(self, cli):
        task_id = _setup_task(cli)
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.side_effect = _copilot_mock()
            result = cli(
                [
                    "deploy",
                    "wait",
                    "my-app",
                    "--env",
                    "production",
                    "--task-id",
                    str(task_id),
                    "--json",
                ]
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        wp_result = cli(["wp", "get", str(data["wp_id"]), "--json"])
        report = json.loads(json.loads(wp_result.output)["content"])
        assert report["environment"] == "production"


# ---------------------------------------------------------------------------
# Deploy-failure path
# ---------------------------------------------------------------------------


class TestDeployWaitFailed:
    """Deploy fails → exit 1 with failure metadata."""

    def test_failed_exits_1(self, cli):
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.side_effect = _copilot_mock(
                poll_status="failed",
                poll_logs_url="https://coolify/logs/dep-fail",
            )
            result = cli(["deploy", "wait", "my-app"])
        assert result.exit_code == 1

    def test_failed_json_deploy_status(self, cli):
        task_id = _setup_task(cli)
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.side_effect = _copilot_mock(
                poll_status="failed",
                poll_logs_url="https://coolify/logs/dep-fail",
            )
            result = cli(
                [
                    "deploy",
                    "wait",
                    "my-app",
                    "--task-id",
                    str(task_id),
                    "--json",
                ]
            )
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["deploy_status"] == "failed"
        assert data["logs_url"] == "https://coolify/logs/dep-fail"

    def test_failed_wp_stores_failure_status(self, cli):
        task_id = _setup_task(cli)
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.side_effect = _copilot_mock(
                poll_status="failed",
                poll_logs_url="https://coolify/logs/dep-fail",
            )
            result = cli(
                [
                    "deploy",
                    "wait",
                    "my-app",
                    "--task-id",
                    str(task_id),
                    "--json",
                ]
            )
        data = json.loads(result.output)
        wp_result = cli(["wp", "get", str(data["wp_id"]), "--json"])
        report = json.loads(json.loads(wp_result.output)["content"])
        assert report["deploy_status"] == "failed"
        assert report["logs_url"] == "https://coolify/logs/dep-fail"


# ---------------------------------------------------------------------------
# Timeout path
# ---------------------------------------------------------------------------


class TestDeployWaitTimeout:
    """Deploy times out → exit 2."""

    def _non_terminal_side_effect(self):
        """Always return 'in_progress' after the trigger call."""
        call_count = 0

        def side_effect(args):
            nonlocal call_count
            idx = call_count
            call_count += 1
            if idx == 0:
                return _make_ok_response("help")
            if idx == 1:
                return _make_trigger_response()
            return _make_status_response("in_progress")

        return side_effect

    def test_timeout_exits_2(self, cli):
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.side_effect = self._non_terminal_side_effect()
            with patch("tc.commands.deploy.time.sleep"):  # skip real sleep
                result = cli(
                    [
                        "deploy",
                        "wait",
                        "my-app",
                        "--timeout",
                        "1",
                    ]
                )
        assert result.exit_code == 2

    def test_timeout_json_deploy_status(self, cli):
        task_id = _setup_task(cli)
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.side_effect = self._non_terminal_side_effect()
            with patch("tc.commands.deploy.time.sleep"):
                result = cli(
                    [
                        "deploy",
                        "wait",
                        "my-app",
                        "--timeout",
                        "1",
                        "--task-id",
                        str(task_id),
                        "--json",
                    ]
                )
        assert result.exit_code == 2
        data = json.loads(result.output)
        assert data["deploy_status"] == "timeout"


# ---------------------------------------------------------------------------
# Test-failure path
# ---------------------------------------------------------------------------


class TestDeployWaitTestFailed:
    """Deploy succeeds but test fails → exit 3."""

    def _mock_with_test(self, test_returncode: int):
        """Four calls: availability → trigger → poll → test-cmd."""
        call_count = 0

        def side_effect(args):
            nonlocal call_count
            idx = call_count
            call_count += 1
            if idx == 0:
                return _make_ok_response("help")
            if idx == 1:
                return _make_trigger_response()
            if idx == 2:
                return _make_status_response("finished")
            # test command (via subprocess.run with shell=True) is NOT captured
            # here — it goes through subprocess.run directly, not _run_copilot.
            return _make_ok_response()

        return side_effect

    def test_test_fail_exits_3(self, cli):
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.side_effect = _copilot_mock()
            # Patch subprocess.run only for the test command call
            import subprocess as sp_module

            original_run = sp_module.run

            def run_side_effect(cmd, **kwargs):
                # Only intercept shell=True calls (test command)
                if kwargs.get("shell"):
                    m = MagicMock()
                    m.returncode = 1
                    m.stdout = "test failed output"
                    m.stderr = ""
                    return m
                return original_run(cmd, **kwargs)

            with patch(
                "tc.commands.deploy.subprocess.run", side_effect=run_side_effect
            ):
                result = cli(
                    [
                        "deploy",
                        "wait",
                        "my-app",
                        "--test",
                        "playwright test my-spec.ts",
                    ]
                )
        assert result.exit_code == 3

    def test_test_pass_exits_0(self, cli):
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.side_effect = _copilot_mock()
            import subprocess as sp_module

            original_run = sp_module.run

            def run_side_effect(cmd, **kwargs):
                if kwargs.get("shell"):
                    m = MagicMock()
                    m.returncode = 0
                    m.stdout = "all tests passed"
                    m.stderr = ""
                    return m
                return original_run(cmd, **kwargs)

            with patch(
                "tc.commands.deploy.subprocess.run", side_effect=run_side_effect
            ):
                result = cli(
                    [
                        "deploy",
                        "wait",
                        "my-app",
                        "--test",
                        "playwright test my-spec.ts",
                    ]
                )
        assert result.exit_code == 0

    def test_test_not_run_on_deploy_failure(self, cli):
        """Test command must NOT run when deploy failed."""
        test_was_called = []

        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.side_effect = _copilot_mock(poll_status="failed")

            import subprocess as sp_module

            original_run = sp_module.run

            def run_side_effect(cmd, **kwargs):
                if kwargs.get("shell"):
                    test_was_called.append(True)
                    m = MagicMock()
                    m.returncode = 0
                    m.stdout = ""
                    m.stderr = ""
                    return m
                return original_run(cmd, **kwargs)

            with patch(
                "tc.commands.deploy.subprocess.run", side_effect=run_side_effect
            ):
                cli(["deploy", "wait", "my-app", "--test", "echo ok"])

        assert not test_was_called, "Test command should not run when deploy fails"

    def test_test_status_stored_in_wp(self, cli):
        task_id = _setup_task(cli)
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.side_effect = _copilot_mock()

            import subprocess as sp_module

            original_run = sp_module.run

            def run_side_effect(cmd, **kwargs):
                if kwargs.get("shell"):
                    m = MagicMock()
                    m.returncode = 1
                    m.stdout = "FAILED: 1 test"
                    m.stderr = ""
                    return m
                return original_run(cmd, **kwargs)

            with patch(
                "tc.commands.deploy.subprocess.run", side_effect=run_side_effect
            ):
                result = cli(
                    [
                        "deploy",
                        "wait",
                        "my-app",
                        "--test",
                        "pytest tests/",
                        "--task-id",
                        str(task_id),
                        "--json",
                    ]
                )
        assert result.exit_code == 3
        data = json.loads(result.output)
        wp_result = cli(["wp", "get", str(data["wp_id"]), "--json"])
        report = json.loads(json.loads(wp_result.output)["content"])
        assert report["test_status"] == "fail"
        assert report["test_output"] is not None


# ---------------------------------------------------------------------------
# Dry-run / smoke test
# ---------------------------------------------------------------------------


class TestDeployWaitDryRun:
    """--dry-run exercises the flow without hitting Coolify."""

    def test_dry_run_exits_0(self, cli):
        result = cli(["deploy", "wait", "my-app", "--dry-run"])
        assert result.exit_code == 0

    def test_dry_run_json_output(self, cli):
        result = cli(["deploy", "wait", "my-app", "--dry-run", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["dry_run"] is True
        assert data["deploy_status"] == "success"

    def test_dry_run_with_task_id_skips_wp_storage(self, cli):
        task_id = _setup_task(cli)
        result = cli(
            [
                "deploy",
                "wait",
                "my-app",
                "--dry-run",
                "--task-id",
                str(task_id),
                "--json",
            ]
        )
        # dry_run=True skips WP storage
        data = json.loads(result.output)
        assert data["wp_id"] is None

    def test_dry_run_no_copilot_calls(self, cli):
        """Dry-run must not call _run_copilot at all."""
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            cli(["deploy", "wait", "my-app", "--dry-run"])
        mock_copilot.assert_not_called()

    def test_dry_run_shows_dry_run_marker(self, cli):
        result = cli(["deploy", "wait", "my-app", "--dry-run"])
        assert "DRY RUN" in result.output


# ---------------------------------------------------------------------------
# Trigger / UUID extraction edge cases
# ---------------------------------------------------------------------------


class TestTriggerParsing:
    """Various response shapes from deploy trigger."""

    def test_list_response_uses_first_item(self, cli):
        trigger_stdout = json.dumps(
            [
                {"deployment_uuid": "uuid-first", "application_name": "app1"},
                {"deployment_uuid": "uuid-second", "application_name": "app2"},
            ]
        )
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.side_effect = _copilot_mock(trigger_stdout=trigger_stdout)
            result = cli(["deploy", "wait", "my-tag", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["deployment_uuid"] == "uuid-first"

    def test_missing_uuid_exits_4(self, cli):
        bad_response = json.dumps({"message": "no uuid here"})
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.side_effect = _copilot_mock(trigger_stdout=bad_response)
            result = cli(["deploy", "wait", "my-app"])
        assert result.exit_code == 4

    def test_trigger_non_zero_exits_4(self, cli):
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.side_effect = _copilot_mock(trigger_returncode=1)
            result = cli(["deploy", "wait", "my-app"])
        assert result.exit_code == 4


# ---------------------------------------------------------------------------
# wp list --type deploy_report integration
# ---------------------------------------------------------------------------


class TestDeployReportListing:
    """tc wp list --type deploy_report surfaces deploy_report WPs."""

    def test_deploy_reports_listable(self, cli):
        task_id = _setup_task(cli)
        with patch("tc.commands.deploy._run_copilot") as mock_copilot:
            mock_copilot.side_effect = _copilot_mock(trigger_uuid="uuid-list-test")
            cli(
                [
                    "deploy",
                    "wait",
                    "my-app",
                    "--task-id",
                    str(task_id),
                ]
            )

        result = cli(["wp", "list", "--type", "deploy_report", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["type"] == "deploy_report"
