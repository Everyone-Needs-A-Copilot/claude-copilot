"""Live dashboard command for Task Copilot CLI.

Provides a real-time terminal dashboard that polls the SQLite database
and renders task progress, active agents, and recent activity using
Rich Live + Layout.
"""

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class StreamProgress:
    """Progress data for a single stream."""

    stream_id: int
    name: str
    total: int = 0
    completed: int = 0
    in_progress: int = 0
    blocked: int = 0


@dataclass
class StatusCounts:
    """Aggregate task status counts."""

    pending: int = 0
    in_progress: int = 0
    completed: int = 0
    blocked: int = 0
    cancelled: int = 0

    @property
    def total(self) -> int:
        """Return total number of tasks across all statuses."""
        return (
            self.pending
            + self.in_progress
            + self.completed
            + self.blocked
            + self.cancelled
        )


@dataclass
class ActiveAgent:
    """An agent currently working on a task."""

    agent: str
    task_id: int
    task_title: str
    stream_name: str


@dataclass
class LogEntry:
    """A single agent log entry."""

    timestamp: str
    agent: str
    action: str
    task_id: Optional[int]
    details: Optional[str]


@dataclass
class DashboardData:
    """All data needed to render one frame of the dashboard."""

    totals: StatusCounts = field(default_factory=StatusCounts)
    streams: list[StreamProgress] = field(default_factory=list)
    agents: list[ActiveAgent] = field(default_factory=list)
    log_entries: list[LogEntry] = field(default_factory=list)
    last_refresh: str = ""


# ---------------------------------------------------------------------------
# Database queries
# ---------------------------------------------------------------------------

def _fetch_dashboard_data(
    conn: sqlite3.Connection,
    stream_filter: Optional[int] = None,
) -> DashboardData:
    """Query the database and return all dashboard data in one pass.

    Args:
        conn: Open SQLite connection.
        stream_filter: Optional stream ID to filter results.

    Returns:
        DashboardData populated from current database state.
    """
    data = DashboardData(last_refresh=datetime.now().strftime("%H:%M:%S"))

    # --- Status counts (overall) ------------------------------------------
    count_query = "SELECT status, COUNT(*) as cnt FROM tasks"
    count_params: list = []
    if stream_filter is not None:
        count_query += " WHERE stream_id = ?"
        count_params.append(stream_filter)
    count_query += " GROUP BY status"

    for row in conn.execute(count_query, count_params).fetchall():
        status = row["status"]
        cnt = row["cnt"]
        if hasattr(data.totals, status):
            setattr(data.totals, status, cnt)

    # --- Per-stream progress ----------------------------------------------
    stream_query = """
        SELECT
            s.id AS stream_id,
            s.name,
            t.status,
            COUNT(*) AS cnt
        FROM streams s
        LEFT JOIN tasks t ON t.stream_id = s.id
        WHERE s.status != 'archived'
    """
    stream_params: list = []
    if stream_filter is not None:
        stream_query += " AND s.id = ?"
        stream_params.append(stream_filter)
    stream_query += " GROUP BY s.id, t.status ORDER BY s.id"

    stream_map: dict[int, StreamProgress] = {}
    for row in conn.execute(stream_query, stream_params).fetchall():
        sid = row["stream_id"]
        if sid not in stream_map:
            stream_map[sid] = StreamProgress(stream_id=sid, name=row["name"])
        sp = stream_map[sid]
        status = row["status"]
        cnt = row["cnt"]
        if status == "completed":
            sp.completed += cnt
        elif status == "in_progress":
            sp.in_progress += cnt
        elif status == "blocked":
            sp.blocked += cnt
        if status is not None:
            sp.total += cnt

    data.streams = list(stream_map.values())

    # --- Active agents (claimed tasks) ------------------------------------
    agent_query = """
        SELECT
            t.claimed_by,
            t.id AS task_id,
            t.title,
            COALESCE(s.name, 'unassigned') AS stream_name
        FROM tasks t
        LEFT JOIN streams s ON s.id = t.stream_id
        WHERE t.claimed_by IS NOT NULL
          AND t.status = 'in_progress'
    """
    agent_params: list = []
    if stream_filter is not None:
        agent_query += " AND t.stream_id = ?"
        agent_params.append(stream_filter)
    agent_query += " ORDER BY t.claimed_at DESC"

    for row in conn.execute(agent_query, agent_params).fetchall():
        data.agents.append(
            ActiveAgent(
                agent=row["claimed_by"],
                task_id=row["task_id"],
                task_title=_truncate(row["title"], 36),
                stream_name=row["stream_name"],
            )
        )

    # --- Recent activity log ----------------------------------------------
    log_query = "SELECT * FROM agent_log"
    log_params: list = []
    if stream_filter is not None:
        log_query += " WHERE stream_id = ?"
        log_params.append(stream_filter)
    log_query += " ORDER BY id DESC LIMIT 10"

    for row in conn.execute(log_query, log_params).fetchall():
        ts = row["created_at"]
        if ts and len(ts) > 10:
            ts = ts[11:19]  # Extract HH:MM:SS from datetime string
        data.log_entries.append(
            LogEntry(
                timestamp=ts or "",
                agent=row["agent"],
                action=row["action"],
                task_id=row["task_id"],
                details=_truncate(row["details"], 48) if row["details"] else "",
            )
        )

    return data


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis if it exceeds max_len."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "\u2026"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render_header(data: DashboardData, refresh: int) -> Panel:
    """Render the top header panel with overall progress."""
    total = data.totals.total
    done = data.totals.completed
    pct = (done / total * 100) if total > 0 else 0.0

    bar_width = 40
    filled = int(bar_width * pct / 100)
    empty = bar_width - filled
    bar = f"[green]{'█' * filled}[/green][dim]{'░' * empty}[/dim]"

    title_text = (
        f"[bold cyan]TC Watch[/bold cyan]  "
        f"[dim]refresh: {refresh}s | {data.last_refresh}[/dim]"
    )
    progress_text = f"  Overall: {bar}  {pct:5.1f}%  ({done}/{total} tasks)"

    content = Text.from_markup(f"{title_text}\n{progress_text}")
    return Panel(content, border_style="cyan")


def _render_stream_panel(data: DashboardData) -> Panel:
    """Render the per-stream progress panel."""
    table = Table(
        show_header=True,
        header_style="bold",
        expand=True,
        show_edge=False,
        pad_edge=False,
    )
    table.add_column("Stream", style="cyan", min_width=12)
    table.add_column("Progress", min_width=20)
    table.add_column("%", justify="right", width=6)
    table.add_column("Done", justify="right", width=5)
    table.add_column("Total", justify="right", width=5)

    for sp in data.streams:
        pct = (sp.completed / sp.total * 100) if sp.total > 0 else 0.0
        bar_w = 16
        filled = int(bar_w * pct / 100)
        empty = bar_w - filled

        if sp.blocked > 0:
            bar_str = f"[green]{'█' * filled}[/green][red]{'▓' * min(sp.blocked, empty)}[/red][dim]{'░' * max(0, empty - sp.blocked)}[/dim]"
        else:
            bar_str = f"[green]{'█' * filled}[/green][dim]{'░' * empty}[/dim]"

        table.add_row(
            _truncate(sp.name, 16),
            bar_str,
            f"{pct:.0f}%",
            str(sp.completed),
            str(sp.total),
        )

    if not data.streams:
        table.add_row("[dim]No active streams[/dim]", "", "", "", "")

    return Panel(table, title="[bold]Stream Progress[/bold]", border_style="blue")


def _render_agents_panel(data: DashboardData) -> Panel:
    """Render the active agents table."""
    table = Table(
        show_header=True,
        header_style="bold",
        expand=True,
        show_edge=False,
        pad_edge=False,
    )
    table.add_column("Agent", style="yellow", min_width=10)
    table.add_column("Task", min_width=8)
    table.add_column("Title", min_width=12)
    table.add_column("Stream", style="dim", min_width=8)

    for agent in data.agents:
        table.add_row(
            agent.agent,
            f"#{agent.task_id}",
            agent.task_title,
            agent.stream_name,
        )

    if not data.agents:
        table.add_row("[dim]No active agents[/dim]", "", "", "")

    return Panel(table, title="[bold]Active Agents[/bold]", border_style="yellow")


def _render_status_panel(data: DashboardData) -> Panel:
    """Render the task status breakdown as a compact summary."""
    lines = [
        f"[green]  completed : {data.totals.completed:>4}[/green]",
        f"[yellow]  in_progress: {data.totals.in_progress:>4}[/yellow]",
        f"[dim]  pending    : {data.totals.pending:>4}[/dim]",
        f"[red]  blocked    : {data.totals.blocked:>4}[/red]",
        f"[dim]  cancelled  : {data.totals.cancelled:>4}[/dim]",
    ]
    content = Text.from_markup("\n".join(lines))
    return Panel(content, title="[bold]Status Breakdown[/bold]", border_style="green")


def _render_log_panel(data: DashboardData) -> Panel:
    """Render the recent activity log."""
    table = Table(
        show_header=True,
        header_style="bold",
        expand=True,
        show_edge=False,
        pad_edge=False,
    )
    table.add_column("Time", style="dim", width=8)
    table.add_column("Agent", style="yellow", min_width=10)
    table.add_column("Action", min_width=10)
    table.add_column("Task", width=6)
    table.add_column("Details", min_width=12)

    action_styles = {
        "completed": "green",
        "started": "cyan",
        "claimed": "yellow",
        "handoff": "magenta",
        "blocked": "red",
    }

    for entry in data.log_entries:
        style = action_styles.get(entry.action, "")
        action_text = f"[{style}]{entry.action}[/{style}]" if style else entry.action
        task_str = f"#{entry.task_id}" if entry.task_id else ""
        table.add_row(
            entry.timestamp,
            entry.agent,
            action_text,
            task_str,
            entry.details or "",
        )

    if not data.log_entries:
        table.add_row("[dim]No recent activity[/dim]", "", "", "", "")

    return Panel(table, title="[bold]Recent Activity[/bold]", border_style="magenta")


def _build_layout(data: DashboardData, refresh: int, compact: bool) -> Layout:
    """Assemble the full dashboard layout from data.

    Args:
        data: Current dashboard data snapshot.
        refresh: Refresh interval in seconds (displayed in header).
        compact: If True, omit the activity log panel.

    Returns:
        Rich Layout ready to be rendered.
    """
    layout = Layout()

    if compact:
        layout.split_column(
            Layout(name="header", size=4),
            Layout(name="middle"),
        )
        layout["middle"].split_row(
            Layout(name="streams"),
            Layout(name="right_col"),
        )
        layout["right_col"].split_column(
            Layout(name="agents"),
            Layout(name="status", size=9),
        )
    else:
        layout.split_column(
            Layout(name="header", size=4),
            Layout(name="middle"),
            Layout(name="footer"),
        )
        layout["middle"].split_row(
            Layout(name="streams"),
            Layout(name="right_col"),
        )
        layout["right_col"].split_column(
            Layout(name="agents"),
            Layout(name="status", size=9),
        )
        layout["footer"].size = 14

    layout["header"].update(_render_header(data, refresh))
    layout["streams"].update(_render_stream_panel(data))
    layout["agents"].update(_render_agents_panel(data))
    layout["status"].update(_render_status_panel(data))

    if not compact:
        layout["footer"].update(_render_log_panel(data))

    return layout


# ---------------------------------------------------------------------------
# Main command entry point
# ---------------------------------------------------------------------------

def watch(
    refresh: int = 5,
    compact: bool = False,
    stream_filter: Optional[int] = None,
) -> None:
    """Run the live dashboard loop.

    Polls the database every ``refresh`` seconds and re-renders the
    dashboard using Rich Live in alternate screen mode.

    Args:
        refresh: Seconds between database polls.
        compact: If True, omit the activity log panel.
        stream_filter: Optional stream ID to restrict all queries.
    """
    from tc.db.connection import get_db
    from tc.utils.errors import require_db

    db_path = require_db()
    console = Console()

    try:
        with Live(
            console=console,
            screen=True,
            refresh_per_second=1,
        ) as live:
            while True:
                conn = get_db(db_path)
                try:
                    data = _fetch_dashboard_data(conn, stream_filter)
                finally:
                    conn.close()

                layout = _build_layout(data, refresh, compact)
                live.update(layout)

                time.sleep(refresh)

    except KeyboardInterrupt:
        # Clean exit on Ctrl+C - no error message needed
        pass
