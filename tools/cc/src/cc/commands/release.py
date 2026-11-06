"""`cc release` commands: build, flip, rollback, status, history, prune, shims, doctor.

Exposed as `release_app`; the integration stream registers it in main.py.
`--home` (default: the user's home) lets every command run against a temporary
home. `build` takes a JSON file of framework pins plus the layers manifest.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from cc.core.release.engine import build, doctor, layout, pointer, prune, shims

release_app = typer.Typer(help="Release pointer: immutable releases behind ~/.copilot/current.")

HomeOpt = typer.Option(None, "--home", help="Home directory (default: user home).")


def _emit(data) -> None:
    typer.echo(json.dumps(data, indent=2, sort_keys=True))


def _fail(message: str) -> None:
    typer.echo(message, err=True)
    raise typer.Exit(1)


@release_app.command("build")
def build_cmd(
    pins: Path = typer.Option(..., "--pins", help="JSON file of framework component pins."),
    layers: Path = typer.Option(
        Path.home() / ".config" / "copilot" / "copilot.layers.yml", "--layers"
    ),
    home: Optional[Path] = HomeOpt,
    flip_after: bool = typer.Option(False, "--flip", help="Flip current to the new release."),
) -> None:
    """Build a release from signed tags; current changes only with --flip."""
    import yaml

    try:
        sources = build.sources_from_layers(
            yaml.safe_load(layers.read_text(encoding="utf-8")),
            json.loads(pins.read_text(encoding="utf-8")),
        )
        manifest = build.build_release(sources, home, post_build=build.build_cc_venv)
    except (build.ReleaseBuildError, OSError, ValueError) as exc:
        _fail(f"release build failed: {exc}")
    if flip_after:
        pointer.flip(manifest.release_id, home, reason="build --flip")
    _emit({"release": manifest.release_id, "flipped": flip_after})


@release_app.command("flip")
def flip_cmd(release_id: str, home: Optional[Path] = HomeOpt, reason: str = "") -> None:
    """Atomically point current at RELEASE_ID."""
    try:
        _emit(pointer.flip(release_id, home, reason=reason))
    except Exception as exc:
        _fail(f"flip failed: {exc}")


@release_app.command("rollback")
def rollback_cmd(
    to: Optional[str] = typer.Option(None, "--to"),
    steps: int = typer.Option(1, "--steps", min=1, help="Walk back this many releases"),
    home: Optional[Path] = HomeOpt,
    reason: str = "",
) -> None:
    """Walk back --steps releases through history, or to the --to named release."""
    try:
        _emit(pointer.rollback(home, to=to, steps=steps, reason=reason))
    except Exception as exc:
        _fail(f"rollback failed: {exc}")


@release_app.command("status")
def status_cmd(home: Optional[Path] = HomeOpt) -> None:
    _emit(pointer.status(home))


@release_app.command("history")
def history_cmd(home: Optional[Path] = HomeOpt) -> None:
    _emit(pointer.read_history(home))


@release_app.command("prune")
def prune_cmd(
    keep: int = typer.Option(layout.DEFAULT_KEEP, "--keep"),
    approve: bool = typer.Option(False, "--approve", help="Delete the paths of --receipt."),
    receipt: Optional[str] = typer.Option(None, "--receipt"),
    home: Optional[Path] = HomeOpt,
) -> None:
    """List exact paths a prune would delete; delete only with --approve --receipt ID."""
    try:
        if approve:
            if not receipt:
                _fail("--approve requires --receipt from a prior plan")
            _emit({"removed": prune.execute(receipt, home, approved=True)})
        else:
            _emit(prune.plan(home, keep=keep))
    except prune.PruneError as exc:
        _fail(str(exc))


@release_app.command("shims")
def shims_cmd(home: Optional[Path] = HomeOpt) -> None:
    """(Re)write the cc, tc and tc-limits shims."""
    _emit(shims.install(home))


@release_app.command("doctor")
def doctor_cmd(home: Optional[Path] = HomeOpt) -> None:
    """Run release checks; exit 1 on any failure (also used by `cc doctor --release`)."""
    checks = doctor.run(home)
    _emit([{"name": c.name, "ok": c.ok, "detail": c.detail} for c in checks])
    if not all(c.ok for c in checks):
        raise typer.Exit(1)
