"""WP-6 tests: Layer 5 — round-trip / end-to-end (`HARNESS-DESIGN.md` §4
Layer 5, `TEST-MATRIX.md` §5).

Every subject here is a disposable scratch git repo created fresh inside
`tmp_path` (there is nothing to clone — a brand-new project has no prior
content) with `$HOME` also redirected into `tmp_path`
(`roundtrip.build_scratch_env`). No real repo is ever a write target; the
module-autouse `_conformance_machine_readonly_tripwire` fixture (inherited
from `conftest.py`) fails the whole run if that promise is broken.

**TEST-MATRIX.md §5 test-ID cross-reference** (used verbatim as the map from
a matrix row to the test that implements it):

  RT-1  test_rt1_setup_project_produces_reference_install
  RT-2  test_rt2_update_project_closes_command_gap
  RT-3  test_rt3_second_update_is_idempotent (first live run — this test
        itself establishes RT-3's ground truth; TEST-MATRIX.md records RT-3
        as "UNVERIFIED — no audit evidence either way ... treat the first
        live run as the baseline, not as confirmation of either outcome.")
  RT-4  test_rt4_hook_is_never_installed
  RT-5  codex-copilot/scripts/setup-project.sh's second-run behavior is OUT
        OF SCOPE for this test module: that script lives in the
        codex-copilot repo, not claude-copilot, and this package owns only
        claude-copilot/tools/cc (per the task brief's file-ownership rule).
        `rc.rc2.codex_has_an_updater` (WP-7's root_causes.py) is the
        registered pin for the underlying regression; this module does not
        silently claim RT-5 coverage it does not have.
  RT-6  test_rt6_update_preserves_project_owned_agent

Plus `test_degraded_install_is_detected` — the task's explicit sixth
requirement ("include the degraded-install fixture so the harness proves it
detects a bad install, not just a good one"), which has no TEST-MATRIX.md
RT-N id of its own.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping

import pytest
from cc.core.conformance import roundtrip as rt
from cc.core.conformance.types import ExpectedToday, Verdict
from cc.core.ecosystem.project_integration import inspect_project_integration

from .conftest import init_git_repo

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE_MANIFEST_PATH = FIXTURES / "reference-install" / "manifest.json"
DEGRADED_SHAPES_PATH = FIXTURES / "degraded" / "known-bad-shapes.json"

pytestmark = pytest.mark.filterwarnings("ignore")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def framework_repo_root() -> Path:
    return rt.discover_framework_repo_root()


@pytest.fixture(scope="module")
def cc_bin(framework_repo_root: Path) -> Path:
    return rt.discover_cc_bin(framework_repo_root)


@pytest.fixture(scope="module")
def reference() -> dict:
    return rt.load_reference_manifest(REFERENCE_MANIFEST_PATH)


@pytest.fixture(scope="module")
def degradation_shapes() -> tuple[rt.DegradationShape, ...]:
    return rt.load_degradation_shapes(DEGRADED_SHAPES_PATH)


@pytest.fixture
def scratch(tmp_path: Path, framework_repo_root: Path, cc_bin: Path) -> SimpleNamespace:
    """One disposable scratch project + fake $HOME per test."""

    home = tmp_path / "home"
    rt.materialize_framework_source(home / ".claude" / "copilot", framework_repo_root)
    project = tmp_path / "project"
    project.mkdir()
    init_git_repo(project)
    return SimpleNamespace(
        home=home,
        project=project,
        framework_repo_root=framework_repo_root,
        cc_bin=cc_bin,
    )


def _build_synthetic_reference_project(project: Path, reference: Mapping) -> None:
    """Build a tree that matches `reference` (the checked-in
    `reference-install/manifest.json` fixture) exactly, with no real bash
    execution — the "what correct looks like" fixture the design's own
    §5.2 text describes ("Reference install as data ... Layers 3 and 5 both
    consume it"). Used both to prove the comparison logic itself is correct
    (`test_check_produces_reference_install_passes_on_a_synthetic_exact_match`)
    and as the "seed the reference install" starting point for degradation
    tests, since today's real installer cannot itself reach this shape yet
    (RT-1's own findings)."""

    claude_ref = reference["claude"]
    codex_ref = reference["codex"]

    (project / ".claude" / "commands").mkdir(parents=True)
    for name in claude_ref["commands"]["names"]:
        (project / ".claude" / "commands" / f"{name}.md").write_text(
            "x", encoding="utf-8"
        )
    (project / ".claude" / "agents").mkdir(parents=True)
    for name in claude_ref["agents"]["names"]:
        (project / ".claude" / "agents" / f"{name}.md").write_text(
            "x", encoding="utf-8"
        )
    hook = project / ".claude" / "hooks" / "copilot-hook.sh"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/bin/sh\n", encoding="utf-8")
    hook.chmod(0o755)
    fitness = project / ".claude" / "fitness-check.sh"
    fitness.write_text("#!/bin/sh\n", encoding="utf-8")
    fitness.chmod(0o755)
    (project / ".mcp.json").write_text(
        json.dumps(claude_ref["mcp_json"]), encoding="utf-8"
    )
    (project / ".claude" / "cc").mkdir(parents=True)
    (project / ".claude" / "cc" / "config.json").write_text(
        json.dumps(
            {
                "$schema": claude_ref["cc_config"]["schema"],
                "version": 1,
                "paths": {"shared_docs": "@machine", "knowledge_repo": "@machine"},
            }
        ),
        encoding="utf-8",
    )
    (project / "CLAUDE.md").write_text(
        f"{claude_ref['claude_md_heading']}\n", encoding="utf-8"
    )
    memory_dir = project / ".claude" / "memory" / "entries"
    memory_dir.mkdir(parents=True)
    (memory_dir / ".gitkeep").write_text("", encoding="utf-8")
    (project / "copilot.lock.json").write_text("{}", encoding="utf-8")
    (project / "copilot.project.json").write_text(
        json.dumps({"schema_version": "1.0", "components": ["claude"]}),
        encoding="utf-8",
    )

    plugin_dir = project / "plugins" / "codex-copilot"
    plugin_dir.mkdir(parents=True)
    for index in range(codex_ref["plugin_file_count"]):
        (plugin_dir / f"file{index}.txt").write_text("x", encoding="utf-8")
    skills_dir = project / ".claude" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "codex-copilot").symlink_to(
        codex_ref["skill_bridge_target"], target_is_directory=True
    )


# ---------------------------------------------------------------------------
# RT-1 — a fresh /setup-project reproduces the reference install
# ---------------------------------------------------------------------------


def test_rt1_setup_project_produces_reference_install(scratch, reference):
    run = rt.run_setup_project(
        scratch.project,
        framework_repo_root=scratch.framework_repo_root,
        home=scratch.home,
        cc_bin=scratch.cc_bin,
    )
    # Every extracted step must at least be *runnable* bash -- a non-empty
    # extraction with zero steps would silently prove nothing.
    assert run.steps, "no bash steps were extracted from setup-project.md"

    results = rt.check_produces_reference_install(
        project=scratch.project, reference=reference, subject_prefix="rt1-setup"
    )
    by_facet = {result.subject.split("::")[-1]: result for result in results}

    # Facets known, live, to already match the reference (must stay PASS —
    # these are the check's own regression controls). RC-1/RC-4 fix,
    # re-verified live 2026-08-10: a fresh /setup-project alone (no
    # /update-project needed) now also reproduces the full 16-agent roster
    # (including 'kc'), all 7 project commands, the installed+executable
    # enforcement hook, AND a genuinely generated copilot.lock.json -- the
    # `cc settings-hook add` call Step 6 already runs (added for RC-1)
    # itself writes a real mutation-ledger lock via
    # core/ecosystem/mutations.py, not a copied template. `declaration`
    # joined the same "must stay PASS" group when Step 6D was added:
    # copilot.project.json is now written/merged from what this run
    # genuinely installed (repo.d09.portable_declaration's own fix, same
    # shape as RC-1/RC-4). Five facets total have moved out of "known
    # today FAIL" into this group.
    for facet in (
        "mcp_json",
        "cc_config",
        "claude_md_heading",
        "fitness_check",
        "memory_gitkeep",
        "agents",
        "commands",
        "hook",
        "lock",
        "declaration",
    ):
        assert by_facet[facet].verdict is Verdict.PASS, (
            f"{facet} regressed: {by_facet[facet].detail} "
            f"{[e.as_dict() for e in by_facet[facet].evidence]}"
        )
        assert by_facet[facet].expected_today is ExpectedToday.PASS

    # The one facet still genuinely broken today -- asserted, not assumed:
    # codex's plugin tree is a structural gap /setup-project never touches
    # at all (a separate installer, codex-copilot/scripts/setup-project.sh,
    # owns it entirely).
    for facet in ("codex",):
        assert by_facet[facet].verdict is Verdict.FAIL, (
            f"{facet} unexpectedly {by_facet[facet].verdict.value} -- if "
            "setup-project.md was fixed to close this gap, update this "
            "test's expectation (and remove the corresponding finding from "
            "the WP-6 return message)."
        )
        assert by_facet[facet].expected_today is ExpectedToday.FAIL

    # Cross-reference: in-process WRAP of project_integration.py, per the
    # task's explicit instruction to use it rather than reimplementing
    # verification. Its capability census must agree with observe_install()
    # on the raw agent/command counts (both are counting the same files).
    inspection = _inspect(scratch.project, scratch.framework_repo_root)
    observed = rt.observe_install(scratch.project)
    assert inspection["capabilities"]["agents"] == len(observed["agent_names"])
    assert inspection["capabilities"]["commands"] == len(observed["command_names"])
    # Never 'ready' by construction (no lock at all yet) -- and if it ever
    # were, printing it bare would violate report.py's own refusal; this
    # assertion protects against accidentally treating "ready" as a pass
    # oracle anywhere in this module (EXISTING-VERIFICATION.md section 2).
    assert inspection["classification"] != "ready"


def _inspect(project: Path, framework_repo_root: Path) -> dict:
    return inspect_project_integration(
        project,
        claude_root=framework_repo_root,
        codex_root=framework_repo_root,
    )


# ---------------------------------------------------------------------------
# roundtrip.setup.reports_only_what_it_did
# ---------------------------------------------------------------------------


def test_setup_and_update_report_text_matches_measured_agent_count(scratch):
    rt.run_setup_project(
        scratch.project,
        framework_repo_root=scratch.framework_repo_root,
        home=scratch.home,
        cc_bin=scratch.cc_bin,
    )
    results = rt.check_reports_only_what_it_did(
        framework_repo_root=scratch.framework_repo_root,
        project=scratch.project,
        subject="rt1-setup",
    )
    assert len(results) == 2
    # RC-1 fix, re-verified live 2026-08-10: the roster loop now actually
    # produces 16 agent files (including 'kc'), so both installers'
    # unconditional "16 agent files" claim is now honest, not a disagreement
    # with the measured roster.
    for result in results:
        assert result.verdict is Verdict.PASS, (
            "expected the '16 agent files' claim to now match the measured "
            f"roster: {result.detail}"
        )
        assert result.expected_today is ExpectedToday.PASS


# ---------------------------------------------------------------------------
# RT-4 — the enforcement hook is never installed (RC-1)
# ---------------------------------------------------------------------------


def test_rt4_hook_is_installed_by_setup_project(scratch):
    """Renamed from `test_rt4_hook_is_never_installed` -- RC-1 fix,
    re-verified live 2026-08-10: setup-project.md now cp's + chmod's
    .claude/hooks/copilot-hook.sh and registers it via `cc settings-hook
    add`. The old name described the bug this test now proves is fixed."""

    rt.run_setup_project(
        scratch.project,
        framework_repo_root=scratch.framework_repo_root,
        home=scratch.home,
        cc_bin=scratch.cc_bin,
    )
    rt.run_update_project(
        scratch.project,
        framework_repo_root=scratch.framework_repo_root,
        home=scratch.home,
        cc_bin=scratch.cc_bin,
    )
    result = rt.check_installs_enforcement_hook(project=scratch.project, subject="rt4")
    assert result.verdict is Verdict.PASS
    assert result.expected_today is ExpectedToday.PASS
    # Confirm the SOURCE genuinely has the file (materialize_framework_source
    # copied it) -- unchanged control, still relevant now that the installer
    # also reaches for it.
    source_hook = (
        scratch.home / ".claude" / "copilot" / ".claude" / "hooks" / "copilot-hook.sh"
    )
    assert source_hook.is_file()


def test_check_installs_enforcement_hook_still_detects_absence(tmp_path):
    """A check that can no longer fail is worthless (HARNESS-DESIGN.md
    section 9.3): `check_installs_enforcement_hook` must still report FAIL
    against a project that genuinely lacks the hook, independent of
    whether today's real installer reaches it (proven above)."""

    project = tmp_path / "no-hook"
    project.mkdir()
    result = rt.check_installs_enforcement_hook(project=project, subject="synthetic")
    assert result.verdict is Verdict.FAIL
    assert result.root_cause == "rc.rc1.enforcement_hook_is_installed_by_something"


# ---------------------------------------------------------------------------
# RT-2 — /update-project closes the command gap
# ---------------------------------------------------------------------------


def test_rt2_update_project_closes_command_gap(scratch):
    rt.run_setup_project(
        scratch.project,
        framework_repo_root=scratch.framework_repo_root,
        home=scratch.home,
        cc_bin=scratch.cc_bin,
    )
    before = rt.observe_install(scratch.project)
    # RC-1 fix, re-verified live 2026-08-10: setup-project.md's Step 5 now
    # copies all 7 project commands directly, not just protocol+continue --
    # RT-1's own baseline moved from a 2-command subset to the full set.
    assert before["command_names"] == tuple(sorted(rt.REFERENCE_COMMANDS))

    update_run = rt.run_update_project(
        scratch.project,
        framework_repo_root=scratch.framework_repo_root,
        home=scratch.home,
        cc_bin=scratch.cc_bin,
    )
    assert update_run.steps

    result = rt.check_closes_command_gap(project=scratch.project, subject="rt2")
    assert result.verdict is Verdict.PASS, (
        f"expected all 7 project commands after /update-project: "
        f"{rt.observe_install(scratch.project)['command_names']}"
    )
    assert result.expected_today is ExpectedToday.PASS


# ---------------------------------------------------------------------------
# RT-3 — is a second /update-project run a true no-op?
# ---------------------------------------------------------------------------


def test_rt3_second_update_is_idempotent(scratch):
    rt.run_setup_project(
        scratch.project,
        framework_repo_root=scratch.framework_repo_root,
        home=scratch.home,
        cc_bin=scratch.cc_bin,
    )
    rt.run_update_project(
        scratch.project,
        framework_repo_root=scratch.framework_repo_root,
        home=scratch.home,
        cc_bin=scratch.cc_bin,
    )
    before_tree = _tree_snapshot(scratch.project)

    rt.run_update_project(
        scratch.project,
        framework_repo_root=scratch.framework_repo_root,
        home=scratch.home,
        cc_bin=scratch.cc_bin,
    )
    after_tree = _tree_snapshot(scratch.project)

    diff_paths = sorted(_diff_relative_paths(before_tree, after_tree))
    # TEST-MATRIX.md RT-3: "the first live run establishes the baseline, not
    # confirmation of either outcome" -- this assertion below IS that first
    # live run. It is written to FAIL loudly (not silently downgrade to a
    # warning) if the second update is not byte-identical, because a
    # harness that reports fewer failures than reality is worthless
    # (HARNESS-DESIGN.md's stated purpose). As measured on this machine,
    # this run is idempotent -- update-project.md's own existence guards
    # (`[ ! -f ".claude/memory/.gitignore" ]` etc.) hold.
    expected_today = ExpectedToday.FAIL if diff_paths else ExpectedToday.PASS
    result = rt.check_update_idempotent(
        diff_paths=diff_paths, subject="rt3", expected_today=expected_today
    )
    assert result.verdict is Verdict.PASS, (
        f"a second /update-project run was NOT idempotent -- {len(diff_paths)} "
        f"path(s) differ: {diff_paths}"
    )


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    """A path->content snapshot excluding volatile, machine-local paths
    (`.git/` metadata and anything under `.claude/memory/` -- pure local
    cache/index state, not part of the installed tree's identity, per
    `roundtrip.check_update_idempotent`'s own docstring)."""

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
    changed = set()
    for key in set(before) | set(after):
        if before.get(key) != after.get(key):
            changed.add(key)
    return changed


# ---------------------------------------------------------------------------
# RT-6 — the negative test: a project-owned agent survives /update-project
# ---------------------------------------------------------------------------


def test_rt6_update_preserves_project_owned_agent(scratch):
    rt.run_setup_project(
        scratch.project,
        framework_repo_root=scratch.framework_repo_root,
        home=scratch.home,
        cc_bin=scratch.cc_bin,
    )
    seeded_path = rt.seed_project_owned_agent(scratch.project, name="my-custom")
    before_content = seeded_path.read_text(encoding="utf-8")
    assert "owner: project" in before_content

    rt.run_update_project(
        scratch.project,
        framework_repo_root=scratch.framework_repo_root,
        home=scratch.home,
        cc_bin=scratch.cc_bin,
    )

    result = rt.check_preserves_project_owned(
        before=before_content, after_path=seeded_path, subject="rt6"
    )
    assert result.verdict is Verdict.PASS, (
        "the never-destroy invariant failed: a project-owned agent "
        f"(owner: project) did not survive /update-project unmodified "
        f"({[e.as_dict() for e in result.evidence]})"
    )
    assert result.expected_today is ExpectedToday.PASS


def test_does_not_touch_third_party_mcp_server(scratch):
    """`update-project.md`'s own "Unchanged: .mcp.json" promise, run for
    real. Not one of TEST-MATRIX.md's 6 named RT ids, but explicitly listed
    in HARNESS-DESIGN.md's Layer 5 table
    (`roundtrip.update.does_not_touch_mcp_json`)."""

    rt.run_setup_project(
        scratch.project,
        framework_repo_root=scratch.framework_repo_root,
        home=scratch.home,
        cc_bin=scratch.cc_bin,
    )
    rt.seed_third_party_mcp_server(scratch.project, name="third-party-example")
    before = json.loads((scratch.project / ".mcp.json").read_text(encoding="utf-8"))

    rt.run_update_project(
        scratch.project,
        framework_repo_root=scratch.framework_repo_root,
        home=scratch.home,
        cc_bin=scratch.cc_bin,
    )

    result = rt.check_does_not_touch_mcp_json(
        before=before, project=scratch.project, subject="rt-mcp"
    )
    assert result.verdict is Verdict.PASS
    assert result.expected_today is ExpectedToday.PASS


# ---------------------------------------------------------------------------
# The degraded-install fixture — proving detection, not just a clean pass
# ---------------------------------------------------------------------------


def test_degraded_install_is_detected(tmp_path, reference, degradation_shapes):
    """Task requirement 6: "Include the degraded-install fixture so the
    harness proves it detects a bad install, not just a good one."

    Per `HARNESS-DESIGN.md` section 5.2's own recipe for this kind of test
    ("Seed the reference install, then degrade it exactly as the fleet is
    degraded"), the starting point is a SYNTHETIC, fully reference-shaped
    tree (`_build_synthetic_reference_project`, the same builder
    `test_check_produces_reference_install_passes_on_a_synthetic_exact_match`
    proves is a true, all-PASS match) — not today's real installer output,
    which cannot itself reach the reference shape yet (RT-1). Degrading a
    tree that already has known gaps would make some shapes (e.g.
    'missing-hook', when the hook was never installed to begin with) a
    no-op, silently proving nothing. Each shape cites its real-fleet
    evidence; detection is asserted as a concrete per-facet FAIL, never a
    false PASS on a project that is provably not conformant."""

    assert degradation_shapes, "no degradation shapes loaded from the fixture"

    for shape in degradation_shapes:
        shape_project = tmp_path / f"degraded-{shape.name}"
        _build_synthetic_reference_project(shape_project, reference)

        actions = rt.apply_degradation(shape_project, shape)
        assert actions, f"degradation shape {shape.name!r} applied nothing"

        result = rt.check_degraded_install_detected(
            project=shape_project,
            reference=reference,
            shape=shape,
            subject_prefix="rt-degraded",
        )
        assert result.verdict is Verdict.PASS, (
            f"shape {shape.name!r} ({shape.citing_evidence}) went "
            f"undetected: {[e.as_dict() for e in result.evidence]}"
        )
        assert result.expected_today is ExpectedToday.PASS


def test_degraded_shapes_are_distinct_from_a_healthy_reference(scratch, reference):
    """A control case for the detector above: applying NO degradation must
    NOT trip `check_degraded_install_detected`'s own logic into reporting a
    fabricated FAIL against a project that only has the known,
    accepted-today gaps. RC-1/RC-4 fix, re-verified live 2026-08-10: agents,
    commands, hook, and lock are no longer gaps -- only codex (a structural
    gap /setup-project never touches) remains, already asserted by RT-1."""

    rt.run_setup_project(
        scratch.project,
        framework_repo_root=scratch.framework_repo_root,
        home=scratch.home,
        cc_bin=scratch.cc_bin,
    )
    facet_results = rt.check_produces_reference_install(
        project=scratch.project, reference=reference, subject_prefix="control"
    )
    failing_facets = {
        result.subject.split("::")[-1]
        for result in facet_results
        if result.verdict is Verdict.FAIL
    }
    # Exactly the known-today gaps from RT-1 -- no MORE than that on a
    # project nobody degraded.
    assert failing_facets == {"codex"}


def test_degraded_shapes_survive_an_undegraded_synthetic_reference(tmp_path, reference):
    """A second control case, tighter than the one above: build the FULL
    synthetic reference tree (zero known gaps -- see
    `test_check_produces_reference_install_passes_on_a_synthetic_exact_match`)
    and confirm it passes every facet BEFORE any degradation is applied,
    so `test_degraded_install_is_detected`'s FAILs are attributable to the
    degradation, not to a synthetic builder that was already incomplete."""

    project = tmp_path / "undegraded"
    _build_synthetic_reference_project(project, reference)
    results = rt.check_produces_reference_install(
        project=project, reference=reference, subject_prefix="undegraded"
    )
    failing = [result for result in results if result.verdict is Verdict.FAIL]
    assert not failing, [r.as_dict() for r in failing]


# ---------------------------------------------------------------------------
# Extraction mechanics — proving the harness reads the REAL command files,
# not a copy it made up.
# ---------------------------------------------------------------------------


def test_extract_bash_steps_reads_the_real_setup_project_md(framework_repo_root):
    markdown = (
        framework_repo_root / ".claude" / "commands" / "setup-project.md"
    ).read_text(encoding="utf-8")
    blocks = rt.extract_bash_steps(markdown, rt.SETUP_PROJECT_SECTIONS)
    assert blocks
    joined = "\n".join(blocks)
    # The exact literal lines the design's own findings cite.
    assert (
        "cp ~/.claude/copilot/.claude/commands/protocol.md .claude/commands/" in joined
    )
    assert (
        "cp ~/.claude/copilot/.claude/commands/continue.md .claude/commands/" in joined
    )
    # RC-1 fix, re-verified live 2026-08-10: setup-project.md now DOES
    # reference and install the enforcement hook -- the flip side of the
    # same finding that used to confirm its absence "by construction".
    assert (
        "cp ~/.claude/copilot/.claude/hooks/copilot-hook.sh "
        ".claude/hooks/copilot-hook.sh" in joined
    )
    assert "chmod +x .claude/hooks/copilot-hook.sh" in joined


def test_extract_bash_steps_raises_on_a_missing_marker(framework_repo_root):
    markdown = (
        framework_repo_root / ".claude" / "commands" / "setup-project.md"
    ).read_text(encoding="utf-8")
    with pytest.raises(rt.InstallerScriptError):
        rt.extract_bash_steps(
            markdown, [("## Step 999: Does Not Exist", "## Step 1000: Also Missing")]
        )


def test_discover_framework_repo_root_finds_a_real_checkout(framework_repo_root):
    assert (framework_repo_root / "VERSION.json").is_file()
    assert (framework_repo_root / ".claude" / "commands" / "setup-project.md").is_file()


def test_discover_cc_bin_resolves_a_working_executable(cc_bin):
    result = subprocess.run(
        [str(cc_bin), "--version"], capture_output=True, text=True, timeout=10.0
    )
    assert result.returncode == 0
    assert "cc version" in result.stdout


def test_materialize_framework_source_is_selective_not_a_full_clone(
    tmp_path, framework_repo_root
):
    dest = tmp_path / "copilot"
    rt.materialize_framework_source(dest, framework_repo_root)
    assert (dest / "VERSION.json").is_file()
    assert (dest / ".claude" / "hooks" / "copilot-hook.sh").is_file()
    assert (dest / ".claude" / "commands" / "protocol.md").is_file()
    # Selective, not a git clone: no .git/ directory should exist in the
    # materialized copy (HARNESS-DESIGN.md's write-risk rationale for never
    # cloning the whole 2GB+ working tree per test).
    assert not (dest / ".git").exists()


# ---------------------------------------------------------------------------
# Harness self-tests — the round-trip's own comparison logic (net-new per
# HARNESS-DESIGN.md section 2.4 point 6) must be provably correct on both a
# passing and a failing synthetic input, independent of any real bash run.
# ---------------------------------------------------------------------------


def test_observe_install_reads_a_synthetic_tree_directly(tmp_path):
    project = tmp_path / "synthetic"
    (project / ".claude" / "commands").mkdir(parents=True)
    (project / ".claude" / "commands" / "protocol.md").write_text("x", encoding="utf-8")
    (project / ".claude" / "agents").mkdir(parents=True)
    for name in ("cw", "kc"):
        (project / ".claude" / "agents" / f"{name}.md").write_text(
            "x", encoding="utf-8"
        )
    (project / ".mcp.json").write_text('{"mcpServers": {}}', encoding="utf-8")

    observed = rt.observe_install(project)
    assert observed["command_names"] == ("protocol",)
    assert observed["agent_names"] == ("cw", "kc")
    assert observed["mcp_json"] == {"mcpServers": {}}
    assert observed["hook_present"] is False
    assert observed["lock_present"] is False


def test_has_owner_project_frontmatter_matches_the_documented_grep():
    text = "---\nowner: project\nname: my-custom\n---\n\nbody\n"

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "agent.md"
        path.write_text(text, encoding="utf-8")
        assert rt.has_owner_project_frontmatter(path) is True

        other = Path(tmp) / "framework.md"
        other.write_text("---\nname: cw\n---\n", encoding="utf-8")
        assert rt.has_owner_project_frontmatter(other) is False


def test_apply_degradation_removes_and_writes_as_declared(tmp_path):
    project = tmp_path / "project"
    (project / ".claude" / "hooks").mkdir(parents=True)
    hook = project / ".claude" / "hooks" / "copilot-hook.sh"
    hook.write_text("#!/bin/sh\n", encoding="utf-8")

    shape = rt.DegradationShape(
        name="test-shape",
        description="unit test shape",
        citing_evidence="n/a",
        remove=(".claude/hooks/copilot-hook.sh",),
        write={"copilot.lock.json": "{}"},
    )
    actions = rt.apply_degradation(project, shape)
    assert not hook.exists()
    assert (project / "copilot.lock.json").read_text(encoding="utf-8") == "{}"
    assert len(actions) == 2


def test_check_produces_reference_install_passes_on_a_synthetic_exact_match(
    tmp_path, reference
):
    """The comparison logic itself, proven correct independent of any real
    bash execution: build a tree that matches the fixture manifest exactly
    and confirm every facet reports PASS."""

    project = tmp_path / "exact-match"
    _build_synthetic_reference_project(project, reference)

    results = rt.check_produces_reference_install(
        project=project, reference=reference, subject_prefix="synthetic"
    )
    failing = [result for result in results if result.verdict is Verdict.FAIL]
    assert not failing, [r.as_dict() for r in failing]
