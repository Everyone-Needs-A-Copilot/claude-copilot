"""Base screen class for monitor screens."""

import logging
import traceback
from typing import TYPE_CHECKING

from textual.widget import Widget

if TYPE_CHECKING:
    from claude_monitor.tui.app import ClaudeMonitorApp
    from claude_monitor.tui.state.app_state import AppState

logger = logging.getLogger(__name__)


class BaseMonitorScreen(Widget):
    """Base class for all monitor screens.

    Note: These are Widgets (not Screens) because they're composed
    inside the main app's Container, not pushed as full screens.

    Provides common functionality for accessing app state
    and handling updates.
    """

    DEFAULT_CSS = """
    BaseMonitorScreen {
        height: 1fr;
        width: 100%;
    }
    """

    @property
    def monitor_app(self) -> "ClaudeMonitorApp":
        """Get the typed app instance."""
        try:
            app = self.app
            logger.debug(f"{self.__class__.__name__}: app type={type(app).__name__}")
            return app  # type: ignore
        except Exception as e:
            logger.error(f"{self.__class__.__name__}: Failed to get app: {e}")
            raise

    @property
    def state(self) -> "AppState":
        """Get the application state."""
        try:
            state = self.monitor_app.state
            logger.debug(
                f"{self.__class__.__name__}: state.plan={state.plan}, "
                f"blocks={len(state.blocks)}, is_loading={state.is_loading}"
            )
            return state
        except Exception as e:
            logger.error(f"{self.__class__.__name__}: Failed to get state: {e}")
            logger.error(traceback.format_exc())
            raise

    def on_mount(self) -> None:
        """Handle screen mount."""
        logger.info(f"{self.__class__.__name__}: on_mount called")

    def refresh_display(self) -> None:
        """Refresh the display with current state.

        Override in subclasses to update widgets.
        """
        logger.debug(f"{self.__class__.__name__}: refresh_display called")
