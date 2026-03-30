"""Base screen class for monitor screens."""

from typing import TYPE_CHECKING

from textual.screen import Screen

if TYPE_CHECKING:
    from claude_monitor.tui.app import ClaudeMonitorApp
    from claude_monitor.tui.state.app_state import AppState


class BaseMonitorScreen(Screen):
    """Base class for all monitor screens.

    Provides common functionality for accessing app state
    and handling updates.
    """

    @property
    def monitor_app(self) -> "ClaudeMonitorApp":
        """Get the typed app instance."""
        return self.app  # type: ignore

    @property
    def state(self) -> "AppState":
        """Get the application state."""
        return self.monitor_app.state

    def on_mount(self) -> None:
        """Handle screen mount."""
        pass

    def refresh_display(self) -> None:
        """Refresh the display with current state.

        Override in subclasses to update widgets.
        """
        pass
