"""Plan auto-detection for Claude Monitor.

Combines multiple detection strategies to infer user's subscription plan:
1. Limit-hit detection (highest confidence) - detects when rate limits are hit
2. Max-usage inference (medium confidence) - infers minimum plan from max usage
3. P90 calculation fallback (lowest confidence) - statistical estimation
"""

import logging
from typing import Any, Dict, List, Optional

from claude_monitor.core.models import DetectionConfidence, PlanDetectionResult
from claude_monitor.core.p90_calculator import P90Calculator
from claude_monitor.core.plans import (
    LIMIT_DETECTION_THRESHOLD,
    PLAN_LIMITS,
    Plans,
    PlanType,
)

logger = logging.getLogger(__name__)


class PlanDetector:
    """Detects user's Claude subscription plan from usage data."""

    def __init__(self) -> None:
        self.p90_calculator = P90Calculator()

    def detect_plan(
        self,
        blocks: List[Dict[str, Any]],
        raw_entries: Optional[List[Dict[str, Any]]] = None,
    ) -> PlanDetectionResult:
        """Detect the most likely plan from usage data.

        Detection priority:
        1. If limit-hit detected at known threshold -> HIGH confidence
        2. If max usage exceeds known plan limits -> MEDIUM confidence
        3. Fall back to P90 calculation -> LOW confidence

        Args:
            blocks: Session blocks with totalTokens, isGap, isActive fields
            raw_entries: Raw JSONL entries for limit detection

        Returns:
            PlanDetectionResult with detected plan and confidence
        """
        if not blocks:
            return PlanDetectionResult(
                detected_plan="pro",
                confidence=DetectionConfidence.UNKNOWN,
                token_limit=Plans.DEFAULT_TOKEN_LIMIT,
                detection_method="no_data",
                evidence=["No usage data available"],
            )

        # Strategy 1: Check for rate limit events (highest priority)
        if raw_entries:
            limit_result = self._detect_from_limit_hits(raw_entries, blocks)
            if limit_result:
                return limit_result

        # Strategy 2: Infer from max token usage
        max_usage_result = self._detect_from_max_usage(blocks)
        if (
            max_usage_result
            and max_usage_result.confidence != DetectionConfidence.UNKNOWN
        ):
            return max_usage_result

        # Strategy 3: Fall back to P90 calculation
        return self._detect_from_p90(blocks)

    def _detect_from_limit_hits(
        self,
        raw_entries: List[Dict[str, Any]],
        blocks: List[Dict[str, Any]],
    ) -> Optional[PlanDetectionResult]:
        """Detect plan from rate limit events.

        When a user hits a rate limit, the limit threshold reveals their plan.
        """
        from claude_monitor.data.analyzer import SessionAnalyzer

        analyzer = SessionAnalyzer()
        limit_events = analyzer.detect_limits(raw_entries)

        if not limit_events:
            return None

        # Find blocks with limit messages or closest to limit events
        limit_hit_tokens: List[int] = []

        for block in blocks:
            if block.get("isGap"):
                continue

            # Check if block has limit messages
            if block.get("limitMessages") or block.get("limit_messages"):
                block_tokens = block.get("totalTokens", 0) or block.get(
                    "total_tokens", 0
                )
                if block_tokens > 0:
                    limit_hit_tokens.append(block_tokens)

        # Also check limit events for token context
        for event in limit_events:
            block_context = event.get("block_context", {})
            usage = block_context.get("usage", {})

            # Sum up tokens from usage if available
            total = (
                usage.get("input_tokens", 0)
                + usage.get("output_tokens", 0)
                + usage.get("cache_creation_input_tokens", 0)
                + usage.get("cache_read_input_tokens", 0)
            )
            if total > 0:
                limit_hit_tokens.append(total)

        if not limit_hit_tokens:
            # We have limit events but can't determine token count
            # Return None to fall through to other strategies
            logger.debug("Limit events found but no token counts available")
            return None

        max_limit_tokens = max(limit_hit_tokens)
        detected_plan = self._infer_plan_from_limit(max_limit_tokens)

        if detected_plan:
            plan_config = Plans.get_plan(detected_plan)
            return PlanDetectionResult(
                detected_plan=detected_plan.value,
                confidence=DetectionConfidence.HIGH,
                token_limit=plan_config.token_limit,
                detection_method="limit_hit",
                evidence=[
                    f"Rate limit hit at ~{max_limit_tokens:,} tokens",
                    f"Matches {plan_config.display_name} plan ({plan_config.token_limit:,})",
                    f"Found {len(limit_events)} limit event(s)",
                ],
                max_session_tokens=max_limit_tokens,
                limit_hit_count=len(limit_events),
                limit_hit_threshold=plan_config.token_limit,
            )

        return None

    def _infer_plan_from_limit(self, tokens_at_limit: int) -> Optional[PlanType]:
        """Infer plan from token count when limit was hit."""
        pro_limit = PLAN_LIMITS[PlanType.PRO]["token_limit"]
        max5_limit = PLAN_LIMITS[PlanType.MAX5]["token_limit"]
        max20_limit = PLAN_LIMITS[PlanType.MAX20]["token_limit"]

        threshold = LIMIT_DETECTION_THRESHOLD  # 0.95

        # Check if tokens match a known limit (within threshold)
        if tokens_at_limit >= pro_limit * threshold and tokens_at_limit < max5_limit * 0.5:
            return PlanType.PRO
        elif (
            tokens_at_limit >= max5_limit * threshold
            and tokens_at_limit < max20_limit * 0.5
        ):
            return PlanType.MAX5
        elif tokens_at_limit >= max20_limit * threshold:
            return PlanType.MAX20

        return None

    def _detect_from_max_usage(
        self,
        blocks: List[Dict[str, Any]],
    ) -> Optional[PlanDetectionResult]:
        """Detect minimum plan from maximum session token usage.

        Logic:
        - If any session used >88k tokens, user MUST be on Max20
        - If any session used >19k tokens, user MUST be on Max5+
        - Otherwise, could be Pro
        """
        if not blocks:
            return None

        # Get max tokens from completed (non-active, non-gap) sessions
        completed_sessions = [
            b
            for b in blocks
            if not b.get("isGap") and not b.get("isActive") and not b.get("is_gap") and not b.get("is_active")
        ]

        if not completed_sessions:
            # Try all non-gap blocks
            completed_sessions = [
                b for b in blocks if not b.get("isGap") and not b.get("is_gap")
            ]

        if not completed_sessions:
            return None

        # Handle both dict formats (camelCase from JSON and snake_case from dataclass)
        max_tokens = max(
            b.get("totalTokens", 0) or b.get("total_tokens", 0)
            for b in completed_sessions
        )

        if max_tokens <= 0:
            return None

        # Determine minimum plan based on max usage
        pro_limit = PLAN_LIMITS[PlanType.PRO]["token_limit"]  # 19k
        max5_limit = PLAN_LIMITS[PlanType.MAX5]["token_limit"]  # 88k
        max20_limit = PLAN_LIMITS[PlanType.MAX20]["token_limit"]  # 220k

        evidence = [f"Maximum session usage: {max_tokens:,} tokens"]

        if max_tokens > max5_limit:
            # Must be Max20
            return PlanDetectionResult(
                detected_plan=PlanType.MAX20.value,
                confidence=DetectionConfidence.MEDIUM,
                token_limit=max20_limit,
                detection_method="max_usage",
                evidence=evidence
                + [
                    f"Exceeds Max5 limit ({max5_limit:,}), must be Max20",
                ],
                max_session_tokens=max_tokens,
            )
        elif max_tokens > pro_limit:
            # Must be at least Max5
            return PlanDetectionResult(
                detected_plan=PlanType.MAX5.value,
                confidence=DetectionConfidence.MEDIUM,
                token_limit=max5_limit,
                detection_method="max_usage",
                evidence=evidence
                + [
                    f"Exceeds Pro limit ({pro_limit:,}), must be Max5+",
                ],
                max_session_tokens=max_tokens,
            )
        else:
            # Could be Pro (but not definitive - they might just not have used much)
            return PlanDetectionResult(
                detected_plan=PlanType.PRO.value,
                confidence=DetectionConfidence.LOW,
                token_limit=pro_limit,
                detection_method="max_usage",
                evidence=evidence
                + [
                    f"Within Pro limit ({pro_limit:,}), likely Pro plan",
                ],
                max_session_tokens=max_tokens,
            )

    def _detect_from_p90(
        self,
        blocks: List[Dict[str, Any]],
    ) -> PlanDetectionResult:
        """Fall back to P90 calculation for limit estimation."""
        p90_limit = self.p90_calculator.calculate_p90_limit(blocks)

        if p90_limit is None:
            p90_limit = Plans.DEFAULT_TOKEN_LIMIT

        # Determine which plan the P90 is closest to
        detected_plan = self._closest_plan_for_limit(p90_limit)
        plan_config = Plans.get_plan(detected_plan)

        return PlanDetectionResult(
            detected_plan=detected_plan.value,
            confidence=DetectionConfidence.LOW,
            token_limit=p90_limit,  # Use calculated P90, not plan limit
            detection_method="p90_fallback",
            evidence=[
                f"P90 session limit: {p90_limit:,} tokens",
                f"Closest to {plan_config.display_name} plan",
            ],
        )

    def _closest_plan_for_limit(self, token_limit: int) -> PlanType:
        """Find the closest matching plan for a token limit."""
        pro_limit = PLAN_LIMITS[PlanType.PRO]["token_limit"]
        max5_limit = PLAN_LIMITS[PlanType.MAX5]["token_limit"]
        max20_limit = PLAN_LIMITS[PlanType.MAX20]["token_limit"]

        # Find closest plan
        distances = {
            PlanType.PRO: abs(token_limit - pro_limit),
            PlanType.MAX5: abs(token_limit - max5_limit),
            PlanType.MAX20: abs(token_limit - max20_limit),
        }

        return min(distances, key=lambda k: distances[k])
