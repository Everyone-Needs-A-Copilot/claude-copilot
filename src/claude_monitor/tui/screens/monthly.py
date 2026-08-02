"""Monthly aggregation screen."""

from typing import Any, Dict, List

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Static

from claude_monitor.tui.events import DataUpdated
from claude_monitor.tui.screens.base import BaseMonitorScreen
from claude_monitor.tui.widgets import SessionDataTable


class MonthlyScreen(BaseMonitorScreen):
    """Monthly usage aggregation screen.

    Shows usage broken down by month with trends.
    """

    DEFAULT_CSS = """
    MonthlyScreen {
        layout: vertical;
        height: 1fr;
        width: 100%;
    }

    #monthly-container {
        height: 1fr;
        width: 100%;
    }

    #monthly-header {
        height: auto;
        border: solid $primary;
        padding: 1;
        margin: 0 1 1 1;
    }

    #monthly-table-container {
        height: 1fr;
        margin: 0 1;
    }

    #monthly-footer {
        height: auto;
        border: solid $primary;
        padding: 1;
        margin: 0 1 1 1;
    }
    """

    BINDINGS = [
        ("s", "sort_menu", "Sort"),
        ("c", "compare_mode", "Compare"),
        ("enter", "show_details", "Details"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the monthly view layout."""
        with Container(id="monthly-container"):
            # Header
            with Vertical(id="monthly-header"):
                yield Static("MONTHLY USAGE", classes="panel-title")
                yield Static("3-month view with monthly breakdown", classes="muted")

            # Table
            with Vertical(id="monthly-table-container"):
                yield SessionDataTable(id="monthly-table")

            # Footer summary
            with Vertical(id="monthly-footer"):
                yield Static("Summary: Loading...", id="monthly-summary")

    def on_mount(self) -> None:
        """Handle screen mount."""
        table = self.query_one("#monthly-table", SessionDataTable)
        table.view_mode = "monthly"
        self._load_data()

    def on_data_updated(self, event: DataUpdated) -> None:
        """Handle data update events."""
        self._load_data()

    def _load_data(self) -> None:
        """Load and display monthly data from state."""
        # Get blocks from state and aggregate by month
        blocks = self.state.blocks
        monthly_data = self._aggregate_by_month(blocks)

        table = self.query_one("#monthly-table", SessionDataTable)
        table.data = monthly_data

        # Update summary
        self._update_summary(monthly_data)

    def _aggregate_by_month(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Aggregate blocks by month."""
        from collections import defaultdict
        from datetime import datetime

        monthly: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"tokens": 0, "cost": 0.0, "days": set()}
        )

        for block in blocks:
            # Get date from block
            start_time = block.get("startTime") or block.get("start_time")
            if not start_time:
                continue

            # Parse date
            if isinstance(start_time, str):
                try:
                    dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                    month_str = dt.strftime("%Y-%m")
                    date_str = dt.strftime("%Y-%m-%d")
                except (ValueError, AttributeError):
                    continue
            else:
                continue

            # Aggregate
            monthly[month_str]["month"] = month_str
            monthly[month_str]["tokens"] += block.get("totalTokens", 0)
            monthly[month_str]["cost"] += block.get("costUSD", 0.0)
            monthly[month_str]["days"].add(date_str)

        # Calculate daily averages and convert to list
        result = []
        for month_str, data in monthly.items():
            days_active = len(data["days"])
            data["days_active"] = days_active
            data["daily_avg"] = data["tokens"] // days_active if days_active > 0 else 0
            del data["days"]
            result.append(data)

        # Sort by month descending
        result.sort(key=lambda x: x.get("month", ""), reverse=True)
        return result[:3]  # Last 3 months

    def _update_summary(self, monthly_data: List[Dict[str, Any]]) -> None:
        """Update the summary display."""
        summary = self.query_one("#monthly-summary", Static)

        if not monthly_data:
            summary.update("Summary: No data available")
            return

        total_tokens = sum(d.get("tokens", 0) for d in monthly_data)
        total_cost = sum(d.get("cost", 0.0) for d in monthly_data)
        avg_tokens = total_tokens // len(monthly_data) if monthly_data else 0
        avg_cost = total_cost / len(monthly_data) if monthly_data else 0

        summary.update(
            f"3-month total: {total_tokens:,} tokens (${total_cost:.2f}) | "
            f"Monthly avg: {avg_tokens:,} tokens (${avg_cost:.2f})"
        )

    def action_sort_menu(self) -> None:
        """Show sort options."""
        self.app.notify("Sort: Press 'm' for month, 't' for tokens, 'c' for cost")

    def action_compare_mode(self) -> None:
        """Enter comparison mode."""
        self.app.notify("Compare mode - coming in Phase 4")

    def action_show_details(self) -> None:
        """Show details for selected month."""
        table = self.query_one("#monthly-table", SessionDataTable)
        selected = table.get_selected_row()
        if selected:
            self.app.notify(f"Selected: {selected.get('month', 'Unknown')}")
        else:
            self.app.notify("No row selected")
