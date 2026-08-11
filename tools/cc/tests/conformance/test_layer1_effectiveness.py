"""Layer 1 (tier) — EFFECTIVENESS tests (`cc.core.conformance.effectiveness`).

Closes the blind spot: the harness's existing checks (H-1..H-9) prove the
RESOLVER computes the right answer given inputs; none of them prove the
answer ever reaches a project, or that anything actually consumes it. Every
class below follows the same two-fixture rule `test_layer1_tier.py` already
holds itself to — a PASS-shape fixture and a FAIL-shape fixture per check,
so no check here is "satisfied by its own existence" (the exact H-8
regression `tier.py`'s `_is_under_excluded_package` guard closes) — plus,
where a live instance exists on this developer's machine, a
`@pytest.mark.machine` test asserting the verdict this task's own live
investigation (2026-08-11) found and recorded in `effectiveness.py`'s
per-check `expected_today` overrides.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cc.core.conformance import effectiveness as eff
from cc.core.conformance.types import Verdict
from cc.core.ecosystem.discovery import discover_contributions
from cc.core.ecosystem.lockfile import LAYER_META_KEY

from .conftest import FleetFactory

pytestmark = pytest.mark.filterwarnings("ignore")

_REAL_HOME = Path.home()
_REAL_MACHINE_CONFIG_PATH = _REAL_HOME / ".claude" / "cc" / "config.json"
_REAL_MANIFEST_PATH = _REAL_HOME / ".config" / "copilot" / "copilot.layers.yml"

# This file lives at <claude-copilot>/tools/cc/tests/conformance/test_layer1_effectiveness.py
# -- same depth as test_layer1_tier.py, same derivation.
_CLAUDE_COPILOT_ROOT = Path(__file__).resolve().parents[4]
_LADDER_AGENT_FILES = ("cw.md", "sd.md", "ta.md", "ind.md", "uxd.md", "uids.md", "cco.md")


def _real_machine_available() -> bool:
    return _REAL_MACHINE_CONFIG_PATH.is_file() and _REAL_MANIFEST_PATH.is_file()


requires_real_machine = pytest.mark.skipif(
    not _real_machine_available(),
    reason="real ~/.claude/cc/config.json or ~/.config/copilot/copilot.layers.yml not present on this machine",
)


# ---------------------------------------------------------------------------
# E-1 -- org content reaches the project's INSTALLED files
# ---------------------------------------------------------------------------


class TestE1OrgContentReachesProject:
    def test_fixture_pass_marker_present_in_installed_text(self):
        result = eff.check_e1_org_content_reaches_project(
            probe_item="cw",
            winning_layer="probe-organization",
            expected_marker="ORG-MARKER-abc123",
            installed_text="---\nstatus: active\n---\nORG-MARKER-abc123\n",
        )
        assert result.verdict is Verdict.PASS

    def test_fixture_fail_when_installer_never_consulted_the_tier(self):
        """The exact real shape: the installer copied foundation content
        only, so the marker a fixture org tier declared never reached the
        installed file."""

        result = eff.check_e1_org_content_reaches_project(
            probe_item="cw",
            winning_layer="probe-organization",
            expected_marker="ORG-MARKER-abc123",
            installed_text="---\nstatus: active\n---\nfoundation content, unmodified\n",
        )
        assert result.verdict is Verdict.FAIL
        assert result.evidence
        assert "probe-organization" in result.evidence[0].expected

    def test_fixture_fail_when_nothing_installed_at_all(self):
        result = eff.check_e1_org_content_reaches_project(
            probe_item="cw",
            winning_layer="probe-organization",
            expected_marker="ORG-MARKER-abc123",
            installed_text=None,
        )
        assert result.verdict is Verdict.FAIL

    @requires_real_machine
    @pytest.mark.machine
    def test_machine_real_installer_never_wires_org_tier_content_in(self):
        """Drives the real setup-project.md bash steps (via `roundtrip.py`,
        the module that already established what "the real installer"
        means) against a scratch project + scratch $HOME, cross-checked
        against a synthetic org-tier fixture — the same assembly
        `commands/conformance.py::_run_installer_effectiveness_machine`
        performs for the live report. Every write lands inside a fresh
        tmp dir; no real project or tier repo is ever touched, so this
        does not need `machine_readonly_guard` the way a real-repo-reading
        H-check does."""

        from cc.commands import conformance as conformance_cmd

        conformance_cmd._ensure_registry_loaded()
        results = conformance_cmd._run_installer_effectiveness_machine()
        e1_results = [r for r in results if r.id == eff.E1_ORG_CONTENT_REACHES_PROJECT.id]
        assert e1_results, "installer effectiveness probe produced no E-1 result"
        assert e1_results[0].verdict is Verdict.PASS, (
            "TASK-live-2026-08-11, re-verified 2026-08-11: setup-project.md's "
            "Copy Agents step now resolves each agent through "
            "resolve_claude_content() (core/ecosystem/project_sources.py) "
            "instead of a single hardcoded ~/.claude/copilot source, and "
            "this harness's own fixture is wired into the scratch $HOME's "
            "layers.manifest BEFORE the bash runs (previously built "
            "afterward, so no installer could ever have seen it) -- both "
            "were required for the org tier's content to actually reach "
            "the installed file"
        )


# ---------------------------------------------------------------------------
# E-2 -- nearest-wins never costs the project its other artifacts
# ---------------------------------------------------------------------------


class TestE2NearestWinsPreservesSiblings:
    def test_fixture_pass_all_siblings_still_installed(self):
        result = eff.check_e2_nearest_wins_preserves_siblings(
            overridden_item="cw",
            roster=["cw", "sd", "ta", "kc"],
            installed_content={
                "cw": "org override content",
                "sd": "foundation content",
                "ta": "foundation content",
                "kc": "foundation content",
            },
        )
        assert result.verdict is Verdict.PASS

    def test_fixture_fail_a_naive_wholesale_switch_drops_the_others(self):
        """The regression this exists to pin: an installer that, upon
        seeing ANY org override, switches its whole source to the org
        tier wholesale instead of resolving per item -- losing every
        sibling the org tier does not also declare."""

        result = eff.check_e2_nearest_wins_preserves_siblings(
            overridden_item="cw",
            roster=["cw", "sd", "ta", "kc"],
            installed_content={
                "cw": "org override content",
                "sd": None,
                "ta": "",
                # "kc" missing entirely
            },
        )
        assert result.verdict is Verdict.FAIL
        assert {e.path for e in result.evidence} == {"sd", "ta", "kc"}

    @requires_real_machine
    @pytest.mark.machine
    def test_machine_real_installer_copies_the_full_roster_regardless(self):
        from cc.commands import conformance as conformance_cmd

        conformance_cmd._ensure_registry_loaded()
        results = conformance_cmd._run_installer_effectiveness_machine()
        e2_results = [
            r for r in results if r.id == eff.E2_NEAREST_WINS_PRESERVES_SIBLINGS.id
        ]
        assert e2_results, "installer effectiveness probe produced no E-2 result"
        assert e2_results[0].verdict is Verdict.PASS, (
            "re-verified 2026-08-11 against the now-tier-aware installer: "
            "resolve_claude_content() resolves PER agent, not per root, so "
            "one agent (cco) winning from the organization tier costs the "
            "project none of the other roster agents, which still resolve "
            "from the foundation -- nearest-wins stays per-item even now "
            "that the installer actually consults the ladder"
        )


# ---------------------------------------------------------------------------
# E-3 -- draft placeholder never shadows, generalized across resolve_layers
# ---------------------------------------------------------------------------


class TestE3DraftPlaceholderNeverShadowsResolverWide:
    def test_fixture_pass_substantive_winner(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        near = fleet.product("claude").tier("organization", rank=30)
        far = fleet.product("claude").tier("foundation", rank=40)
        near.contributes("commands", {"protocol": "a real, substantive org override"})
        far.contributes("commands", {"protocol": "foundation protocol content"})
        handle = fleet.build()

        layers = [near.manifest_layer(), far.manifest_layer()]
        contributions = discover_contributions(layers)
        results = eff.check_e3_draft_placeholder_never_shadows(
            layers=layers, contributions=contributions
        )
        assert results
        assert all(r.verdict is Verdict.PASS for r in results)
        assert handle.tiers  # fleet built successfully

    def test_fixture_fail_todo_placeholder_shadows_real_content(self, tmp_path):
        """The exact live shape this check caught for real: an org
        override whose own text opens with a TODO placeholder marker
        while shadowing genuine foundation content."""

        fleet = FleetFactory(tmp_path)
        near = fleet.product("claude").tier("organization", rank=30)
        far = fleet.product("claude").tier("foundation", rank=40)
        near.contributes(
            "commands",
            {"protocol": "TODO(pablo): no-op placeholder, byte-for-byte reproduction"},
        )
        far.contributes("commands", {"protocol": "foundation protocol content, real"})
        fleet.build()

        layers = [near.manifest_layer(), far.manifest_layer()]
        contributions = discover_contributions(layers)
        results = eff.check_e3_draft_placeholder_never_shadows(
            layers=layers, contributions=contributions
        )
        assert len(results) == 1
        assert results[0].verdict is Verdict.FAIL
        assert results[0].evidence

    def test_fixture_fail_empty_draft_shadows_real_content(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        near = fleet.product("claude").tier("personal", rank=10)
        far = fleet.product("claude").tier("foundation", rank=40)
        near.write("commands/protocol.md", "---\nstatus: draft\n---\n")
        far.contributes("commands", {"protocol": "foundation protocol content, real"})
        fleet.build()

        layers = [near.manifest_layer(), far.manifest_layer()]
        contributions = discover_contributions(layers)
        results = eff.check_e3_draft_placeholder_never_shadows(
            layers=layers, contributions=contributions
        )
        assert len(results) == 1
        assert results[0].verdict is Verdict.FAIL

    def test_fixture_skip_when_nothing_is_shadowed(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        only = fleet.product("claude").tier("foundation", rank=40)
        only.contributes("commands", {"protocol": "the only declaration"})
        fleet.build()

        layers = [only.manifest_layer()]
        contributions = discover_contributions(layers)
        results = eff.check_e3_draft_placeholder_never_shadows(
            layers=layers, contributions=contributions
        )
        assert results == ()

    @requires_real_machine
    @pytest.mark.machine
    def test_machine_org_protocol_placeholder_was_removed_not_papered_over(self):
        """TASK-live-2026-08-11, re-verified 2026-08-11: `claude-copilot-
        internal`'s `commands/protocol.md` used to open "TODO(pablo): this
        section is currently a no-op placeholder ... byte-for-byte"
        reproduction of the foundation copy -- a real, live instance of
        exactly the shadow-substance bug this check generalizes H-3/Q25 to
        catch. Per the task's own instruction not to author the owner's
        company protocol content, the fix was to DELETE the empty, stale
        fork (982 lines vs. foundation's 994, carrying an outdated
        extension-resolution algorithm) rather than launder it by
        rebasing -- so the organization tier now declares nothing for
        `commands/protocol` and resolution honestly falls through to the
        foundation's real, current content. This test asserts the
        substance guard is no longer even reached for this item (nothing
        to guard against), never that the guard was relaxed."""

        from cc.commands import conformance as conformance_cmd

        conformance_cmd._ensure_registry_loaded()
        results = conformance_cmd._run_resolver_effectiveness_machine()
        e3_results = [
            r for r in results if r.id == eff.E3_DRAFT_PLACEHOLDER_NEVER_SHADOWS.id
        ]
        protocol_results = [r for r in e3_results if "protocol" in r.subject]
        assert protocol_results == [], (
            "claude/commands/protocol should no longer appear in E-3 results "
            "at all -- the organization tier declares nothing for it now, so "
            "there is nothing shadowed to evaluate substance against"
        )


# ---------------------------------------------------------------------------
# E-4 -- resolve attribution must match a REAL lock materialization
# ---------------------------------------------------------------------------


class TestE4AttributionMatchesLock:
    _LAYERS = [
        {
            "id": "org",
            "role": "organization",
            "rank": 30,
            "product": "claude",
            "source": {"repo": "file:///org", "path": "/org"},
            "auth": "anon",
            "activation": "always",
        },
        {
            "id": "foundation",
            "role": "foundation",
            "rank": 40,
            "product": "claude",
            "source": {"repo": "file:///foundation", "path": "/foundation"},
            "auth": "anon",
            "activation": "always",
        },
    ]
    _CONTRIBUTIONS = {
        "org": {"commands": {"protocol": "sha-org-1"}},
        "foundation": {"commands": {"protocol": "sha-foundation-1"}},
    }

    def test_fixture_pass_winner_has_a_real_recorded_pin(self):
        lockfile = {"org": {"commands": {"protocol": "sha-org-1"}, LAYER_META_KEY: {}}}
        results = eff.check_e4_resolve_attribution_matches_lock(
            layers=self._LAYERS, contributions=self._CONTRIBUTIONS, lockfile=lockfile
        )
        assert len(results) == 1
        assert results[0].verdict is Verdict.PASS

    def test_fixture_fail_winner_lock_entry_is_meta_only(self):
        """The exact live discrepancy this check exists to catch: `cc
        resolve --explain` claims `org` wins, but `org`'s lock entry
        carries only `_meta` -- a mirror pinned with no real dimension
        pins ever recorded (`claude-organization` on the real machine,
        2026-08-11)."""

        lockfile = {
            "org": {LAYER_META_KEY: {"product": "claude", "source_sha": "deadbeef"}}
        }
        results = eff.check_e4_resolve_attribution_matches_lock(
            layers=self._LAYERS, contributions=self._CONTRIBUTIONS, lockfile=lockfile
        )
        assert len(results) == 1
        assert results[0].verdict is Verdict.FAIL
        assert "_meta" in results[0].evidence[0].actual

    def test_fixture_fail_winner_absent_from_lock_entirely(self):
        results = eff.check_e4_resolve_attribution_matches_lock(
            layers=self._LAYERS, contributions=self._CONTRIBUTIONS, lockfile={}
        )
        assert len(results) == 1
        assert results[0].verdict is Verdict.FAIL

    @requires_real_machine
    @pytest.mark.machine
    def test_machine_claude_organization_no_longer_wins_anything(self):
        """TASK-live-2026-08-11 ground truth (superseded, re-verified
        2026-08-11): `cc resolve --explain` used to report `winning_layer:
        claude-organization` for `commands/protocol`, while `~/.claude/cc/
        copilot.lock.json`'s `claude-organization` entry carried only
        `_meta`. That specific discrepancy is now closed at the source: the
        stale, empty `commands/protocol.md` placeholder in
        `claude-copilot-internal` was deleted (E-3's fix, this same task),
        so `claude-organization` no longer declares anything and cannot
        win any item at all -- it simply never appears as a `winning_layer`
        in E-4's results any more, not because the check stopped looking."""

        from cc.commands import conformance as conformance_cmd

        conformance_cmd._ensure_registry_loaded()
        results = conformance_cmd._run_resolver_effectiveness_machine()
        e4_results = [
            r for r in results if r.id == eff.E4_ATTRIBUTION_MATCHES_LOCK.id
        ]
        assert e4_results, "resolver effectiveness probe produced no E-4 result"
        org_results = [r for r in e4_results if "claude-organization" in r.subject]
        assert org_results == [], (
            "claude-organization should not win any item now that its only "
            "declared content (commands/protocol.md) has been removed"
        )

    # NOTE: deliberately NOT a `@pytest.mark.machine` test. `tests/conftest.py`'s
    # autouse `_isolate_machine_config` fixture redirects `CC_MACHINE_ROOT`
    # for EVERY test with no exemption for `machine`-marked ones, so
    # `read_lockfile(default_lockfile_path())` is ALWAYS `{}` inside pytest
    # regardless of the real machine's actual lockfile content -- a
    # "machine" test asserting on `expected_today` here would trivially
    # pass no matter what the real lockfile says (every winner would look
    # lock-empty), proving nothing. These two fixture tests exercise the
    # SAME dynamic logic (`_policy_blocked_reason`) deterministically
    # instead, matching this file's own two-fixture-rule discipline.
    _POLICY_BLOCKED_LAYERS = [
        {
            "id": "org",
            "role": "organization",
            "rank": 30,
            "product": "claude",
            "source": {"repo": "file:///org", "path": "/org"},
            "auth": "anon",
            "activation": "always",
            "policy": {"allowed_signers": []},
        },
        {
            "id": "foundation",
            "role": "foundation",
            "rank": 40,
            "product": "claude",
            "source": {"repo": "file:///foundation", "path": "/foundation"},
            "auth": "anon",
            "activation": "always",
            "policy": {"allowed_signers": ["SHA256:deadbeef"]},
        },
    ]

    def test_fixture_fail_policy_blocked_winner_is_expected(self):
        """`org` declares `allowed_signers: []` for `commands` (an
        executable dimension per `core/ecosystem/policy.py`'s
        `EXECUTABLE_DIMENSIONS`) -- the exact live shape of
        `knowledge-personal`/`cli-personal`/`codex-personal`/(the now-
        removed) `claude-organization` in `copilot.layers.yml` today.
        `verdict` stays FAIL (the resolver still names a layer the lock
        never backed -- that disagreement is real), but `expected_today`
        must be FAIL too: this is a legitimate, already-understood,
        by-design outcome, not a regression."""

        lockfile = {"org": {LAYER_META_KEY: {"product": "claude"}}}
        results = eff.check_e4_resolve_attribution_matches_lock(
            layers=self._POLICY_BLOCKED_LAYERS,
            contributions=self._CONTRIBUTIONS,
            lockfile=lockfile,
        )
        assert len(results) == 1
        assert results[0].verdict is Verdict.FAIL
        assert results[0].expected_today is eff.ExpectedToday.FAIL
        assert "POLICY-BLOCKED" in results[0].evidence[0].detail

    def test_fixture_fail_non_policy_blocked_winner_is_unexpected(self):
        """Same shape, but the WINNER (`foundation`) declares a real
        signer -- there is no policy-blocked reason for its lock entry to
        be empty, so this must surface as `expected_today=PASS` (an
        honest "investigate this" signal a baseline diff would flag as a
        regression), never silently absorbed into the same "known
        exception" bucket as a genuinely policy-blocked winner. This is
        the check refusing to be weakened into always agreeing with
        whatever the lock happens to say."""

        contributions = {
            "org": {},
            "foundation": {"commands": {"protocol": "sha-foundation-1"}},
        }
        lockfile = {"foundation": {LAYER_META_KEY: {"product": "claude"}}}
        results = eff.check_e4_resolve_attribution_matches_lock(
            layers=self._POLICY_BLOCKED_LAYERS,
            contributions=contributions,
            lockfile=lockfile,
        )
        assert len(results) == 1
        assert results[0].verdict is Verdict.FAIL
        assert results[0].expected_today is eff.ExpectedToday.PASS
        assert "NOT POLICY-BLOCKED" in results[0].evidence[0].detail


# ---------------------------------------------------------------------------
# E-5 -- knowledge ladder hydration must be followed by real consumption
# ---------------------------------------------------------------------------


class TestE5KnowledgeLadderActuallyConsumed:
    def test_fixture_pass_walks_and_reads(self):
        text = (
            '2. `eval "$(cc env)"` -- hydrate shared docs / knowledge env\n'
            "3. before writing, walk `$CC_KNOWLEDGE_REPOS` (nearest-tier-first) "
            "and read the first repo where `01-company/02-voice/` exists\n"
        )
        results = eff.check_e5_knowledge_ladder_actually_consumed(
            agent_files={"cw.md": text}
        )
        assert len(results) == 1
        assert results[0].verdict is Verdict.PASS

    def test_fixture_fail_hydrates_then_reads_nothing(self):
        """The exact real shape found live: an agent hydrates `cc env`
        and never walks/reads `$CC_KNOWLEDGE_REPOS` at all -- installed
        (the agent file exists, the env var is populated) but not
        effective (nothing is ever read from it)."""

        text = (
            '2. `eval "$(cc env)"` -- hydrate shared docs / knowledge env\n'
            "3. `cc memory search \"<task topic>\"` -- recall prior decisions\n"
        )
        results = eff.check_e5_knowledge_ladder_actually_consumed(
            agent_files={"ind.md": text}
        )
        assert len(results) == 1
        assert results[0].verdict is Verdict.FAIL

    def test_fixture_skip_when_agent_never_hydrates_cc_env(self):
        results = eff.check_e5_knowledge_ladder_actually_consumed(
            agent_files={"qa.md": "1. `tc task get <taskId>` -- verify task exists\n"}
        )
        assert len(results) == 1
        assert results[0].verdict is Verdict.SKIP

    @requires_real_machine
    @pytest.mark.machine
    def test_machine_all_seven_ladder_agents_walk_and_read_today(
        self, machine_readonly_guard
    ):
        """TASK-live-2026-08-11: re-verified that cw/sd/ta/ind/uxd/uids/cco
        all walk-and-read $CC_KNOWLEDGE_REPOS today -- ind/uxd/uids/cco
        were found hydrating `cc env` and reading nothing at the start of
        this task; a concurrent sibling agent's fix landed in this repo's
        working tree during this same session. Reads agent files directly
        (never through `_run_tier_layer_machine`'s `resolve_knowledge_
        repos()` gate, which the whole-suite `_isolate_machine_config`
        autouse fixture redirects to an empty tmp root for every test --
        same reason `test_layer1_tier.py`'s own H-5 machine test reads
        `_CLAUDE_COPILOT_ROOT`-relative paths directly instead)."""

        agents_dir = _CLAUDE_COPILOT_ROOT / ".claude" / "agents"
        agent_paths = [agents_dir / name for name in _LADDER_AGENT_FILES]
        assert all(p.is_file() for p in agent_paths), (
            "expected the real framework agent files to exist"
        )

        with machine_readonly_guard(extra_paths=agent_paths):
            agent_files = {
                path.name: path.read_text(encoding="utf-8") for path in agent_paths
            }
            results = eff.check_e5_knowledge_ladder_actually_consumed(
                agent_files=agent_files
            )

        by_name = {result.subject: result for result in results}
        assert set(by_name) == set(_LADDER_AGENT_FILES)
        for name, result in by_name.items():
            assert result.verdict is Verdict.PASS, (
                f"{name} regressed to hydrate-then-never-read: {result.detail}"
            )


# ---------------------------------------------------------------------------
# E-6 -- extension resolution wired beyond prose
# ---------------------------------------------------------------------------


class TestE6ExtensionResolutionWiredBeyondProse:
    def test_fixture_fail_prose_only_mention(self, tmp_path):
        (tmp_path / "commands").mkdir()
        (tmp_path / "commands" / "protocol.md").write_text(
            "Run `cc extensions resolve --agent <id> --json` before role work.\n",
            encoding="utf-8",
        )
        result = eff.check_e6_extension_resolution_wired_beyond_prose(
            source_root=tmp_path
        )
        assert result.verdict is Verdict.FAIL
        assert result.evidence

    def test_fixture_fail_commented_out_line_does_not_count(self, tmp_path):
        (tmp_path / "hooks").mkdir()
        (tmp_path / "hooks" / "copilot-hook.sh").write_text(
            "#!/bin/bash\n# TODO: call cc extensions resolve --agent \"$AGENT\" --json\n",
            encoding="utf-8",
        )
        result = eff.check_e6_extension_resolution_wired_beyond_prose(
            source_root=tmp_path
        )
        assert result.verdict is Verdict.FAIL

    def test_fixture_pass_real_hook_invocation(self, tmp_path):
        (tmp_path / "hooks").mkdir()
        (tmp_path / "hooks" / "copilot-hook.sh").write_text(
            '#!/bin/bash\ncc extensions resolve --agent "$AGENT" --json\n',
            encoding="utf-8",
        )
        result = eff.check_e6_extension_resolution_wired_beyond_prose(
            source_root=tmp_path
        )
        assert result.verdict is Verdict.PASS
        assert "copilot-hook.sh" in result.detail

    @requires_real_machine
    @pytest.mark.machine
    def test_machine_pretool_check_hook_now_invokes_it_for_real(self, machine_readonly_guard):
        """TASK-live-2026-08-11, re-verified 2026-08-11: `.claude` now
        PASSES -- `.claude/hooks/pretool-check.sh` gained a real
        `rule_extension_resolution` that calls `cc extensions resolve
        --agent <id> --json` on a direct main-session @agent-X dispatch
        (scoped to the small named roster of agents a real org/personal
        knowledge-manifest.json plausibly declares an extension for --
        never every agent, which would tax the framework's single most
        frequent operation for the ~half of the roster that can only ever
        resolve to `no_extension`) and denies on `fallback_fail`, the one
        outcome every wired agent's own file already documented as a hard
        stop but had no enforced consumer for. `plugins`/`scripts`
        correctly stay FAIL -- neither has any reason to invoke extension
        resolution, and wiring it there anyway would be exactly the
        cargo-culting this check exists to catch, not a fix. Reads
        `_CLAUDE_COPILOT_ROOT` directly, same isolation-avoidance reason as
        the E-5 machine test above."""

        candidates = [
            _CLAUDE_COPILOT_ROOT / relative
            for relative in (".claude", "plugins", "scripts")
        ]
        candidates = [path for path in candidates if path.is_dir()]
        assert candidates, "expected at least one of .claude/plugins/scripts to exist"

        with machine_readonly_guard(extra_paths=candidates):
            results = [
                eff.check_e6_extension_resolution_wired_beyond_prose(source_root=path)
                for path in candidates
            ]

        by_name = {Path(r.subject).name: r for r in results}
        assert by_name[".claude"].verdict is Verdict.PASS, by_name[".claude"].detail
        for name in ("plugins", "scripts"):
            if name in by_name:
                assert by_name[name].verdict is Verdict.FAIL, (
                    f"{name}: expected still-FAIL (nothing there legitimately "
                    "invokes extension resolution)"
                )
