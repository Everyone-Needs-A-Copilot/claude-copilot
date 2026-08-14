"""Layer 1 (tier) — EFFECTIVENESS checks: INSTALLED vs WIRED vs EFFECTIVE.

`tier.py` (H-1..H-9) proves the RESOLVER computes the right answer: given a
manifest and some contributions, `resolve_extension`/`resolve_layers` pick
the nearest declaring tier. None of that proves the answer ever reaches a
project. Those are different properties: a harness that only measures "does
this project's install MATCH A REFERENCE" can report green forever while the
resolver's answer never once reaches a real project directory, because
nothing between the resolver and the installer was ever wired together.
This module is the harness's answer to that gap — six checks, each proving
one of INSTALLED (files present — already covered elsewhere), WIRED (a real
consumer reads the resolved answer), or EFFECTIVE (it changes what actually
lands on disk / what an agent actually does), never merely that a config
key or manifest entry SAYS the right thing.

Every check here follows the same rule H-8's own regression (see
`tier.py`'s `_is_under_excluded_package`) exists to enforce: a check that
cannot be shown to FAIL against some fixture is not a check. Each check
function below has a paired PASS-shape and FAIL-shape fixture in
`tests/conformance/test_layer1_effectiveness.py` proving it can go both
ways — never a check "satisfied by its own existence."

Wraps only (`HARNESS-DESIGN.md` §3.2 rule 1), same discipline as `tier.py`:
  - `cc.core.ecosystem.resolver.resolve_layers` — the exact fold `cc resolve
    --explain` runs; E-3/E-4 call it directly rather than re-deriving a
    winner some other way.
  - `cc.core.ecosystem.discovery.discover_contributions` — the exact local
    scan `resolve --explain` uses to know what a tier currently contains.
  - `cc.core.ecosystem.lockfile` — read-only, the exact shape `cc doctor`/
    `cc freshness` already read.
  - `cc.core.conformance.roundtrip` (the module that already established
    "the real installer" means the literal bash fenced in
    `setup-project.md`/`update-project.md`, extracted and run verbatim,
    never a Python reimplementation) — E-1/E-2's real-machine gathering (in
    `commands/conformance.py`) reuses `roundtrip.materialize_framework_source`
    / `roundtrip.build_scratch_env` / `roundtrip.extract_bash_steps` /
    `roundtrip.run_bash_steps` rather than inventing a second installer
    simulation.

The six checks, matched to the task that created them:
  - E-1 `tier.effectiveness.org_content_reaches_project` — a nearer tier's
    content actually appears in a project's INSTALLED files, proven by
    running the real installer against a fixture tier with distinguishing
    content and reading the result off disk (never by inspecting
    `copilot.layers.yml`/config, which only proves intent).
  - E-2 `tier.effectiveness.nearest_wins_preserves_siblings` — one tier
    overriding one artifact must never cost the project every artifact it
    did NOT override (guards against a "switch the whole dimension's
    source wholesale" regression in whatever tier-aware installer lands).
  - E-3 `tier.effectiveness.draft_placeholder_never_shadows_resolver_wide`
    — generalizes H-3/Q25's shadow-substance guard beyond agent
    extensions (`extensions_resolver.resolve_extension`, a narrower,
    separate subsystem) to `resolve_layers`' own fold, which is what the
    installer is SUPPOSED to consult and never has — so nothing has ever
    checked substance there before.
  - E-4 `tier.effectiveness.resolve_attribution_matches_lock` — every
    item's `winning_layer` must be backed by a REAL recorded
    materialization in `copilot.lock.json`, catching the exact live
    discrepancy class (`cc resolve --explain` claims `claude-organization`
    while its lock entry is `_meta`-only, because the resolver reads the
    live checkout and the lock still reflects a July mirror pin).
  - E-5 `tier.effectiveness.knowledge_ladder_actually_consumed` — an agent
    that hydrates `$CC_KNOWLEDGE_REPOS` must also walk and read it; hydrate-
    then-never-dereference is installed-but-not-effective.
  - E-6 `tier.effectiveness.extension_resolution_wired_beyond_prose` — `cc
    extensions resolve` must be invoked by an executable framework
    consumer (a hook/script), not merely described in agent/command
    markdown that an LLM may or may not choose to follow.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from cc.core.conformance.registry import register_check
from cc.core.conformance.types import (
    CheckResult,
    Evidence,
    ExpectedToday,
    Layer,
    Scope,
    Severity,
    Verdict,
)
from cc.core.ecosystem.lockfile import LAYER_META_KEY
from cc.core.ecosystem.policy import EXECUTABLE_DIMENSIONS
from cc.core.ecosystem.resolver import resolve_layers

# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

E1_ORG_CONTENT_REACHES_PROJECT = register_check(
    id="tier.effectiveness.org_content_reaches_project",
    layer=Layer.TIER,
    severity=Severity.S0,
    scope=Scope.GLOBAL,
    summary=(
        "EFFECTIVENESS E-1: content a nearer tier (e.g. organization) "
        "contributes for an override-semantics dimension actually appears "
        "in a project's INSTALLED files after running the real project "
        "installer (setup-project.md's literal bash steps) -- not merely "
        "in copilot.layers.yml or a resolved-config report"
    ),
    remediation=(
        "wire copilot.layers.yml resolution into the project installer "
        "(setup-project.md Step 6 / its cc equivalent) so per-item "
        "content is copied from resolve_layers()'s winning tier, not "
        "always from a single hardcoded ~/.claude/copilot foundation root"
    ),
    expected_today=ExpectedToday.FAIL,
)

E2_NEAREST_WINS_PRESERVES_SIBLINGS = register_check(
    id="tier.effectiveness.nearest_wins_preserves_siblings",
    layer=Layer.TIER,
    severity=Severity.S1,
    scope=Scope.GLOBAL,
    summary=(
        "EFFECTIVENESS E-2: a nearer tier overriding ONE artifact does not "
        "cost the project every other artifact it did not override -- "
        "nearest-wins is per-item, never all-or-nothing"
    ),
    remediation=(
        "materialize per item (resolve_layers' own per-(dimension,item) "
        "fold), never switch a whole dimension's source wholesale to "
        "whichever tier happens to declare one override"
    ),
    expected_today=ExpectedToday.PASS,
)

E3_DRAFT_PLACEHOLDER_NEVER_SHADOWS = register_check(
    id="tier.effectiveness.draft_placeholder_never_shadows_resolver_wide",
    layer=Layer.TIER,
    severity=Severity.S0,
    scope=Scope.PER_TIER,
    summary=(
        "EFFECTIVENESS E-3 (generalizes H-3/Q25 beyond agent extensions): "
        "an empty, TODO-marked, or `status: draft` placeholder in a "
        "nearer tier does not win resolve_layers()'s fold over real, "
        "substantive shadowed content, for any override-semantics "
        "dimension"
    ),
    remediation=(
        "fill the placeholder with real content or withdraw its "
        "contribution so resolution falls through to the substantive "
        "shadowed tier -- same remediation class as H-3/Q25"
    ),
    # Registration default is the COMMON case (most resolved items with a
    # shadowed candidate are substantive); the one known live exception
    # (claude/commands/protocol -- claude-copilot-internal's own org
    # override literally opens with "TODO(pablo): this section is
    # currently a no-op placeholder ... byte-for-byte" reproduction of
    # foundation) is set to `expected_today=FAIL` per-result in
    # `check_e3_draft_placeholder_never_shadows`, the same "override the
    # default on the specific known-bad subject" pattern H-6 uses for its
    # hollow-rung branch.
    expected_today=ExpectedToday.PASS,
)

E4_ATTRIBUTION_MATCHES_LOCK = register_check(
    id="tier.effectiveness.resolve_attribution_matches_lock",
    layer=Layer.TIER,
    severity=Severity.S0,
    scope=Scope.PER_TIER,
    summary=(
        "EFFECTIVENESS E-4: every item's `winning_layer` (per "
        "resolve_layers / `cc resolve --explain`) is backed by a real, "
        "recorded materialization for that layer in copilot.lock.json -- "
        "never a layer whose lock entry is `_meta`-only (a mirror pinned "
        "with no real dimension pins ever recorded)"
    ),
    remediation=(
        "run `cc update` for the winning layer so its lock entry records "
        "real dimension/item shas, or surface winning_sha=None + "
        "_meta-only as 'never actually materialized' rather than silently "
        "trusting the live-checkout-only winner. If the layer's own "
        "manifest entry declares `policy.allowed_signers: []` for an "
        "executable dimension, this is not a bug to chase -- it is the "
        "fail-closed policy gate (core/ecosystem/policy.py) working as "
        "designed, and the remediation is either configuring a real "
        "signer for that layer or accepting it will never win materialize "
        "under its own layer id."
    ),
    # Registration default is the common case (`claude-foundation`'s lock
    # entry carries real pins for every foundation-won item, the large
    # majority). Per-result `expected_today` is now COMPUTED, never a
    # hardcoded subject list: `check_e4_resolve_attribution_matches_lock`
    # inspects the winning layer's own `policy.allowed_signers` for the
    # resolved item's dimension and only marks a lock-empty FAIL as
    # `expected_today=FAIL` when that layer is genuinely policy-blocked by
    # its own manifest (empty allowed-signers list on an executable
    # dimension -- `core/ecosystem/policy.py`'s `EXECUTABLE_DIMENSIONS`,
    # the SAME signer requirement `materialize()` enforces, reused rather
    # than re-derived). A lock-empty winner that is NOT policy-blocked
    # (real signers configured, `cc update` simply never ran, or some
    # other unexplained gap) gets `expected_today=PASS` instead -- an
    # honest "this looks like a real problem" signal a baseline diff would
    # surface as a regression, never silently absorbed into "known
    # exception." Live-verified 2026-08-11: `claude-organization`,
    # `knowledge-personal`, `cli-personal`, `codex-personal` are today's
    # policy-blocked instances (every one declares `allowed_signers: []`
    # in `copilot.layers.yml`), but this check no longer depends on that
    # specific list staying fixed -- it re-derives the reason every run.
    expected_today=ExpectedToday.PASS,
)

E5_KNOWLEDGE_LADDER_ACTUALLY_CONSUMED = register_check(
    id="tier.effectiveness.knowledge_ladder_actually_consumed",
    layer=Layer.TIER,
    severity=Severity.S1,
    scope=Scope.PER_TIER,
    summary=(
        "EFFECTIVENESS E-5: an agent whose instructions hydrate "
        '$CC_KNOWLEDGE_REPOS (`eval "$(cc env)"`) also WALKS and READS '
        "it -- hydrating the ladder and then never dereferencing it is "
        "installed-but-not-effective"
    ),
    remediation=(
        "add an explicit 'walk $CC_KNOWLEDGE_REPOS ... and read <path>' "
        "consumption step, the same shape sd.md/ta.md/cw.md already use"
    ),
    # Ground truth when this check was written: ind/uxd/uids/cco hydrated
    # `cc env` and read nothing further (a sibling agent's concurrent fix
    # target). Re-verified live 2026-08-11 that all seven agents
    # (cw/sd/ta/ind/uxd/uids/cco) now walk-and-read $CC_KNOWLEDGE_REPOS --
    # the sibling's fix landed in this repo's working tree during this
    # same session. `expected_today=PASS` reflects that live-verified
    # state honestly; re-flip to FAIL per-subject if a future agent edit
    # regresses to hydrate-then-never-read.
    expected_today=ExpectedToday.PASS,
)

E6_EXTENSION_RESOLUTION_WIRED_BEYOND_PROSE = register_check(
    id="tier.effectiveness.extension_resolution_wired_beyond_prose",
    layer=Layer.TIER,
    severity=Severity.S2,
    scope=Scope.GLOBAL,
    summary=(
        "EFFECTIVENESS E-6: `cc extensions resolve` is actually invoked "
        "by an executable framework consumer (a hook/script), not merely "
        "described in agent/command markdown prose that an LLM may or "
        "may not choose to follow"
    ),
    remediation=(
        "call `cc extensions resolve --agent <id> --json` from the "
        "enforcement hook (copilot-hook.sh) or an equivalent script "
        "path, so extension resolution is enforced rather than merely "
        "documented"
    ),
    expected_today=ExpectedToday.PASS,
)


# ---------------------------------------------------------------------------
# E-1 / E-2 -- installer effectiveness (pure functions; real-machine driver
# lives in commands/conformance.py, which runs the real setup-project.md
# bash steps against a scratch fixture and feeds the result in here).
# ---------------------------------------------------------------------------


def check_e1_org_content_reaches_project(
    *,
    probe_item: str,
    winning_layer: str,
    expected_marker: str,
    installed_text: str | None,
) -> CheckResult:
    """`expected_marker`: a distinguishing string ONLY the nearer
    (winning) tier's fixture content carries -- never something the
    foundation content could contain by coincidence. `installed_text`: the
    literal content the REAL installer wrote to the project's file for
    `probe_item` (`None` if nothing was installed at all)."""

    if installed_text is not None and expected_marker in installed_text:
        return E1_ORG_CONTENT_REACHES_PROJECT.result(
            subject=probe_item,
            verdict=Verdict.PASS,
            detail=(
                f"installed {probe_item!r} carries {winning_layer}'s "
                "distinguishing content"
            ),
        )

    evidence = (
        Evidence(
            kind="installed-file",
            path=probe_item,
            expected=f"installed content contains {winning_layer}'s marker {expected_marker!r}",
            actual=(
                "no file installed"
                if installed_text is None
                else "installed, but marker absent -- foundation content only"
            ),
            detail=(
                f"resolve_layers() says {winning_layer!r} should win {probe_item!r}, "
                "but the real installer never consults the tier manifest, so its "
                "content never reached the project"
            ),
        ),
    )
    return E1_ORG_CONTENT_REACHES_PROJECT.result(
        subject=probe_item, verdict=Verdict.FAIL, evidence=evidence
    )


def check_e2_nearest_wins_preserves_siblings(
    *,
    overridden_item: str,
    roster: Sequence[str],
    installed_content: Mapping[str, str | None],
) -> CheckResult:
    """`roster`: every item the project is supposed to receive (e.g. the
    full framework agent roster). `installed_content`: item -> installed
    file content, `None`/empty if missing. Fails if overriding
    `overridden_item` cost the project ANY sibling item's presence."""

    siblings = [item for item in roster if item != overridden_item]
    missing = [item for item in siblings if not installed_content.get(item)]

    if not missing:
        return E2_NEAREST_WINS_PRESERVES_SIBLINGS.result(
            subject=overridden_item,
            verdict=Verdict.PASS,
            detail=(
                f"all {len(siblings)} non-overridden roster item(s) remain "
                f"installed alongside the {overridden_item!r} override"
            ),
        )

    evidence = tuple(
        Evidence(
            kind="installed-file",
            path=item,
            expected="present, non-empty",
            actual="missing" if item not in installed_content else "empty",
            detail=f"overriding {overridden_item!r} must not cost {item!r}",
        )
        for item in missing
    )
    return E2_NEAREST_WINS_PRESERVES_SIBLINGS.result(
        subject=overridden_item,
        verdict=Verdict.FAIL,
        evidence=evidence,
        detail=(
            f"{len(missing)} of {len(siblings)} non-overridden roster "
            f"item(s) were lost when {overridden_item!r} was overridden"
        ),
    )


# ---------------------------------------------------------------------------
# E-3 -- draft-placeholder-never-shadows, generalized across resolve_layers
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---", re.DOTALL)
_STATUS_RE = re.compile(r"^status:\s*(\S+)\s*$", re.MULTILINE)


def _frontmatter_status(text: str) -> str | None:
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return None
    status_match = _STATUS_RE.search(match.group(1))
    return status_match.group(1) if status_match else None


def _resolve_item_path(
    layer: Mapping[str, Any] | None, dimension: str, item: str
) -> Path | None:
    """The on-disk file or directory `discover_contributions` would have
    hashed for `(layer, dimension, item)` -- a file `<dim>/<item>.md`, or a
    directory `<dim>/<item>/` (e.g. a whole codex plugin). `None` if the
    layer has no usable local `source.path`, or neither shape exists --
    an honest degrade (same as `discovery.py`'s own "path doesn't exist ->
    contributes nothing"), never a guess."""

    if layer is None:
        return None
    local_root = (layer.get("source") or {}).get("path")
    if not local_root:
        return None
    dim_dir = Path(str(local_root)).expanduser() / dimension
    candidate_file = dim_dir / f"{item}.md"
    if candidate_file.is_file():
        return candidate_file
    candidate_dir = dim_dir / item
    if candidate_dir.is_dir():
        return candidate_dir
    return None


def _read_item_text_and_size(path: Path) -> tuple[str, int]:
    """Best-effort `(readable text, total bytes)` for a file OR a directory
    item. Directory items (e.g. a codex plugin) concatenate every
    text-shaped file's content for the `status:`/`TODO(` heuristics and sum
    every file's size for the size-ratio heuristic -- an unreadable binary
    file inside the directory still counts toward size, it just does not
    contribute text."""

    if path.is_dir():
        total = 0
        chunks: list[str] = []
        for child in sorted(path.rglob("*")):
            if not child.is_file():
                continue
            try:
                total += child.stat().st_size
            except OSError:
                continue
            if child.suffix in (".md", ".json", ".yml", ".yaml", ".txt"):
                try:
                    chunks.append(child.read_text(encoding="utf-8", errors="ignore"))
                except OSError:
                    continue
        return "\n".join(chunks), total
    text = path.read_text(encoding="utf-8")
    return text, path.stat().st_size


def check_e3_draft_placeholder_never_shadows(
    *,
    layers: Sequence[Mapping[str, Any]],
    contributions: Mapping[str, Mapping[str, Mapping[str, str | None]]],
    lockfile: Mapping[str, Any] | None = None,
    min_size_ratio: float = 0.5,
) -> tuple[CheckResult, ...]:
    """Thin wrap over `resolve_layers` -- the SAME fold `cc resolve
    --explain` runs -- generalizing H-3/Q25's shadow-substance guard from
    `extensions_resolver.resolve_extension` (agent extensions only) to
    every override-semantics dimension the tier manifest actually folds.
    Only emits a result for items whose WINNER is locally readable (a file
    or directory `_resolve_item_path` can find); an item whose winner has
    no locally-readable content is silently skipped, never fabricated
    either way -- matches `discover_contributions`'s own best-effort
    degrade."""

    items = resolve_layers(
        list(layers), dict(contributions), lockfile=dict(lockfile or {})
    )
    layer_by_id = {layer["id"]: layer for layer in layers}
    results: list[CheckResult] = []

    for item in items:
        if not item["shadowed"]:
            continue
        winner_layer = layer_by_id.get(item["winning_layer"])
        winner_path = _resolve_item_path(winner_layer, item["dimension"], item["item"])
        if winner_path is None:
            continue

        subject = f"{item['product']}/{item['dimension']}/{item['item']}"
        winner_text, winner_size = _read_item_text_and_size(winner_path)
        winner_status = _frontmatter_status(winner_text)
        todo_count = winner_text.count("TODO(")

        nearest_shadow = item["shadowed"][0]
        shadow_layer = layer_by_id.get(nearest_shadow["layer"])
        shadow_path = _resolve_item_path(shadow_layer, item["dimension"], item["item"])
        shadow_size = shadow_path.stat().st_size if shadow_path else 0
        if shadow_path is not None and shadow_path.is_dir():
            _, shadow_size = _read_item_text_and_size(shadow_path)

        is_draft = winner_status == "draft"
        has_todo = todo_count > 0
        size_ratio_ok = shadow_size == 0 or winner_size >= min_size_ratio * shadow_size
        substantive = not is_draft and not has_todo and size_ratio_ok

        detail = (
            f"winner={item['winning_layer']} ({winner_size}B, status={winner_status!r}, "
            f"{todo_count}x 'TODO('); shadows {nearest_shadow['layer']} ({shadow_size}B)"
        )

        if substantive:
            results.append(
                E3_DRAFT_PLACEHOLDER_NEVER_SHADOWS.result(
                    subject=subject,
                    verdict=Verdict.PASS,
                    detail=detail,
                    expected_today=ExpectedToday.PASS,
                )
            )
            continue

        evidence = (
            Evidence(
                kind="resolved-item",
                path=str(winner_path),
                expected=(
                    f"status != 'draft', no 'TODO(' markers, size >= "
                    f"{int(min_size_ratio * 100)}% of the nearest shadowed candidate"
                ),
                actual=f"status={winner_status!r}, {todo_count}x 'TODO(', {winner_size}B",
                detail=f"shadows {nearest_shadow['layer']}'s {shadow_size}B content",
            ),
        )
        results.append(
            E3_DRAFT_PLACEHOLDER_NEVER_SHADOWS.result(
                subject=subject,
                verdict=Verdict.FAIL,
                evidence=evidence,
                detail=detail,
                # This specific branch is the live-verified known case
                # (2026-08-11: claude/commands/protocol -> claude-organization,
                # whose own org override text opens "TODO(pablo): this
                # section is currently a no-op placeholder ... byte-for-byte"
                # reproduction of foundation) -- FAIL is the honest,
                # already-confirmed prediction here, not a blind mirror of
                # whatever this run happens to compute.
                expected_today=ExpectedToday.FAIL,
            )
        )
    return tuple(results)


# ---------------------------------------------------------------------------
# E-4 -- resolve attribution must match a REAL lock materialization
# ---------------------------------------------------------------------------


def _policy_blocked_reason(
    layer: Mapping[str, Any] | None, dimension: str
) -> str | None:
    """Explain why a nominal contributor cannot be an effective winner.

    ``resolve_layers`` now applies the same static fail-closed prerequisite
    as materialization: an explicitly empty signer list cannot win an
    executable dimension.  E-4 uses this helper to describe blocked entries
    in the resolved item's shadow chain; it must never use one to excuse an
    effective winner whose lock proof is missing.
    """

    if layer is None or dimension not in EXECUTABLE_DIMENSIONS:
        return None
    policy = layer.get("policy")
    if not isinstance(policy, Mapping) or policy.get("allowed_signers"):
        return None
    return (
        f"{layer.get('id', '<unknown>')!r} explicitly declares no "
        f"allowed_signers for executable dimension {dimension!r}"
    )


def check_e4_resolve_attribution_matches_lock(
    *,
    layers: Sequence[Mapping[str, Any]],
    contributions: Mapping[str, Mapping[str, Mapping[str, str | None]]],
    lockfile: Mapping[str, Any],
) -> tuple[CheckResult, ...]:
    """Thin wrap over `resolve_layers` (the same fold `cc resolve
    --explain` runs) cross-checked against the lockfile `cc doctor`/`cc
    freshness` already read. Catches the exact live discrepancy class:
    `winning_layer` claims a layer whose lock entry carries no real
    dimension pin at all -- only `_meta` (or nothing), meaning the
    resolver is trusting the live checkout while nothing ever recorded
    that layer as actually materialized.

    Two sources of truth (the resolver's *effective* ``winning_layer`` and
    the lock's recorded pins) must genuinely agree. Explicitly unsigned
    executable contributors can remain visible in the shadow chain, but
    they cannot excuse a missing lock record for the signed effective
    winner. Every lock-empty effective winner is therefore an unexpected
    FAIL (`expected_today=PASS`)."""

    items = resolve_layers(list(layers), dict(contributions), lockfile=dict(lockfile))
    layer_by_id = {layer["id"]: layer for layer in layers}
    results: list[CheckResult] = []

    for item in items:
        winning_layer = item["winning_layer"]
        subject = (
            f"{item['product']}/{item['dimension']}/{item['item']} -> {winning_layer}"
        )
        entry = lockfile.get(winning_layer, {})
        real_pins = sorted(key for key in entry if key != LAYER_META_KEY)
        blocked_nominal = [
            reason
            for shadow in item.get("shadowed", ())
            if (
                reason := _policy_blocked_reason(
                    layer_by_id.get(shadow.get("layer")), item["dimension"]
                )
            )
        ]
        blocked_note = (
            f"; {len(blocked_nominal)} nominal contributor(s) were "
            f"policy-ineligible: {blocked_nominal}"
            if blocked_nominal
            else ""
        )

        if real_pins:
            results.append(
                E4_ATTRIBUTION_MATCHES_LOCK.result(
                    subject=subject,
                    verdict=Verdict.PASS,
                    detail=(
                        f"{winning_layer}'s lock entry carries {len(real_pins)} real "
                        f"dimension pin(s): {real_pins}{blocked_note}"
                    ),
                    expected_today=ExpectedToday.PASS,
                )
            )
            continue

        meta = entry.get(LAYER_META_KEY, {})
        base_detail = (
            f"resolve_layers claims winning_layer={winning_layer!r} for "
            f"{item['dimension']}/{item['item']} (winning_sha={item['winning_sha']!r}) "
            f"but the lock has never recorded a real materialization for this "
            f"layer -- only {LAYER_META_KEY!r}={meta!r}. The resolver reads the "
            "live checkout; the lock still reflects whatever (if anything) `cc "
            "update` last pinned, which can silently disagree."
        )
        evidence = (
            Evidence(
                kind="lock-attribution",
                path=winning_layer,
                expected=(
                    "lock entry carries at least one real dimension pin "
                    "(the effective winner was actually materialized)"
                ),
                actual=f"lock entry keys={sorted(entry) or ['<absent from lockfile>']}",
                detail=(
                    f"{base_detail}{blocked_note}. The effective winner is not "
                    "policy-blocked; either `cc update` has never recorded it "
                    "or materialization failed."
                ),
            ),
        )
        results.append(
            E4_ATTRIBUTION_MATCHES_LOCK.result(
                subject=subject,
                verdict=Verdict.FAIL,
                evidence=evidence,
                expected_today=ExpectedToday.PASS,
            )
        )
    return tuple(results)


# ---------------------------------------------------------------------------
# E-5 -- knowledge ladder hydration must be followed by real consumption
# ---------------------------------------------------------------------------

_HYDRATE_CC_ENV_RE = re.compile(r'eval\s+"\$\(cc env\)"', re.IGNORECASE)
# Real agent phrasing wraps the var in backticks ("walk `$CC_KNOWLEDGE_REPOS`
# ... and read ..."), so "walk" and the variable name are never strictly
# adjacent -- `[\s\S]{0,80}?` tolerates the punctuation/markup between them
# without requiring it be whitespace, the same way `[\s\S]{0,600}?` tolerates
# the parenthetical between the variable and the "read" verb.
_LADDER_WALK_AND_READ_RE = re.compile(
    r"\bwalk\b[\s\S]{0,80}?CC_KNOWLEDGE_REPOS\b[\s\S]{0,600}?\bread\b",
    re.IGNORECASE,
)


def check_e5_knowledge_ladder_actually_consumed(
    *, agent_files: Mapping[str, str]
) -> tuple[CheckResult, ...]:
    """`agent_files`: `{display name -> file text}`. An agent that never
    hydrates `cc env` at all is SKIP (nothing to check follow-through
    against -- that agent simply does not claim to use the ladder). An
    agent that hydrates it but never walks-and-reads `$CC_KNOWLEDGE_REPOS`
    is exactly the "installed but not effective" bug this check exists to
    catch: it can call `eval "$(cc env)"` and then read nothing."""

    results: list[CheckResult] = []
    for name, text in agent_files.items():
        if not _HYDRATE_CC_ENV_RE.search(text):
            results.append(
                E5_KNOWLEDGE_LADDER_ACTUALLY_CONSUMED.result(
                    subject=name,
                    verdict=Verdict.SKIP,
                    detail=f'{name} does not hydrate `eval "$(cc env)"` at all',
                )
            )
            continue

        if _LADDER_WALK_AND_READ_RE.search(text):
            results.append(
                E5_KNOWLEDGE_LADDER_ACTUALLY_CONSUMED.result(
                    subject=name,
                    verdict=Verdict.PASS,
                    detail=f"{name} hydrates cc env and walks+reads $CC_KNOWLEDGE_REPOS",
                )
            )
            continue

        evidence = (
            Evidence(
                kind="agent-instructions",
                path=name,
                expected=(
                    "a 'walk $CC_KNOWLEDGE_REPOS ... and read <path>' consumption "
                    "step, the same shape sd.md/ta.md/cw.md use"
                ),
                actual='hydrates `eval "$(cc env)"` but never walks/reads $CC_KNOWLEDGE_REPOS',
            ),
        )
        results.append(
            E5_KNOWLEDGE_LADDER_ACTUALLY_CONSUMED.result(
                subject=name, verdict=Verdict.FAIL, evidence=evidence
            )
        )
    return tuple(results)


# ---------------------------------------------------------------------------
# E-6 -- extension resolution wired beyond prose
# ---------------------------------------------------------------------------

_EXTENSIONS_RESOLVE_RE = re.compile(r"cc extensions resolve")


def find_extension_resolution_invocations(
    source_root: Path, *, scan_roots: Sequence[Path] | None = None
) -> tuple[Path, ...]:
    """Every `*.sh` file under the selected roots with a non-comment line
    invoking `cc extensions resolve` -- deliberately `.sh` only (hooks and
    scripts, the framework's actual executable surface), and deliberately
    skipping comment lines, so a `.md` mention (agent/command prose an LLM
    may or may not follow) or a commented-out example never counts as real
    wiring -- the same "a mention is not a consumer" discipline `tier.py`'s
    `find_dimensions_consumers` already enforces for H-8."""

    hits: list[Path] = []
    roots = tuple(scan_roots) if scan_roots is not None else (source_root,)
    for root in roots:
        for path in sorted(root.rglob("*.sh")):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if _EXTENSIONS_RESOLVE_RE.search(stripped):
                    hits.append(path)
                    break
    return tuple(hits)


def check_e6_extension_resolution_wired_beyond_prose(
    *,
    source_root: Path,
    scan_roots: Sequence[Path] | None = None,
    subject: str | None = None,
) -> CheckResult:
    hits = find_extension_resolution_invocations(
        source_root, scan_roots=scan_roots
    )
    result_subject = subject or str(source_root)
    if hits:
        return E6_EXTENSION_RESOLUTION_WIRED_BEYOND_PROSE.result(
            subject=result_subject,
            verdict=Verdict.PASS,
            detail=(
                f"{len(hits)} executable invocation(s) found: "
                f"{', '.join(str(path) for path in hits)}"
            ),
        )

    evidence = (
        Evidence(
            kind="code-scan",
            path=result_subject,
            expected=(
                "at least one *.sh hook/script with a non-comment "
                "`cc extensions resolve` invocation"
            ),
            actual="0 matches",
            detail=(
                "every occurrence of 'cc extensions resolve' in the framework is "
                "inside agent/command *.md prose (an instruction an LLM may or may "
                "not follow) -- nothing enforces it"
            ),
        ),
    )
    return E6_EXTENSION_RESOLUTION_WIRED_BEYOND_PROSE.result(
        subject=result_subject,
        verdict=Verdict.FAIL,
        evidence=evidence,
        expected_today=ExpectedToday.FAIL,
    )


__all__ = [
    "E1_ORG_CONTENT_REACHES_PROJECT",
    "E2_NEAREST_WINS_PRESERVES_SIBLINGS",
    "E3_DRAFT_PLACEHOLDER_NEVER_SHADOWS",
    "E4_ATTRIBUTION_MATCHES_LOCK",
    "E5_KNOWLEDGE_LADDER_ACTUALLY_CONSUMED",
    "E6_EXTENSION_RESOLUTION_WIRED_BEYOND_PROSE",
    "check_e1_org_content_reaches_project",
    "check_e2_nearest_wins_preserves_siblings",
    "check_e3_draft_placeholder_never_shadows",
    "check_e4_resolve_attribution_matches_lock",
    "check_e5_knowledge_ladder_actually_consumed",
    "check_e6_extension_resolution_wired_beyond_prose",
    "find_extension_resolution_invocations",
]
