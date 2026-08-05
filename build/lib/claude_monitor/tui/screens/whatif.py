"""What-If scenario calculator modal."""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class WhatIfScreen(ModalScreen):
    """Modal screen for what-if scenario calculations."""

    DEFAULT_CSS = """
    WhatIfScreen {
        align: center middle;
    }

    #whatif-container {
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #whatif-title {
        text-style: bold;
        text-align: center;
        width: 100%;
        margin-bottom: 1;
    }

    .whatif-section {
        margin-bottom: 1;
    }

    .whatif-label {
        width: 20;
    }

    .whatif-value {
        width: 1fr;
    }

    #burn-rate-input {
        width: 20;
    }

    #projections {
        border: solid $secondary;
        padding: 1;
        margin: 1 0;
    }

    .projection-row {
        height: 1;
    }

    #whatif-footer {
        text-align: center;
        margin-top: 1;
    }

    #whatif-buttons {
        margin-top: 1;
        align: center middle;
    }
    """

    BINDINGS = [
        ("escape", "dismiss", "Close"),
    ]

    # Current values (will be set from app state)
    current_burn_rate: reactive[float] = reactive(0.0)
    current_tokens: reactive[int] = reactive(0)
    token_limit: reactive[int] = reactive(44000)

    # What-if burn rate
    whatif_rate: reactive[float] = reactive(0.0)

    def compose(self) -> ComposeResult:
        """Compose the what-if screen."""
        with Container(id="whatif-container"):
            yield Static("WHAT-IF SCENARIO CALCULATOR", id="whatif-title")

            # Current status
            with Vertical(classes="whatif-section"):
                yield Static("Current Status:", classes="whatif-label")
                yield Static("", id="current-status")

            # Burn rate input
            with Horizontal(classes="whatif-section"):
                yield Label("Burn rate (tok/min):", classes="whatif-label")
                yield Input(
                    placeholder="Enter rate...",
                    id="burn-rate-input",
                    type="number",
                )

            # Preset buttons
            with Horizontal(id="whatif-buttons"):
                yield Button("-50%", id="btn-half", variant="default")
                yield Button("-25%", id="btn-quarter", variant="default")
                yield Button("Current", id="btn-current", variant="primary")
                yield Button("+25%", id="btn-plus-quarter", variant="default")
                yield Button("+50%", id="btn-plus-half", variant="default")

            # Projections
            with Vertical(id="projections"):
                yield Static("Projections at this rate:", classes="whatif-label")
                yield Static("", id="time-to-90")
                yield Static("", id="time-to-limit")
                yield Static("", id="session-end")

            yield Static("Press ESC to close", id="whatif-footer")

    def on_mount(self) -> None:
        """Initialize with current values."""
        # Get current state from app
        try:
            state = self.app.state  # type: ignore
            self.current_burn_rate = state.session.burn_rate
            self.current_tokens = state.session.tokens_used
            self.token_limit = state.token_limit
            self.whatif_rate = self.current_burn_rate
        except AttributeError:
            pass

        self._update_display()

        # Set input value
        input_widget = self.query_one("#burn-rate-input", Input)
        input_widget.value = str(int(self.current_burn_rate))

    def _update_display(self) -> None:
        """Update the display with current values."""
        # Update current status
        status = self.query_one("#current-status", Static)
        status.update(
            f"Tokens: {self.current_tokens:,} / {self.token_limit:,} | "
            f"Rate: {self.current_burn_rate:,.0f} tok/min"
        )

        # Calculate projections
        if self.whatif_rate > 0:
            remaining = self.token_limit - self.current_tokens
            remaining_to_90 = (self.token_limit * 0.9) - self.current_tokens

            # Time to 90%
            time_90 = self.query_one("#time-to-90", Static)
            if remaining_to_90 > 0:
                mins_to_90 = remaining_to_90 / self.whatif_rate
                time_90.update(f"Time to 90%: {self._format_time(mins_to_90)}")
            else:
                time_90.update("Time to 90%: Already exceeded")

            # Time to limit
            time_limit = self.query_one("#time-to-limit", Static)
            if remaining > 0:
                mins_to_limit = remaining / self.whatif_rate
                time_limit.update(f"Time to 100%: {self._format_time(mins_to_limit)}")
            else:
                time_limit.update("Time to 100%: Already at limit")

            # Session end projection (assume 5 hour window, 300 minutes remaining)
            session_end = self.query_one("#session-end", Static)
            projected_tokens = self.current_tokens + (self.whatif_rate * 180)  # 3 hours
            session_end.update(f"3hr projection: {projected_tokens:,.0f} tokens")
        else:
            self.query_one("#time-to-90", Static).update("Time to 90%: --")
            self.query_one("#time-to-limit", Static).update("Time to 100%: --")
            self.query_one("#session-end", Static).update("3hr projection: --")

    def _format_time(self, minutes: float) -> str:
        """Format minutes into human-readable time."""
        if minutes < 0:
            return "--"
        if minutes < 60:
            return f"~{minutes:.0f} min"
        hours = minutes / 60
        if hours < 24:
            return f"~{hours:.1f} hours"
        days = hours / 24
        return f"~{days:.1f} days"

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle burn rate input changes."""
        if event.input.id == "burn-rate-input":
            try:
                self.whatif_rate = float(event.value) if event.value else 0.0
            except ValueError:
                self.whatif_rate = 0.0
            self._update_display()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle preset button presses."""
        multipliers = {
            "btn-half": 0.5,
            "btn-quarter": 0.75,
            "btn-current": 1.0,
            "btn-plus-quarter": 1.25,
            "btn-plus-half": 1.5,
        }

        button_id = event.button.id or ""
        multiplier = multipliers.get(button_id, 1.0)
        new_rate = self.current_burn_rate * multiplier
        self.whatif_rate = new_rate

        # Update input
        input_widget = self.query_one("#burn-rate-input", Input)
        input_widget.value = str(int(new_rate))

        self._update_display()
