"""`cc conformance check|report|baseline|explain|list` -- WP-8, the
operator CLI surface over the conformance harness WP-1..WP-7 built.

Design source of truth: `HARNESS-DESIGN.md` section 6 ("CLI surface") and
section 7.2 ("two modes"). This module is orchestration ONLY -- every
verdict comes from a sibling package's already-registered check (`tier.py`
WP-2, `stack.py` WP-3, `sweep.py`+`dimensions/` WP-4, `lock.py` WP-5,
`roundtrip.py` WP-6, `root_causes.py` WP-7); nothing here computes a new
`CheckResult` of its own except a single, honest "this layer's real-machine
input could not be gathered" `COULD_NOT_RUN` wrapper (`_safe_run`), which
exists so one layer's crash never aborts the whole run
(`HARNESS-DESIGN.md` section 10's "a check crashes -> COULD_NOT_RUN, siblings
continue", extended here from per-check to per-layer since this module is
the first place several checks are run together).

Six architectural choices this module makes, each traced against the
sibling packages' actual public API (not assumed from the design prose):

1. **`resolve_key`/`get_resolved_config`/`resolve_knowledge_repos`, never
   `Path.home()`.** Unlike `tier.py`'s and `root_causes.py`'s own test
   files (which bypass the config-resolution seam because pytest's autouse
   `_isolate_machine_config` fixture has already redirected it to an empty
   `tmp_path`), THIS module runs as the real, installed `cc` CLI -- there is
   no isolation fixture in production, so the normal `cc.core.config` seam
   IS the correct way to find the real manifest/knowledge ladder, exactly
   like `commands/env.py` and `commands/resolve.py` already do.
2. **Tier-layer (H1..H9) has no `run_h*_machine()` wrapper in `tier.py`**
   (unlike `root_causes.py`, which ships `run_rc1()`..`run_rc5()`) --
   `tier.py`'s own module docstring says callers "supply real-machine data
   or synthetic-fleet data through the same parameters", so gathering that
   real-machine data is explicitly THIS module's job, not a gap. H-8
   (`tier.precedence.commands_dimension_has_no_consumer`) has a real,
   non-fixture invocation despite `TEST-MATRIX.md`'s "fixture-only" label on
   the test-scope column -- its own module docstring confirms it was
   "verified true on this codebase" by grepping the real `src/cc` tree, so
   it runs here too. H-9 genuinely has no live instance (no real project on
   this machine sets a literal `paths.knowledge_repo` override) --
   `TEST-MATRIX.md` section 7 item 10 says not to fabricate one, so it is
   registered (visible to `cc conformance list`/`explain`) but never
   invoked by the real-machine sweep.
3. **`--repo`/`--class` pre-filter the repo-layer sweep (`sweep.py`'s own
   `SweepOptions`) for speed, and `report.filter_by_repo` post-filters
   EVERY layer's results uniformly afterward** -- tier/stack/lock/
   regression have no per-layer pre-filter API of their own (their real-
   machine wiring is comparatively cheap: at most a few dozen file reads,
   not a ~75-repo sweep), so re-deriving one would be more code for no
   measurable speed gain; `report.filter_by_repo` (WP-1) already defines
   the exact subject-matching semantics this module needs and is reused
   verbatim, never reimplemented.
4. **Ordinary `--full` includes the sandboxed round-trip.**
   `HARNESS-DESIGN.md` section 7.2 and the product PRD both define full mode
   as all six layers. The mutation boundary remains strict: round-trip writes
   only to a disposable directory created by `tempfile`, never a real repo,
   and the CLI announces that scratch mutation on stderr before it starts,
   including for `--json`. Fast/default mode remains read-only and excludes
   round-trip.
5. **`cc conformance explain <id>` never runs a `roundtrip.*` check live.**
   `explain` is documented as read-only ("what it asserts, why, evidence,
   remediation"); recomputing a round-trip check's evidence would silently
   turn a read-only inspection command into one that mutates a scratch
   clone. `explain` prints the static registration for a `roundtrip.*` id
   and tells the operator to run `check --layer roundtrip --check <id>`
   instead.
6. **The scratch-mutation notice goes to stderr, not stdout, even though
   section 6.1's prose says "stdout".** `--json` output must stay one
   parseable JSON document on stdout for a scripted consumer; interleaving
   a plain-text notice before it would break that contract for no benefit
   (a human running without `--json` sees the stderr line immediately in
   the same terminal anyway). This is the same class of documented,
   deliberate divergence `commands/freshness.py`'s own "SCHEMA DIVERGENCE"
   comment models.
"""

from __future__ import annotations

import json as _json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

import typer
import yaml as _yaml

from cc.core.config import resolve_key, resolve_knowledge_repos
from cc.core.conformance import classes as classes_mod
from cc.core.conformance import (
    effectiveness,
    lock,
    report,
    root_causes,
    roundtrip,
    stack,
    sweep,
    tier,
)
from cc.core.conformance.dimensions import discover_dimension_modules
from cc.core.conformance.registry import DEFAULT_REGISTRY, REPO_CLASSES
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
from cc.core.ecosystem.canonical_transaction import build_canonical_project_request
from cc.core.ecosystem.discovery import discover_contributions
from cc.core.ecosystem.lockfile import default_lockfile_path, read_lockfile
from cc.core.ecosystem.manifest import ManifestError, load_layers, validate_layers
from cc.core.ecosystem.project_plan_store import issue_plan
from cc.core.ecosystem.project_reconciliation import assess_project
from cc.core.ecosystem.reconciliation import (
    build_apply_report,
    build_plan_report,
    build_verify_report,
)
from cc.core.ecosystem.resolver import resolve_layers

conformance_app = typer.Typer(
    help=(
        "Verify ecosystem conformance across tier, stack, install, lock, "
        "round-trip, and regression layers."
    ),
    no_args_is_help=True,
)

baseline_app = typer.Typer(
    help="Freeze or diff a conformance baseline.", no_args_is_help=True
)
conformance_app.add_typer(baseline_app, name="baseline")

DEFAULT_JOBS = 8  # HARNESS-DESIGN.md section 7.1: 4.6s cold / 2.0s warm at jobs=8.

# Fast/default mode stays read-only. Full mode adds the sandboxed round-trip
# as the sixth designed layer (module docstring point 4).
DEFAULT_CHECK_LAYERS: tuple[str, ...] = ("tier", "stack", "repo", "lock", "regression")
ALL_LAYER_CHOICES: tuple[str, ...] = (*DEFAULT_CHECK_LAYERS, "roundtrip")
FULL_CHECK_LAYERS: tuple[str, ...] = ALL_LAYER_CHOICES
SEVERITY_CHOICES: tuple[str, ...] = tuple(s.value for s in Severity)

# `--class` accepts two vocabularies (see `_resolve_class_filters`): the
# rubric letters `Registry.select(classes=...)` filters on, and the
# `classification.toml` taxonomy names operators actually read
# (`classes.RepoClass`). Both are spelled out here so an unknown value's
# error message can show the operator every value that actually works,
# never just the half they didn't try.
RUBRIC_CLASS_CHOICES: tuple[str, ...] = tuple(sorted(REPO_CLASSES))
CLASSIFICATION_NAME_CHOICES: tuple[str, ...] = tuple(
    c.value for c in classes_mod.RepoClass
)

_ROUNDTRIP_MUTATION_NOTICE = (
    "conformance check --layer roundtrip: mutating a disposable scratch "
    "clone under a fresh temporary directory only -- no real repo is ever "
    "a write target."
)


def _ensure_registry_loaded() -> None:
    """Populate `DEFAULT_REGISTRY` with every check id, including the 13+1
    `dimensions/d0N_*.py` modules `sweep.py` otherwise only imports lazily
    on its own first repo sweep. `tier`/`stack`/`lock`/`roundtrip`/
    `root_causes` are already imported at this module's own top level (each
    registers at import time -- `registry.py`'s own docstring), so only the
    dimension package needs an explicit nudge here. Import caching makes
    repeat calls free; called unconditionally at the top of every
    subcommand so `list`/`explain` never depend on which `--layer` a prior
    call happened to select."""

    discover_dimension_modules()


# ---------------------------------------------------------------------------
# Real-machine input gathering -- tier layer (H1..H9)
# ---------------------------------------------------------------------------


def _real_manifest_path() -> Optional[Path]:
    """The one canonical manifest `cc env`/`cc resolve --explain` already
    use (`resolve_key("layers.manifest")`, mirroring `commands/resolve.py`
    line-for-line), falling back to the first of the three well-known
    locations `stack.discover_real_manifest_paths()` finds present."""

    configured = resolve_key("layers.manifest")
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return path
    for path in stack.discover_real_manifest_paths():
        return path
    return None


def _load_validated_layers() -> tuple[dict[str, Any], ...]:
    manifest_path = _real_manifest_path()
    if manifest_path is None:
        return ()
    try:
        return tuple(validate_layers(load_layers(manifest_path)))
    except ManifestError:
        return ()


def _declared_agent_names(knowledge_repos: Sequence[str]) -> set[str]:
    """Every distinct `extensions[].agent` name declared by ANY tier on the
    real knowledge ladder -- never a hardcoded agent list (arity-
    independent, matches `tier.py`'s own "never assume 4" convention), so a
    newly-declared extension is picked up automatically on the next run."""

    names: set[str] = set()
    for repo in knowledge_repos:
        manifest_path = Path(repo) / "knowledge-manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            data = _json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, _json.JSONDecodeError):
            continue
        for entry in data.get("extensions") or ():
            if isinstance(entry, dict) and isinstance(entry.get("agent"), str):
                names.add(entry["agent"])
    return names


def _run_tier_layer_machine() -> tuple[CheckResult, ...]:
    results: list[CheckResult] = []
    ladder = resolve_knowledge_repos()
    if not ladder:
        return tuple(results)

    for agent in sorted(_declared_agent_names(ladder)):
        results.append(
            tier.check_h1_nearest_declared_wins(agent, knowledge_repos=ladder)
        )
        results.append(
            tier.check_h2_absence_is_not_shadow(agent, knowledge_repos=ladder)
        )
        results.append(tier.check_h3_shadow_substance(agent, knowledge_repos=ladder))

    layers = _load_validated_layers()
    expected_ladder = (
        tier.knowledge_ladder_from_layers(layers, product="knowledge") if layers else ()
    )
    results.append(
        tier.check_h4_ladder_order(
            actual_ladder=ladder, expected_ladder=expected_ladder
        )
    )

    try:
        framework_root: Optional[Path] = roundtrip.discover_framework_repo_root()
    except roundtrip.InstallerScriptError:
        framework_root = None

    if framework_root is not None:
        agents_dir = framework_root / ".claude" / "agents"
        agent_files = {
            name: (agents_dir / name).read_text(encoding="utf-8")
            for name in ("cw.md", "sd.md", "ta.md")
            if (agents_dir / name).is_file()
        }
        if agent_files:
            results.extend(
                tier.check_h5_singular_alias_paths_exist(
                    agent_files=agent_files, cc_knowledge_repo=ladder[0]
                )
            )

        # The exact two subtrees `test_layer1_tier.py`'s own real-machine
        # H-8 test scans: `core/ecosystem` and `commands` -- deliberately
        # NOT the whole `src/cc` tree, which would also sweep in
        # `core/conformance/` itself. `stack.py`'s own dimensions-declared
        # check legitimately reads a layer's declared-dimensions field
        # while INSPECTING a copilot.layer.yml (a read-only harness check,
        # never a materialize/shadow consumer), and `find_dimensions_
        # consumers`'s plain-text scan cannot tell that apart from a real
        # consumer -- scanning the harness's own package (including THIS
        # file, whose comments would otherwise echo the literal pattern
        # being searched for) would produce a false "a consumer exists"
        # PASS, contradicting the FAIL TEST-MATRIX.md predicts for the
        # real ecosystem source.
        cc_src_root = framework_root / "tools" / "cc" / "src" / "cc"
        for relative in ("core/ecosystem", "commands"):
            candidate = cc_src_root / relative
            if candidate.is_dir():
                results.append(
                    tier.check_h8_commands_dimension_has_no_consumer(
                        source_root=candidate
                    )
                )

        # E-5: every framework agent whose instructions claim to consult the
        # knowledge ladder, not just the three H-5 already reads for the
        # singular-alias check -- ground truth (TEST-MATRIX-adjacent, this
        # task): cw/sd/ta already walk+read CC_KNOWLEDGE_REPOS; ind/uxd/
        # uids/cco were found hydrating `cc env` and then reading nothing.
        ladder_agent_files = {
            name: (agents_dir / name).read_text(encoding="utf-8")
            for name in (
                "cw.md",
                "sd.md",
                "ta.md",
                "ind.md",
                "uxd.md",
                "uids.md",
                "cco.md",
            )
            if (agents_dir / name).is_file()
        }
        if ladder_agent_files:
            results.extend(
                effectiveness.check_e5_knowledge_ladder_actually_consumed(
                    agent_files=ladder_agent_files
                )
            )

        # E-6: `cc extensions resolve` must fire from an executable
        # consumer (a hook/script), not merely be described in markdown
        # prose -- scoped to the framework's real executable surface
        # (`.claude`, `plugins`, `scripts`), deliberately never `tools/cc`
        # itself (the CLI's own implementation/tests always mention the
        # command they implement, the same H-8-shaped trap `tier.py`'s
        # `_is_under_excluded_package` guards against).
        for relative in (".claude", "plugins", "scripts"):
            candidate = framework_root / relative
            if candidate.is_dir():
                results.append(
                    effectiveness.check_e6_extension_resolution_wired_beyond_prose(
                        source_root=candidate
                    )
                )

    tier_repos = {f"rank-{index}": repo for index, repo in enumerate(ladder)}
    results.extend(tier.check_h6_declared_skill_paths_exist(tier_repos=tier_repos))
    results.append(tier.check_h7_no_hollow_rung(tier_repos=tier_repos))

    # H-9 deliberately NOT invoked here -- see module docstring point 2.
    results.extend(_run_resolver_effectiveness_machine())
    return tuple(results)


# ---------------------------------------------------------------------------
# Real-machine input gathering -- tier EFFECTIVENESS, E-1..E-4
# ---------------------------------------------------------------------------


def _resolver_effectiveness_inputs() -> Optional[
    tuple[tuple[dict[str, Any], ...], dict[str, Any], dict[str, Any]]
]:
    """`(effective_layers, contributions, lockfile)` for E-3/E-4 -- the
    identical assembly `cc.commands.resolve.build_resolve_report` performs
    (manifest -> mirror-synthesized effective layers -> local discovery ->
    lockfile), reused directly rather than re-derived, so these checks can
    never silently disagree with what `cc resolve --explain` itself
    reports. `None` when there is no manifest to resolve against at all."""

    manifest_path = _real_manifest_path()
    if manifest_path is None:
        return None
    try:
        raw_layers = validate_layers(load_layers(manifest_path))
    except ManifestError:
        return None
    if not raw_layers:
        return None

    from cc.commands.resolve import _synthesize_effective_layers

    mirror_root_raw = resolve_key("paths.mirrors_root")
    mirror_root_base = (
        Path(str(mirror_root_raw)).expanduser()
        if mirror_root_raw
        else Path("~/.copilot/mirrors").expanduser()
    )
    effective_layers = _synthesize_effective_layers(
        raw_layers, mirror_root_base=mirror_root_base
    )
    contributions = discover_contributions(effective_layers)
    lockfile = read_lockfile(default_lockfile_path())
    return tuple(effective_layers), contributions, lockfile


def _run_resolver_effectiveness_machine() -> tuple[CheckResult, ...]:
    """E-3/E-4: no subprocess, no mutation -- a pure read+fold over the
    real manifest/lockfile, exactly like H-1..H-4 above."""

    inputs = _resolver_effectiveness_inputs()
    if inputs is None:
        return ()
    effective_layers, contributions, lockfile = inputs
    results: list[CheckResult] = list(
        effectiveness.check_e3_draft_placeholder_never_shadows(
            layers=effective_layers, contributions=contributions, lockfile=lockfile
        )
    )
    results.extend(
        effectiveness.check_e4_resolve_attribution_matches_lock(
            layers=effective_layers, contributions=contributions, lockfile=lockfile
        )
    )
    return tuple(results)


def _run_installer_effectiveness_machine() -> tuple[CheckResult, ...]:
    """E-1/E-2: drives the REAL installer (`setup-project.md`'s literal
    "Copy Agents" bash step, via `roundtrip.py` -- the module that already
    established "the real installer" means those literal bash blocks, run
    verbatim, never a Python reimplementation) against a disposable scratch
    project + scratch `$HOME`, cross-checked against a small SYNTHETIC
    two-tier fixture (never the real ladder) built only to compute what an
    organization-tier override SHOULD produce. Every write happens inside a
    fresh `tempfile.TemporaryDirectory()`; no real project or real tier repo
    is ever touched, matching `HARNESS-DESIGN.md` §5.3's rule for any check
    that needs a mutable target.

    The synthetic org-tier fixture is built and wired into the scratch
    `$HOME`'s OWN `layers.manifest` config BEFORE `run_bash_steps` below --
    a prior version of this function built the fixture AFTER the real bash
    already ran, so no implementation of Step 6 could ever have discovered
    it (the fixture and the bash execution were two disconnected
    computations that happened to be compared afterward). It also uses
    `product: "claude"`, matching `resolve_claude_content()`'s own
    `layer.get("product") == "claude"` filter -- the prior
    `"effectiveness-probe"` product could never be picked up by the real
    per-product resolver either. Both were live bugs in THIS harness
    function, not in the installer it drives."""

    try:
        framework_root = roundtrip.discover_framework_repo_root()
    except roundtrip.InstallerScriptError:
        return ()
    try:
        cc_bin = roundtrip.discover_cc_bin(framework_root)
    except roundtrip.CcBinaryNotFoundError:
        return ()

    version_path = framework_root / "VERSION.json"
    setup_project_path = framework_root / ".claude" / "commands" / "setup-project.md"
    if not version_path.is_file() or not setup_project_path.is_file():
        return ()
    try:
        version = _json.loads(version_path.read_text(encoding="utf-8"))
        roster = list(version["components"]["agents"]["frameworkAgents"])
    except (OSError, _json.JSONDecodeError, KeyError, TypeError):
        return ()
    if not roster:
        return ()
    probe_agent = roster[0]

    with tempfile.TemporaryDirectory(prefix="cc-conformance-effectiveness-") as raw_tmp:
        tmp_path = Path(raw_tmp)
        home = tmp_path / "home"
        project = tmp_path / "project"
        project.mkdir(parents=True, exist_ok=True)
        (project / ".claude" / "agents").mkdir(parents=True, exist_ok=True)

        roundtrip.materialize_framework_source(
            home / ".claude" / "copilot", framework_root
        )
        env = roundtrip.build_scratch_env(home=home, cc_bin=cc_bin)

        # A marker ONLY this synthetic org-tier fixture file carries -- the
        # real foundation content cannot contain it by coincidence, so a
        # match in `installed_content` can only mean the org tier's content
        # actually reached the project. The foundation's own real content
        # for `probe_agent` is prefixed with the marker (rather than the
        # marker standing alone) so the fixture is trivially
        # substance-gate-safe (core/ecosystem/substance.py's size-ratio
        # heuristic: a real override must be >= half the size of what it
        # shadows) -- a tiny marker-only stub would be, correctly, REJECTED
        # by the same guard E-3 exists to prove works, which would make
        # this probe fail for the wrong reason entirely.
        marker = "EFFECTIVENESS-PROBE-ORG-MARKER-38fbe4a1"
        foundation_dir = home / ".claude" / "copilot" / ".claude"
        foundation_agent_path = foundation_dir / "agents" / f"{probe_agent}.md"
        foundation_agent_text = (
            foundation_agent_path.read_text(encoding="utf-8")
            if foundation_agent_path.is_file()
            else ""
        )
        org_dir = tmp_path / "org-tier"
        (org_dir / "agents").mkdir(parents=True, exist_ok=True)
        (org_dir / "agents" / f"{probe_agent}.md").write_text(
            f"---\nstatus: active\n---\n{marker}\n\n{foundation_agent_text}",
            encoding="utf-8",
        )

        # `validate_layers` requires ascending-rank order per product --
        # nearest (lowest rank number, highest precedence) first.
        probe_layers: list[dict[str, Any]] = [
            {
                "id": "probe-organization",
                "role": "organization",
                "rank": 30,
                "product": "claude",
                "source": {"repo": f"file://{org_dir}", "path": str(org_dir)},
                "auth": "anon",
                "activation": "always",
            },
            {
                "id": "probe-foundation",
                "role": "foundation",
                "rank": 40,
                "product": "claude",
                "source": {
                    "repo": f"file://{foundation_dir}",
                    "path": str(foundation_dir),
                },
                "auth": "anon",
                "activation": "always",
            },
        ]

        # Wire the fixture into the scratch $HOME's OWN machine config --
        # the SAME `layers.manifest` key `resolve_key("layers.manifest")`
        # (config_paths.py, honoring `CC_MACHINE_ROOT` -- already set to
        # `home/.claude/cc` by `build_scratch_env`) reads -- so the bash
        # steps about to run (a genuinely tier-aware Step 6) discover this
        # fixture exactly as they would a real `copilot.layers.yml`.
        manifest_path = tmp_path / "copilot.layers.yml"
        manifest_path.write_text(
            _yaml.safe_dump({"version": 1, "layers": probe_layers}, sort_keys=False),
            encoding="utf-8",
        )
        machine_config_dir = home / ".claude" / "cc"
        machine_config_dir.mkdir(parents=True, exist_ok=True)
        (machine_config_dir / "config.json").write_text(
            _json.dumps({"layers": {"manifest": str(manifest_path)}}), encoding="utf-8"
        )

        markdown = setup_project_path.read_text(encoding="utf-8")
        try:
            blocks = roundtrip.extract_bash_steps(
                markdown, [("## Step 6: Copy Agents", "## Step 7: Create .mcp.json")]
            )
        except roundtrip.InstallerScriptError:
            return ()
        roundtrip.run_bash_steps(blocks, cwd=project, env=env)

        installed_content: dict[str, Optional[str]] = {}
        for agent in roster:
            agent_path = project / ".claude" / "agents" / f"{agent}.md"
            installed_content[agent] = (
                agent_path.read_text(encoding="utf-8") if agent_path.is_file() else None
            )

        probe_contributions = discover_contributions(
            probe_layers, dimensions=("agents",)
        )
        probe_items = {
            item["item"]: item
            for item in resolve_layers(probe_layers, probe_contributions)
            if item["dimension"] == "agents"
        }

    results: list[CheckResult] = []
    winner = probe_items.get(probe_agent)
    if winner is not None:
        results.append(
            effectiveness.check_e1_org_content_reaches_project(
                probe_item=probe_agent,
                winning_layer=winner["winning_layer"],
                expected_marker=marker,
                installed_text=installed_content.get(probe_agent),
            )
        )
    results.append(
        effectiveness.check_e2_nearest_wins_preserves_siblings(
            overridden_item=probe_agent,
            roster=roster,
            installed_content=installed_content,
        )
    )
    return tuple(results)


# ---------------------------------------------------------------------------
# Real-machine input gathering -- stack layer
# ---------------------------------------------------------------------------


def _run_stack_layer_machine() -> tuple[CheckResult, ...]:
    manifest_paths = stack.discover_real_manifest_paths()
    if not manifest_paths:
        return ()
    return tuple(stack.run_stack_checks(manifest_paths=manifest_paths))


# ---------------------------------------------------------------------------
# Real-machine input gathering -- repo layer (the D1..D13 sweep)
# ---------------------------------------------------------------------------


def _run_repo_layer(
    *,
    mode: Mode,
    repos: Sequence[str],
    classes: Sequence[str],
    repo_classes: Sequence[str],
    check_ids: Sequence[str],
    jobs: int,
    use_cache: bool,
) -> tuple[CheckResult, ...]:
    options = sweep.SweepOptions(
        repos=tuple(repos),
        classes=tuple(classes),
        repo_classes=tuple(repo_classes),
        check_ids=tuple(check_ids),
        mode=mode,
        jobs=jobs,
        use_cache=use_cache,
    )
    return sweep.run_sweep(options).results


# ---------------------------------------------------------------------------
# Real-machine input gathering -- lock layer
# ---------------------------------------------------------------------------


def _repo_selected(path: Path, wanted: Sequence[str]) -> bool:
    """Same suffix-match semantics as `report.filter_by_repo` / `sweep.py`'s
    `_repo_matches_filter`, applied pre-execution here since `lock.py` has
    no `SweepOptions`-shaped pre-filter of its own."""

    if not wanted:
        return True
    text = str(path)
    return any(text == want or text.endswith(f"/{Path(want).name}") for want in wanted)


def _out_of_scope_lock_subjects(
    discovered: Sequence["sweep.DiscoveredRepo"],
) -> dict[str, str]:
    """`{subject: reason}` for every discovered repo whose classification
    resolves to rubric letter "E" (SCRATCH-ARCHIVE) -- the same
    class-E-is-out-of-scope convention every `repo.d0*` dimension already
    applies via its own `applies_to_classes=("A","B","C","D")`
    (`dimensions/d01_claude.py`, `d04_hook.py`, etc.), which `lock.py`'s
    Layer-4 checks have no `RepoContext` of their own to consult. Computed
    unconditionally (not only when `--class`/`--repo-class` is passed) so
    the default `cc conformance check` run never grades an owner-excluded
    repo's lock as a live S0 -- `check_lock_full_mode_records_required_paths`
    (LI-5)'s own docstring has the full rationale and two confirmed live
    cases (`convoco-policy-build`, a git worktree of `convoco`, and
    `rfp-copilot`, ratified for archival)."""

    table = classes_mod.load_classification_table()
    out_of_scope: dict[str, str] = {}
    for entry in discovered:
        cls = classes_mod.classify(
            entry.path, root=entry.root, table=table, is_git_root=entry.is_git_root
        )
        if cls.rubric_letter == "E":
            out_of_scope[str(entry.path)] = (
                f"{cls.repo_class.value} (rubric E): {cls.rationale}"
                if cls.rationale
                else cls.repo_class.value
            )
    return out_of_scope


def _run_lock_layer(
    *,
    repos: Sequence[str] = (),
    classes: Sequence[str] = (),
    repo_classes: Sequence[str] = (),
) -> tuple[CheckResult, ...]:
    discovered = [entry for entry in sweep.discover_repos() if entry.is_git_root]
    discovered = [entry for entry in discovered if _repo_selected(entry.path, repos)]
    out_of_scope = _out_of_scope_lock_subjects(discovered)
    if classes or repo_classes:
        table = classes_mod.load_classification_table()
        classified = [
            (
                entry,
                classes_mod.classify(
                    entry.path,
                    root=entry.root,
                    table=table,
                    is_git_root=entry.is_git_root,
                ),
            )
            for entry in discovered
        ]
        if classes:
            classified = [
                (entry, cls)
                for entry, cls in classified
                if cls.rubric_letter in classes
            ]
        if repo_classes:
            classified = [
                (entry, cls)
                for entry, cls in classified
                if cls.repo_class.value in repo_classes
            ]
        discovered = [entry for entry, _cls in classified]
    repo_roots = tuple(entry.path for entry in discovered)
    if not repo_roots:
        return ()
    return lock.run_lock_checks(repo_roots, out_of_scope=out_of_scope)


# ---------------------------------------------------------------------------
# Real-machine input gathering -- round-trip layer (MUTATING, opt-in only)
# ---------------------------------------------------------------------------


def _reference_install_manifest_path() -> Path:
    # src/cc/commands/conformance.py -> parents[3] == tools/cc
    return (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "conformance"
        / "fixtures"
        / "reference-install"
        / "manifest.json"
    )


def _snapshot_tree(root: Path) -> dict[str, str]:
    """Content hash per tracked-identity file under `root`, EXCLUDING
    `.claude/memory/` (pure local cache/index state -- `roundtrip.
    check_update_idempotent`'s own docstring: "excluding volatile,
    machine-local files") and `.git/` (the scratch repo's own VCS
    metadata, never part of the installed tree's identity)."""

    snapshot: dict[str, str] = {}
    import hashlib

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith(".claude/memory/") or relative.startswith(".git/"):
            continue
        try:
            snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            snapshot[relative] = "<unreadable>"
    return snapshot


def _diff_paths(before: dict[str, str], after: dict[str, str]) -> tuple[str, ...]:
    changed = {key for key in {*before, *after} if before.get(key) != after.get(key)}
    return tuple(sorted(changed))


def _run_roundtrip_layer() -> tuple[CheckResult, ...]:
    """Run canonical request/plan/apply/verify against one scratch project.

    The machine preflight is deliberately supplied as an isolated, ready
    fixture because this layer verifies the project transaction rather than
    ambient auth/network setup. Census, recipes, plan binding, transaction,
    disk verification, and private state are all the real implementations.
    """

    with tempfile.TemporaryDirectory(prefix="cc-conformance-roundtrip-") as raw_tmp:
        tmp_path = Path(raw_tmp)
        project = tmp_path / "project"
        project.mkdir(parents=True, exist_ok=True)

        framework_repo_root = roundtrip.discover_framework_repo_root()

        for git_args in (
            ("init", "--quiet"),
            ("config", "user.email", "conformance@localhost"),
            ("config", "user.name", "cc conformance"),
        ):
            subprocess.run(
                ("git", *git_args),
                cwd=project,
                check=True,
                timeout=10.0,
                capture_output=True,
            )

        request = build_canonical_project_request(
            project,
            components=("claude", "codex"),
            approved_roots=(tmp_path,),
        )
        authority_root = Path(request.roots[0])
        project = Path(request.projects[0].path)
        subject = str(project)
        state_root = authority_root / "private-reconciliation-state"

        def machine_builder() -> dict[str, Any]:
            return {
                "state": "ready",
                "helper": {
                    "state": "ready",
                    "version": "2.9.0",
                    "path": "cc conformance (isolated preflight)",
                    "detail": "The isolated transaction preflight is ready.",
                },
                "frameworks": [
                    {
                        "component": component,
                        "state": "ready",
                        "path": str(resolve_key(f"paths.{component}_copilot_root")),
                        "version": "verified-by-recipe-source-binding",
                        "detail": "The configured authoritative source is available.",
                    }
                    for component in ("claude", "codex")
                ],
                "configuration": {
                    "state": "ready",
                    "path": str(state_root),
                    "approved_roots": [str(authority_root)],
                    "detail": "Only the disposable scratch root is approved.",
                },
                "authentication": {
                    "state": "signed-in",
                    "credential_state": "present",
                    "detail": "External authentication is outside this local transaction probe.",
                },
                "connectivity": {
                    "state": "online",
                    "detail": "The local transaction makes no network request.",
                },
                "layers": {
                    "state": "ready",
                    "ready": 2,
                    "total": 2,
                    "detail": "Both selected component sources are assessed by the recipes.",
                },
                "dependencies": [],
                "blockers": [],
                "next_action": "Run the canonical project transaction.",
            }

        def census_builder(**kwargs: Any) -> list[dict[str, Any]]:
            selections = kwargs.get("selections") or {}
            return [
                assess_project(
                    project,
                    approved_root=authority_root,
                    selected_components=tuple(selections.get(subject, ())),
                )
            ]

        def plan_issuer(**kwargs: Any) -> Any:
            return issue_plan(**kwargs, root=state_root)

        results: list[CheckResult] = []
        plan_report = build_plan_report(
            request,
            machine_builder=machine_builder,
            census_builder=census_builder,
            plan_issuer=plan_issuer,
        )
        apply_report = build_apply_report(
            request,
            str(plan_report["plan_id"]),
            machine_builder=machine_builder,
            census_builder=census_builder,
            state_root=state_root,
        )
        verify_report = build_verify_report(
            request,
            machine_builder=machine_builder,
            census_builder=census_builder,
        )

        reference_path = _reference_install_manifest_path()
        if reference_path.is_file():
            reference = roundtrip.load_reference_manifest(reference_path)
            results.extend(
                roundtrip.check_produces_reference_install(
                    project=project, reference=reference, subject_prefix=subject
                )
            )
        results.append(
            roundtrip.check_installs_enforcement_hook(project=project, subject=subject)
        )
        results.extend(
            roundtrip.check_reports_only_what_it_did(
                framework_repo_root=framework_repo_root,
                project=project,
                subject=subject,
            )
        )

        before_repeat = _snapshot_tree(project)
        repeat_plan_report = build_plan_report(
            request,
            machine_builder=machine_builder,
            census_builder=census_builder,
            plan_issuer=plan_issuer,
        )
        repeat_apply_report = build_apply_report(
            request,
            str(repeat_plan_report["plan_id"]),
            machine_builder=machine_builder,
            census_builder=census_builder,
            state_root=state_root,
        )
        after_repeat = _snapshot_tree(project)
        results.append(
            roundtrip.check_canonical_transaction(
                subject=subject,
                plan_report=plan_report,
                apply_report=apply_report,
                verify_report=verify_report,
                repeat_plan_report=repeat_plan_report,
                repeat_apply_report=repeat_apply_report,
            )
        )
        results.append(
            roundtrip.check_update_idempotent(
                diff_paths=_diff_paths(before_repeat, after_repeat),
                subject=subject,
                expected_today=ExpectedToday.PASS,
            )
        )

        # Intentional project-owned additions make the fresh assessment hold
        # rather than inventing a mutation recipe. A held apply must preserve
        # them byte-for-byte, which is the safe update behavior under review.
        seeded_agent = roundtrip.seed_project_owned_agent(project)
        seeded_agent_text = seeded_agent.read_text(encoding="utf-8")
        roundtrip.seed_third_party_mcp_server(project)
        mcp_before = _json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
        preservation_plan = build_plan_report(
            request,
            machine_builder=machine_builder,
            census_builder=census_builder,
            plan_issuer=plan_issuer,
        )
        build_apply_report(
            request,
            str(preservation_plan["plan_id"]),
            machine_builder=machine_builder,
            census_builder=census_builder,
            state_root=state_root,
        )
        results.append(
            roundtrip.check_closes_command_gap(project=project, subject=subject)
        )
        results.append(
            roundtrip.check_preserves_project_owned(
                before=seeded_agent_text, after_path=seeded_agent, subject=subject
            )
        )
        results.append(
            roundtrip.check_does_not_touch_mcp_json(
                before=mcp_before, project=project, subject=subject
            )
        )

        return tuple(results)


# ---------------------------------------------------------------------------
# Orchestration -- one layer's crash never aborts the run
# ---------------------------------------------------------------------------


def _safe_run(
    layer: Layer, subject: str, fn: Callable[[], tuple[CheckResult, ...]]
) -> tuple[CheckResult, ...]:
    try:
        return tuple(fn())
    except Exception as exc:  # noqa: BLE001 -- one layer's crash must never abort the others.
        return (
            CheckResult(
                id=f"conformance.{layer.value}.harness_could_not_run",
                layer=layer,
                severity=Severity.S1,
                scope=Scope.GLOBAL,
                subject=subject,
                assertion=(
                    f"the {layer.value} layer's checks can be computed "
                    "against this machine"
                ),
                verdict=Verdict.COULD_NOT_RUN,
                expected_today=ExpectedToday.PASS,
                evidence=(
                    Evidence(
                        kind="exception",
                        path=subject,
                        expected="layer computation completes without raising",
                        actual=f"{type(exc).__name__}: {exc}",
                    ),
                ),
                detail=(
                    f"the {layer.value} layer crashed while gathering "
                    "real-machine input -- not necessarily an ecosystem "
                    "defect, investigate the harness's own wiring first"
                ),
                remediation=(
                    f"re-run with --json for the full traceback context, or "
                    f"isolate with --layer {layer.value} --check <id>"
                ),
            ),
        )


def _filter_by_selected_modes(
    results: tuple[CheckResult, ...], mode: Mode
) -> tuple[CheckResult, ...]:
    """`--fast` runs only FAST-registered checks; `--full` runs FAST+FULL
    (mirrors `sweep.py`'s own `_selected_modes`, generalized here to every
    layer since only `sweep.py` narrows by mode internally)."""

    selected = {Mode.FAST} if mode is Mode.FAST else {Mode.FAST, Mode.FULL}
    kept: list[CheckResult] = []
    for result in results:
        try:
            registration = DEFAULT_REGISTRY.get(result.id)
        except KeyError:
            # Synthetic, never-registered ids (this module's own
            # `harness_could_not_run`, dimensions/'s `.module_unavailable`
            # / `.crashed`) are never hidden by a mode filter --
            # `inv.no_fabricated_healthy`.
            kept.append(result)
            continue
        if registration.mode in selected:
            kept.append(result)
    return tuple(kept)


def _collect_results(
    *,
    layers: Sequence[str],
    mode: Mode,
    repos: Sequence[str] = (),
    classes: Sequence[str] = (),
    repo_classes: Sequence[str] = (),
    check_ids: Sequence[str] = (),
    jobs: int = DEFAULT_JOBS,
    use_cache: bool = True,
    announce: Optional[Callable[[str], None]] = None,
) -> tuple[CheckResult, ...]:
    """The one seam every subcommand funnels through. Kept free of any
    typer/CLI concern so tests can call it directly, and so
    `monkeypatch.setattr(conformance, "_collect_results", ...)` is a valid,
    minimal way to exercise the CLI's exit-code paths (including a forced
    COULD_NOT_RUN) without needing a real fleet on the test machine."""

    _ensure_registry_loaded()
    results: list[CheckResult] = []

    if "tier" in layers:
        results.extend(
            _safe_run(Layer.TIER, "tier layer (real machine)", _run_tier_layer_machine)
        )
    if "stack" in layers:
        results.extend(
            _safe_run(
                Layer.STACK, "stack layer (real machine)", _run_stack_layer_machine
            )
        )
    if "repo" in layers:
        results.extend(
            _safe_run(
                Layer.REPO,
                "repo layer sweep",
                lambda: _run_repo_layer(
                    mode=mode,
                    repos=repos,
                    classes=classes,
                    repo_classes=repo_classes,
                    check_ids=check_ids,
                    jobs=jobs,
                    use_cache=use_cache,
                ),
            )
        )
    if "lock" in layers:
        results.extend(
            _safe_run(
                Layer.LOCK,
                "lock layer (real machine)",
                lambda: _run_lock_layer(
                    repos=repos, classes=classes, repo_classes=repo_classes
                ),
            )
        )
    if "regression" in layers:
        results.extend(
            _safe_run(
                Layer.REGRESSION,
                "root-cause regression sweep",
                root_causes.run_all_root_cause_checks,
            )
        )
    if "roundtrip" in layers:
        if announce is not None:
            announce(_ROUNDTRIP_MUTATION_NOTICE)
        results.extend(
            _safe_run(Layer.ROUNDTRIP, "round-trip scratch clone", _run_roundtrip_layer)
        )

    filtered = _filter_by_selected_modes(tuple(results), mode)
    filtered = report.deduplicate_global_results(filtered)
    filtered = report.filter_by_repo(filtered, repos)
    if check_ids:
        wanted = set(check_ids)
        filtered = tuple(result for result in filtered if result.id in wanted)
    return report.attribute_could_not_run_results(filtered)


# ---------------------------------------------------------------------------
# CLI argument parsing helpers (this module's own idiom, mirrors main.py's
# "echo + typer.Exit(2)" convention -- no typer.BadParameter anywhere in
# this codebase, see this file's docstring).
# ---------------------------------------------------------------------------


def _emit_argument_error(
    message: str, output_json: bool, *, code: str = "invalid-argument"
) -> None:
    if output_json:
        typer.echo(
            _json.dumps(
                {"schema_version": "1.0", "error": {"code": code, "message": message}}
            )
        )
    else:
        typer.echo(message, err=True)


def _resolve_layers(
    raw: Optional[Sequence[str]], *, command: str, output_json: bool, mode: Mode
) -> tuple[str, ...]:
    if not raw:
        return FULL_CHECK_LAYERS if mode is Mode.FULL else DEFAULT_CHECK_LAYERS
    deduped = tuple(dict.fromkeys(raw))
    unknown = [value for value in deduped if value not in ALL_LAYER_CHOICES]
    if unknown:
        _emit_argument_error(
            f"conformance {command}: unknown --layer value(s) {unknown!r}; "
            f"choose from {list(ALL_LAYER_CHOICES)!r}",
            output_json,
        )
        raise typer.Exit(2)
    return deduped


def _resolve_class_filters(
    raw: Optional[Sequence[str]], *, command: str, output_json: bool
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """`--class` accepts EITHER a rubric letter (`A`..`E`, case-insensitive
    -- `Registry.select(classes=...)`'s own vocabulary, unchanged) OR a
    `classification.toml` taxonomy name (`COMPONENT`/`PRODUCT`/`SITE-
    CONTENT`/`DOCS-KNOWLEDGE`/`SCRATCH-ARCHIVE`, case-insensitive, `_`/`-`
    interchangeable) -- never both meanings silently collapsed into one.
    Returns `(rubric_letters, classification_names)`, each ready to hand
    straight to `sweep.SweepOptions(classes=..., repo_classes=...)` /
    `_run_lock_layer`'s matching filter, which AND the two together exactly
    like `--repo` already ANDs with `--class`.

    A value that matches NEITHER vocabulary is a loud, exit-2 argument
    error naming every value that DOES work -- silently matching zero repos
    (the bug this replaces: `--class PRODUCT` compared literally against
    single-letter rubric codes and always came back empty) is never an
    acceptable outcome for an unrecognized filter value."""

    if not raw:
        return (), ()
    letters: list[str] = []
    names: list[str] = []
    unknown: list[str] = []
    for value in raw:
        upper = value.strip().upper()
        if upper in REPO_CLASSES:
            letters.append(upper)
            continue
        normalized = upper.replace("_", "-")
        try:
            names.append(classes_mod.RepoClass(normalized).value)
            continue
        except ValueError:
            pass
        unknown.append(value)
    if unknown:
        _emit_argument_error(
            f"conformance {command}: unknown --class value(s) {unknown!r}; "
            f"choose a rubric letter from {list(RUBRIC_CLASS_CHOICES)!r} or "
            f"a classification.toml class from {list(CLASSIFICATION_NAME_CHOICES)!r}",
            output_json,
        )
        raise typer.Exit(2)
    return tuple(dict.fromkeys(letters)), tuple(dict.fromkeys(names))


def _parse_severity(value: str, *, command: str, output_json: bool) -> Severity:
    try:
        return Severity(value)
    except ValueError:
        _emit_argument_error(
            f"conformance {command}: unknown --fail-on value {value!r}; "
            f"choose from {list(SEVERITY_CHOICES)!r}",
            output_json,
        )
        raise typer.Exit(2)


# ---------------------------------------------------------------------------
# report --format renderers this module owns (md/tsv) -- `report.py`
# (WP-1) is never edited; these are presentation-only, built from its
# already-computed `Summary`/`group_by_root_cause` data.
# ---------------------------------------------------------------------------


def _render_tsv(results: Sequence[CheckResult]) -> str:
    lines = ["id\tlayer\tseverity\tverdict\tsubject\tdetail"]
    for result in results:
        detail = result.detail.replace("\t", " ").replace("\n", " ")
        lines.append(
            f"{result.id}\t{result.layer.value}\t{result.severity.value}\t"
            f"{result.verdict.value}\t{result.subject}\t{detail}"
        )
    text = "\n".join(lines)
    report.assert_no_bare_ready(text)
    if "%" in text:
        raise AssertionError(
            "conformance report --format tsv must never print a percentage "
            "(HARNESS-DESIGN.md section 3.2 rule 4)."
        )
    return text


def _render_markdown(
    results: Sequence[CheckResult],
    *,
    mode: Mode,
    baseline: Optional[report.BaselineComparison] = None,
) -> str:
    summary = report.summarize(results)
    lines: list[str] = [f"# Copilot Ecosystem Conformance -- {mode.value}", ""]
    lines.append("| severity | failing |")
    lines.append("|---|---|")
    for severity in Severity:
        lines.append(f"| {severity.value} | {summary.by_severity[severity.value]} |")
    lines.append("")

    grouped = report.group_by_root_cause(results)
    if grouped:
        lines.append("## Failures by root cause")
        lines.append("")
        for cause, items in sorted(grouped.items()):
            lines.append(f"- **{cause}** ({len(items)}): {items[0].assertion}")
        lines.append("")

    if summary.could_not_run_total:
        lines.append(
            f"**COULD-NOT-RUN**: {summary.could_not_run_total} check(s) -- not a pass."
        )
        lines.append("")

    if baseline is not None:
        lines.append(
            f"Baseline `{baseline.file}`: fixed {len(baseline.fixed)}, "
            f"still-failing {len(baseline.still_failing)}, "
            f"regressed {len(baseline.regressed)}, "
            f"new {len(baseline.new_failures)}"
        )

    text = "\n".join(lines)
    report.assert_no_bare_ready(text)
    if "%" in text:
        raise AssertionError(
            "conformance report --format md must never print a percentage "
            "(HARNESS-DESIGN.md section 3.2 rule 4)."
        )
    return text


# ---------------------------------------------------------------------------
# cc conformance check
# ---------------------------------------------------------------------------


@conformance_app.command("check")
def check_cmd(
    layer: Optional[List[str]] = typer.Option(
        None,
        "--layer",
        help=(
            "Restrict to one or more layers "
            f"({'|'.join(ALL_LAYER_CHOICES)}); default is every layer "
            "except roundtrip; --full includes roundtrip in a disposable scratch clone."
        ),
    ),
    fast: bool = typer.Option(
        False, "--fast", help="Local-only, cached, no network (the default)."
    ),
    full: bool = typer.Option(
        False,
        "--full",
        help="Everything --fast covers plus network/git-remote checks; bypasses the cache.",
    ),
    repo: Optional[List[str]] = typer.Option(
        None,
        "--repo",
        help="Restrict to one or more repos (path or path-suffix match).",
    ),
    repo_class: Optional[List[str]] = typer.Option(
        None,
        "--class",
        help=(
            "Restrict to one or more rubric classes (A|B|C|D|E) or "
            "classification.toml classes "
            f"({'|'.join(CLASSIFICATION_NAME_CHOICES)})."
        ),
    ),
    check_id: Optional[List[str]] = typer.Option(
        None, "--check", help="Restrict to one or more specific check ids."
    ),
    fail_on: str = typer.Option(
        "S3",
        "--fail-on",
        help="Exit non-zero if any check at or above this severity fails (S0|S1|S2|S3).",
    ),
    baseline: Optional[Path] = typer.Option(
        None,
        "--baseline",
        help=(
            "Compare against a frozen baseline (cc conformance baseline "
            "write); a PASS->FAIL regression forces exit 3."
        ),
    ),
    jobs: int = typer.Option(
        DEFAULT_JOBS, "--jobs", help="Parallel workers for the repo-layer sweep."
    ),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Bypass the per-repo fast-mode cache even in --fast mode.",
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Output the conformance.schema.json envelope as JSON."
    ),
) -> None:
    """Run the ecosystem conformance harness and report pass/fail.

    Exit codes: 0 conforms, 1 a check failed, 2 the harness could not run
    at least one selected check, 3 a --baseline comparison found a
    PASS->FAIL regression. Precedence: baseline-regression > could-not-run
    > fail (HARNESS-DESIGN.md section 6.4).
    """

    if fast and full:
        _emit_argument_error(
            "conformance check: --fast and --full are mutually exclusive.", output_json
        )
        raise typer.Exit(2)

    mode = Mode.FULL if full else Mode.FAST
    layers = _resolve_layers(layer, command="check", output_json=output_json, mode=mode)
    fail_on_severity = _parse_severity(
        fail_on, command="check", output_json=output_json
    )
    rubric_classes, classification_names = _resolve_class_filters(
        repo_class, command="check", output_json=output_json
    )

    baseline_entries: tuple[report.BaselineEntry, ...] = ()
    if baseline is not None:
        if not baseline.is_file():
            _emit_argument_error(
                f"conformance check: --baseline file not found: {baseline}", output_json
            )
            raise typer.Exit(2)
        baseline_entries = report.load_baseline(baseline)

    try:
        results = _collect_results(
            layers=layers,
            mode=mode,
            repos=repo or (),
            classes=rubric_classes,
            repo_classes=classification_names,
            check_ids=check_id or (),
            jobs=jobs,
            use_cache=not no_cache,
            announce=lambda text: typer.echo(text, err=True),
        )
    except Exception as exc:  # environment/unexpected error -> exit 2
        _emit_argument_error(
            f"conformance check: environment error: {exc}",
            output_json,
            code="environment-error",
        )
        raise typer.Exit(2) from exc

    baseline_comparison: Optional[report.BaselineComparison] = None
    if baseline is not None:
        baseline_comparison = report.compare_to_baseline(
            results, baseline_entries, file=str(baseline)
        )

    exit_code = report.compute_exit_code(
        results, fail_on=fail_on_severity, baseline=baseline_comparison
    )

    if output_json:
        envelope = report.to_envelope(results, mode=mode, baseline=baseline_comparison)
        typer.echo(_json.dumps(envelope))
    else:
        typer.echo(
            report.render_human(
                results,
                mode=mode,
                fail_on=fail_on_severity,
                baseline=baseline_comparison,
            )
        )

    raise typer.Exit(exit_code)


# ---------------------------------------------------------------------------
# cc conformance report
# ---------------------------------------------------------------------------


@conformance_app.command("report")
def report_cmd(
    layer: Optional[List[str]] = typer.Option(
        None,
        "--layer",
        help="Restrict layers; fast/default excludes roundtrip, while --full includes its disposable scratch clone.",
    ),
    fast: bool = typer.Option(
        False, "--fast", help="Local-only, cached, no network (the default)."
    ),
    full: bool = typer.Option(
        False, "--full", help="Everything --fast covers plus network/git-remote checks."
    ),
    repo: Optional[List[str]] = typer.Option(
        None,
        "--repo",
        help="Restrict to one or more repos (path or path-suffix match).",
    ),
    repo_class: Optional[List[str]] = typer.Option(
        None,
        "--class",
        help=(
            "Restrict to one or more rubric classes (A|B|C|D|E) or "
            "classification.toml classes "
            f"({'|'.join(CLASSIFICATION_NAME_CHOICES)})."
        ),
    ),
    check_id: Optional[List[str]] = typer.Option(
        None, "--check", help="Restrict to one or more specific check ids."
    ),
    baseline: Optional[Path] = typer.Option(
        None,
        "--baseline",
        help="Compare against a frozen baseline and include fixed/still-failing/new counts.",
    ),
    jobs: int = typer.Option(
        DEFAULT_JOBS, "--jobs", help="Parallel workers for the repo-layer sweep."
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Bypass the per-repo fast-mode cache."
    ),
    output_format: str = typer.Option(
        "table", "--format", help="table|tsv|md|json -- how to render the results."
    ),
) -> None:
    """Render the ecosystem conformance harness's results in the requested format."""

    output_json = output_format == "json"
    if output_format not in {"table", "tsv", "md", "json"}:
        _emit_argument_error(
            f"conformance report: unknown --format {output_format!r}; "
            "choose from table|tsv|md|json",
            output_json=False,
        )
        raise typer.Exit(2)

    if fast and full:
        _emit_argument_error(
            "conformance report: --fast and --full are mutually exclusive.", output_json
        )
        raise typer.Exit(2)

    mode = Mode.FULL if full else Mode.FAST
    layers = _resolve_layers(
        layer, command="report", output_json=output_json, mode=mode
    )
    rubric_classes, classification_names = _resolve_class_filters(
        repo_class, command="report", output_json=output_json
    )

    baseline_entries: tuple[report.BaselineEntry, ...] = ()
    if baseline is not None:
        if not baseline.is_file():
            _emit_argument_error(
                f"conformance report: --baseline file not found: {baseline}",
                output_json,
            )
            raise typer.Exit(2)
        baseline_entries = report.load_baseline(baseline)

    try:
        results = _collect_results(
            layers=layers,
            mode=mode,
            repos=repo or (),
            classes=rubric_classes,
            repo_classes=classification_names,
            check_ids=check_id or (),
            jobs=jobs,
            use_cache=not no_cache,
            announce=lambda text: typer.echo(text, err=True),
        )
    except Exception as exc:  # environment/unexpected error -> exit 2
        _emit_argument_error(
            f"conformance report: environment error: {exc}",
            output_json,
            code="environment-error",
        )
        raise typer.Exit(2) from exc

    baseline_comparison: Optional[report.BaselineComparison] = None
    if baseline is not None:
        baseline_comparison = report.compare_to_baseline(
            results, baseline_entries, file=str(baseline)
        )

    exit_code = report.compute_exit_code(results, baseline=baseline_comparison)

    if output_format == "json":
        typer.echo(
            _json.dumps(
                report.to_envelope(results, mode=mode, baseline=baseline_comparison)
            )
        )
    elif output_format == "tsv":
        typer.echo(_render_tsv(results))
    elif output_format == "md":
        typer.echo(_render_markdown(results, mode=mode, baseline=baseline_comparison))
    else:
        typer.echo(
            report.render_human(results, mode=mode, baseline=baseline_comparison)
        )

    raise typer.Exit(exit_code)


# ---------------------------------------------------------------------------
# cc conformance baseline write|diff
# ---------------------------------------------------------------------------


@baseline_app.command("write")
def baseline_write_cmd(
    path: Path = typer.Argument(..., help="Where to write the frozen baseline JSON."),
    layer: Optional[List[str]] = typer.Option(
        None,
        "--layer",
        help="Restrict layers; fast/default excludes roundtrip, while --full includes its disposable scratch clone.",
    ),
    fast: bool = typer.Option(
        False, "--fast", help="Local-only, cached, no network (the default)."
    ),
    full: bool = typer.Option(
        False, "--full", help="Everything --fast covers plus network/git-remote checks."
    ),
    jobs: int = typer.Option(
        DEFAULT_JOBS, "--jobs", help="Parallel workers for the repo-layer sweep."
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Bypass the per-repo fast-mode cache."
    ),
) -> None:
    """Freeze the current verdict set as a baseline (`cc conformance check
    --baseline`/`cc conformance baseline diff` compare future runs against
    it)."""

    if fast and full:
        typer.echo(
            "conformance baseline write: --fast and --full are mutually exclusive.",
            err=True,
        )
        raise typer.Exit(2)

    mode = Mode.FULL if full else Mode.FAST
    layers = _resolve_layers(
        layer, command="baseline write", output_json=False, mode=mode
    )

    try:
        results = _collect_results(
            layers=layers,
            mode=mode,
            jobs=jobs,
            use_cache=not no_cache,
            announce=lambda text: typer.echo(text, err=True),
        )
    except Exception as exc:  # environment/unexpected error -> exit 2
        typer.echo(f"conformance baseline write: environment error: {exc}", err=True)
        raise typer.Exit(2) from exc

    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entries": [
            {
                "id": result.id,
                "subject": result.subject,
                "verdict": result.verdict.value,
            }
            for result in results
        ],
    }
    path.write_text(
        _json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    typer.echo(f"conformance baseline: wrote {len(results)} entries to {path}")


@baseline_app.command("diff")
def baseline_diff_cmd(
    path: Path = typer.Argument(
        ..., help="An existing baseline JSON (from `baseline write`)."
    ),
    layer: Optional[List[str]] = typer.Option(
        None,
        "--layer",
        help="Restrict layers; fast/default excludes roundtrip, while --full includes its disposable scratch clone.",
    ),
    fast: bool = typer.Option(
        False, "--fast", help="Local-only, cached, no network (the default)."
    ),
    full: bool = typer.Option(
        False, "--full", help="Everything --fast covers plus network/git-remote checks."
    ),
    jobs: int = typer.Option(
        DEFAULT_JOBS, "--jobs", help="Parallel workers for the repo-layer sweep."
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Bypass the per-repo fast-mode cache."
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Output the comparison as JSON."
    ),
) -> None:
    """Show what changed since a frozen baseline. Exit 3 on any PASS->FAIL
    regression, else 0 -- independent of --fail-on (there is none here;
    this command reports, it never gates on absolute severity)."""

    if not path.is_file():
        _emit_argument_error(
            f"conformance baseline diff: baseline file not found: {path}", output_json
        )
        raise typer.Exit(2)
    if fast and full:
        _emit_argument_error(
            "conformance baseline diff: --fast and --full are mutually exclusive.",
            output_json,
        )
        raise typer.Exit(2)

    mode = Mode.FULL if full else Mode.FAST
    layers = _resolve_layers(
        layer, command="baseline diff", output_json=output_json, mode=mode
    )
    baseline_entries = report.load_baseline(path)

    try:
        results = _collect_results(
            layers=layers,
            mode=mode,
            jobs=jobs,
            use_cache=not no_cache,
            announce=lambda text: typer.echo(text, err=True),
        )
    except Exception as exc:  # environment/unexpected error -> exit 2
        _emit_argument_error(
            f"conformance baseline diff: environment error: {exc}",
            output_json,
            code="environment-error",
        )
        raise typer.Exit(2) from exc

    comparison = report.compare_to_baseline(results, baseline_entries, file=str(path))
    exit_code = 3 if comparison.has_regression else 0

    if output_json:
        typer.echo(_json.dumps(comparison.as_dict()))
    else:
        typer.echo(
            f"BASELINE  {comparison.file}    fixed {len(comparison.fixed)}    "
            f"still-failing {len(comparison.still_failing)}    "
            f"regressed {len(comparison.regressed)}    "
            f"new {len(comparison.new_failures)}"
        )

    raise typer.Exit(exit_code)


# ---------------------------------------------------------------------------
# cc conformance explain
# ---------------------------------------------------------------------------


@conformance_app.command("explain")
def explain_cmd(
    check_id: str = typer.Argument(
        ..., help="A registered check id, e.g. tier.shadow.substance."
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Output the registration plus live evidence as JSON."
    ),
) -> None:
    """Print one check's assertion, remediation, and (for non-mutating
    layers) freshly recomputed evidence against this machine."""

    _ensure_registry_loaded()
    try:
        registration = DEFAULT_REGISTRY.get(check_id)
    except KeyError:
        message = (
            f"conformance explain: no check registered with id {check_id!r}. "
            "Run `cc conformance list` to see valid ids."
        )
        _emit_argument_error(message, output_json, code="unknown-check-id")
        raise typer.Exit(2)

    live_results: tuple[CheckResult, ...] = ()
    live_note = ""
    if registration.layer is Layer.ROUNDTRIP:
        live_note = (
            "roundtrip checks mutate a disposable scratch clone -- explain "
            "never runs them live. Re-run `cc conformance check --layer "
            f"roundtrip --check {check_id}` to see fresh evidence."
        )
    else:
        try:
            live_results = _collect_results(
                layers=(registration.layer.value,),
                mode=registration.mode,
                check_ids=(check_id,),
            )
        except (
            Exception
        ) as exc:  # pragma: no cover -- _safe_run already guards each layer
            live_note = f"could not recompute live evidence: {exc}"

    if output_json:
        payload = {
            "schema_version": "1.0",
            "registration": registration.as_dict(),
            "live_results": [result.as_dict() for result in live_results],
            "note": live_note,
        }
        typer.echo(_json.dumps(payload))
        return

    typer.echo(
        f"{registration.id}  [{registration.layer.value} / "
        f"{registration.severity.value} / {registration.mode.value}]"
    )
    typer.echo(f"asserts:     {registration.summary}")
    typer.echo(f"remediation: {registration.remediation}")
    if registration.applies_to_classes:
        typer.echo(
            f"applies to:  class {', '.join(sorted(registration.applies_to_classes))}"
        )
    if live_note:
        typer.echo(live_note)
    if not live_results:
        if not live_note:
            typer.echo(
                "(no live evidence produced -- this check may not apply to "
                "any subject on this machine)"
            )
        return
    for result in live_results:
        typer.echo("")
        typer.echo(f"subject:  {result.subject}")
        typer.echo(f"verdict:  {result.verdict.value}")
        if result.detail:
            typer.echo(f"detail:   {result.detail}")
        for entry in result.evidence:
            typer.echo(f"evidence: {entry.path}")
            typer.echo(f"          expected={entry.expected!r} actual={entry.actual!r}")
            if entry.detail:
                typer.echo(f"          {entry.detail}")


# ---------------------------------------------------------------------------
# cc conformance list
# ---------------------------------------------------------------------------


@conformance_app.command("list")
def list_cmd(
    layer: Optional[List[str]] = typer.Option(
        None, "--layer", help="Filter to one or more layers."
    ),
    severity: Optional[List[str]] = typer.Option(
        None, "--severity", help="Filter to one or more severities (S0|S1|S2|S3)."
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Output the filtered registration list as JSON."
    ),
) -> None:
    """List every registered conformance check id."""

    _ensure_registry_loaded()

    layer_filter: set[Layer] = set()
    for value in layer or ():
        try:
            layer_filter.add(Layer(value))
        except ValueError:
            _emit_argument_error(
                f"conformance list: unknown --layer value {value!r}", output_json
            )
            raise typer.Exit(2)

    severity_filter: set[Severity] = set()
    for value in severity or ():
        try:
            severity_filter.add(Severity(value))
        except ValueError:
            _emit_argument_error(
                f"conformance list: unknown --severity value {value!r}", output_json
            )
            raise typer.Exit(2)

    registrations = sorted(
        DEFAULT_REGISTRY.all(), key=lambda registration: registration.id
    )
    if layer_filter:
        registrations = [r for r in registrations if r.layer in layer_filter]
    if severity_filter:
        registrations = [r for r in registrations if r.severity in severity_filter]

    if output_json:
        typer.echo(_json.dumps([r.as_dict() for r in registrations]))
        return

    for r in registrations:
        typer.echo(
            f"{r.id:<55} {r.layer.value:<10} {r.severity.value:<3} {r.mode.value:<4}  {r.summary}"
        )


__all__ = ["baseline_app", "conformance_app"]
