"""Main Textual application for Claude Code Usage Monitor."""

import logging
from typing import Any, Dict, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container

from claude_monitor.tui.events import DataUpdated, PauseToggled, ViewSwitched
from claude_monitor.tui.state.app_state import AppState
from claude_monitor.tui.widgets import FooterWidget, HeaderWidget

logger = logging.getLogger(__name__)


class ClaudeMonitorApp(App):
    """Interactive Claude Code Usage Monitor TUI.

    This application provides an interactive terminal interface for
    monitoring Claude AI token usage with keyboard-driven navigation.
    """

    TITLE = "Claude Code Usage Monitor"
    SUB_TITLE = "Interactive TUI"

    CSS_PATH = "styles.tcss"

    BINDINGS = [
        # Global bindings
        Binding("q", "quit", "Quit", priority=True),
        Binding("question_mark", "show_help", "Help"),
        Binding("space", "toggle_pause", "Pause/Resume"),
        Binding("r", "force_refresh", "Refresh"),
        Binding("w", "show_whatif", "What-If"),
        # View switching
        Binding("1", "switch_view('dashboard')", "Dashboard", show=True),
        Binding("2", "switch_view('daily')", "Daily", show=True),
        Binding("3", "switch_view('monthly')", "Monthly", show=True),
        Binding("4", "switch_view('agents')", "Agents", show=True),
    ]

    def __init__(
        self,
        orchestrator: Any,
        settings: Any,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Initialize the application.

        Args:
            orchestrator: MonitoringOrchestrator instance
            settings: Application settings
            *args: Additional positional arguments for App
            **kwargs: Additional keyword arguments for App
        """
        super().__init__(*args, **kwargs)
        self.orchestrator = orchestrator
        self.settings = settings
        self.state = AppState()

        # Initialize state from settings
        if hasattr(settings, "plan"):
            self.state.plan = settings.plan
        if hasattr(settings, "timezone"):
            self.state.timezone = settings.timezone

        # Track current screen
        self._current_view = "dashboard"

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        yield HeaderWidget(id="app-header")
        with Container(id="main-content"):
            # Import screens here to avoid circular imports
            from claude_monitor.tui.screens.dashboard import DashboardScreen
            yield DashboardScreen(id="dashboard-screen")
        yield FooterWidget(id="app-footer")

    def on_mount(self) -> None:
        """Handle application mount event."""
        logger.info("TUI application mounted")

        # Register orchestrator callback
        self.orchestrator.register_update_callback(self._on_data_update)

        # Register session change callback
        self.orchestrator.register_session_callback(self._on_session_change)

        # Start monitoring
        self.orchestrator.start()

        # Update header with plan info
        self._update_header()

    def on_unmount(self) -> None:
        """Handle application unmount event."""
        logger.info("TUI application unmounting")
        self.orchestrator.stop()

    def _on_data_update(self, data: Dict[str, Any]) -> None:
        """Handle data updates from orchestrator (called from background thread).

        Args:
            data: Monitoring data dictionary
        """
        # Use call_from_thread to safely update UI from background thread
        self.call_from_thread(self._process_data_update, data)

    def _process_data_update(self, data: Dict[str, Any]) -> None:
        """Process data update on main thread.

        Args:
            data: Monitoring data dictionary
        """
        # Update state
        self.state.update_from_monitoring_data(data)

        # Post event for widgets to react
        self.post_message(DataUpdated(data))

        # Update header and footer
        self._update_header()
        self._update_footer()

    def _on_session_change(
        self, event_type: str, session_id: str, session_data: Optional[Dict[str, Any]]
    ) -> None:
        """Handle session change events.

        Args:
            event_type: Type of event (session_start, session_end)
            session_id: Session identifier
            session_data: Optional session data
        """
        logger.info(f"Session {event_type}: {session_id}")

    def _update_header(self) -> None:
        """Update the header widget with current state."""
        try:
            header = self.query_one("#app-header", HeaderWidget)
            header.plan_name = self.state.plan.upper()
            header.is_paused = self.state.is_paused
            header.usage_percent = self.state.session.usage_percentage
        except Exception:
            pass  # Header might not be mounted yet

    def _update_footer(self) -> None:
        """Update the footer widget with current state."""
        try:
            footer = self.query_one("#app-footer", FooterWidget)
            footer.current_view = self._current_view
            footer.last_refresh = self.state.last_refresh
        except Exception:
            pass  # Footer might not be mounted yet

    # Action handlers

    def action_toggle_pause(self) -> None:
        """Toggle pause state."""
        is_paused = self.state.toggle_paused()
        self.post_message(PauseToggled(is_paused))
        self._update_header()
        self.notify(
            "Monitoring paused" if is_paused else "Monitoring resumed",
            severity="warning" if is_paused else "information",
        )

    def action_force_refresh(self) -> None:
        """Force immediate data refresh."""
        if not self.state.is_paused:
            self.orchestrator.force_refresh()
            self.notify("Refreshing data...")

    def action_switch_view(self, view: str) -> None:
        """Switch to a different view.

        Args:
            view: View name to switch to
        """
        if view == self._current_view:
            return

        self._current_view = view
        self.state.set_view(view)
        self.post_message(ViewSwitched(view))

        # Get the main content container
        main_content = self.query_one("#main-content", Container)

        # Remove current screen content
        for child in main_content.children:
            child.remove()

        # Import and mount new screen
        from claude_monitor.tui.screens.agents import AgentsScreen
        from claude_monitor.tui.screens.daily import DailyScreen
        from claude_monitor.tui.screens.dashboard import DashboardScreen
        from claude_monitor.tui.screens.monthly import MonthlyScreen

        screen_map = {
            "dashboard": DashboardScreen,
            "daily": DailyScreen,
            "monthly": MonthlyScreen,
            "agents": AgentsScreen,
        }

        screen_class = screen_map.get(view, DashboardScreen)
        new_screen = screen_class(id=f"{view}-screen")
        main_content.mount(new_screen)

        # Update footer hints
        self._update_footer()

        self.notify(f"Switched to {view} view")

    def action_show_help(self) -> None:
        """Show help overlay."""
        from claude_monitor.tui.screens.help import HelpScreen

        self.push_screen(HelpScreen())

    def action_show_whatif(self) -> None:
        """Show what-if calculator."""
        from claude_monitor.tui.screens.whatif import WhatIfScreen

        self.push_screen(WhatIfScreen())
