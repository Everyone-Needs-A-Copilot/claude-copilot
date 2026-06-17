"""Header widget for the TUI application."""

from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class HeaderWidget(Widget):
    """Application header with plan info, status, and time."""

    DEFAULT_CSS = """
    HeaderWidget {
        dock: top;
        height: 3;
        background: $primary-background;
        padding: 0 1;
    }

    HeaderWidget .header-left {
        width: 1fr;
    }

    HeaderWidget .header-center {
        width: auto;
        text-align: center;
    }

    HeaderWidget .header-right {
        width: auto;
        text-align: right;
    }

    HeaderWidget .plan-badge {
        background: $primary;
        color: $text;
        padding: 0 1;
    }

    HeaderWidget .paused-badge {
        background: $warning;
        color: $text;
        padding: 0 1;
        text-style: bold;
    }

    HeaderWidget .time-display {
        color: $text-muted;
    }
    """

    plan_name: reactive[str] = reactive("CUSTOM")
    is_paused: reactive[bool] = reactive(False)
    usage_percent: reactive[float] = reactive(0.0)

    def compose(self) -> ComposeResult:
        """Compose the header layout."""
        with Horizontal():
            yield Static("", id="header-left", classes="header-left")
            yield Static("Claude Code Usage Monitor", id="header-center", classes="header-center")
            yield Static("", id="header-right", classes="header-right")

    def on_mount(self) -> None:
        """Set up timer for clock updates."""
        self.set_interval(1, self._update_time)
        self._update_display()

    def _update_time(self) -> None:
        """Update the time display."""
        time_str = datetime.now().strftime("%H:%M:%S")
        right = self.query_one("#header-right", Static)
        right.update(time_str)

    def _update_display(self) -> None:
        """Update the header display."""
        left = self.query_one("#header-left", Static)

        # Build left side content
        parts = [f"[{self.plan_name}]"]
        if self.is_paused:
            parts.append(" PAUSED")

        left.update(" ".join(parts))

    def watch_plan_name(self, value: str) -> None:
        """React to plan name changes."""
        self._update_display()

    def watch_is_paused(self, value: bool) -> None:
        """React to pause state changes."""
        self._update_display()

    def watch_usage_percent(self, value: float) -> None:
        """React to usage percent changes."""
        center = self.query_one("#header-center", Static)
        if value > 0:
            center.update(f"Claude Code Usage Monitor | {value:.1f}%")
        else:
            center.update("Claude Code Usage Monitor")
