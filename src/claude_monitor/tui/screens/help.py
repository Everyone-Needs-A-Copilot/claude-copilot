"""Help screen overlay."""

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class HelpScreen(ModalScreen):
    """Modal help screen showing keyboard shortcuts."""

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }

    #help-container {
        width: 70;
        height: auto;
        max-height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #help-title {
        text-style: bold;
        text-align: center;
        width: 100%;
        margin-bottom: 1;
    }

    .help-section {
        margin-bottom: 1;
    }

    .help-section-title {
        text-style: bold;
        color: $primary;
    }

    .help-key {
        width: 12;
    }

    .help-desc {
        width: 1fr;
    }

    #help-footer {
        text-align: center;
        margin-top: 1;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("question_mark", "dismiss", "Close"),
        ("q", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the help screen."""
        with Container(id="help-container"):
            yield Static("KEYBOARD SHORTCUTS", id="help-title")

            # Global shortcuts
            with Vertical(classes="help-section"):
                yield Static("Global", classes="help-section-title")
                yield Static("  1-4        Switch views (Dashboard/Daily/Monthly/Agents)")
                yield Static("  Space      Pause/Resume monitoring")
                yield Static("  r          Force refresh data")
                yield Static("  ?          Show this help")
                yield Static("  q          Quit application")

            # Dashboard shortcuts
            with Vertical(classes="help-section"):
                yield Static("Dashboard", classes="help-section-title")
                yield Static("  m          Show model breakdown")
                yield Static("  w          What-if calculator")

            # Table view shortcuts
            with Vertical(classes="help-section"):
                yield Static("Daily/Monthly Views", classes="help-section-title")
                yield Static("  Up/Down    Navigate rows")
                yield Static("  Enter      Show details")
                yield Static("  s          Sort menu")
                yield Static("  c          Compare mode")

            # Agents shortcuts
            with Vertical(classes="help-section"):
                yield Static("Agents View", classes="help-section-title")
                yield Static("  f          Toggle filter")
                yield Static("  i          Toggle inactive agents")
                yield Static("  a          Show all (clear filters)")
                yield Static("  r          Show relationships")
                yield Static("  Enter      Show agent details")

            yield Static("Press ESC or ? to close", id="help-footer")
