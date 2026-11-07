"""`cc release` commands: build, publish, flip, rollback, status, history, prune, shims, doctor.

Exposed as `release_app`; the integration stream registers it in main.py.
`--home` (default: the user's home) lets every command run against a temporary
home. `build` takes a JSON file of framework pins plus the layers manifest.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from cc.core.release import publish as publisher
from cc.core.release.engine import build, layout, pointer, prune, shims

release_app = typer.Typer(help="Release pointer: immutable releases behind ~/.copilot/current.")



@release_app.callback()
def _isolation_guard() -> None:
    """Fail before any command runs when $COPILOT_HOME cannot name a home safely."""
    try:
        layout.home_root()
    except ValueError as exc:
        _fail(str(exc))


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
        manifest = build.build_release(sources, home, post_build=publisher.make_post_build(home))
    except (build.ReleaseBuildError, OSError, ValueError) as exc:
        _fail(f"release build failed: {exc}")
    if flip_after:
        pointer.flip(manifest.release_id, home, reason="build --flip", on_moved=publisher.relink(home))
    _emit({"release": manifest.release_id, "flipped": flip_after})


@release_app.command("flip")
def flip_cmd(release_id: str, home: Optional[Path] = HomeOpt, reason: str = "") -> None:
    """Atomically point current at RELEASE_ID."""
    try:
        _emit(pointer.flip(release_id, home, reason=reason, on_moved=publisher.relink(home)))
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
        _emit(pointer.rollback(home, to=to, steps=steps, reason=reason, on_moved=publisher.relink(home)))
    except Exception as exc:
        _fail(f"rollback failed: {exc}")


@release_app.command("status")
def status_cmd(home: Optional[Path] = HomeOpt) -> None:
    """Show the active release pointer and its manifest."""
    _emit(pointer.status(home))


@release_app.command("history")
def history_cmd(home: Optional[Path] = HomeOpt) -> None:
    """Read the recorded central release transitions."""
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
def doctor_cmd(
    home: Optional[Path] = HomeOpt,
    codex_home: Optional[Path] = typer.Option(None, "--codex-home", help="Codex home (default: $CODEX_HOME or ~/.codex)."),
) -> None:
    """Run release checks; exit 1 on any failure (also used by `cc doctor --release`)."""
    checks = publisher.run_doctor(home, codex_home)
    _emit([{"name": c.name, "ok": c.ok, "detail": c.detail} for c in checks])
    if not all(c.ok for c in checks):
        raise typer.Exit(1)


@release_app.command("publish")
def publish_cmd(
    pins: Path = typer.Option(..., "--pins", help="JSON file of framework component pins."),
    layers: Path = typer.Option(
        Path.home() / ".config" / "copilot" / "copilot.layers.yml", "--layers"
    ),
    home: Optional[Path] = HomeOpt,
    codex_home: Optional[Path] = typer.Option(None, "--codex-home"),
    retrust: list[str] = typer.Option([], "--retrust", help="Plugin whose Codex content trust may reset."),
    no_strict_frozen: bool = typer.Option(False, "--no-strict-frozen", help="Allow plugin directory changes (resets Codex trust)."),
) -> None:
    """Build, flip, link, refresh the Codex marketplace, run doctor, record history; restore on failure."""
    import yaml

    try:
        sources = build.sources_from_layers(
            yaml.safe_load(layers.read_text(encoding="utf-8")),
            json.loads(pins.read_text(encoding="utf-8")),
        )
        report = publisher.publish(sources, home, codex_home, strict_frozen=not no_strict_frozen,
                                   retrust=retrust)
    except publisher.PublishError as exc:
        typer.echo(f"release publish failed at {exc.step}: {exc}", err=True)
        typer.echo(("previous state restored; " if exc.restored else "RESTORE INCOMPLETE; ")
                   + f"to roll back manually: {exc.rollback_hint}", err=True)
        raise typer.Exit(1)
    except (build.ReleaseBuildError, OSError, ValueError) as exc:
        _fail(f"release publish failed: {exc}")
    _emit(report.to_json())
