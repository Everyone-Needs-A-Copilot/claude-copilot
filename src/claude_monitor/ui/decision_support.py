"""Decision support components for Claude Monitor.

Provides Tier 1 dashboard components for at-a-glance session health
and work capacity information.
"""

from dataclasses import dataclass
from typing import List, Optional

from claude_monitor.terminal.themes import (
    SESSION_HEALTH_STATUS,
    SESSION_RECOMMENDATIONS,
    get_progress_bar_style,
    get_session_health_status,
)


@dataclass
class WorkCapacity:
    """Work capacity estimate for the current session."""

    minutes_remaining: float
    tokens_remaining: int
    limiting_factor: str  # "tokens", "time", or "cost"
    description: str

    @property
    def hours(self) -> int:
        """Get hours component of remaining time."""
        return int(self.minutes_remaining // 60)

    @property
    def mins(self) -> int:
        """Get minutes component of remaining time."""
        return int(self.minutes_remaining % 60)

    def format_time(self) -> str:
        """Format remaining time as human-readable string."""
        if self.hours > 0:
            return f"~{self.hours}h {self.mins}m"
        elif self.mins > 0:
            return f"~{self.mins}m"
        else:
            return "<1m"


def calculate_work_capacity(
    tokens_left: int,
    burn_rate: float,
    time_to_reset_minutes: float,
    cost_remaining: Optional[float] = None,
    cost_per_minute: Optional[float] = None,
) -> WorkCapacity:
    """Calculate remaining work capacity in human terms.

    Args:
        tokens_left: Remaining tokens in the session.
        burn_rate: Current token burn rate (tokens/min).
        time_to_reset_minutes: Minutes until session reset.
        cost_remaining: Optional remaining cost budget.
        cost_per_minute: Optional current cost rate.

    Returns:
        WorkCapacity object with time estimate and description.
    """
    # Calculate time until tokens run out
    if burn_rate > 0:
        minutes_until_tokens_gone = tokens_left / burn_rate
    else:
        minutes_until_tokens_gone = float("inf")

    # Calculate time until cost runs out (if applicable)
    if cost_remaining is not None and cost_per_minute is not None and cost_per_minute > 0:
        minutes_until_cost_gone = cost_remaining / cost_per_minute
    else:
        minutes_until_cost_gone = float("inf")

    # Find the limiting factor
    limiting_factors = [
        ("tokens", minutes_until_tokens_gone),
        ("time", time_to_reset_minutes),
        ("cost", minutes_until_cost_gone),
    ]

    limiting_factor, capacity_minutes = min(limiting_factors, key=lambda x: x[1])

    # Generate description based on capacity
    if capacity_minutes > 180:  # > 3 hours
        description = "Plenty of capacity for complex work"
    elif capacity_minutes > 120:  # 2-3 hours
        description = "Good capacity for substantial tasks"
    elif capacity_minutes > 60:  # 1-2 hours
        description = "Moderate capacity remaining"
    elif capacity_minutes > 30:  # 30-60 mins
        description = "Limited capacity - wrap up soon"
    elif capacity_minutes > 10:  # 10-30 mins
        description = "Low capacity - finish current task"
    else:
        description = "Minimal capacity - finish immediately"

    return WorkCapacity(
        minutes_remaining=capacity_minutes,
        tokens_remaining=tokens_left,
        limiting_factor=limiting_factor,
        description=description,
    )


def format_session_health_header(
    usage_pct: float,
    time_remaining_minutes: float,
    work_capacity: WorkCapacity,
) -> List[str]:
    """Format the session health header section (Tier 1).

    Args:
        usage_pct: Current usage percentage.
        time_remaining_minutes: Minutes until reset.
        work_capacity: Calculated work capacity.

    Returns:
        List of formatted lines for the header.
    """
    status_key = get_session_health_status(usage_pct, time_remaining_minutes)
    status = SESSION_HEALTH_STATUS[status_key]

    lines = []

    # Status line with emoji and message
    lines.append(
        f"[{status['title_style']}]Status: {status['emoji']} {status['label']}[/] - "
        f"{status['message']}"
    )

    # Work capacity line
    lines.append(
        f"[value]Work Capacity:[/] [{status['border_style']}]{work_capacity.format_time()}[/] "
        f"[dim]({work_capacity.description})[/]"
    )

    return lines


def format_metric_progress_bar(
    label: str,
    emoji: str,
    percentage: float,
    used: float,
    limit: float,
    is_currency: bool = False,
    bar_width: int = 40,
) -> str:
    """Format a single metric with progress bar.

    Args:
        label: Metric label (e.g., "Token Usage").
        emoji: Emoji prefix.
        percentage: Usage percentage (0-100+).
        used: Amount used.
        limit: Total limit.
        is_currency: Whether to format as currency.
        bar_width: Width of the progress bar.

    Returns:
        Formatted progress bar line.
    """
    style_info = get_progress_bar_style(percentage)

    # Calculate filled segments
    capped_pct = min(percentage, 100.0)
    filled = int(bar_width * capped_pct / 100)
    empty = bar_width - filled

    # Build the bar
    filled_part = f"[{style_info['filled_style']}]{'█' * filled}[/]"
    empty_part = f"[table.border]{'░' * empty}[/]"
    bar = f"{filled_part}{empty_part}"

    # Format value string
    if is_currency:
        value_str = f"${used:.2f} / ${limit:.2f}"
    else:
        if limit >= 1000:
            value_str = f"{used:,.0f} / {limit:,.0f}"
        else:
            value_str = f"{int(used)} / {int(limit)}"

    return (
        f"{emoji} [value]{label}[/]".ljust(22)
        + f" {style_info['emoji']} \\[{bar}] "
        + f"{percentage:5.1f}%   {value_str}"
    )


def format_time_bar(
    elapsed_minutes: float,
    total_minutes: float,
    bar_width: int = 40,
) -> str:
    """Format time remaining progress bar.

    Args:
        elapsed_minutes: Minutes elapsed in session.
        total_minutes: Total session duration.
        bar_width: Width of the progress bar.

    Returns:
        Formatted time progress bar line.
    """
    if total_minutes <= 0:
        percentage = 0.0
    else:
        percentage = min(100, (elapsed_minutes / total_minutes) * 100)

    remaining_minutes = max(0, total_minutes - elapsed_minutes)
    hours = int(remaining_minutes // 60)
    mins = int(remaining_minutes % 60)

    # Time bar uses inverted colors (more time = better)
    if remaining_minutes > 120:
        filled_style = "success"
        emoji = "🟢"
    elif remaining_minutes > 30:
        filled_style = "warning"
        emoji = "🟡"
    else:
        filled_style = "error"
        emoji = "🔴"

    filled = int(bar_width * (100 - percentage) / 100)
    empty = bar_width - filled

    bar = f"[{filled_style}]{'█' * filled}[/][table.border]{'░' * empty}[/]"

    time_str = f"{hours}h {mins}m" if hours > 0 else f"{mins}m"

    return f"⏱️  [value]Time to Reset[/]    {emoji} \\[{bar}] {time_str} remaining"


def format_recommendation(
    usage_pct: float,
    time_remaining_minutes: float,
) -> str:
    """Format the recommendation line.

    Args:
        usage_pct: Current usage percentage.
        time_remaining_minutes: Minutes until reset.

    Returns:
        Formatted recommendation line.
    """
    status_key = get_session_health_status(usage_pct, time_remaining_minutes)
    recommendation = SESSION_RECOMMENDATIONS[status_key]

    return f"[info]💡 RECOMMENDATION:[/] {recommendation}"


def format_decision_support_panel(
    tokens_used: int,
    token_limit: int,
    session_cost: float,
    cost_limit: float,
    sent_messages: int,
    messages_limit: int,
    elapsed_minutes: float,
    total_minutes: float,
    burn_rate: float,
    cost_per_minute: float = 0.0,
) -> List[str]:
    """Format the complete Tier 1 decision support panel.

    Args:
        tokens_used: Tokens consumed in session.
        token_limit: Token limit for the plan.
        session_cost: Current session cost.
        cost_limit: Cost limit for the plan.
        sent_messages: Messages sent in session.
        messages_limit: Message limit for the plan.
        elapsed_minutes: Minutes elapsed in session.
        total_minutes: Total session duration.
        burn_rate: Current burn rate (tokens/min).
        cost_per_minute: Current cost rate.

    Returns:
        List of formatted lines for the panel.
    """
    # Calculate percentages
    token_pct = (tokens_used / token_limit * 100) if token_limit > 0 else 0
    cost_pct = (session_cost / cost_limit * 100) if cost_limit > 0 else 0
    messages_pct = (sent_messages / messages_limit * 100) if messages_limit > 0 else 0

    # Calculate work capacity
    tokens_left = max(0, token_limit - tokens_used)
    cost_remaining = max(0, cost_limit - session_cost)
    time_remaining = max(0, total_minutes - elapsed_minutes)

    work_capacity = calculate_work_capacity(
        tokens_left=tokens_left,
        burn_rate=burn_rate,
        time_to_reset_minutes=time_remaining,
        cost_remaining=cost_remaining,
        cost_per_minute=cost_per_minute,
    )

    # Build the panel content
    lines = []

    # Session health header
    lines.extend(
        format_session_health_header(
            usage_pct=max(token_pct, cost_pct),  # Use highest usage
            time_remaining_minutes=time_remaining,
            work_capacity=work_capacity,
        )
    )
    lines.append("")

    # Progress bars
    lines.append(
        format_metric_progress_bar(
            label="Token Usage",
            emoji="📊",
            percentage=token_pct,
            used=tokens_used,
            limit=token_limit,
        )
    )

    lines.append(
        format_metric_progress_bar(
            label="Cost Usage",
            emoji="💰",
            percentage=cost_pct,
            used=session_cost,
            limit=cost_limit,
            is_currency=True,
        )
    )

    lines.append(
        format_metric_progress_bar(
            label="Messages",
            emoji="📨",
            percentage=messages_pct,
            used=sent_messages,
            limit=messages_limit,
        )
    )

    # Time bar
    lines.append(format_time_bar(elapsed_minutes, total_minutes))

    lines.append("")

    # Recommendation
    lines.append(format_recommendation(max(token_pct, cost_pct), time_remaining))

    return lines


__all__ = [
    "WorkCapacity",
    "calculate_work_capacity",
    "format_session_health_header",
    "format_metric_progress_bar",
    "format_time_bar",
    "format_recommendation",
    "format_decision_support_panel",
]
