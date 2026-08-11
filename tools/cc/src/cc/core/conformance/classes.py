"""The ecosystem repo taxonomy: COMPONENT / PRODUCT / SITE-CONTENT /
DOCS-KNOWLEDGE / SCRATCH-ARCHIVE, and the derived rubric letter (A..E,
`registry.REPO_CLASSES`) that decides which Layer-3 dimension checks apply
to a given directory.

Two distinct vocabularies live here, on purpose:

  - `RepoClass` -- the five-value taxonomy `CLASSIFICATION.md`'s 2026-08-10
    audit assigned to every directory under `/Volumes/Dev/Sites`. Editable,
    human-facing, carried straight through into `cc conformance`'s per-repo
    report rows.
  - the rubric letter (a bare `str`, one of `registry.REPO_CLASSES` --
    `"A"`..`"E"`) -- `HARNESS-DESIGN.md` Layer 3's own evidence rule ("A =
    `source.path` with `role: foundation`; B = ... organization,
    department, personal; C = git root with a remote, not A/B; D =
    markdown-knowledge repo; E = not a git root, or an `_archive/`
    descendant, or scratch"). This is what a registered check's
    `applies_to_classes` set and `Registry.select(classes=...)` actually
    filter on (`registry.py`'s own module comment: "Kept here as plain
    strings rather than importing WP-4's `classes.py`").

The two are related by a fixed, small mapping (`rubric_letter` below), not
duplicated data: PRODUCT and SITE-CONTENT both mean "C" (a git root with a
remote, outside the four synced framework families); DOCS-KNOWLEDGE means
"D"; SCRATCH-ARCHIVE means "E"; COMPONENT means "A" or "B" depending on its
tier `role` -- except the one COMPONENT entry with no tier `role`
(`product-creation-copilot`, Q27), which is not a member of the inheritance
ladder at all and therefore also means "C" (the same "renders/supervises
but is a consumer" reasoning `copilot-control-tower` earned under Q9 --
see `classification.toml`'s own rationale for both entries).

**Classification is data, never a code edit** (`HARNESS-DESIGN.md` Layer
3): every real, already-audited directory has an explicit row in
`classification.toml` (seeded from `CLASSIFICATION.md`, corrected by the
owner's ratified Q9/Q27/Q2/Q20 answers -- see that file's header for the
full provenance). A directory `sweep.py` discovers that has NO row in the
table (e.g. something created on this machine after the audit) falls back
to `compute_default()` below -- a conservative, evidence-only guess (git
root -> PRODUCT/"C"; not a git root -> SCRATCH-ARCHIVE/"E") that
deliberately never invents a COMPONENT/A/B verdict, because doing so from
directory-name heuristics alone is exactly the "`-internal`/`test-pilot`
trap" the design spec warns against.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

import tomllib

from cc.core.conformance.registry import REPO_CLASSES

CLASSIFICATION_FILE_NAME = "classification.toml"

# `classes.py` lives at tools/cc/src/cc/core/conformance/classes.py;
# classification.toml lives at tools/cc/classification.toml (HARNESS-DESIGN.md
# section 8's file layout) -- four `.parent`s up from this file's directory.
_PACKAGE_TO_TOOLS_CC_DEPTH = 4


class RepoClass(StrEnum):
    """The five-value taxonomy `CLASSIFICATION.md` assigned to every
    directory under `/Volumes/Dev/Sites` -- literal string values match
    the audit's own class names exactly, including the hyphenated ones."""

    COMPONENT = "COMPONENT"
    PRODUCT = "PRODUCT"
    SITE_CONTENT = "SITE-CONTENT"
    DOCS_KNOWLEDGE = "DOCS-KNOWLEDGE"
    SCRATCH_ARCHIVE = "SCRATCH-ARCHIVE"


# The four tier roles a COMPONENT entry's `role` field may carry, and the
# rubric letter each maps to (`HARNESS-DESIGN.md`: "A = foundation; B =
# organization, department, personal").
_ROLE_TO_RUBRIC_LETTER: Mapping[str, str] = {
    "foundation": "A",
    "organization": "B",
    "department": "B",
    "personal": "B",
}

# Every non-COMPONENT taxonomy class maps to exactly one rubric letter.
_TAXONOMY_TO_RUBRIC_LETTER: Mapping[RepoClass, str] = {
    RepoClass.PRODUCT: "C",
    RepoClass.SITE_CONTENT: "C",
    RepoClass.DOCS_KNOWLEDGE: "D",
    RepoClass.SCRATCH_ARCHIVE: "E",
}

# The fallback rubric letter for a COMPONENT entry that carries no `role`
# (i.e. it is not a rung of one of the four synced framework families'
# tier ladder) -- `product-creation-copilot` today (Q27).
_ROLELESS_COMPONENT_RUBRIC_LETTER = "C"


class ClassificationError(ValueError):
    """A `classification.toml` row (or a value passed to `classify()`) is
    malformed: an unknown `class`, a `role` on a non-COMPONENT entry, or an
    unrecognized `role` value. Always raised eagerly -- a bad row must
    never silently degrade into a wrong verdict for the checks that
    depend on it."""


@dataclass(frozen=True)
class ClassificationEntry:
    """One directory's resolved classification.

    `key` is the portable, machine-independent lookup key
    (`"<group>/<name>"`, e.g. `"TSM/h3"`) -- never an absolute path, so the
    same `classification.toml` works whether the fleet root is mounted at
    `/Volumes/Dev/Sites` or its `/Users/pabs/Sites` symlink alias.

    `source` is `"override"` for a `classification.toml` row and
    `"computed-default"` for a directory the table has no row for
    (module docstring) -- callers (notably `sweep.py`'s per-repo report
    rows) surface this distinction rather than hiding it, so an
    unclassified new directory reads as "unclassified, using a
    conservative default" rather than as an audited call.
    """

    key: str
    repo_class: RepoClass
    rationale: str
    role: str | None = None
    source: str = "computed-default"

    def __post_init__(self) -> None:
        if not self.key:
            raise ClassificationError(
                "a ClassificationEntry must have a non-empty key."
            )
        if self.role is not None and self.repo_class is not RepoClass.COMPONENT:
            raise ClassificationError(
                f"{self.key!r}: `role` is only meaningful for class COMPONENT "
                f"entries (tier rungs of the four synced framework "
                f"families), not {self.repo_class.value!r}."
            )
        if self.role is not None and self.role not in _ROLE_TO_RUBRIC_LETTER:
            raise ClassificationError(
                f"{self.key!r}: unknown component role {self.role!r}; must be "
                f"one of {sorted(_ROLE_TO_RUBRIC_LETTER)!r}."
            )

    @property
    def rubric_letter(self) -> str:
        """The `registry.REPO_CLASSES` letter ("A".."E") this entry maps
        to -- what a check's `applies_to_classes` and
        `Registry.select(classes=...)` actually filter on."""

        if self.repo_class is RepoClass.COMPONENT:
            if self.role is None:
                return _ROLELESS_COMPONENT_RUBRIC_LETTER
            return _ROLE_TO_RUBRIC_LETTER[self.role]
        return _TAXONOMY_TO_RUBRIC_LETTER[self.repo_class]

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "key": self.key,
            "class": self.repo_class.value,
            "rubric_letter": self.rubric_letter,
            "rationale": self.rationale,
            "source": self.source,
        }
        if self.role is not None:
            result["role"] = self.role
        return result


def default_classification_path() -> Path:
    """`tools/cc/classification.toml` -- `HARNESS-DESIGN.md` section 8's
    file layout puts this beside `src/`, `tests/`, and `docs/`, not inside
    the `conformance/` package itself, so it is trivially discoverable and
    editable without touching code."""

    return (
        Path(__file__).resolve().parents[_PACKAGE_TO_TOOLS_CC_DEPTH]
        / CLASSIFICATION_FILE_NAME
    )


def _entry_from_row(row: Mapping[str, Any]) -> ClassificationEntry:
    try:
        key = str(row["path"])
        repo_class = RepoClass(row["class"])
    except KeyError as exc:
        raise ClassificationError(
            f"classification.toml row missing {exc}: {row!r}"
        ) from exc
    except ValueError as exc:
        raise ClassificationError(f"classification.toml row {row!r}: {exc}") from exc
    return ClassificationEntry(
        key=key,
        repo_class=repo_class,
        rationale=str(row.get("rationale", "")),
        role=row.get("role"),
        source="override",
    )


def load_classification_table(
    path: Path | None = None,
) -> dict[str, ClassificationEntry]:
    """Parse `classification.toml` into `{key: ClassificationEntry}`.

    Fail-open in the same spirit as `cc.core.ecosystem`'s readers (module
    docstrings across that package: "missing/corrupt degrades to empty,
    never raises") for the *file-level* failure modes -- a missing file
    returns an empty table (every repo then falls back to
    `compute_default()`) -- but a *row-level* malformed entry (unknown
    class, bad role) is a real authoring bug in a file this package owns
    and is raised immediately (`ClassificationError`), never silently
    dropped, so a typo in the audit table cannot quietly reclassify a
    repo's dimension applicability.
    """

    target = path or default_classification_path()
    try:
        raw = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}

    rows = raw.get("repos", [])
    if not isinstance(rows, list):
        raise ClassificationError(
            f"{target}: top-level `repos` must be an array of tables, got {type(rows)!r}."
        )

    table: dict[str, ClassificationEntry] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ClassificationError(
                f"{target}: every [[repos]] row must be a table, got {row!r}."
            )
        entry = _entry_from_row(row)
        if entry.key in table:
            raise ClassificationError(
                f"{target}: duplicate classification.toml entry for {entry.key!r}."
            )
        table[entry.key] = entry
    return table


def repo_key(path: Path, root: Path) -> str:
    """The portable `"<group>/<name>"` lookup key for `path`, relative to
    `root` (`sweep.py`'s discovery root, e.g. `/Volumes/Dev/Sites`). Falls
    back to the full relative-to-root path (POSIX-joined) for anything
    deeper than two levels -- `classification.toml` only ever seeds
    two-level entries today (`CLASSIFICATION.md`'s own scan depth), but a
    deeper future discovery still gets a stable, greppable key rather than
    an error."""

    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        # `path` is not under `root` at all (a caller error, or a symlink
        # that resolved outside the scanned tree) -- fall back to the
        # absolute path so the caller still gets a stable, if inelegant,
        # key instead of a crash.
        return path.as_posix()
    return relative.as_posix()


def compute_default(path: Path, *, is_git_root: bool) -> ClassificationEntry:
    """The conservative fallback for a directory `classification.toml` has
    no row for: a git root defaults to PRODUCT (rubric "C" -- "git root
    with a remote, not A/B"); anything else defaults to SCRATCH-ARCHIVE
    (rubric "E" -- "not a git root ... or scratch"). Never returns
    COMPONENT -- see module docstring's "`-internal`/`test-pilot` trap"
    note. `source="computed-default"` always, so callers can tell an
    audited call from a guess."""

    if is_git_root:
        return ClassificationEntry(
            key=path.as_posix(),
            repo_class=RepoClass.PRODUCT,
            rationale=(
                "computed default: git root with no classification.toml entry "
                "(not yet audited)."
            ),
            source="computed-default",
        )
    return ClassificationEntry(
        key=path.as_posix(),
        repo_class=RepoClass.SCRATCH_ARCHIVE,
        rationale=(
            "computed default: not a git root, no classification.toml entry "
            "(not yet audited)."
        ),
        source="computed-default",
    )


def classify(
    path: Path,
    *,
    root: Path,
    table: Mapping[str, ClassificationEntry],
    is_git_root: bool,
) -> ClassificationEntry:
    """Classify one discovered repo: `classification.toml` override first
    (looked up by `repo_key(path, root)`), `compute_default()` otherwise.
    This is the single function `sweep.py` calls per discovered repo."""

    key = repo_key(path, root)
    override = table.get(key)
    if override is not None:
        return override
    return compute_default(path, is_git_root=is_git_root)


__all__ = [
    "CLASSIFICATION_FILE_NAME",
    "ClassificationEntry",
    "ClassificationError",
    "RepoClass",
    "classify",
    "compute_default",
    "default_classification_path",
    "load_classification_table",
    "repo_key",
]

assert (
    set(_TAXONOMY_TO_RUBRIC_LETTER.values())
    | set(_ROLE_TO_RUBRIC_LETTER.values())
    | {_ROLELESS_COMPONENT_RUBRIC_LETTER}
    <= REPO_CLASSES
), "classes.py's rubric-letter mapping must stay inside registry.REPO_CLASSES"
