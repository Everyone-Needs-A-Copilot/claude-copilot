"""Agent data reader for Claude Monitor.

Reads and parses agent-*.jsonl files to extract agent activity information
for the --view agents mode.
"""

import json
import logging
import re
from datetime import datetime, timedelta
from datetime import timezone as tz
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from claude_monitor.core.data_processors import TimestampProcessor
from claude_monitor.core.models import AgentActivity
from claude_monitor.utils.time_utils import TimezoneHandler

logger = logging.getLogger(__name__)

# Agent type detection keywords - check assistant's first message
AGENT_TYPE_KEYWORDS: Dict[str, List[str]] = {
    "Explore": ["explore", "search", "find", "read-only", "investigation", "codebase"],
    "Plan": ["plan", "design", "architect", "implementation plan", "strategy"],
    "QA": ["test", "quality", "verification", "coverage", "pytest", "unit test"],
    "Sec": ["security", "vulnerability", "audit", "threat", "owasp"],
    "Doc": ["documentation", "readme", "docs", "document"],
    "Code": ["implement", "write code", "coding", "feature"],
}

# Tool name to human-readable action formatters
TOOL_FORMATTERS: Dict[str, callable] = {
    "Read": lambda i: f"Reading {_truncate_path(i.get('file_path', 'file'))}",
    "Write": lambda i: f"Writing {_truncate_path(i.get('file_path', 'file'))}",
    "Edit": lambda i: f"Editing {_truncate_path(i.get('file_path', 'file'))}",
    "Bash": lambda i: f"Running: {_truncate_cmd(i.get('command', 'command'))}",
    "Glob": lambda i: f"Searching: {i.get('pattern', 'files')[:20]}",
    "Grep": lambda i: f"Grep: {i.get('pattern', 'pattern')[:20]}",
    "WebFetch": lambda i: f"Fetching: {_truncate_url(i.get('url', 'url'))}",
    "WebSearch": lambda i: f"Searching: {i.get('query', 'query')[:20]}",
    "Task": lambda i: "Spawning agent",
    "TodoWrite": lambda i: "Updating todos",
    "AskUserQuestion": lambda i: "Asking user",
}


def load_agent_activities(
    data_path: Optional[str] = None,
    hours_back: int = 5,
) -> List[AgentActivity]:
    """Load agent activities from agent-*.jsonl files.

    Args:
        data_path: Path to Claude data directory (defaults to ~/.claude/projects)
        hours_back: Only include agents active in last N hours

    Returns:
        List of AgentActivity objects for active agents
    """
    data_path = Path(data_path if data_path else "~/.claude/projects").expanduser()
    cutoff_time = datetime.now(tz.utc) - timedelta(hours=hours_back)

    agent_files = _find_agent_files(data_path, cutoff_time)
    if not agent_files:
        logger.debug("No agent files found in %s", data_path)
        return []

    activities: List[AgentActivity] = []
    for file_path in agent_files:
        activity = _parse_agent_file(file_path, cutoff_time)
        if activity:
            activities.append(activity)

    # Sort by last action time (most recent first)
    activities.sort(
        key=lambda a: a.last_action_time or datetime.min.replace(tzinfo=tz.utc),
        reverse=True,
    )

    logger.info(f"Found {len(activities)} active agents from {len(agent_files)} files")
    return activities


def _find_agent_files(data_path: Path, cutoff_time: datetime) -> List[Path]:
    """Find all agent-*.jsonl files modified after cutoff time."""
    if not data_path.exists():
        logger.warning("Data path does not exist: %s", data_path)
        return []

    agent_files: List[Path] = []
    for file_path in data_path.rglob("agent-*.jsonl"):
        # Check file modification time for quick filtering
        try:
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=tz.utc)
            if mtime >= cutoff_time:
                agent_files.append(file_path)
        except OSError:
            continue

    return agent_files


def _parse_agent_file(file_path: Path, cutoff_time: datetime) -> Optional[AgentActivity]:
    """Parse a single agent JSONL file into AgentActivity."""
    try:
        entries = _load_jsonl_entries(file_path)
        if not entries:
            return None

        # Filter entries to those after cutoff
        timezone_handler = TimezoneHandler()
        processor = TimestampProcessor(timezone_handler)

        recent_entries = []
        for entry in entries:
            ts = processor.parse_timestamp(entry.get("timestamp", ""))
            if ts and ts >= cutoff_time:
                recent_entries.append(entry)

        if not recent_entries:
            return None

        # Extract agent ID from filename
        agent_id = _extract_agent_id(file_path)
        if not agent_id:
            return None

        # Get session ID and sidechain status from first entry
        first_entry = entries[0]
        session_id = first_entry.get("sessionId", "")
        is_sidechain = first_entry.get("isSidechain", False)

        # Detect agent type from content
        agent_type = _detect_agent_type(entries)
        display_name = f"{agent_type}-{agent_id[:7]}"

        # Sum token usage
        tokens = _sum_agent_tokens(entries)

        # Extract last action
        last_action, last_action_type, last_action_time = _extract_last_action(
            recent_entries, processor
        )

        # Get model from most recent entry with message
        model = ""
        for entry in reversed(entries):
            msg = entry.get("message", {})
            if isinstance(msg, dict) and msg.get("model"):
                model = msg["model"]
                break

        # Get start time from first entry
        start_time = processor.parse_timestamp(first_entry.get("timestamp", ""))

        return AgentActivity(
            agent_id=agent_id,
            session_id=session_id,
            agent_type=agent_type,
            display_name=display_name,
            is_sidechain=is_sidechain,
            input_tokens=tokens.get("input_tokens", 0),
            output_tokens=tokens.get("output_tokens", 0),
            cache_creation_tokens=tokens.get("cache_creation_tokens", 0),
            cache_read_tokens=tokens.get("cache_read_tokens", 0),
            total_tokens=tokens.get("total_tokens", 0),
            last_action=last_action,
            last_action_type=last_action_type,
            last_action_time=last_action_time,
            model=model,
            start_time=start_time,
        )

    except Exception as e:
        logger.warning(f"Failed to parse agent file {file_path}: {e}")
        return None


def _load_jsonl_entries(file_path: Path) -> List[Dict[str, Any]]:
    """Load all entries from a JSONL file."""
    entries: List[Dict[str, Any]] = []
    try:
        with open(file_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.debug(f"Error reading {file_path}: {e}")
    return entries


def _extract_agent_id(file_path: Path) -> Optional[str]:
    """Extract agent ID from filename like 'agent-8d71f43a.jsonl'."""
    match = re.match(r"agent-([a-f0-9]+)\.jsonl", file_path.name)
    return match.group(1) if match else None


def _detect_agent_type(entries: List[Dict[str, Any]]) -> str:
    """Detect agent type from entry content.

    Priority 1: Check first assistant message for keywords
    Priority 2: Analyze tool usage patterns
    Fallback: Return "Agent"
    """
    # Priority 1: Check text content for keywords
    text_content = _extract_all_text(entries[:5])  # Check first few entries
    text_lower = text_content.lower()

    for agent_type, keywords in AGENT_TYPE_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return agent_type

    # Priority 2: Analyze tool usage patterns
    tool_counts = _count_tool_usage(entries)
    if tool_counts:
        read_count = tool_counts.get("Read", 0) + tool_counts.get("Glob", 0) + tool_counts.get("Grep", 0)
        write_count = tool_counts.get("Write", 0) + tool_counts.get("Edit", 0)

        if read_count > write_count * 2:
            return "Explore"
        if tool_counts.get("TodoWrite", 0) > 0 or "plan" in text_lower:
            return "Plan"

    return "Agent"


def _extract_all_text(entries: List[Dict[str, Any]]) -> str:
    """Extract all text content from entries."""
    texts: List[str] = []
    for entry in entries:
        message = entry.get("message", {})
        if not isinstance(message, dict):
            continue
        content = message.get("content", [])
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        texts.append(item.get("text", ""))
                elif isinstance(item, str):
                    texts.append(item)
    return " ".join(texts)


def _count_tool_usage(entries: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count tool usage across entries."""
    counts: Dict[str, int] = {}
    for entry in entries:
        message = entry.get("message", {})
        if not isinstance(message, dict):
            continue
        content = message.get("content", [])
        if not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                tool_name = item.get("name", "")
                counts[tool_name] = counts.get(tool_name, 0) + 1
    return counts


def _sum_agent_tokens(entries: List[Dict[str, Any]]) -> Dict[str, int]:
    """Sum all token usage from agent entries."""
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
        "total_tokens": 0,
    }

    for entry in entries:
        message = entry.get("message", {})
        if not isinstance(message, dict):
            continue
        usage = message.get("usage", {})
        if not isinstance(usage, dict):
            continue

        totals["input_tokens"] += usage.get("input_tokens", 0)
        totals["output_tokens"] += usage.get("output_tokens", 0)
        totals["cache_creation_tokens"] += usage.get("cache_creation_input_tokens", 0)
        totals["cache_read_tokens"] += usage.get("cache_read_input_tokens", 0)

    totals["total_tokens"] = (
        totals["input_tokens"]
        + totals["output_tokens"]
        + totals["cache_creation_tokens"]
        + totals["cache_read_tokens"]
    )

    return totals


def _extract_last_action(
    entries: List[Dict[str, Any]], processor: TimestampProcessor
) -> Tuple[str, str, Optional[datetime]]:
    """Extract the last action from recent entries.

    Returns:
        Tuple of (action_description, action_type, timestamp)
    """
    # Search from most recent entries
    for entry in reversed(entries):
        message = entry.get("message", {})
        if not isinstance(message, dict):
            continue

        content = message.get("content", [])
        timestamp = processor.parse_timestamp(entry.get("timestamp", ""))

        if isinstance(content, list):
            # Check for tool_use first (most specific)
            for item in reversed(content):
                if isinstance(item, dict):
                    item_type = item.get("type", "")

                    if item_type == "tool_use":
                        tool_name = item.get("name", "Unknown")
                        tool_input = item.get("input", {})
                        action = _format_tool_action(tool_name, tool_input)
                        return action, "tool_use", timestamp

                    elif item_type == "thinking":
                        return "Thinking...", "thinking", timestamp

                    elif item_type == "text":
                        text = item.get("text", "")[:40]
                        if text:
                            return f"Responding: {text}...", "text", timestamp

        elif isinstance(content, str) and content:
            return f"Responding: {content[:40]}...", "text", timestamp

    return "Idle", "idle", None


def _format_tool_action(tool_name: str, tool_input: Dict[str, Any]) -> str:
    """Format tool usage into human-readable action."""
    formatter = TOOL_FORMATTERS.get(tool_name)
    if formatter:
        try:
            return formatter(tool_input)
        except Exception:
            pass
    return f"Using {tool_name}"


def _truncate_path(path: str, max_len: int = 25) -> str:
    """Truncate file path for display."""
    if not path:
        return "file"
    if len(path) <= max_len:
        return path
    # Keep filename, truncate directory
    parts = path.split("/")
    if len(parts) > 1:
        filename = parts[-1]
        if len(filename) <= max_len - 4:
            return f".../{filename}"
    return f"...{path[-(max_len - 3):]}"


def _truncate_cmd(cmd: str, max_len: int = 22) -> str:
    """Truncate command for display."""
    if not cmd:
        return "command"
    if len(cmd) <= max_len:
        return cmd
    return f"{cmd[:max_len - 3]}..."


def _truncate_url(url: str, max_len: int = 20) -> str:
    """Truncate URL for display."""
    if not url:
        return "url"
    # Try to extract domain
    match = re.match(r"https?://([^/]+)", url)
    if match:
        domain = match.group(1)
        if len(domain) <= max_len:
            return domain
    if len(url) <= max_len:
        return url
    return f"{url[:max_len - 3]}..."
