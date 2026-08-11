"""Check registration and discovery.

Every check gets registered exactly once, by id, with the metadata
`HARNESS-DESIGN.md` §3.3 specifies: `{id, layer, severity, applies_to_classes,
mode(fast|full), summary, remediation}`. This module owns that registry and
nothing else — it does not run checks, and it does not know what a "tier" or
a "repo" is. Layers 1-6 (`tier.py`, `stack.py`, `sweep.py`+`dimensions/`,
`lock.py`, `roundtrip.py`, `root_causes.py`) import `register_check` and call
it once per check id at import time (module-level, mirroring how Typer
commands register themselves); this module's job is to make that
registration collision-safe and queryable.

`cc conformance explain <id>` (WP-8) prints a `CheckRegistration` record
plus the last observed evidence — this module supplies the record.

ID scheme (`HARNESS-DESIGN.md` §3.3): `<layer>.<area>.<name>`, e.g.
`tier.precedence.nearest_wins`, or the shorter `<area>.<name>` used by the
Layer-6 invariants (`inv.no_bare_cli_name`). Both are two-or-more
dot-separated lowercase identifier segments; `_ID_PATTERN` enforces that
shape and `Registry.register` raises on both a malformed id and a duplicate
one, so a collision is caught the moment the offending module is imported —
never silently at report time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from cc.core.conformance.types import (
    CheckResult,
    Evidence,
    ExpectedToday,
    Layer,
    Mode,
    Scope,
    Severity,
)

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

# The closed set of repo classification letters a check's `applies_to_classes`
# may name (`HARNESS-DESIGN.md` §4 Layer 3: "A = foundation ... E = not a git
# root, or an _archive/ descendant, or scratch"). Kept here as plain strings
# rather than importing WP-4's `classes.py` (which does not exist yet and
# must not be created by this package) — the registry only needs to validate
# the closed vocabulary, not compute class membership.
REPO_CLASSES: frozenset[str] = frozenset({"A", "B", "C", "D", "E"})


class CheckRegistrationError(ValueError):
    """A check tried to register with a malformed id, a duplicate id, or an
    invalid `applies_to_classes` entry. Always raised at registration time
    (i.e. at import time for a module-level `register_check(...)` call),
    never deferred to report time."""


@dataclass(frozen=True)
class CheckRegistration:
    """The declared, immutable metadata for one check id.

    `summary` is the assertion statement ("what this check asserts") that
    `CheckResult.assertion` is expected to carry through to every result
    this check produces — `result()` below copies it automatically so a
    check body never has to repeat it.

    `expected_today` is the DEFAULT expected-today verdict for this check.
    Most checks are uniform (e.g. every RC regression pin is
    `ExpectedToday.FAIL` today); a few vary per subject (e.g. CS-ANCESTOR
    passes for `cli-foundation`/`knowledge-foundation` but fails for
    `claude-foundation`/`codex-foundation` — see `TEST-MATRIX.md` §2). For
    those, pass an explicit `expected_today=` to `result()` per subject;
    the registration's own value is only the fallback.
    """

    id: str
    layer: Layer
    severity: Severity
    scope: Scope
    summary: str
    remediation: str
    mode: Mode = Mode.FAST
    applies_to_classes: frozenset[str] = field(default_factory=frozenset)
    expected_today: ExpectedToday = ExpectedToday.PASS
    requires_network: bool = False

    def __post_init__(self) -> None:
        if not _ID_PATTERN.fullmatch(self.id):
            raise CheckRegistrationError(
                f"invalid check id {self.id!r}: must be two or more "
                "lowercase, dot-separated identifier segments, e.g. "
                "'tier.precedence.nearest_wins' or 'inv.no_bare_cli_name'."
            )
        if not self.summary:
            raise CheckRegistrationError(
                f"check {self.id!r} has no summary (assertion statement) — "
                "every check must state what it asserts."
            )
        if not self.remediation:
            raise CheckRegistrationError(
                f"check {self.id!r} has no remediation string — a check may "
                "never fail without telling the operator how to fix it "
                "(HARNESS-DESIGN.md §13 test_every_check_has_severity_and_remediation)."
            )
        unknown_classes = self.applies_to_classes - REPO_CLASSES
        if unknown_classes:
            raise CheckRegistrationError(
                f"check {self.id!r} declares unknown repo class(es) "
                f"{sorted(unknown_classes)!r}; must be a subset of "
                f"{sorted(REPO_CLASSES)!r}."
            )

    def result(
        self,
        *,
        subject: str,
        verdict: "Any",
        evidence: Iterable[Evidence] = (),
        detail: str = "",
        expected_today: ExpectedToday | None = None,
        root_cause: str | None = None,
    ) -> CheckResult:
        """Build a `CheckResult` for this check, filling in every field the
        registration already knows (`id`, `layer`, `severity`, `scope`,
        `assertion`, `remediation`) so a check body only ever supplies the
        runtime-varying facts."""

        return CheckResult(
            id=self.id,
            layer=self.layer,
            severity=self.severity,
            scope=self.scope,
            subject=subject,
            assertion=self.summary,
            verdict=verdict,
            expected_today=expected_today
            if expected_today is not None
            else self.expected_today,
            evidence=tuple(evidence),
            detail=detail,
            remediation=self.remediation,
            root_cause=root_cause,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "layer": self.layer.value,
            "severity": self.severity.value,
            "scope": self.scope.value,
            "summary": self.summary,
            "remediation": self.remediation,
            "mode": self.mode.value,
            "applies_to_classes": sorted(self.applies_to_classes),
            "expected_today": self.expected_today.value,
            "requires_network": self.requires_network,
        }


class Registry:
    """A collision-checked collection of `CheckRegistration`s.

    Production check modules register into the process-wide `DEFAULT_REGISTRY`
    (via the module-level `register_check()` convenience below). Tests that
    want to exercise registration behavior (including collision detection)
    without polluting global state should construct their own `Registry()`
    instance instead — this is the isolation seam, not an env var or a
    reset function.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, CheckRegistration] = {}

    def register(self, registration: CheckRegistration) -> CheckRegistration:
        if registration.id in self._by_id:
            raise CheckRegistrationError(
                f"duplicate check id {registration.id!r}: already registered "
                f"by {self._by_id[registration.id].layer.value} layer. Check "
                "ids must be stable and globally unique — rename one of them."
            )
        self._by_id[registration.id] = registration
        return registration

    def get(self, check_id: str) -> CheckRegistration:
        try:
            return self._by_id[check_id]
        except KeyError as exc:
            raise KeyError(f"no check registered with id {check_id!r}") from exc

    def __contains__(self, check_id: str) -> bool:
        return check_id in self._by_id

    def __len__(self) -> int:
        return len(self._by_id)

    def all(self) -> tuple[CheckRegistration, ...]:
        return tuple(self._by_id.values())

    def select(
        self,
        *,
        layers: Iterable[Layer | str] | None = None,
        modes: Iterable[Mode | str] | None = None,
        check_ids: Iterable[str] | None = None,
        classes: Iterable[str] | None = None,
    ) -> tuple[CheckRegistration, ...]:
        """Filter registrations for `--layer`, `--full`/`--fast` (`modes`),
        `--check`, and `--class`. `--repo` and `--fail-on` are NOT registry
        concerns — they filter already-computed `CheckResult`s (post-hoc, by
        `subject` and `severity` respectively) and live in `report.py`."""

        layer_set = (
            {Layer(layer) for layer in layers} if layers is not None else None
        )
        mode_set = {Mode(mode) for mode in modes} if modes is not None else None
        id_set = set(check_ids) if check_ids is not None else None
        class_set = set(classes) if classes is not None else None

        selected = []
        for registration in self._by_id.values():
            if layer_set is not None and registration.layer not in layer_set:
                continue
            if mode_set is not None and registration.mode not in mode_set:
                continue
            if id_set is not None and registration.id not in id_set:
                continue
            if class_set is not None and registration.applies_to_classes and not (
                registration.applies_to_classes & class_set
            ):
                continue
            selected.append(registration)
        return tuple(selected)


# The process-wide registry every production check module registers into.
DEFAULT_REGISTRY = Registry()


def register_check(
    *,
    id: str,  # noqa: A002 - matches the design's own field name ("id")
    layer: Layer | str,
    severity: Severity | str,
    scope: Scope | str,
    summary: str,
    remediation: str,
    mode: Mode | str = Mode.FAST,
    applies_to_classes: Iterable[str] = (),
    expected_today: ExpectedToday | str = ExpectedToday.PASS,
    requires_network: bool = False,
    registry: Registry = DEFAULT_REGISTRY,
) -> CheckRegistration:
    """Build a `CheckRegistration` and register it in one call — the normal
    entry point for a check module. Returns the registration so the caller
    can hold onto it and call `.result(...)` when the check actually runs."""

    registration = CheckRegistration(
        id=id,
        layer=Layer(layer),
        severity=Severity(severity),
        scope=Scope(scope),
        summary=summary,
        remediation=remediation,
        mode=Mode(mode),
        applies_to_classes=frozenset(applies_to_classes),
        expected_today=ExpectedToday(expected_today),
        requires_network=requires_network,
    )
    return registry.register(registration)


def collision_report(registry: Registry = DEFAULT_REGISTRY) -> Mapping[str, int]:
    """A trivial diagnostic: id -> 1 for every registered check (a real
    collision cannot exist in a live registry — `register()` already raises
    on one — so this exists mainly so tests and `cc conformance list` can
    assert `len(collision_report()) == len(registry)` as a sanity check that
    nothing bypassed `register()`)."""

    return {registration.id: 1 for registration in registry.all()}


__all__ = [
    "CheckRegistration",
    "CheckRegistrationError",
    "DEFAULT_REGISTRY",
    "REPO_CLASSES",
    "Registry",
    "collision_report",
    "register_check",
]
