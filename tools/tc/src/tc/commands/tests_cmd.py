"""``tc tests map``: change-to-test map and lane selection."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer

from tc.db.exceptions import TcError
from tc.formatting import output_json
from tc.services import test_map as tm
from tc.utils.errors import EXIT_VALIDATION, error_exit, require_db

tests_app = typer.Typer(help="Per-project test selection.")
map_app = typer.Typer(help="Change-to-test map (.copilot/test-map.json).")
tests_app.add_typer(map_app, name="map")


def _guard(fn):
    try:
        return fn(require_db())
    except (TcError, OSError) as exc:
        error_exit(str(exc), EXIT_VALIDATION)


@map_app.command("show")
def show(json: bool = typer.Option(False, "--json")):
    """Show the map."""
    data = _guard(tm.load_map)
    if json:
        output_json(data)
        return
    if not data:
        print("No test map. Add one with: tc tests map set <glob> --focused CMD")
    for glob, entry in data.items():
        if glob == tm.RELEASE_KEY:
            print(f"release: broad={entry['broad']}")
        else:
            print(f"{glob}: lane={entry.get('lane', 'affected')} cap={entry.get('cap_seconds', tm.LANE_CAPS[entry.get('lane', 'affected')])}s focused={entry['focused']} affected={entry['affected']}")


@map_app.command("set")
def set_(
    glob: str = typer.Argument(..., help="Source glob, or 'release' with --broad."),
    focused: Optional[str] = typer.Option(None, "--focused"),
    affected: Optional[str] = typer.Option(None, "--affected"),
    lane: Optional[str] = typer.Option(None, "--lane", help="focused, affected (default) or broad."),
    cap_seconds: Optional[int] = typer.Option(None, "--cap-seconds"),
    broad: Optional[str] = typer.Option(None, "--broad", help="Only for 'release': the full-suite command."),
):
    """Add or replace a map entry."""
    if glob == tm.RELEASE_KEY:
        if broad is None or any(v is not None for v in (focused, affected, lane, cap_seconds)):
            error_exit("'release' takes only --broad CMD", EXIT_VALIDATION)
        output_json(_guard(lambda db: tm.set_release(db, broad)))
        return
    if focused is None or broad is not None:
        error_exit("--focused CMD is required (and --broad is only for 'release')", EXIT_VALIDATION)
    output_json(_guard(lambda db: tm.set_entry(db, glob, focused, affected, lane, cap_seconds)))


@map_app.command("remove")
def remove(glob: str):
    """Remove a map entry."""
    _guard(lambda db: tm.remove_entry(db, glob))
    print(f"Removed {glob}")


@map_app.command("select")
def select(
    paths: Optional[List[str]] = typer.Argument(None, help="Changed paths."),
    diff: bool = typer.Option(False, "--diff", help="Use git diff --name-only in the project root."),
    base: Optional[str] = typer.Option(None, "--base", help="With --diff: compare against this ref (default HEAD)."),
    json: bool = typer.Option(False, "--json"),
):
    """Pick focused/affected commands, lane and cap for changed paths."""
    if diff == bool(paths) or (base and not diff):
        error_exit("give changed paths, or --diff [--base REF] (not both)", EXIT_VALIDATION)

    def go(db):
        found = tm.changed_paths(Path(db).parent.parent, base) if diff else paths
        return tm.select(db, found)

    result = _guard(go)
    if json:
        output_json(result)
        return
    print(f"lane: {result['lane']} (cap {result['cap_seconds']} s)")
    for kind in ("focused", "affected"):
        for command in result[kind]:
            print(f"{kind}: {command}")
    if result.get("broad"):
        print(f"broad: {result['broad']}")
    if result["note"]:
        print(result["note"])
