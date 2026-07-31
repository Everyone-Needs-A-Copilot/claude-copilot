"""Tests for TUI application state."""

import pytest
from unittest.mock import MagicMock


class TestAppState:
    """Tests for AppState."""

    def test_app_state_import(self):
        """Test AppState can be imported."""
        from claude_monitor.tui.state.app_state import AppState
        assert AppState is not None

    def test_app_state_creation(self):
        """Test AppState can be created."""
        from claude_monitor.tui.state.app_state import AppState
        state = AppState()
        assert state is not None

    def test_app_state_defaults(self):
        """Test AppState has correct default values."""
        from claude_monitor.tui.state.app_state import AppState
        state = AppState()

        assert state.is_paused is False
        assert state.is_loading is True
        assert state.current_view == "dashboard"
        assert state.last_refresh is None
        assert state.blocks == []
        assert state.agents == []
        assert state.token_limit == 44000
        assert state.plan == "custom"
        assert state.timezone == "UTC"
        assert state.filter_text == ""

    def test_session_state_defaults(self):
        """Test SessionState has correct default values."""
        from claude_monitor.tui.state.app_state import AppState
        state = AppState()
        session = state.session

        assert session.tokens_used == 0
        assert session.token_limit == 44000
        assert session.cost_used == 0.0
        assert session.burn_rate == 0.0
        assert session.usage_percentage == 0.0
        assert session.elapsed_minutes == 0.0
        assert session.is_active is False

    def test_update_from_monitoring_data(self, sample_monitoring_data):
        """Test updating state from monitoring data."""
        from claude_monitor.tui.state.app_state import AppState
        state = AppState()

        state.update_from_monitoring_data(sample_monitoring_data)

        assert state.is_loading is False
        assert len(state.blocks) == 3
        assert state.token_limit == 200000
        assert state.last_refresh is not None

        # Check session is updated with active block
        assert state.session.is_active is True
        assert state.session.tokens_used == 50000
        assert state.session.cost_used == 5.00

    def test_update_when_paused(self, sample_monitoring_data):
        """Test state is not updated when paused."""
        from claude_monitor.tui.state.app_state import AppState
        state = AppState()
        state.is_paused = True

        state.update_from_monitoring_data(sample_monitoring_data)

        # Should not have updated
        assert state.is_loading is True
        assert len(state.blocks) == 0

    def test_toggle_paused(self):
        """Test pause toggle."""
        from claude_monitor.tui.state.app_state import AppState
        state = AppState()

        assert state.is_paused is False

        result = state.toggle_paused()
        assert result is True
        assert state.is_paused is True

        result = state.toggle_paused()
        assert result is False
        assert state.is_paused is False

    def test_set_view(self):
        """Test setting view."""
        from claude_monitor.tui.state.app_state import AppState
        state = AppState()

        assert state.current_view == "dashboard"

        state.set_view("daily")
        assert state.current_view == "daily"

        state.set_view("monthly")
        assert state.current_view == "monthly"

        state.set_view("agents")
        assert state.current_view == "agents"

        # Invalid view should not change
        state.set_view("invalid")
        assert state.current_view == "agents"

    def test_set_filter(self):
        """Test setting filter."""
        from claude_monitor.tui.state.app_state import AppState
        state = AppState()

        assert state.filter_text == ""

        state.set_filter("test")
        assert state.filter_text == "test"

    def test_clear_filter(self):
        """Test clearing filter."""
        from claude_monitor.tui.state.app_state import AppState
        state = AppState()

        state.filter_text = "test"
        state.clear_filter()
        assert state.filter_text == ""

    def test_no_active_block(self):
        """Test state update with no active block."""
        from claude_monitor.tui.state.app_state import AppState
        state = AppState()

        monitoring_data = {
            "data": {
                "blocks": [
                    {
                        "startTime": "2024-12-13T08:00:00Z",
                        "totalTokens": 80000,
                        "costUSD": 8.00,
                        "isActive": False,
                    }
                ]
            },
            "token_limit": 200000,
        }

        state.update_from_monitoring_data(monitoring_data)

        assert state.session.is_active is False
        assert state.is_loading is False
        assert len(state.blocks) == 1

    def test_burn_rate_dict_handling(self):
        """Test that burn_rate correctly extracts values from dict."""
        from claude_monitor.tui.state.app_state import AppState
        state = AppState()

        monitoring_data = {
            "data": {
                "blocks": [
                    {
                        "startTime": "2024-12-14T10:00:00Z",
                        "totalTokens": 50000,
                        "costUSD": 5.00,
                        "isActive": True,
                        "burnRate": {
                            "tokensPerMinute": 768522.60,
                            "costPerHour": 90.27,
                        },
                        "durationMinutes": 30,
                    }
                ]
            },
            "token_limit": 200000,
        }

        state.update_from_monitoring_data(monitoring_data)

        # burn_rate should be extracted as tokensPerMinute
        assert state.session.burn_rate == 768522.60
        # cost_per_hour should be extracted from dict
        assert state.session.cost_per_hour == 90.27
        assert state.session.is_active is True

    def test_burn_rate_float_fallback(self):
        """Test that burn_rate handles float values for backwards compat."""
        from claude_monitor.tui.state.app_state import AppState
        state = AppState()

        monitoring_data = {
            "data": {
                "blocks": [
                    {
                        "startTime": "2024-12-14T10:00:00Z",
                        "totalTokens": 50000,
                        "costUSD": 5.00,
                        "isActive": True,
                        "burnRate": 166.67,  # Float instead of dict
                        "durationMinutes": 30,
                    }
                ]
            },
            "token_limit": 200000,
        }

        state.update_from_monitoring_data(monitoring_data)

        # burn_rate should be the float value directly
        assert state.session.burn_rate == 166.67
        # cost_per_hour should be 0 when burnRate is not a dict
        assert state.session.cost_per_hour == 0.0

    def test_session_state_cost_per_hour_default(self):
        """Test SessionState has cost_per_hour field with default."""
        from claude_monitor.tui.state.app_state import AppState
        state = AppState()

        assert state.session.cost_per_hour == 0.0
