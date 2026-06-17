"""Agent analyzer for Claude Monitor.

Creates snapshots of agent activity for display in --view agents mode.
"""

import logging
from datetime import datetime
from datetime import timezone as tz
from typing import List

from claude_monitor.core.models import AgentActivity, AgentSnapshot

logger = logging.getLogger(__name__)


class AgentAnalyzer:
    """Analyzes and groups agent activities for display."""

    def __init__(self, token_limit: int):
        """Initialize analyzer with token limit for context percentage calculation.

        Args:
            token_limit: Maximum token limit for the current plan
        """
        self.token_limit = token_limit

    def create_snapshot(
        self,
        agents: List[AgentActivity],
        include_inactive: bool = False,
    ) -> AgentSnapshot:
        """Create a display snapshot from agent activities.

        Args:
            agents: List of AgentActivity objects
            include_inactive: Whether to include inactive agents (no activity in 5 min)

        Returns:
            AgentSnapshot with aggregated data for display
        """
        # Filter inactive agents if requested
        if not include_inactive:
            agents = [a for a in agents if a.is_active]

        # Sort by last action time (most recent first)
        agents.sort(
            key=lambda a: a.last_action_time or datetime.min.replace(tzinfo=tz.utc),
            reverse=True,
        )

        # Calculate totals
        total_tokens = sum(a.total_tokens for a in agents)
        usage_percentage = (
            (total_tokens / self.token_limit * 100) if self.token_limit > 0 else 0
        )

        # Calculate individual context percentages
        for agent in agents:
            agent.context_percentage = (
                (agent.total_tokens / self.token_limit * 100)
                if self.token_limit > 0
                else 0
            )

        # Count active and sidechain agents
        active_count = len([a for a in agents if a.is_active])
        sidechain_count = len([a for a in agents if a.is_sidechain])

        return AgentSnapshot(
            agents=agents,
            total_tokens=total_tokens,
            token_limit=self.token_limit,
            usage_percentage=usage_percentage,
            active_count=active_count,
            sidechain_count=sidechain_count,
            snapshot_time=datetime.now(tz.utc),
        )

    def filter_recent(
        self, agents: List[AgentActivity], max_agents: int = 15
    ) -> List[AgentActivity]:
        """Filter to most recent agents for display.

        Args:
            agents: List of AgentActivity objects
            max_agents: Maximum number of agents to return

        Returns:
            Filtered list of most recent agents
        """
        # Already sorted by last_action_time in create_snapshot
        return agents[:max_agents]
