"""D8 — Tier / layer participation (CLI Copilot).

`RUBRIC.md` §D8 / `HARNESS-DESIGN.md` §4 Layer 3 (`repo.d08.tier_participation`,
S1, fast, "Class A/B only; NA for C/D/E"):

  PRESENT (class A/B) — the repo's absolute path appears as `source.path`
  for a layer in `copilot.layers.yml`, with a resolvable `source.repo`, a
  `ref`, a non-empty `auth`, and — for foundation layers — a non-empty
  `policy.allowed_signers`.
  PARTIAL/ABSENT (class A/B) — layer entry missing, or present but missing
  a required field.
  N/A (class C/D/E) — "the correct verdict is 'N/A — consumer, not a
  layer.' A consumer repo participates in the ecosystem through D1/D2/D3
  ... Marking a product repo 'missing tier membership' is a category error
  the CSE doc exists to prevent" (RUBRIC.md §D8).

Per the task brief's own ratified decision (owner Q9): `copilot-control-
tower` is class C (a consumer), absent from all 16 `copilot.layers.yml`
entries by design — so it must score N/A here, never FAIL. This module
implements that explicitly: `types.Verdict.SKIP` is the harness's
dedicated "not applicable" answer (`types.py`: "D8 tier participation is
NA/SKIP for class C/D/E repos by design, never silently omitted"), and this
check ALWAYS returns a result (never omits the repo from the sweep) so the
N/A is a recorded, visible fact rather than a silent absence.

Wraps `cc.core.ecosystem.manifest.load_layers`/`validate_layers` — the real
manifest parser — rather than re-parsing `copilot.layers.yml` by hand
(Rule 1, `HARNESS-DESIGN.md` §3.2: "a check never computes ecosystem state
it can ask cc for"). A malformed manifest is `COULD_NOT_RUN`, never a
fabricated `PASS`/`FAIL` (`inv.no_fabricated_healthy`).

No git access — this dimension only reads the manifest file and compares
filesystem paths.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

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
from cc.core.ecosystem.manifest import ManifestError, load_layers, validate_layers

if TYPE_CHECKING:
    from cc.core.conformance.dimensions import RepoContext

# The rubric's own closed vocabulary (`HARNESS-DESIGN.md` §4 Layer 3: "Class
# assignment ... A = source.path with role: foundation; B = ... {organization,
# department, personal} ... never NA for A/B; N/A for C/D/E").
_TIER_PARTICIPATING_CLASSES: frozenset[str] = frozenset({"A", "B"})

_D08_REGISTRATION = register_check(
    id="repo.d08.tier_participation",
    layer=Layer.REPO,
    severity=Severity.S1,
    scope=Scope.PER_REPO,
    summary=(
        "For class A/B repos: the repo's path appears as `source.path` in "
        "`copilot.layers.yml` with a resolvable `source.repo`, `ref`, "
        "`auth`, and (for foundation layers) a non-empty "
        "`policy.allowed_signers`. For class C/D/E: explicitly N/A — a "
        "consumer repo participates through D1/D2/D3, never through the "
        "layer manifest."
    ),
    remediation=(
        "Class A/B: add a `layers[]` entry to `copilot.layers.yml` with "
        "`source.path`/`source.repo`/`source.ref`, a non-empty `auth`, and "
        "(for foundation layers) a non-empty `policy.allowed_signers`. "
        "Class C/D/E: do not add one — per the CSE model, layers carry the "
        "tools, never the products built with them."
    ),
    mode=Mode.FAST,
    applies_to_classes=("A", "B", "C", "D", "E"),
    expected_today=ExpectedToday.PASS,
)


def _matching_layer(
    layers: list[dict[str, Any]], repo: Path
) -> dict[str, Any] | None:
    resolved_repo = repo.resolve()
    for layer in layers:
        source = layer.get("source")
        if not isinstance(source, dict):
            continue
        raw_path = source.get("path")
        if not raw_path:
            continue
        try:
            if Path(raw_path).expanduser().resolve() == resolved_repo:
                return layer
        except OSError:
            continue
    return None


def check_d08_tier_participation(
    repo: Path,
    *,
    repo_class: str,
    manifest_path: Path,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    """Pure function of `(repo, repo_class, manifest_path)` to a
    `CheckResult`. `repo_class` is supplied by the caller (Layer 3's
    class-assignment pass, `classes.py` — owned by WP-4, not yet built) —
    this module does not compute repo class itself."""

    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)

    if repo_class not in _TIER_PARTICIPATING_CLASSES:
        return _D08_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.SKIP,
            detail=(
                f"N/A — class {repo_class} is a consumer, not a layer "
                "(RUBRIC.md D8: layers carry the tools, never the products)."
            ),
            expected_today=expected_today,
        )

    try:
        layers = validate_layers(load_layers(Path(manifest_path)))
    except ManifestError as exc:
        return _D08_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.COULD_NOT_RUN,
            detail=f"could not load/validate {manifest_path}: {exc}",
            expected_today=expected_today,
        )

    layer = _matching_layer(layers, repo)
    evidence: list[Evidence] = []

    if layer is None:
        evidence.append(
            Evidence(
                kind="tier-layer-entry",
                path=str(manifest_path),
                expected=f"a `layers[]` entry with source.path == {repo}",
                actual="no matching layer entry",
                detail=(
                    f"class {repo_class} is structurally a tier variant but "
                    "has no layer entry — RUBRIC.md D8 ABSENT."
                ),
            )
        )
        return _D08_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.FAIL,
            evidence=tuple(evidence),
            detail="no layer entry for this repo.",
            expected_today=expected_today,
        )

    layer_id = layer.get("id", "<unnamed layer>")
    source = layer.get("source") if isinstance(layer.get("source"), dict) else {}

    if not source.get("repo"):
        evidence.append(
            Evidence(
                kind="tier-layer-source-repo",
                path=str(manifest_path),
                expected=f"layers[id={layer_id!r}].source.repo set",
                actual=repr(source.get("repo")),
            )
        )
    if not source.get("ref"):
        evidence.append(
            Evidence(
                kind="tier-layer-source-ref",
                path=str(manifest_path),
                expected=f"layers[id={layer_id!r}].source.ref set",
                actual=repr(source.get("ref")),
            )
        )
    if not layer.get("auth"):
        evidence.append(
            Evidence(
                kind="tier-layer-auth",
                path=str(manifest_path),
                expected=f"layers[id={layer_id!r}].auth set",
                actual=repr(layer.get("auth")),
            )
        )

    if layer.get("role") == "foundation":
        policy = layer.get("policy") if isinstance(layer.get("policy"), dict) else {}
        allowed_signers = policy.get("allowed_signers")
        if not allowed_signers:
            evidence.append(
                Evidence(
                    kind="tier-layer-foundation-signers",
                    path=str(manifest_path),
                    expected=f"layers[id={layer_id!r}].policy.allowed_signers non-empty",
                    actual=repr(allowed_signers),
                    detail="a foundation layer with no compiled-in trust root.",
                )
            )

    verdict = Verdict.FAIL if evidence else Verdict.PASS
    detail = (
        f"layer id={layer_id!r}"
        if verdict is Verdict.PASS
        else f"layer id={layer_id!r}: {len(evidence)} violation(s)."
    )
    return _D08_REGISTRATION.result(
        subject=subject_name,
        verdict=verdict,
        evidence=tuple(evidence),
        detail=detail,
        expected_today=expected_today,
    )


def run(context: "RepoContext") -> Iterable[CheckResult]:
    """The `dimensions/__init__.py` module contract's required entry
    point: exactly one `CheckResult` for `repo.d08.tier_participation`,
    for every repo. Class C/D/E's `Verdict.SKIP` is produced by
    `check_d08_tier_participation` itself (it needs no manifest at all for
    that branch); class A/B resolves the machine's configured layer
    manifest via `layers.manifest` (`cc.core.config.resolve_key` -- the
    same config cascade `cc env`/`cc doctor` already read, never a
    re-parse of anything this module owns) rather than requiring
    `RepoContext` to carry a manifest path of its own."""

    if context.rubric_class not in _TIER_PARTICIPATING_CLASSES:
        return (
            check_d08_tier_participation(
                context.path,
                repo_class=context.rubric_class,
                manifest_path=Path(),  # unused on the SKIP branch
                subject=context.subject,
            ),
        )

    manifest_path = resolve_key("layers.manifest")
    if not manifest_path:
        return (
            _D08_REGISTRATION.result(
                subject=context.subject,
                verdict=Verdict.COULD_NOT_RUN,
                detail=(
                    "no `layers.manifest` configured on this machine -- "
                    "cannot evaluate D8 for a class "
                    f"{context.rubric_class} repo."
                ),
            ),
        )
    return (
        check_d08_tier_participation(
            context.path,
            repo_class=context.rubric_class,
            manifest_path=Path(manifest_path),
            subject=context.subject,
        ),
    )


__all__ = [
    "check_d08_tier_participation",
    "run",
]
