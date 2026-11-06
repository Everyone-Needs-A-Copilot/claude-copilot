"""Plan data model for `cc project migrate`."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Action kinds (what apply does)
DELETE = "delete"            # remove a regular file (content backed up)
UNLINK = "unlink"            # remove a symlink (target recorded)
EDIT_JSON = "edit-json"      # rewrite a JSON file (settings.json)
EDIT_TEXT = "edit-text"      # remove framework sections from CLAUDE.md / AGENTS.md
WRITE = "write"              # project-init writes (marker, thin sections, trust)


class MigrateError(Exception):
    """A clean, user-actionable migrate failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Item:
    path: str
    reason: str
    kind: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class MigrationPlan:
    project: str
    git: bool
    actions: list[Item] = field(default_factory=list)   # delete/unlink/edit/write
    keeps: list[Item] = field(default_factory=list)     # explicitly kept, with reason
    holds: list[Item] = field(default_factory=list)     # ambiguous or modified: kept, reported
    dirty: list[str] = field(default_factory=list)      # dirty paths overlapping the plan
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)     # planning errors: apply is refused
    staged: dict[str, str] = field(default_factory=dict, repr=False)  # path -> new text (not serialized)

    @property
    def refused(self) -> bool:
        return bool(self.dirty or self.errors)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for a in self.actions:
            out[a.kind] = out.get(a.kind, 0) + 1
        out["keep"] = len(self.keeps)
        out["hold"] = len(self.holds)
        out["dirty"] = len(self.dirty)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "git": self.git,
            "refused": self.refused,
            "counts": self.counts(),
            "actions": [asdict(a) for a in self.actions],
            "keeps": [asdict(a) for a in self.keeps],
            "holds": [asdict(a) for a in self.holds],
            "dirty": list(self.dirty),
            "notes": list(self.notes),
            "errors": list(self.errors),
        }
