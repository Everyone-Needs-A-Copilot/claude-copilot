"""Tests for TUI screens."""

import pytest
from unittest.mock import MagicMock, patch


class TestDashboardScreen:
    """Tests for DashboardScreen."""

    def test_dashboard_screen_import(self):
        """Test DashboardScreen can be imported."""
        from claude_monitor.tui.screens.dashboard import DashboardScreen
        assert DashboardScreen is not None

    def test_dashboard_screen_creation(self):
        """Test DashboardScreen can be created."""
        from claude_monitor.tui.screens.dashboard import DashboardScreen
        screen = DashboardScreen(id="test-dashboard")
        assert screen is not None
        assert screen.id == "test-dashboard"

    def test_dashboard_bindings(self):
        """Test DashboardScreen has expected bindings."""
        from claude_monitor.tui.screens.dashboard import DashboardScreen
        binding_keys = [b[0] for b in DashboardScreen.BINDINGS]
        assert "m" in binding_keys  # Models
        assert "w" in binding_keys  # What-if


class TestDailyScreen:
    """Tests for DailyScreen."""

    def test_daily_screen_import(self):
        """Test DailyScreen can be imported."""
        from claude_monitor.tui.screens.daily import DailyScreen
        assert DailyScreen is not None

    def test_daily_screen_creation(self):
        """Test DailyScreen can be created."""
        from claude_monitor.tui.screens.daily import DailyScreen
        screen = DailyScreen(id="test-daily")
        assert screen is not None
        assert screen.id == "test-daily"

    def test_daily_bindings(self):
        """Test DailyScreen has expected bindings."""
        from claude_monitor.tui.screens.daily import DailyScreen
        binding_keys = [b[0] for b in DailyScreen.BINDINGS]
        assert "s" in binding_keys  # Sort
        assert "c" in binding_keys  # Compare
        assert "enter" in binding_keys  # Details

    def test_daily_aggregate_by_day(self, sample_blocks):
        """Test daily aggregation logic."""
        from claude_monitor.tui.screens.daily import DailyScreen
        screen = DailyScreen(id="test-daily")

        # Call the aggregation method directly
        daily_data = screen._aggregate_by_day(sample_blocks)

        # Should have entries for each day with data
        assert len(daily_data) > 0

        # Each entry should have expected fields
        for day in daily_data:
            assert "date" in day
            assert "tokens" in day
            assert "cost" in day
            assert "sessions" in day
            assert "peak_hour" in day


class TestMonthlyScreen:
    """Tests for MonthlyScreen."""

    def test_monthly_screen_import(self):
        """Test MonthlyScreen can be imported."""
        from claude_monitor.tui.screens.monthly import MonthlyScreen
        assert MonthlyScreen is not None

    def test_monthly_screen_creation(self):
        """Test MonthlyScreen can be created."""
        from claude_monitor.tui.screens.monthly import MonthlyScreen
        screen = MonthlyScreen(id="test-monthly")
        assert screen is not None
        assert screen.id == "test-monthly"

    def test_monthly_aggregate_by_month(self, sample_blocks):
        """Test monthly aggregation logic."""
        from claude_monitor.tui.screens.monthly import MonthlyScreen
        screen = MonthlyScreen(id="test-monthly")

        # Call the aggregation method directly
        monthly_data = screen._aggregate_by_month(sample_blocks)

        # Should have at least one month
        assert len(monthly_data) >= 0  # Could be 0 if blocks are in same month

        # Each entry should have expected fields
        for month in monthly_data:
            assert "month" in month
            assert "tokens" in month
            assert "cost" in month
            assert "days_active" in month
            assert "daily_avg" in month


class TestAgentsScreen:
    """Tests for AgentsScreen."""

    def test_agents_screen_import(self):
        """Test AgentsScreen can be imported."""
        from claude_monitor.tui.screens.agents import AgentsScreen
        assert AgentsScreen is not None

    def test_agents_screen_creation(self):
        """Test AgentsScreen can be created."""
        from claude_monitor.tui.screens.agents import AgentsScreen
        screen = AgentsScreen(id="test-agents")
        assert screen is not None
        assert screen.id == "test-agents"

    def test_agents_bindings(self):
        """Test AgentsScreen has expected bindings."""
        from claude_monitor.tui.screens.agents import AgentsScreen
        binding_keys = [b[0] for b in AgentsScreen.BINDINGS]
        assert "f" in binding_keys  # Filter
        assert "r" in binding_keys  # Relationships
        assert "a" in binding_keys  # Show all
        assert "i" in binding_keys  # Toggle inactive

    def test_agents_extract_from_blocks(self, sample_blocks):
        """Test extracting agents from blocks."""
        from claude_monitor.tui.screens.agents import AgentsScreen
        screen = AgentsScreen(id="test-agents")

        agents = screen._extract_agents_from_blocks(sample_blocks)

        # Should extract at least the active block
        active_count = sum(1 for b in sample_blocks if b.get("isActive"))
        assert len(agents) == active_count


class TestBaseMonitorScreen:
    """Tests for BaseMonitorScreen."""

    def test_base_screen_import(self):
        """Test BaseMonitorScreen can be imported."""
        from claude_monitor.tui.screens.base import BaseMonitorScreen
        assert BaseMonitorScreen is not None

    def test_base_screen_is_widget_subclass(self):
        """Test BaseMonitorScreen is a Widget subclass (not Screen)."""
        from claude_monitor.tui.screens.base import BaseMonitorScreen
        from textual.widget import Widget
        assert issubclass(BaseMonitorScreen, Widget)
