"""Versioned CLI boundary for Python-owned ecosystem reconciliation."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

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


def _run_report(
    builder: Callable[[], dict[str, Any]], *, output_json: bool
) -> dict[str, Any]:
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
    return report


@reconcile_app.command("assess")
def assess(
    output_json: bool = typer.Option(
        False, "--json", help="Emit the versioned reconciliation report."
    ),
) -> None:
    """Inspect the Mac and every project below approved roots without writing."""
    _run_report(assess_reconciliation, output_json=output_json)


@reconcile_app.command("prepare")
def prepare(
    output_json: bool = typer.Option(
        False, "--json", help="Emit the active setup preparation report."
    ),
) -> None:
    """Checkpoint Product work and download safe shared updates before setup."""
    from cc.core.ecosystem.setup_preflight import build_setup_prepare_report

    _run_report(build_setup_prepare_report, output_json=output_json)


@reconcile_app.command("run")
def run_setup_journey(
    output_json: bool = typer.Option(
        False, "--json", help="Emit the complete Python-owned setup journey."
    ),
) -> None:
    """Prepare, update, integrate, and verify this Mac and all projects."""
    from cc.core.ecosystem.setup_journey import build_setup_journey_report

    report = _run_report(build_setup_journey_report, output_json=output_json)
    if report["result"] != "ready":
        raise typer.Exit(1)


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


@reconcile_app.command("guide-prepare")
def guide_prepare(
    request: Optional[Path] = typer.Option(
        None, "--request", help="The exact selected project batch."
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Emit the guided instruction-package report."
    ),
) -> None:
    """Write one Sites-root work order for Codex or Claude Code."""
    from cc.core.ecosystem.reconciliation_guide import (
        build_guide_prepare_report,
    )

    helper_path = str(Path(sys.executable if getattr(sys, "frozen", False) else sys.argv[0]).resolve())
    _run_report(
        lambda: build_guide_prepare_report(
            _load_request(request), helper_path=helper_path
        ),
        output_json=output_json,
    )


@reconcile_app.command("guide-start")
def guide_start(
    guide_id: Optional[str] = typer.Option(
        None, "--guide-id", help="Opaque guided-session identifier."
    ),
    assistant: Optional[str] = typer.Option(
        None, "--assistant", help="codex or claude-code."
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Emit the guided-session start report."
    ),
) -> None:
    """Record that one visible root-level assistant session started."""
    from cc.core.ecosystem.reconciliation_guide import build_guide_start_report

    _run_report(
        lambda: build_guide_start_report(guide_id or "", assistant or ""),
        output_json=output_json,
    )


@reconcile_app.command("guide-check")
def guide_check(
    guide_id: Optional[str] = typer.Option(
        None, "--guide-id", help="Opaque guided-session identifier."
    ),
    project: Optional[str] = typer.Option(
        None, "--project", help="One exact project path from the work order."
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Emit the fresh per-project check."
    ),
) -> None:
    """Freshly verify one project and update Python-owned progress."""
    from cc.core.ecosystem.reconciliation_guide import build_guide_check_report

    _run_report(
        lambda: build_guide_check_report(guide_id or "", project or ""),
        output_json=output_json,
    )


@reconcile_app.command("guide-status")
def guide_status(
    guide_id: Optional[str] = typer.Option(
        None, "--guide-id", help="Opaque guided-session identifier."
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Emit current Python-owned guided progress."
    ),
) -> None:
    """Read one guided session without trusting assistant output."""
    from cc.core.ecosystem.reconciliation_guide import build_guide_status_report

    _run_report(
        lambda: build_guide_status_report(guide_id or ""),
        output_json=output_json,
    )


@reconcile_app.command("guide-finalize")
def guide_finalize(
    guide_id: Optional[str] = typer.Option(
        None, "--guide-id", help="Opaque guided-session identifier."
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Emit the fresh whole-run verification."
    ),
) -> None:
    """Freshly verify every selected project and close the guided run."""
    from cc.core.ecosystem.reconciliation_guide import (
        build_guide_finalize_report,
    )

    _run_report(
        lambda: build_guide_finalize_report(guide_id or ""),
        output_json=output_json,
    )


def _adopt_settings_hook_ledger_rows(
    loaded_request: ReconciliationRequest, report: dict[str, Any]
) -> None:
    """Best-effort follow-up: append the `mutations[]` ledger row for any
    project whose `.claude/settings.json` the guarded transaction above
    just merged via the `register-settings-hooks` operation.

    Deliberately OUTSIDE the audited claim/execute/finalize contract this
    function's caller drives: `mutations.apply_settings_hook()` acquires
    its OWN `project_lock()` per project (safe here -- `execute_reconciliation()`
    already released every per-project lock it held before returning the
    report this function reads) and is independently transactional
    (snapshot, atomic write, ledger row). Called AFTER the transaction
    already wrote the merged settings content, so this call's own
    `merge_hook_entries()` recomputation finds identical bytes already in
    place and takes the existing `"adopted"` branch -- ledger-row-only,
    never a second settings write (see that function's and
    `reconciliation_recipes.py::_claude_setup()`'s docstrings). Failures
    here are surfaced on stderr but NEVER raise past this point and NEVER
    change `apply`'s own exit code or JSON report -- the settings file
    itself is already durably correct regardless; a project missing only
    its ledger row is `"orphaned"`, not unenforced, and `cc settings-hook
    list-sources` / a fresh `cc reconcile apply` (or `cc settings-hook
    add`) can adopt it later.
    """
    claude_paths = {
        project.path for project in loaded_request.projects if "claude" in project.components
    }
    if not claude_paths:
        return
    applied_paths = {
        str(item.get("path"))
        for item in report.get("ledger", [])
        if isinstance(item, Mapping) and item.get("status") in {"applied", "unchanged"}
    }
    targets = claude_paths & applied_paths
    if not targets:
        return
    from cc.core.ecosystem.mutations import DEFAULT_HOOK_ENTRIES, apply_settings_hook

    for project_path in sorted(targets):
        try:
            apply_settings_hook(
                project_path,
                entries=DEFAULT_HOOK_ENTRIES,
                source="claude-copilot",
                component="claude",
                scope="project",
                applied_by="cc reconcile apply",
            )
        except Exception as exc:  # pragma: no cover - best-effort, never fatal
            typer.echo(
                f"reconcile apply: settings-hook ledger row not recorded for {project_path}: {exc}",
                err=True,
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
    # Loaded inside build() (not before _run_report()) so a bad --request
    # file still goes through _run_report()'s existing RequestValidationError
    # handling unchanged; captured into this outer slot purely so the
    # best-effort follow-up below can reuse it without a second parse.
    loaded_request_slot: dict[str, ReconciliationRequest] = {}

    def build() -> dict[str, Any]:
        if plan_id is None or not _PLAN_ID.fullmatch(plan_id):
            raise RequestValidationError("Provide the exact reviewed plan identifier.")
        from cc.core.ecosystem.reconciliation import build_apply_report

        loaded_request_slot["value"] = _load_request(request)
        return build_apply_report(loaded_request_slot["value"], plan_id)

    report = _run_report(
        build,
        output_json=output_json,
    )
    loaded_request = loaded_request_slot.get("value")
    if loaded_request is not None:
        _adopt_settings_hook_ledger_rows(loaded_request, report)


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
