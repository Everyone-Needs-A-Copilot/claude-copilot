"""reconstruct.py — transcript-based usage reconstruction.

Offline / non-macOS / no-network fallback.

Reads ~/.claude/projects/**/*.jsonl timestamps and groups them into rolling
5-hour blocks to estimate activity density.  This is NOT a token count;
it's a message count — the real quota is in tokens and only the live
API headers know the true number.  But it gives a useful offline signal.

Algorithm
---------
1. Scan all .jsonl files under TRANSCRIPT_ROOT.
2. Parse every line's "timestamp" field (ISO-8601 with Z suffix).
3. Group timestamps into 5-hour buckets (aligned to UTC hour boundaries).
4. The "current" 5h block is the bucket containing now().
5. The "current" 7d block spans the last 7 * 24 h.
6. Return message counts per window.

Design decisions
----------------
- We count *messages* (lines with a "timestamp" field), not tokens, because
  tokens are not stored in transcripts.  The returned struct carries a
  ``five_h_tokens_reconstructed`` field set to the message count so
  callers understand the unit.
- Empty / missing / malformed transcript directories degrade gracefully
  (return zeros, not errors).
- Cross-project chaining: we scan ALL project dirs, not just the current one.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)

TRANSCRIPT_ROOT = Path.home() / ".claude" / "projects"
TRANSCRIPT_GLOB = "**/*.jsonl"

FIVE_H_SECONDS = 5 * 3600
SEVEN_D_SECONDS = 7 * 24 * 3600


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

def _parse_ts(ts_str: str) -> Optional[float]:
    """Parse ISO-8601 timestamp string (with or without Z/offset) to epoch float."""
    if not ts_str:
        return None
    ts_str = ts_str.strip()
    try:
        # Python 3.11+ handles Z directly; older versions need replacement
        ts_str_norm = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts_str_norm)
        return dt.timestamp()
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Transcript scanning
# ---------------------------------------------------------------------------

def _collect_timestamps(root: Path = TRANSCRIPT_ROOT) -> list[float]:
    """Scan all .jsonl files and collect all message timestamps as epoch floats."""
    timestamps: list[float] = []
    if not root.exists():
        _log.debug("Transcript root does not exist: %s", root)
        return timestamps
    try:
        for jl_path in root.glob(TRANSCRIPT_GLOB):
            try:
                for line in jl_path.read_text(encoding="utf-8", errors="replace").splitlines():
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                        ts_str = obj.get("timestamp")
                        if ts_str:
                            ep = _parse_ts(ts_str)
                            if ep is not None:
                                timestamps.append(ep)
                    except (json.JSONDecodeError, AttributeError):
                        continue
            except OSError as exc:
                _log.debug("Could not read %s: %s", jl_path, exc)
    except Exception as exc:
        _log.debug("Transcript glob error: %s", exc)
    return timestamps


# ---------------------------------------------------------------------------
# Bucketing into rolling windows
# ---------------------------------------------------------------------------

def _count_in_window(timestamps: list[float], since_epoch: float) -> int:
    """Count timestamps that fall at or after *since_epoch*."""
    return sum(1 for t in timestamps if t >= since_epoch)


def _bucket_into_5h_blocks(
    timestamps: list[float],
    now: float,
) -> dict[int, int]:
    """Group timestamps into 5-hour buckets relative to UTC epoch.

    Bucket key = floor(epoch / FIVE_H_SECONDS) * FIVE_H_SECONDS.
    Returns a dict: bucket_start_epoch -> message_count.
    """
    buckets: dict[int, int] = {}
    for t in timestamps:
        bucket = int(t // FIVE_H_SECONDS) * FIVE_H_SECONDS
        buckets[bucket] = buckets.get(bucket, 0) + 1
    return buckets


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def reconstruct_usage(
    root: Path = TRANSCRIPT_ROOT,
    _now: Optional[float] = None,
) -> "UsageCache":  # type: ignore[name-defined]  # imported at call site to avoid circular
    """Build a UsageCache from transcript files (fallback path).

    Returns a UsageCache with source='fallback' and message counts in
    the *_tokens_reconstructed fields (unit: messages, not tokens).
    """
    from cc.usage.probe import UsageCache  # local import avoids circular

    now = _now if _now is not None else time.time()

    timestamps = _collect_timestamps(root)

    five_h_count = _count_in_window(timestamps, now - FIVE_H_SECONDS)
    seven_d_count = _count_in_window(timestamps, now - SEVEN_D_SECONDS)

    # Compute the current 5h bucket start for reset estimate
    current_bucket_start = int(now // FIVE_H_SECONDS) * FIVE_H_SECONDS
    five_h_reset = current_bucket_start + FIVE_H_SECONDS

    seven_d_reset = int((now // SEVEN_D_SECONDS) + 1) * SEVEN_D_SECONDS

    return UsageCache(
        probed_at=now,
        source="fallback",
        idle_gated=False,
        five_h_tokens_reconstructed=five_h_count,
        seven_d_tokens_reconstructed=seven_d_count,
        five_h_reset_epoch=int(five_h_reset),
        seven_d_reset_epoch=int(seven_d_reset),
    )
