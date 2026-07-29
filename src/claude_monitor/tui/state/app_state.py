"""Centralized application state for the TUI."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class SessionState:
    """Current active session state."""

    tokens_used: int = 0
    token_limit: int = 44_000
    cost_used: float = 0.0
    burn_rate: float = 0.0  # tokens per minute
    cost_per_hour: float = 0.0  # cost per hour
    usage_percentage: float = 0.0
    elapsed_minutes: float = 0.0
    reset_time: Optional[datetime] = None
    per_model_stats: Dict[str, Any] = field(default_factory=dict)
    is_active: bool = False
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


@dataclass
class AppState:
    """Central application state for the TUI.

    This dataclass holds all state needed by the TUI, updated from
    the monitoring orchestrator via callbacks.
    """

    # UI state
    is_paused: bool = False
    is_loading: bool = True
    current_view: str = "dashboard"
    last_refresh: Optional[datetime] = None

    # Session data
    session: SessionState = field(default_factory=SessionState)

    # Historical block data
    blocks: List[Dict[str, Any]] = field(default_factory=list)

    # Agent data
    agents: List[Dict[str, Any]] = field(default_factory=list)

    # Token limit (from orchestrator)
    token_limit: int = 44_000

    # Plan info
    plan: str = "custom"
    timezone: str = "UTC"

    # Filter state
    filter_text: str = ""

    def update_from_monitoring_data(self, monitoring_data: Dict[str, Any]) -> None:
        """Update state from orchestrator monitoring data.

        Args:
            monitoring_data: Data dict from orchestrator callback
        """
        if self.is_paused:
            return

        data = monitoring_data.get("data", {})
        blocks = data.get("blocks", [])

        # Update token limit
        self.token_limit = monitoring_data.get("token_limit", self.token_limit)

        # Update plan and timezone from args if available
        args = monitoring_data.get("args")
        if args:
            self.plan = getattr(args, "plan", self.plan)
            self.timezone = getattr(args, "timezone", self.timezone)

        # Find and update active session
        active_block = next((b for b in blocks if b.get("isActive")), None)

        if active_block:
            self.session.is_active = True
            self.session.tokens_used = active_block.get("totalTokens", 0)
            self.session.token_limit = self.token_limit
            self.session.cost_used = active_block.get("costUSD", 0.0)

            # Handle burn_rate which can be a dict or float
            burn_rate_data = active_block.get("burnRate", 0.0)
            if isinstance(burn_rate_data, dict):
                self.session.burn_rate = burn_rate_data.get("tokensPerMinute", 0.0)
                self.session.cost_per_hour = burn_rate_data.get("costPerHour", 0.0)
            else:
                self.session.burn_rate = burn_rate_data
                self.session.cost_per_hour = 0.0

            # Calculate usage percentage
            if self.token_limit > 0:
                self.session.usage_percentage = (
                    self.session.tokens_used / self.token_limit
                ) * 100
            else:
                self.session.usage_percentage = 0.0

            # Get elapsed time
            self.session.elapsed_minutes = active_block.get("durationMinutes", 0.0)

            # Get per-model stats
            self.session.per_model_stats = active_block.get("perModelStats", {})
        else:
            self.session.is_active = False

        # Store all blocks
        self.blocks = blocks

        # Update refresh time
        self.last_refresh = datetime.now()
        self.is_loading = False

    def toggle_paused(self) -> bool:
        """Toggle pause state.

        Returns:
            New paused state
        """
        self.is_paused = not self.is_paused
        return self.is_paused

    def set_view(self, view: str) -> None:
        """Set the current view.

        Args:
            view: View name (dashboard, daily, monthly, agents)
        """
        valid_views = ["dashboard", "daily", "monthly", "agents"]
        if view in valid_views:
            self.current_view = view

    def set_filter(self, filter_text: str) -> None:
        """Set the filter text.

        Args:
            filter_text: Filter string
        """
        self.filter_text = filter_text

    def clear_filter(self) -> None:
        """Clear the filter text."""
        self.filter_text = ""
