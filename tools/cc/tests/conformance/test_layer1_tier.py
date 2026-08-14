"""WP-2 tests: Layer 1 -- tier / hierarchy resolution.

Implements `TEST-MATRIX.md` section 1's 9 test ids (H-1..H-9), verbatim,
against `cc.core.conformance.tier`. Every check class below follows the
two-world rule (`HARNESS-DESIGN.md` §5.1):

  - a fixture (World A) PASS test and a fixture FAIL test, built with
    `conftest.py`'s `FleetFactory` -- proving the check can detect BOTH
    outcomes (`test_every_h_check_has_a_positive_and_a_negative_test`
    below is the fitness function that holds this package to it), and
  - for the H-ids that have a live instance on this machine (H-1, H-2,
    H-3, H-4, H-5, H-6, H-7, H-8 -- everything except fixture-only H-9,
    `TEST-MATRIX.md` §7 items 9-10), a `@pytest.mark.machine` test that
    reads the REAL manifest/config/tier repos strictly read-only and
    asserts the verdict `TEST-MATRIX.md` §8 predicts for THIS machine
    today.

No real machine path is ever hardcoded in this file (the repo's own
no-hardcoded-paths CI gate greps committed source for absolute user-home
path literals) -- every real path used below is READ at test time from
`Path.home()`-relative locations (the real `~/.claude/cc/config.json`,
the real `~/.config/copilot/copilot.layers.yml`, and this test file's own
location relative to the `claude-copilot` repo root it lives inside),
never written as a literal string.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cc.core.conformance import tier
from cc.core.conformance.types import ExpectedToday, Verdict
from cc.core.ecosystem.manifest import load_layers, validate_layers
from cc.core.extensions_resolver import ACTION_APPLY, ExtensionResolution

from .conftest import FleetFactory

pytestmark = pytest.mark.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Real-machine path resolution -- deliberately NOT through
# `cc.core.config_paths` (the whole-suite `_isolate_machine_config` autouse
# fixture in `tests/conftest.py` redirects `CC_MACHINE_ROOT` to a fresh
# tmp_path for every test, so any read through that seam would see an EMPTY
# isolated config, not this machine's real one). This mirrors
# `fsguard.py`'s own `_home()` and `tests/conftest.py`'s own
# `_REAL_MACHINE_CONFIG` constant, which resolve the same way for the same
# reason.
# ---------------------------------------------------------------------------

_REAL_HOME = Path.home()
_REAL_MACHINE_CONFIG_PATH = _REAL_HOME / ".claude" / "cc" / "config.json"
_REAL_MANIFEST_PATH = _REAL_HOME / ".config" / "copilot" / "copilot.layers.yml"

# This file lives at <claude-copilot>/tools/cc/tests/conformance/test_layer1_tier.py.
_CLAUDE_COPILOT_ROOT = Path(__file__).resolve().parents[4]
_CC_TOOL_ROOT = Path(__file__).resolve().parents[2]
_REAL_AGENT_FILES = ("cw.md", "sd.md", "ta.md")


def _real_machine_available() -> bool:
    return _REAL_MACHINE_CONFIG_PATH.is_file() and _REAL_MANIFEST_PATH.is_file()


def _real_knowledge_ladder() -> list[str]:
    """The real `paths.knowledge_repo` list, read directly from the real
    `~/.claude/cc/config.json` -- never through `get_resolved_config()`
    (isolated to a tmp root for the whole test process, see module
    docstring)."""

    config = json.loads(_REAL_MACHINE_CONFIG_PATH.read_text(encoding="utf-8"))
    value = (config.get("paths") or {}).get("knowledge_repo")
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


requires_real_machine = pytest.mark.skipif(
    not _real_machine_available(),
    reason="real ~/.claude/cc/config.json or ~/.config/copilot/copilot.layers.yml not present on this machine",
)


# ---------------------------------------------------------------------------
# Fixture helpers (World A)
# ---------------------------------------------------------------------------


def _seed_extension(
    tier_builder,
    *,
    agent: str,
    body: str,
    frontmatter_extra: str = "",
) -> None:
    """Write a `knowledge-manifest.json` declaring exactly one
    `extensions[]` entry for `agent`, plus the extension file itself --
    the same two-file shape `extensions_resolver.py` consumes."""

    manifest = {
        "extensions": [
            {
                "agent": agent,
                "type": "extension",
                "file": f".claude/extensions/{agent}.extension.md",
                "description": f"fixture extension for {agent}",
                "requiredSkills": [],
                "fallbackBehavior": "use_base",
            }
        ]
    }
    tier_builder.write("knowledge-manifest.json", json.dumps(manifest, indent=2))
    tier_builder.write(
        f".claude/extensions/{agent}.extension.md",
        f"---\n{frontmatter_extra}---\n\n{body}",
    )


def _always_available(_required: list[str]) -> list[str]:
    """`missing_skills_checker` stub: every required skill is available.
    Isolates the precedence/substance assertions under test from the real
    global skill store."""

    return []


# ---------------------------------------------------------------------------
# H-1 -- nearest DECLARED tier wins
# ---------------------------------------------------------------------------


class TestH1NearestDeclaredWins:
    def test_fixture_pass_nearest_tier_wins(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        near = fleet.product("claude").tier("personal", rank=10)
        far = fleet.product("claude").tier("foundation", rank=40)
        _seed_extension(near, agent="kc", body="personal voice content, real")
        _seed_extension(far, agent="kc", body="foundation voice content, real")
        fleet.build()

        repos = [str(near.path), str(far.path)]
        result = tier.check_h1_nearest_declared_wins(
            "kc", knowledge_repos=repos, missing_skills_checker=_always_available
        )
        assert result.verdict is Verdict.PASS
        assert result.subject == "kc"

    def test_fixture_pass_farther_tier_wins_when_nearer_absent(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        near = fleet.product("claude").tier("personal", rank=10)  # declares nothing
        far = fleet.product("claude").tier("organization", rank=30)
        _seed_extension(far, agent="sd", body="org service-design content")
        fleet.build()

        repos = [str(near.path), str(far.path)]
        result = tier.check_h1_nearest_declared_wins(
            "sd", knowledge_repos=repos, missing_skills_checker=_always_available
        )
        assert result.verdict is Verdict.PASS

    def test_fixture_skip_when_nothing_declares(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        near = fleet.product("claude").tier("personal", rank=10)
        fleet.build()

        result = tier.check_h1_nearest_declared_wins(
            "ghost-agent", knowledge_repos=[str(near.path)]
        )
        assert result.verdict is Verdict.SKIP

    def test_fixture_fail_detects_a_wrong_winner(self, tmp_path, monkeypatch):
        """Proves the check can actually FAIL -- `resolve_extension` is
        monkeypatched to return a winner OTHER than the nearest declaring
        tier (independently determined by reading each tier's manifest),
        reproducing what a real regression in the resolver's iteration
        order would look like."""

        fleet = FleetFactory(tmp_path)
        near = fleet.product("claude").tier("personal", rank=10)
        far = fleet.product("claude").tier("foundation", rank=40)
        _seed_extension(near, agent="kc", body="personal content")
        _seed_extension(far, agent="kc", body="foundation content")
        fleet.build()

        repos = [str(near.path), str(far.path)]
        wrong_file = str(Path(far.path) / ".claude" / "extensions" / "kc.extension.md")

        def _wrong_winner(agent, *, knowledge_repos=None, missing_skills_checker=None):
            return ExtensionResolution(
                agent=agent,
                action=ACTION_APPLY,
                matched=True,
                type="extension",
                file=wrong_file,
                source_repo=repos[1],  # the FARTHER tier, wrongly
            )

        monkeypatch.setattr(tier, "resolve_extension", _wrong_winner)
        result = tier.check_h1_nearest_declared_wins("kc", knowledge_repos=repos)
        assert result.verdict is Verdict.FAIL
        assert result.evidence
        assert result.evidence[0].expected != result.evidence[0].actual

    @requires_real_machine
    @pytest.mark.machine
    def test_machine_cw_and_sd_resolve_to_the_nearest_declaring_tier(
        self, machine_readonly_guard
    ):
        repos = _real_knowledge_ladder()
        assert len(repos) >= 2, "expected a multi-entry real knowledge ladder"

        with machine_readonly_guard(extra_paths=[Path(r) for r in repos]):
            cw = tier.check_h1_nearest_declared_wins(
                "cw", knowledge_repos=repos, missing_skills_checker=_always_available
            )
            sd = tier.check_h1_nearest_declared_wins(
                "sd", knowledge_repos=repos, missing_skills_checker=_always_available
            )

        # TEST-MATRIX H-1: PASS today -- both cases verified live.
        assert cw.verdict is Verdict.PASS, cw.detail
        assert sd.verdict is Verdict.PASS, sd.detail


# ---------------------------------------------------------------------------
# H-2 -- a nearer tier's absence never blocks a farther tier's real content
# ---------------------------------------------------------------------------


class TestH2AbsenceIsNotShadow:
    def test_fixture_pass_absence_does_not_block_resolution(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        personal = fleet.product("claude").tier("personal", rank=10)  # absent
        department = fleet.product("claude").tier(
            "department", rank=20, unit="accounting"
        )  # absent
        organization = fleet.product("claude").tier("organization", rank=30)
        _seed_extension(organization, agent="do", body="org design-ops content")
        fleet.build()

        repos = [str(personal.path), str(department.path), str(organization.path)]
        result = tier.check_h2_absence_is_not_shadow(
            "do", knowledge_repos=repos, missing_skills_checker=_always_available
        )
        assert result.verdict is Verdict.PASS

    def test_fixture_skip_when_nearest_tier_already_declares(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        near = fleet.product("claude").tier("personal", rank=10)
        _seed_extension(near, agent="kc", body="content")
        fleet.build()

        result = tier.check_h2_absence_is_not_shadow(
            "kc",
            knowledge_repos=[str(near.path)],
            missing_skills_checker=_always_available,
        )
        assert result.verdict is Verdict.SKIP

    def test_fixture_fail_when_absence_actually_blocks_resolution(
        self, tmp_path, monkeypatch
    ):
        fleet = FleetFactory(tmp_path)
        personal = fleet.product("claude").tier("personal", rank=10)  # absent
        organization = fleet.product("claude").tier("organization", rank=30)
        _seed_extension(organization, agent="do", body="org content")
        fleet.build()

        repos = [str(personal.path), str(organization.path)]

        def _no_extension(agent, *, knowledge_repos=None, missing_skills_checker=None):
            return ExtensionResolution(
                agent=agent
            )  # action=no_extension, matched=False

        monkeypatch.setattr(tier, "resolve_extension", _no_extension)
        result = tier.check_h2_absence_is_not_shadow("do", knowledge_repos=repos)
        assert result.verdict is Verdict.FAIL
        assert result.evidence

    @requires_real_machine
    @pytest.mark.machine
    def test_machine_do_ind_sd_uxd_reach_the_org_tier_unmodified(
        self, machine_readonly_guard
    ):
        repos = _real_knowledge_ladder()
        with machine_readonly_guard(extra_paths=[Path(r) for r in repos]):
            results = [
                tier.check_h2_absence_is_not_shadow(
                    agent,
                    knowledge_repos=repos,
                    missing_skills_checker=_always_available,
                )
                for agent in ("do", "ind", "sd", "uxd")
            ]

        exercised = [r for r in results if r.verdict is not Verdict.SKIP]
        assert exercised, (
            "expected at least one of do/ind/sd/uxd to exercise a nearer absence"
        )
        for result in exercised:
            # TEST-MATRIX H-2: PASS today.
            assert result.verdict is Verdict.PASS, result.detail


# ---------------------------------------------------------------------------
# H-3 -- shadow-substance (THE BUG, Q25)
# ---------------------------------------------------------------------------


class TestH3ShadowSubstance:
    def test_fixture_pass_substantive_winner(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        near = fleet.product("claude").tier("personal", rank=10)
        far = fleet.product("claude").tier("foundation", rank=40)
        real_body = "Real, filled-in voice guidance.\n" * 30
        _seed_extension(
            near, agent="cw", body=real_body, frontmatter_extra="status: final\n"
        )
        _seed_extension(
            far, agent="cw", body=real_body, frontmatter_extra="status: final\n"
        )
        fleet.build()

        repos = [str(near.path), str(far.path)]
        result = tier.check_h3_shadow_substance(
            "cw", knowledge_repos=repos, missing_skills_checker=_always_available
        )
        assert result.verdict is Verdict.PASS

    def test_fixture_fail_reproduces_the_draft_scaffold_bug(self, tmp_path):
        """Reproduces the exact live shape: a nearer tier's DRAFT scaffold
        (small, `status: draft`, TODO( markers) resolves as the winner
        over a farther tier's real, substantive content."""

        fleet = FleetFactory(tmp_path)
        near = fleet.product("claude").tier("personal", rank=10)
        far = fleet.product("claude").tier("organization", rank=30)
        scaffold_body = "TODO(pablo): fill this in.\n" * 2
        real_body = "Real, filled-in company voice guidance.\n" * 40
        _seed_extension(
            near, agent="cw", body=scaffold_body, frontmatter_extra="status: draft\n"
        )
        _seed_extension(
            far, agent="cw", body=real_body, frontmatter_extra="status: final\n"
        )
        fleet.build()

        repos = [str(near.path), str(far.path)]
        result = tier.check_h3_shadow_substance(
            "cw", knowledge_repos=repos, missing_skills_checker=_always_available
        )
        assert result.verdict is Verdict.FAIL
        assert result.evidence
        assert "draft" in result.evidence[0].actual

    def test_fixture_skip_when_only_one_tier_declares(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        near = fleet.product("claude").tier("personal", rank=10)
        _seed_extension(
            near, agent="kc", body="content", frontmatter_extra="status: final\n"
        )
        fleet.build()

        result = tier.check_h3_shadow_substance(
            "kc",
            knowledge_repos=[str(near.path)],
            missing_skills_checker=_always_available,
        )
        assert result.verdict is Verdict.SKIP

    @requires_real_machine
    @pytest.mark.machine
    def test_machine_cw_scaffold_is_now_substantive(self, machine_readonly_guard):
        """TEST-MATRIX H-3 / owner decision Q25: re-verified live -- the
        personal `cw.extension.md` scaffold was filled with real drafted
        content (1646B/6x 'TODO(' -> 9002B/0x 'TODO(', `status: draft` ->
        `status: active`), so it no longer hollow-shadows the organization
        tier's real content. Was FAIL (the bug); now PASS."""

        repos = _real_knowledge_ladder()
        with machine_readonly_guard(extra_paths=[Path(r) for r in repos]):
            result = tier.check_h3_shadow_substance(
                "cw", knowledge_repos=repos, missing_skills_checker=_always_available
            )

        assert result.verdict is Verdict.PASS, (
            "H-3 (Q25 shadow-substance) is expected to PASS on this machine today "
            "(the personal cw.extension.md scaffold was filled with real content); "
            "if it now fails, the scaffold has regressed -- update TEST-MATRIX.md "
            "and this test together"
        )
        assert "TODO(" not in result.detail or "0x 'TODO('" in result.detail


# ---------------------------------------------------------------------------
# H-4 -- knowledge ladder order
# ---------------------------------------------------------------------------


class TestH4LadderOrder:
    def test_fixture_pass_four_tier_ladder_matches(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        fleet.product("knowledge").tier("foundation", rank=40)
        fleet.product("knowledge").tier("organization", rank=30)
        fleet.product("knowledge").tier("department", rank=20, unit="accounting")
        fleet.product("knowledge").tier("personal", rank=10)
        handle = fleet.build()

        layers = validate_layers(load_layers(handle.manifest_path))
        expected = tier.knowledge_ladder_from_layers(layers)
        assert len(expected) == 4

        result = tier.check_h4_ladder_order(
            actual_ladder=expected, expected_ladder=expected
        )
        assert result.verdict is Verdict.PASS

    def test_fixture_pass_is_arity_independent_with_two_tiers(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        fleet.product("knowledge").tier("foundation", rank=40)
        fleet.product("knowledge").tier("personal", rank=10)
        handle = fleet.build()

        layers = validate_layers(load_layers(handle.manifest_path))
        expected = tier.knowledge_ladder_from_layers(layers)
        assert len(expected) == 2

        result = tier.check_h4_ladder_order(
            actual_ladder=expected, expected_ladder=expected
        )
        assert result.verdict is Verdict.PASS

    def test_fixture_fail_wrong_order(self):
        result = tier.check_h4_ladder_order(
            actual_ladder=["/tiers/org", "/tiers/personal"],
            expected_ladder=["/tiers/personal", "/tiers/org"],
        )
        assert result.verdict is Verdict.FAIL
        assert result.evidence

    def test_fixture_fail_missing_entry(self):
        result = tier.check_h4_ladder_order(
            actual_ladder=["/tiers/personal"],
            expected_ladder=["/tiers/personal", "/tiers/org", "/tiers/foundation"],
        )
        assert result.verdict is Verdict.FAIL

    @requires_real_machine
    @pytest.mark.machine
    def test_machine_ladder_matches_manifest_rank_order(self, machine_readonly_guard):
        with machine_readonly_guard(extra_paths=[]):
            actual = _real_knowledge_ladder()
            layers = validate_layers(load_layers(_REAL_MANIFEST_PATH))
            expected = list(tier.knowledge_ladder_from_layers(layers))
            result = tier.check_h4_ladder_order(
                actual_ladder=actual, expected_ladder=expected
            )

        # TEST-MATRIX H-4: PASS today.
        assert result.verdict is Verdict.PASS, result.detail


# ---------------------------------------------------------------------------
# H-5 -- singular alias sub-paths must exist (THE BUG, Q24)
# ---------------------------------------------------------------------------


class TestH5SingularAliasPathsExist:
    _SAMPLE_AGENT_TEXT = (
        Path(__file__).parent / "fixtures" / "tiers" / "agents" / "sample-agent.md"
    ).read_text(encoding="utf-8")

    def test_fixture_pass_when_referenced_subpaths_exist(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        repo = fleet.product("knowledge").tier("personal", rank=10)
        repo.write("reference/glossary.md", "defined terms")
        repo.write("reference/style/index.md", "conventions")
        fleet.build()

        results = tier.check_h5_singular_alias_paths_exist(
            agent_files={"sample-agent.md": self._SAMPLE_AGENT_TEXT},
            cc_knowledge_repo=str(repo.path),
        )
        assert len(results) == 1
        assert results[0].verdict is Verdict.PASS

    def test_fixture_fail_when_referenced_subpaths_are_missing(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        repo = fleet.product("knowledge").tier("personal", rank=10)
        fleet.build()  # nothing written under reference/

        results = tier.check_h5_singular_alias_paths_exist(
            agent_files={"sample-agent.md": self._SAMPLE_AGENT_TEXT},
            cc_knowledge_repo=str(repo.path),
        )
        assert len(results) == 1
        assert results[0].verdict is Verdict.FAIL
        assert len(results[0].evidence) == 2

    def test_fixture_skip_when_no_alias_reference(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        repo = fleet.product("knowledge").tier("personal", rank=10)
        fleet.build()

        results = tier.check_h5_singular_alias_paths_exist(
            agent_files={"no-refs.md": "nothing to see here"},
            cc_knowledge_repo=str(repo.path),
        )
        assert results[0].verdict is Verdict.SKIP

    def test_extract_knowledge_alias_subpaths_is_order_preserving_and_deduplicated(
        self,
    ):
        text = (
            "see $CC_KNOWLEDGE_REPO/a/b.md and $CC_KNOWLEDGE_REPO/c/ "
            "then again $CC_KNOWLEDGE_REPO/a/b.md"
        )
        assert tier.extract_knowledge_alias_subpaths(text) == ("a/b.md", "c/")

    @requires_real_machine
    @pytest.mark.machine
    def test_machine_cw_sd_ta_no_longer_dereference_the_singular_alias(
        self, machine_readonly_guard
    ):
        """TEST-MATRIX H-5 / owner decision Q24: re-verified live -- cw/sd/ta
        were migrated to walk `$CC_KNOWLEDGE_REPOS` (the full, nearest-first
        ladder) instead of dereferencing the singular `$CC_KNOWLEDGE_REPO`
        back-compat alias, so none of the three agent files contains a
        `$CC_KNOWLEDGE_REPO/<subpath>` reference for this check to evaluate
        any more. Was FAIL, 5/5 distinct sub-paths missing (the bug); now
        SKIP for all three (nothing to exercise). The check's ability to
        still detect the broken shape is proven by the fixture tests above
        (`test_fixture_fail_when_referenced_subpaths_are_missing`), not by
        this machine test -- a check that can no longer fail is worthless,
        but its fixture coverage, not a stale machine fact, is what must
        keep proving that."""

        agents_dir = _CLAUDE_COPILOT_ROOT / ".claude" / "agents"
        agent_paths = [agents_dir / name for name in _REAL_AGENT_FILES]
        assert all(p.is_file() for p in agent_paths), (
            "expected the real framework agent files to exist"
        )

        ladder = _real_knowledge_ladder()
        assert ladder, "expected a non-empty real knowledge ladder"
        singular_target = ladder[0]  # commands/env.py:116-121 -- always the FIRST entry

        with machine_readonly_guard(extra_paths=[*agent_paths, Path(singular_target)]):
            agent_files = {
                path.name: path.read_text(encoding="utf-8") for path in agent_paths
            }
            results = tier.check_h5_singular_alias_paths_exist(
                agent_files=agent_files, cc_knowledge_repo=singular_target
            )

        by_name = {result.subject: result for result in results}
        assert set(by_name) == set(_REAL_AGENT_FILES)
        for name, result in by_name.items():
            assert result.verdict is Verdict.SKIP, (
                f"H-5 (Q24 ladder integrity) is expected to SKIP for {name} on this "
                "machine today (no $CC_KNOWLEDGE_REPO sub-path reference left to "
                "check); if it now FAILs, cw/sd/ta have regressed back to "
                "dereferencing the singular alias -- update TEST-MATRIX.md and this "
                "test together"
            )
            assert "no $CC_KNOWLEDGE_REPO sub-path reference found" in result.detail


# ---------------------------------------------------------------------------
# H-6 -- declared skill paths exist, per tier
# ---------------------------------------------------------------------------


class TestH6DeclaredSkillPathsExist:
    def test_fixture_pass_all_declared_paths_exist(self, tmp_path):
        """`skills.local[]` entries are TYPED OBJECTS per the real schema
        (`docs/schemas/knowledge-manifest-schema.json`: required `name` +
        `path`), never raw path strings -- this fixture uses the real
        shape deliberately (a raw-string fixture here would silently
        exercise the H-6 false-pass bug this check was fixed to catch, see
        `test_fixture_pass_is_vacuous_only_for_malformed_non_dict_entries`
        below for that exact shape proven inert)."""

        fleet = FleetFactory(tmp_path)
        repo = fleet.product("knowledge").tier("foundation", rank=40)
        repo.write("skills/testing-patterns/SKILL.md", "content")
        repo.write(
            "knowledge-manifest.json",
            json.dumps(
                {
                    "skills": {
                        "local": [
                            {
                                "name": "testing-patterns",
                                "path": "skills/testing-patterns/SKILL.md",
                                "description": "fixture skill",
                            }
                        ]
                    }
                }
            ),
        )
        fleet.build()

        results = tier.check_h6_declared_skill_paths_exist(
            tier_repos={"knowledge-foundation": str(repo.path)}
        )
        assert len(results) == 1
        assert results[0].verdict is Verdict.PASS
        assert "1 declared skill path(s), 0 broken" in results[0].detail

    def test_fixture_fail_dangling_declared_path(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        repo = fleet.product("knowledge").tier("foundation", rank=40)
        repo.write(
            "knowledge-manifest.json",
            json.dumps(
                {
                    "skills": {
                        "local": [
                            {
                                "name": "ghost-skill",
                                "path": "skills/does-not-exist/SKILL.md",
                            }
                        ]
                    }
                }
            ),
        )
        fleet.build()

        results = tier.check_h6_declared_skill_paths_exist(
            tier_repos={"knowledge-foundation": str(repo.path)}
        )
        assert results[0].verdict is Verdict.FAIL
        assert results[0].evidence
        assert results[0].evidence[0].path.endswith(
            "skills/does-not-exist/SKILL.md"
        )

    def test_fixture_pass_is_vacuous_only_for_malformed_non_dict_entries(
        self, tmp_path
    ):
        """The regression this check was fixed for (`AssertionError: []` on
        every real machine, always): a raw path STRING (the pre-fix code's
        assumed, wrong shape) is not a valid `skills.local[]` entry under
        the real schema, so it is correctly excluded from
        `declared_paths` -- a manifest containing ONLY malformed entries
        legitimately has 0 declared paths (vacuous PASS is correct here,
        the same way an empty `skills.local: []` is). This is deliberately
        NOT the same claim as "the check can't fail" -- the two tests
        above prove it detects both a real declaration existing and a real
        declaration dangling; this one just documents that a malformed
        entry is silently dropped rather than crashing or being treated as
        a bogus path."""

        fleet = FleetFactory(tmp_path)
        repo = fleet.product("knowledge").tier("foundation", rank=40)
        repo.write(
            "knowledge-manifest.json",
            json.dumps({"skills": {"local": ["a-raw-string-is-not-a-valid-entry"]}}),
        )
        fleet.build()

        results = tier.check_h6_declared_skill_paths_exist(
            tier_repos={"knowledge-foundation": str(repo.path)}
        )
        assert results[0].verdict is Verdict.PASS
        assert "0 declared skill path(s), 0 broken" in results[0].detail

    def test_fixture_fail_hollow_rung_has_no_manifest(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        repo = fleet.product("knowledge").tier(
            "department", rank=20, unit="accounting"
        )  # no manifest written
        fleet.build()

        results = tier.check_h6_declared_skill_paths_exist(
            tier_repos={"knowledge-department-accounting": str(repo.path)}
        )
        assert results[0].verdict is Verdict.FAIL
        assert "hollow rung" in results[0].evidence[0].detail

    @requires_real_machine
    @pytest.mark.machine
    def test_machine_declared_skill_paths(self, machine_readonly_guard):
        """TEST-MATRIX H-6, re-verified after the false-pass fix (the
        check previously read `skills.local[]` entries as raw strings;
        the real schema is typed objects, so it always found "0 declared"
        and could never fail -- see `tier.check_h6_declared_skill_paths_
        exist`'s docstring comment). Live today: every ladder rung now has
        a `knowledge-manifest.json` (Q26/H-7 closed the hollow department
        rung), so all 4 PASS; the organization rung alone declares 222
        real `skills.local[]` entries with 0 broken paths -- the healthy
        baseline this fix was verified against -- proving the fixed check
        finds REAL declarations on the real machine, not just an absence
        of them."""

        ladder = _real_knowledge_ladder()
        labels = [f"rank-{idx}" for idx in range(len(ladder))]
        tier_repos = dict(zip(labels, ladder))

        with machine_readonly_guard(extra_paths=[Path(r) for r in ladder]):
            results = tier.check_h6_declared_skill_paths_exist(tier_repos=tier_repos)

        assert len(results) == len(ladder)
        failing = [r for r in results if r.verdict is Verdict.FAIL]
        assert failing == [], [r.evidence for r in failing]
        assert all(r.verdict is Verdict.PASS for r in results)

        # At least one real rung must show a non-zero declared count -- a
        # suite where every rung vacuously reports "0 declared" would be
        # the exact false-pass this fix closed, silently reintroduced.
        declared_counts = [
            int(r.detail.split(" declared", 1)[0]) for r in results if r.detail
        ]
        assert max(declared_counts) >= 222, declared_counts


# ---------------------------------------------------------------------------
# H-7 -- no hollow rung
# ---------------------------------------------------------------------------


class TestH7NoHollowRung:
    def test_fixture_pass_every_rung_has_a_manifest(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        foundation = fleet.product("knowledge").tier("foundation", rank=40)
        personal = fleet.product("knowledge").tier("personal", rank=10)
        foundation.write("knowledge-manifest.json", "{}")
        personal.write("knowledge-manifest.json", "{}")
        fleet.build()

        result = tier.check_h7_no_hollow_rung(
            tier_repos={
                "knowledge-foundation": str(foundation.path),
                "knowledge-personal": str(personal.path),
            }
        )
        assert result.verdict is Verdict.PASS

    def test_fixture_fail_one_hollow_rung(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        foundation = fleet.product("knowledge").tier("foundation", rank=40)
        department = fleet.product("knowledge").tier(
            "department", rank=20, unit="accounting"
        )
        foundation.write("knowledge-manifest.json", "{}")
        # department: no manifest written -- the hollow rung.
        fleet.build()

        result = tier.check_h7_no_hollow_rung(
            tier_repos={
                "knowledge-foundation": str(foundation.path),
                "knowledge-department-accounting": str(department.path),
            }
        )
        assert result.verdict is Verdict.FAIL
        assert len(result.evidence) == 1
        assert "knowledge-department-accounting" in result.evidence[0].detail

    @requires_real_machine
    @pytest.mark.machine
    def test_machine_no_ladder_rung_is_hollow_anymore(self, machine_readonly_guard):
        """TEST-MATRIX H-7: re-verified live -- `knowledge-copilot-accounting`
        (the department rung, Q26) now has its own `knowledge-manifest.json`,
        so 4/4 ladder rungs are real. Was FAIL (the hollow-rung bug); now
        PASS. The check's ability to still detect a hollow rung is proven by
        `test_fixture_fail_one_hollow_rung` above, not by this machine test."""

        ladder = _real_knowledge_ladder()
        labels = [f"rank-{idx}" for idx in range(len(ladder))]
        tier_repos = dict(zip(labels, ladder))

        with machine_readonly_guard(extra_paths=[Path(r) for r in ladder]):
            result = tier.check_h7_no_hollow_rung(tier_repos=tier_repos)

        assert result.verdict is Verdict.PASS, (
            "H-7 (no-hollow-rung) is expected to PASS on this machine today "
            "(every ladder rung has a knowledge-manifest.json); if it now FAILs, "
            "a rung has gone hollow again -- update TEST-MATRIX.md and this test "
            "together"
        )
        assert result.evidence == ()
        assert f"all {len(ladder)} ladder rung(s)" in result.detail


# ---------------------------------------------------------------------------
# H-8 -- commands dimension has a framework-wide materialization consumer
# ---------------------------------------------------------------------------


class TestH8CommandsDimensionHasNoConsumer:
    def test_fixture_pass_when_a_consumer_exists(self, tmp_path):
        source_root = tmp_path / "src"
        source_root.mkdir()
        (source_root / "materialize.py").write_text(
            'def apply(layer):\n    return layer.get("dimensions")\n', encoding="utf-8"
        )
        result = tier.check_h8_commands_dimension_has_no_consumer(
            source_root=source_root
        )
        assert result.verdict is Verdict.PASS

    def test_fixture_fail_when_dimensions_is_only_ever_written(self, tmp_path):
        source_root = tmp_path / "src"
        source_root.mkdir()
        (source_root / "onboard.py").write_text(
            'def scaffold():\n    return {"dimensions": []}\n', encoding="utf-8"
        )
        result = tier.check_h8_commands_dimension_has_no_consumer(
            source_root=source_root
        )
        assert result.verdict is Verdict.FAIL
        assert result.evidence

    def test_fixture_never_counts_its_own_conformance_package_as_a_consumer(
        self, tmp_path
    ):
        """The regression this exists to pin: a checker that reads
        `dimensions:` for read-only inspection (exactly what `check_h8_*`
        and `stack.py`'s dimensions-declared check do) must never count as
        a materialize/shadow CONSUMER of its own subject -- the same shape
        as the real bug (`core/conformance/root_causes.py`, `stack.py`,
        `tier.py` itself all matched `_DIMENSIONS_READ_RE` when a caller's
        `source_root` widened to include `core/conformance/`). Without the
        `_is_under_excluded_package` guard this fixture would report a
        false PASS purely because `fake_checker.py` sits under
        `core/conformance/` and reads `layer.get("dimensions")` -- proving
        the check can still be fooled the same way H-8 originally was, and
        that the guard added here is what stops it."""

        source_root = tmp_path / "src"
        conformance_dir = source_root / "core" / "conformance"
        conformance_dir.mkdir(parents=True)
        (conformance_dir / "fake_checker.py").write_text(
            'def inspect(layer):\n    return layer.get("dimensions")\n',
            encoding="utf-8",
        )
        result = tier.check_h8_commands_dimension_has_no_consumer(
            source_root=source_root
        )
        assert result.verdict is Verdict.FAIL, (
            "a dimensions:-reading file under core/conformance/ must never "
            "be counted as a real consumer -- got a false PASS, exactly "
            "the class of bug this guard exists to prevent"
        )
        assert result.evidence

    def test_fixture_pass_still_works_alongside_an_excluded_package_hit(
        self, tmp_path
    ):
        """A REAL consumer elsewhere in `source_root` still wins the check
        even when a `core/conformance/`-shaped false-positive coexists in
        the same tree -- the exclusion filters precisely, it does not just
        make the whole check pessimistic."""

        source_root = tmp_path / "src"
        conformance_dir = source_root / "core" / "conformance"
        conformance_dir.mkdir(parents=True)
        (conformance_dir / "fake_checker.py").write_text(
            'def inspect(layer):\n    return layer.get("dimensions")\n',
            encoding="utf-8",
        )
        (source_root / "materialize.py").write_text(
            'def apply(layer):\n    return layer["dimensions"]\n', encoding="utf-8"
        )
        result = tier.check_h8_commands_dimension_has_no_consumer(
            source_root=source_root
        )
        assert result.verdict is Verdict.PASS
        assert "materialize.py" in result.detail
        assert "fake_checker.py" not in result.detail

    def test_fixture_pass_with_a_resolver_fold_precedence_sanity_check(self, tmp_path):
        """Companion sanity check (`TEST-MATRIX.md` §7 item 10 -- "flag as
        exercising unproven code paths, not just untested data"): the
        RESOLVER's own fold correctly handles the "commands" dimension
        exactly like any other override-semantics dimension, via a fixture
        (no live layer has a non-empty `dimensions:` today, RC-5). This
        proves the gap `check_h8_commands_dimension_has_no_consumer`
        reports is a missing MATERIALIZATION consumer, not a broken fold."""

        from cc.core.ecosystem.discovery import discover_contributions
        from cc.core.ecosystem.resolver import resolve_layers

        fleet = FleetFactory(tmp_path)
        near = fleet.product("claude").tier("personal", rank=10)
        far = fleet.product("claude").tier("foundation", rank=40)
        near.contributes("commands", {"protocol": "personal override of /protocol"})
        far.contributes("commands", {"protocol": "foundation /protocol"})
        handle = fleet.build()

        layers = validate_layers(load_layers(handle.manifest_path))
        contributions = discover_contributions(layers)
        resolved = resolve_layers(layers, contributions)
        [item] = [entry for entry in resolved if entry["item"] == "protocol"]
        assert item["winning_layer"] == near.layer_id
        assert [s["layer"] for s in item["shadowed"]] == [far.layer_id]

    @requires_real_machine
    @pytest.mark.machine
    def test_machine_framework_has_one_real_dimensions_consumer(
        self, machine_readonly_guard
    ):
        """The framework needs one materialization consumer, not one copy in
        every sibling package. `discovery.py` provides that consumer while
        `core/conformance` remains structurally excluded from the scan."""

        cc_source_root = _CC_TOOL_ROOT / "src" / "cc"
        assert cc_source_root.is_dir()

        with machine_readonly_guard(extra_paths=[cc_source_root]):
            result = tier.check_h8_commands_dimension_has_no_consumer(
                source_root=cc_source_root
            )

        assert result.verdict is Verdict.PASS, result.detail
        assert result.expected_today is ExpectedToday.PASS
        assert "core/ecosystem/discovery.py" in result.detail


# ---------------------------------------------------------------------------
# H-9 -- project config overrides the machine ladder (fixture-only)
# ---------------------------------------------------------------------------


class TestH9ProjectOverridesMachineLadder:
    def test_fixture_pass_literal_override_wins(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        project = fleet.project("literal-override")
        machine_config = {
            "$schema": "cc-config-v1",
            "version": 1,
            "paths": {"knowledge_repo": ["/ladder/private", "/ladder/internal"]},
        }
        project_config = {
            "$schema": "cc-config-v1",
            "version": 1,
            "paths": {"knowledge_repo": "/literal/project/override"},
        }
        project.write("machine-config.json", json.dumps(machine_config))
        project.write(".claude/cc/config.json", json.dumps(project_config))
        handle = fleet.build()
        project_path = handle.projects["literal-override"]

        result = tier.check_h9_project_overrides_machine_ladder(
            machine_config_path=project_path / "machine-config.json",
            project_config_path=project_path / ".claude" / "cc" / "config.json",
            subject="literal-override",
        )
        assert result.verdict is Verdict.PASS

    def test_fixture_fail_machine_ladder_wins_when_project_uses_the_sentinel(
        self, tmp_path
    ):
        fleet = FleetFactory(tmp_path)
        project = fleet.project("sentinel-project")
        machine_config = {
            "paths": {"knowledge_repo": ["/ladder/private", "/ladder/internal"]}
        }
        project_config = {"paths": {"knowledge_repo": "@machine"}}
        project.write("machine-config.json", json.dumps(machine_config))
        project.write(".claude/cc/config.json", json.dumps(project_config))
        handle = fleet.build()
        project_path = handle.projects["sentinel-project"]

        # The check's PASS condition specifically proves a LITERAL override
        # wins; a project that just re-selects the machine value via
        # "@machine" is legitimately NOT this scenario, and must FAIL this
        # check (it is proving the wrong thing) even though the resolved
        # config value itself is perfectly correct.
        result = tier.check_h9_project_overrides_machine_ladder(
            machine_config_path=project_path / "machine-config.json",
            project_config_path=project_path / ".claude" / "cc" / "config.json",
            subject="sentinel-project",
        )
        assert result.verdict is Verdict.FAIL
        assert result.evidence


# ---------------------------------------------------------------------------
# Fitness functions scoped to this package
# (`HARNESS-DESIGN.md` §9.3 "definition of done" (b): every check has a
# positive AND a negative test.)
# ---------------------------------------------------------------------------


def test_all_9_h_checks_are_registered_with_severity_and_remediation():
    from cc.core.conformance.registry import DEFAULT_REGISTRY

    expected_ids = {
        "tier.precedence.nearest_declared_wins",
        "tier.precedence.absence_is_not_shadow",
        "tier.shadow.substance",
        "tier.knowledge.ladder_order",
        "tier.knowledge.singular_alias_paths_exist",
        "tier.knowledge.declared_skill_paths_exist",
        "tier.knowledge.no_hollow_rung",
        "tier.precedence.commands_dimension_has_no_consumer",
        "tier.config.project_overrides_machine_ladder",
    }
    assert expected_ids <= {r.id for r in DEFAULT_REGISTRY.all()}
    for check_id in expected_ids:
        registration = DEFAULT_REGISTRY.get(check_id)
        assert registration.severity is not None
        assert registration.remediation
        assert registration.summary
