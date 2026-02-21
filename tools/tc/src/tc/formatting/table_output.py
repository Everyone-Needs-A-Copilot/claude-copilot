"""Table output helpers for Task Copilot CLI."""

import sys
from typing import Optional

try:
    from rich.console import Console
    from rich.table import Table

    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False


def output_table(
    columns: list[str],
    rows: list[dict],
    title: Optional[str] = None,
) -> None:
    """Output data as a formatted table.

    Uses Rich if available, falls back to plain text tab-separated output.

    Args:
        columns: List of column header names.
        rows: List of dicts (or sqlite3.Row-compatible objects) with row data.
        title: Optional title to display above the table.
    """
    if not rows:
        if title:
            print(f"{title}: (no results)")
        else:
            print("(no results)")
        return

    # Normalize rows to plain dicts
    normalized: list[dict] = []
    for row in rows:
        if hasattr(row, "keys"):
            normalized.append(dict(row))
        else:
            normalized.append(row)

    if _RICH_AVAILABLE:
        _output_rich_table(columns, normalized, title)
    else:
        _output_plain_table(columns, normalized, title)


def _output_rich_table(
    columns: list[str],
    rows: list[dict],
    title: Optional[str],
) -> None:
    """Render a Rich table to stdout."""
    console = Console()
    table = Table(title=title, show_header=True, header_style="bold cyan")

    for col in columns:
        table.add_column(col, overflow="fold")

    for row in rows:
        table.add_row(*[str(row.get(col, "")) for col in columns])

    console.print(table)


def _output_plain_table(
    columns: list[str],
    rows: list[dict],
    title: Optional[str],
) -> None:
    """Render a plain text tab-separated table to stdout."""
    if title:
        print(f"=== {title} ===")

    # Header
    print("\t".join(columns))
    print("\t".join("-" * len(col) for col in columns))

    # Rows
    for row in rows:
        print("\t".join(str(row.get(col, "")) for col in columns))
