"""Usage overview panel widget."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from claude_monitor.tui.widgets.progress_bars import CostBar, TokenBar


class UsagePanel(Widget):
    """Token and cost usage overview panel."""

    DEFAULT_CSS = """
    UsagePanel {
        height: auto;
        border: solid $primary;
        padding: 1;
        margin: 0 1 1 1;
    }

    UsagePanel:focus-within {
        border: double $primary;
    }

    UsagePanel .panel-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    UsagePanel .plan-info {
        margin-bottom: 1;
    }

    UsagePanel .summary {
        margin-top: 1;
        text-align: center;
    }

    UsagePanel.warning {
        border: solid $warning;
    }

    UsagePanel.critical {
        border: solid $error;
    }
    """

    # Reactive properties
    plan_name: reactive[str] = reactive("CUSTOM")
    tokens_used: reactive[int] = reactive(0)
    token_limit: reactive[int] = reactive(44000)
    cost_used: reactive[float] = reactive(0.0)
    cost_projected: reactive[float] = reactive(0.0)
    reset_time: reactive[str] = reactive("")

    def compose(self) -> ComposeResult:
        """Compose the usage panel layout."""
        with Vertical():
            yield Static("OVERVIEW", classes="panel-title")
            yield Static("", id="plan-info", classes="plan-info")
            yield TokenBar()
            yield CostBar()
            yield Static("", id="summary", classes="summary")

    def on_mount(self) -> None:
        """Initialize the panel."""
        self._update_display()

    def _update_display(self) -> None:
        """Update all display elements."""
        # Skip if not mounted yet
        if not self.is_mounted:
            return

        try:
            # Update plan info
            plan_info = self.query_one("#plan-info", Static)
            reset_str = f" | Reset: {self.reset_time}" if self.reset_time else ""
            plan_info.update(f"Plan: {self.plan_name} | Limit: {self.token_limit:,} tokens{reset_str}")

            # Update token bar
            token_bar = self.query_one(TokenBar)
            token_bar.tokens_used = self.tokens_used
            token_bar.token_limit = self.token_limit

            # Update cost bar
            cost_bar = self.query_one(CostBar)
            cost_bar.cost_used = self.cost_used
            cost_bar.cost_projected = self.cost_projected

            # Update summary
            summary = self.query_one("#summary", Static)
            if self.token_limit > 0:
                pct = (self.tokens_used / self.token_limit) * 100
                remaining = self.token_limit - self.tokens_used
                summary.update(f"{pct:.1f}% used | {remaining:,} tokens remaining")
            else:
                summary.update("--")

            # Update panel styling based on usage
            self._update_threshold_styling()
        except Exception:
            pass  # Widget not fully mounted yet

    def _update_threshold_styling(self) -> None:
        """Update panel border color based on usage threshold."""
        self.remove_class("warning", "critical")
        if self.token_limit > 0:
            pct = (self.tokens_used / self.token_limit) * 100
            if pct >= 90:
                self.add_class("critical")
            elif pct >= 75:
                self.add_class("warning")

    def watch_plan_name(self, value: str) -> None:
        """React to plan name changes."""
        self._update_display()

    def watch_tokens_used(self, value: int) -> None:
        """React to token changes."""
        self._update_display()

    def watch_token_limit(self, value: int) -> None:
        """React to limit changes."""
        self._update_display()

    def watch_cost_used(self, value: float) -> None:
        """React to cost changes."""
        self._update_display()

    def watch_cost_projected(self, value: float) -> None:
        """React to projected cost changes."""
        self._update_display()

    def watch_reset_time(self, value: str) -> None:
        """React to reset time changes."""
        self._update_display()
