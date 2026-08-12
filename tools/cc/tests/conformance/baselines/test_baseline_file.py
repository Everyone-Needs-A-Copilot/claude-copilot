"""WP-9 tests: the committed baseline file itself, and the exit-code
regression path it exists to drive.

Two things this module proves, independently of whatever CLI eventually
wraps `report.compute_exit_code` (WP-8's `cc conformance check --baseline`,
not required for these tests to pass):

  1. `test_baseline_captures_every_known_root_cause` -- the fitness
     function `HARNESS-DESIGN.md` section 5.4 / section 13 names. If the
     committed baseline ever stops recording a FAIL for one of RC-1..RC-5,
     this goes red -- the harness has stopped detecting a known-bad
     condition and the baseline can no longer prove it would have caught a
     regression there.
  2. `TestExitCodeRegressionPath` -- `report.compute_exit_code` /
     `report.compare_to_baseline` (WP-1, unmodified) actually return exit
     code 3 when a synthetic run flips one of the baseline's currently-PASS
     `(id, subject)` pairs to FAIL, and never fabricate a bare 0 when the
     baseline (honestly) contains `COULD_NOT_RUN` entries. This is the same
     mechanism demonstrated manually while building the harness; it is
     re-proven here as a permanent, automated regression test rather than a
     one-off script.

This file is entirely hermetic (reads only the committed baseline JSON,
never the real machine) -- no `@pytest.mark.machine` needed, and it runs on
a CI box with no ecosystem installed at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cc.core.conformance import report
from cc.core.conformance.types import (
    CheckResult,
    Evidence,
    ExpectedToday,
    Layer,
    Scope,
    Severity,
    Verdict,
)

BASELINE_PATH = Path(__file__).parent / "2026-08-12-reviewed-current.json"

# TASK-281's reviewed current failure taxonomy.  An exact set is stricter and
# more honest than the obsolete 2026-08-10 numeric floor: many originally
# predicted failures have been verified fixed, while newly implemented checks
# now expose different current failures.  Any addition or removal requires an
# explicit baseline review rather than quietly satisfying a loose count.
REVIEWED_CURRENT_FAILING_CHECK_IDS = {
    "repo.d01.agent_roster_exact",
    "repo.d01.claude_md_agent_count_accurate",
    "repo.d01.claude_md_entry_heading",
    "repo.d01.command_set_exact",
    "repo.d01.documented_commands_exist",
    "repo.d01.fitness_check_passes",
    "repo.d01.fitness_check_present_executable",
    "repo.d01.mcp_json_is_object",
    "repo.d02.codex_entry_contract",
    "repo.d02.declared_version_matches_lock",
    "repo.d02.plugin_tree_matches_pinned_mirror",
    "repo.d02.skill_bridge_internal_symlink",
    "repo.d03.all_installed_components_locked",
    "repo.d03.lock_schema_and_checksums",
    "repo.d05.cc_config_machine_sentinel",
    "repo.d06.memory_entries_committed_db_ignored",
    "repo.d07.knowledge_wiring_resolves",
    "repo.d08.tier_participation",
    "repo.d09.portable_declaration",
    "repo.d10.mcp_json_is_committable",
    "repo.d10.mcp_object_no_retired_servers",
    "repo.d11.registry_entry",
    "repo.d12.initiatives_scaffold",
    "repo.d13.scanner_reachable",
    "repo.gitignore.no_self_exclusion",
    "stack.cs_signers",
    "tier.effectiveness.extension_resolution_wired_beyond_prose",
    "tier.precedence.commands_dimension_has_no_consumer",
}

# The 5 required root-cause regression pins (HARNESS-DESIGN.md section 4
# Layer 6 / TEST-MATRIX.md section 6) -- rc.rc6/rc.rc7 are documented bonus
# pins in the design and are not required here.
REQUIRED_ROOT_CAUSE_ID_PREFIXES = (
    "rc.rc1.",
    "rc.rc2.",
    "rc.rc3.",
    "rc.rc4.",
    "rc.rc5.",
)


@pytest.fixture(scope="module")
def baseline_entries() -> tuple[report.BaselineEntry, ...]:
    return report.load_baseline(BASELINE_PATH)


def test_baseline_file_exists_and_is_non_empty(baseline_entries):
    assert BASELINE_PATH.is_file(), f"expected a committed baseline at {BASELINE_PATH}"
    assert len(baseline_entries) > 0


def test_baseline_captures_every_known_root_cause(baseline_entries):
    """Every named regression pin remains represented even after a root cause
    is fixed. Synthetic negative fixtures prove detection; the live baseline
    records current truth instead of requiring resolved defects to stay red."""

    recorded_ids = {entry.id for entry in baseline_entries}
    for prefix in REQUIRED_ROOT_CAUSE_ID_PREFIXES:
        matching = [check_id for check_id in recorded_ids if check_id.startswith(prefix)]
        assert matching, (
            f"expected an entry for a check id starting with {prefix!r} -- "
            "the live baseline silently dropped this regression pin"
        )


def test_baseline_matches_the_reviewed_current_failure_taxonomy(baseline_entries):
    """No current failing check category appears or disappears silently."""

    failing_ids = {entry.id for entry in baseline_entries if entry.verdict is Verdict.FAIL}
    assert failing_ids == REVIEWED_CURRENT_FAILING_CHECK_IDS


def test_baseline_change_review_has_zero_unreviewed_pass_to_fail():
    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    review = payload["change_review"]
    assert review["zero_unreviewed_pass_to_fail"] is True
    changes = review["changes"]
    assert changes
    pass_to_fail = [
        row
        for row in changes
        if row.get("previous") == "pass" and row.get("current") == "fail"
    ]
    assert pass_to_fail
    for row in pass_to_fail:
        assert row["classification"].startswith("reviewed-open-")
        assert row["rationale"]
        assert row["owner"]
    acknowledged = {
        (row["id"], row["subject"])
        for row in payload["acknowledged_regressions"]
    }
    assert acknowledged == {(row["id"], row["subject"]) for row in pass_to_fail}


def test_baseline_entries_are_well_formed(baseline_entries):
    for entry in baseline_entries:
        assert entry.id, "every baseline entry must name a check id"
        assert entry.subject, "every baseline entry must name a subject"
        assert entry.verdict in (
            Verdict.PASS,
            Verdict.FAIL,
            Verdict.SKIP,
            Verdict.COULD_NOT_RUN,
        )


def test_baseline_has_no_duplicate_id_subject_pairs(baseline_entries):
    keys = [entry.key() for entry in baseline_entries]
    assert len(keys) == len(set(keys)), (
        "duplicate (id, subject) pairs in the baseline -- "
        "report.compare_to_baseline indexes by this key, so a duplicate "
        "silently shadows an earlier entry"
    )


# ---------------------------------------------------------------------------
# The exit-code regression path, proven against the REAL committed baseline
# ---------------------------------------------------------------------------


def _replay_result(entry: report.BaselineEntry, *, verdict: Verdict | None = None) -> CheckResult:
    """Reconstruct a minimal `CheckResult` for one baseline entry, optionally
    overriding its verdict (the synthetic-regression case below)."""

    effective_verdict = verdict if verdict is not None else entry.verdict
    evidence: tuple[Evidence, ...] = ()
    if effective_verdict is Verdict.FAIL:
        evidence = (Evidence(kind="baseline-replay", path=entry.subject, actual="fail"),)
    return CheckResult(
        id=entry.id,
        layer=Layer.REPO,
        severity=Severity.S2,
        scope=Scope.PER_REPO,
        subject=entry.subject,
        assertion="baseline replay for the exit-code regression test",
        verdict=effective_verdict,
        expected_today=ExpectedToday.FAIL
        if effective_verdict is Verdict.FAIL
        else ExpectedToday.PASS,
        evidence=evidence,
    )


class TestExitCodeRegressionPath:
    def test_unchanged_replay_never_fabricates_a_pass(self, baseline_entries):
        """An exact replay of the baseline (nothing changed) must not exit 0
        while the baseline itself contains real `COULD_NOT_RUN` entries --
        `compute_exit_code`'s own documented precedence puts COULD_NOT_RUN
        (2) ahead of a bare pass, and `inv.no_fabricated_healthy` forbids
        ever coercing "we could not tell" into "it is fine". If a future
        baseline regeneration ever eliminates every COULD_NOT_RUN entry,
        this assertion's precondition (skip below) stops applying and an
        unchanged replay legitimately becomes exit 0 -- that is the correct
        evolution, not a break."""

        results = [_replay_result(entry) for entry in baseline_entries]
        comparison = report.compare_to_baseline(results, baseline_entries, file=str(BASELINE_PATH))
        exit_code = report.compute_exit_code(results, baseline=comparison)

        assert not comparison.regressed, "an unchanged replay must never itself be a regression"
        has_could_not_run = any(entry.verdict is Verdict.COULD_NOT_RUN for entry in baseline_entries)
        if has_could_not_run:
            assert exit_code == 2
        else:
            assert exit_code == 0

    def test_synthetic_pass_to_fail_flip_produces_exit_3(self, baseline_entries):
        """The regression gate's whole reason to exist: something that
        PASSED in the committed baseline and now FAILS must produce exit 3,
        regardless of `--fail-on` and regardless of every other check's
        verdict (`compute_exit_code`'s documented precedence: baseline
        regression beats COULD_NOT_RUN beats FAIL)."""

        pass_entry = next(
            (entry for entry in baseline_entries if entry.verdict is Verdict.PASS), None
        )
        assert pass_entry is not None, "expected at least one PASS entry in the baseline"

        results = [
            _replay_result(entry, verdict=Verdict.FAIL)
            if entry is pass_entry
            else _replay_result(entry)
            for entry in baseline_entries
        ]
        comparison = report.compare_to_baseline(results, baseline_entries, file=str(BASELINE_PATH))
        exit_code = report.compute_exit_code(results, baseline=comparison)

        assert len(comparison.regressed) == 1
        assert comparison.regressed[0].id == pass_entry.id
        assert comparison.regressed[0].subject == pass_entry.subject
        assert exit_code == 3

    def test_reverting_the_flip_restores_the_unregressed_exit_code(self, baseline_entries):
        """Confirms the regression signal is a live comparison, not a
        one-way latch: fixing the synthetic flip from the previous test
        (independently, since each test gets its own fresh replay) makes
        the regression disappear again."""

        pass_entry = next(entry for entry in baseline_entries if entry.verdict is Verdict.PASS)
        flipped = [
            _replay_result(entry, verdict=Verdict.FAIL)
            if entry is pass_entry
            else _replay_result(entry)
            for entry in baseline_entries
        ]
        reverted = [_replay_result(entry) for entry in baseline_entries]

        comparison_flipped = report.compare_to_baseline(flipped, baseline_entries, file=str(BASELINE_PATH))
        comparison_reverted = report.compare_to_baseline(reverted, baseline_entries, file=str(BASELINE_PATH))

        assert report.compute_exit_code(flipped, baseline=comparison_flipped) == 3
        assert not comparison_reverted.regressed
        assert report.compute_exit_code(reverted, baseline=comparison_reverted) != 3
