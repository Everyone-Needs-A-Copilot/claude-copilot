"""Versioned CLI boundary for Python-owned ecosystem reconciliation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Optional

import typer

from cc.core.ecosystem.reconciliation import (
    ReconciliationError,
    assess_reconciliation,
    build_plan_report,
    build_recover_report,
    build_verify_report,
)
from cc.core.ecosystem.reconciliation_types import (
    RECONCILIATION_SCHEMA_VERSION,
    ReconciliationRequest,
    RequestValidationError,
    parse_reconciliation_request,
)

reconcile_app = typer.Typer(
    help="Assess, plan, apply, recover, and verify the selected Copilot ecosystem.",
    no_args_is_help=True,
)
_PLAN_ID = re.compile(r"^plan_[0-9a-f]{32}$")


def _error(code: str, detail: str, exit_code: int) -> dict[str, Any]:
    return {
        "schema_version": RECONCILIATION_SCHEMA_VERSION,
        "phase": "error",
        "result": "error",
        "exit_code": exit_code,
        "error": {"code": code, "detail": detail},
    }


def _emit(report: dict[str, Any], *, output_json: bool) -> None:
    if output_json:
        typer.echo(json.dumps(report, sort_keys=True))
    else:
        typer.echo(f"{report['phase']}: {report['result']}")


def _load_request(path: Optional[Path]) -> ReconciliationRequest:
    if path is None:
        raise RequestValidationError("Provide the explicit reconciliation request.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RequestValidationError(
            "The reconciliation request file was not found."
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RequestValidationError(
            "The reconciliation request file could not be read."
        ) from exc
    return parse_reconciliation_request(payload)


def _run_report(builder: Callable[[], dict[str, Any]], *, output_json: bool) -> None:
    try:
        report = builder()
    except RequestValidationError as exc:
        _emit(_error("invalid-request", str(exc), 2), output_json=output_json)
        raise typer.Exit(2) from exc
    except ReconciliationError as exc:
        _emit(_error(exc.code, exc.detail, exc.exit_code), output_json=output_json)
        raise typer.Exit(exc.exit_code) from exc
    except Exception as exc:
        _emit(
            _error(
                "environment-error",
                "The reconciliation workflow could not inspect this Mac safely.",
                2,
            ),
            output_json=output_json,
        )
        raise typer.Exit(2) from exc
    _emit(report, output_json=output_json)
    if report["result"] in {"blocked", "partial"}:
        raise typer.Exit(1)


@reconcile_app.command("assess")
def assess(
    output_json: bool = typer.Option(
        False, "--json", help="Emit the versioned reconciliation report."
    ),
) -> None:
    """Inspect the Mac and every project below approved roots without writing."""
    _run_report(assess_reconciliation, output_json=output_json)


@reconcile_app.command("plan")
def plan(
    request: Optional[Path] = typer.Option(
        None, "--request", help="Versioned explicit roots/projects/components JSON."
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Emit the versioned reconciliation report."
    ),
) -> None:
    """Create an exact, expiring plan after a fresh read-only inspection."""
    _run_report(
        lambda: build_plan_report(_load_request(request)),
        output_json=output_json,
    )


@reconcile_app.command("assistant-prepare")
def assistant_prepare(
    request: Optional[Path] = typer.Option(
        None, "--request", help="The exact selected project batch."
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Emit the bounded preparation session report."
    ),
) -> None:
    """Prepare one private content-free Claude Code selection session."""
    from cc.core.ecosystem.reconciliation_assistant import (
        build_assistant_prepare_report,
    )

    _run_report(
        lambda: build_assistant_prepare_report(_load_request(request)),
        output_json=output_json,
    )


@reconcile_app.command("assistant-run")
def assistant_run(
    session_id: Optional[str] = typer.Option(
        None, "--session-id", help="Opaque session identifier returned by prepare."
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Emit the bounded Claude Code runner report."
    ),
) -> None:
    """Run one already-prepared Claude Code session without project access."""
    from cc.core.ecosystem.reconciliation_assistant import run_assistant_session

    _run_report(
        lambda: run_assistant_session(
            session_id or "",
            progress_callback=(None if output_json else typer.echo),
        ),
        output_json=output_json,
    )


@reconcile_app.command("assistant-status")
def assistant_status(
    session_id: Optional[str] = typer.Option(
        None, "--session-id", help="Opaque session identifier returned by prepare."
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Emit the validated proposal status report."
    ),
) -> None:
    """Read one private session and issue a proposal only after fresh validation."""
    from cc.core.ecosystem.reconciliation_assistant import (
        build_assistant_status_report,
    )

    _run_report(
        lambda: build_assistant_status_report(session_id or ""),
        output_json=output_json,
    )


@reconcile_app.command("apply")
def apply(
    request: Optional[Path] = typer.Option(
        None, "--request", help="The exact reviewed selection request."
    ),
    plan_id: Optional[str] = typer.Option(
        None, "--plan-id", help="Fresh opaque plan identifier returned by plan."
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Emit the versioned reconciliation receipt."
    ),
) -> None:
    """Apply one claimed plan through the guarded Python transaction."""

    def build() -> dict[str, Any]:
        if plan_id is None or not _PLAN_ID.fullmatch(plan_id):
            raise RequestValidationError("Provide the exact reviewed plan identifier.")
        from cc.core.ecosystem.reconciliation import build_apply_report

        return build_apply_report(_load_request(request), plan_id)

    _run_report(
        build,
        output_json=output_json,
    )


@reconcile_app.command("verify")
def verify(
    request: Optional[Path] = typer.Option(
        None, "--request", help="Versioned explicit roots/projects/components JSON."
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Emit the versioned reconciliation report."
    ),
) -> None:
    """Freshly verify the selected components without mutating state."""
    _run_report(
        lambda: build_verify_report(_load_request(request)),
        output_json=output_json,
    )


@reconcile_app.command("recover")
def recover(
    output_json: bool = typer.Option(
        False, "--json", help="Emit the versioned recovery report."
    ),
) -> None:
    """Safely finalize interrupted private reconciliation runs."""
    _run_report(build_recover_report, output_json=output_json)


__all__ = ["reconcile_app"]
