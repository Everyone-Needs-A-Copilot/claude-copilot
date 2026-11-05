"""Internal protocol coordination commands shared by both native harnesses."""
from pathlib import Path
from typing import Optional
import json as jsonlib
import typer
from tc.db.exceptions import ConflictError, ValidationError
from tc.formatting import output_json, output_error_json
from tc.utils.errors import require_db
from tc.services import cycles

cycle_app = typer.Typer(help="Protocol-owned ready-work coordination; no model calls. Guide: tools/tc/docs/CYCLE.md.")


def _run(fn, json, **kwargs):
    try:
        result = fn(**kwargs)
    except (ValidationError, ConflictError, OSError, ValueError) as exc:
        if json:
            output_error_json(str(exc), 4)
        else:
            typer.echo(str(exc), err=True)
        raise typer.Exit(4)
    if json:
        output_json(result)
    else:
        typer.echo(jsonlib.dumps(result, indent=2))


def _read(path):
    return jsonlib.loads(path.read_text())


@cycle_app.command("validate")
def validate(file: Path = typer.Option(..., "--file", help="Schema-1 plan JSON."), json: bool = typer.Option(False, "--json")):
    """Validate ownership and dependencies without a database or dispatch."""
    _run(lambda: cycles.validate_plan(_read(file)), json)


@cycle_app.command("plan")
def plan(file: Path = typer.Option(..., "--file", help="Approved schema-1 plan JSON."), json: bool = typer.Option(False, "--json")):
    """Persist an approved cycle; identical retries are idempotent."""
    _run(lambda: cycles.create_cycle(plan=_read(file), db_path=require_db()), json)


@cycle_app.command("status")
def status(cycle: str, json: bool = typer.Option(False, "--json")):
    """Read streams, capacity queues, stale evidence and disposition."""
    _run(cycles.cycle_status, json, cycle=cycle, db_path=require_db())


@cycle_app.command("ready")
def ready(cycle: str, json: bool = typer.Option(False, "--json")):
    """Return ready scopes and concrete wait reasons."""
    _run(lambda: {k: v for k, v in cycles.cycle_status(cycle=cycle, db_path=require_db()).items() if k in {"ready", "queued", "running", "stalled", "capacity", "available"}}, json)


@cycle_app.command("claim")
def claim(cycle: str, stream: str, agent: str = typer.Option(..., "--agent"), cwd: Path = typer.Option(..., "--cwd"), branch: Optional[str] = typer.Option(None, "--branch"), lease_seconds: int = typer.Option(900, "--lease-seconds"), json: bool = typer.Option(False, "--json")):
    """Claim one ready scope after exact execution-root and capacity checks."""
    _run(cycles.claim_stream, json, cycle=cycle, stream=stream, agent=agent, cwd=cwd, branch=branch, lease_seconds=lease_seconds, db_path=require_db())


@cycle_app.command("prepare")
def prepare(cycle: str, stream: str, json: bool = typer.Option(False, "--json")):
    """Create the planned new writer worktree/branch, recording its identity."""
    _run(cycles.prepare_worktree, json, cycle=cycle, stream=stream, db_path=require_db())


@cycle_app.command("verify-dispatch")
def verify_dispatch(cycle: str, stream: str, role: str = typer.Option(..., "--role"), cwd: Path = typer.Option(..., "--cwd"), blocked_task: list[int] = typer.Option([], "--blocked-task", help="Pending-QA builder task that cannot consume an unrelated-work permit."), json: bool = typer.Option(False, "--json")):
    """Consume one running claim's native dispatch permit; duplicate launches refuse."""
    _run(cycles.verify_dispatch, json, cycle=cycle, stream=stream, role=role, cwd=cwd, blocked_tasks=blocked_task, db_path=require_db())


@cycle_app.command("record")
def record(cycle: str, stream: str, event: str = typer.Option(..., "--event"), file: Path = typer.Option(..., "--file", help="Evidence receipt JSON, including leaseToken for worker events."), json: bool = typer.Option(False, "--json")):
    """Record contract/build/integration/QA/stopped/teardown outcomes."""
    _run(lambda: cycles.record_event(cycle=cycle, stream=stream, event=event, receipt=_read(file), db_path=require_db()), json)


@cycle_app.command("cleanup-plan")
def cleanup_plan(cycle: str, json: bool = typer.Option(False, "--json")):
    """Inspect exact eligible cycle worktrees and preserved holds."""
    _run(cycles.cleanup_plan, json, cycle=cycle, db_path=require_db())


@cycle_app.command("cleanup")
def cleanup(cycle: str, json: bool = typer.Option(False, "--json")):
    """Retire eligible merged cycle worktrees; preserve branches and every hold."""
    _run(cycles.cleanup_cycle, json, cycle=cycle, db_path=require_db())


@cycle_app.command("smoke")
def smoke(roles: str = typer.Option(",".join(cycles.DEFAULT_ROLES), "--roles", help="Comma-separated role identifiers, no provider calls."), out: Optional[Path] = typer.Option(None, "--out", help="New JSON evidence path; existing files are preserved."), json: bool = typer.Option(False, "--json")):
    """Handshake overlapping local role processes and verify complete shutdown."""
    _run(cycles.smoke_roles, json, roles=roles.split(","), out=out)


@cycle_app.command("finish")
def finish(cycle: str, json: bool = typer.Option(False, "--json")):
    """Close the PRD only when all body tasks, workers and cycle resources resolve."""
    _run(cycles.finish_cycle, json, cycle=cycle, db_path=require_db())


@cycle_app.command("adapter")
def adapter(project: Path, json: bool = typer.Option(False, "--json")):
    """Discover one project's setup/check/teardown and declared isolation without execution."""
    _run(cycles.inspect_adapter, json, project=project)
