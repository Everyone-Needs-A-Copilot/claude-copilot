"""Widget modules for the TUI application."""

from typing import List

from claude_monitor.tui.widgets.agent_table import AgentDataTable
from claude_monitor.tui.widgets.burn_rate import BurnRateWidget
from claude_monitor.tui.widgets.footer import FooterWidget
from claude_monitor.tui.widgets.header import HeaderWidget
from claude_monitor.tui.widgets.model_usage import ModelUsageWidget
from claude_monitor.tui.widgets.predictions import PredictionsPanel
from claude_monitor.tui.widgets.progress_bars import CostBar, TimeBar, TokenBar
from claude_monitor.tui.widgets.session_table import SessionDataTable
from claude_monitor.tui.widgets.usage_panel import UsagePanel

__all__: List[str] = [
    "HeaderWidget",
    "FooterWidget",
    "TokenBar",
    "CostBar",
    "TimeBar",
    "UsagePanel",
    "BurnRateWidget",
    "PredictionsPanel",
    "ModelUsageWidget",
    "SessionDataTable",
    "AgentDataTable",
]
