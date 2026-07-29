"""Lock-acquiring stub for WS-A's still-engine-blocked mutating verb
(`repair`).

`update` GRADUATED out of this module in WS-A slice 4 -- it now has a real
engine (core/ecosystem/{mirror,materialize,policy}.py) and its own
`--json` contract; see cc/commands/update.py. `deprovision` GRADUATED out
of this module in WS-A slice 5 -- it now has a real engine
(core/ecosystem/deprovision.py) and its own `--json` contract; see
cc/commands/deprovision.py. `repair` remains ENGINE-BLOCKED here: the
logic that would actually perform it does not exist yet, and per
copilot-control-tower CLAUDE.md invariant #1 ("parse, never compute"), no
resolution/sync/wipe logic should be improvised here ahead of that engine
landing.

This module exists so the `flock` discipline around this verb is real and
testable NOW: the stub acquires the advisory copilot lock (proving
contention/serialization actually works) and then returns a structured
"not implemented" JSON response instead of silently no-op'ing or crashing.
"""

from __future__ import annotations

import json

import typer

from cc.core.locking import LockContentionError, copilot_lock

NOT_IMPLEMENTED_SCHEMA_VERSION = "1.0"


def _not_implemented_response(verb: str) -> dict:
    return {
        "schema_version": NOT_IMPLEMENTED_SCHEMA_VERSION,
        "error": {
            "code": "not-implemented",
            "message": (
                f"cc {verb} is engine-blocked: the sync/resolution engine has "
                "not landed yet (WS-A doctor-slice only implements doctor + "
                "the flock scaffold). The lock was acquired successfully; no "
                "mutation was attempted."
            ),
        },
    }


def _lock_contention_response(verb: str, detail: str) -> dict:
    return {
        "schema_version": NOT_IMPLEMENTED_SCHEMA_VERSION,
        "error": {
            "code": "lock-contention",
            "message": detail,
        },
    }


def _run_stub(verb: str) -> None:
    """
    Acquire the copilot lock, emit a not-implemented JSON body, exit 2.

    Exit code 2 is a provisional stand-in (these verbs have no frozen
    contract yet) chosen to match the doctor contract's "environment/
    unexpected condition" code, since "not implemented" is the CLI failing
    to do what was asked, not a clean success. Confirm with the CLI owner
    once these verbs get their own `--json` contracts.
    """
    try:
        with copilot_lock():
            typer.echo(json.dumps(_not_implemented_response(verb)))
    except LockContentionError as exc:
        typer.echo(json.dumps(_lock_contention_response(verb, str(exc))))
        raise typer.Exit(2) from exc
    raise typer.Exit(2)


def run_repair() -> None:
    """`cc repair` stub: acquires the copilot lock, then reports not-implemented."""
    _run_stub("repair")
