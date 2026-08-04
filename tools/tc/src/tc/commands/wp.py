"""Work product commands for Task Copilot CLI."""

from pathlib import Path
from typing import Optional

import typer

from tc.formatting import output_json, output_table, output_error_json
from tc.utils.errors import error_exit, require_db, EXIT_NOT_FOUND, EXIT_VALIDATION
from tc.db.exceptions import TaskNotFound, ValidationError

wp_app = typer.Typer(name="wp", help="Work product commands.")


@wp_app.command("render")
def wp_render(
    wp_id: int = typer.Argument(..., help="Work product ID to render."),
    html: bool = typer.Option(
        True,
        "--html/--no-html",
        help="Render as self-contained HTML (default: true).",
    ),
    out: Optional[Path] = typer.Option(
        None,
        "--out",
        help="Override the output file path (default: .copilot/renders/WP-<id>.html).",
    ),
) -> None:
    """Render a work product to a standalone self-contained HTML file.

    Prints only the absolute path to the rendered file — the HTML body is
    never written to stdout (token-free side artifact).

    Output path convention: .copilot/renders/WP-<id>.html
    """
    from tc.services.render_html import render_wp_html
    from tc.db.exceptions import WorkProductNotFound

    if not html:
        error_exit("Only --html rendering is supported by this command.", EXIT_VALIDATION)

    db_path = require_db()
    try:
        html_path = render_wp_html(wp_id=wp_id, out_path=out, db_path=db_path)
    except WorkProductNotFound:
        error_exit(f"Work product #{wp_id} not found.", EXIT_NOT_FOUND)

    print(str(html_path))


@wp_app.command("store")
def wp_store(
    task: int = typer.Option(..., "--task", help="Associated task ID."),
    type_: str = typer.Option(..., "--type", metavar="TYPE", help="Work product type."),
    title: str = typer.Option(..., "--title", help="Work product title."),
    content: Optional[str] = typer.Option(
        None, "--content", help="Work product content."
    ),
    file: Optional[Path] = typer.Option(None, "--file", help="Read content from file."),
    agent: Optional[str] = typer.Option(None, "--agent", help="Authoring agent."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Store a work product, using hybrid storage for large content."""
    from tc.services.wp import store_wp as _store_wp

    if file is not None:
        if not file.exists():
            error_exit(f"File not found: {file}", EXIT_VALIDATION)
        content = file.read_text(encoding="utf-8")

    db_path = require_db()
    try:
        row = _store_wp(
            task_id=task,
            type_=type_,
            title=title,
            content=content,
            agent=agent,
            db_path=db_path,
        )
    except ValidationError as exc:
        error_exit(str(exc), EXIT_VALIDATION)
    except TaskNotFound as exc:
        error_exit(str(exc), EXIT_NOT_FOUND)

    if row.get("file_path") and not row.get("content"):
        if json:
            output_json(row)
        else:
            print(
                f"Stored work product #{row['id']}: {row['title']} (file: {row['file_path']})"
            )
    else:
        if json:
            output_json(row)
        else:
            print(f"Stored work product #{row['id']}: {row['title']}")


@wp_app.command("get")
def wp_get(
    wp_id: int = typer.Argument(..., help="Work product ID."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Get a work product by ID, reading file content if stored externally."""
    from tc.services.wp import get_wp as _get_wp
    from tc.db.exceptions import WorkProductNotFound

    db_path = require_db()
    try:
        d = _get_wp(wp_id=wp_id, db_path=db_path)
    except WorkProductNotFound:
        if json:
            output_error_json(f"Work product #{wp_id} not found", EXIT_NOT_FOUND)
        error_exit(f"Work product #{wp_id} not found", EXIT_NOT_FOUND)

    if json:
        output_json(d)
    else:
        for k, v in d.items():
            if k == "content" and v and len(v) > 200:
                print(f"{k}: {v[:200]}... [truncated]")
            else:
                print(f"{k}: {v}")


@wp_app.command("list")
def wp_list(
    task: Optional[int] = typer.Option(None, "--task", help="Filter by task ID."),
    type_: Optional[str] = typer.Option(
        None, "--type", metavar="TYPE", help="Filter by type."
    ),
    agent: Optional[str] = typer.Option(None, "--agent", help="Filter by agent."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List work products with optional filters."""
    from tc.services.wp import list_wps as _list_wps

    db_path = require_db()
    data = _list_wps(task=task, type_=type_, agent=agent, db_path=db_path)

    if json:
        output_json(data)
    else:
        output_table(
            ["id", "task_id", "type", "title", "agent", "created_at"],
            data,
            title="Work Products",
        )


@wp_app.command("search")
def wp_search(
    query: str = typer.Argument(..., help="Full-text search query."),
    limit: int = typer.Option(10, "--limit", help="Maximum results to return."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Search work products using FTS5 full-text search."""
    from tc.services.wp import search_wps as _search_wps
    from tc.db.exceptions import DatabaseError

    db_path = require_db()
    try:
        data = _search_wps(query=query, limit=limit, db_path=db_path)
    except DatabaseError as exc:
        error_exit(str(exc))

    if json:
        output_json(data)
    else:
        if not data:
            print(f"No results for: {query}")
        else:
            output_table(
                ["id", "task_id", "type", "title", "agent", "snippet"],
                data,
                title=f"Search: {query}",
            )
