"""D11 -- Registry entry in `ECOSYSTEM.md` (`RUBRIC.md` D11,
`TEST-MATRIX.md` IC-D11-REGISTRY).

The owner has now ratified what the registry SHOULD contain
(`docs/ecosystem-audit-open-questions.md` Q2-Q8), so this check asserts
against the RATIFIED TARGET STATE, never against today's file content. The
target state is encoded as plain data (`EXPECTED_REGISTRY`, below) precisely
so a future correction to the target -- a repo renamed again, a fifth
product added -- is a data edit, never a change to the check logic:

  - Q5 (all "add now"): `flow`, `crm-automation-copilot`,
    `thought-leadership`, `small-business-copilot` need real table rows.
  - Q8-A: `knowledge-copilot` (the public foundation) needs its own Layer-1
    row, matching its 3 siblings (`claude-copilot`, `codex-copilot`,
    `cli-copilot`).
  - Q4-C: the 12 class-B tier-variant repos are represented as a compact
    product x tier MATRIX section, never as 12 individual rows (this is
    deliberately NOT "add 12 rows" -- `TIER_VARIANT_REPOS_REQUIRING_MATRIX`
    below is exactly the 10 of those 12 that do not already carry their own
    row for an unrelated reason; `cli-copilot-internal` and
    `knowledge-copilot-internal` each already have a standalone Layer-1 row
    today and keep it).
  - Q6-B: `everyone-needs-knowledge-management`, `rfp-copilot`,
    `conversations-copilot`, `ops-copilot`/`ops-copilot-platform` are
    removed entirely -- none of `COPILOT/_archive/` recoverable on this
    machine, so "correct the path" is not an option; the row/mention must
    be gone, not relocated.
  - Q7-A: 4 names corrected to match disk --
    `forces-assessment` -> `force-readiness-assessment`,
    `transformations` -> `transformation`, and (documented, not yet a table
    row on this machine) `Hermes-3`/`h3` and `performance-tracker`/`tracker`.
  - Q3-A: the "Client delivery" exclusion bullet additionally names
    `Delphi` and `Hermes-2` (it already correctly names `Hermes-3`).
  - Q2: PERSONAL is now explicitly IN scope ("Add the ecosystem to all
    personal work") -- there is therefore no `class == PERSONAL` branch
    anywhere in this module that returns SKIP/NA. A PERSONAL-tree subject
    is evaluated by the exact same rules as any class C repo (either a
    named `EXPECTED_REGISTRY` entry, or the generic row-or-out-of-scope-
    mention fallback below). This is enforced structurally, not by a
    comment: read `check_registry_entry` top to bottom and there is no
    branch on path prefix at all.

Table-row detection is deliberately markdown-table-row-shaped
(`^\\|\\s*\\**name\\**\\s*\\|`), never a bare substring search -- prose-only
mentions do not count as PRESENT (`TEST-MATRIX.md` IC-D11-REGISTRY: "grep
the repo's canonical name against ECOSYSTEM.md's table rows (not prose)").
This is what correctly rejects the existing `> Renamed 2026-06-29:` banner
line that name-drops `knowledge-copilot` in prose without giving it a row.

This check never mutates `ECOSYSTEM.md`; it is a plain read (`Path.read_
text`), never routed through git plumbing, so it needs no allowlisted
`fsguard.run_git_readonly` call at all.

`run(context)` below implements the `dimensions/__init__.py` module
contract (`DimensionModule`/`RepoContext`, owned by WP-4), which has since
landed. `RepoContext` carries no separate "canonical registry name" field,
so `run()` derives it the same way `check_registry_entry`'s own default
does -- `context.path.name`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from cc.core.config import resolve_key
from cc.core.conformance.registry import register_check
from cc.core.conformance.types import (
    CheckResult,
    Evidence,
    ExpectedToday,
    Layer,
    Mode,
    Scope,
    Severity,
    Verdict,
)

if TYPE_CHECKING:
    from cc.core.conformance.dimensions import RepoContext

_APPLIES_TO = ("A", "B", "C")  # RUBRIC.md D11: "Applies to: A, B, C (products)."

_ECOSYSTEM_MD_ENV = "CC_CONFORMANCE_ECOSYSTEM_MD"

class RegistryDisposition(StrEnum):
    """How a ratified-target subject is expected to appear in
    `ECOSYSTEM.md`."""

    ROW = "row"  # a real markdown table row, under the given layer if named
    EXCLUDED_BULLET = "excluded_bullet"  # named in the "Out of scope" section
    REMOVED = "removed"  # must not appear anywhere (a dead entry, Q6-B)


@dataclass(frozen=True)
class ExpectedRegistryEntry:
    """One ratified-target fact about one product name. `aliases` are
    incorrect/legacy spellings that must NOT be the only spelling present
    (a row still living under an alias is reported as a stale-name FAIL,
    not a PASS)."""

    canonical_name: str
    disposition: RegistryDisposition
    aliases: tuple[str, ...] = ()
    layer: str = ""  # e.g. "Layer 1" -- constrains ROW lookup to that section
    note: str = ""


# --- THE RATIFIED TARGET STATE (DATA) --------------------------------------
# Every entry cites the owner's ratified answer
# (`docs/ecosystem-audit-open-questions.md`). Edit this table, never the
# check logic below, when the ratified target changes.
EXPECTED_REGISTRY: tuple[ExpectedRegistryEntry, ...] = (
    # Q5 -- add now (all four answered "Add now").
    ExpectedRegistryEntry("flow", RegistryDisposition.ROW, note="Q5: add now"),
    ExpectedRegistryEntry(
        "crm-automation-copilot", RegistryDisposition.ROW, note="Q5: add now"
    ),
    ExpectedRegistryEntry(
        "thought-leadership", RegistryDisposition.ROW, note="Q5: add now"
    ),
    ExpectedRegistryEntry(
        "small-business-copilot", RegistryDisposition.ROW, note="Q5: add now"
    ),
    # Q8-A -- knowledge-copilot (public foundation) gets its own Layer-1 row.
    ExpectedRegistryEntry(
        "knowledge-copilot", RegistryDisposition.ROW, layer="Layer 1", note="Q8-A"
    ),
    # Already-correct Layer-1 siblings, named explicitly so the "generic
    # fallback" branch is never exercised for them and so KNOWN_TODAY_PASS_
    # NAMES has a single, auditable source next to what it's grounded in.
    ExpectedRegistryEntry("claude-copilot", RegistryDisposition.ROW, layer="Layer 1"),
    ExpectedRegistryEntry("codex-copilot", RegistryDisposition.ROW, layer="Layer 1"),
    ExpectedRegistryEntry("cli-copilot", RegistryDisposition.ROW, layer="Layer 1"),
    ExpectedRegistryEntry(
        "cli-copilot-internal", RegistryDisposition.ROW, layer="Layer 1"
    ),
    ExpectedRegistryEntry(
        "knowledge-copilot-internal", RegistryDisposition.ROW, layer="Layer 1"
    ),
    ExpectedRegistryEntry(
        "product-creation-copilot", RegistryDisposition.ROW, layer="Layer 1"
    ),
    ExpectedRegistryEntry(
        "copilot-control-tower", RegistryDisposition.ROW, layer="Layer 1"
    ),
    # Q7-A -- name corrections (registry name must match disk).
    ExpectedRegistryEntry(
        "force-readiness-assessment",
        RegistryDisposition.ROW,
        aliases=("forces-assessment",),
        layer="Layer 3",
        note="Q7-A",
    ),
    ExpectedRegistryEntry(
        "transformation",
        RegistryDisposition.ROW,
        aliases=("transformations",),
        layer="Layer 3",
        note="Q7-A",
    ),
    # Q7-A -- PERSONAL/tracker (repo pablitoalejo/performance-tracker): no
    # longer N/A-by-being-personal per Q2 -- needs a real row under its
    # disk name, never the old repo-name spelling.
    ExpectedRegistryEntry(
        "tracker",
        RegistryDisposition.ROW,
        aliases=("performance-tracker",),
        note="Q7-A + Q2: PERSONAL is in scope",
    ),
    # Q6-B -- dead entries removed entirely (none recoverable from
    # COPILOT/_archive/, which is empty on this machine).
    ExpectedRegistryEntry(
        "everyone-needs-knowledge-management",
        RegistryDisposition.REMOVED,
        note="Q6-B",
    ),
    ExpectedRegistryEntry("rfp-copilot", RegistryDisposition.REMOVED, note="Q6-B"),
    ExpectedRegistryEntry(
        "conversations-copilot", RegistryDisposition.REMOVED, note="Q6-B"
    ),
    ExpectedRegistryEntry("ops-copilot", RegistryDisposition.REMOVED, note="Q6-B"),
    ExpectedRegistryEntry(
        "ops-copilot-platform", RegistryDisposition.REMOVED, note="Q6-B"
    ),
    # Q3-A -- client-delivery exclusion bullet gains 2 more names (it
    # already correctly names Hermes-3/h3 -- Q7-A's "pick one" is already
    # satisfied by the existing "Hermes-3" spelling, so no change is
    # required there).
    ExpectedRegistryEntry(
        "Hermes-3",
        RegistryDisposition.EXCLUDED_BULLET,
        aliases=("h3",),
        note="Q7-A: already correctly spelled in the exclusion bullet",
    ),
    ExpectedRegistryEntry("Delphi", RegistryDisposition.EXCLUDED_BULLET, note="Q3-A"),
    ExpectedRegistryEntry(
        "Hermes-2", RegistryDisposition.EXCLUDED_BULLET, aliases=("h2",), note="Q3-A"
    ),
)

# Q4-C -- represented via a product x tier MATRIX, never 12 individual rows.
# 10 of the 12 class-B tier variants (the other 2, `cli-copilot-internal`
# and `knowledge-copilot-internal`, already carry their own standalone row
# for an unrelated reason -- see EXPECTED_REGISTRY above -- and keep it).
TIER_VARIANT_REPOS_REQUIRING_MATRIX: frozenset[str] = frozenset(
    {
        "claude-copilot-internal",
        "claude-copilot-accounting",
        "claude-copilot-private",
        "codex-copilot-internal",
        "codex-copilot-accounting",
        "codex-copilot-private",
        "cli-copilot-accounting",
        "cli-copilot-private",
        "knowledge-copilot-accounting",
        "knowledge-copilot-private",
    }
)

# Machine-verified today (direct read of ECOSYSTEM.md, 2026-08-10): the
# subset of EXPECTED_REGISTRY names (plus the 2 tier variants with their own
# pre-existing row) that ALREADY satisfy the ratified target as written.
# Everything else named in EXPECTED_REGISTRY or
# TIER_VARIANT_REPOS_REQUIRING_MATRIX is verified-FAIL-today. Any name in
# neither collection has no specific ground-truth claim attached here (the
# generic fallback's own live evaluation is the only signal for it).
KNOWN_TODAY_PASS_NAMES: frozenset[str] = frozenset(
    {
        "claude-copilot",
        "codex-copilot",
        "cli-copilot",
        "cli-copilot-internal",
        "knowledge-copilot-internal",
        "product-creation-copilot",
        "copilot-control-tower",
        "Hermes-3",
    }
)


def _find_entry(name: str) -> ExpectedRegistryEntry | None:
    for entry in EXPECTED_REGISTRY:
        if name == entry.canonical_name or name in entry.aliases:
            return entry
    return None


def _default_ecosystem_md_candidates() -> tuple[Path, ...]:
    candidates: list[Path] = []
    override = os.environ.get(_ECOSYSTEM_MD_ENV)
    if override:
        candidates.append(Path(override).expanduser())
    configured = resolve_key("paths.shared_docs")
    if isinstance(configured, str) and configured and configured != "@machine":
        candidates.append(Path(configured).expanduser() / "ECOSYSTEM.md")
    roots = resolve_key("projects.roots") or []
    if isinstance(roots, str):
        roots = [roots]
    for raw_root in roots:
        root = Path(str(raw_root)).expanduser()
        candidates.extend(
            (
                root / "shared-docs" / "ECOSYSTEM.md",
                root / "COPILOT" / "shared-docs" / "ECOSYSTEM.md",
            )
        )
    # Conventional undocked layout, expressed relative to the current
    # account rather than one developer's literal home directory.
    candidates.append(Path.home() / "Sites" / "COPILOT" / "shared-docs" / "ECOSYSTEM.md")
    return tuple(candidates)


def resolve_ecosystem_md_path() -> Path | None:
    """First existing candidate path to the real `ECOSYSTEM.md`, or `None`
    if none of the known locations exist on this machine. Never raises."""

    for candidate in _default_ecosystem_md_candidates():
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


_TABLE_ROW_TEMPLATE = r"^\|\s*\**{name}\**\s*\|"


def _has_table_row(text: str, name: str) -> bool:
    pattern = re.compile(_TABLE_ROW_TEMPLATE.format(name=re.escape(name)), re.MULTILINE)
    return bool(pattern.search(text))


def _section(text: str, heading: str) -> str:
    """Text from a `## <heading>...` line up to (not including) the next
    `## ` heading, or the end of the document. Empty string if the heading
    is not present at all."""

    pattern = re.compile(
        rf"^##\s*{re.escape(heading)}.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL
    )
    match = pattern.search(text)
    return match.group(0) if match else ""


_TIER_MATRIX_HEADING = re.compile(
    r"^##.*\btier\b.*(matrix|variant)", re.MULTILINE | re.IGNORECASE
)
_TIER_ROLE_WORDS: tuple[str, ...] = (
    "foundation",
    "organization",
    "department",
    "personal",
)


def _has_tier_matrix_section(text: str) -> bool:
    """Q4-C's target: a heading naming a tier matrix/legend, OR a table row
    whose cells name at least 3 of the 4 tier roles (a real product x tier
    header row). Deliberately lenient about exact heading wording -- this
    check exists to detect ABSENCE today, and should not be so strict that
    a reasonable future implementation of Q4-C fails to satisfy it."""

    if _TIER_MATRIX_HEADING.search(text):
        return True
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        lowered = stripped.lower()
        if sum(word in lowered for word in _TIER_ROLE_WORDS) >= 3:
            return True
    return False


_REGISTRY_ENTRY_CHECK = register_check(
    id="repo.d11.registry_entry",
    layer=Layer.REPO,
    severity=Severity.S3,
    scope=Scope.PER_REPO,
    summary=(
        "The repo is represented in ECOSYSTEM.md per the ratified target "
        "state (docs/ecosystem-audit-open-questions.md Q2-Q8): a real "
        "table row (never prose-only), the corrected name, the tier-variant "
        "matrix, or the appropriate exclusion bullet."
    ),
    remediation=(
        "Add/correct the row, bullet mention, or matrix entry in "
        "ECOSYSTEM.md per the ratified answer cited in this result's "
        "detail. PERSONAL repos are in scope (Q2) -- being under PERSONAL/ "
        "is never itself a reason to skip this."
    ),
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)


def _evaluate_tier_matrix(
    text: str, doc_path: Path
) -> tuple[Verdict, tuple[Evidence, ...], str | None]:
    if _has_tier_matrix_section(text):
        return Verdict.PASS, (), None
    evidence = (
        Evidence(
            kind="registry-tier-matrix",
            path=str(doc_path),
            expected=(
                "a product x tier matrix/legend section representing the "
                "12 class-B tier-variant repos (Q4-C)"
            ),
            actual="no matrix/legend section found",
            detail="the 12 tier variants are entirely undocumented today",
        ),
    )
    return Verdict.FAIL, evidence, "registry.tier_matrix_missing"


def _evaluate_row_entry(
    text: str, entry: ExpectedRegistryEntry, doc_path: Path
) -> tuple[Verdict, tuple[Evidence, ...]]:
    section_text = _section(text, entry.layer) if entry.layer else text
    haystack = section_text or text
    if _has_table_row(haystack, entry.canonical_name):
        return Verdict.PASS, ()
    stale_alias = next(
        (alias for alias in entry.aliases if _has_table_row(text, alias)), None
    )
    actual = (
        f"still present under the old name {stale_alias!r}"
        if stale_alias
        else "no matching table row found"
    )
    expected = f"a table row named {entry.canonical_name!r}"
    if entry.layer:
        expected += f" under {entry.layer}"
    evidence = (
        Evidence(
            kind="registry-row",
            path=str(doc_path),
            expected=expected,
            actual=actual,
            detail=entry.note,
        ),
    )
    return Verdict.FAIL, evidence


def _evaluate_excluded_bullet_entry(
    text: str, entry: ExpectedRegistryEntry, doc_path: Path
) -> tuple[Verdict, tuple[Evidence, ...]]:
    scope_text = _section(text, "Out of scope")
    present = entry.canonical_name in scope_text or any(
        alias in scope_text for alias in entry.aliases
    )
    if present:
        return Verdict.PASS, ()
    evidence = (
        Evidence(
            kind="registry-bullet",
            path=str(doc_path),
            expected=(
                f"{entry.canonical_name!r} named in the Out of scope exclusion bullet"
            ),
            actual="not mentioned in the Out of scope section",
            detail=entry.note,
        ),
    )
    return Verdict.FAIL, evidence


def _evaluate_removed_entry(
    text: str, entry: ExpectedRegistryEntry, doc_path: Path
) -> tuple[Verdict, tuple[Evidence, ...]]:
    still_present = _has_table_row(text, entry.canonical_name) or (
        entry.canonical_name in text
    )
    if not still_present:
        return Verdict.PASS, ()
    evidence = (
        Evidence(
            kind="registry-dead-entry",
            path=str(doc_path),
            expected=f"{entry.canonical_name!r} removed entirely (Q6-B)",
            actual="still referenced in the document",
            detail=entry.note,
        ),
    )
    return Verdict.FAIL, evidence


def _evaluate_generic(
    text: str, name: str, doc_path: Path
) -> tuple[Verdict, tuple[Evidence, ...]]:
    """No ratified-target entry names this repo specifically. Fall back to
    the plain rubric rule: a real table row, OR a mention inside the "Out
    of scope" section. This branch is class-blind by construction -- it
    never inspects `repo`'s path, so a PERSONAL-tree subject is judged
    exactly like any other (Q2: PERSONAL is in scope)."""

    if _has_table_row(text, name):
        return Verdict.PASS, ()
    scope_text = _section(text, "Out of scope")
    if name in scope_text:
        return Verdict.PASS, ()
    evidence = (
        Evidence(
            kind="registry-row",
            path=str(doc_path),
            expected=f"a table row or an Out-of-scope mention for {name!r}",
            actual="neither found",
        ),
    )
    return Verdict.FAIL, evidence


def check_registry_entry(
    repo: Path,
    *,
    canonical_name: str | None = None,
    ecosystem_md: Path | None = None,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    """`repo.d11.registry_entry` against one repo. `canonical_name` lets a
    caller supply the class-resolved name (`classes.py`'s job, once it
    exists); it falls back to the directory basename. `expected_today`
    overrides this function's own machine-verified grounding
    (`KNOWN_TODAY_PASS_NAMES` / `EXPECTED_REGISTRY` membership) when a
    caller has better information; left `None`, that grounding is the
    default."""

    name = subject or str(repo)
    lookup_name = canonical_name or repo.name
    doc_path = ecosystem_md or resolve_ecosystem_md_path()
    if doc_path is not None and not doc_path.is_file():
        doc_path = None

    if doc_path is None:
        return CheckResult(
            id=_REGISTRY_ENTRY_CHECK.id,
            layer=_REGISTRY_ENTRY_CHECK.layer,
            severity=_REGISTRY_ENTRY_CHECK.severity,
            scope=_REGISTRY_ENTRY_CHECK.scope,
            subject=name,
            assertion=_REGISTRY_ENTRY_CHECK.summary,
            verdict=Verdict.COULD_NOT_RUN,
            expected_today=(
                expected_today if expected_today is not None else ExpectedToday.PASS
            ),
            detail="ECOSYSTEM.md not found at any known location on this machine",
            remediation=_REGISTRY_ENTRY_CHECK.remediation,
        )

    text = doc_path.read_text(encoding="utf-8")

    if lookup_name in TIER_VARIANT_REPOS_REQUIRING_MATRIX:
        verdict, evidence, root_cause = _evaluate_tier_matrix(text, doc_path)
        expected = (
            expected_today
            if expected_today is not None
            else (
                ExpectedToday.PASS
                if lookup_name in KNOWN_TODAY_PASS_NAMES
                else ExpectedToday.FAIL
            )
        )
        return _REGISTRY_ENTRY_CHECK.result(
            subject=name,
            verdict=verdict,
            evidence=evidence,
            expected_today=expected,
            detail="Q4-C: tier variants are represented via a matrix, not per-repo rows",
            root_cause=root_cause,
        )

    entry = _find_entry(lookup_name)
    if entry is not None:
        if entry.disposition is RegistryDisposition.ROW:
            verdict, evidence = _evaluate_row_entry(text, entry, doc_path)
        elif entry.disposition is RegistryDisposition.EXCLUDED_BULLET:
            verdict, evidence = _evaluate_excluded_bullet_entry(text, entry, doc_path)
        elif entry.disposition is RegistryDisposition.REMOVED:
            verdict, evidence = _evaluate_removed_entry(text, entry, doc_path)
        else:  # pragma: no cover -- exhaustive over RegistryDisposition
            raise AssertionError(f"unhandled disposition {entry.disposition!r}")
        expected = (
            expected_today
            if expected_today is not None
            else (
                ExpectedToday.PASS
                if lookup_name in KNOWN_TODAY_PASS_NAMES
                else ExpectedToday.FAIL
            )
        )
        return _REGISTRY_ENTRY_CHECK.result(
            subject=name, verdict=verdict, evidence=evidence, expected_today=expected
        )

    verdict, evidence = _evaluate_generic(text, lookup_name, doc_path)
    # No EXPECTED_REGISTRY entry names this repo specifically, so there is
    # no machine-verified ground truth to attach here -- default to PASS
    # (the registration's own neutral default) rather than fabricate a
    # known-bad claim this module never actually checked.
    return _REGISTRY_ENTRY_CHECK.result(
        subject=name,
        verdict=verdict,
        evidence=evidence,
        expected_today=(
            expected_today if expected_today is not None else ExpectedToday.PASS
        ),
    )


def run(context: "RepoContext") -> Iterable[CheckResult]:
    """The `dimensions/__init__.py` module contract's required entry
    point: one `CheckResult` for `repo.d11.registry_entry`, for every repo
    (`Verdict.SKIP` for a class D11 does not apply to). Uses
    `context.path.name` as the canonical registry name -- see module
    docstring."""

    if context.rubric_class not in _APPLIES_TO:
        return (
            _REGISTRY_ENTRY_CHECK.result(
                subject=context.subject,
                verdict=Verdict.SKIP,
                detail=(
                    f"N/A for class {context.rubric_class} -- D11 applies to "
                    "classes A/B/C (products)."
                ),
            ),
        )
    return (check_registry_entry(context.path, subject=context.subject),)


__all__ = [
    "EXPECTED_REGISTRY",
    "ExpectedRegistryEntry",
    "KNOWN_TODAY_PASS_NAMES",
    "RegistryDisposition",
    "TIER_VARIANT_REPOS_REQUIRING_MATRIX",
    "check_registry_entry",
    "resolve_ecosystem_md_path",
    "run",
]
