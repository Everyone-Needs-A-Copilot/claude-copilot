"""Data models for Claude Monitor.
Core data structures for usage tracking, session management, and token calculations.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class CostMode(Enum):
    """Cost calculation modes for token usage analysis."""

    AUTO = "auto"
    CACHED = "cached"
    CALCULATED = "calculate"


class DetectionConfidence(Enum):
    """Confidence levels for plan auto-detection."""

    HIGH = "high"  # Rate limit hit confirmed plan
    MEDIUM = "medium"  # Usage exceeded lower plan limits
    LOW = "low"  # Inferred from P90 calculation
    UNKNOWN = "unknown"  # No data or detection failed


@dataclass
class PlanDetectionResult:
    """Result of plan auto-detection."""

    detected_plan: str  # "pro", "max5", "max20"
    confidence: DetectionConfidence
    token_limit: int
    detection_method: str  # "limit_hit", "max_usage", "p90_fallback"
    evidence: List[str]  # Human-readable reasons

    # Optional context
    max_session_tokens: Optional[int] = None
    limit_hit_count: int = 0
    limit_hit_threshold: Optional[int] = None


@dataclass
class UsageEntry:
    """Individual usage record from Claude usage data."""

    timestamp: datetime
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    message_id: str = ""
    request_id: str = ""


@dataclass
class TokenCounts:
    """Token aggregation structure with computed totals."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Get total tokens across all types."""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )


@dataclass
class BurnRate:
    """Token consumption rate metrics."""

    tokens_per_minute: float
    cost_per_hour: float


@dataclass
class UsageProjection:
    """Usage projection calculations for active blocks."""

    projected_total_tokens: int
    projected_total_cost: float
    remaining_minutes: float


@dataclass
class SessionBlock:
    """Aggregated session block representing a 5-hour period."""

    id: str
    start_time: datetime
    end_time: datetime
    entries: List[UsageEntry] = field(default_factory=list)
    token_counts: TokenCounts = field(default_factory=TokenCounts)
    is_active: bool = False
    is_gap: bool = False
    burn_rate: Optional[BurnRate] = None
    actual_end_time: Optional[datetime] = None
    per_model_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    models: List[str] = field(default_factory=list)
    sent_messages_count: int = 0
    cost_usd: float = 0.0
    limit_messages: List[Dict[str, Any]] = field(default_factory=list)
    projection_data: Optional[Dict[str, Any]] = None
    burn_rate_snapshot: Optional[BurnRate] = None

    @property
    def total_tokens(self) -> int:
        """Get total tokens from token_counts."""
        return self.token_counts.total_tokens

    @property
    def total_cost(self) -> float:
        """Get total cost - alias for cost_usd."""
        return self.cost_usd

    @property
    def duration_minutes(self) -> float:
        """Get duration in minutes."""
        if self.actual_end_time:
            duration = (self.actual_end_time - self.start_time).total_seconds() / 60
        else:
            duration = (self.end_time - self.start_time).total_seconds() / 60
        return max(duration, 1.0)


@dataclass
class AgentActivity:
    """Real-time agent activity tracking for --view agents mode."""

    agent_id: str  # Hash from filename (e.g., "8d71f43a")
    session_id: str  # Parent session UUID
    agent_type: str  # Detected type: "Explore", "Plan", "QA", "Sec", "Agent"
    display_name: str  # Combined: "Explore-8d71f43a"
    is_sidechain: bool  # True for subagents

    # Token usage
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0

    # Activity tracking
    last_action: str = ""  # Summary of last activity (e.g., "Reading src/file.py")
    last_action_type: str = ""  # "tool_use", "text", "thinking"
    last_action_time: Optional[datetime] = None

    # Context usage
    context_percentage: float = 0.0  # Cumulative tokens vs plan limit

    # Metadata
    model: str = ""
    start_time: Optional[datetime] = None

    @property
    def is_active(self) -> bool:
        """Agent is active if last action was within 5 minutes."""
        if not self.last_action_time:
            return False
        now = datetime.now(timezone.utc)
        # Handle naive datetimes
        last_time = self.last_action_time
        if last_time.tzinfo is None:
            last_time = last_time.replace(tzinfo=timezone.utc)
        return (now - last_time).total_seconds() < 300


@dataclass
class AgentSnapshot:
    """Snapshot of all agents for display in --view agents mode."""

    agents: List[AgentActivity]
    total_tokens: int
    token_limit: int
    usage_percentage: float
    active_count: int
    sidechain_count: int
    snapshot_time: datetime


def normalize_model_name(model: str) -> str:
    """Normalize model name for consistent usage across the application.

    Handles various model name formats and maps them to standard keys.
    (Moved from utils/model_utils.py)

    Args:
        model: Raw model name from usage data

    Returns:
        Normalized model key

    Examples:
        >>> normalize_model_name("claude-3-opus-20240229")
        'claude-3-opus'
        >>> normalize_model_name("Claude 3.5 Sonnet")
        'claude-3-5-sonnet'
    """
    if not model:
        return ""

    model_lower = model.lower()

    if (
        "claude-opus-4-" in model_lower
        or "claude-sonnet-4-" in model_lower
        or "claude-haiku-4-" in model_lower
        or "sonnet-4-" in model_lower
        or "opus-4-" in model_lower
        or "haiku-4-" in model_lower
    ):
        return model_lower

    if "opus" in model_lower:
        if "4-" in model_lower:
            return model_lower
        return "claude-3-opus"
    if "sonnet" in model_lower:
        if "4-" in model_lower:
            return model_lower
        if "3.5" in model_lower or "3-5" in model_lower:
            return "claude-3-5-sonnet"
        return "claude-3-sonnet"
    if "haiku" in model_lower:
        if "3.5" in model_lower or "3-5" in model_lower:
            return "claude-3-5-haiku"
        return "claude-3-haiku"

    return model
