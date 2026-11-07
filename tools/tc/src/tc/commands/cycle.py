"""Internal protocol coordination commands shared by both native harnesses."""
import json as jsonlib
from pathlib import Path
from typing import Optional

import typer

from tc.db.exceptions import ConflictError, ValidationError
from tc.formatting import output_error_json, output_json
from tc.services import cycles
from tc.utils.errors import require_db

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


@cycle_app.command('capability')
def capability(json: bool = typer.Option(False, '--json')):
    """Report supported control schemas, not native execution capabilities."""
    _run(lambda: {'schemaVersions': [1, 2], 'stagePolicyVersion': 1, 'nativeDispatch': False}, json)


@cycle_app.command('advance')
def advance(cycle: str, event: str = typer.Option(..., '--event'), file: Path = typer.Option(..., '--file'), expect_revision: Optional[int] = typer.Option(None, '--expect-revision'), json: bool = typer.Option(False, '--json')):
    """Commit one source-bound stage transition; never dispatch workers."""
    from tc.services.cycle_stages import advance_cycle
    _run(advance_cycle, json, cycle=cycle, event=event, receipt=_read(file), expect_revision=expect_revision, db_path=require_db())


@cycle_app.command('check')
def check(cycle: str, phase: str = typer.Option('complete', '--phase'), candidate: Optional[str] = typer.Option(None, '--candidate'), json: bool = typer.Option(False, '--json')):
    """Refuse incomplete or stale stage acceptance."""
    from tc.services.cycle_stages import check_cycle
    def checked():
        result = check_cycle(cycle=cycle, phase=phase, candidate=candidate, db_path=require_db())
        if not result['approved']:
            raise ValidationError('; '.join(result['reasons']))
        return result
    _run(checked, json)


@cycle_app.command('audit')
def audit(cycle: str, json: bool = typer.Option(False, '--json')):
    """Report durable queue/native observations and explicit unknown intervals."""
    from tc.services.cycle_stages import audit_cycle
    _run(audit_cycle, json, cycle=cycle, db_path=require_db())


@cycle_app.command('export')
def export(cycle: str, phase: str = typer.Option(..., '--phase'), out: Path = typer.Option(..., '--out'), json: bool = typer.Option(False, '--json')):
    """Export a new nonsecret release packet after phase acceptance."""
    from tc.services.cycle_stages import export_packet
    _run(export_packet, json, cycle=cycle, phase=phase, output=out, db_path=require_db())


@cycle_app.command('verify-packet')
def verify_packet(file: Path = typer.Option(..., '--file'), sha256: str = typer.Option(..., '--sha256'), root: Path = typer.Option(..., '--root'), phase: str = typer.Option(..., '--phase'), source_commit: Optional[str] = typer.Option(None, '--source-commit'), candidate_inputs_sha256: Optional[str] = typer.Option(None, '--candidate-inputs-sha256'), json: bool = typer.Option(False, '--json')):
    """Verify approved packet digest/source binding offline; no local task DB."""
    from tc.services.cycle_stages import verify_packet as verify
    _run(verify, json, file=file, sha256=sha256, root=root, phase=phase, source_commit=source_commit, candidate_inputs_sha256=candidate_inputs_sha256)


@cycle_app.command('dispatch-context')
def dispatch_context(cwd: Path = typer.Option(..., '--cwd'), json: bool = typer.Option(False, '--json')):
    """Find active stage enrollment for omitted-envelope dispatch protection."""
    import os

    from tc.db.connection import _main_checkout, find_db_path
    from tc.services.cycle_stages import dispatch_context as context

    def resolve():
        # Absence is a positive statement by this capable authority, not a
        # fallback for an old/missing tc, damaged DB or unresolved worktree.
        db_path = find_db_path()
        if db_path is not None:
            return context(cwd=cwd, db_path=db_path)
        current = Path.cwd().resolve()
        if cwd.resolve() != current or not cwd.is_dir():
            raise ValidationError('Dispatch context must be inspected from its requested cwd')
        if os.environ.get('TC_WORKTREE_DB'):
            raise ValidationError('Explicit database selection has no task authority')
        for directory in (current, *current.parents):
            store = directory / '.copilot'
            if store.is_symlink() and not store.is_dir():
                raise ValidationError('Task authority directory link is unresolved')
            candidate = store / 'tasks.db'
            try:
                candidate.lstat()
            except FileNotFoundError:
                pass
            else:
                raise ValidationError('Task authority exists but could not be discovered')
            marker = directory / '.git'
            if marker.is_file() or marker.is_symlink():
                main = _main_checkout(directory)
                if main is None:
                    raise ValidationError('Cannot establish linked-worktree task authority')
                store = main / '.copilot'
                if store.is_symlink() and not store.is_dir():
                    raise ValidationError('Shared task authority directory link is unresolved')
                shared = store / 'tasks.db'
                try:
                    shared.lstat()
                except FileNotFoundError:
                    pass
                else:
                    raise ValidationError('Shared task authority exists but could not be discovered')
        return {'managed': False, 'cycles': [], 'nativeDispatch': False}

    _run(resolve, json)
