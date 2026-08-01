"""Burn rate widget for displaying token consumption rate."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class BurnRateWidget(Widget):
    """Widget displaying current burn rate and velocity."""

    DEFAULT_CSS = """
    BurnRateWidget {
        height: auto;
        border: solid $primary;
        padding: 1;
        margin: 0 1 1 1;
    }

    BurnRateWidget:focus-within {
        border: double $primary;
    }

    BurnRateWidget .panel-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    BurnRateWidget .rate-value {
        text-style: bold;
        text-align: center;
        height: 2;
    }

    BurnRateWidget .rate-large {
        text-style: bold;
    }

    BurnRateWidget .velocity-indicator {
        text-align: center;
        margin-top: 1;
    }

    BurnRateWidget .velocity-up {
        color: $error;
    }

    BurnRateWidget .velocity-down {
        color: $success;
    }

    BurnRateWidget .velocity-stable {
        color: $text-muted;
    }

    BurnRateWidget .cost-rate {
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }
    """

    burn_rate: reactive[float] = reactive(0.0)
    previous_rate: reactive[float] = reactive(0.0)
    cost_per_hour: reactive[float] = reactive(0.0)

    def compose(self) -> ComposeResult:
        """Compose the burn rate widget layout."""
        with Vertical():
            yield Static("BURN RATE", classes="panel-title")
            yield Static("", id="rate-value", classes="rate-value")
            yield Static("", id="velocity", classes="velocity-indicator")
            yield Static("", id="cost-rate", classes="cost-rate")

    def on_mount(self) -> None:
        """Initialize the widget."""
        self._update_display()

    def _update_display(self) -> None:
        """Update the display."""
        if not self.is_mounted:
            return

        try:
            # Update rate value
            rate_display = self.query_one("#rate-value", Static)
            if self.burn_rate > 0:
                rate_display.update(f"{self.burn_rate:,.0f} tokens/min")
            else:
                rate_display.update("No active session")

            # Update velocity indicator
            velocity = self.query_one("#velocity", Static)
            if self.burn_rate > 0 and self.previous_rate > 0:
                diff = self.burn_rate - self.previous_rate
                pct_change = (diff / self.previous_rate) * 100 if self.previous_rate > 0 else 0

                if abs(pct_change) < 5:
                    velocity.update("Stable")
                    velocity.remove_class("velocity-up", "velocity-down")
                    velocity.add_class("velocity-stable")
                elif diff > 0:
                    velocity.update(f"Increasing (+{pct_change:.0f}%)")
                    velocity.remove_class("velocity-stable", "velocity-down")
                    velocity.add_class("velocity-up")
                else:
                    velocity.update(f"Decreasing ({pct_change:.0f}%)")
                    velocity.remove_class("velocity-stable", "velocity-up")
                    velocity.add_class("velocity-down")
            else:
                velocity.update("--")
                velocity.remove_class("velocity-up", "velocity-down")
                velocity.add_class("velocity-stable")

            # Update cost rate
            cost_rate = self.query_one("#cost-rate", Static)
            if self.cost_per_hour > 0:
                cost_rate.update(f"${self.cost_per_hour:.2f}/hour")
            else:
                cost_rate.update("--")
        except Exception:
            pass  # Widget not fully mounted yet

    def watch_burn_rate(self, value: float) -> None:
        """React to burn rate changes."""
        if self.is_mounted:
            self._update_display()

    def watch_previous_rate(self, value: float) -> None:
        """React to previous rate changes."""
        if self.is_mounted:
            self._update_display()

    def watch_cost_per_hour(self, value: float) -> None:
        """React to cost rate changes."""
        if self.is_mounted:
            self._update_display()
