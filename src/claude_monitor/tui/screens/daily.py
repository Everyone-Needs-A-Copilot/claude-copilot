"""Daily aggregation screen."""

import logging
import traceback
from typing import Any, Dict, List

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Static

from claude_monitor.tui.events import DataUpdated
from claude_monitor.tui.screens.base import BaseMonitorScreen
from claude_monitor.tui.widgets import SessionDataTable

logger = logging.getLogger(__name__)


class DailyScreen(BaseMonitorScreen):
    """Daily usage aggregation screen.

    Shows usage broken down by day with sorting and drill-down.
    """

    DEFAULT_CSS = """
    DailyScreen {
        layout: vertical;
        height: 1fr;
        width: 100%;
    }

    #daily-container {
        height: 1fr;
        width: 100%;
    }

    #daily-header {
        height: auto;
        border: solid $primary;
        padding: 1;
        margin: 0 1 1 1;
    }

    #daily-table-container {
        height: 1fr;
        margin: 0 1;
    }

    #daily-footer {
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
        """Compose the daily view layout."""
        with Container(id="daily-container"):
            # Header
            with Vertical(id="daily-header"):
                yield Static("DAILY USAGE", classes="panel-title")
                yield Static("7-day view with daily breakdown", classes="muted")

            # Table
            with Vertical(id="daily-table-container"):
                yield SessionDataTable(id="daily-table")

            # Footer summary
            with Vertical(id="daily-footer"):
                yield Static("Summary: Loading...", id="daily-summary")

    def on_mount(self) -> None:
        """Handle screen mount."""
        logger.info("DailyScreen.on_mount called")
        try:
            super().on_mount()
            logger.debug("Querying #daily-table")
            table = self.query_one("#daily-table", SessionDataTable)
            logger.debug(f"Found table: {table}")
            table.view_mode = "daily"
            logger.debug("Loading data...")
            self._load_data()
            logger.info("DailyScreen mount complete")
        except Exception as e:
            logger.error(f"DailyScreen.on_mount failed: {e}")
            logger.error(traceback.format_exc())

    def on_data_updated(self, event: DataUpdated) -> None:
        """Handle data update events."""
        self._load_data()

    def _load_data(self) -> None:
        """Load and display daily data from state."""
        logger.debug("DailyScreen._load_data called")
        try:
            # Get blocks from state and aggregate by day
            blocks = self.state.blocks
            logger.debug(f"Got {len(blocks)} blocks from state")
            daily_data = self._aggregate_by_day(blocks)
            logger.debug(f"Aggregated to {len(daily_data)} daily records")

            table = self.query_one("#daily-table", SessionDataTable)
            table.data = daily_data
            logger.debug("Set table data")

            # Update summary
            self._update_summary(daily_data)
            logger.debug("Updated summary")
        except Exception as e:
            logger.error(f"DailyScreen._load_data failed: {e}")
            logger.error(traceback.format_exc())

    def _aggregate_by_day(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Aggregate blocks by day."""
        from collections import defaultdict
        from datetime import datetime

        daily: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"tokens": 0, "cost": 0.0, "sessions": 0, "peak_hour": None, "hours": defaultdict(int)}
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
                    date_str = dt.strftime("%Y-%m-%d")
                    hour = dt.hour
                except (ValueError, AttributeError):
                    continue
            else:
                continue

            # Aggregate
            daily[date_str]["date"] = date_str
            daily[date_str]["tokens"] += block.get("totalTokens", 0)
            daily[date_str]["cost"] += block.get("costUSD", 0.0)
            daily[date_str]["sessions"] += 1
            daily[date_str]["hours"][hour] += block.get("totalTokens", 0)

        # Find peak hours and convert to list
        result = []
        for date_str, data in daily.items():
            if data["hours"]:
                peak_hour = max(data["hours"], key=data["hours"].get)
                data["peak_hour"] = f"{peak_hour:02d}:00"
            else:
                data["peak_hour"] = "--"
            del data["hours"]
            result.append(data)

        # Sort by date descending
        result.sort(key=lambda x: x.get("date", ""), reverse=True)
        return result[:7]  # Last 7 days

    def _update_summary(self, daily_data: List[Dict[str, Any]]) -> None:
        """Update the summary display."""
        summary = self.query_one("#daily-summary", Static)

        if not daily_data:
            summary.update("Summary: No data available")
            return

        total_tokens = sum(d.get("tokens", 0) for d in daily_data)
        total_cost = sum(d.get("cost", 0.0) for d in daily_data)
        avg_tokens = total_tokens // len(daily_data) if daily_data else 0
        avg_cost = total_cost / len(daily_data) if daily_data else 0

        summary.update(
            f"7-day total: {total_tokens:,} tokens (${total_cost:.2f}) | "
            f"Daily avg: {avg_tokens:,} tokens (${avg_cost:.2f})"
        )

    def action_sort_menu(self) -> None:
        """Show sort options."""
        self.app.notify("Sort: Press 'd' for date, 't' for tokens, 'c' for cost")

    def action_compare_mode(self) -> None:
        """Enter comparison mode."""
        self.app.notify("Compare mode - coming in Phase 4")

    def action_show_details(self) -> None:
        """Show details for selected day."""
        table = self.query_one("#daily-table", SessionDataTable)
        selected = table.get_selected_row()
        if selected:
            self.app.notify(f"Selected: {selected.get('date', 'Unknown')}")
        else:
            self.app.notify("No row selected")
