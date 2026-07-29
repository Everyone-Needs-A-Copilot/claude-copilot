"""Tests for the main TUI application."""

import pytest
from unittest.mock import MagicMock, patch
from textual.pilot import Pilot


@pytest.fixture
def app(mock_orchestrator, mock_settings):
    """Create the TUI app with mocked dependencies."""
    from claude_monitor.tui.app import ClaudeMonitorApp

    app = ClaudeMonitorApp(
        orchestrator=mock_orchestrator,
        settings=mock_settings,
    )
    return app


class TestClaudeMonitorApp:
    """Tests for ClaudeMonitorApp."""

    def test_app_creation(self, mock_orchestrator, mock_settings):
        """Test app can be created."""
        from claude_monitor.tui.app import ClaudeMonitorApp

        app = ClaudeMonitorApp(
            orchestrator=mock_orchestrator,
            settings=mock_settings,
        )
        assert app is not None
        assert app.orchestrator == mock_orchestrator
        assert app.settings == mock_settings

    def test_app_initial_state(self, app):
        """Test app initial state is correct."""
        assert app._current_view == "dashboard"
        assert app.state.is_paused is False
        assert app.state.is_loading is True

    @pytest.mark.asyncio
    async def test_app_compose(self, app):
        """Test app composes correctly."""
        async with app.run_test() as pilot:
            # Check header is present
            header = app.query_one("#app-header")
            assert header is not None

            # Check main content is present
            main_content = app.query_one("#main-content")
            assert main_content is not None

            # Check footer is present
            footer = app.query_one("#app-footer")
            assert footer is not None

            # Check dashboard screen is present initially
            dashboard = app.query_one("#dashboard-screen")
            assert dashboard is not None

    @pytest.mark.asyncio
    async def test_switch_to_daily_view(self, app, sample_monitoring_data):
        """Test switching to daily view."""
        async with app.run_test() as pilot:
            # First update state with sample data so screens have something to show
            app.state.update_from_monitoring_data(sample_monitoring_data)

            # Press 2 to switch to daily view
            await pilot.press("2")

            # Wait for the view to switch
            await pilot.pause()

            # Verify current view is now daily
            assert app._current_view == "daily"

            # Verify daily screen is mounted
            daily_screen = app.query("#daily-screen")
            assert len(daily_screen) == 1

    @pytest.mark.asyncio
    async def test_switch_to_monthly_view(self, app, sample_monitoring_data):
        """Test switching to monthly view."""
        async with app.run_test() as pilot:
            app.state.update_from_monitoring_data(sample_monitoring_data)

            await pilot.press("3")
            await pilot.pause()

            assert app._current_view == "monthly"
            monthly_screen = app.query("#monthly-screen")
            assert len(monthly_screen) == 1

    @pytest.mark.asyncio
    async def test_switch_to_agents_view(self, app, sample_monitoring_data):
        """Test switching to agents view."""
        async with app.run_test() as pilot:
            app.state.update_from_monitoring_data(sample_monitoring_data)

            await pilot.press("4")
            await pilot.pause()

            assert app._current_view == "agents"
            agents_screen = app.query("#agents-screen")
            assert len(agents_screen) == 1

    @pytest.mark.asyncio
    async def test_switch_back_to_dashboard(self, app, sample_monitoring_data):
        """Test switching back to dashboard."""
        async with app.run_test() as pilot:
            app.state.update_from_monitoring_data(sample_monitoring_data)

            # Switch to daily first
            await pilot.press("2")
            await pilot.pause()
            assert app._current_view == "daily"

            # Switch back to dashboard
            await pilot.press("1")
            await pilot.pause()
            assert app._current_view == "dashboard"

    @pytest.mark.asyncio
    async def test_pause_toggle(self, app):
        """Test pause toggle."""
        async with app.run_test() as pilot:
            assert app.state.is_paused is False

            await pilot.press("space")
            await pilot.pause()

            assert app.state.is_paused is True

            await pilot.press("space")
            await pilot.pause()

            assert app.state.is_paused is False

    @pytest.mark.asyncio
    async def test_quit_app(self, app):
        """Test app quits on q press."""
        async with app.run_test() as pilot:
            await pilot.press("q")
            # The app should be exiting after q
            # We can't easily test exit, but we can verify the action exists
            assert "q" in [b.key for b in app.BINDINGS]

    @pytest.mark.asyncio
    async def test_data_update_callback(self, app, sample_monitoring_data):
        """Test data update callback updates state."""
        async with app.run_test() as pilot:
            # Simulate data update from orchestrator
            app._process_data_update(sample_monitoring_data)
            await pilot.pause()

            # Verify state was updated
            assert app.state.is_loading is False
            assert len(app.state.blocks) == 3
            assert app.state.token_limit == 200000
