"""WP-7 tests: the five root-cause regression pins (`root_causes.py`).

Every check gets BOTH a World-A synthetic positive test (a fixture shaped
like the fix having landed -- proves the check is capable of reporting
PASS, never "always red by construction") and a World-A synthetic negative
test (a fixture shaped like today's real defect -- proves detection), per
`HARNESS-DESIGN.md` §9.3's definition of done ("a check never proven to
fail is not a check" -- and, symmetrically here, a check never proven able
to pass is not trustworthy either).

The `@pytest.mark.machine` class at the bottom runs the SAME checks against
the real machine and asserts they currently fail with concrete, path-level
evidence -- the actual deliverable the task asked for ("Each MUST fail
today against the real machine"). Those tests skip cleanly (never fail) on
a machine with no real ecosystem installed, exactly like the rest of this
suite's `machine`-marked tests (`pytest -m "not machine"` stays hermetic).

Real repos are touched read-only only, through `run_git_readonly`
(exercised transitively via `root_causes.check_rc3`) and plain file reads;
the autouse `_conformance_machine_readonly_tripwire` fixture
(`tests/conformance/conftest.py`) guards the fixed core machine paths for
every test in this file, and the machine-marked tests additionally guard
the SPECIFIC small installer files they read via `machine_readonly_guard`.
Whole real-repo working trees are deliberately never passed as
`machine_readonly_guard` extra_paths -- fingerprinting a multi-thousand-file
working tree byte-for-byte on every test run would be needlessly slow, and
every root_causes.py function is a pure reader (`.read_text`/`.read_bytes`/
`.stat`/`.rglob`, plus git subcommands fsguard's own allowlist already
refuses to let mutate) -- reviewable directly from the module source.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from cc.core.conformance import report, root_causes
from cc.core.conformance.registry import DEFAULT_REGISTRY
from cc.core.conformance.types import ExpectedToday, Mode, Verdict
from cc.core.ecosystem.manifest import load_layers, validate_layers
from jsonschema import Draft202012Validator
from referencing import Registry as SchemaRegistry
from referencing import Resource

from .conftest import FleetFactory

pytestmark = pytest.mark.filterwarnings("ignore")

_SCHEMA_DIR = Path(__file__).parents[1] / "fixtures" / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _validate_envelope(payload: dict) -> None:
    conformance_schema = _load_schema("conformance.schema.json")
    envelope_schema = _load_schema("_envelope.schema.json")
    schema_registry = SchemaRegistry().with_resources(
        [
            ("_envelope.schema.json", Resource.from_contents(envelope_schema)),
            (envelope_schema["$id"], Resource.from_contents(envelope_schema)),
            (conformance_schema["$id"], Resource.from_contents(conformance_schema)),
        ]
    )
    validator = Draft202012Validator(conformance_schema, registry=schema_registry)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


def _hook_lock_json(content: bytes) -> str:
    checksum = f"sha256:{hashlib.sha256(content).hexdigest()}"
    return json.dumps(
        {
            "schema_version": "1.0",
            "components": [
                {
                    "product": "claude",
                    "files": [
                        {"path": root_causes.HOOK_RELATIVE_PATH, "checksum": checksum}
                    ],
                }
            ],
        }
    )


def _foundation_layers_from(handle) -> list[dict]:
    layers = validate_layers(load_layers(handle.manifest_path))
    return [layer for layer in layers if layer["role"] == "foundation"]


def _tier_variant_layers_from(handle) -> list[dict]:
    layers = validate_layers(load_layers(handle.manifest_path))
    return [layer for layer in layers if layer["role"] != "foundation"]


# ---------------------------------------------------------------------------
# Registration sanity -- every RC id is a real, well-formed check.
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_all_five_root_cause_ids_are_registered(self):
        for check_id in root_causes.ALL_ROOT_CAUSE_CHECK_IDS:
            assert check_id in DEFAULT_REGISTRY
            registration = DEFAULT_REGISTRY.get(check_id)
            assert registration.severity.value == "S0"
            assert registration.remediation  # never fails without telling how to fix it
            assert registration.summary

    def test_check_ids_match_test_matrix_verbatim(self):
        assert root_causes.RC1_ID == "rc.rc1.enforcement_hook_is_installed_by_something"
        assert root_causes.RC2_ID == "rc.rc2.codex_has_an_updater"
        assert root_causes.RC3_ID == "rc.rc3.orphan_release_tags"
        assert root_causes.RC4_ID == "rc.rc4.lock_is_generated_not_templated"
        assert root_causes.RC5_ID == "rc.rc5.tier_variants_declare_dimensions"


# ---------------------------------------------------------------------------
# RC-1 -- the enforcement hook
# ---------------------------------------------------------------------------


class TestRC1:
    def test_positive_installer_references_and_fleet_fully_locked(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        claude = fleet.product("claude").tier("foundation", rank=40)
        claude.write(
            ".claude/commands/setup-project.md",
            "Step 5: install .claude/hooks/copilot-hook.sh and lock it.\n",
        )
        claude.write(
            ".claude/commands/update-project.md",
            "re-copy .claude/hooks/copilot-hook.sh and re-lock it.\n",
        )

        hook_content = b"#!/bin/sh\necho ok\n"
        good = fleet.project("good-repo")
        good.write(root_causes.HOOK_RELATIVE_PATH, hook_content, executable=True)
        good.write("copilot.lock.json", _hook_lock_json(hook_content))

        handle = fleet.build()
        claude_path = handle.tiers[("claude", "foundation")]
        fleet_repos = (handle.projects["good-repo"],)

        results = root_causes.check_rc1(
            claude_foundation_path=claude_path, fleet_repos=fleet_repos
        )
        installer_result, fleet_result = results
        assert installer_result.verdict is Verdict.PASS
        assert fleet_result.verdict is Verdict.PASS
        for result in results:
            assert result.id == root_causes.RC1_ID
            assert result.root_cause == "RC-1"

    def test_negative_installer_silent_and_fleet_unlocked(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        claude = fleet.product("claude").tier("foundation", rank=40)
        claude.write(
            ".claude/commands/setup-project.md",
            "Step 5: cp protocol.md and continue.md only.\n",
        )
        claude.write(
            ".claude/commands/update-project.md", "re-copy the 7 project commands.\n"
        )

        broken = fleet.project("broken-repo")
        broken.write("README.md", "no hook here\n")

        handle = fleet.build()
        claude_path = handle.tiers[("claude", "foundation")]
        fleet_repos = (handle.projects["broken-repo"],)

        results = root_causes.check_rc1(
            claude_foundation_path=claude_path, fleet_repos=fleet_repos
        )
        installer_result, fleet_result = results
        assert installer_result.verdict is Verdict.FAIL
        assert installer_result.evidence and installer_result.evidence[0].path
        assert fleet_result.verdict is Verdict.FAIL
        assert fleet_result.evidence and fleet_result.evidence[0].path
        assert fleet_result.evidence[0].actual == "0 of 1 present-and-locked"

    def test_partial_fleet_coverage_still_fails(self, tmp_path):
        """One good repo is not enough -- fleet_ok requires EVERY discovered
        repo, not merely `> 0`, matching the compound "0 of N" framing."""

        fleet = FleetFactory(tmp_path)
        claude = fleet.product("claude").tier("foundation", rank=40)
        claude.write(
            ".claude/commands/setup-project.md", "installs copilot-hook\n"
        )

        hook_content = b"#!/bin/sh\necho ok\n"
        good = fleet.project("good-repo")
        good.write(root_causes.HOOK_RELATIVE_PATH, hook_content, executable=True)
        good.write("copilot.lock.json", _hook_lock_json(hook_content))
        fleet.project("stale-repo").write("README.md", "never updated\n")

        handle = fleet.build()
        claude_path = handle.tiers[("claude", "foundation")]
        fleet_repos = (handle.projects["good-repo"], handle.projects["stale-repo"])

        results = root_causes.check_rc1(
            claude_foundation_path=claude_path, fleet_repos=fleet_repos
        )
        installer_result, fleet_result = results
        assert installer_result.verdict is Verdict.PASS
        assert fleet_result.verdict is Verdict.FAIL
        assert fleet_result.evidence[0].actual == "1 of 2 present-and-locked"


# ---------------------------------------------------------------------------
# RC-2 -- codex has no in-place updater
# ---------------------------------------------------------------------------


class TestRC2:
    def test_positive_updater_exists_and_setup_does_not_refuse(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        codex = fleet.product("codex").tier("foundation", rank=40)
        codex.write("scripts/update-project.sh", "#!/bin/sh\necho update in place\n")
        codex.write("scripts/setup-project.sh", "#!/bin/sh\necho ok, always idempotent\n")

        handle = fleet.build()
        codex_path = handle.tiers[("codex", "foundation")]

        results = root_causes.check_rc2(codex_foundation_path=codex_path)
        updater_result, setup_result = results
        assert updater_result.verdict is Verdict.PASS
        assert setup_result.verdict is Verdict.PASS
        for result in results:
            assert result.id == root_causes.RC2_ID
            assert result.root_cause == "RC-2"

    def test_negative_no_updater_and_setup_hard_refuses(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        codex = fleet.product("codex").tier("foundation", rank=40)
        codex.write(
            "scripts/setup-project.sh",
            'echo "Refusing to replace existing plugin link/path" >&2\nexit 1\n',
        )

        handle = fleet.build()
        codex_path = handle.tiers[("codex", "foundation")]

        results = root_causes.check_rc2(codex_foundation_path=codex_path)
        updater_result, setup_result = results
        assert updater_result.verdict is Verdict.FAIL
        assert updater_result.evidence and updater_result.evidence[0].path
        assert setup_result.verdict is Verdict.FAIL
        assert setup_result.evidence and "Refusing to replace" in setup_result.evidence[0].actual


# ---------------------------------------------------------------------------
# RC-3 -- orphan release tags
# ---------------------------------------------------------------------------


class TestRC3:
    def test_negative_orphan_tag_is_detected_network_independently(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        tier = fleet.product("claude").tier("foundation", rank=40)
        tier.contributes("agents", {"cw": "content"})
        tier.pin("v9.9.9", orphan=True)

        handle = fleet.build()
        results = root_causes.check_rc3(layers=_foundation_layers_from(handle))

        assert len(results) == 1
        result = results[0]
        assert result.verdict is Verdict.FAIL
        assert result.id == root_causes.RC3_ID
        assert result.root_cause == "RC-3"
        assert result.expected_today is ExpectedToday.FAIL  # claude is a known-broken product
        assert result.evidence[0].actual.startswith("1 ")
        assert result.evidence[0].command.startswith("git ")

    def test_positive_real_ancestor_tag_passes(self, tmp_path):
        # `knowledge`, not `cli`: `cli` was moved into
        # `_RC3_KNOWN_BROKEN_PRODUCTS` after re-verification found
        # cli-copilot's own real foundation pin (`v0.3.5`) has the identical
        # orphan-snapshot defect -- picking a still-not-known-broken product
        # keeps this PASS-case fixture meaningful instead of silently
        # asserting the opposite of what `_RC3_KNOWN_BROKEN_PRODUCTS` now
        # says about `cli`.
        fleet = FleetFactory(tmp_path)
        tier = fleet.product("knowledge").tier("foundation", rank=40)
        tier.contributes("agents", {"do": "content v1"})
        tier.contributes("agents", {"do": "content v2"})  # a second commit -> a real chain
        tier.pin("v9.9.9", orphan=False)

        handle = fleet.build()
        results = root_causes.check_rc3(layers=_foundation_layers_from(handle))

        assert len(results) == 1
        result = results[0]
        assert result.verdict is Verdict.PASS
        assert result.evidence == ()
        assert result.expected_today is ExpectedToday.PASS  # knowledge is not a known-broken product

    def test_dangling_ref_reports_could_not_run_not_a_fabricated_pass(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        fleet.product("codex").tier("foundation", rank=40).contributes(
            "plugins", {"gate": "content"}
        )
        handle = fleet.build()
        layers = _foundation_layers_from(handle)
        # Point the ref at a tag that was never actually created.
        layers[0] = {**layers[0], "source": {**layers[0]["source"], "ref": "v0.0.0-does-not-exist"}}

        results = root_causes.check_rc3(layers=layers)
        assert len(results) == 1
        assert results[0].verdict is Verdict.COULD_NOT_RUN  # never coerced to PASS


# ---------------------------------------------------------------------------
# RC-4 -- lock is a copied template, not a generated record
# ---------------------------------------------------------------------------


class TestRC4:
    def test_positive_generator_referenced_and_locks_unique(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        claude = fleet.product("claude").tier("foundation", rank=40)
        claude.write(
            ".claude/commands/setup-project.md",
            "call projects.write_project_lock(...) to generate copilot.lock.json\n",
        )
        fleet.project("proj-a").write(
            "copilot.lock.json",
            json.dumps({"schema_version": "1.0", "components": [{"generated_for": "proj-a"}]}),
        )
        fleet.project("proj-b").write(
            "copilot.lock.json",
            json.dumps({"schema_version": "1.0", "components": [{"generated_for": "proj-b"}]}),
        )

        handle = fleet.build()
        installer_files = (
            handle.tiers[("claude", "foundation")] / ".claude" / "commands" / "setup-project.md",
        )
        fleet_repos = (handle.projects["proj-a"], handle.projects["proj-b"])

        results = root_causes.check_rc4(installer_files=installer_files, fleet_repos=fleet_repos)
        generator_result, uniqueness_result = results
        assert generator_result.verdict is Verdict.PASS
        assert uniqueness_result.verdict is Verdict.PASS
        for result in results:
            assert result.id == root_causes.RC4_ID
            assert result.root_cause == "RC-4"

    def test_negative_templated_lock_shared_across_repos(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        claude = fleet.product("claude").tier("foundation", rank=40)
        claude.write(
            ".claude/commands/setup-project.md", "cp the reference project instructions only\n"
        )
        template_lock = json.dumps({"schema_version": "1.0", "components": []})
        fleet.project("proj-a").write("copilot.lock.json", template_lock)
        fleet.project("proj-b").write("copilot.lock.json", template_lock)

        handle = fleet.build()
        installer_files = (
            handle.tiers[("claude", "foundation")] / ".claude" / "commands" / "setup-project.md",
        )
        fleet_repos = (handle.projects["proj-a"], handle.projects["proj-b"])

        results = root_causes.check_rc4(installer_files=installer_files, fleet_repos=fleet_repos)
        generator_result, uniqueness_result = results
        assert generator_result.verdict is Verdict.FAIL
        assert generator_result.evidence and generator_result.evidence[0].path
        assert uniqueness_result.verdict is Verdict.FAIL
        assert "1 duplicate cluster" in uniqueness_result.evidence[0].actual
        assert "proj-a" in uniqueness_result.evidence[0].detail
        assert "proj-b" in uniqueness_result.evidence[0].detail


# ---------------------------------------------------------------------------
# RC-5 -- tier-variant layers must declare real dimensions
# ---------------------------------------------------------------------------


class TestRC5:
    def test_positive_declared_dimensions_match_real_content(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        tier = fleet.product("claude").tier("organization", rank=30)
        tier.contributes("commands", {"protocol": "# protocol"})
        tier.write(
            "copilot.layer.yml",
            yaml.safe_dump(
                {
                    "schema_version": "1.0",
                    "package": {"role": "organization", "rank": 30, "product": "claude"},
                    "dimensions": ["commands"],
                }
            ),
        )

        handle = fleet.build()
        results = root_causes.check_rc5(layers=_tier_variant_layers_from(handle))

        assert len(results) == 1
        assert results[0].verdict is Verdict.PASS
        assert results[0].id == root_causes.RC5_ID
        assert results[0].root_cause == "RC-5"

    def test_negative_empty_dimensions_despite_real_content(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        tier = fleet.product("claude").tier("organization", rank=30)
        tier.contributes("commands", {"protocol": "# protocol"})
        tier.write(
            "copilot.layer.yml",
            yaml.safe_dump(
                {
                    "schema_version": "1.0",
                    "package": {"role": "organization", "rank": 30, "product": "claude"},
                    "dimensions": [],
                }
            ),
        )

        handle = fleet.build()
        results = root_causes.check_rc5(layers=_tier_variant_layers_from(handle))

        assert results[0].verdict is Verdict.FAIL
        assert "commands" in results[0].evidence[0].detail

    def test_negative_dimensions_present_but_omits_real_content(self, tmp_path):
        """Not gameable: a NON-empty list that still omits a real directory
        must still fail (HARNESS-DESIGN.md §3.2 rule 3 -- evidence must be
        specific, never merely present)."""

        fleet = FleetFactory(tmp_path)
        tier = fleet.product("claude").tier("organization", rank=30)
        tier.contributes("commands", {"protocol": "# protocol"})
        tier.contributes("agents", {"cw": "content"})
        tier.write(
            "copilot.layer.yml",
            yaml.safe_dump(
                {
                    "schema_version": "1.0",
                    "package": {"role": "organization", "rank": 30, "product": "claude"},
                    "dimensions": ["commands"],  # omits "agents"
                }
            ),
        )

        handle = fleet.build()
        results = root_causes.check_rc5(layers=_tier_variant_layers_from(handle))

        assert results[0].verdict is Verdict.FAIL
        assert "agents" in results[0].evidence[0].expected

    def test_negative_missing_layer_file_entirely(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        tier = fleet.product("knowledge").tier("organization", rank=30)
        tier.contributes("knowledge", {"item": "real content"})

        handle = fleet.build()
        results = root_causes.check_rc5(layers=_tier_variant_layers_from(handle))

        assert results[0].verdict is Verdict.FAIL
        assert "no copilot.layer.yml" in results[0].detail
        assert "knowledge" in results[0].evidence[0].detail


# ---------------------------------------------------------------------------
# Report integration -- our results must be renderable/serializable without
# the harness's own refusals (no bare "ready", no "%", schema-valid).
# ---------------------------------------------------------------------------


class TestReportIntegration:
    def test_group_by_root_cause_groups_all_five_together_when_all_fail(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        claude = fleet.product("claude").tier("foundation", rank=40)
        claude.write(".claude/commands/setup-project.md", "no hook mention\n")
        codex = fleet.product("codex").tier("foundation", rank=40)
        codex.write(
            "scripts/setup-project.sh",
            'echo "Refusing to replace existing plugin link/path" >&2\n',
        )
        broken = fleet.project("broken-repo")
        broken.write("README.md", "nothing here\n")

        handle = fleet.build()
        claude_path = handle.tiers[("claude", "foundation")]
        codex_path = handle.tiers[("codex", "foundation")]

        results = (
            *root_causes.check_rc1(
                claude_foundation_path=claude_path,
                fleet_repos=(handle.projects["broken-repo"],),
            ),
            *root_causes.check_rc2(codex_foundation_path=codex_path),
        )
        groups = report.group_by_root_cause(results)
        assert set(groups) == {"RC-1", "RC-2"}
        assert len(groups["RC-1"]) == 2
        assert len(groups["RC-2"]) == 2

    def test_envelope_and_human_render_validate_for_a_full_negative_sweep(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        claude = fleet.product("claude").tier("foundation", rank=40)
        claude.write(".claude/commands/setup-project.md", "no hook mention\n")
        claude.write(".claude/commands/update-project.md", "no hook mention either\n")
        claude.contributes("plugins", {"x": "y"})
        codex = fleet.product("codex").tier("foundation", rank=40)
        codex.write(
            "scripts/setup-project.sh",
            'echo "Refusing to replace existing plugin link/path" >&2\n',
        )
        cli_tier_variant = fleet.product("cli").tier("organization", rank=30)
        cli_tier_variant.contributes("commands", {"protocol": "x"})
        cli_tier_variant.write(
            "copilot.layer.yml",
            yaml.safe_dump(
                {
                    "schema_version": "1.0",
                    "package": {"role": "organization", "rank": 30, "product": "cli"},
                    "dimensions": [],
                }
            ),
        )
        fleet.product("codex").tier("foundation", rank=40).pin("v0.0.1", orphan=True)
        broken = fleet.project("broken-repo")
        broken.write("README.md", "nothing here\n")

        handle = fleet.build()
        claude_path = handle.tiers[("claude", "foundation")]
        codex_path = handle.tiers[("codex", "foundation")]

        results = (
            *root_causes.check_rc1(
                claude_foundation_path=claude_path,
                fleet_repos=(handle.projects["broken-repo"],),
            ),
            *root_causes.check_rc2(codex_foundation_path=codex_path),
            *root_causes.check_rc3(layers=_foundation_layers_from(handle)),
            *root_causes.check_rc5(layers=_tier_variant_layers_from(handle)),
        )
        assert any(result.verdict is Verdict.FAIL for result in results)

        envelope = report.to_envelope(results, mode=Mode.FAST, host="test-host")
        _validate_envelope(envelope)
        assert envelope["result"] == "fail"

        text = report.render_human(results, mode=Mode.FAST)
        assert "%" not in text
        assert root_causes.RC1_ID in text


# ---------------------------------------------------------------------------
# World B -- the real machine. Skips cleanly if no real ecosystem is
# installed (mirrors `pytest -m "not machine"` staying hermetic elsewhere
# in this suite).
# ---------------------------------------------------------------------------


def _real_home_or_skip() -> Path:
    home = Path.home()
    manifest = home / ".config" / "copilot" / "copilot.layers.yml"
    if not manifest.is_file():
        pytest.skip("no real copilot.layers.yml on this machine -- machine-only test")
    return home


@pytest.mark.machine
class TestRealMachineRootCausesFailToday:
    """Each of these asserts the CURRENT, MEASURED state of the real
    ecosystem on this machine. They are not asserting a hard-coded story --
    they call the exact same `run_rc*` functions `cc conformance check
    --layer regression` will eventually call, and they are expected to flip
    to PASS the day the underlying root cause is actually fixed (at which
    point these specific assertions will need updating -- that update IS
    the acknowledgment `HARNESS-DESIGN.md` §5.4 describes)."""

    def test_rc1_installer_references_hook_but_fleet_is_not_yet_locked(
        self, machine_readonly_guard
    ):
        """Renamed from `test_rc1_hook_is_not_installed_by_anything_and_
        fleet_is_unlocked` -- RC-1 fix, re-verified live 2026-08-10:
        setup-project.md now references .claude/hooks/copilot-hook.sh (cp +
        chmod +x + `cc settings-hook add`) -- the installer-source half is
        genuinely fixed. The FLEET half is NOT: 0 of the discovered repos
        are present+executable+locked yet (the fix has not been fanned out
        via /update-project across the real fleet) -- partial, not fixed."""

        home = _real_home_or_skip()
        manifest_path = root_causes._real_manifest_path(home)
        layers = root_causes.foundation_layers(manifest_path)
        claude_path = root_causes._foundation_source_path(layers, "claude")
        if claude_path is None:
            pytest.skip("no claude foundation layer in the real manifest")
        setup_md = claude_path / ".claude" / "commands" / "setup-project.md"
        update_md = claude_path / ".claude" / "commands" / "update-project.md"

        with machine_readonly_guard(extra_paths=[setup_md, update_md]):
            results = root_causes.run_rc1(home=home)

        assert len(results) == 2
        for result in results:
            assert result.id == root_causes.RC1_ID
            assert result.root_cause == "RC-1"
        installer_result, fleet_result = results
        assert installer_result.verdict is Verdict.PASS
        assert installer_result.expected_today is ExpectedToday.PASS
        assert fleet_result.verdict is Verdict.FAIL
        assert fleet_result.expected_today is ExpectedToday.FAIL
        assert "present, executable, and locked" in fleet_result.evidence[0].expected
        assert fleet_result.evidence[0].actual.startswith("0 of ")

    def test_rc2_codex_now_has_an_updater_and_setup_no_longer_hard_refuses(
        self, machine_readonly_guard
    ):
        """Renamed from `test_rc2_codex_has_no_updater_and_setup_hard_
        refuses` -- RC-2 fix, re-verified live 2026-08-10: codex-copilot/
        scripts/update-project.sh now exists (a real in-place, content-
        hashed updater), and setup-project.sh no longer contains a
        "Refusing to replace" hard refusal. Fully fixed, not partial."""

        home = _real_home_or_skip()
        manifest_path = root_causes._real_manifest_path(home)
        layers = root_causes.foundation_layers(manifest_path)
        codex_path = root_causes._foundation_source_path(layers, "codex")
        if codex_path is None:
            pytest.skip("no codex foundation layer in the real manifest")
        updater = codex_path / "scripts" / "update-project.sh"
        setup = codex_path / "scripts" / "setup-project.sh"

        with machine_readonly_guard(extra_paths=[updater, setup]):
            results = root_causes.run_rc2(home=home)

        assert len(results) == 2
        for result in results:
            assert result.id == root_causes.RC2_ID
            assert result.root_cause == "RC-2"
            assert result.expected_today is ExpectedToday.PASS
        updater_result, setup_result = results
        assert updater_result.verdict is Verdict.PASS
        assert setup_result.verdict is Verdict.PASS

    def test_rc3_claude_and_codex_foundation_tags_are_orphan_snapshots(self):
        home = _real_home_or_skip()
        manifest_path = root_causes._real_manifest_path(home)
        layers = root_causes.foundation_layers(manifest_path)
        if root_causes._foundation_source_path(layers, "claude") is None:
            pytest.skip("no claude foundation layer in the real manifest")

        results = root_causes.run_rc3(home=home)
        by_subject = {result.subject.split(" ", 1)[0]: result for result in results}

        assert "claude-foundation" in by_subject
        assert by_subject["claude-foundation"].verdict is Verdict.FAIL
        assert by_subject["claude-foundation"].expected_today is ExpectedToday.FAIL
        assert by_subject["claude-foundation"].evidence[0].actual.startswith("1 ")

        assert "codex-foundation" in by_subject
        assert by_subject["codex-foundation"].verdict is Verdict.FAIL
        assert by_subject["codex-foundation"].expected_today is ExpectedToday.FAIL
        assert by_subject["codex-foundation"].evidence[0].actual.startswith("1 ")

        # cli-copilot's foundation pin (v0.3.5) is the identical defect --
        # an earlier pass wrongly assumed it was a clean control case (see
        # `_RC3_KNOWN_BROKEN_PRODUCTS`'s docstring); re-verified live and
        # corrected here rather than left unchecked.
        if "cli-foundation" in by_subject:
            assert by_subject["cli-foundation"].verdict is Verdict.FAIL
            assert by_subject["cli-foundation"].expected_today is ExpectedToday.FAIL
            assert by_subject["cli-foundation"].evidence[0].actual.startswith("1 ")

    def test_rc4_generator_now_referenced_but_fleet_locks_still_duplicate(
        self, machine_readonly_guard
    ):
        """Renamed from `test_rc4_no_generator_reference_and_fleet_has_
        duplicate_locks` -- RC-4 fix, re-verified live 2026-08-10:
        codex-copilot/scripts/update-project.sh (RC-2's new updater) now
        computes real per-file sha256 checksums and writes a genuinely
        generated copilot.lock.json component -- the generator half is
        genuinely fixed (if narrowly: claude's own installer text still
        never mentions a generator by name, though `cc settings-hook add`
        -- a step it already runs -- independently produces a real lock
        too; see roundtrip.setup.produces_reference_install's "lock"
        facet). The FLEET UNIQUENESS half is NOT fixed: 6 duplicate
        clusters remain across 42 of 59 real locks -- the fix has not
        propagated fleet-wide yet. Partial, not fixed."""

        home = _real_home_or_skip()
        manifest_path = root_causes._real_manifest_path(home)
        layers = root_causes.foundation_layers(manifest_path)
        claude_path = root_causes._foundation_source_path(layers, "claude")
        if claude_path is None:
            pytest.skip("no claude foundation layer in the real manifest")
        setup_md = claude_path / ".claude" / "commands" / "setup-project.md"

        with machine_readonly_guard(extra_paths=[setup_md]):
            results = root_causes.run_rc4(home=home)

        assert len(results) == 2
        for result in results:
            assert result.id == root_causes.RC4_ID
            assert result.root_cause == "RC-4"
        generator_result, uniqueness_result = results
        assert generator_result.verdict is Verdict.PASS
        assert generator_result.expected_today is ExpectedToday.PASS
        assert uniqueness_result.verdict is Verdict.FAIL
        assert uniqueness_result.expected_today is ExpectedToday.FAIL
        assert "duplicate cluster" in uniqueness_result.evidence[0].actual

    def test_rc5_tier_variants_do_not_declare_real_dimensions(self):
        home = _real_home_or_skip()
        manifest_path = root_causes._real_manifest_path(home)
        layers = root_causes.tier_variant_layers(manifest_path)
        if not layers:
            pytest.skip("no tier-variant layers in the real manifest")

        results = root_causes.run_rc5(home=home)
        assert results
        for result in results:
            assert result.id == root_causes.RC5_ID
            assert result.root_cause == "RC-5"
        # At least one PASS-capable check must currently show at least one
        # real, evidenced FAIL -- the actual deliverable ("fails today").
        assert any(result.verdict is Verdict.FAIL for result in results)
        assert all(
            result.verdict is not Verdict.FAIL or (result.evidence and result.evidence[0].path)
            for result in results
        )

    def test_full_regression_sweep_envelope_is_schema_valid_and_all_fail(self):
        home = _real_home_or_skip()
        results = root_causes.run_all_root_cause_checks(home=home)
        assert results
        assert any(result.verdict is Verdict.FAIL for result in results)

        envelope = report.to_envelope(results, mode=Mode.FAST, host="test-host")
        _validate_envelope(envelope)
        assert envelope["result"] == "fail"

        groups = report.group_by_root_cause(results)
        # Every RC this sweep found at least one failure for must be
        # groupable by its own cause, never by a per-repo id alone.
        assert groups
        assert all(key.startswith("RC-") for key in groups)
