"""Footer widget for the TUI application."""

from datetime import datetime
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class FooterWidget(Widget):
    """Application footer with key hints and status."""

    DEFAULT_CSS = """
    FooterWidget {
        dock: bottom;
        height: 1;
        background: $primary-background;
        padding: 0 1;
    }

    FooterWidget .footer-hints {
        width: 1fr;
    }

    FooterWidget .footer-status {
        width: auto;
        text-align: right;
        color: $text-muted;
    }

    FooterWidget .key {
        background: $primary;
        color: $text;
        padding: 0 1;
    }
    """

    current_view: reactive[str] = reactive("dashboard")
    last_refresh: reactive[Optional[datetime]] = reactive(None)

    def compose(self) -> ComposeResult:
        """Compose the footer layout."""
        with Horizontal():
            yield Static("", id="footer-hints", classes="footer-hints")
            yield Static("", id="footer-status", classes="footer-status")

    def on_mount(self) -> None:
        """Initialize footer content."""
        self._update_hints()
        self._update_status()

    def _update_hints(self) -> None:
        """Update key hints based on current view."""
        hints = self.query_one("#footer-hints", Static)

        # Common hints
        base_hints = "[1-4] Views  [Space] Pause  [?] Help  [q] Quit"

        # View-specific hints
        view_hints = {
            "dashboard": "[r] Refresh  [m] Models",
            "daily": "[s] Sort  [c] Compare  [Enter] Details",
            "monthly": "[s] Sort  [c] Compare  [Enter] Details",
            "agents": "[f] Filter  [r] Relationships  [Enter] Details",
        }

        specific = view_hints.get(self.current_view, "")
        if specific:
            hints.update(f"{base_hints}  |  {specific}")
        else:
            hints.update(base_hints)

    def _update_status(self) -> None:
        """Update status display."""
        status = self.query_one("#footer-status", Static)
        if self.last_refresh:
            time_str = self.last_refresh.strftime("%H:%M:%S")
            status.update(f"Last update: {time_str}")
        else:
            status.update("Loading...")

    def watch_current_view(self, value: str) -> None:
        """React to view changes."""
        self._update_hints()

    def watch_last_refresh(self, value: Optional[datetime]) -> None:
        """React to refresh time changes."""
        self._update_status()
