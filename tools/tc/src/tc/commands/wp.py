"""Work product commands for Task Copilot CLI."""

from pathlib import Path
from typing import Optional

import typer

from tc.db.connection import get_db, find_db_path
from tc.formatting import output_json, output_table, output_error_json
from tc.utils.errors import error_exit, require_db, EXIT_NOT_FOUND, EXIT_VALIDATION
from tc import WP_CONTENT_SIZE_THRESHOLD, WP_FILE_DIR

wp_app = typer.Typer(name="wp", help="Work product commands.")


def _row_to_dict(row) -> dict:
    return dict(row)


def _get_wp_file_dir(db_path: Path) -> Path:
    """Get the work product file directory relative to the .copilot dir."""
    return db_path.parent / "wp"


@wp_app.command("store")
def wp_store(
    task: int = typer.Option(..., "--task", help="Associated task ID."),
    type_: str = typer.Option(..., "--type", metavar="TYPE", help="Work product type."),
    title: str = typer.Option(..., "--title", help="Work product title."),
    content: Optional[str] = typer.Option(None, "--content", help="Work product content."),
    file: Optional[Path] = typer.Option(None, "--file", help="Read content from file."),
    agent: Optional[str] = typer.Option(None, "--agent", help="Authoring agent."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Store a work product, using hybrid storage for large content."""
    if file is not None:
        if not file.exists():
            error_exit(f"File not found: {file}", EXIT_VALIDATION)
        content = file.read_text(encoding="utf-8")

    db_path = require_db()
    conn = get_db(db_path)

    # Verify task exists
    task_row = conn.execute("SELECT id FROM tasks WHERE id = ?", (task,)).fetchone()
    if task_row is None:
        conn.close()
        error_exit(f"Task #{task} not found", EXIT_NOT_FOUND)

    stored_file_path: Optional[str] = None
    stored_content: Optional[str] = content

    # Check content size threshold
    if content and len(content.encode("utf-8")) > WP_CONTENT_SIZE_THRESHOLD:
        # Use hybrid storage: write to file
        wp_dir = _get_wp_file_dir(db_path)
        wp_dir.mkdir(parents=True, exist_ok=True)

        # Insert first to get ID, then write file
        cursor = conn.execute(
            "INSERT INTO work_products (task_id, type, title, content, file_path, agent) VALUES (?, ?, ?, ?, ?, ?)",
            (task, type_, title, None, None, agent),
        )
        conn.commit()
        wp_id = cursor.lastrowid

        file_path = wp_dir / f"{wp_id}.md"
        file_path.write_text(content, encoding="utf-8")

        conn.execute(
            "UPDATE work_products SET file_path = ?, content = NULL WHERE id = ?",
            (str(file_path), wp_id),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM work_products WHERE id = ?", (wp_id,)).fetchone()
        conn.close()

        if json:
            output_json(_row_to_dict(row))
        else:
            print(f"Stored work product #{row['id']}: {row['title']} (file: {row['file_path']})")
        return

    # Normal inline storage
    cursor = conn.execute(
        "INSERT INTO work_products (task_id, type, title, content, file_path, agent) VALUES (?, ?, ?, ?, ?, ?)",
        (task, type_, title, stored_content, stored_file_path, agent),
    )
    conn.commit()
    wp_id = cursor.lastrowid

    row = conn.execute("SELECT * FROM work_products WHERE id = ?", (wp_id,)).fetchone()
    conn.close()

    if json:
        output_json(_row_to_dict(row))
    else:
        print(f"Stored work product #{row['id']}: {row['title']}")


@wp_app.command("get")
def wp_get(
    wp_id: int = typer.Argument(..., help="Work product ID."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Get a work product by ID, reading file content if stored externally."""
    db_path = require_db()
    conn = get_db(db_path)

    row = conn.execute("SELECT * FROM work_products WHERE id = ?", (wp_id,)).fetchone()
    conn.close()

    if row is None:
        if json:
            output_error_json(f"Work product #{wp_id} not found", EXIT_NOT_FOUND)
        error_exit(f"Work product #{wp_id} not found", EXIT_NOT_FOUND)

    d = _row_to_dict(row)

    # Read from file if content is stored externally
    if d.get("file_path") and not d.get("content"):
        fp = Path(d["file_path"])
        if fp.exists():
            d["content"] = fp.read_text(encoding="utf-8")
        else:
            d["content"] = f"[File not found: {d['file_path']}]"

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
    type_: Optional[str] = typer.Option(None, "--type", metavar="TYPE", help="Filter by type."),
    agent: Optional[str] = typer.Option(None, "--agent", help="Filter by agent."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List work products with optional filters."""
    db_path = require_db()
    conn = get_db(db_path)

    query = "SELECT * FROM work_products WHERE 1=1"
    params: list = []

    if task is not None:
        query += " AND task_id = ?"
        params.append(task)
    if type_:
        query += " AND type = ?"
        params.append(type_)
    if agent:
        query += " AND agent = ?"
        params.append(agent)

    query += " ORDER BY id DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    data = [_row_to_dict(r) for r in rows]

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
    db_path = require_db()
    conn = get_db(db_path)

    try:
        rows = conn.execute(
            """SELECT wp.*,
                      snippet(work_products_fts, 1, '[', ']', '...', 20) as snippet
               FROM work_products wp
               JOIN work_products_fts ON wp.id = work_products_fts.rowid
               WHERE work_products_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (query, limit),
        ).fetchall()
    except Exception as e:
        conn.close()
        error_exit(f"Search error: {e}")

    conn.close()

    data = [_row_to_dict(r) for r in rows]

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
