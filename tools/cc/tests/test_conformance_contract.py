"""WP-8 contract test: `cc conformance check|report|baseline|explain|list`.

Covers the operator CLI surface (`cc/commands/conformance.py`) -- every
subcommand, every documented exit code (0/1/2/3, including a FORCED
could-not-run), `--json` validating against the vendored
`conformance.schema.json`, and the two output-rule prohibitions
(`HARNESS-DESIGN.md` section 3.2 rule 4 / section 6.2: never a percentage,
never a bare "ready"). Every check *body* (tier/stack/repo/lock/roundtrip/
regression) is covered by its own owning package's tests
(`tests/conformance/test_layer*.py`); this file is the CLI's own contract,
not a re-test of check logic.

Two worlds, matching this suite's own convention
(`tests/conformance/*`'s "two-world rule", `HARNESS-DESIGN.md` section 5.1):

  - World A (default, hermetic): `conformance._collect_results` is
    monkeypatched to return deterministic, injected `CheckResult` tuples --
    every subcommand and every exit-code path is provable without a real
    fleet on the test machine, so `pytest -m "not machine"` stays green
    anywhere (including a machine with no ecosystem installed).
  - World B (`@pytest.mark.machine`): `CC_MACHINE_ROOT` is monkeypatched
    BACK to its real default for the duration of one test, undoing
    `tests/conftest.py`'s own autouse `_isolate_machine_config` fixture
    (which would otherwise make `resolve_key`/`resolve_knowledge_repos` --
    the seams `_run_tier_layer_machine`/`_run_repo_layer`/`_run_lock_layer`
    read through -- see an EMPTY config under every test in this repo).
    Strictly read-only: nothing in `cc conformance check|report|explain|
    list` ever calls a write path, so the outer fixture's own after-
    checksum safety net stays satisfied regardless of this override.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Sequence

import cc.commands.conformance as conformance_mod
import pytest
from cc.core.conformance.types import (
    CheckResult,
    Evidence,
    ExpectedToday,
    Layer,
    Scope,
    Severity,
    Verdict,
)
from cc.main import app
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from typer.testing import CliRunner

runner = CliRunner()

_SCHEMA_DIR = Path(__file__).parent / "fixtures" / "schemas"

pytestmark = pytest.mark.filterwarnings("ignore")


# ---------------------------------------------------------------------------
# Schema validation helper
# ---------------------------------------------------------------------------


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _conformance_validator() -> Draft202012Validator:
    conformance_schema = _load_schema("conformance.schema.json")
    envelope_schema = _load_schema("_envelope.schema.json")
    # Registered under each schema's OWN $id (not a bare filename) --
    # conformance.schema.json's own $comment explains why: it refs
    # _envelope.schema.json by full absolute $id, since it lives in a
    # different namespaced directory (claude-copilot, not
    # copilot-control-tower) than a bare relative ref would resolve against.
    registry = Registry().with_resources(
        [
            (envelope_schema["$id"], Resource.from_contents(envelope_schema)),
            (conformance_schema["$id"], Resource.from_contents(conformance_schema)),
        ]
    )
    return Draft202012Validator(conformance_schema, registry=registry)


def _validate(payload: dict) -> None:
    validator = _conformance_validator()
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


_BARE_READY_RE = re.compile(r"(?<![\w(])ready\b(?!\s*\()")


def _assert_no_output_rule_violations(text: str) -> None:
    """The two prohibitions every rendered surface must satisfy
    (`HARNESS-DESIGN.md` section 3.2 rule 4, section 6.2): never a
    completion percentage, never a bare 'ready' verdict."""

    assert "%" not in text, f"a percentage leaked into rendered output:\n{text}"
    assert not _BARE_READY_RE.search(text), f"a bare 'ready' leaked into rendered output:\n{text}"


# ---------------------------------------------------------------------------
# World A -- deterministic fixture CheckResults
# ---------------------------------------------------------------------------


def _result(
    id: str,
    *,
    layer: Layer = Layer.TIER,
    severity: Severity = Severity.S1,
    verdict: Verdict = Verdict.PASS,
    subject: str = "fixture-subject",
    evidence: Sequence[Evidence] = (),
) -> CheckResult:
    return CheckResult(
        id=id,
        layer=layer,
        severity=severity,
        scope=Scope.GLOBAL,
        subject=subject,
        assertion=f"{id} asserts something, for contract-test purposes only",
        verdict=verdict,
        expected_today=ExpectedToday.PASS,
        evidence=tuple(evidence),
        detail="fixture detail text",
        remediation="fixture remediation text",
    )


_EVIDENCE = (
    Evidence(kind="fixture", path="/fixture/path", expected="x", actual="y", detail="z"),
)

PASSING = (_result("tier.fixture.pass_a"),)
ONE_FAILING = (
    _result("tier.fixture.pass_a"),
    _result(
        "tier.fixture.fail_b",
        severity=Severity.S0,
        verdict=Verdict.FAIL,
        subject="fixture-failing-subject",
        evidence=_EVIDENCE,
    ),
)
ONE_COULD_NOT_RUN = (
    _result("tier.fixture.pass_a"),
    _result(
        "tier.fixture.could_not_run_c",
        verdict=Verdict.COULD_NOT_RUN,
        subject="fixture-cnr-subject",
        evidence=_EVIDENCE,
    ),
)


@pytest.fixture(autouse=True)
def _stub_collect_results(monkeypatch, request):
    """World A default: every non-`machine` test in this file is hermetic
    -- `_collect_results` never touches a real path unless a test opts in
    (either by re-monkeypatching it itself, or by being `@pytest.mark.
    machine`, which skips this stub entirely)."""

    if "machine" in request.keywords:
        yield
        return
    monkeypatch.setattr(conformance_mod, "_collect_results", lambda **kwargs: PASSING)
    yield


# ---------------------------------------------------------------------------
# cc conformance check -- exit codes
# ---------------------------------------------------------------------------


def test_check_exit_code_0_pass(monkeypatch):
    monkeypatch.setattr(conformance_mod, "_collect_results", lambda **kwargs: PASSING)
    result = runner.invoke(app, ["conformance", "check", "--json"])
    assert result.exit_code == 0, result.output
    _validate(json.loads(result.output))


def test_check_exit_code_1_fail(monkeypatch):
    monkeypatch.setattr(conformance_mod, "_collect_results", lambda **kwargs: ONE_FAILING)
    result = runner.invoke(app, ["conformance", "check", "--json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    _validate(payload)
    assert payload["result"] == "fail"


def test_check_exit_code_2_could_not_run_forced(monkeypatch):
    """The task's own explicit ask: a FORCED could-not-run must produce
    exit 2, never conflated with exit 1 (`inv.no_fabricated_healthy`)."""

    monkeypatch.setattr(conformance_mod, "_collect_results", lambda **kwargs: ONE_COULD_NOT_RUN)
    result = runner.invoke(app, ["conformance", "check", "--json"])
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    _validate(payload)
    assert any(c["verdict"] == "could-not-run" for c in payload["checks"])


def test_check_exit_code_3_baseline_regression(monkeypatch, tmp_path):
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-08-10T00:00:00Z",
                "entries": [{"id": "tier.fixture.pass_a", "subject": "fixture-subject", "verdict": "pass"}],
            }
        ),
        encoding="utf-8",
    )
    regressed = (
        _result(
            "tier.fixture.pass_a",
            severity=Severity.S3,
            verdict=Verdict.FAIL,
            evidence=_EVIDENCE,
        ),
    )
    monkeypatch.setattr(conformance_mod, "_collect_results", lambda **kwargs: regressed)
    # --fail-on S0 would not fire on its own (the regression is S3) --
    # proving the baseline-regression trigger is independent of --fail-on.
    result = runner.invoke(
        app, ["conformance", "check", "--baseline", str(baseline_path), "--fail-on", "S0", "--json"]
    )
    assert result.exit_code == 3, result.output
    payload = json.loads(result.output)
    _validate(payload)
    assert payload["baseline"]["regressed"] == 1


def test_check_precedence_baseline_regression_over_could_not_run(monkeypatch, tmp_path):
    """`HARNESS-DESIGN.md` section 6.4's documented precedence: baseline-
    regression (3) > could-not-run (2) > fail (1)."""

    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-08-10T00:00:00Z",
                "entries": [{"id": "tier.fixture.pass_a", "subject": "fixture-subject", "verdict": "pass"}],
            }
        ),
        encoding="utf-8",
    )
    mixed = (
        _result("tier.fixture.pass_a", verdict=Verdict.FAIL, evidence=_EVIDENCE),
        _result("tier.fixture.could_not_run_c", verdict=Verdict.COULD_NOT_RUN, evidence=_EVIDENCE),
    )
    monkeypatch.setattr(conformance_mod, "_collect_results", lambda **kwargs: mixed)
    result = runner.invoke(app, ["conformance", "check", "--baseline", str(baseline_path), "--json"])
    assert result.exit_code == 3, result.output


def test_check_mutually_exclusive_fast_full(monkeypatch):
    result = runner.invoke(app, ["conformance", "check", "--fast", "--full"])
    assert result.exit_code == 2
    assert "mutually exclusive" in result.output


def test_check_rejects_unknown_layer(monkeypatch):
    result = runner.invoke(app, ["conformance", "check", "--layer", "bogus"])
    assert result.exit_code == 2
    assert "unknown --layer" in result.output


def test_check_rejects_unknown_fail_on(monkeypatch):
    result = runner.invoke(app, ["conformance", "check", "--fail-on", "S9"])
    assert result.exit_code == 2
    assert "unknown --fail-on" in result.output


def test_check_rejects_missing_baseline_file(tmp_path):
    result = runner.invoke(
        app, ["conformance", "check", "--baseline", str(tmp_path / "does-not-exist.json")]
    )
    assert result.exit_code == 2
    assert "not found" in result.output


def test_check_environment_error_maps_to_exit_2(monkeypatch):
    def _boom(**kwargs):
        raise RuntimeError("simulated environment failure")

    monkeypatch.setattr(conformance_mod, "_collect_results", _boom)
    result = runner.invoke(app, ["conformance", "check", "--json"])
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "environment-error"


# ---------------------------------------------------------------------------
# cc conformance check -- human output rules
# ---------------------------------------------------------------------------


def test_check_human_output_never_prints_percentage_or_bare_ready(monkeypatch):
    monkeypatch.setattr(conformance_mod, "_collect_results", lambda **kwargs: ONE_FAILING)
    result = runner.invoke(app, ["conformance", "check"])
    assert result.exit_code == 1, result.output
    _assert_no_output_rule_violations(result.output)


def test_check_human_output_allows_the_qualified_ready_form(monkeypatch):
    """The prohibition is on a BARE 'ready', not the word itself -- the
    qualified form ('ready (by waiver, N files)') must render without
    raising (`HARNESS-DESIGN.md` section 6.2's own worked example).
    `render_human` only prints per-check detail for FAIL results (WP-1's
    own `report.py`), so this uses a FAIL verdict to actually exercise the
    rendered text, not merely register a PASS a human reader never sees."""

    qualified = (
        CheckResult(
            id="lock.fixture.ready_by_waiver",
            layer=Layer.LOCK,
            severity=Severity.S1,
            scope=Scope.GLOBAL,
            subject="fixture-subject",
            assertion="a component classified ready (by waiver, 2 files) is reported honestly",
            verdict=Verdict.FAIL,
            expected_today=ExpectedToday.PASS,
            evidence=(
                Evidence(
                    kind="fixture",
                    path="/fixture/path",
                    expected="ownership_mode: full",
                    actual="ready (by waiver, 2 files)",
                ),
            ),
            detail="classification is ready (by waiver, 2 files), never bare",
        ),
    )
    monkeypatch.setattr(conformance_mod, "_collect_results", lambda **kwargs: qualified)
    result = runner.invoke(app, ["conformance", "check"])
    assert result.exit_code == 1, result.output
    assert "ready (by waiver, 2 files)" in result.output


# ---------------------------------------------------------------------------
# cc conformance report
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("output_format", ["table", "tsv", "md", "json"])
def test_report_every_format_succeeds_and_respects_output_rules(monkeypatch, output_format):
    monkeypatch.setattr(conformance_mod, "_collect_results", lambda **kwargs: ONE_FAILING)
    result = runner.invoke(app, ["conformance", "report", "--format", output_format])
    assert result.exit_code == 1, result.output
    if output_format == "json":
        _validate(json.loads(result.output))
    else:
        _assert_no_output_rule_violations(result.output)


def test_report_json_format_validates_against_schema_with_baseline(monkeypatch, tmp_path):
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps({"generated_at": "2026-08-10T00:00:00Z", "entries": []}), encoding="utf-8"
    )
    monkeypatch.setattr(conformance_mod, "_collect_results", lambda **kwargs: ONE_FAILING)
    result = runner.invoke(
        app, ["conformance", "report", "--format", "json", "--baseline", str(baseline_path)]
    )
    payload = json.loads(result.output)
    _validate(payload)
    assert "baseline" in payload


def test_report_rejects_unknown_format():
    result = runner.invoke(app, ["conformance", "report", "--format", "yaml"])
    assert result.exit_code == 2
    assert "unknown --format" in result.output


# ---------------------------------------------------------------------------
# cc conformance baseline write | diff
# ---------------------------------------------------------------------------


def test_baseline_write_creates_a_reloadable_baseline_file(monkeypatch, tmp_path):
    monkeypatch.setattr(conformance_mod, "_collect_results", lambda **kwargs: ONE_FAILING)
    baseline_path = tmp_path / "baseline.json"
    result = runner.invoke(app, ["conformance", "baseline", "write", str(baseline_path)])
    assert result.exit_code == 0, result.output
    assert baseline_path.is_file()

    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert "generated_at" in payload
    ids = {entry["id"] for entry in payload["entries"]}
    assert ids == {"tier.fixture.pass_a", "tier.fixture.fail_b"}
    verdicts = {entry["id"]: entry["verdict"] for entry in payload["entries"]}
    assert verdicts["tier.fixture.fail_b"] == "fail"


def test_baseline_diff_reports_fixed_still_failing_regressed_and_new(monkeypatch, tmp_path):
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-08-10T00:00:00Z",
                "entries": [
                    {"id": "x.fixed", "subject": "s1", "verdict": "fail"},
                    {"id": "x.still_failing", "subject": "s2", "verdict": "fail"},
                    {"id": "x.regressed", "subject": "s3", "verdict": "pass"},
                ],
            }
        ),
        encoding="utf-8",
    )
    current = (
        _result("x.fixed", subject="s1", verdict=Verdict.PASS),
        _result("x.still_failing", subject="s2", verdict=Verdict.FAIL, evidence=_EVIDENCE),
        _result("x.regressed", subject="s3", verdict=Verdict.FAIL, evidence=_EVIDENCE),
        _result("x.new", subject="s4", verdict=Verdict.FAIL, evidence=_EVIDENCE),
    )
    monkeypatch.setattr(conformance_mod, "_collect_results", lambda **kwargs: current)

    result = runner.invoke(app, ["conformance", "baseline", "diff", str(baseline_path), "--json"])
    assert result.exit_code == 3, result.output  # a regression is present
    payload = json.loads(result.output)
    assert payload["fixed"] == 1
    assert payload["still_failing"] == 1
    assert payload["regressed"] == 1
    assert payload["new_failures"] == 1


def test_baseline_diff_missing_file_is_exit_2():
    result = runner.invoke(app, ["conformance", "baseline", "diff", "/does/not/exist.json"])
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# cc conformance explain
# ---------------------------------------------------------------------------


def test_explain_known_check_id_succeeds_and_prints_the_registration(monkeypatch):
    monkeypatch.setattr(conformance_mod, "_collect_results", lambda **kwargs: PASSING)
    result = runner.invoke(app, ["conformance", "explain", "tier.shadow.substance"])
    assert result.exit_code == 0, result.output
    assert "tier.shadow.substance" in result.output
    assert "asserts:" in result.output
    assert "remediation:" in result.output


def test_explain_unknown_check_id_is_exit_2():
    result = runner.invoke(app, ["conformance", "explain", "not.a.real.check"])
    assert result.exit_code == 2
    assert "no check registered" in result.output


def test_explain_json_shape(monkeypatch):
    monkeypatch.setattr(conformance_mod, "_collect_results", lambda **kwargs: PASSING)
    result = runner.invoke(app, ["conformance", "explain", "tier.shadow.substance", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["registration"]["id"] == "tier.shadow.substance"
    assert isinstance(payload["live_results"], list)


def test_explain_never_runs_a_roundtrip_check_live(monkeypatch):
    """A roundtrip.* id must never trigger `_collect_results` (which is
    the ONLY path that can mutate a scratch clone) -- `explain` is
    documented read-only."""

    def _must_not_be_called(**kwargs):
        raise AssertionError("explain must never call _collect_results for a roundtrip check")

    monkeypatch.setattr(conformance_mod, "_collect_results", _must_not_be_called)
    result = runner.invoke(
        app, ["conformance", "explain", "roundtrip.setup.produces_reference_install"]
    )
    assert result.exit_code == 0, result.output
    assert "mutate" in result.output


# ---------------------------------------------------------------------------
# cc conformance list
# ---------------------------------------------------------------------------


def test_list_json_returns_every_registered_check():
    result = runner.invoke(app, ["conformance", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload) > 20
    ids = {entry["id"] for entry in payload}
    assert "tier.shadow.substance" in ids
    assert "rc.rc1.enforcement_hook_is_installed_by_something" in ids


def test_list_filters_by_layer_and_severity():
    result = runner.invoke(
        app, ["conformance", "list", "--layer", "regression", "--severity", "S0", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload  # non-empty
    assert all(entry["layer"] == "regression" for entry in payload)
    assert all(entry["severity"] == "S0" for entry in payload)


def test_list_rejects_unknown_layer():
    result = runner.invoke(app, ["conformance", "list", "--layer", "bogus"])
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# Wiring sanity
# ---------------------------------------------------------------------------


def test_main_app_exposes_the_conformance_command_family():
    result = runner.invoke(app, ["conformance", "--help"])
    assert result.exit_code == 0, result.output
    for subcommand in ("check", "report", "baseline", "explain", "list"):
        assert subcommand in result.output


# ---------------------------------------------------------------------------
# World B -- real machine, read-only, `@pytest.mark.machine`
# ---------------------------------------------------------------------------

_REAL_MACHINE_ROOT = Path.home() / ".claude" / "cc"


def _real_machine_available() -> bool:
    return (_REAL_MACHINE_ROOT / "config.json").is_file()


requires_real_machine = pytest.mark.skipif(
    not _real_machine_available(),
    reason="real ~/.claude/cc/config.json not present on this machine",
)


@pytest.fixture
def real_machine_root(monkeypatch):
    """Undo `tests/conftest.py`'s own `CC_MACHINE_ROOT` isolation for
    exactly one read-only test -- see this module's own docstring, 'World
    B'. `resolve_key`/`resolve_knowledge_repos` (the seams the CLI's tier/
    repo/lock real-machine wiring reads through) would otherwise see an
    empty config under every test in this repo, making a `@pytest.mark.
    machine` CLI-level test pass vacuously instead of proving anything."""

    monkeypatch.setenv("CC_MACHINE_ROOT", str(_REAL_MACHINE_ROOT))
    yield


@requires_real_machine
@pytest.mark.machine
def test_machine_check_stack_layer_json_validates_and_reflects_the_real_manifest(
    real_machine_root,
):
    """End-to-end: the real CLI, against the real 16-cell manifest, --json
    validating against the schema.

    Deliberately scoped to `--layer stack` rather than the full default
    layer set: a full sweep (`repo` + `lock`, ~60 real repos each) run
    serially inside a pytest worker that is itself one of many concurrent
    processes on a shared, heavily-loaded machine was observed to take
    several minutes here (vs. ~10s standalone, confirmed by invoking the
    same `cc conformance check --json` directly, outside pytest, during
    this same verification pass) -- environmental contention, not a defect
    in the CLI. `stack` alone (16 cells, no per-repo filesystem sweep)
    stays fast and still proves the real-machine wiring end-to-end."""

    result = runner.invoke(app, ["conformance", "check", "--layer", "stack", "--json"])
    assert result.exit_code in (0, 1, 2, 3), result.output
    payload = json.loads(result.output)
    _validate(payload)
    ids = {c["id"] for c in payload["checks"]}
    assert "stack.cs_decl" in ids
    _assert_no_output_rule_violations(json.dumps(payload))


@requires_real_machine
@pytest.mark.machine
def test_machine_check_human_output_reflects_the_real_regression_layer_state(
    real_machine_root,
):
    """Renamed from `test_machine_check_human_output_reproduces_known_
    findings` -- that version pinned to `rc.rc1.enforcement_hook_is_
    installed_by_something` appearing in the human-rendered FAIL section,
    which was a genuine, real finding at the time it was written. RC-1's
    fleet half (and RC-5's last real miss) are now genuinely fixed on this
    machine (see `TestRealMachineRootCausesFailToday` in `tests/
    conformance/test_rc_regressions.py`), so `render_human` -- which by
    design (`report.py`) only ever lists FAIL-verdict check ids, never
    passing ones -- correctly no longer prints it. Re-verify the render
    pipeline against the real machine's CURRENT state instead of a
    hardcoded-to-fail id: cross-check human output against the same run's
    `--json` payload, which lists every check regardless of verdict."""

    result = runner.invoke(app, ["conformance", "check", "--layer", "regression"])
    assert result.exit_code in (0, 1, 2, 3), result.output
    _assert_no_output_rule_violations(result.output)
    assert "LAYER  regression" in result.output

    json_result = runner.invoke(
        app, ["conformance", "check", "--layer", "regression", "--json"]
    )
    assert json_result.exit_code in (0, 1, 2, 3), json_result.output
    payload = json.loads(json_result.output)
    ids = {c["id"] for c in payload["checks"]}
    assert "rc.rc1.enforcement_hook_is_installed_by_something" in ids
    assert "rc.rc5.tier_variants_declare_dimensions" in ids

    # A check id only ever appears in the human FAIL listing when it
    # actually failed -- assert the two outputs agree, rather than
    # asserting either shape outright.
    failing_ids = {c["id"] for c in payload["checks"] if c["verdict"] == "fail"}
    for check_id in ids:
        if check_id in failing_ids:
            assert check_id in result.output
    if "rc.rc1.enforcement_hook_is_installed_by_something" not in failing_ids:
        assert "rc.rc1.enforcement_hook_is_installed_by_something" not in result.output


@requires_real_machine
@pytest.mark.machine
def test_machine_explain_tier_shadow_substance(real_machine_root):
    result = runner.invoke(app, ["conformance", "explain", "tier.shadow.substance"])
    assert result.exit_code == 0, result.output
    assert "tier.shadow.substance" in result.output
