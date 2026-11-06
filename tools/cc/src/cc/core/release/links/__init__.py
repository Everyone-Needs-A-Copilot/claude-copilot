"""Machine link generator (ADR-001 decision 2, stream release-links).

`build_plan` derives one link plan from a release directory; `apply_plan`
makes `~/.claude` and `~/.codex` match it, owning only what the receipt
(`~/.copilot/links-receipt.json`) records.
"""

from .apply import ApplyReport, apply_plan, remove_all
from .plan import LinkEntry, LinkPlan, build_plan, plan_from_json, plan_to_json, write_plan

__all__ = [
    "ApplyReport",
    "LinkEntry",
    "LinkPlan",
    "apply_plan",
    "build_plan",
    "plan_from_json",
    "plan_to_json",
    "remove_all",
    "write_plan",
]
