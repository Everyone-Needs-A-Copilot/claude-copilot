"""WP-1 tests: the harness core (types, registry, report, fsguard, cache)
and the `FleetFactory` fixture builder itself.

Every fitness function this test file proves is one of
`HARNESS-DESIGN.md` §13's table, scoped to what WP-1 alone can prove
(the RC-completeness and "every check has a positive+negative test"
fitness functions need real registered checks from WP-2..WP-7 and are not
this package's job).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from cc.core.conformance import cache as cache_mod
from cc.core.conformance import fsguard, report
from cc.core.conformance.registry import (
    CheckRegistrationError,
    Registry,
    register_check,
)
from cc.core.conformance.types import (
    CheckResult,
    Evidence,
    ExpectedToday,
    Layer,
    Mode,
    Scope,
    Severity,
    Verdict,
    severity_at_or_above,
)
from cc.core.ecosystem.discovery import discover_contributions
from cc.core.ecosystem.manifest import load_layers, validate_layers
from jsonschema import Draft202012Validator
from referencing import Registry as SchemaRegistry
from referencing import Resource

from .conftest import FleetFactory, git_clone_local

pytestmark = pytest.mark.filterwarnings("ignore")

_SCHEMA_DIR = Path(__file__).parents[1] / "fixtures" / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _conformance_validator() -> Draft202012Validator:
    conformance_schema = _load_schema("conformance.schema.json")
    envelope_schema = _load_schema("_envelope.schema.json")
    registry = SchemaRegistry().with_resources(
        [
            ("_envelope.schema.json", Resource.from_contents(envelope_schema)),
            (envelope_schema["$id"], Resource.from_contents(envelope_schema)),
            (conformance_schema["$id"], Resource.from_contents(conformance_schema)),
        ]
    )
    return Draft202012Validator(conformance_schema, registry=registry)


def _validate_envelope(payload: dict) -> None:
    validator = _conformance_validator()
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


def _fail_result(
    *,
    check_id: str = "tier.shadow.substance",
    subject: str = "cw",
    severity: Severity = Severity.S0,
    evidence: tuple[Evidence, ...] | None = None,
    detail: str = "",
    remediation: str = "fill in real content",
) -> CheckResult:
    return CheckResult(
        id=check_id,
        layer=Layer.TIER,
        severity=severity,
        scope=Scope.PER_TIER,
        subject=subject,
        assertion="a nearer tier's real content is not shadowed by a scaffold",
        verdict=Verdict.FAIL,
        expected_today=ExpectedToday.FAIL,
        evidence=evidence
        if evidence is not None
        else (
            Evidence(
                kind="extension-file",
                path=f"knowledge-copilot-private/.claude/extensions/{subject}.extension.md",
                expected="substantive content",
                actual="status: draft, 1646 bytes",
                detail="shadows knowledge-copilot-internal's real content",
            ),
        ),
        detail=detail,
        remediation=remediation,
    )


def _pass_result(
    *, check_id: str = "tier.precedence.nearest_wins", subject: str = "cw"
) -> CheckResult:
    return CheckResult(
        id=check_id,
        layer=Layer.TIER,
        severity=Severity.S1,
        scope=Scope.PER_TIER,
        subject=subject,
        assertion="nearest declaring tier wins",
        verdict=Verdict.PASS,
        expected_today=ExpectedToday.PASS,
    )


# ---------------------------------------------------------------------------
# types.py
# ---------------------------------------------------------------------------


class TestTypes:
    def test_severity_at_or_above_ordering(self):
        assert severity_at_or_above(Severity.S0, Severity.S1) is True
        assert severity_at_or_above(Severity.S1, Severity.S1) is True
        assert severity_at_or_above(Severity.S2, Severity.S1) is False
        assert severity_at_or_above(Severity.S3, Severity.S0) is False

    def test_evidence_as_dict_and_from_dict_roundtrip(self):
        evidence = Evidence(
            kind="lock-record",
            path=".claude/hooks/copilot-hook.sh",
            expected="present and locked",
            actual="missing",
            detail="0 of 76 repos pass",
            command="git ls-files .claude/hooks/copilot-hook.sh",
            output="",
        )
        restored = Evidence.from_dict(evidence.as_dict())
        assert restored == evidence

    def test_check_result_fail_without_evidence_raises(self):
        with pytest.raises(ValueError, match="no evidence"):
            CheckResult(
                id="rc.rc1.enforcement_hook_is_installed_by_something",
                layer=Layer.REGRESSION,
                severity=Severity.S0,
                scope=Scope.GLOBAL,
                subject="claude-copilot",
                assertion="the hook is installed by a sanctioned command",
                verdict=Verdict.FAIL,
                expected_today=ExpectedToday.FAIL,
            )

    def test_check_result_evidence_without_path_raises(self):
        with pytest.raises(ValueError, match="no path"):
            CheckResult(
                id="rc.rc1.enforcement_hook_is_installed_by_something",
                layer=Layer.REGRESSION,
                severity=Severity.S0,
                scope=Scope.GLOBAL,
                subject="claude-copilot",
                assertion="x",
                verdict=Verdict.FAIL,
                expected_today=ExpectedToday.FAIL,
                evidence=(Evidence(kind="grep", path=""),),
            )

    def test_check_result_empty_subject_raises(self):
        with pytest.raises(ValueError, match="empty subject"):
            CheckResult(
                id="tier.precedence.nearest_wins",
                layer=Layer.TIER,
                severity=Severity.S1,
                scope=Scope.GLOBAL,
                subject="",
                assertion="x",
                verdict=Verdict.PASS,
                expected_today=ExpectedToday.PASS,
            )

    def test_check_result_pass_needs_no_evidence(self):
        result = _pass_result()
        assert result.evidence == ()

    def test_check_result_as_dict_round_trips(self):
        result = _fail_result()
        restored = CheckResult.from_dict(result.as_dict())
        assert restored == result

    def test_check_result_root_cause_only_serialized_when_set(self):
        assert "root_cause" not in _pass_result().as_dict()
        tagged = _fail_result().as_dict()
        with_cause = CheckResult.from_dict({**tagged, "root_cause": "rc.rc1"})
        assert with_cause.as_dict()["root_cause"] == "rc.rc1"


# ---------------------------------------------------------------------------
# registry.py
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_register_and_lookup(self):
        registry = Registry()
        registration = register_check(
            id="tier.precedence.nearest_wins",
            layer=Layer.TIER,
            severity=Severity.S0,
            scope=Scope.GLOBAL,
            summary="nearest-rank contributing layer wins",
            remediation="n/a — descriptive, not remedial",
            registry=registry,
        )
        assert registry.get("tier.precedence.nearest_wins") is registration
        assert len(registry) == 1
        assert registration in registry.all()

    def test_duplicate_id_raises(self):
        registry = Registry()
        register_check(
            id="tier.precedence.nearest_wins",
            layer=Layer.TIER,
            severity=Severity.S0,
            scope=Scope.GLOBAL,
            summary="x",
            remediation="x",
            registry=registry,
        )
        with pytest.raises(CheckRegistrationError, match="duplicate"):
            register_check(
                id="tier.precedence.nearest_wins",
                layer=Layer.STACK,
                severity=Severity.S1,
                scope=Scope.GLOBAL,
                summary="y",
                remediation="y",
                registry=registry,
            )

    @pytest.mark.parametrize(
        "bad_id",
        ["NoDots", "has space.here", "Upper.Case", "trailing.dot.", ".leading", "one"],
    )
    def test_malformed_id_raises(self, bad_id):
        registry = Registry()
        with pytest.raises(CheckRegistrationError, match="invalid check id"):
            register_check(
                id=bad_id,
                layer=Layer.TIER,
                severity=Severity.S0,
                scope=Scope.GLOBAL,
                summary="x",
                remediation="x",
                registry=registry,
            )

    def test_two_segment_id_is_valid(self):
        registry = Registry()
        register_check(
            id="inv.no_bare_cli_name",
            layer=Layer.REGRESSION,
            severity=Severity.S1,
            scope=Scope.GLOBAL,
            summary="x",
            remediation="x",
            registry=registry,
        )
        assert "inv.no_bare_cli_name" in registry

    def test_missing_summary_raises(self):
        registry = Registry()
        with pytest.raises(CheckRegistrationError, match="no summary"):
            register_check(
                id="tier.precedence.nearest_wins",
                layer=Layer.TIER,
                severity=Severity.S0,
                scope=Scope.GLOBAL,
                summary="",
                remediation="x",
                registry=registry,
            )

    def test_missing_remediation_raises(self):
        registry = Registry()
        with pytest.raises(CheckRegistrationError, match="no remediation"):
            register_check(
                id="tier.precedence.nearest_wins",
                layer=Layer.TIER,
                severity=Severity.S0,
                scope=Scope.GLOBAL,
                summary="x",
                remediation="",
                registry=registry,
            )

    def test_unknown_repo_class_raises(self):
        registry = Registry()
        with pytest.raises(CheckRegistrationError, match="unknown repo class"):
            register_check(
                id="repo.d08.tier_participation",
                layer=Layer.REPO,
                severity=Severity.S1,
                scope=Scope.PER_REPO,
                summary="x",
                remediation="x",
                applies_to_classes=("A", "Z"),
                registry=registry,
            )

    def test_two_independent_registry_instances_do_not_collide(self):
        # The isolation seam: constructing a fresh Registry() per test
        # never pollutes DEFAULT_REGISTRY or any other test's registry.
        first = Registry()
        second = Registry()
        register_check(
            id="tier.precedence.nearest_wins",
            layer=Layer.TIER,
            severity=Severity.S0,
            scope=Scope.GLOBAL,
            summary="x",
            remediation="x",
            registry=first,
        )
        register_check(
            id="tier.precedence.nearest_wins",
            layer=Layer.TIER,
            severity=Severity.S0,
            scope=Scope.GLOBAL,
            summary="x",
            remediation="x",
            registry=second,
        )  # must NOT raise -- distinct registries.
        assert len(first) == 1
        assert len(second) == 1

    def test_select_filters_by_layer_mode_id_and_class(self):
        registry = Registry()
        register_check(
            id="tier.precedence.nearest_wins",
            layer=Layer.TIER,
            severity=Severity.S0,
            scope=Scope.GLOBAL,
            summary="x",
            remediation="x",
            mode=Mode.FAST,
            registry=registry,
        )
        register_check(
            id="repo.d01.agent_roster_exact",
            layer=Layer.REPO,
            severity=Severity.S1,
            scope=Scope.PER_REPO,
            summary="x",
            remediation="x",
            mode=Mode.FULL,
            applies_to_classes=("A", "B"),
            registry=registry,
        )

        assert {r.id for r in registry.select(layers=[Layer.TIER])} == {
            "tier.precedence.nearest_wins"
        }
        assert {r.id for r in registry.select(modes=[Mode.FULL])} == {
            "repo.d01.agent_roster_exact"
        }
        assert {r.id for r in registry.select(check_ids=["repo.d01.agent_roster_exact"])} == {
            "repo.d01.agent_roster_exact"
        }
        # tier.precedence.nearest_wins declares no applies_to_classes at all
        # (it is not repo-class-scoped), so it survives every --class
        # filter alongside whichever class-scoped check(s) also match.
        assert {r.id for r in registry.select(classes=["A"])} == {
            "repo.d01.agent_roster_exact",
            "tier.precedence.nearest_wins",
        }
        assert {r.id for r in registry.select(classes=["C"])} == {
            "tier.precedence.nearest_wins"
        }

    def test_result_factory_fills_in_registration_metadata(self):
        registry = Registry()
        registration = register_check(
            id="stack.pin.ancestry",
            layer=Layer.STACK,
            severity=Severity.S0,
            scope=Scope.PER_CELL,
            summary="every pinned tag is an ancestor of the branch it claims",
            remediation="re-cut the release from a connected branch tip",
            expected_today=ExpectedToday.FAIL,
            registry=registry,
        )
        evidence = (Evidence(kind="git", path="claude-copilot", detail="rev-list --count=1"),)
        result = registration.result(
            subject="claude-copilot", verdict=Verdict.FAIL, evidence=evidence
        )
        assert result.id == "stack.pin.ancestry"
        assert result.layer is Layer.STACK
        assert result.severity is Severity.S0
        assert result.assertion == registration.summary
        assert result.remediation == registration.remediation
        assert result.expected_today is ExpectedToday.FAIL  # registration default

        overridden = registration.result(
            subject="cli-foundation",
            verdict=Verdict.PASS,
            expected_today=ExpectedToday.PASS,  # a per-subject override (CS-ANCESTOR control case)
        )
        assert overridden.expected_today is ExpectedToday.PASS


# ---------------------------------------------------------------------------
# report.py
# ---------------------------------------------------------------------------


class TestReport:
    def test_assert_no_bare_ready_raises_on_bare_word(self):
        with pytest.raises(report.BareReadyError):
            report.assert_no_bare_ready("this repo is ready")

    def test_assert_no_bare_ready_allows_qualified_word(self):
        report.assert_no_bare_ready("ready (by waiver, 2 files)")  # must not raise

    def test_assert_no_bare_ready_ignores_substring_words(self):
        report.assert_no_bare_ready("already installed")  # must not raise

    def test_render_human_raises_on_bare_ready_in_a_result(self):
        unsafe = _fail_result(detail="classification is ready")
        with pytest.raises(report.BareReadyError):
            report.render_human([unsafe], mode=Mode.FAST)

    def test_render_human_qualified_ready_is_allowed(self):
        safe = _fail_result(detail="classification is ready (by waiver, 2 files)")
        text = report.render_human([safe], mode=Mode.FAST)
        assert "ready (by waiver" in text

    def test_render_human_never_contains_a_percent_sign(self):
        results = [_pass_result(), _fail_result()]
        text = report.render_human(results, mode=Mode.FAST)
        assert "%" not in text

    def test_render_human_groups_by_layer_and_shows_failures(self):
        text = report.render_human([_pass_result(), _fail_result()], mode=Mode.FAST)
        assert "tier.shadow.substance" in text
        assert "FAIL" in text
        assert "S0" in text

    def test_summarize_counts_by_severity_and_layer(self):
        summary = report.summarize([_pass_result(), _fail_result(), _fail_result()])
        assert summary.by_severity["S0"] == 2
        assert summary.by_layer["tier"]["pass"] == 1
        assert summary.by_layer["tier"]["fail"] == 2

    def test_summary_and_envelope_never_carry_a_score_key(self):
        envelope = report.to_envelope([_pass_result(), _fail_result()], mode=Mode.FAST)
        assert "score" not in envelope
        assert "score" not in envelope["summary"]
        assert "percentage" not in json.dumps(envelope)

    def test_to_envelope_validates_against_schema(self):
        envelope = report.to_envelope(
            [_pass_result(), _fail_result()],
            mode=Mode.FAST,
            host="test-host",
        )
        _validate_envelope(envelope)
        assert envelope["result"] == "fail"

    def test_to_envelope_all_pass_validates_and_is_pass(self):
        envelope = report.to_envelope([_pass_result()], mode=Mode.FULL)
        _validate_envelope(envelope)
        assert envelope["result"] == "pass"

    def test_to_envelope_with_baseline_validates(self):
        baseline = report.BaselineComparison(
            file="baselines/2026-08-10-known-bad.json",
            fixed=(),
            still_failing=(_fail_result(),),
            regressed=(),
            new_failures=(),
        )
        envelope = report.to_envelope(
            [_fail_result()], mode=Mode.FAST, baseline=baseline
        )
        _validate_envelope(envelope)
        assert envelope["baseline"]["still_failing"] == 1

    def test_compute_exit_code_zero_when_everything_passes(self):
        assert report.compute_exit_code([_pass_result()], fail_on=Severity.S1) == 0

    def test_compute_exit_code_one_when_failure_at_or_above_threshold(self):
        assert (
            report.compute_exit_code(
                [_fail_result(severity=Severity.S1)], fail_on=Severity.S1
            )
            == 1
        )

    def test_compute_exit_code_ignores_failures_below_threshold(self):
        assert (
            report.compute_exit_code(
                [_fail_result(severity=Severity.S3)], fail_on=Severity.S1
            )
            == 0
        )

    def test_compute_exit_code_two_for_could_not_run_regardless_of_threshold(self):
        could_not_run = CheckResult(
            id="stack.doctor.contract_shape",
            layer=Layer.STACK,
            severity=Severity.S3,
            scope=Scope.GLOBAL,
            subject="claude-copilot",
            assertion="x",
            verdict=Verdict.COULD_NOT_RUN,
            expected_today=ExpectedToday.PASS,
        )
        # Even though severity S3 is below the S1 threshold, COULD_NOT_RUN
        # must still drive a non-zero, non-1 exit code -- never coerced to
        # PASS (inv.no_fabricated_healthy).
        assert report.compute_exit_code([could_not_run], fail_on=Severity.S1) == 2

    def test_compute_exit_code_never_returns_zero_when_could_not_run_present(self):
        could_not_run = CheckResult(
            id="stack.doctor.contract_shape",
            layer=Layer.STACK,
            severity=Severity.S0,
            scope=Scope.GLOBAL,
            subject="x",
            assertion="x",
            verdict=Verdict.COULD_NOT_RUN,
            expected_today=ExpectedToday.PASS,
        )
        code = report.compute_exit_code(
            [could_not_run, _pass_result()], fail_on=Severity.S3
        )
        assert code != 0

    def test_compute_exit_code_three_when_baseline_regressed_takes_precedence(self):
        regressed = report.BaselineComparison(
            file="baselines/x.json", fixed=(), still_failing=(), regressed=(_fail_result(),), new_failures=()
        )
        # Even a clean run (no FAIL/COULD_NOT_RUN passed in) is code 3 if
        # the baseline says something regressed.
        code = report.compute_exit_code([_pass_result()], fail_on=Severity.S3, baseline=regressed)
        assert code == 3

    def test_filter_by_severity_threshold(self):
        results = [_fail_result(severity=Severity.S0), _fail_result(severity=Severity.S3)]
        filtered = report.filter_by_severity_threshold(results, Severity.S1)
        assert len(filtered) == 1
        assert filtered[0].severity is Severity.S0

    def test_filter_by_repo_matches_exact_and_suffix(self):
        a = _fail_result(subject="/Volumes/Dev/Sites/COPILOT/claude-copilot")
        b = _fail_result(subject="/Volumes/Dev/Sites/COPILOT/codex-copilot")
        filtered = report.filter_by_repo([a, b], ["claude-copilot"])
        assert filtered == (a,)

    def test_group_by_root_cause_groups_multiple_repos_under_one_cause(self):
        first = CheckResult(
            id="repo.d04.hook_present_and_locked",
            layer=Layer.REPO,
            severity=Severity.S0,
            scope=Scope.PER_REPO,
            subject="repo-one",
            assertion="x",
            verdict=Verdict.FAIL,
            expected_today=ExpectedToday.FAIL,
            evidence=(Evidence(kind="framework-file", path=".claude/hooks/copilot-hook.sh"),),
            root_cause="rc.rc1",
        )
        second = CheckResult(
            id="repo.d04.hook_present_and_locked",
            layer=Layer.REPO,
            severity=Severity.S0,
            scope=Scope.PER_REPO,
            subject="repo-two",
            assertion="x",
            verdict=Verdict.FAIL,
            expected_today=ExpectedToday.FAIL,
            evidence=(Evidence(kind="framework-file", path=".claude/hooks/copilot-hook.sh"),),
            root_cause="rc.rc1",
        )
        groups = report.group_by_root_cause([first, second, _pass_result()])
        assert set(groups) == {"rc.rc1"}
        assert len(groups["rc.rc1"]) == 2

    def test_group_by_root_cause_falls_back_to_check_id(self):
        groups = report.group_by_root_cause([_fail_result()])
        assert set(groups) == {"tier.shadow.substance"}

    def test_compare_to_baseline_classifies_every_bucket(self):
        baseline = (
            report.BaselineEntry(id="a", subject="s", verdict=Verdict.FAIL),  # -> fixed
            report.BaselineEntry(id="b", subject="s", verdict=Verdict.FAIL),  # -> still_failing
            report.BaselineEntry(id="c", subject="s", verdict=Verdict.PASS),  # -> regressed
        )
        results = [
            CheckResult(
                id="a", layer=Layer.REPO, severity=Severity.S1, scope=Scope.PER_REPO,
                subject="s", assertion="x", verdict=Verdict.PASS, expected_today=ExpectedToday.PASS,
            ),
            _mk_fail("b", "s"),
            _mk_fail("c", "s"),
            _mk_fail("d", "s"),  # not in baseline at all -> new_failure
        ]
        comparison = report.compare_to_baseline(results, baseline, file="x.json")
        assert len(comparison.fixed) == 1
        assert len(comparison.still_failing) == 1
        assert len(comparison.regressed) == 1
        assert len(comparison.new_failures) == 1
        assert comparison.has_regression is True


def _mk_fail(check_id: str, subject: str) -> CheckResult:
    return CheckResult(
        id=check_id,
        layer=Layer.REPO,
        severity=Severity.S2,
        scope=Scope.PER_REPO,
        subject=subject,
        assertion="x",
        verdict=Verdict.FAIL,
        expected_today=ExpectedToday.FAIL,
        evidence=(Evidence(kind="framework-file", path="x"),),
    )


# ---------------------------------------------------------------------------
# fsguard.py -- prove the tripwire actually trips
# ---------------------------------------------------------------------------


class TestFsguard:
    def test_guard_passes_when_nothing_changes(self, tmp_path):
        guarded = tmp_path / "config.json"
        guarded.write_text("{}", encoding="utf-8")
        with fsguard.MachineReadOnlyGuard([guarded], include_core_paths=False):
            pass  # must not raise

    def test_guard_trips_on_file_content_change(self, tmp_path):
        guarded = tmp_path / "config.json"
        guarded.write_text("{}", encoding="utf-8")
        with pytest.raises(fsguard.MachineMutationError, match=str(guarded)):
            with fsguard.MachineReadOnlyGuard([guarded], include_core_paths=False):
                guarded.write_text('{"mutated": true}', encoding="utf-8")

    def test_guard_trips_on_file_creation(self, tmp_path):
        newly_created = tmp_path / "copilot.layers.yml"
        with pytest.raises(fsguard.MachineMutationError):
            with fsguard.MachineReadOnlyGuard([newly_created], include_core_paths=False):
                newly_created.write_text("layers: []\n", encoding="utf-8")

    def test_guard_trips_on_file_deletion(self, tmp_path):
        guarded = tmp_path / "secrets.env"
        guarded.write_text("KEY=value\n", encoding="utf-8")
        with pytest.raises(fsguard.MachineMutationError):
            with fsguard.MachineReadOnlyGuard([guarded], include_core_paths=False):
                guarded.unlink()

    def test_guard_trips_on_directory_content_change(self, tmp_path):
        entries_dir = tmp_path / "entries"
        entries_dir.mkdir()
        (entries_dir / "one.md").write_text("first entry", encoding="utf-8")
        with pytest.raises(fsguard.MachineMutationError):
            with fsguard.MachineReadOnlyGuard([entries_dir], include_core_paths=False):
                (entries_dir / "two.md").write_text("a new entry snuck in", encoding="utf-8")

    def test_guard_does_not_trip_on_unrelated_paths(self, tmp_path):
        guarded = tmp_path / "config.json"
        guarded.write_text("{}", encoding="utf-8")
        unrelated = tmp_path / "scratch.txt"
        with fsguard.MachineReadOnlyGuard([guarded], include_core_paths=False):
            unrelated.write_text("this is fine, it's not guarded", encoding="utf-8")

    def test_default_guarded_machine_paths_names_the_three_manifests(self):
        paths = fsguard.default_guarded_machine_paths()
        manifest_names = [path for path in paths if path.name == "copilot.layers.yml"]
        assert len(manifest_names) == 3

    def test_run_git_readonly_allows_rev_parse(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        result = fsguard.run_git_readonly(("rev-parse", "--is-inside-work-tree"), cwd=tmp_path)
        assert result.returncode == 0

    @pytest.mark.parametrize("forbidden", ["fetch", "checkout", "worktree", "gc", "push", "clone"])
    def test_run_git_readonly_rejects_mutating_subcommands(self, tmp_path, forbidden):
        with pytest.raises(fsguard.GitCommandNotAllowed):
            fsguard.run_git_readonly((forbidden,), cwd=tmp_path)

    def test_read_only_fs_reads_work(self, tmp_path):
        (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
        adapter = fsguard.ReadOnlyFS(tmp_path)
        assert adapter.read_text("file.txt") == "hello"
        assert adapter.is_file("file.txt")
        assert adapter.exists("file.txt")

    @pytest.mark.parametrize(
        "method,args",
        [
            ("write_text", ("file.txt", "x")),
            ("write_bytes", ("file.txt", b"x")),
            ("mkdir", ("sub",)),
            ("unlink", ("file.txt",)),
            ("rmdir", ("sub",)),
            ("chmod", ("file.txt", 0o755)),
        ],
    )
    def test_read_only_fs_writes_refuse(self, tmp_path, method, args):
        adapter = fsguard.ReadOnlyFS(tmp_path)
        with pytest.raises(fsguard.ReadOnlyViolation):
            getattr(adapter, method)(*args)


# ---------------------------------------------------------------------------
# cache.py
# ---------------------------------------------------------------------------


class TestCache:
    def test_fingerprint_changes_when_file_mtime_or_size_changes(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / "agents").mkdir()
        agent_file = tmp_path / "agents" / "cw.md"
        agent_file.write_text("v1", encoding="utf-8")
        before = cache_mod.compute_repo_fingerprint(tmp_path, ["agents/cw.md"])
        agent_file.write_text("v2 -- longer content", encoding="utf-8")
        after = cache_mod.compute_repo_fingerprint(tmp_path, ["agents/cw.md"])
        assert before.digest() != after.digest()

    def test_fingerprint_stable_when_nothing_changes(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / "agents").mkdir()
        (tmp_path / "agents" / "cw.md").write_text("v1", encoding="utf-8")
        first = cache_mod.compute_repo_fingerprint(tmp_path, ["agents/cw.md"])
        second = cache_mod.compute_repo_fingerprint(tmp_path, ["agents/cw.md"])
        assert first.digest() == second.digest()

    def test_fingerprint_reflects_missing_path(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        fingerprint = cache_mod.compute_repo_fingerprint(tmp_path, ["does/not/exist.md"])
        assert fingerprint.paths == (("does/not/exist.md", -1, -1),)

    def test_cache_put_get_roundtrip(self, tmp_path):
        cache_path = tmp_path / "cache.json"
        cache = cache_mod.ConformanceCache(cache_path)
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        fingerprint = cache_mod.compute_repo_fingerprint(repo, [])
        results = (_pass_result(),)
        assert cache.get(repo, fingerprint) is None
        cache.put(repo, fingerprint, results)
        assert cache.get(repo, fingerprint) == results

    def test_cache_misses_when_fingerprint_changes(self, tmp_path):
        cache_path = tmp_path / "cache.json"
        cache = cache_mod.ConformanceCache(cache_path)
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        (repo / "agents").mkdir()
        (repo / "agents" / "cw.md").write_text("v1", encoding="utf-8")
        fingerprint_one = cache_mod.compute_repo_fingerprint(repo, ["agents/cw.md"])
        cache.put(repo, fingerprint_one, (_pass_result(),))
        (repo / "agents" / "cw.md").write_text("v2 changed", encoding="utf-8")
        fingerprint_two = cache_mod.compute_repo_fingerprint(repo, ["agents/cw.md"])
        assert cache.get(repo, fingerprint_two) is None

    def test_disabled_cache_never_stores_or_hits(self, tmp_path):
        cache = cache_mod.ConformanceCache.disabled()
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        fingerprint = cache_mod.compute_repo_fingerprint(repo, [])
        cache.put(repo, fingerprint, (_pass_result(),))
        assert cache.get(repo, fingerprint) is None
        assert len(cache) == 0

    def test_save_and_reload_round_trips_through_disk(self, tmp_path):
        cache_path = tmp_path / "cache.json"
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        fingerprint = cache_mod.compute_repo_fingerprint(repo, [])

        first = cache_mod.ConformanceCache(cache_path)
        first.put(repo, fingerprint, (_pass_result(), _fail_result()))
        first.save()

        second = cache_mod.ConformanceCache(cache_path)
        assert second.get(repo, fingerprint) == (_pass_result(), _fail_result())

    def test_corrupt_cache_file_is_silently_discarded(self, tmp_path):
        cache_path = tmp_path / "cache.json"
        cache_path.write_text("not json at all {{{", encoding="utf-8")
        cache = cache_mod.ConformanceCache(cache_path)  # must not raise
        assert len(cache) == 0

    def test_default_cache_path_lives_beside_machine_config(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CC_MACHINE_ROOT", str(tmp_path / "machine-root"))
        path = cache_mod.default_cache_path()
        assert path == tmp_path / "machine-root" / "conformance-cache.json"


# ---------------------------------------------------------------------------
# FleetFactory -- proving the World-A fixture builder produces what it
# promises (real git, real orphan tags, discoverable dimension content).
# ---------------------------------------------------------------------------


class TestFleetFactory:
    def test_build_produces_a_manifest_that_validates(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        fleet.product("claude").tier("foundation", rank=40).contributes(
            "agents", {"cw": "real foundation content"}
        )
        fleet.product("claude").tier("personal", rank=10).contributes(
            "agents", {"cw": ""}
        )
        handle = fleet.build()

        layers = load_layers(handle.manifest_path)
        validate_layers(layers)  # must not raise
        assert {layer["id"] for layer in layers} == {
            "claude-foundation",
            "claude-personal",
        }
        # validate_layers requires ascending rank order per product.
        assert [layer["rank"] for layer in layers] == [10, 40] or [
            layer["rank"] for layer in layers
        ] == [10, 40]

    def test_manifest_orders_layers_by_ascending_rank_per_product(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        fleet.product("claude").tier("foundation", rank=40)
        fleet.product("claude").tier("organization", rank=30)
        fleet.product("claude").tier("department", rank=20, unit="engineering")
        fleet.product("claude").tier("personal", rank=10)
        handle = fleet.build()
        layers = load_layers(handle.manifest_path)
        validate_layers(layers)  # raises ManifestError if out of order
        assert [layer["rank"] for layer in layers] == [10, 20, 30, 40]

    def test_is_arity_independent_with_two_tiers(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        fleet.product("codex").tier("foundation", rank=40)
        fleet.product("codex").tier("personal", rank=10)
        handle = fleet.build()
        layers = validate_layers(load_layers(handle.manifest_path))
        assert len(layers) == 2

    def test_orphan_pin_reproduces_rc3_defect(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        tier = fleet.product("claude").tier("foundation", rank=40)
        tier.contributes("agents", {"cw": "content"})
        tier.pin("v5.13.62", orphan=True)
        handle = fleet.build()
        tier_path = handle.tiers[("claude", "foundation")]

        count = subprocess.run(
            ["git", "rev-list", "--count", "v5.13.62"],
            cwd=tier_path,
            capture_output=True,
            text=True,
            check=True,
        )
        assert count.stdout.strip() == "1"  # a parentless single-commit orphan

        ancestry = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "v5.13.62", "main"],
            cwd=tier_path,
            capture_output=True,
            text=True,
        )
        assert ancestry.returncode != 0  # RC-3: no merge-base with main

    def test_non_orphan_pin_is_a_real_ancestor(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        tier = fleet.product("cli").tier("foundation", rank=40)
        tier.contributes("agents", {"do": "content"})
        tier.pin("v0.3.5", orphan=False)
        handle = fleet.build()
        tier_path = handle.tiers[("cli", "foundation")]

        ancestry = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "v0.3.5", "main"],
            cwd=tier_path,
            capture_output=True,
            text=True,
        )
        assert ancestry.returncode == 0  # control case: a real ancestor tag

    def test_contributes_is_discoverable_by_the_real_discovery_module(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        fleet.product("claude").tier("foundation", rank=40).contributes(
            "agents", {"sd": "service designer content"}
        )
        handle = fleet.build()
        layers = validate_layers(load_layers(handle.manifest_path))
        contributions = discover_contributions(layers)
        assert "sd" in contributions["claude-foundation"]["agents"]

    def test_empty_shadow_case_content_is_an_empty_file(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        fleet.product("claude").tier("personal", rank=10).contributes("agents", {"cw": ""})
        handle = fleet.build()
        tier_path = handle.tiers[("claude", "personal")]
        assert (tier_path / "agents" / "cw.md").read_text(encoding="utf-8") == ""

    def test_project_install_write_and_remove(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        fleet.project("degraded-no-hook").install(
            {
                "CLAUDE.md": "## Claude Copilot\n",
                ".claude/hooks/copilot-hook.sh": "#!/bin/sh\necho hook\n",
            }
        ).remove(".claude/hooks/copilot-hook.sh")
        handle = fleet.build()
        project_path = handle.projects["degraded-no-hook"]
        assert (project_path / "CLAUDE.md").exists()
        assert not (project_path / ".claude" / "hooks" / "copilot-hook.sh").exists()

    def test_project_install_accepts_a_callable(self, tmp_path):
        def _seed(root: Path) -> None:
            (root / "seeded.txt").write_text("from callable", encoding="utf-8")

        fleet = FleetFactory(tmp_path)
        fleet.project("scratch").install(_seed)
        handle = fleet.build()
        assert (handle.projects["scratch"] / "seeded.txt").read_text() == "from callable"

    def test_git_clone_local_produces_an_independent_mutable_clone(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        tier = fleet.product("claude").tier("foundation", rank=40)
        tier.write("CLAUDE.md", "## Claude Copilot\n")
        handle = fleet.build()
        source = handle.tiers[("claude", "foundation")]

        clone_dest = tmp_path / "clone-target"
        clone = git_clone_local(source, clone_dest)
        (clone / "CLAUDE.md").write_text("mutated in the clone only\n", encoding="utf-8")

        assert (source / "CLAUDE.md").read_text(encoding="utf-8") == "## Claude Copilot\n"
        assert "mutated" in (clone / "CLAUDE.md").read_text(encoding="utf-8")

    def test_build_env_points_at_the_synthetic_home(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        handle = fleet.build()
        assert handle.env["HOME"] == str(handle.home)
        assert Path(handle.env["CC_MACHINE_ROOT"]).parent.parent == handle.home

    def test_apply_fleet_env_lets_resolve_key_see_the_synthetic_manifest(
        self, tmp_path, apply_fleet_env
    ):
        from cc.core.config import resolve_key

        fleet = FleetFactory(tmp_path)
        fleet.product("claude").tier("foundation", rank=40)
        handle = apply_fleet_env(fleet.build())

        assert resolve_key("layers.manifest") == str(handle.manifest_path)


# ---------------------------------------------------------------------------
# End-to-end smoke: a check-like function using the registry + fleet +
# report machinery together, proving the seams actually fit.
# ---------------------------------------------------------------------------


def test_end_to_end_registered_check_against_a_fleet_renders_and_validates(tmp_path):
    registry = Registry()
    registration = register_check(
        id="tier.shadow.substance",
        layer=Layer.TIER,
        severity=Severity.S0,
        scope=Scope.PER_TIER,
        summary="a nearer tier's winning content must be substantive",
        remediation="Q25 answer A -- fill the personal scaffold",
        expected_today=ExpectedToday.FAIL,
        registry=registry,
    )

    fleet = FleetFactory(tmp_path)
    fleet.product("claude").tier("foundation", rank=40).contributes(
        "agents", {"cw": "real org content, long and substantive"}
    )
    fleet.product("claude").tier("personal", rank=10).contributes("agents", {"cw": ""})
    handle = fleet.build()
    layers = validate_layers(load_layers(handle.manifest_path))
    contributions = discover_contributions(layers)

    winner_content_len = len(
        (handle.tiers[("claude", "personal")] / "agents" / "cw.md").read_text()
    )
    assert winner_content_len == 0  # confirms the fixture set up the bug

    result = registration.result(
        subject="cw",
        verdict=Verdict.FAIL,
        evidence=(
            Evidence(
                kind="extension-file",
                path=str(handle.tiers[("claude", "personal")] / "agents" / "cw.md"),
                expected="substantive content",
                actual="0 bytes",
                detail="shadows claude-foundation's real content",
            ),
        ),
    )

    assert "claude-foundation" in contributions
    text = report.render_human([result], mode=Mode.FAST)
    assert "tier.shadow.substance" in text
    envelope = report.to_envelope([result], mode=Mode.FAST)
    _validate_envelope(envelope)
    assert report.compute_exit_code([result], fail_on=Severity.S0) == 1
