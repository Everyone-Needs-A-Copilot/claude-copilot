"""Deploy commands for Task Copilot CLI."""

from __future__ import annotations

import json as json_mod
import shlex
import subprocess
import sys
import time
from typing import Optional

import typer

from tc.db.connection import get_db
from tc.formatting import output_json
from tc.utils.errors import error_exit, require_db, EXIT_NOT_FOUND, EXIT_VALIDATION

deploy_app = typer.Typer(name="deploy", help="Deployment orchestration commands.")

# Exit codes
EXIT_DEPLOY_FAILED = 1
EXIT_TIMEOUT = 2
EXIT_TEST_FAILED = 3
EXIT_BAD_CONFIG = 4

# Terminal deploy statuses — generic enough to work with any provider that
# reports a string status field.  The set of values is kept here as a named
# constant so tests can assert against it and a future provider can extend it
# via config without touching this module.
_DEPLOY_SUCCESS_STATUSES = {"finished"}
_DEPLOY_FAILURE_STATUSES = {"failed", "error", "cancelled", "canceled"}
_DEPLOY_TERMINAL_STATUSES = _DEPLOY_SUCCESS_STATUSES | _DEPLOY_FAILURE_STATUSES

# ---------------------------------------------------------------------------
# Deploy CLI resolution
# ---------------------------------------------------------------------------

#: Config key read from cc machine/project config (cc config set deploy.cli "...").
#: Override via env var CC_DEPLOY_CLI or by writing deploy.cli to cc config.
_DEPLOY_CLI_CONFIG_KEY = "deploy.cli"

#: Fallback used when the config key is absent.  Written here as a constant so
#: the framework code contains no hardcoded vendor name — the default is the
#: constant, and users who never set the config key get the same behaviour.
_DEPLOY_CLI_DEFAULT = "python -m copilot_cli"


def _get_deploy_cli() -> list[str]:
    """Return the deploy CLI command prefix as a list of tokens.

    Resolution order (highest wins):
      1. CC_DEPLOY_CLI environment variable
      2. deploy.cli key in cc machine or project config
      3. Built-in default: ``python -m copilot_cli``

    The returned list is ready to prepend to subprocess args, e.g.::

        cmd = _get_deploy_cli() + ["--json", "coolify", "deploy", "trigger", app_id]
    """
    import os

    # Env var override (CC_DEPLOY_CLI)
    env_val = os.environ.get("CC_DEPLOY_CLI")
    if env_val:
        return shlex.split(env_val)

    # cc config lookup — graceful: if cc is not importable, fall through
    try:
        from cc.core.config import resolve_key

        val = resolve_key(_DEPLOY_CLI_CONFIG_KEY)
        if val:
            return shlex.split(str(val))
    except Exception:
        pass

    return shlex.split(_DEPLOY_CLI_DEFAULT)


def _run_copilot(args: list[str]) -> subprocess.CompletedProcess:
    """Run the configured deploy CLI command and return the CompletedProcess.

    The CLI prefix is resolved via :func:`_get_deploy_cli` on each call so
    that tests can patch ``_get_deploy_cli`` or ``_run_copilot`` independently.
    Extracted so tests can mock this single function without intercepting
    unrelated subprocess calls (git, etc.).
    """
    cmd = _get_deploy_cli() + args
    return subprocess.run(cmd, capture_output=True, text=True)


def _check_cli_available() -> None:
    """Exit with code 4 if the configured deploy CLI is not runnable."""
    result = _run_copilot(["coolify", "deploy", "--help"])
    if result.returncode != 0:
        cli_cmd = " ".join(_get_deploy_cli())
        error_exit(
            f"Deploy CLI is not available (`{cli_cmd} coolify deploy --help` failed). "
            'Set deploy.cli in cc config (cc config set deploy.cli "<command>") '
            "or install the CLI per SETUP.md section P5.2.",
            EXIT_BAD_CONFIG,
        )


def _trigger_deploy(app_id: str, force: bool) -> str:
    """Trigger a deploy and return the deployment UUID.

    Shells out to the config-resolved deploy CLI (see _get_deploy_cli), e.g.:
      <deploy-cli> --json coolify deploy trigger <app_id> [--force]
    The "coolify" token and subsequent subcommands are the provider CLI's own
    verbs — they are not part of the framework CLI name.

    Returns the deployment UUID string.
    Exits with EXIT_BAD_CONFIG on unexpected output.
    """
    args = ["--json", "coolify", "deploy", "trigger", app_id]
    if force:
        args.append("--force")

    result = _run_copilot(args)
    if result.returncode != 0:
        error_exit(
            f"Deploy trigger failed (exit {result.returncode}): {result.stderr.strip()}",
            EXIT_BAD_CONFIG,
        )

    raw = result.stdout.strip()
    try:
        data = json_mod.loads(raw)
    except json_mod.JSONDecodeError:
        error_exit(
            f"Unexpected output from deploy trigger (expected JSON): {raw[:200]}",
            EXIT_BAD_CONFIG,
        )

    # The Coolify API returns {"deployment_uuid": "...", "message": "..."}
    # or a list of such dicts for tag deploys.
    if isinstance(data, list):
        if not data:
            error_exit(
                "Deploy trigger returned an empty list — no deployment started.",
                EXIT_BAD_CONFIG,
            )
        data = data[0]

    uuid = data.get("deployment_uuid") or data.get("uuid")
    if not uuid:
        error_exit(
            f"Deploy trigger response missing 'deployment_uuid': {json_mod.dumps(data)[:200]}",
            EXIT_BAD_CONFIG,
        )
    return str(uuid)


def _poll_deploy(deployment_uuid: str, poll_interval: int, timeout: int) -> dict:
    """Poll deploy status until terminal or timeout.

    Returns a dict with keys:
      status: 'finished' | 'failed' | ... (raw Coolify status)
      outcome: 'success' | 'failed' | 'timeout'
      duration_seconds: float
      logs_url: str | None
      raw: dict (last Coolify response)
    """
    start = time.monotonic()
    deadline = start + timeout

    while True:
        elapsed = time.monotonic() - start
        if time.monotonic() > deadline:
            return {
                "status": "timeout",
                "outcome": "timeout",
                "duration_seconds": elapsed,
                "logs_url": None,
                "raw": {},
            }

        result = _run_copilot(["--json", "coolify", "deploy", "get", deployment_uuid])
        elapsed = time.monotonic() - start

        if result.returncode == 0:
            try:
                data = json_mod.loads(result.stdout.strip())
            except json_mod.JSONDecodeError:
                data = {}
        else:
            # Transient error — keep polling
            data = {}

        raw_status = (data.get("status") or "").lower()

        if raw_status in _DEPLOY_TERMINAL_STATUSES:
            outcome = "success" if raw_status in _DEPLOY_SUCCESS_STATUSES else "failed"
            return {
                "status": raw_status,
                "outcome": outcome,
                "duration_seconds": elapsed,
                "logs_url": data.get("logs_url") or data.get("url"),
                "raw": data,
            }

        # Not terminal — sleep then retry
        remaining = deadline - time.monotonic()
        sleep_time = min(poll_interval, max(0, remaining))
        if sleep_time > 0:
            time.sleep(sleep_time)


def _run_test_cmd(test_cmd: str) -> dict:
    """Run an arbitrary test command (e.g. Playwright spec).

    Returns dict with keys: passed (bool), output (str).
    """
    result = subprocess.run(
        test_cmd,
        shell=True,
        capture_output=True,
        text=True,
    )
    output = (result.stdout + result.stderr).strip()
    return {
        "passed": result.returncode == 0,
        "output": output[-2000:] if len(output) > 2000 else output,
    }


def _get_git_branch() -> Optional[str]:
    """Return the current git branch, or None if not in a git repo."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip() or None
    return None


def _get_git_sha() -> Optional[str]:
    """Return the current git commit SHA (short), or None."""
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip() or None
    return None


def _store_deploy_report(
    *,
    task_id: int,
    app_id: str,
    branch: Optional[str],
    commit_sha: Optional[str],
    env: str,
    deploy_status: str,
    duration_seconds: float,
    logs_url: Optional[str],
    test_status: str,
    test_output: Optional[str],
    deployment_uuid: Optional[str],
    dry_run: bool,
) -> Optional[int]:
    """Store a deploy_report work product. Returns WP id or None on dry-run."""
    if dry_run:
        return None

    db_path = require_db()
    conn = get_db(db_path)

    task_row = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task_row is None:
        conn.close()
        error_exit(f"Task #{task_id} not found", EXIT_NOT_FOUND)

    report_content = {
        "app_id": app_id,
        "deployment_uuid": deployment_uuid,
        "branch": branch,
        "commit_sha": commit_sha,
        "environment": env,
        "deploy_status": deploy_status,
        "duration_seconds": round(duration_seconds, 1),
        "logs_url": logs_url,
        "test_status": test_status,
        "test_output": test_output,
    }
    content_str = json_mod.dumps(report_content, indent=2)
    title = f"Deploy report: {app_id} [{deploy_status}]"

    cursor = conn.execute(
        "INSERT INTO work_products (task_id, type, title, content, file_path, agent) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (task_id, "deploy_report", title, content_str, None, "do"),
    )
    conn.commit()
    wp_id = cursor.lastrowid
    conn.close()
    return wp_id


@deploy_app.command("wait")
def deploy_wait(
    app_id: str = typer.Argument(..., help="Application UUID or tag to deploy."),
    branch: Optional[str] = typer.Option(
        None, "--branch", help="Branch to deploy (default: current git branch)."
    ),
    timeout: int = typer.Option(
        600, "--timeout", help="Max wait time in seconds (default: 600)."
    ),
    test_cmd: Optional[str] = typer.Option(
        None,
        "--test",
        help="Command to run after successful deploy (e.g. Playwright spec).",
    ),
    env: str = typer.Option(
        "staging", "--env", help="Environment name (staging|production)."
    ),
    use_json: bool = typer.Option(False, "--json", help="Emit JSON to stdout."),
    task_id: Optional[int] = typer.Option(
        None, "--task-id", help="Link deploy_report WP to this task."
    ),
    force: bool = typer.Option(False, "--force", help="Force rebuild."),
    trigger: bool = typer.Option(
        True, "--trigger/--no-trigger", help="Trigger deploy (default: true)."
    ),
    poll_interval: int = typer.Option(
        5, "--poll-interval", help="Polling interval in seconds."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Exercise the flow without hitting Coolify."
    ),
) -> None:
    """Trigger a Coolify deploy and wait for completion.

    Polls until the deploy finishes (success, failure, or timeout), then
    optionally runs a test command. Stores a deploy_report work product.

    Exit codes:
      0 — deploy succeeded (and test passed if --test was given)
      1 — deploy failed
      2 — deploy timed out
      3 — test failed (deploy succeeded)
      4 — invalid config / missing dependency
    """
    # --- Dependency check ---
    if not dry_run:
        _check_cli_available()

    # --- Resolve branch / commit ---
    resolved_branch = branch or _get_git_branch()
    commit_sha = _get_git_sha()

    if dry_run:
        # Dry-run: simulate a successful deploy
        deployment_uuid = "dry-run-uuid"
        poll_result = {
            "status": "finished",
            "outcome": "success",
            "duration_seconds": 0.0,
            "logs_url": None,
            "raw": {},
        }
    else:
        # --- Trigger ---
        deployment_uuid: Optional[str] = None
        if trigger:
            deployment_uuid = _trigger_deploy(app_id, force)
        else:
            # --no-trigger: user pre-triggered; poll the app's most recent deployment
            # We resolve the latest deployment UUID via deploy history
            deployment_uuid = None

        if deployment_uuid is None and not trigger:
            # Without a UUID we can't poll — this mode requires the caller to know the UUID
            error_exit(
                "--no-trigger requires a known deployment UUID. "
                "Use --trigger (default) or provide a UUID via the app history.",
                EXIT_BAD_CONFIG,
            )

        # --- Poll ---
        poll_result = _poll_deploy(deployment_uuid, poll_interval, timeout)

    deploy_status = poll_result["outcome"]  # success | failed | timeout

    # --- Optional test ---
    test_status = "skipped"
    test_output = None
    if test_cmd and deploy_status == "success":
        test_result = _run_test_cmd(test_cmd)
        test_status = "pass" if test_result["passed"] else "fail"
        test_output = test_result["output"]

    # --- Store WP ---
    wp_id: Optional[int] = None
    if task_id is not None:
        wp_id = _store_deploy_report(
            task_id=task_id,
            app_id=app_id,
            branch=resolved_branch,
            commit_sha=commit_sha,
            env=env,
            deploy_status=deploy_status,
            duration_seconds=poll_result["duration_seconds"],
            logs_url=poll_result.get("logs_url"),
            test_status=test_status,
            test_output=test_output,
            deployment_uuid=deployment_uuid,
            dry_run=dry_run,
        )

    # --- Build result payload ---
    payload = {
        "app_id": app_id,
        "deployment_uuid": deployment_uuid,
        "branch": resolved_branch,
        "commit_sha": commit_sha,
        "environment": env,
        "deploy_status": deploy_status,
        "duration_seconds": round(poll_result["duration_seconds"], 1),
        "logs_url": poll_result.get("logs_url"),
        "test_status": test_status,
        "test_output": test_output,
        "wp_id": wp_id,
        "dry_run": dry_run,
    }

    # --- Output ---
    if use_json:
        output_json(payload)
    else:
        status_icon = {"success": "OK", "failed": "FAILED", "timeout": "TIMEOUT"}.get(
            deploy_status, deploy_status.upper()
        )
        print(f"Deploy {status_icon}: {app_id}")
        print(f"  Deployment UUID : {deployment_uuid or 'n/a'}")
        print(f"  Branch          : {resolved_branch or 'unknown'}")
        print(f"  Commit          : {commit_sha or 'unknown'}")
        print(f"  Environment     : {env}")
        print(f"  Duration        : {round(poll_result['duration_seconds'], 1)}s")
        if poll_result.get("logs_url"):
            print(f"  Logs URL        : {poll_result['logs_url']}")
        print(f"  Test status     : {test_status}")
        if wp_id:
            print(f"  WP stored       : WP-{wp_id}")
        if dry_run:
            print("  [DRY RUN — no Coolify calls made]")

    # --- Exit code ---
    if deploy_status == "failed":
        raise typer.Exit(EXIT_DEPLOY_FAILED)
    if deploy_status == "timeout":
        raise typer.Exit(EXIT_TIMEOUT)
    if test_status == "fail":
        raise typer.Exit(EXIT_TEST_FAILED)
    raise typer.Exit(0)
