"""Dashboard screen - real-time monitoring view."""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Static

from claude_monitor.tui.events import DataUpdated, PauseToggled
from claude_monitor.tui.screens.base import BaseMonitorScreen
from claude_monitor.tui.widgets import (
    BurnRateWidget,
    ModelUsageWidget,
    PredictionsPanel,
    UsagePanel,
)


class DashboardScreen(BaseMonitorScreen):
    """Real-time monitoring dashboard screen.

    Shows current session usage, burn rate, and projections.
    """

    DEFAULT_CSS = """
    DashboardScreen {
        layout: vertical;
        height: 1fr;
        width: 100%;
    }

    #dashboard-container {
        height: 1fr;
        width: 100%;
        padding: 0;
    }

    #metrics-row {
        height: auto;
        min-height: 8;
    }

    #bottom-row {
        height: auto;
        min-height: 8;
    }

    .paused-overlay {
        dock: top;
        height: 1;
        background: $warning;
        color: $text;
        text-align: center;
        text-style: bold;
    }
    """

    BINDINGS = [
        ("m", "show_models", "Models"),
        ("w", "show_whatif", "What-If"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the dashboard layout."""
        with Container(id="dashboard-container"):
            # Paused indicator (hidden by default)
            yield Static("PAUSED - Press Space to resume", id="paused-indicator", classes="paused-overlay")

            # Overview panel
            yield UsagePanel(id="usage-panel")

            # Metrics row: burn rate and predictions
            with Horizontal(id="metrics-row"):
                yield BurnRateWidget(id="burn-rate")
                yield PredictionsPanel(id="predictions")

            # Bottom row: model breakdown
            with Horizontal(id="bottom-row"):
                yield ModelUsageWidget(id="model-usage")

    def on_mount(self) -> None:
        """Handle screen mount."""
        # Hide paused indicator initially
        paused = self.query_one("#paused-indicator", Static)
        paused.display = False

        # Initial refresh
        self.refresh_display()

    def on_data_updated(self, event: DataUpdated) -> None:
        """Handle data update events from app."""
        self.refresh_display()

    def on_pause_toggled(self, event: PauseToggled) -> None:
        """Handle pause toggle events."""
        paused = self.query_one("#paused-indicator", Static)
        paused.display = event.is_paused

    def refresh_display(self) -> None:
        """Refresh display with current state."""
        state = self.state
        session = state.session

        # Update usage panel
        usage_panel = self.query_one("#usage-panel", UsagePanel)
        usage_panel.plan_name = state.plan.upper()
        usage_panel.tokens_used = session.tokens_used
        usage_panel.token_limit = state.token_limit
        usage_panel.cost_used = session.cost_used

        # Calculate projected cost based on burn rate
        if session.burn_rate > 0 and session.elapsed_minutes > 0:
            # Estimate remaining time in session (assume 5 hour window)
            remaining_mins = max(0, 300 - session.elapsed_minutes)
            projected_additional = (session.burn_rate * remaining_mins) * 0.00001  # rough cost estimate
            usage_panel.cost_projected = session.cost_used + projected_additional
        else:
            usage_panel.cost_projected = session.cost_used

        # Update burn rate widget
        burn_rate = self.query_one("#burn-rate", BurnRateWidget)
        burn_rate.burn_rate = session.burn_rate
        burn_rate.cost_per_hour = session.cost_per_hour

        # Update predictions panel
        predictions = self.query_one("#predictions", PredictionsPanel)
        predictions.is_active = session.is_active

        if session.is_active and session.burn_rate > 0:
            remaining_tokens = state.token_limit - session.tokens_used
            remaining_to_90 = (state.token_limit * 0.9) - session.tokens_used

            # Time to 90%
            if remaining_to_90 > 0:
                predictions.time_to_90_pct = remaining_to_90 / session.burn_rate
            else:
                predictions.time_to_90_pct = 0

            # Time to limit
            if remaining_tokens > 0:
                predictions.time_to_limit = remaining_tokens / session.burn_rate
            else:
                predictions.time_to_limit = 0

            # Session end projection (assume 5 hour window)
            remaining_mins = max(0, 300 - session.elapsed_minutes)
            predictions.session_end_tokens = int(
                session.tokens_used + (session.burn_rate * remaining_mins)
            )
            predictions.session_end_cost = predictions.session_end_tokens * 0.00001

            # Daily projection (extrapolate from current usage)
            if session.elapsed_minutes > 0:
                rate_per_day = (session.tokens_used / session.elapsed_minutes) * 60 * 8  # 8 hour day
                predictions.daily_projected_tokens = int(rate_per_day)
                predictions.daily_projected_cost = rate_per_day * 0.00001
        else:
            predictions.time_to_90_pct = 0
            predictions.time_to_limit = 0
            predictions.session_end_tokens = 0
            predictions.daily_projected_tokens = 0

        # Update model usage widget
        model_usage = self.query_one("#model-usage", ModelUsageWidget)
        model_usage.model_stats = session.per_model_stats
        model_usage.total_tokens = session.tokens_used

    def action_show_models(self) -> None:
        """Show model breakdown modal."""
        self.app.notify("Model breakdown - use widget below")

    def action_show_whatif(self) -> None:
        """Show what-if calculator."""
        self.app.notify("What-if calculator - coming in Phase 4")
