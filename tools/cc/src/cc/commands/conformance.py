"""`cc conformance` -- retired.

The harness measured whether every project's per-file copies and `copilot.lock.json`
checksums matched the framework (project sweep, lock layer, plan/apply round trip). With
no copies and no locks there is nothing for it to verify; `cc doctor` verifies the machine
and `cc doctor --release` the release pointer.
"""

from __future__ import annotations

import typer

from cc.commands.retired import register_retired

conformance_app = typer.Typer(
    help="RETIRED: use `cc doctor` (per-project copy and lock conformance no longer exists).",
    no_args_is_help=True,
)

for _name in ("check", "report", "baseline", "explain", "list"):
    register_retired(conformance_app, _name, display=f"conformance {_name}")
