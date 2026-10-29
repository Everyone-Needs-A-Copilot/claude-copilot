"""Task-bound command execution and offline corrective checks."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

import typer

from tc.db.exceptions import TcError
from tc.formatting import output_json
from tc.services import execution as ex
from tc.utils.errors import EXIT_VALIDATION, error_exit, require_db

execution_app = typer.Typer(
    help="Persistent scope, experiment limits, evidence and handoff status."
)


def _call(fn, **kwargs):
    try:
        return fn(db_path=require_db(), **kwargs)
    except (TcError, ValueError, OSError) as exc:
        error_exit(str(exc), EXIT_VALIDATION)


@execution_app.command("register")
def register(
    task: int,
    attempts: Optional[int] = typer.Option(
        None, help="Legacy v1 fixed attempt cap. Omit for policy v2 (recommended)."
    ),
    calls: int = 0,
    usd: float = 0,
    authority: Optional[List[str]] = typer.Option(None),
    root: Optional[Path] = None,
    timeout: int = 900,
    stale: int = 300,
    no_progress_n: Optional[int] = None,
    ceiling_attempts: Optional[int] = None,
    ceiling_seconds: Optional[int] = None,
):
    """Freeze task scope. Policy v2 (no --attempts): no fixed attempt cap, stops on
    no progress, hard runaway ceiling, paid calls come from the project budget.
    With --attempts: legacy v1 caps (--authority required, may be repeated)."""
    output_json(
        _call(
            ex.register_limits,
            task_id=task,
            attempts=attempts,
            calls=calls,
            cost_usd=usd,
            authority=authority or None,
            root=root,
            timeout_seconds=timeout,
            stale_seconds=stale,
            no_progress_n=no_progress_n,
            ceiling_attempts=ceiling_attempts,
            ceiling_seconds=ceiling_seconds,
        )
    )


@execution_app.command("amend")
def amend(
    task: int,
    file: Path = typer.Option(..., help="The complete owner-approved acceptance contract JSON."),
    expected_contract_sha256: str = typer.Option(
        ..., help="Current limits.contract_sha256 from execution status (not QA identity)."
    ),
    decision: str = typer.Option(..., help="The verbatim owner decision approving this amendment."),
):
    """Audit a contract correction; preserve all history, limits and failure stops."""
    try:
        contract = json.loads(file.read_text())
    except (OSError, ValueError) as exc:
        error_exit(str(exc), EXIT_VALIDATION)
    output_json(_call(ex.amend_contract, task_id=task, contract=contract,
                      expected_contract_sha256=expected_contract_sha256, decision=decision))


budget_app = typer.Typer(help="Per-project lifetime paid-call budget (append-only).")
execution_app.add_typer(budget_app, name="budget")


@budget_app.command("show")
def budget_show(json: bool = typer.Option(True, "--json/--no-json", help="Always JSON.")):
    """Budget, lifetime spend and remaining for this project (one task database;
    linked worktrees share their main checkout's)."""
    output_json(_call(ex.budget_status))


@budget_app.command("set")
def budget_set(
    calls: int = typer.Option(...),
    usd: float = typer.Option(...),
    authority: List[str] = typer.Option(...),
):
    """Append a budget round with lifetime totals. Needs a new verbatim owner quote."""
    output_json(
        _call(
            ex.set_budget,
            calls=calls,
            cost_usd=usd,
            authority=authority,
        )
    )


@execution_app.command("reopen")
def reopen(
    task: int,
    decision: str = typer.Option(..., help="Pablo's recorded decision to continue."),
    ceiling_attempts: Optional[int] = None,
    ceiling_seconds: Optional[int] = None,
):
    """Raise a runaway ceiling after an owner decision. Carries all history."""
    output_json(
        _call(
            ex.reopen_ceiling,
            task_id=task,
            decision=decision,
            ceiling_attempts=ceiling_attempts,
            ceiling_seconds=ceiling_seconds,
        )
    )


@execution_app.command("migrate")
def migrate(
    task: Optional[int] = None,
    dry_run: bool = typer.Option(False, "--dry-run"),
    no_backup: bool = False,
):
    """Append a policy-v2 round to v1 tasks and seed the project budget from their
    existing approvals. Idempotent; history, usage and QA identity are untouched."""
    output_json(
        _call(ex.migrate_ledgers, task_id=task, dry_run=dry_run, backup=not no_backup)
    )


@execution_app.command("succeed")
def succeed(
    task: int,
    attempts: int = typer.Option(...),
    calls: int = 0,
    usd: float = 0,
    authority: List[str] = typer.Option(...),
    timeout: Optional[int] = None,
    stale: Optional[int] = None,
):
    """Open a successor round. Caps are lifetime totals and can only rise; all
    usage and failures carry forward. Needs a new, verbatim owner --authority."""
    output_json(
        _call(
            ex.succeed_limits,
            task_id=task,
            attempts=attempts,
            calls=calls,
            cost_usd=usd,
            authority=authority,
            timeout_seconds=timeout,
            stale_seconds=stale,
        )
    )


@execution_app.command("status")
def status(task: int):
    """Observed execution state and exact authorizations; no guessed ETA."""
    output_json(_call(ex.execution_status, task_id=task))


@execution_app.command("begin")
def begin(
    task: int,
    criterion: str = typer.Option(...),
    label: str = typer.Option(...),
    calls: int = 0,
    usd: float = 0,
):
    output_json(
        _call(
            ex.begin_attempt,
            task_id=task,
            criterion=criterion,
            label=label,
            reserve_calls=calls,
            reserve_usd=usd,
        )
    )


@execution_app.command("consume")
def consume(token: str):
    """Preflight one external call against a persistent reservation."""
    output_json(_call(ex.consume_call, token=token))


@execution_app.command("settle")
def settle(
    token: str,
    artifact: Path = typer.Option(...),
    succeeded: bool = False,
    calls: Optional[int] = None,
    usd: Optional[float] = None,
    reason: str = "",
):
    output_json(
        _call(
            ex.settle_attempt,
            token=token,
            artifact=artifact,
            succeeded=succeeded,
            calls=calls,
            cost_usd=usd,
            reason=reason,
        )
    )


@execution_app.command("diagnose")
def diagnose(
    task: int, criterion: str = typer.Option(...), regression: Path = typer.Option(...)
):
    output_json(
        _call(
            ex.diagnosis_checkpoint,
            task_id=task,
            criterion=criterion,
            regression=regression,
        )
    )


def execute_command(
    *,
    task,
    criterion,
    command,
    db_path,
    label="verification",
    calls=0,
    usd=0,
    offline=False,
    usage_file=None,
    worker=False,
    live=None,
):
    """Run without a shell, bound elapsed time, persist a private result even on failure."""
    if usage_file and Path(usage_file).exists():
        raise ex.ValidationError(
            "Usage report already exists; use a fresh attempt-specific path"
        )
    if not command:
        raise ex.ValidationError("A command is required after --")
    state = ex.execution_status(task_id=task, db_path=db_path)
    if offline:
        state = ex.execution_status(task_id=task, db_path=db_path)
        p = state["limits"]
        if criterion not in p["criteria"]:
            raise ex.ValidationError(
                "Criterion is outside the registered acceptance scope"
            )
        token, source, timeout = None, ex._source(p), p["timeout_seconds"]
    else:
        attempt = ex.begin_attempt(
            task_id=task,
            criterion=criterion,
            label=label,
            reserve_calls=calls,
            reserve_usd=usd,
            db_path=db_path,
        )
        token, source, timeout = (
            attempt["token"],
            attempt["source"],
            attempt["timeout_seconds"],
        )
    directory = (
        Path(db_path).parent / "execution" / str(task) / (token or f"check-{uuid4()}")
    )
    directory.mkdir(parents=True, mode=0o700)
    log = directory / "output.log"
    result_path = directory / "result.json"
    env = dict(os.environ)
    env.update(
        TC_EXECUTION_DB=str(Path(db_path).resolve()),
        TC_EXECUTION_TASK_ID=str(task),
        TC_EXECUTION_CRITERION=criterion,
    )
    # Replay by default: only an explicit live run (reserved calls/usd) may reach a paid API.
    if live is None:
        live = float(calls or 0) > 0 or float(usd or 0) > 0
    if token and live:
        env["TC_EXECUTION_TOKEN"] = token
        env["API_STUB_MISS_BUDGET"] = str(calls)
        env["API_STUB_COST_CAP_USD"] = str(usd)
    else:
        if token:
            env["TC_EXECUTION_TOKEN"] = token
        else:
            env.pop("TC_EXECUTION_TOKEN", None)
        env.update(
            APP_ENV="test",
            API_MODE="stub_strict",
            API_MODE_CALLS="",
            API_MODE_PIPELINES="",
            API_STUB_MISS_BUDGET="0",
            API_STUB_COST_CAP_USD="0",
        )
        env.pop("ALLOW_LIVE_API_IN_PYTEST", None)
    started = time.time()
    timed_out = False
    with os.fdopen(
        os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as out:
        try:
            process = subprocess.Popen(
                command,
                stdout=out,
                stderr=subprocess.STDOUT,
                env=env,
                cwd=state["limits"]["root"],
                start_new_session=True,
            )
            try:
                code = process.wait(timeout=timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                code = 124
        except OSError as exc:
            out.write(f"Could not launch command: {type(exc).__name__}\n")
            code = 127
    current = ex.execution_status(task_id=task, db_path=db_path)
    after = ex._source(current["limits"])
    receipt = {
        "task_id": task,
        "criterion": criterion,
        "command": command,
        "exit_code": code,
        "source_before": source,
        "source_after": after,
        "elapsed_seconds": round(time.time() - started, 3),
        "timed_out": timed_out,
        "output": str(log),
        "output_sha256": ex._artifact(log)[1],
    }
    with os.fdopen(
        os.open(result_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as out:
        json.dump(receipt, out, indent=2)
    if offline and code == 0 and source == after:
        ex.record_regression(
            task_id=task, criterion=criterion, artifact=result_path, db_path=db_path
        )
    spend = {}
    if token:
        actual_calls, actual_usd = None, None
        if usage_file:
            usage = json.loads(Path(usage_file).read_text())
            actual_calls, actual_usd = (
                usage["network_calls"],
                usage["recorded_cost_usd"],
            )
        if worker:
            from tc.commands.worker import _parse_spend, is_budget_breach

            spend = _parse_spend(log.read_text())
            actual_usd = spend.get("total_cost_usd")
            if is_budget_breach(spend) or spend.get("is_error"):
                code = code or 1
        settled = ex.settle_attempt(
            token=token,
            succeeded=code == 0,
            artifact=result_path,
            calls=actual_calls,
            cost_usd=actual_usd,
            reason="timeout" if timed_out else f"exit={code}",
            db_path=db_path,
        )
        if settled["exceeded"]:
            code = 4
    return {
        "exit_code": code,
        "artifact": str(result_path),
        "token": token,
        "spend": spend,
    }


@execution_app.command(
    "run", context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def run(
    ctx: typer.Context,
    task: int,
    criterion: str = typer.Option(...),
    label: str = "verification",
    calls: int = 0,
    usd: float = 0,
    usage_file: Optional[Path] = None,
    live: bool = typer.Option(
        False, "--live", help="The only way to make a paid call; needs --calls and --usd (>0)."
    ),
):
    """Run a check in replay mode (APP_ENV=test API_MODE=stub_strict, zero miss budget).
    --live reserves --calls/--usd from the project budget and allows paid calls.
    --usage-file consumes a machine-produced transport report."""
    if not live and (calls or usd):
        error_exit(
            "--calls/--usd only apply with --live; without --live the run is replay-only (API_MODE=stub_strict, no paid calls)",
            EXIT_VALIDATION,
        )
    if live and not (calls > 0 and usd > 0):
        error_exit("--live needs --calls and --usd greater than 0 to reserve against the project budget", EXIT_VALIDATION)
    result = _call(
        execute_command,
        task=task,
        criterion=criterion,
        command=ctx.args,
        label=label,
        calls=calls,
        usd=usd,
        usage_file=usage_file,
        live=live,
    )
    output_json(result)
    raise typer.Exit(result["exit_code"])


def stub_miss_hint_line(budget, *, provider, prompt_hash, test, adapter):
    return (
        f"No recording for {provider} with prompt hash {prompt_hash}. "
        f"Record it with: {adapter} --live {test}. "
        f"Live calls charge the {budget['project']} budget "
        f"(remaining ${budget['remaining_cost_usd']:.2f} of ${budget['cost_usd']:.2f})."
    )


@execution_app.command("stub-miss-hint")
def stub_miss_hint(
    provider: str = typer.Option(..., help="provider:model, e.g. openrouter:anthropic/claude-sonnet-5-5"),
    hash: str = typer.Option(..., "--hash", help="Prompt hash that has no recording."),
    test: str = typer.Option(..., help="Test id to record."),
    adapter: str = typer.Option("scripts/test.sh", help="Project test adapter command."),
):
    """Print the message a project adapter shows on a stub miss, with the real budget."""
    budget = _call(ex.budget_status)
    print(stub_miss_hint_line(budget, provider=provider, prompt_hash=hash, test=test, adapter=adapter))


@execution_app.command(
    "prove", context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def prove(ctx: typer.Context, task: int, criterion: str = typer.Option(...)):
    """Run a corrective regression in strict-stub mode without resetting live budgets."""
    result = _call(
        execute_command, task=task, criterion=criterion, command=ctx.args, offline=True
    )
    output_json(result)
    raise typer.Exit(result["exit_code"])
