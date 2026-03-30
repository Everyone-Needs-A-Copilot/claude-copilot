"""Agent display component for Claude Monitor.

Provides UI components for displaying agent activity in --view agents mode.
"""

from datetime import datetime
from datetime import timezone as tz
from typing import List, Optional, Tuple

from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from claude_monitor.core.models import AgentActivity, AgentSnapshot
from claude_monitor.ui.layouts import HeaderManager
from claude_monitor.utils.formatting import format_number

# Health thresholds
HEALTH_LIGHT_THRESHOLD = 100_000  # Under 100K tokens
HEALTH_NORMAL_THRESHOLD = 500_000  # Under 500K tokens
HEALTH_HEAVY_THRESHOLD = 1_000_000  # Under 1M tokens
# Above 1M = Consider restart


class AgentDisplayComponent:
    """Display component for agent activity view."""

    SEPARATOR_CHAR = "-"
    SEPARATOR_LENGTH = 70
    BAR_WIDTH = 40

    def __init__(self, console: Optional[Console] = None):
        """Initialize the agent display component.

        Args:
            console: Optional Console instance for rich output
        """
        self.console = console
        self.header_manager = HeaderManager()

    def format_agent_view(
        self,
        snapshot: AgentSnapshot,
        plan: str,
        timezone_str: str,
        token_limit: int,
    ) -> RenderableType:
        """Format the agent view for display.

        Args:
            snapshot: AgentSnapshot with agent data
            plan: Current plan name
            timezone_str: Display timezone string
            token_limit: Token limit for the plan

        Returns:
            Rich renderable for display
        """
        lines: List[str] = []

        # Calculate average tokens for relative comparison
        avg_tokens = self._calculate_average_tokens(snapshot.agents)

        # Header
        lines.extend(self.header_manager.create_header(plan, timezone_str))
        lines.append("")

        # Token usage summary bar
        usage_bar = self._render_usage_bar(snapshot.usage_percentage)
        usage_text = (
            f"[bold]Token Usage:[/bold]     {usage_bar} "
            f"{snapshot.usage_percentage:5.1f}% | "
            f"{format_number(snapshot.total_tokens)} / {format_number(token_limit)}"
        )
        lines.append(usage_text)

        # Predictions section
        lines.append("")
        lines.append("[bold]Predictions:[/bold]")
        lines.append(self._format_predictions(snapshot))
        lines.append("")

        # Agent table
        lines.append(f"[table.border]{self.SEPARATOR_CHAR * self.SEPARATOR_LENGTH}[/]")
        lines.append(self._format_table_header())
        lines.append(f"[table.border]{self.SEPARATOR_CHAR * self.SEPARATOR_LENGTH}[/]")

        # Agent rows
        if snapshot.agents:
            for agent in snapshot.agents[:15]:  # Limit to 15 agents
                lines.append(self._format_agent_row(agent, avg_tokens))
        else:
            lines.append("[dim]No active agents found[/]")

        lines.append(f"[table.border]{self.SEPARATOR_CHAR * self.SEPARATOR_LENGTH}[/]")

        # Footer
        lines.append("")
        lines.append(self._format_footer(snapshot, avg_tokens))
        lines.append(self._format_status_line())

        return Text.from_markup("\n".join(lines))

    def _render_usage_bar(self, percentage: float) -> str:
        """Render a usage progress bar.

        Args:
            percentage: Usage percentage (0-100)

        Returns:
            Formatted progress bar string
        """
        filled = int(self.BAR_WIDTH * min(percentage, 100) / 100)
        empty = self.BAR_WIDTH - filled

        # Color based on percentage
        if percentage >= 80:
            color = "red"
            indicator = "[red bold]!![/]"
        elif percentage >= 50:
            color = "yellow"
            indicator = "[yellow]!![/]"
        else:
            color = "green"
            indicator = "[green]OK[/]"

        bar = f"[{color}]{'█' * filled}[/][dim]{'░' * empty}[/]"
        return f"{indicator} [{bar}]"

    def _format_predictions(self, snapshot: AgentSnapshot) -> str:
        """Format predictions line.

        Args:
            snapshot: AgentSnapshot with usage data

        Returns:
            Formatted predictions string
        """
        # Calculate rough prediction based on current usage
        now = datetime.now(tz.utc)
        reset_time = self._get_next_reset_time(now)

        return (
            f"   Reset time: [success]{reset_time.strftime('%I:%M %p')}[/] | "
            f"Active agents: [cyan]{snapshot.active_count}[/]"
        )

    def _get_next_reset_time(self, now: datetime) -> datetime:
        """Get next 5-hour block reset time.

        Args:
            now: Current datetime

        Returns:
            Next reset datetime
        """
        # 5-hour blocks: 0, 5, 10, 15, 20 hours
        current_hour = now.hour
        next_block = ((current_hour // 5) + 1) * 5
        if next_block >= 24:
            next_block = 0
            reset_day = now.day + 1
        else:
            reset_day = now.day

        return now.replace(hour=next_block % 24, minute=0, second=0, microsecond=0)

    def _format_table_header(self) -> str:
        """Format the agent table header.

        Returns:
            Formatted header string
        """
        return (
            f"[bold]{'Agent Type-ID':<22}[/] | "
            f"[bold]{'Last Action':<24}[/] | "
            f"[bold]{'vs Avg':>6}[/] | "
            f"[bold]{'Status':<15}[/]"
        )

    def _format_agent_row(self, agent: AgentActivity, avg_tokens: int) -> str:
        """Format a single agent row.

        Args:
            agent: AgentActivity to format
            avg_tokens: Average tokens across all agents for comparison

        Returns:
            Formatted row string
        """
        # Status indicator based on activity
        if agent.is_active:
            status_color = "green"
        else:
            status_color = "yellow"

        # Agent name
        name = agent.display_name[:22]

        # Truncate action to fit
        action = agent.last_action[:22]
        if len(agent.last_action) > 22:
            action += ".."

        # Calculate relative usage vs average
        relative, rel_style = self._calculate_relative_usage(agent.total_tokens, avg_tokens)

        # Calculate health status
        status, status_style = self._get_health_status(agent.total_tokens)

        return (
            f"[{status_color}]{name:<22}[/] | "
            f"{action:<24} | "
            f"[{rel_style}]{relative:>6}[/] | "
            f"[{status_style}]{status:<15}[/]"
        )

    def _calculate_relative_usage(self, tokens: int, avg_tokens: int) -> Tuple[str, str]:
        """Calculate relative usage compared to average.

        Args:
            tokens: Agent's total tokens
            avg_tokens: Average tokens across agents

        Returns:
            Tuple of (display string, style)
        """
        if avg_tokens == 0:
            return "N/A", "dim"

        ratio = tokens / avg_tokens

        if ratio < 0.5:
            return f"{ratio:.1f}x", "green"
        elif ratio < 1.5:
            return f"{ratio:.1f}x", "cyan"
        elif ratio < 3.0:
            return f"{ratio:.1f}x", "yellow"
        else:
            return f"{ratio:.1f}x", "red"

    def _get_health_status(self, tokens: int) -> Tuple[str, str]:
        """Get health status based on token count.

        Args:
            tokens: Agent's total tokens

        Returns:
            Tuple of (status string, style)
        """
        if tokens < HEALTH_LIGHT_THRESHOLD:
            return "Light", "green"
        elif tokens < HEALTH_NORMAL_THRESHOLD:
            return "Normal", "cyan"
        elif tokens < HEALTH_HEAVY_THRESHOLD:
            return "Heavy", "yellow"
        else:
            return "Consider restart", "red bold"

    def _calculate_average_tokens(self, agents: List[AgentActivity]) -> int:
        """Calculate average tokens across all agents.

        Args:
            agents: List of agents

        Returns:
            Average token count (0 if no agents)
        """
        if not agents:
            return 0
        total = sum(a.total_tokens for a in agents)
        return total // len(agents)

    def _format_footer(self, snapshot: AgentSnapshot, avg_tokens: int) -> str:
        """Format the footer with summary stats.

        Args:
            snapshot: AgentSnapshot with stats
            avg_tokens: Average tokens across agents

        Returns:
            Formatted footer string
        """
        avg_display = self._format_tokens_short(avg_tokens) if avg_tokens > 0 else "N/A"
        return (
            f"[dim]Active: {snapshot.active_count} | "
            f"Subagents: {snapshot.sidechain_count} | "
            f"Avg: {avg_display} | "
            f"Total: {self._format_tokens_short(snapshot.total_tokens)}[/]"
        )

    def _format_tokens_short(self, tokens: int) -> str:
        """Format token count in short form (K, M).

        Args:
            tokens: Token count

        Returns:
            Formatted string like "1.2M" or "452K"
        """
        if tokens >= 1_000_000:
            return f"{tokens / 1_000_000:.1f}M"
        elif tokens >= 1_000:
            return f"{tokens / 1_000:.0f}K"
        else:
            return str(tokens)

    def _format_status_line(self) -> str:
        """Format the status line with time and exit hint.

        Returns:
            Formatted status line
        """
        now = datetime.now()
        time_str = now.strftime("%I:%M:%S %p")
        return f"[dim]{time_str}[/] | [dim]Ctrl+C to exit[/]"

    def create_agent_table(self, snapshot: AgentSnapshot) -> Table:
        """Create a Rich Table for agent display.

        Args:
            snapshot: AgentSnapshot with agent data

        Returns:
            Rich Table object
        """
        table = Table(
            title="Active Agents",
            title_style="bold cyan",
            show_header=True,
            header_style="bold",
            border_style="bright_blue",
            expand=True,
        )

        table.add_column("Agent", style="cyan", width=25)
        table.add_column("Last Action", style="white", width=35)
        table.add_column("Tokens", style="yellow", justify="right", width=12)
        table.add_column("Context %", style="green", justify="right", width=10)

        for agent in snapshot.agents[:15]:
            # Status indicator
            status = "●" if agent.is_active else "○"
            name = f"{status} {agent.display_name}"

            # Context percentage color
            ctx_pct = agent.context_percentage
            if ctx_pct > 50:
                ctx_style = "red"
            elif ctx_pct > 25:
                ctx_style = "yellow"
            else:
                ctx_style = "green"

            table.add_row(
                name,
                agent.last_action[:33] + ".." if len(agent.last_action) > 35 else agent.last_action,
                format_number(agent.total_tokens),
                Text(f"{ctx_pct:.1f}%", style=ctx_style),
            )

        return table
