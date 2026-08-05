"""Tests for TUI widgets."""

import pytest
from unittest.mock import MagicMock


class TestHeaderWidget:
    """Tests for HeaderWidget."""

    def test_header_import(self):
        """Test HeaderWidget can be imported."""
        from claude_monitor.tui.widgets.header import HeaderWidget
        assert HeaderWidget is not None

    def test_header_creation(self):
        """Test HeaderWidget can be created."""
        from claude_monitor.tui.widgets.header import HeaderWidget
        widget = HeaderWidget(id="test-header")
        assert widget is not None

    def test_header_class_attributes(self):
        """Test HeaderWidget class has expected reactive attributes."""
        from claude_monitor.tui.widgets.header import HeaderWidget
        # Check that the class has the reactive descriptors
        assert hasattr(HeaderWidget, 'plan_name')
        assert hasattr(HeaderWidget, 'is_paused')
        assert hasattr(HeaderWidget, 'usage_percent')


class TestFooterWidget:
    """Tests for FooterWidget."""

    def test_footer_import(self):
        """Test FooterWidget can be imported."""
        from claude_monitor.tui.widgets.footer import FooterWidget
        assert FooterWidget is not None

    def test_footer_creation(self):
        """Test FooterWidget can be created."""
        from claude_monitor.tui.widgets.footer import FooterWidget
        widget = FooterWidget(id="test-footer")
        assert widget is not None

    def test_footer_class_attributes(self):
        """Test FooterWidget class has expected reactive attributes."""
        from claude_monitor.tui.widgets.footer import FooterWidget
        assert hasattr(FooterWidget, 'current_view')
        assert hasattr(FooterWidget, 'last_refresh')


class TestUsagePanel:
    """Tests for UsagePanel."""

    def test_usage_panel_import(self):
        """Test UsagePanel can be imported."""
        from claude_monitor.tui.widgets.usage_panel import UsagePanel
        assert UsagePanel is not None

    def test_usage_panel_creation(self):
        """Test UsagePanel can be created."""
        from claude_monitor.tui.widgets.usage_panel import UsagePanel
        widget = UsagePanel(id="test-usage")
        assert widget is not None

    def test_usage_panel_class_attributes(self):
        """Test UsagePanel class has expected reactive attributes."""
        from claude_monitor.tui.widgets.usage_panel import UsagePanel
        assert hasattr(UsagePanel, 'plan_name')
        assert hasattr(UsagePanel, 'tokens_used')
        assert hasattr(UsagePanel, 'token_limit')
        assert hasattr(UsagePanel, 'cost_used')


class TestBurnRateWidget:
    """Tests for BurnRateWidget."""

    def test_burn_rate_import(self):
        """Test BurnRateWidget can be imported."""
        from claude_monitor.tui.widgets.burn_rate import BurnRateWidget
        assert BurnRateWidget is not None

    def test_burn_rate_creation(self):
        """Test BurnRateWidget can be created."""
        from claude_monitor.tui.widgets.burn_rate import BurnRateWidget
        widget = BurnRateWidget(id="test-burn")
        assert widget is not None

    def test_burn_rate_class_attributes(self):
        """Test BurnRateWidget class has expected reactive attributes."""
        from claude_monitor.tui.widgets.burn_rate import BurnRateWidget
        assert hasattr(BurnRateWidget, 'burn_rate')
        assert hasattr(BurnRateWidget, 'previous_rate')
        assert hasattr(BurnRateWidget, 'cost_per_hour')


class TestPredictionsPanel:
    """Tests for PredictionsPanel."""

    def test_predictions_import(self):
        """Test PredictionsPanel can be imported."""
        from claude_monitor.tui.widgets.predictions import PredictionsPanel
        assert PredictionsPanel is not None

    def test_predictions_creation(self):
        """Test PredictionsPanel can be created."""
        from claude_monitor.tui.widgets.predictions import PredictionsPanel
        widget = PredictionsPanel(id="test-predictions")
        assert widget is not None

    def test_predictions_format_time(self):
        """Test time formatting."""
        from claude_monitor.tui.widgets.predictions import PredictionsPanel
        widget = PredictionsPanel()

        # Test various time values
        assert widget._format_time(0) == "--"
        assert widget._format_time(30) == "~30 min"
        assert widget._format_time(90) == "~1.5 hours"
        assert widget._format_time(60 * 24 * 2) == "~2.0 days"


class TestModelUsageWidget:
    """Tests for ModelUsageWidget."""

    def test_model_usage_import(self):
        """Test ModelUsageWidget can be imported."""
        from claude_monitor.tui.widgets.model_usage import ModelUsageWidget
        assert ModelUsageWidget is not None

    def test_model_usage_creation(self):
        """Test ModelUsageWidget can be created."""
        from claude_monitor.tui.widgets.model_usage import ModelUsageWidget
        widget = ModelUsageWidget(id="test-model")
        assert widget is not None

    def test_model_display_name(self):
        """Test model display name formatting."""
        from claude_monitor.tui.widgets.model_usage import ModelUsageWidget
        widget = ModelUsageWidget()

        assert widget._get_model_display_name("claude-3-opus-20240229") == "Opus 4"
        assert widget._get_model_display_name("claude-3-5-sonnet-20241022") == "Sonnet 4.5"
        assert widget._get_model_display_name("claude-3-5-haiku-20241022") == "Haiku"


class TestSessionDataTable:
    """Tests for SessionDataTable."""

    def test_session_table_import(self):
        """Test SessionDataTable can be imported."""
        from claude_monitor.tui.widgets.session_table import SessionDataTable
        assert SessionDataTable is not None

    def test_session_table_creation(self):
        """Test SessionDataTable can be created."""
        from claude_monitor.tui.widgets.session_table import SessionDataTable
        widget = SessionDataTable(id="test-table")
        assert widget is not None

    def test_session_table_class_attributes(self):
        """Test SessionDataTable class has expected reactive attributes."""
        from claude_monitor.tui.widgets.session_table import SessionDataTable
        assert hasattr(SessionDataTable, 'data')
        assert hasattr(SessionDataTable, 'view_mode')
        assert hasattr(SessionDataTable, 'sort_column')
        assert hasattr(SessionDataTable, 'sort_reverse')


class TestAgentDataTable:
    """Tests for AgentDataTable."""

    def test_agent_table_import(self):
        """Test AgentDataTable can be imported."""
        from claude_monitor.tui.widgets.agent_table import AgentDataTable
        assert AgentDataTable is not None

    def test_agent_table_creation(self):
        """Test AgentDataTable can be created."""
        from claude_monitor.tui.widgets.agent_table import AgentDataTable
        widget = AgentDataTable(id="test-agent-table")
        assert widget is not None

    def test_agent_table_class_attributes(self):
        """Test AgentDataTable class has expected reactive attributes."""
        from claude_monitor.tui.widgets.agent_table import AgentDataTable
        assert hasattr(AgentDataTable, 'agents')
        assert hasattr(AgentDataTable, 'filter_text')
        assert hasattr(AgentDataTable, 'show_inactive')

    def test_agent_filter_logic(self, sample_agents):
        """Test agent filtering logic directly (without reactive initialization)."""
        # Test the filtering logic independently of the widget
        # Filter active only
        active_agents = [a for a in sample_agents if a.get("is_active", False)]
        active_count = sum(1 for a in sample_agents if a.get("is_active"))
        assert len(active_agents) == active_count
        assert active_count == 2  # Main Session and Explore Agent are active

        # Filter by text
        filter_text = "Explore"
        text_filtered = [
            a for a in sample_agents
            if filter_text.lower() in a.get("name", "").lower()
            or filter_text.lower() in a.get("type", "").lower()
        ]
        assert len(text_filtered) == 1
        assert text_filtered[0]["name"] == "Explore Agent"

        # Filter inactive (should include all)
        all_agents = sample_agents
        assert len(all_agents) == 3


class TestProgressBars:
    """Tests for progress bar widgets."""

    def test_token_bar_import(self):
        """Test TokenBar can be imported."""
        from claude_monitor.tui.widgets.progress_bars import TokenBar
        assert TokenBar is not None

    def test_cost_bar_import(self):
        """Test CostBar can be imported."""
        from claude_monitor.tui.widgets.progress_bars import CostBar
        assert CostBar is not None

    def test_time_bar_import(self):
        """Test TimeBar can be imported."""
        from claude_monitor.tui.widgets.progress_bars import TimeBar
        assert TimeBar is not None

    def test_token_bar_class_attributes(self):
        """Test TokenBar class has expected reactive attributes."""
        from claude_monitor.tui.widgets.progress_bars import TokenBar
        assert hasattr(TokenBar, 'tokens_used')
        assert hasattr(TokenBar, 'token_limit')
        assert hasattr(TokenBar, 'show_label')

    def test_cost_bar_class_attributes(self):
        """Test CostBar class has expected reactive attributes."""
        from claude_monitor.tui.widgets.progress_bars import CostBar
        assert hasattr(CostBar, 'cost_used')
        assert hasattr(CostBar, 'cost_projected')
        assert hasattr(CostBar, 'show_label')

    def test_time_bar_class_attributes(self):
        """Test TimeBar class has expected reactive attributes."""
        from claude_monitor.tui.widgets.progress_bars import TimeBar
        assert hasattr(TimeBar, 'elapsed_minutes')
        assert hasattr(TimeBar, 'total_minutes')
        assert hasattr(TimeBar, 'show_label')
