"""Progress bar widgets for usage display."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, ProgressBar, Static


class TokenBar(Widget):
    """Token usage progress bar with threshold coloring."""

    DEFAULT_CSS = """
    TokenBar {
        height: 3;
        padding: 0 1;
    }

    TokenBar .bar-label {
        width: 10;
    }

    TokenBar .bar-container {
        width: 1fr;
    }

    TokenBar ProgressBar {
        width: 100%;
    }

    TokenBar .bar-value {
        width: 20;
        text-align: right;
    }

    TokenBar.warning ProgressBar > .bar--bar {
        color: $warning;
    }

    TokenBar.critical ProgressBar > .bar--bar {
        color: $error;
    }
    """

    tokens_used: reactive[int] = reactive(0)
    token_limit: reactive[int] = reactive(44000)
    show_label: reactive[bool] = reactive(True)

    def compose(self) -> ComposeResult:
        """Compose the token bar layout."""
        with Horizontal():
            if self.show_label:
                yield Label("Tokens:", classes="bar-label")
            yield ProgressBar(total=100, show_eta=False, show_percentage=False, classes="bar-container")
            yield Static("", id="token-value", classes="bar-value")

    def on_mount(self) -> None:
        """Initialize the progress bar."""
        self._update_display()

    def _update_display(self) -> None:
        """Update the progress bar display."""
        if not self.is_mounted:
            return

        try:
            # Calculate percentage
            if self.token_limit > 0:
                pct = (self.tokens_used / self.token_limit) * 100
            else:
                pct = 0

            # Update progress bar
            bar = self.query_one(ProgressBar)
            bar.update(progress=pct)

            # Update value display
            value = self.query_one("#token-value", Static)
            value.update(f"{self.tokens_used:,} / {self.token_limit:,}")

            # Update styling based on threshold
            self.remove_class("warning", "critical")
            if pct >= 90:
                self.add_class("critical")
            elif pct >= 75:
                self.add_class("warning")
        except Exception:
            pass  # Widget not fully mounted yet

    def watch_tokens_used(self, value: int) -> None:
        """React to token changes."""
        if self.is_mounted:
            self._update_display()

    def watch_token_limit(self, value: int) -> None:
        """React to limit changes."""
        if self.is_mounted:
            self._update_display()


class CostBar(Widget):
    """Cost usage progress bar."""

    DEFAULT_CSS = """
    CostBar {
        height: 3;
        padding: 0 1;
    }

    CostBar .bar-label {
        width: 10;
    }

    CostBar .bar-container {
        width: 1fr;
    }

    CostBar ProgressBar {
        width: 100%;
    }

    CostBar .bar-value {
        width: 20;
        text-align: right;
    }

    CostBar ProgressBar > .bar--bar {
        color: $success;
    }
    """

    cost_used: reactive[float] = reactive(0.0)
    cost_projected: reactive[float] = reactive(0.0)
    show_label: reactive[bool] = reactive(True)

    def compose(self) -> ComposeResult:
        """Compose the cost bar layout."""
        with Horizontal():
            if self.show_label:
                yield Label("Cost:", classes="bar-label")
            yield ProgressBar(total=100, show_eta=False, show_percentage=False, classes="bar-container")
            yield Static("", id="cost-value", classes="bar-value")

    def on_mount(self) -> None:
        """Initialize the progress bar."""
        self._update_display()

    def _update_display(self) -> None:
        """Update the progress bar display."""
        if not self.is_mounted:
            return

        try:
            # Calculate percentage based on projected
            if self.cost_projected > 0:
                pct = (self.cost_used / self.cost_projected) * 100
            else:
                pct = 0

            # Update progress bar
            bar = self.query_one(ProgressBar)
            bar.update(progress=min(pct, 100))

            # Update value display
            value = self.query_one("#cost-value", Static)
            if self.cost_projected > 0:
                value.update(f"${self.cost_used:.2f} / ${self.cost_projected:.2f}")
            else:
                value.update(f"${self.cost_used:.2f}")
        except Exception:
            pass  # Widget not fully mounted yet

    def watch_cost_used(self, value: float) -> None:
        """React to cost changes."""
        if self.is_mounted:
            self._update_display()

    def watch_cost_projected(self, value: float) -> None:
        """React to projected cost changes."""
        if self.is_mounted:
            self._update_display()


class TimeBar(Widget):
    """Time remaining progress bar."""

    DEFAULT_CSS = """
    TimeBar {
        height: 3;
        padding: 0 1;
    }

    TimeBar .bar-label {
        width: 10;
    }

    TimeBar .bar-container {
        width: 1fr;
    }

    TimeBar ProgressBar {
        width: 100%;
    }

    TimeBar .bar-value {
        width: 20;
        text-align: right;
    }

    TimeBar ProgressBar > .bar--bar {
        color: cyan;
    }
    """

    elapsed_minutes: reactive[float] = reactive(0.0)
    total_minutes: reactive[float] = reactive(300.0)  # 5 hours default
    show_label: reactive[bool] = reactive(True)

    def compose(self) -> ComposeResult:
        """Compose the time bar layout."""
        with Horizontal():
            if self.show_label:
                yield Label("Time:", classes="bar-label")
            yield ProgressBar(total=100, show_eta=False, show_percentage=False, classes="bar-container")
            yield Static("", id="time-value", classes="bar-value")

    def on_mount(self) -> None:
        """Initialize the progress bar."""
        self._update_display()

    def _update_display(self) -> None:
        """Update the progress bar display."""
        if not self.is_mounted:
            return

        try:
            # Calculate percentage
            if self.total_minutes > 0:
                pct = (self.elapsed_minutes / self.total_minutes) * 100
            else:
                pct = 0

            # Update progress bar
            bar = self.query_one(ProgressBar)
            bar.update(progress=min(pct, 100))

            # Update value display
            value = self.query_one("#time-value", Static)
            elapsed_h = int(self.elapsed_minutes // 60)
            elapsed_m = int(self.elapsed_minutes % 60)
            remaining = max(0, self.total_minutes - self.elapsed_minutes)
            remaining_h = int(remaining // 60)
            remaining_m = int(remaining % 60)
            value.update(f"{elapsed_h}h{elapsed_m:02d}m / {remaining_h}h{remaining_m:02d}m left")
        except Exception:
            pass  # Widget not fully mounted yet

    def watch_elapsed_minutes(self, value: float) -> None:
        """React to elapsed time changes."""
        if self.is_mounted:
            self._update_display()

    def watch_total_minutes(self, value: float) -> None:
        """React to total time changes."""
        if self.is_mounted:
            self._update_display()
