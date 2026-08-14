#!/usr/bin/env python3
"""Generate a conformance-harness baseline from a REAL, live run against
this machine's real ecosystem state -- never by hand.

WP-9 owns this file (and everything else under `tests/conformance/
baselines/`). It is a standalone script, not a pytest test, and not part of
`cc conformance` (that CLI verb family is WP-8's, and may not exist yet in
every checkout this script runs in) -- so baseline generation never blocks
on, or depends on, the CLI surface landing.

WHAT THIS PRODUCES
-------------------
A JSON file shaped `{"generated_at", "reason", "generated_by", "host",
"mode", "counts", "entries": [{"id", "subject", "verdict"}, ...]}`.
`report.load_baseline()` (WP-1, `core/conformance/report.py`) reads only the
`entries` list -- the other top-level keys are this script's own audit
trail, ignored by every consumer, kept so a reviewer looking at the file's
history can see WHY and BY WHOM it was regenerated without needing `git
blame` archaeology.

WHAT IT RUNS (all six layers, against the real machine, read-only except
Layer 5's isolated scratch clones -- HARNESS-DESIGN.md section 5.3):
  Layer 1 (tier)       -- H-1..H-8 against the real manifest/config/agents.
                          H-9 has NO LIVE INSTANCE on this machine
                          (TEST-MATRIX.md section 7 items 9/10) and is
                          correctly absent from the baseline, not faked.
  Layer 2 (stack)       -- stack.run_stack_checks against every real
                          copilot.layers.yml this machine has.
  Layer 3 (repo sweep)  -- sweep.run_sweep(mode=FULL) over every repo under
                          projects.roots (13 dimensions x ~75 repos).
  Layer 4 (lock)        -- lock.run_lock_checks over the same repo set.
  Layer 5 (round-trip)  -- the canonical request / reviewed plan / guarded
                          apply / fresh verify transaction, executed against
                          one disposable scratch project. Mutates only a
                          `tempfile.TemporaryDirectory()`.
  Layer 6 (regression)  -- root_causes.run_all_root_cause_checks (RC-1..5).

REGENERATION IS DELIBERATELY NOT TRIVIAL
------------------------------------------
Default behavior is a DRY RUN: this script always computes and prints a
summary, and writes nothing unless `--write` is given. If a baseline
already exists at the target path, writing a new one additionally requires:
  1. `--reason "<why>"` -- mandatory, non-empty, stored in the file. A
     baseline regenerated with no stated reason is exactly the "quietly
     refreshed to paper over a regression" failure mode this mechanism
     exists to prevent.
  2. If the fresh run's verdicts, compared against the EXISTING baseline
     via `report.compare_to_baseline`, contain any REGRESSION (something
     that was PASS in the old baseline and is FAIL now) -- which is
     precisely the shape of "a check broke and someone tried to make that
     look normal by refreshing the baseline instead of fixing it" -- this
     script refuses to write and prints every regressed `(id, subject)`
     pair, UNLESS `--acknowledge-regression` is also passed. Even then, the
     regressed pairs are written into the file's own `"acknowledged_
     regressions"` metadata list, so the fact that a regression was
     knowingly baked into a new baseline is itself part of the permanent,
     reviewable record -- never silent. `--review-file` must additionally
     match every such delta exactly and provide classification, rationale,
     and owner. Every other added, removed, or changed identity is classified
     automatically in `change_review.changes`.

USAGE
-----
    tools/cc/.venv/bin/python tools/cc/tests/conformance/baselines/generate_baseline.py \\
        --reason "initial baseline capture" --write

    # Dry run (default) -- prints the summary, writes nothing:
    tools/cc/.venv/bin/python tools/cc/tests/conformance/baselines/generate_baseline.py

Run via the framework's own `tools/cc/.venv` interpreter so `cc` resolves
as the editable-installed package this repo already uses everywhere else
(`sys.path` is adjusted defensively below so a bare system `python3` also
works, but is not the documented path).
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Make `cc` importable even under a bare system interpreter (defensive only
# -- the documented invocation already runs under tools/cc/.venv, where `cc`
# is already an editable-installed package and this is a no-op).
# ---------------------------------------------------------------------------

_THIS_FILE = Path(__file__).resolve()
_BASELINES_DIR = _THIS_FILE.parent  # tests/conformance/baselines
_CONFORMANCE_TESTS_DIR = _BASELINES_DIR.parent  # tests/conformance
_TESTS_DIR = _CONFORMANCE_TESTS_DIR.parent  # tools/cc/tests
_CC_TOOL_ROOT = _TESTS_DIR.parent  # tools/cc
_TOOLS_DIR = _CC_TOOL_ROOT.parent  # tools
_FRAMEWORK_ROOT = _TOOLS_DIR.parent  # claude-copilot repo root
_SRC = _CC_TOOL_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cc.core.conformance import report, root_causes, tier  # noqa: E402
from cc.core.conformance.lock import run_lock_checks  # noqa: E402
from cc.core.conformance.stack import (  # noqa: E402
    discover_real_manifest_paths,
    run_stack_checks,
)
from cc.core.conformance.sweep import (  # noqa: E402
    SweepOptions,
    discover_repos,
    run_sweep,
)
from cc.core.conformance.types import CheckResult, ExpectedToday, Mode  # noqa: E402
from cc.core.ecosystem.manifest import load_layers, validate_layers  # noqa: E402

DEFAULT_BASELINE_PATH = _BASELINES_DIR / "2026-08-12-reviewed-current.json"

_REAL_HOME = Path.home()
_REAL_MACHINE_CONFIG_PATH = _REAL_HOME / ".claude" / "cc" / "config.json"
_REAL_MANIFEST_PATH = _REAL_HOME / ".config" / "copilot" / "copilot.layers.yml"
_AGENTS_DIR = _FRAMEWORK_ROOT / ".claude" / "agents"
_REAL_AGENT_FILES = ("cw.md", "sd.md", "ta.md")
_REFERENCE_MANIFEST_PATH = (
    _CONFORMANCE_TESTS_DIR / "fixtures" / "reference-install" / "manifest.json"
)


# ---------------------------------------------------------------------------
# Layer 1 -- tier / hierarchy resolution, real machine
# ---------------------------------------------------------------------------


def _real_knowledge_ladder() -> list[str]:
    """`paths.knowledge_repo`, read directly from the real machine config.

    Deliberately NOT imported from `test_layer1_tier.py`'s identical helper
    -- that test file belongs to WP-2, which this package (WP-9) does not
    touch (see the task's file-ownership rule). This script owns its own,
    independent real-data assembly, which also means WP-2's fixture tests
    and this generator can never silently share a bug.
    """

    config = json.loads(_REAL_MACHINE_CONFIG_PATH.read_text(encoding="utf-8"))
    value = (config.get("paths") or {}).get("knowledge_repo")
    if isinstance(value, list):
        return [str(entry) for entry in value if entry]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _always_available(_required: list[str]) -> list[str]:
    """`missing_skills_checker` stub matching WP-2's own fixture tests: every
    required skill is treated as available, isolating H-1/H-2/H-3 from the
    real global skill store (a separate, unrelated concern)."""

    return []


def collect_layer1_tier() -> list[CheckResult]:
    """H-1 through H-8 against the real manifest / config / framework
    agents. H-9 (`tier.config.project_overrides_machine_ladder`) has NO
    LIVE INSTANCE on this machine (every real project config uses the
    `@machine` sentinel, never a literal override -- TEST-MATRIX.md section
    7 item 10) and is correctly omitted, not fabricated."""

    if not (_REAL_MACHINE_CONFIG_PATH.is_file() and _REAL_MANIFEST_PATH.is_file()):
        return []

    ladder = _real_knowledge_ladder()
    results: list[CheckResult] = []

    if ladder:
        results.append(
            tier.check_h1_nearest_declared_wins(
                "cw", knowledge_repos=ladder, missing_skills_checker=_always_available
            )
        )
        results.append(
            tier.check_h1_nearest_declared_wins(
                "sd", knowledge_repos=ladder, missing_skills_checker=_always_available
            )
        )
        for agent in ("do", "ind", "sd", "uxd"):
            results.append(
                tier.check_h2_absence_is_not_shadow(
                    agent,
                    knowledge_repos=ladder,
                    missing_skills_checker=_always_available,
                )
            )
        results.append(
            tier.check_h3_shadow_substance(
                "cw", knowledge_repos=ladder, missing_skills_checker=_always_available
            )
        )

    if _REAL_MANIFEST_PATH.is_file():
        layers = validate_layers(load_layers(_REAL_MANIFEST_PATH))
        expected_ladder = list(tier.knowledge_ladder_from_layers(layers))
        results.append(
            tier.check_h4_ladder_order(
                actual_ladder=ladder, expected_ladder=expected_ladder
            )
        )

    agent_paths = [_AGENTS_DIR / name for name in _REAL_AGENT_FILES]
    if ladder and all(path.is_file() for path in agent_paths):
        agent_files = {
            path.name: path.read_text(encoding="utf-8") for path in agent_paths
        }
        results.extend(
            tier.check_h5_singular_alias_paths_exist(
                agent_files=agent_files, cc_knowledge_repo=ladder[0]
            )
        )

    if ladder:
        labels = [f"rank-{idx}" for idx in range(len(ladder))]
        tier_repos = dict(zip(labels, ladder))
        results.extend(tier.check_h6_declared_skill_paths_exist(tier_repos=tier_repos))
        results.append(tier.check_h7_no_hollow_rung(tier_repos=tier_repos))

    cc_source_root = _CC_TOOL_ROOT / "src" / "cc"
    if cc_source_root.is_dir():
        results.append(
            tier.check_h8_commands_dimension_has_no_consumer(
                source_root=cc_source_root
            )
        )

    return results


# ---------------------------------------------------------------------------
# Layer 2 -- component stack, real machine
# ---------------------------------------------------------------------------


def collect_layer2_stack() -> list[CheckResult]:
    manifest_paths = discover_real_manifest_paths()
    if not manifest_paths:
        return []
    return list(run_stack_checks(manifest_paths=manifest_paths))


# ---------------------------------------------------------------------------
# Layer 3 -- install conformance sweep, real machine
# ---------------------------------------------------------------------------


def collect_layer3_repo(*, mode: Mode) -> list[CheckResult]:
    sweep_result = run_sweep(SweepOptions(mode=mode, use_cache=False))
    return list(sweep_result.results)


# ---------------------------------------------------------------------------
# Layer 4 -- lock integrity, real machine
# ---------------------------------------------------------------------------


def collect_layer4_lock() -> list[CheckResult]:
    repos = [str(repo.path) for repo in discover_repos()]
    if not repos:
        return []
    return list(run_lock_checks(repos))


# ---------------------------------------------------------------------------
# Layer 5 -- round-trip, real installer bash against disposable scratch
# clones. Never a real product repo (HARNESS-DESIGN.md section 5.3).
# ---------------------------------------------------------------------------


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "conformance-baseline@invalid"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Conformance Baseline Generator"],
        cwd=path,
        check=True,
    )


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    """Path -> content, excluding `.git/` and `.claude/memory/` (volatile,
    machine-local state -- not part of the installed tree's identity).
    Mirrors `test_layer5_roundtrip.py`'s own `_tree_snapshot`, independently
    implemented here for the same file-ownership reason as
    `_real_knowledge_ladder` above."""

    snapshot: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        parts = relative.parts
        if parts[0] == ".git":
            continue
        if parts[:2] == (".claude", "memory"):
            continue
        snapshot[str(relative)] = path.read_bytes()
    return snapshot


def _diff_relative_paths(before: dict[str, bytes], after: dict[str, bytes]) -> set[str]:
    return {key for key in {*before, *after} if before.get(key) != after.get(key)}


def collect_layer5_roundtrip() -> list[CheckResult]:
    """Runs the REAL `setup-project.md` / `update-project.md` bash steps
    against disposable `tempfile.TemporaryDirectory()` scratch clones.
    Covers RT-1 (multi-facet), RT-2, RT-3, RT-4, RT-6, and the
    does-not-touch-.mcp.json check -- everything TEST-MATRIX.md section 5
    predicts EXCEPT RT-5 (`codex-copilot/scripts/setup-project.sh`'s
    second-run behavior), which lives in a different repo entirely and is
    out of this package's scope (the same scoping decision
    `test_layer5_roundtrip.py`'s own module docstring states; the
    underlying regression is instead covered here via Layer 6's
    `rc.rc2.codex_has_an_updater`)."""

    from cc.core.conformance import roundtrip as rt

    try:
        framework_repo_root = rt.discover_framework_repo_root(start=_THIS_FILE.parent)
        cc_bin = rt.discover_cc_bin(framework_repo_root)
    except Exception as exc:  # noqa: BLE001 - report, never crash the whole run
        print(f"  [layer5] skipped: {exc}", file=sys.stderr)
        return []

    if not _REFERENCE_MANIFEST_PATH.is_file():
        print(
            f"  [layer5] skipped: no reference manifest at {_REFERENCE_MANIFEST_PATH}",
            file=sys.stderr,
        )
        return []

    reference = rt.load_reference_manifest(_REFERENCE_MANIFEST_PATH)
    results: list[CheckResult] = []

    # -- rt1 / rt2 / rt3 / rt4: one scratch project, setup then update twice.
    with tempfile.TemporaryDirectory(prefix="cc-conformance-baseline-main-") as raw:
        tmp_path = Path(raw)
        home = tmp_path / "home"
        rt.materialize_framework_source(
            home / ".claude" / "copilot", framework_repo_root
        )
        project = tmp_path / "project"
        project.mkdir()
        _init_git_repo(project)

        rt.run_setup_project(
            project, framework_repo_root=framework_repo_root, home=home, cc_bin=cc_bin
        )
        results.extend(
            rt.check_produces_reference_install(
                project=project, reference=reference, subject_prefix="rt1-setup"
            )
        )
        results.extend(
            rt.check_reports_only_what_it_did(
                framework_repo_root=framework_repo_root,
                project=project,
                subject="rt1-setup",
            )
        )
        results.append(rt.check_installs_enforcement_hook(project=project, subject="rt4"))

        rt.run_update_project(
            project, framework_repo_root=framework_repo_root, home=home, cc_bin=cc_bin
        )
        results.append(rt.check_closes_command_gap(project=project, subject="rt2"))

        after_first_update = _tree_snapshot(project)
        rt.run_update_project(
            project, framework_repo_root=framework_repo_root, home=home, cc_bin=cc_bin
        )
        after_second_update = _tree_snapshot(project)
        diff_paths = sorted(
            _diff_relative_paths(after_first_update, after_second_update)
        )
        expected_today = ExpectedToday.FAIL if diff_paths else ExpectedToday.PASS
        results.append(
            rt.check_update_idempotent(
                diff_paths=diff_paths, subject="rt3", expected_today=expected_today
            )
        )

    # -- rt6: the never-destroy invariant, a fresh scratch project.
    with tempfile.TemporaryDirectory(prefix="cc-conformance-baseline-rt6-") as raw:
        tmp_path = Path(raw)
        home = tmp_path / "home"
        rt.materialize_framework_source(
            home / ".claude" / "copilot", framework_repo_root
        )
        project = tmp_path / "project"
        project.mkdir()
        _init_git_repo(project)

        rt.run_setup_project(
            project, framework_repo_root=framework_repo_root, home=home, cc_bin=cc_bin
        )
        seeded_path = rt.seed_project_owned_agent(project, name="my-custom")
        before_content = seeded_path.read_text(encoding="utf-8")

        rt.run_update_project(
            project, framework_repo_root=framework_repo_root, home=home, cc_bin=cc_bin
        )
        results.append(
            rt.check_preserves_project_owned(
                before=before_content, after_path=seeded_path, subject="rt6"
            )
        )

    # -- .mcp.json is never touched by /update-project, a fresh scratch project.
    with tempfile.TemporaryDirectory(prefix="cc-conformance-baseline-mcp-") as raw:
        tmp_path = Path(raw)
        home = tmp_path / "home"
        rt.materialize_framework_source(
            home / ".claude" / "copilot", framework_repo_root
        )
        project = tmp_path / "project"
        project.mkdir()
        _init_git_repo(project)

        rt.run_setup_project(
            project, framework_repo_root=framework_repo_root, home=home, cc_bin=cc_bin
        )
        rt.seed_third_party_mcp_server(project, name="third-party-example")
        before_mcp = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))

        rt.run_update_project(
            project, framework_repo_root=framework_repo_root, home=home, cc_bin=cc_bin
        )
        results.append(
            rt.check_does_not_touch_mcp_json(
                before=before_mcp, project=project, subject="rt-mcp"
            )
        )

    return results


# ---------------------------------------------------------------------------
# Layer 6 -- root-cause regression pins, real machine
# ---------------------------------------------------------------------------


def collect_layer6_regression() -> list[CheckResult]:
    if not _REAL_MACHINE_CONFIG_PATH.is_file():
        return []
    return list(root_causes.run_all_root_cause_checks())


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def collect_all(*, sweep_mode: Mode, include_roundtrip: bool) -> list[CheckResult]:
    # The baseline must freeze the exact ordinary CLI collector, not a second
    # orchestration implementation that can drift (the former Layer-5 helper
    # still exercised markdown compatibility seams after the CLI had moved to
    # the canonical transaction).  Import lazily to keep this standalone
    # script's module import cheap and hermetic for unit tests.
    from cc.commands import conformance as conformance_cmd

    layers = (
        conformance_cmd.FULL_CHECK_LAYERS
        if include_roundtrip
        else conformance_cmd.DEFAULT_CHECK_LAYERS
    )
    return list(
        conformance_cmd._collect_results(
            layers=layers,
            mode=sweep_mode,
            jobs=conformance_cmd.DEFAULT_JOBS,
            use_cache=False,
            announce=lambda text: print(f"  {text}", file=sys.stderr),
        )
    )


def _entries_from_results(results: list[CheckResult]) -> list[dict[str, str]]:
    # De-duplicate on (id, subject) -- Layer 1/6 can legitimately be asked
    # for the same (id, subject) more than once across this script's own
    # helper calls (they never are, today, but a future edit adding an
    # extra call site should not silently double an entry in the baseline).
    seen: dict[tuple[str, str], str] = {}
    for result in results:
        key = (result.id, report.baseline_subject(result.id, result.subject))
        prior = seen.get(key)
        if prior is not None and prior != result.verdict.value:
            raise RuntimeError(
                f"conflicting verdicts for baseline identity {key!r}: "
                f"{prior!r} and {result.verdict.value!r}"
            )
        seen[key] = result.verdict.value
    return [
        {"id": key[0], "subject": key[1], "verdict": verdict}
        for key, verdict in sorted(seen.items())
    ]


def _counts_by_verdict(results: list[CheckResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.verdict.value] = counts.get(result.verdict.value, 0) + 1
    return counts


def _git_identity() -> str:
    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            cwd=_FRAMEWORK_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        email = result.stdout.strip()
        if email:
            return email
    except OSError:
        pass
    return getpass.getuser()


def _change_classification(previous: str | None, current: str | None) -> str:
    if previous == "fail" and current == "pass":
        return "verified-remediation"
    if previous == "could-not-run" and current == "pass":
        return "newly-runnable"
    if previous == "skip" and current == "pass":
        return "newly-applicable"
    if previous == "fail" and current == "skip":
        return "reviewed-nonapplicability"
    if previous == "could-not-run" and current == "fail":
        return "newly-measurable-failure"
    if previous == "pass" and current == "skip":
        return "reviewed-nonapplicability"
    if previous == "pass" and current == "fail":
        return "review-required-pass-to-fail"
    if previous is None:
        return "new-check-or-subject"
    if current is None:
        return "superseded-or-no-longer-applicable-subject"
    return "other-reviewed-transition"


def _load_pass_to_fail_reviews(path: Path | None) -> tuple[dict[str, str], ...]:
    if path is None:
        return ()
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("pass_to_fail") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        raise ValueError("review file must contain a pass_to_fail array")
    required = {"id", "subject", "classification", "rationale", "owner"}
    reviewed: list[dict[str, str]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not required <= set(row):
            raise ValueError(
                f"review pass_to_fail[{index}] must contain {sorted(required)}"
            )
        normalized = {key: str(row[key]).strip() for key in required}
        if any(not value for value in normalized.values()):
            raise ValueError(f"review pass_to_fail[{index}] contains an empty field")
        normalized["subject"] = report.baseline_subject(
            normalized["id"], normalized["subject"]
        )
        reviewed.append(normalized)
    return tuple(reviewed)


def _reviewed_change_set(
    *,
    old_path: Path,
    new_entries: list[dict[str, str]],
    pass_to_fail_reviews: tuple[dict[str, str], ...],
) -> dict[str, object]:
    raw_old = json.loads(old_path.read_text(encoding="utf-8"))
    raw_old_entries = raw_old.get("entries", [])
    old: dict[tuple[str, str], str] = {}
    duplicate_count = 0
    for entry in raw_old_entries:
        key = (
            str(entry["id"]),
            report.baseline_subject(str(entry["id"]), str(entry["subject"])),
        )
        if key in old:
            duplicate_count += 1
        old[key] = str(entry["verdict"])
    new = {
        (str(entry["id"]), str(entry["subject"])): str(entry["verdict"])
        for entry in new_entries
    }
    review_by_key = {
        (row["id"], row["subject"]): row for row in pass_to_fail_reviews
    }
    changes: list[dict[str, object]] = []
    required_reviews: set[tuple[str, str]] = set()
    for key in sorted(set(old) | set(new)):
        previous = old.get(key)
        current = new.get(key)
        if previous == current:
            continue
        classification = _change_classification(previous, current)
        row: dict[str, object] = {
            "id": key[0],
            "subject": key[1],
            "previous": previous,
            "current": current,
            "classification": classification,
        }
        if previous == "pass" and current == "fail":
            required_reviews.add(key)
            review = review_by_key.get(key)
            if review is not None:
                row.update(
                    {
                        "classification": review["classification"],
                        "rationale": review["rationale"],
                        "owner": review["owner"],
                    }
                )
        changes.append(row)
    supplied_reviews = set(review_by_key)
    missing = required_reviews - supplied_reviews
    extra = supplied_reviews - required_reviews
    if missing or extra:
        formatted_missing = [f"{item[0]} | {item[1]}" for item in sorted(missing)]
        formatted_extra = [f"{item[0]} | {item[1]}" for item in sorted(extra)]
        raise ValueError(
            "pass-to-fail review set does not match live deltas; "
            f"missing={formatted_missing}, extra={formatted_extra}"
        )
    counts: dict[str, int] = {}
    for change in changes:
        label = str(change["classification"])
        counts[label] = counts.get(label, 0) + 1
    return {
        "source_baseline": str(old_path),
        "source_sha256": hashlib.sha256(old_path.read_bytes()).hexdigest(),
        "source_duplicate_entries_collapsed": duplicate_count,
        "classification_counts": counts,
        "zero_unreviewed_pass_to_fail": not missing,
        "changes": changes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a conformance-harness baseline from a live run against "
            "the real machine. Dry run by default; --write persists the file."
        )
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_BASELINE_PATH,
        help=f"baseline file to write (default: {DEFAULT_BASELINE_PATH})",
    )
    parser.add_argument(
        "--write", action="store_true", help="actually write the baseline file"
    )
    parser.add_argument(
        "--reason",
        type=str,
        default="",
        help="required (non-empty) when --write is passed: WHY this baseline was regenerated",
    )
    parser.add_argument(
        "--acknowledge-regression",
        action="store_true",
        help=(
            "required in addition to --reason if the fresh run would encode "
            "a PASS-to-FAIL flip (vs. the EXISTING file at --out) as part of "
            "the new baseline -- see this file's module docstring"
        ),
    )
    parser.add_argument(
        "--review-file",
        type=Path,
        help=(
            "JSON review whose pass_to_fail array exactly matches every live "
            "PASS-to-FAIL delta and attributes classification, rationale, and owner"
        ),
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="use fast-mode (no network, cached-off) Layer 3 sweep instead of full mode",
    )
    parser.add_argument(
        "--no-roundtrip",
        action="store_true",
        help="skip Layer 5 (round-trip) -- it is the slowest layer and mutates scratch clones",
    )
    args = parser.parse_args()

    sweep_mode = Mode.FAST if args.fast else Mode.FULL
    results = collect_all(sweep_mode=sweep_mode, include_roundtrip=not args.no_roundtrip)

    entries = _entries_from_results(results)
    counts = _counts_by_verdict(results)

    print("")
    print(f"Collected {len(results)} check result(s) -> {len(entries)} distinct (id, subject) entries.")
    for verdict, count in sorted(counts.items()):
        print(f"  {verdict:<14} {count}")

    if not args.write:
        print("\nDry run (no --write) -- nothing written.")
        return 0

    if not args.reason.strip():
        print(
            "\nREFUSED: --write requires a non-empty --reason "
            "(state WHY this baseline is being regenerated).",
            file=sys.stderr,
        )
        return 2

    payload: dict[str, object] = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reason": args.reason.strip(),
        "generated_by": _git_identity(),
        "mode": sweep_mode.value,
        "included_roundtrip": not args.no_roundtrip,
        "counts": counts,
        "entries": entries,
    }

    if args.out.is_file():
        existing_baseline = report.load_baseline(args.out)
        comparison = report.compare_to_baseline(results, existing_baseline, file=str(args.out))
        if comparison.regressed:
            print(
                f"\n{len(comparison.regressed)} check(s) REGRESSED vs. the existing "
                f"baseline at {args.out} (PASS there, FAIL now):",
                file=sys.stderr,
            )
            for result in comparison.regressed:
                print(f"  {result.id}  {result.subject}", file=sys.stderr)
            if not args.acknowledge_regression:
                print(
                    "\nREFUSED: pass --acknowledge-regression to knowingly bake these "
                    "into the new baseline (they will be recorded in the file's own "
                    "'acknowledged_regressions' list, never silently).",
                    file=sys.stderr,
                )
                return 3
        try:
            pass_to_fail_reviews = _load_pass_to_fail_reviews(args.review_file)
            change_review = _reviewed_change_set(
                old_path=args.out,
                new_entries=entries,
                pass_to_fail_reviews=pass_to_fail_reviews,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            print(f"\nREFUSED: invalid or incomplete delta review: {exc}", file=sys.stderr)
            return 4
        if comparison.regressed and args.review_file is None:
            print(
                "\nREFUSED: --acknowledge-regression also requires --review-file "
                "with an exact attributed review for every PASS-to-FAIL delta.",
                file=sys.stderr,
            )
            return 4
        payload["change_review"] = change_review
        payload["acknowledged_regressions"] = list(pass_to_fail_reviews)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"\nWrote {args.out} ({len(entries)} entries).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
