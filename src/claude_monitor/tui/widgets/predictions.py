"""Predictions panel widget for projections."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class PredictionsPanel(Widget):
    """Widget displaying usage projections."""

    DEFAULT_CSS = """
    PredictionsPanel {
        height: auto;
        border: solid $primary;
        padding: 1;
        margin: 0 1 1 1;
    }

    PredictionsPanel:focus-within {
        border: double $primary;
    }

    PredictionsPanel .panel-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    PredictionsPanel .prediction-row {
        height: 1;
    }

    PredictionsPanel .prediction-label {
        width: 20;
    }

    PredictionsPanel .prediction-value {
        width: 1fr;
        text-align: right;
    }

    PredictionsPanel .warning-value {
        color: $warning;
    }

    PredictionsPanel .critical-value {
        color: $error;
    }
    """

    # Time predictions
    time_to_90_pct: reactive[float] = reactive(0.0)  # minutes
    time_to_limit: reactive[float] = reactive(0.0)  # minutes

    # Token predictions
    session_end_tokens: reactive[int] = reactive(0)
    daily_projected_tokens: reactive[int] = reactive(0)

    # Cost predictions
    session_end_cost: reactive[float] = reactive(0.0)
    daily_projected_cost: reactive[float] = reactive(0.0)

    # Current state
    is_active: reactive[bool] = reactive(False)

    def compose(self) -> ComposeResult:
        """Compose the predictions panel layout."""
        with Vertical():
            yield Static("PROJECTIONS", classes="panel-title")
            yield Static("At current burn rate:", classes="section-header")
            yield Static("", id="time-to-90")
            yield Static("", id="time-to-limit")
            yield Static("", id="session-end")
            yield Static("", id="daily-projected")

    def on_mount(self) -> None:
        """Initialize the widget."""
        self._update_display()

    def _format_time(self, minutes: float) -> str:
        """Format minutes into human-readable time."""
        if minutes <= 0:
            return "--"
        if minutes < 60:
            return f"~{minutes:.0f} min"
        hours = minutes / 60
        if hours < 24:
            return f"~{hours:.1f} hours"
        days = hours / 24
        return f"~{days:.1f} days"

    def _update_display(self) -> None:
        """Update the display."""
        if not self.is_mounted:
            return

        try:
            if not self.is_active:
                self.query_one("#time-to-90", Static).update("No active session")
                self.query_one("#time-to-limit", Static).update("")
                self.query_one("#session-end", Static).update("")
                self.query_one("#daily-projected", Static).update("")
                return

            # Time to 90%
            time_90 = self.query_one("#time-to-90", Static)
            time_90_str = self._format_time(self.time_to_90_pct)
            time_90.update(f"90% limit in: {time_90_str}")

            # Time to limit
            time_limit = self.query_one("#time-to-limit", Static)
            time_limit_str = self._format_time(self.time_to_limit)
            time_limit.update(f"100% limit in: {time_limit_str}")

            # Session end projection
            session_end = self.query_one("#session-end", Static)
            if self.session_end_tokens > 0:
                session_end.update(
                    f"Session end: {self.session_end_tokens:,} tokens (${self.session_end_cost:.2f})"
                )
            else:
                session_end.update("Session end: --")

            # Daily projection
            daily = self.query_one("#daily-projected", Static)
            if self.daily_projected_tokens > 0:
                daily.update(
                    f"Daily projected: {self.daily_projected_tokens:,} tokens (${self.daily_projected_cost:.2f})"
                )
            else:
                daily.update("Daily projected: --")
        except Exception:
            pass  # Widget not fully mounted yet

    def watch_time_to_90_pct(self, value: float) -> None:
        """React to time changes."""
        if self.is_mounted:
            self._update_display()

    def watch_time_to_limit(self, value: float) -> None:
        """React to time changes."""
        if self.is_mounted:
            self._update_display()

    def watch_session_end_tokens(self, value: int) -> None:
        """React to token changes."""
        if self.is_mounted:
            self._update_display()

    def watch_daily_projected_tokens(self, value: int) -> None:
        """React to token changes."""
        if self.is_mounted:
            self._update_display()

    def watch_is_active(self, value: bool) -> None:
        """React to active state changes."""
        if self.is_mounted:
            self._update_display()
