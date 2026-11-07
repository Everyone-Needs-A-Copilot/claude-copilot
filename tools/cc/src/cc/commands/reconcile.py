"""`cc reconcile` -- retired.

The per-project reconcile engine (assess, plan, apply, recover, verify, the assistant and
guided sessions) copied framework files into projects and recorded per-file checksums in
`copilot.lock.json`. Central resolution replaced it: `cc project init` sets a project up in
one step, `cc release publish|rollback` moves every project to a new framework release,
and `cc doctor` verifies the machine. Every subcommand now refuses with that pointer.
"""

from __future__ import annotations

import typer

from cc.commands.retired import register_retired

reconcile_app = typer.Typer(
    help="RETIRED: use `cc project init` and `cc release` (framework copies into projects no longer exist).",
    no_args_is_help=True,
)

RETIRED_SUBCOMMANDS = (
    "assess",
    "prepare",
    "run",
    "request",
    "plan",
    "assistant-prepare",
    "assistant-run",
    "assistant-status",
    "guide-prepare",
    "guide-start",
    "guide-check",
    "guide-status",
    "guide-finalize",
    "apply",
    "verify",
    "recover",
)

for _name in RETIRED_SUBCOMMANDS:
    register_retired(reconcile_app, _name, display=f"reconcile {_name}")
