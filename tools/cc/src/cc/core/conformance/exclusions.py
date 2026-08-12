"""Reviewed conformance exclusions.

An exclusion is not a passing result and it is never invisible.  This module
holds the small, owner-ratified set that the current machine-local
``excluded-projects.json`` format cannot describe on its own.  Each record
names the affected path, the reason, the decision authority, and durable
review evidence.  D13 renders a matching record as an explicit ``SKIP`` with
``reviewed-exclusion`` evidence; an unmatched registry entry remains a
failure.

The registry deliberately uses portable path suffixes instead of absolute
machine paths.  It is conformance evidence, not write authority: nothing in
this module edits the exclusion registry or any project.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from cc.core.conformance.types import Evidence


@dataclass(frozen=True)
class ReviewedExclusion:
    """One attributable, owner-reviewed exception to fleet participation."""

    path_suffix: str
    reason: str
    authority: str
    review_evidence: str
    reviewed_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "path_suffix",
            "reason",
            "authority",
            "review_evidence",
            "reviewed_at",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"ReviewedExclusion.{field_name} must be non-empty.")

    def matches(self, path: Path | str) -> bool:
        normalized = Path(path).expanduser().as_posix().rstrip("/")
        suffix = self.path_suffix.strip("/")
        return normalized == suffix or normalized.endswith(f"/{suffix}")

    def evidence(self, path: Path | str) -> Evidence:
        return Evidence(
            kind="reviewed-exclusion",
            path=str(Path(path).expanduser()),
            expected=self.reason,
            actual=f"authority={self.authority}; reviewed_at={self.reviewed_at}",
            detail=f"review_evidence={self.review_evidence}",
        )


_Q14_REVIEW = (
    "copilot-control-tower/docs/40-initiatives/"
    "05-ecosystem-conformance-audit/audit/"
    "ecosystem-audit-open-questions.md#q14-keep-alive-or-archive-calls-for-5-low-activity-repos"
)

# Pablo selected Q14 option B for these four repositories: archive on GitHub
# or exclude them from framework fan-out.  The repositories have not all been
# archived yet, so the machine-local exclusion is the operative disposition.
DEFAULT_REVIEWED_EXCLUSIONS: tuple[ReviewedExclusion, ...] = (
    ReviewedExclusion(
        path_suffix="COPILOT/BM",
        reason="Owner chose archive-or-exclude for this low-activity client research repository (Q14 option B).",
        authority="Pablo Alejo (ecosystem owner)",
        review_evidence=_Q14_REVIEW,
        reviewed_at="2026-08-10",
    ),
    ReviewedExclusion(
        path_suffix="COPILOT/preflight-copilot",
        reason="Owner chose archive-or-exclude for this sunset-planned product (Q14 option B).",
        authority="Pablo Alejo (ecosystem owner)",
        review_evidence=_Q14_REVIEW,
        reviewed_at="2026-08-10",
    ),
    ReviewedExclusion(
        path_suffix="COPILOT/workflow-copilot",
        reason="Owner chose archive-or-exclude for this dormant, superseded product (Q14 option B).",
        authority="Pablo Alejo (ecosystem owner)",
        review_evidence=_Q14_REVIEW,
        reviewed_at="2026-08-10",
    ),
    ReviewedExclusion(
        path_suffix="COPILOT/rfp-copilot",
        reason="Owner chose archive-or-exclude for this superseded product (Q14 option B).",
        authority="Pablo Alejo (ecosystem owner)",
        review_evidence=_Q14_REVIEW,
        reviewed_at="2026-08-10",
    ),
)


def find_reviewed_exclusion(
    path: Path | str,
    *,
    reviewed: Iterable[ReviewedExclusion] = DEFAULT_REVIEWED_EXCLUSIONS,
) -> ReviewedExclusion | None:
    """Return the unique reviewed record matching ``path``, if any.

    Multiple matching records are an authoring defect rather than a
    precedence rule: an operator must never have to guess which decision is
    authoritative.
    """

    matches = tuple(entry for entry in reviewed if entry.matches(path))
    if len(matches) > 1:
        raise ValueError(
            f"multiple reviewed exclusions match {str(path)!r}: "
            f"{[entry.path_suffix for entry in matches]!r}"
        )
    return matches[0] if matches else None


__all__ = [
    "DEFAULT_REVIEWED_EXCLUSIONS",
    "ReviewedExclusion",
    "find_reviewed_exclusion",
]
