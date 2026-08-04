"""Session data table widget for daily/monthly views."""

import logging
from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import DataTable

logger = logging.getLogger(__name__)


class SessionDataTable(Widget):
    """Data table for displaying session/daily/monthly data."""

    DEFAULT_CSS = """
    SessionDataTable {
        height: 1fr;
    }

    SessionDataTable DataTable {
        height: 100%;
    }
    """

    data: reactive[List[Dict[str, Any]]] = reactive([], always_update=True)
    view_mode: reactive[str] = reactive("daily")  # daily or monthly
    sort_column: reactive[str] = reactive("date")
    sort_reverse: reactive[bool] = reactive(True)

    def __init__(self, *args, **kwargs):
        """Initialize the widget."""
        super().__init__(*args, **kwargs)
        self._columns_initialized = False
        self._current_column_mode: Optional[str] = None

    def compose(self) -> ComposeResult:
        """Compose the data table."""
        yield DataTable(id="session-data-table")

    def on_mount(self) -> None:
        """Initialize the table."""
        logger.debug(f"SessionDataTable.on_mount: id={self.id}")
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        self._setup_columns()
        self._load_data()

    def _setup_columns(self) -> None:
        """Setup table columns based on view mode."""
        logger.debug(f"SessionDataTable._setup_columns: view_mode={self.view_mode}, current={self._current_column_mode}")

        # Skip if columns are already set up for this mode
        if self._current_column_mode == self.view_mode and self._columns_initialized:
            logger.debug("Columns already set up for this mode, skipping")
            return

        table = self.query_one(DataTable)

        # Clear existing columns and rows
        try:
            # First clear rows, then clear with columns
            table.clear()
            # Remove all existing columns by clearing with columns=True
            if table.columns:
                logger.debug(f"Clearing {len(table.columns)} existing columns")
                table.clear(columns=True)
        except Exception as e:
            logger.warning(f"Error clearing table: {e}")

        try:
            if self.view_mode == "daily":
                table.add_column("Date", key="date")
                table.add_column("Tokens", key="tokens")
                table.add_column("Cost", key="cost")
                table.add_column("Sessions", key="sessions")
                table.add_column("Peak Hour", key="peak")
            else:  # monthly
                table.add_column("Month", key="month")
                table.add_column("Tokens", key="tokens")
                table.add_column("Cost", key="cost")
                table.add_column("Days Active", key="days")
                table.add_column("Daily Avg", key="avg")

            # Mark columns as initialized for this mode
            self._columns_initialized = True
            self._current_column_mode = self.view_mode
            logger.debug(f"Columns set up successfully for mode: {self.view_mode}")
        except Exception as e:
            logger.error(f"Error setting up columns: {e}")

    def _load_data(self) -> None:
        """Load data into the table."""
        table = self.query_one(DataTable)
        table.clear()

        if not self.data:
            if self.view_mode == "daily":
                table.add_row("No data", "--", "--", "--", "--")
            else:
                table.add_row("No data", "--", "--", "--", "--")
            return

        # Sort data
        sorted_data = sorted(
            self.data,
            key=lambda x: x.get(self.sort_column, ""),
            reverse=self.sort_reverse,
        )

        for item in sorted_data:
            if self.view_mode == "daily":
                table.add_row(
                    item.get("date", "--"),
                    f"{item.get('tokens', 0):,}",
                    f"${item.get('cost', 0.0):.2f}",
                    str(item.get("sessions", 0)),
                    item.get("peak_hour", "--"),
                )
            else:  # monthly
                table.add_row(
                    item.get("month", "--"),
                    f"{item.get('tokens', 0):,}",
                    f"${item.get('cost', 0.0):.2f}",
                    str(item.get("days_active", 0)),
                    f"{item.get('daily_avg', 0):,}",
                )

    def watch_data(self, value: List[Dict[str, Any]]) -> None:
        """React to data changes."""
        self._load_data()

    def watch_view_mode(self, value: str) -> None:
        """React to view mode changes."""
        logger.debug(f"SessionDataTable.watch_view_mode: {self._current_column_mode} -> {value}")
        # Reset column tracking when mode changes
        if value != self._current_column_mode:
            self._columns_initialized = False
        self._setup_columns()
        self._load_data()

    def watch_sort_column(self, value: str) -> None:
        """React to sort column changes."""
        self._load_data()

    def watch_sort_reverse(self, value: bool) -> None:
        """React to sort direction changes."""
        self._load_data()

    def sort_by(self, column: str) -> None:
        """Sort by the specified column."""
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = True

    def get_selected_row(self) -> Optional[Dict[str, Any]]:
        """Get the currently selected row data."""
        table = self.query_one(DataTable)
        if table.cursor_row is not None and self.data:
            idx = table.cursor_row
            if 0 <= idx < len(self.data):
                return self.data[idx]
        return None
