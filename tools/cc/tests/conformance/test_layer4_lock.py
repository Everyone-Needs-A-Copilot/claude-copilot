"""WP-5 tests: Layer 4 -- lock integrity (`lock.py`, the five `LI-1`..`LI-5`
checks from `TEST-MATRIX.md` section 4).

Two worlds, per `HARNESS-DESIGN.md` section 5.1:

  World A (synthetic, the default) -- every check gets one POSITIVE test
  (a fixture where it PASSES) and one NEGATIVE test (a fixture where it
  FAILS), per the work package's own definition of done
  (`HARNESS-DESIGN.md` section 9.3: "a check never proven to fail is not a
  check"). Built with plain `tmp_path` directories -- Layer 4 is pure
  filesystem + JSON, it never touches the tier manifest `FleetFactory`
  exists for, so a bespoke fixture is the "fewest elements" choice here,
  not `FleetFactory`'s tier/product machinery.

  World B (`@pytest.mark.machine`) -- the SAME check functions run against
  this machine's real repos, strictly read-only (guarded by
  `machine_readonly_guard` on top of the suite's autouse tripwire),
  reproducing the exact evidence `TEST-MATRIX.md` section 4 and
  `EXISTING-VERIFICATION.md` section 2 record: the two LI-1 hash clusters,
  `claude-copilot`'s own stale LI-2 checksums, `sproutworks`'s LI-3
  ownership contradiction, `copilot-control-tower`'s LI-4 ready-by-waiver,
  and LI-5's universal missing-hook fact. `pytest -m "not machine"` skips
  this half entirely, so the suite stays hermetic on a machine with no
  ecosystem installed. Every World-B test also skips (not fails) if the
  specific real repo it names is absent -- these are inherently
  this-machine facts, not portable fixtures.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from cc.core.conformance import lock
from cc.core.conformance.types import ExpectedToday, Verdict
from cc.core.ecosystem.project_locking import fingerprint_file_payload

from .conftest import FleetFactory

pytestmark = pytest.mark.filterwarnings("ignore")

_REAL_COPILOT_ROOT = Path("/Volumes/Dev/Sites/COPILOT")
_REAL_PERSONAL_ROOT = Path("/Volumes/Dev/Sites/PERSONAL")
_REAL_TSM_ROOT = Path("/Volumes/Dev/Sites/TSM")


def _require_real_repo(path: Path) -> Path:
    """World-B tests name a specific real repo on THIS machine
    (`HARNESS-DESIGN.md` section 5.1's own framing: these are facts about
    "this machine", not a portable fixture). Skip -- never fail or error --
    when the fleet this test documents is not present, so the suite stays
    green on a checkout without this exact `/Volumes/Dev/Sites` tree."""

    if not path.is_dir():
        pytest.skip(f"real repo not present on this machine: {path}")
    return path


# ---------------------------------------------------------------------------
# World-A fixture helpers
# ---------------------------------------------------------------------------


def _sha256_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_marker_files(root: Path, *, heading: bool = True) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "CLAUDE.md").write_text(
        "## Claude Copilot\n\nProject entry.\n" if heading else "no heading\n",
        encoding="utf-8",
    )
    (root / ".mcp.json").write_text(
        json.dumps({"mcpServers": {}}), encoding="utf-8"
    )


def _managed_output(root: Path, relative: str) -> dict[str, str]:
    target = root / relative
    mode = target.stat().st_mode & 0o777
    fingerprint = fingerprint_file_payload(target.read_bytes(), mode=mode)
    return {"path": relative, "kind": "managed-text", "fingerprint": fingerprint}


def _write_full_codex_install(root: Path) -> dict[str, Any]:
    """Codex counterpart of `_write_full_claude_install`: a real,
    checksummable install of the two `_CODEX_REQUIRED_LOCK_PATHS`, so a
    codex component entry is structurally valid (files[] verifies clean)
    and any FAIL reached is isolated to what the test itself overrides
    (typically `managed_outputs`) -- mirrors the claude helper's own
    "prove the isolation" property."""

    root.mkdir(parents=True, exist_ok=True)
    (root / "plugins" / "codex-copilot" / ".codex-plugin").mkdir(
        parents=True, exist_ok=True
    )
    (root / "plugins" / "codex-copilot" / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "codex-copilot"}), encoding="utf-8"
    )
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "copilot-gate.sh").write_text(
        "#!/bin/sh\necho gate\n", encoding="utf-8"
    )
    (root / "AGENTS.md").write_text("## Codex Copilot\n\nProject entry.\n", encoding="utf-8")

    relative_paths = [
        "plugins/codex-copilot/.codex-plugin/plugin.json",
        "scripts/copilot-gate.sh",
    ]
    files = [
        {"path": rel, "ownership": "framework", "checksum": _sha256_of(root / rel)}
        for rel in relative_paths
    ]
    return {
        "component": "codex",
        "version": "1.0.0",
        "files": files,
        "managed_outputs": [_managed_output(root, "AGENTS.md")],
    }


def _write_full_claude_install(root: Path, *, include_hook: bool = True) -> dict[str, Any]:
    """Write a real, checksummable claude install (the four required paths
    plus one agent, `HARNESS-DESIGN.md`'s own required-path list) and
    return its lock component entry with `ownership_mode` implicitly
    `"full"` (the key is simply absent, matching the real fleet: absent in
    12 of 13 measured locks -- `lock.py`'s own `_ownership_mode` default
    must therefore be exercised, not sidestepped, by every LI-5 test)."""

    _write_marker_files(root)
    (root / ".claude" / "commands").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "commands" / "protocol.md").write_text("protocol\n", encoding="utf-8")
    (root / ".claude" / "commands" / "continue.md").write_text("continue\n", encoding="utf-8")
    (root / ".claude" / "fitness-check.sh").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    (root / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "agents" / "cw.md").write_text(
        "---\nname: cw\n---\n\nContent.\n", encoding="utf-8"
    )
    relative_paths = [
        ".claude/commands/protocol.md",
        ".claude/commands/continue.md",
        ".claude/fitness-check.sh",
        ".claude/agents/cw.md",
    ]
    if include_hook:
        (root / ".claude" / "hooks").mkdir(parents=True, exist_ok=True)
        (root / ".claude" / "hooks" / "copilot-hook.sh").write_text(
            "#!/bin/sh\necho hook\n", encoding="utf-8"
        )
        relative_paths.append(".claude/hooks/copilot-hook.sh")

    files = [
        {"path": rel, "ownership": "framework", "checksum": _sha256_of(root / rel)}
        for rel in relative_paths
    ]
    return {
        "component": "claude",
        "version": "1.0.0",
        "files": files,
        "managed_outputs": [_managed_output(root, "CLAUDE.md")],
    }


def _write_lock(root: Path, components: list[dict[str, Any]]) -> None:
    (root / "copilot.lock.json").write_text(
        json.dumps({"schema_version": "1.0", "components": components}, indent=2),
        encoding="utf-8",
    )


def _one(results: tuple[Any, ...], subject: str) -> Any:
    matching = [r for r in results if r.subject == subject]
    assert len(matching) == 1, f"expected exactly one result for {subject!r}, got {matching}"
    return matching[0]


# ---------------------------------------------------------------------------
# LI-1 -- lock.template.uniqueness
# ---------------------------------------------------------------------------


class TestUniqueness:
    def test_registered_with_the_stable_id(self):
        from cc.core.conformance.registry import DEFAULT_REGISTRY

        assert "lock.template.uniqueness" in DEFAULT_REGISTRY

    def test_two_repos_with_distinct_locks_both_pass(self, tmp_path):
        repo_a = tmp_path / "repo-a"
        repo_b = tmp_path / "repo-b"
        repo_a.mkdir()
        repo_b.mkdir()
        _write_lock(repo_a, [{"component": "claude", "version": "1.0.0", "files": []}])
        _write_lock(repo_b, [{"component": "claude", "version": "2.0.0", "files": []}])

        results = lock.check_lock_template_uniqueness([repo_a, repo_b])

        assert _one(results, str(repo_a)).verdict is Verdict.PASS
        assert _one(results, str(repo_b)).verdict is Verdict.PASS

    def test_two_repos_with_byte_identical_locks_both_fail(self, tmp_path):
        repo_a = tmp_path / "repo-a"
        repo_b = tmp_path / "repo-b"
        repo_a.mkdir()
        repo_b.mkdir()
        template = [{"component": "claude", "version": "1.0.0", "files": []}]
        _write_lock(repo_a, template)
        _write_lock(repo_b, template)

        results = lock.check_lock_template_uniqueness([repo_a, repo_b])

        result_a = _one(results, str(repo_a))
        result_b = _one(results, str(repo_b))
        assert result_a.verdict is Verdict.FAIL
        assert result_b.verdict is Verdict.FAIL
        assert result_a.root_cause == "rc.rc4"
        assert str(repo_b) in result_a.evidence[0].detail
        assert str(repo_a) in result_b.evidence[0].detail
        assert result_a.expected_today is ExpectedToday.FAIL

    def test_a_third_sibling_is_named_in_every_collision_evidence(self, tmp_path):
        repos = [tmp_path / name for name in ("one", "two", "three")]
        for repo in repos:
            repo.mkdir()
            _write_lock(repo, [{"component": "claude", "version": "x", "files": []}])

        results = lock.check_lock_template_uniqueness(repos)
        for repo in repos:
            result = _one(results, str(repo))
            assert result.verdict is Verdict.FAIL
            assert result.evidence[0].actual.startswith("sha256:")
            assert "shared by 3 repos" in result.evidence[0].actual

    def test_repo_with_no_lock_file_is_skipped_not_omitted(self, tmp_path):
        repo = tmp_path / "no-lock"
        repo.mkdir()

        results = lock.check_lock_template_uniqueness([repo])

        result = _one(results, str(repo))
        assert result.verdict is Verdict.SKIP
        assert result.expected_today is ExpectedToday.PASS

    def test_explicit_expected_today_override_is_honored(self, tmp_path):
        repo = tmp_path / "solo"
        repo.mkdir()
        _write_lock(repo, [{"component": "claude", "version": "1.0.0", "files": []}])

        results = lock.check_lock_template_uniqueness(
            [repo], expected_today={str(repo): ExpectedToday.FAIL}
        )
        assert _one(results, str(repo)).expected_today is ExpectedToday.FAIL


# ---------------------------------------------------------------------------
# LI-2 -- lock.records_match_disk (checksum truth)
# ---------------------------------------------------------------------------


class TestChecksumTruth:
    def test_matching_checksums_pass(self, tmp_path):
        repo = tmp_path / "repo"
        entry = _write_full_claude_install(repo)
        _write_lock(repo, [entry])

        results = lock.check_lock_records_match_disk([repo])
        assert _one(results, str(repo)).verdict is Verdict.PASS

    def test_a_stale_checksum_fails_with_the_file_named_in_evidence(self, tmp_path):
        repo = tmp_path / "repo"
        entry = _write_full_claude_install(repo)
        # Mutate the file on disk AFTER the lock recorded its checksum --
        # exactly the drift claude-copilot's own lock exhibits today.
        (repo / ".claude" / "commands" / "protocol.md").write_text(
            "protocol -- edited after the lock was written\n", encoding="utf-8"
        )
        _write_lock(repo, [entry])

        results = lock.check_lock_records_match_disk([repo])
        result = _one(results, str(repo))
        assert result.verdict is Verdict.FAIL
        assert result.expected_today is ExpectedToday.FAIL
        assert any(
            e.path == ".claude/commands/protocol.md" and e.kind == "framework-file"
            for e in result.evidence
        )

    def test_a_malformed_file_record_reports_could_not_run_not_a_fabricated_pass(
        self, tmp_path
    ):
        repo = tmp_path / "repo"
        repo.mkdir()
        _write_marker_files(repo)
        entry = {
            "component": "claude",
            "version": "1.0.0",
            # No "checksum" key -- structurally invalid, per
            # `_verify_lock_entry`'s own "valid-framework-record" check.
            "files": [{"path": ".claude/commands/protocol.md", "ownership": "framework"}],
        }
        _write_lock(repo, [entry])

        results = lock.check_lock_records_match_disk([repo])
        result = _one(results, str(repo))
        assert result.verdict is Verdict.COULD_NOT_RUN
        assert result.evidence == ()

    def test_repo_with_no_lock_entry_is_skipped(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        results = lock.check_lock_records_match_disk([repo])
        assert _one(results, str(repo)).verdict is Verdict.SKIP

    def test_a_managed_output_missing_fingerprint_fails_not_could_not_run(
        self, tmp_path
    ):
        """Reproduces the exact shape `codex-copilot/scripts/update-project.
        sh` writes today: a `managed_outputs[]` record with only `path` and
        `kind`, no `fingerprint`. `_verify_lock_entry`'s schema requires
        `{"path", "kind", "fingerprint"}` exactly (mirrored by
        `project_reconciliation.py`), so this record is genuinely invalid --
        a real writer defect, not a shape this harness fails to understand.
        Before the fix this silently downgraded to COULD_NOT_RUN, hiding a
        real defect (and masking any framework-file evidence already
        found); it must FAIL with concrete evidence instead."""

        repo = tmp_path / "repo"
        entry = _write_full_claude_install(repo)
        entry["managed_outputs"] = [
            {"path": "CLAUDE.md", "kind": "managed-text"}  # no fingerprint
        ]
        _write_lock(repo, [entry])

        results = lock.check_lock_records_match_disk([repo])
        result = _one(results, str(repo))
        assert result.verdict is Verdict.FAIL
        assert any(
            e.kind == "invalid-managed-output" and "claude" in e.detail
            for e in result.evidence
        )

    def test_codex_managed_output_missing_fingerprint_fails_not_could_not_run(
        self, tmp_path
    ):
        """Codex counterpart of `test_a_managed_output_missing_fingerprint_
        fails_not_could_not_run` immediately above -- same writer-defect
        shape (`{"path", "kind"}`, no `fingerprint`), same required FAIL,
        just for a `codex` component instead of `claude`.

        This fixture is what now keeps LI-2's ability to detect this exact
        stale/malformed-managed-output shape proven, after `TestMachine
        TruthChecksumAndOwnership.test_li2_reproduces_claude_copilot_own_
        stale_checksums` stopped being able to reproduce it live:
        sproutworks's own codex managed_outputs briefly had this shape and
        now carry real `sha256:` fingerprints (the writer defect was fixed
        upstream), so that machine test now correctly asserts PASS for
        sproutworks. A live repo getting fixed must never silently drop
        the harness's proof that it can still catch the bug -- hence a
        fixture, independent of any one repo's current state."""

        repo = tmp_path / "repo"
        entry = _write_full_codex_install(repo)
        entry["managed_outputs"] = [
            {"path": "AGENTS.md", "kind": "managed-text"}  # no fingerprint
        ]
        _write_lock(repo, [entry])

        results = lock.check_lock_records_match_disk([repo])
        result = _one(results, str(repo))
        assert result.verdict is Verdict.FAIL
        assert any(
            e.kind == "invalid-managed-output" and "codex" in e.detail
            for e in result.evidence
        )

    def test_a_managed_output_missing_fingerprint_does_not_hide_a_real_file_mismatch(
        self, tmp_path
    ):
        """A genuinely invalid managed-output record must not swallow
        evidence for an already-detected framework-file checksum mismatch
        on the SAME component -- both are real defects and both must
        surface."""

        repo = tmp_path / "repo"
        entry = _write_full_claude_install(repo)
        (repo / ".claude" / "commands" / "protocol.md").write_text(
            "protocol -- edited after the lock was written\n", encoding="utf-8"
        )
        entry["managed_outputs"] = [{"path": "CLAUDE.md", "kind": "managed-text"}]
        _write_lock(repo, [entry])

        results = lock.check_lock_records_match_disk([repo])
        result = _one(results, str(repo))
        assert result.verdict is Verdict.FAIL
        assert any(e.kind == "invalid-managed-output" for e in result.evidence)
        assert any(
            e.kind == "framework-file" and e.path == ".claude/commands/protocol.md"
            for e in result.evidence
        )


# ---------------------------------------------------------------------------
# LI-3 -- lock.ownership.frontmatter_agrees
# ---------------------------------------------------------------------------


class TestOwnershipAgrees:
    def test_agent_with_no_owner_frontmatter_passes(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _write_marker_files(repo)
        (repo / ".claude" / "agents").mkdir(parents=True)
        agent_path = repo / ".claude" / "agents" / "cw.md"
        agent_path.write_text("---\nname: cw\n---\n\nBody.\n", encoding="utf-8")
        _write_lock(
            repo,
            [
                {
                    "component": "claude",
                    "version": "1.0.0",
                    "files": [
                        {
                            "path": ".claude/agents/cw.md",
                            "ownership": "framework",
                            "checksum": _sha256_of(agent_path),
                        }
                    ],
                }
            ],
        )

        results = lock.check_lock_ownership_frontmatter_agrees([repo])
        assert _one(results, str(repo)).verdict is Verdict.PASS

    def test_project_owned_frontmatter_locked_as_framework_fails(self, tmp_path):
        """Reproduces the `sproutworks` contradiction: the agent's own
        frontmatter says `owner: project`; the lock still says `ownership:
        "framework"`."""

        repo = tmp_path / "repo"
        repo.mkdir()
        _write_marker_files(repo)
        (repo / ".claude" / "agents").mkdir(parents=True)
        agent_path = repo / ".claude" / "agents" / "elec.md"
        agent_path.write_text(
            "---\nname: elec\nowner: project\niteration:\n  enabled: true\n---\n\nBody.\n",
            encoding="utf-8",
        )
        _write_lock(
            repo,
            [
                {
                    "component": "claude",
                    "version": "1.0.0",
                    "files": [
                        {
                            "path": ".claude/agents/elec.md",
                            "ownership": "framework",
                            "checksum": _sha256_of(agent_path),
                        }
                    ],
                }
            ],
        )

        results = lock.check_lock_ownership_frontmatter_agrees([repo])
        result = _one(results, str(repo))
        assert result.verdict is Verdict.FAIL
        assert result.expected_today is ExpectedToday.FAIL
        assert result.evidence[0].path == ".claude/agents/elec.md"
        assert result.evidence[0].kind == "ownership-contradiction"

    def test_repo_with_no_lock_entry_is_skipped(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        results = lock.check_lock_ownership_frontmatter_agrees([repo])
        assert _one(results, str(repo)).verdict is Verdict.SKIP


# ---------------------------------------------------------------------------
# LI-4 -- lock.waiver.ready_requires_required_paths
# ---------------------------------------------------------------------------


class TestReadyByWaiver:
    def test_full_mode_ready_is_never_flagged_as_waived(self, tmp_path):
        repo = tmp_path / "repo"
        entry = _write_full_claude_install(repo)  # ownership_mode absent -> "full"
        _write_lock(repo, [entry])

        results = lock.check_lock_waiver_ready_requires_required_paths([repo])
        assert _one(results, str(repo)).verdict is Verdict.PASS

    def test_customized_preserve_that_records_every_required_path_passes(self, tmp_path):
        repo = tmp_path / "repo"
        _write_marker_files(repo)
        (repo / ".claude" / "commands").mkdir(parents=True)
        (repo / ".claude" / "commands" / "protocol.md").write_text("x\n", encoding="utf-8")
        (repo / ".claude" / "commands" / "continue.md").write_text("x\n", encoding="utf-8")
        (repo / ".claude" / "fitness-check.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (repo / ".claude" / "hooks").mkdir(parents=True)
        (repo / ".claude" / "hooks" / "copilot-hook.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        # customized-preserve's own bounded subset (`_customized_framework_
        # path_allowed`) only ever admits the four required claude paths --
        # never an agent file -- so this fixture deliberately stays within
        # that subset rather than reusing `_write_full_claude_install`.
        relative = [
            ".claude/commands/protocol.md",
            ".claude/commands/continue.md",
            ".claude/fitness-check.sh",
            ".claude/hooks/copilot-hook.sh",
        ]
        entry = {
            "component": "claude",
            "version": "1.0.0",
            "ownership_mode": "customized-preserve",
            "files": [
                {"path": p, "ownership": "framework", "checksum": _sha256_of(repo / p)}
                for p in relative
            ],
            "managed_outputs": [_managed_output(repo, "CLAUDE.md")],
        }
        _write_lock(repo, [entry])

        results = lock.check_lock_waiver_ready_requires_required_paths([repo])
        result = _one(results, str(repo))
        # customized-preserve, but nothing was actually waived -- every
        # required path is independently present, so this is an honest
        # ready, not a ready obtained BY waiver.
        assert result.verdict is Verdict.PASS

    def test_synthetic_minimum_reproduces_existing_verification_proof_2(self, tmp_path):
        """RC-4 waiver hole (closed, project_integration.py's
        `_verify_lock_entry`): `EXISTING-VERIFICATION.md` section 2's
        "Proof 2 -- synthetic minimum" fixture, reproduced exactly --
        `CLAUDE.md` + `.mcp.json` + a lock whose one claude entry is
        `ownership_mode: customized-preserve`, `files: []`, and a correct
        `managed_outputs` fingerprint for `CLAUDE.md`. The live result this
        used to reproduce was `claude -> ready` with zero agents, skills,
        or commands on disk. Re-verified live 2026-08-10: this exact
        fixture no longer reaches `ready` at all -- `customized-preserve`
        now waives a required path's CHECKSUM only, never its EXISTENCE,
        so a path that is genuinely absent from disk (not merely
        unrecorded) correctly keeps classification at `guided-integration`.
        The waiver check therefore has nothing to apply to (SKIP), not a
        FAIL to catch -- see
        `test_ready_by_waiver_still_catches_files_present_but_unrecorded`
        below for the fixture shape that still proves this check can fail."""

        repo = tmp_path / "synthetic-minimum"
        repo.mkdir()
        _write_marker_files(repo)
        entry = {
            "component": "claude",
            "version": "1.0.0",
            "ownership_mode": "customized-preserve",
            "files": [],
            "managed_outputs": [_managed_output(repo, "CLAUDE.md")],
        }
        _write_lock(repo, [entry])

        # Confirm the fixture's classification directly -- otherwise a
        # harness bug could make this test pass for the wrong reason.
        from cc.core.ecosystem.project_integration import inspect_project_integration

        report = inspect_project_integration(repo, detail=False)
        classifications = {c["component"]: c["classification"] for c in report["components"]}
        assert classifications["claude"] == "guided-integration"
        assert report["capabilities"]["agents"] == 0
        assert report["capabilities"]["commands"] == 0

        results = lock.check_lock_waiver_ready_requires_required_paths([repo])
        result = _one(results, str(repo))
        assert result.verdict is Verdict.SKIP
        assert result.expected_today is ExpectedToday.PASS
        assert "not triggered" in result.detail

    def test_ready_by_waiver_still_catches_files_present_but_unrecorded(self, tmp_path):
        """A check that can no longer fail is worthless (HARNESS-DESIGN.md
        section 9.3): now that the classification fix closed the
        "genuinely absent" hole, construct the ONE shape still capable of
        triggering this check -- every required path physically PRESENT on
        disk (so classification honestly reaches `ready`), but the lock's
        own `files[]` under `customized-preserve` records only some of
        them. `lock.py`'s own definition of "by waiver" is RECORDED-based,
        deliberately independent of `project_integration.py`'s on-disk
        existence check, and it must still fire."""

        repo = tmp_path / "present-but-unrecorded"
        repo.mkdir()
        _write_marker_files(repo)
        (repo / ".claude" / "commands").mkdir(parents=True)
        (repo / ".claude" / "commands" / "continue.md").write_text("x\n", encoding="utf-8")
        (repo / ".claude" / "commands" / "protocol.md").write_text("y\n", encoding="utf-8")
        (repo / ".claude" / "fitness-check.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (repo / ".claude" / "hooks").mkdir(parents=True)
        (repo / ".claude" / "hooks" / "copilot-hook.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        entry = {
            "component": "claude",
            "version": "1.0.0",
            "ownership_mode": "customized-preserve",
            "files": [
                {
                    "path": ".claude/commands/continue.md",
                    "ownership": "framework",
                    "checksum": _sha256_of(repo / ".claude/commands/continue.md"),
                },
                {
                    "path": ".claude/fitness-check.sh",
                    "ownership": "framework",
                    "checksum": _sha256_of(repo / ".claude/fitness-check.sh"),
                },
            ],
            "managed_outputs": [_managed_output(repo, "CLAUDE.md")],
        }
        _write_lock(repo, [entry])

        from cc.core.ecosystem.project_integration import inspect_project_integration

        report = inspect_project_integration(repo, detail=False)
        classifications = {c["component"]: c["classification"] for c in report["components"]}
        assert classifications["claude"] == "ready"  # honestly ready -- every path IS on disk

        results = lock.check_lock_waiver_ready_requires_required_paths([repo])
        result = _one(results, str(repo))
        assert result.verdict is Verdict.FAIL
        assert result.expected_today is ExpectedToday.FAIL
        assert result.evidence[0].kind == "ready-by-waiver"
        assert ".claude/commands/protocol.md" in result.evidence[0].detail
        assert ".claude/hooks/copilot-hook.sh" in result.evidence[0].detail

    def test_copilot_control_tower_shaped_fixture_fails(self, tmp_path):
        """RC-4 waiver hole (closed): reproduces the second live proof this
        fixture used to catch -- `customized-preserve` with 2 of 4 required
        paths recorded, and NOTHING on disk for the other 2 -- which used
        to still classify `ready`. Re-verified live 2026-08-10: it no
        longer does. With the missing paths genuinely absent from disk (not
        merely unrecorded), classification now correctly reports
        `guided-integration`, so the waiver check is not applicable (SKIP).
        Despite the name, this is now a passing regression control, not a
        FAIL case -- kept unrenamed so its git history stays attached to
        the live proof it documents."""

        repo = tmp_path / "control-tower-shaped"
        repo.mkdir()
        _write_marker_files(repo)
        (repo / ".claude" / "commands").mkdir(parents=True)
        (repo / ".claude" / "commands" / "continue.md").write_text("x\n", encoding="utf-8")
        (repo / ".claude" / "fitness-check.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        entry = {
            "component": "claude",
            "version": "1.0.0",
            "ownership_mode": "customized-preserve",
            "files": [
                {
                    "path": ".claude/commands/continue.md",
                    "ownership": "framework",
                    "checksum": _sha256_of(repo / ".claude/commands/continue.md"),
                },
                {
                    "path": ".claude/fitness-check.sh",
                    "ownership": "framework",
                    "checksum": _sha256_of(repo / ".claude/fitness-check.sh"),
                },
            ],
            "managed_outputs": [_managed_output(repo, "CLAUDE.md")],
        }
        _write_lock(repo, [entry])

        results = lock.check_lock_waiver_ready_requires_required_paths([repo])
        result = _one(results, str(repo))
        assert result.verdict is Verdict.SKIP
        assert result.expected_today is ExpectedToday.PASS

    def test_a_component_that_never_reaches_ready_is_skipped(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _write_marker_files(repo, heading=False)  # breaks the claude entry marker
        entry = {
            "component": "claude",
            "version": "1.0.0",
            "ownership_mode": "customized-preserve",
            "files": [],
            "managed_outputs": [],
        }
        _write_lock(repo, [entry])

        results = lock.check_lock_waiver_ready_requires_required_paths([repo])
        result = _one(results, str(repo))
        assert result.verdict is Verdict.SKIP

    def test_repo_with_no_lock_entry_is_skipped(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        results = lock.check_lock_waiver_ready_requires_required_paths([repo])
        assert _one(results, str(repo)).verdict is Verdict.SKIP


# ---------------------------------------------------------------------------
# LI-5 -- lock.required_paths.full_mode_complete
# ---------------------------------------------------------------------------


class TestFullModeRequiredPaths:
    def test_full_mode_with_every_required_path_passes(self, tmp_path):
        repo = tmp_path / "repo"
        entry = _write_full_claude_install(repo, include_hook=True)
        _write_lock(repo, [entry])

        results = lock.check_lock_full_mode_records_required_paths([repo])
        assert _one(results, str(repo)).verdict is Verdict.PASS

    def test_full_mode_missing_the_hook_fails_and_tags_rc1(self, tmp_path):
        """Reproduces RC-1's consequence restated at the lock-schema level:
        the hook file itself may or may not exist on disk -- either way, a
        `full`-mode entry that never records it must FAIL."""

        repo = tmp_path / "repo"
        entry = _write_full_claude_install(repo, include_hook=False)
        _write_lock(repo, [entry])

        results = lock.check_lock_full_mode_records_required_paths([repo])
        result = _one(results, str(repo))
        assert result.verdict is Verdict.FAIL
        assert result.expected_today is ExpectedToday.FAIL
        assert result.root_cause == "rc.rc1"
        assert any(e.path == ".claude/hooks/copilot-hook.sh" for e in result.evidence)

    def test_missing_a_non_hook_required_path_fails_without_rc1_tag(self, tmp_path):
        """`root_cause` attribution must be precise, not a blanket label --
        a component missing `protocol.md` (unrelated to RC-1's hook defect)
        must not be lumped under `rc.rc1`."""

        repo = tmp_path / "repo"
        repo.mkdir()
        _write_marker_files(repo)
        (repo / ".claude" / "commands").mkdir(parents=True)
        (repo / ".claude" / "commands" / "continue.md").write_text("x\n", encoding="utf-8")
        (repo / ".claude" / "fitness-check.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (repo / ".claude" / "hooks").mkdir(parents=True)
        (repo / ".claude" / "hooks" / "copilot-hook.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (repo / ".claude" / "agents").mkdir(parents=True)
        (repo / ".claude" / "agents" / "cw.md").write_text("---\nname: cw\n---\n", encoding="utf-8")
        relative = [
            ".claude/commands/continue.md",
            ".claude/fitness-check.sh",
            ".claude/hooks/copilot-hook.sh",
            ".claude/agents/cw.md",
        ]
        entry = {
            "component": "claude",
            "version": "1.0.0",
            "files": [
                {"path": p, "ownership": "framework", "checksum": _sha256_of(repo / p)}
                for p in relative
            ],
        }
        _write_lock(repo, [entry])

        results = lock.check_lock_full_mode_records_required_paths([repo])
        result = _one(results, str(repo))
        assert result.verdict is Verdict.FAIL
        assert result.root_cause is None
        assert any(e.path == ".claude/commands/protocol.md" for e in result.evidence)

    def test_customized_preserve_only_is_out_of_scope_and_skips(self, tmp_path):
        repo = tmp_path / "repo"
        entry = _write_full_claude_install(repo, include_hook=False)
        entry["ownership_mode"] = "customized-preserve"
        _write_lock(repo, [entry])

        results = lock.check_lock_full_mode_records_required_paths([repo])
        result = _one(results, str(repo))
        assert result.verdict is Verdict.SKIP

    def test_repo_with_no_lock_entry_is_skipped(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        results = lock.check_lock_full_mode_records_required_paths([repo])
        assert _one(results, str(repo)).verdict is Verdict.SKIP

    def test_out_of_scope_subject_skips_before_reading_the_lock_at_all(self, tmp_path):
        """The class-E-is-out-of-scope gate every `repo.d0*` dimension
        already applies via `applies_to_classes` (RUBRIC.md: "A, B, C, D",
        not E) -- confirmed live against a git *worktree* of another repo
        (`convoco-policy-build`, "not an independent project") and a repo
        the owner ratified for archival (`rfp-copilot`). A subject present
        in `out_of_scope` short-circuits to SKIP even though its lock
        would otherwise genuinely FAIL (missing the hook path, exactly
        like `test_full_mode_missing_the_hook_fails_and_tags_rc1` above)."""

        repo = tmp_path / "repo"
        entry = _write_full_claude_install(repo, include_hook=False)
        _write_lock(repo, [entry])

        results = lock.check_lock_full_mode_records_required_paths(
            [repo], out_of_scope={str(repo): "SCRATCH-ARCHIVE (rubric E): archived"}
        )
        result = _one(results, str(repo))
        assert result.verdict is Verdict.SKIP
        assert "SCRATCH-ARCHIVE" in result.detail

    def test_subject_not_in_out_of_scope_is_graded_normally(self, tmp_path):
        repo = tmp_path / "repo"
        entry = _write_full_claude_install(repo, include_hook=False)
        _write_lock(repo, [entry])

        results = lock.check_lock_full_mode_records_required_paths(
            [repo], out_of_scope={"/some/other/repo": "irrelevant"}
        )
        assert _one(results, str(repo)).verdict is Verdict.FAIL


# ---------------------------------------------------------------------------
# run_lock_checks -- the one-call convenience seam
# ---------------------------------------------------------------------------


class TestRunLockChecks:
    def test_runs_all_five_checks_against_one_repo(self, tmp_path):
        repo = tmp_path / "repo"
        entry = _write_full_claude_install(repo)
        _write_lock(repo, [entry])

        results = lock.run_lock_checks([repo])
        ids = {r.id for r in results}
        assert ids == {
            "lock.template.uniqueness",
            "lock.records_match_disk",
            "lock.ownership.frontmatter_agrees",
            "lock.waiver.ready_requires_required_paths",
            "lock.required_paths.full_mode_complete",
        }
        assert all(r.subject == str(repo) for r in results)

    def test_out_of_scope_is_forwarded_only_to_li5(self, tmp_path):
        """`out_of_scope` must SKIP LI-5 for this repo while LI-1..LI-4
        keep grading it exactly as if the parameter had never been
        passed (`run_lock_checks`'s own docstring)."""

        repo = tmp_path / "repo"
        entry = _write_full_claude_install(repo, include_hook=False)
        _write_lock(repo, [entry])

        results = lock.run_lock_checks(
            [repo], out_of_scope={str(repo): "SCRATCH-ARCHIVE (rubric E): archived"}
        )
        by_id = {r.id: r for r in results}
        assert by_id["lock.required_paths.full_mode_complete"].verdict is Verdict.SKIP
        assert by_id["lock.template.uniqueness"].verdict is Verdict.PASS

    def test_fleet_factory_project_is_a_legal_input(self, tmp_path):
        """`lock.py`'s functions accept any `Path`, including a project
        built by the suite's own `FleetFactory` -- proving Layer 4 composes
        with the shared World-A fixture builder even though it does not
        need the tier/manifest half of it."""

        fleet = FleetFactory(tmp_path)
        project = fleet.project("scratch")
        project.write("CLAUDE.md", "## Claude Copilot\n")
        project.write(".mcp.json", json.dumps({"mcpServers": {}}))
        handle = fleet.build()
        repo = handle.projects["scratch"]
        _write_lock(repo, [{"component": "claude", "version": "1.0.0", "files": []}])

        results = lock.run_lock_checks([repo])
        assert results  # did not raise, produced at least one result per check


# ---------------------------------------------------------------------------
# World B -- machine truth (strictly read-only, marked `machine`)
# ---------------------------------------------------------------------------


@pytest.mark.machine
class TestMachineTruthUniqueness:
    def test_li1_no_real_lock_cluster_remains(self, machine_readonly_guard):
        """Was `test_li1_reproduces_the_remaining_real_hash_cluster`.
        Re-verified live 2026-08-11: `claude-copilot` and `knowledge-
        copilot` -- the last two-repo byte-identical cluster (neither
        foundation regenerates its OWN lock on install) -- each had their
        `claude` component lock entry regenerated directly
        (`cc.core.ecosystem.projects.generate_component_lock_entry`, the
        same per-project generator every other repo's installer already
        uses), closing the gap `root_causes.py`'s RC-4 generator-half
        comment used to document. Both are verified cleanly COMMITTED
        (`git status --short copilot.lock.json`, empty for both). No
        cluster of any size remains among these twelve real repos."""

        now_unique = [
            _require_real_repo(_REAL_COPILOT_ROOT / name)
            for name in (
                "claude-copilot-accounting",
                "claude-copilot-internal",
                "cli-copilot-accounting",
                "cli-copilot-private",
                "codex-copilot-accounting",
                "codex-copilot-internal",
                "codex-copilot-private",
                "knowledge-copilot-accounting",
                "knowledge-copilot-private",
                "claude-copilot-private",
                "claude-copilot",
                "knowledge-copilot",
            )
        ]
        control = _require_real_repo(_REAL_COPILOT_ROOT / "copilot-control-tower")

        extra_paths = [repo / "copilot.lock.json" for repo in (*now_unique, control)]
        with machine_readonly_guard(extra_paths=extra_paths):
            results = lock.check_lock_template_uniqueness([*now_unique, control])

        for repo in now_unique:
            assert _one(results, str(repo)).verdict is Verdict.PASS, repo

        assert _one(results, str(control)).verdict is Verdict.PASS


@pytest.mark.machine
class TestMachineTruthChecksumAndOwnership:
    def test_li2_claude_copilot_own_stale_checksums_are_fixed(self, machine_readonly_guard):
        """Was `test_li2_reproduces_claude_copilot_own_stale_checksums`.
        `claude-copilot`'s own claude component used to carry stale
        framework-file checksums (18 of 19) because its installer never
        regenerated its own lock. Re-verified live 2026-08-11: its `claude`
        component lock entry was regenerated directly
        (`cc.core.ecosystem.projects.generate_component_lock_entry`, the
        same per-project generator every other repo's installer already
        uses), which recomputes every recorded checksum fresh from disk --
        this check now correctly PASSES it.

        `sproutworks`'s half was already fixed in an earlier pass (its
        codex managed_outputs now carry real `sha256:` fingerprints, see
        the prior revision of this docstring); both repos now PASS.
        `test_codex_managed_output_missing_fingerprint_fails_not_could_
        not_run` below keeps a fixture (not a live repo) proving this
        check still detects a stale/malformed checksum, so this update
        narrows the live claim without weakening what is actually
        verified."""

        claude_copilot = _require_real_repo(_REAL_COPILOT_ROOT / "claude-copilot")
        sproutworks = _require_real_repo(_REAL_PERSONAL_ROOT / "sproutworks")

        with machine_readonly_guard(
            extra_paths=[
                claude_copilot / "copilot.lock.json",
                sproutworks / "copilot.lock.json",
            ]
        ):
            results = lock.check_lock_records_match_disk([claude_copilot, sproutworks])

        claude_result = _one(results, str(claude_copilot))
        assert claude_result.verdict is Verdict.PASS
        assert claude_result.evidence == ()

        sprout_result = _one(results, str(sproutworks))
        assert sprout_result.verdict is Verdict.PASS
        assert sprout_result.evidence == ()

    def test_li3_sproutworks_ownership_contradiction_is_corrected(
        self, machine_readonly_guard
    ):
        """Was `test_li3_reproduces_sproutworks_ownership_contradiction`
        (FAIL, the bug). Re-verified live 2026-08-10 (Q21 answer A --
        "preserve the project's customization and correct the lock"):
        sproutworks's lock no longer records `elec.md`/`emb.md`/`fmea.md`/
        `hyd.md`/`src.md` (the five agents whose own `owner: project`
        frontmatter contradicted a `framework` lock entry) as
        framework-owned at all, so the contradiction is gone. The check's
        ability to still detect this exact shape is proven by
        `TestOwnershipAgrees.test_project_owned_frontmatter_locked_as_
        framework_fails` above, not by this machine test."""

        sproutworks = _require_real_repo(_REAL_PERSONAL_ROOT / "sproutworks")
        claude_copilot = _require_real_repo(_REAL_COPILOT_ROOT / "claude-copilot")

        with machine_readonly_guard(
            extra_paths=[
                sproutworks / "copilot.lock.json",
                claude_copilot / "copilot.lock.json",
            ]
        ):
            results = lock.check_lock_ownership_frontmatter_agrees(
                [sproutworks, claude_copilot]
            )

        sprout_result = _one(results, str(sproutworks))
        assert sprout_result.verdict is Verdict.PASS, (
            "LI-3 (Q21 ownership contradiction) is expected to PASS for sproutworks "
            "on this machine today; if it now FAILs, the contradiction has "
            "returned -- update TEST-MATRIX.md and this test together"
        )
        assert sprout_result.evidence == ()

        # claude-copilot's own lock has no owner:-project frontmatter
        # contradictions -- the check must not false-positive on it.
        assert _one(results, str(claude_copilot)).verdict is Verdict.PASS


@pytest.mark.machine
class TestMachineTruthWaiverAndRequiredPaths:
    def test_li4_reproduces_control_tower_ready_by_waiver_and_hermes_control(
        self, machine_readonly_guard
    ):
        """RC-4 waiver hole (closed): this repo (copilot-control-tower)
        used to classify claude `ready` with only 2 of 4 required paths
        recorded under `customized-preserve`. Re-verified live 2026-08-10
        against both this repo and `hermes`: claude is now honestly
        `guided-integration` in both (a required path absent from disk is
        no longer waived into `ready`), so the only component either repo
        reaches `ready` through is codex, reached honestly (full mode, not
        waived) -- this check's FAIL population is empty on both, and it
        PASSes. Kept unrenamed so its git history stays attached to the
        live proof it documents."""

        control_tower = _require_real_repo(_REAL_COPILOT_ROOT / "copilot-control-tower")
        hermes = _require_real_repo(_REAL_TSM_ROOT / "hermes")

        with machine_readonly_guard(
            extra_paths=[
                control_tower / "copilot.lock.json",
                hermes / "copilot.lock.json",
            ]
        ):
            results = lock.check_lock_waiver_ready_requires_required_paths(
                [control_tower, hermes]
            )

        control_tower_result = _one(results, str(control_tower))
        assert control_tower_result.verdict is Verdict.PASS
        assert control_tower_result.expected_today is ExpectedToday.PASS

        # hermes's only `ready` component is codex, reached honestly
        # (full mode) -- claude itself is guided-integration, not ready,
        # so it never enters this check's population at all.
        hermes_result = _one(results, str(hermes))
        assert hermes_result.verdict is not Verdict.FAIL

    def test_li5_claude_copilot_now_records_its_own_hook(self, machine_readonly_guard):
        """Was `test_li5_reproduces_the_remaining_missing_hook_on_claude_
        copilot_itself` (was, before that,
        `test_li5_reproduces_the_universal_missing_hook_on_claude`).
        Re-verified live 2026-08-11: `claude-copilot` (this framework's
        own foundation repo) had its `claude` component lock entry
        regenerated directly
        (`cc.core.ecosystem.projects.generate_component_lock_entry`, the
        same per-project generator every other repo's installer already
        uses) -- `.claude/hooks/copilot-hook.sh` (a file it already
        shipped, executable, just never locked) is now recorded, closing
        the last confirmed holdout this test documented."""

        claude_copilot = _require_real_repo(_REAL_COPILOT_ROOT / "claude-copilot")
        hermes = _require_real_repo(_REAL_TSM_ROOT / "hermes")
        insights = _require_real_repo(_REAL_COPILOT_ROOT / "insights-copilot")

        with machine_readonly_guard(
            extra_paths=[
                claude_copilot / "copilot.lock.json",
                hermes / "copilot.lock.json",
                insights / "copilot.lock.json",
            ]
        ):
            results = lock.check_lock_full_mode_records_required_paths(
                [claude_copilot, hermes, insights]
            )

        claude_result = _one(results, str(claude_copilot))
        assert claude_result.verdict is Verdict.PASS
        lock_data = json.loads(
            (claude_copilot / "copilot.lock.json").read_text(encoding="utf-8")
        )
        claude_component = next(
            c for c in lock_data["components"] if c["component"] == "claude"
        )
        assert any(
            f["path"] == ".claude/hooks/copilot-hook.sh"
            for f in claude_component["files"]
        )

        # hermes now records the hook (RC-1 fan-out reached it) --
        # full-mode and complete.
        assert _one(results, str(hermes)).verdict is Verdict.PASS

        # insights-copilot's claude entry is full-mode and already records
        # the hook; its codex entry is full-mode and complete too.
        assert _one(results, str(insights)).verdict is Verdict.PASS
