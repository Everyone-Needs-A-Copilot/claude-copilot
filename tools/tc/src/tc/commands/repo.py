"""Register local git checkouts that schemaVersion 3 acceptance contracts may cite."""

from __future__ import annotations

from pathlib import Path

import typer

from tc.db.exceptions import TcError
from tc.formatting import output_json
from tc.utils.errors import EXIT_VALIDATION, error_exit, require_db

repo_app = typer.Typer(help="Registered repositories for contract externalSources (id -> checkout and origin).")


@repo_app.command("add")
def add(
    repo_id: str = typer.Argument(..., metavar="ID"),
    path: Path = typer.Option(..., "--path", help="Top level of the git work tree; must have an origin remote."),
    json: bool = typer.Option(False, "--json"),
) -> None:
    """Register or repoint a repo id. Repointing requires the same origin URL."""
    from tc.services.external_sources import add_repo
    try:
        row = add_repo(repo_id=repo_id, path=path, db_path=require_db())
    except (TcError, OSError) as exc:
        error_exit(str(exc), EXIT_VALIDATION)
    output_json(row) if json else print(f"Registered {row['id']} -> {row['path']} ({row['remote']})")


@repo_app.command("list")
def list_(json: bool = typer.Option(False, "--json")) -> None:
    """List registered repositories."""
    from tc.services.external_sources import list_repos
    try:
        rows = list_repos(db_path=require_db())
    except (TcError, OSError) as exc:
        error_exit(str(exc), EXIT_VALIDATION)
    if json:
        output_json(rows)
    else:
        for row in rows:
            print(f"{row['id']}\t{row['path']}\t{row['remote']}")
