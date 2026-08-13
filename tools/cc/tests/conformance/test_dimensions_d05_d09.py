"""WP-4b tests: dimensions D5-D9 (`dimensions/d05_ccconfig.py` ...
`dimensions/d09_declaration.py`).

Named distinctly from `test_layer3_dimensions.py` (the shared file
`HARNESS-DESIGN.md` §8/§9 assigns to WP-4, the Layer-3 orchestrator) so this
work package's tests never collide on that path with a sibling package
(WP-4a's D1-D4 or WP-4c's D10-D13) landing in parallel
(`HARNESS-DESIGN.md` §9.1 "Collision control": "no two packages may touch
the same path" -- WP-4c independently reached the identical naming decision
for its own `test_dimensions_wp4c.py`).

Two layers of coverage, matching how this module's own `dimensions/d0*.py`
files are shaped:

  - `TestD0*` classes exercise each module's pure `check_d0N_*(repo, ...)`
    function directly (Rule 2, `HARNESS-DESIGN.md` §3.2: "every check is a
    pure function of inputs") -- fast, precise, one assertion per fixture
    shape.
  - `TestRunContract` exercises each module's `run(context: RepoContext)`
    entry point -- the actual `dimensions/__init__.py` module contract that
    landed (in a sibling package's commits) partway through this package's
    own implementation; every `check_d0N_*` function was written first
    against the DOCUMENTED contract (`HARNESS-DESIGN.md` §9.1) and `run()`
    was added once the real `RepoContext`/`discover_dimension_modules()`
    machinery existed, so this class is the proof the two actually agree.

Every check gets a POSITIVE test (a synthetic repo where it passes) and at
least one NEGATIVE test (a synthetic repo where it fails), per the
package's own definition of done (`HARNESS-DESIGN.md` §9.3: "a check never
proven to fail is not a check").
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cc.core.conformance.classes import ClassificationEntry, RepoClass
from cc.core.conformance.dimensions import RepoContext
from cc.core.conformance.dimensions.d05_ccconfig import (
    check_d05_cc_config_machine_sentinel,
)
from cc.core.conformance.dimensions.d05_ccconfig import run as run_d05
from cc.core.conformance.dimensions.d06_memory import (
    check_d06_memory_entries_committed_db_ignored,
)
from cc.core.conformance.dimensions.d06_memory import run as run_d06
from cc.core.conformance.dimensions.d07_knowledge import (
    check_d07_knowledge_wiring_resolves,
)
from cc.core.conformance.dimensions.d07_knowledge import run as run_d07
from cc.core.conformance.dimensions.d08_tier import check_d08_tier_participation
from cc.core.conformance.dimensions.d08_tier import run as run_d08
from cc.core.conformance.dimensions.d09_declaration import (
    check_d09_portable_declaration,
)
from cc.core.conformance.dimensions.d09_declaration import run as run_d09
from cc.core.conformance.types import Layer, Mode, Scope, Severity, Verdict

from .conftest import git_commit_all, init_git_repo

pytestmark = pytest.mark.filterwarnings("ignore")


def _context(
    repo: Path, *, rubric_class: str, role: str | None = None
) -> RepoContext:
    """Build a real `RepoContext` the same way `sweep.py` would, for a
    given rubric letter -- the shortest path from "class A" to a
    `ClassificationEntry` whose `.rubric_letter` is exactly that letter."""

    if role is not None:
        classification = ClassificationEntry(
            key=repo.name,
            repo_class=RepoClass.COMPONENT,
            rationale="test fixture",
            role=role,
        )
    elif rubric_class == "D":
        classification = ClassificationEntry(
            key=repo.name, repo_class=RepoClass.DOCS_KNOWLEDGE, rationale="test fixture"
        )
    elif rubric_class == "E":
        classification = ClassificationEntry(
            key=repo.name, repo_class=RepoClass.SCRATCH_ARCHIVE, rationale="test fixture"
        )
    else:
        classification = ClassificationEntry(
            key=repo.name, repo_class=RepoClass.PRODUCT, rationale="test fixture"
        )
    assert classification.rubric_letter == rubric_class
    return RepoContext.build(
        repo,
        classification=classification,
        is_git_root=(repo / ".git").exists(),
        mode=Mode.FAST,
    )


def _write(path: Path, relative: str, content: str) -> Path:
    target = path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# D5 -- cc project config
# ---------------------------------------------------------------------------


class TestD05CcConfig:
    def test_pass_when_sentinel_and_tracked(self, tmp_path):
        repo = tmp_path / "repo"
        init_git_repo(repo)
        _write(
            repo,
            ".claude/cc/config.json",
            json.dumps(
                {
                    "$schema": "cc-config-v1",
                    "version": 1,
                    "paths": {"shared_docs": "@machine", "knowledge_repo": "@machine"},
                }
            ),
        )
        git_commit_all(repo, "add cc config")

        result = check_d05_cc_config_machine_sentinel(repo)
        assert result.verdict is Verdict.PASS
        assert result.id == "repo.d05.cc_config_machine_sentinel"
        assert result.layer is Layer.REPO
        assert result.severity is Severity.S1
        assert result.scope is Scope.PER_REPO
        assert result.evidence == ()

    def test_fail_when_config_missing(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        result = check_d05_cc_config_machine_sentinel(repo)
        assert result.verdict is Verdict.FAIL
        assert result.evidence[0].kind == "cc-config-missing"
        assert str(repo) in result.evidence[0].path

    def test_fail_when_json_malformed(self, tmp_path):
        repo = tmp_path / "repo"
        _write(repo, ".claude/cc/config.json", "{not json")
        result = check_d05_cc_config_machine_sentinel(repo)
        assert result.verdict is Verdict.FAIL
        assert result.evidence[0].kind == "cc-config-malformed"

    def test_fail_on_absolute_machine_path(self, tmp_path):
        repo = tmp_path / "repo"
        _write(
            repo,
            ".claude/cc/config.json",
            json.dumps(
                {
                    "$schema": "cc-config-v1",
                    "version": 1,
                    "paths": {
                        "knowledge_repo": "/Volumes/Dev/Sites/COPILOT/knowledge-copilot-internal"
                    },
                }
            ),
        )
        result = check_d05_cc_config_machine_sentinel(repo)
        assert result.verdict is Verdict.FAIL
        kinds = {entry.kind for entry in result.evidence}
        assert "cc-config-absolute-path" in kinds

    def test_fail_when_gitignore_self_excludes_config(self, tmp_path):
        """Reproduces convoco-site's `.gitignore:53` finding: the file is
        present on disk with perfectly healthy content, but a `.gitignore`
        rule means it never reaches a fresh clone."""

        repo = tmp_path / "repo"
        init_git_repo(repo)
        _write(repo, ".gitignore", ".claude/cc/config.json\n")
        git_commit_all(repo, "add gitignore")
        _write(
            repo,
            ".claude/cc/config.json",
            json.dumps(
                {
                    "$schema": "cc-config-v1",
                    "version": 1,
                    "paths": {"knowledge_repo": "@machine"},
                }
            ),
        )
        # deliberately not committed -- it is gitignored, so `git add` would
        # be a silent no-op in real usage; the file simply sits on disk.

        result = check_d05_cc_config_machine_sentinel(repo)
        assert result.verdict is Verdict.FAIL
        kinds = {entry.kind for entry in result.evidence}
        assert "cc-config-gitignore-self-exclusion" in kinds

    def test_pass_when_not_a_git_repo_skips_gitignore_check(self, tmp_path):
        repo = tmp_path / "repo"
        _write(
            repo,
            ".claude/cc/config.json",
            json.dumps(
                {
                    "$schema": "cc-config-v1",
                    "version": 1,
                    "paths": {"knowledge_repo": "@machine"},
                }
            ),
        )
        result = check_d05_cc_config_machine_sentinel(repo)
        assert result.verdict is Verdict.PASS


# ---------------------------------------------------------------------------
# D6 -- memory
# ---------------------------------------------------------------------------


class TestD06Memory:
    def test_pass_when_entries_tracked_and_db_ignored(self, tmp_path):
        repo = tmp_path / "repo"
        init_git_repo(repo)
        _write(repo, ".claude/memory/entries/.gitkeep", "")
        _write(repo, ".claude/memory/entries/one.md", "an entry")
        _write(repo, ".gitignore", ".claude/memory/memory.db\n.claude/memory/memory.db-*\n")
        _write(repo, ".claude/memory/memory.db", "sqlite-ish bytes")
        git_commit_all(repo, "add memory")

        result = check_d06_memory_entries_committed_db_ignored(repo)
        assert result.verdict is Verdict.PASS
        assert result.severity is Severity.S2

    def test_fail_when_entries_dir_absent(self, tmp_path):
        repo = tmp_path / "repo"
        init_git_repo(repo)
        result = check_d06_memory_entries_committed_db_ignored(repo)
        assert result.verdict is Verdict.FAIL
        assert result.evidence[0].kind == "memory-entries-missing"

    def test_fail_when_db_is_tracked(self, tmp_path):
        repo = tmp_path / "repo"
        init_git_repo(repo)
        _write(repo, ".claude/memory/entries/.gitkeep", "")
        _write(repo, ".claude/memory/memory.db", "sqlite-ish bytes")
        git_commit_all(repo, "commit db by mistake")

        result = check_d06_memory_entries_committed_db_ignored(repo)
        assert result.verdict is Verdict.FAIL
        kinds = {entry.kind for entry in result.evidence}
        assert "memory-db-tracked" in kinds

    def test_fail_reproduces_force_readiness_assessment_shape(self, tmp_path):
        """The live defect: a `.gitignore` rule scoped to the whole
        `.claude/memory/` tree (not just `memory.db*`) silently drops
        entries from version control."""

        repo = tmp_path / "repo"
        init_git_repo(repo)
        _write(repo, ".gitignore", "# Agent memory entries (local)\n.claude/memory/\n")
        git_commit_all(repo, "add overly broad gitignore rule")
        _write(repo, ".claude/memory/entries/.gitkeep", "")
        for index in range(3):
            _write(repo, f".claude/memory/entries/entry-{index}.md", "content")
        # None of these are committed -- they're all gitignored by the rule
        # above, exactly like force-readiness-assessment's 48-of-59 shape.

        result = check_d06_memory_entries_committed_db_ignored(repo)
        assert result.verdict is Verdict.FAIL
        kinds = {entry.kind for entry in result.evidence}
        assert "memory-entries-excluded" in kinds
        excluded_evidence = next(
            entry for entry in result.evidence if entry.kind == "memory-entries-excluded"
        )
        assert "4 of 4" in excluded_evidence.actual  # 3 entries + .gitkeep

    def test_could_not_run_when_not_a_git_repo(self, tmp_path):
        repo = tmp_path / "repo"
        _write(repo, ".claude/memory/entries/.gitkeep", "")
        result = check_d06_memory_entries_committed_db_ignored(repo)
        assert result.verdict is Verdict.COULD_NOT_RUN
        assert result.evidence == ()


# ---------------------------------------------------------------------------
# D7 -- knowledge wiring
# ---------------------------------------------------------------------------


class TestD07Knowledge:
    def test_pass_when_config_present_and_no_hardcode(self, tmp_path):
        repo = tmp_path / "repo"
        _write(
            repo,
            ".claude/cc/config.json",
            json.dumps({"paths": {"knowledge_repo": "@machine"}}),
        )
        _write(repo, "CLAUDE.md", "## Claude Copilot\n\nUse $CC_KNOWLEDGE_REPO.\n")

        result = check_d07_knowledge_wiring_resolves(repo)
        assert result.verdict is Verdict.PASS
        assert result.severity is Severity.S1

    def test_fail_when_config_absent(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        result = check_d07_knowledge_wiring_resolves(repo)
        assert result.verdict is Verdict.FAIL
        assert result.evidence[0].kind == "knowledge-repo-config"

    def test_fail_on_hardcoded_claude_md_path(self, tmp_path):
        repo = tmp_path / "repo"
        _write(
            repo,
            ".claude/cc/config.json",
            json.dumps({"paths": {"knowledge_repo": "@machine"}}),
        )
        _write(
            repo,
            "CLAUDE.md",
            "line one\nShared Docs | `/Users/pabs/Sites/COPILOT/shared-docs`\n",
        )
        result = check_d07_knowledge_wiring_resolves(repo)
        assert result.verdict is Verdict.FAIL
        hardcode_evidence = [
            entry
            for entry in result.evidence
            if entry.kind == "knowledge-claude-md-hardcoded-path"
        ]
        assert len(hardcode_evidence) == 1
        assert hardcode_evidence[0].path.endswith("CLAUDE.md:2")

    def test_fail_on_linux_home_path_without_known_username(self, tmp_path):
        repo = tmp_path / "repo"
        _write(
            repo,
            ".claude/cc/config.json",
            json.dumps({"paths": {"knowledge_repo": "@machine"}}),
        )
        _write(
            repo,
            "CLAUDE.md",
            "Shared Docs | `/home/ci-user/work/shared-docs`\n",
        )

        result = check_d07_knowledge_wiring_resolves(repo)

        assert result.verdict is Verdict.FAIL
        assert any(
            entry.kind == "knowledge-claude-md-hardcoded-path"
            for entry in result.evidence
        )

    def test_passes_admin_server_operational_volume_paths(self, tmp_path):
        """D7 is not a general ban on machine-specific operational docs."""

        repo = tmp_path / "admin-server"
        _write(
            repo,
            ".claude/cc/config.json",
            json.dumps({"paths": {"knowledge_repo": "@machine"}}),
        )
        _write(
            repo,
            "CLAUDE.md",
            "\n".join(
                (
                    "/Volumes/DockerApps/scripts/backup/pre-change-backup.sh",
                    "cd /Volumes/DockerApps/stacks/network && docker compose up -d",
                    "- Bind mounts: audiobooks from `/Volumes/Davy Jones/Audiobooks`",
                    "- `/Volumes/Barbossa/` — Backups",
                )
            ),
        )

        result = check_d07_knowledge_wiring_resolves(repo)

        assert result.verdict is Verdict.PASS
        assert not any(
            entry.kind == "knowledge-claude-md-hardcoded-path"
            for entry in result.evidence
        )

    def test_fails_admin_server_hardcoded_knowledge_volume_path(self, tmp_path):
        repo = tmp_path / "admin-server"
        _write(
            repo,
            ".claude/cc/config.json",
            json.dumps({"paths": {"knowledge_repo": "@machine"}}),
        )
        _write(
            repo,
            "CLAUDE.md",
            "Knowledge Copilot: `/Volumes/DockerApps/docs/knowledge-copilot/`\n",
        )

        result = check_d07_knowledge_wiring_resolves(repo)

        assert result.verdict is Verdict.FAIL
        evidence = tuple(
            entry
            for entry in result.evidence
            if entry.kind == "knowledge-claude-md-hardcoded-path"
        )
        assert len(evidence) == 1
        assert evidence[0].actual.startswith("Knowledge Copilot:")

    def test_pass_reproduces_org_manifest_healthy_baseline(self, tmp_path):
        """Mirrors `knowledge-copilot-internal`'s live shape: 2 extensions,
        each requiredSkills entry resolves against skills.local, 0 broken
        paths."""

        repo = tmp_path / "repo"
        _write(
            repo,
            ".claude/cc/config.json",
            json.dumps({"paths": {"knowledge_repo": "@machine"}}),
        )
        _write(repo, ".claude/extensions/sd.override.md", "content")
        _write(repo, "03-skills/moments-mapping/SKILL.md", "content")
        _write(
            repo,
            "knowledge-manifest.json",
            json.dumps(
                {
                    "extensions": [
                        {
                            "agent": "sd",
                            "type": "override",
                            "file": ".claude/extensions/sd.override.md",
                            "requiredSkills": ["moments-mapping"],
                        }
                    ],
                    "skills": {
                        "local": [
                            {
                                "name": "moments-mapping",
                                "path": "03-skills/moments-mapping/SKILL.md",
                            }
                        ]
                    },
                }
            ),
        )

        result = check_d07_knowledge_wiring_resolves(repo)
        assert result.verdict is Verdict.PASS

    def test_fail_reproduces_broken_manifest_paths(self, tmp_path):
        repo = tmp_path / "repo"
        _write(
            repo,
            ".claude/cc/config.json",
            json.dumps({"paths": {"knowledge_repo": "@machine"}}),
        )
        _write(
            repo,
            "knowledge-manifest.json",
            json.dumps(
                {
                    "extensions": [
                        {
                            "agent": "ind",
                            "type": "extension",
                            "file": ".claude/extensions/ind.extension.md",  # missing on disk
                            "requiredSkills": ["design-honesty-evaluation"],  # not in skills.local
                        }
                    ],
                    "skills": {"local": []},
                }
            ),
        )

        result = check_d07_knowledge_wiring_resolves(repo)
        assert result.verdict is Verdict.FAIL
        kinds = {entry.kind for entry in result.evidence}
        assert "knowledge-manifest-broken-extension-file" in kinds
        assert "knowledge-manifest-unresolved-required-skill" in kinds

    def test_pass_when_manifest_absent_is_not_evaluated(self, tmp_path):
        """A repo with no `knowledge-manifest.json` at all (e.g. a plain
        consumer repo) is not itself a knowledge-tier contributor -- D7
        must not fabricate a manifest failure for it (that gap, if any, is
        H-6/H-7's Layer-1 territory, not this dimension)."""

        repo = tmp_path / "repo"
        _write(
            repo,
            ".claude/cc/config.json",
            json.dumps({"paths": {"knowledge_repo": "@machine"}}),
        )
        result = check_d07_knowledge_wiring_resolves(repo)
        assert result.verdict is Verdict.PASS


# ---------------------------------------------------------------------------
# D8 -- tier participation
# ---------------------------------------------------------------------------


def _write_manifest(path: Path, layers: list[dict]) -> Path:
    import yaml

    path.write_text(yaml.safe_dump({"version": 1, "layers": layers}), encoding="utf-8")
    return path


class TestD08TierParticipation:
    def test_skip_for_consumer_class(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        manifest = _write_manifest(tmp_path / "copilot.layers.yml", [])

        result = check_d08_tier_participation(
            repo, repo_class="C", manifest_path=manifest
        )
        assert result.verdict is Verdict.SKIP
        assert "N/A" in result.detail
        assert result.evidence == ()

    def test_pass_for_class_b_with_complete_layer_entry(self, tmp_path):
        repo = tmp_path / "cli-copilot-internal"
        repo.mkdir()
        manifest = _write_manifest(
            tmp_path / "copilot.layers.yml",
            [
                {
                    "id": "cli-organization",
                    "role": "organization",
                    "rank": 30,
                    "product": "cli",
                    "source": {"repo": "git@github-work:org/cli-copilot-internal.git", "path": str(repo), "ref": "main"},
                    "auth": "work",
                    "activation": "always",
                }
            ],
        )

        result = check_d08_tier_participation(
            repo, repo_class="B", manifest_path=manifest
        )
        assert result.verdict is Verdict.PASS

    def test_fail_for_class_a_with_no_layer_entry(self, tmp_path):
        repo = tmp_path / "claude-copilot"
        repo.mkdir()
        other_repo = tmp_path / "codex-copilot"
        other_repo.mkdir()
        # A non-empty manifest that simply has no entry for `repo` --
        # `validate_layers` requires at least one layer, and an empty list
        # would raise `ManifestError` before this check's own ABSENT logic
        # is ever reached.
        manifest = _write_manifest(
            tmp_path / "copilot.layers.yml",
            [
                {
                    "id": "codex-foundation",
                    "role": "foundation",
                    "rank": 40,
                    "product": "codex",
                    "source": {"repo": "git@github.com:org/codex-copilot.git", "path": str(other_repo), "ref": "v0.6.2"},
                    "auth": "work",
                    "activation": "always",
                    "policy": {"allowed_signers": ["did:key:abc"]},
                }
            ],
        )

        result = check_d08_tier_participation(
            repo, repo_class="A", manifest_path=manifest
        )
        assert result.verdict is Verdict.FAIL
        assert result.evidence[0].kind == "tier-layer-entry"

    def test_fail_for_foundation_layer_with_empty_allowed_signers(self, tmp_path):
        repo = tmp_path / "claude-copilot"
        repo.mkdir()
        manifest = _write_manifest(
            tmp_path / "copilot.layers.yml",
            [
                {
                    "id": "claude-foundation",
                    "role": "foundation",
                    "rank": 40,
                    "product": "claude",
                    "source": {"repo": "git@github.com:org/claude-copilot.git", "path": str(repo), "ref": "v5.13.62"},
                    "auth": "work",
                    "activation": "always",
                    "policy": {"allowed_signers": []},
                }
            ],
        )

        result = check_d08_tier_participation(
            repo, repo_class="A", manifest_path=manifest
        )
        assert result.verdict is Verdict.FAIL
        kinds = {entry.kind for entry in result.evidence}
        assert "tier-layer-foundation-signers" in kinds

    def test_could_not_run_on_malformed_manifest(self, tmp_path):
        repo = tmp_path / "claude-copilot"
        repo.mkdir()
        manifest = tmp_path / "copilot.layers.yml"
        manifest.write_text("not: [valid, yaml, :::", encoding="utf-8")

        result = check_d08_tier_participation(
            repo, repo_class="A", manifest_path=manifest
        )
        assert result.verdict is Verdict.COULD_NOT_RUN


# ---------------------------------------------------------------------------
# D9 -- portable declaration
# ---------------------------------------------------------------------------


class TestD09PortableDeclaration:
    def test_pass_when_declared_components_are_installed(self, tmp_path):
        repo = tmp_path / "repo"
        _write(repo, ".claude/agents/cw.md", "content")
        _write(repo, "plugins/codex-copilot/.codex-plugin/plugin.json", "{}")
        _write(
            repo,
            "copilot.project.json",
            json.dumps({"schema_version": "1.0", "components": ["claude", "codex"]}),
        )
        result = check_d09_portable_declaration(repo)
        assert result.verdict is Verdict.PASS
        assert result.severity is Severity.S2

    def test_fail_when_declaration_missing(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        result = check_d09_portable_declaration(repo)
        assert result.verdict is Verdict.FAIL
        assert result.evidence[0].kind == "declaration-missing"

    def test_fail_on_wrong_schema_version(self, tmp_path):
        repo = tmp_path / "repo"
        _write(
            repo,
            "copilot.project.json",
            json.dumps({"schema_version": "0.9", "components": []}),
        )
        result = check_d09_portable_declaration(repo)
        assert result.verdict is Verdict.FAIL
        kinds = {entry.kind for entry in result.evidence}
        assert "declaration-schema-version" in kinds

    def test_fail_when_declared_component_not_installed(self, tmp_path):
        repo = tmp_path / "repo"
        _write(
            repo,
            "copilot.project.json",
            json.dumps({"schema_version": "1.0", "components": ["codex"]}),
        )
        result = check_d09_portable_declaration(repo)
        assert result.verdict is Verdict.FAIL
        kinds = {entry.kind for entry in result.evidence}
        assert "declaration-not-installed" in kinds

    def test_fail_on_forbidden_field(self, tmp_path):
        repo = tmp_path / "repo"
        _write(repo, ".claude/agents/cw.md", "content")
        _write(
            repo,
            "copilot.project.json",
            json.dumps(
                {
                    "schema_version": "1.0",
                    "components": ["claude"],
                    "org": "Everyone-Needs-A-Copilot",
                }
            ),
        )
        result = check_d09_portable_declaration(repo)
        assert result.verdict is Verdict.FAIL
        kinds = {entry.kind for entry in result.evidence}
        assert "declaration-forbidden-field" in kinds

    def test_fail_on_hardcoded_machine_path_value(self, tmp_path):
        repo = tmp_path / "repo"
        _write(repo, ".claude/agents/cw.md", "content")
        _write(
            repo,
            "copilot.project.json",
            json.dumps(
                {
                    "schema_version": "1.0",
                    "components": ["claude"],
                    "note": "/Volumes/Dev/Sites/COPILOT/repo",
                }
            ),
        )
        result = check_d09_portable_declaration(repo)
        assert result.verdict is Verdict.FAIL
        kinds = {entry.kind for entry in result.evidence}
        assert "declaration-forbidden-field" in kinds


# ---------------------------------------------------------------------------
# run(context) -- the real `dimensions/__init__.py` module contract
# ---------------------------------------------------------------------------


class TestRunContract:
    """Every module's `run(context)` must return exactly one `CheckResult`
    per repo, and must emit an explicit `Verdict.SKIP` (never a silent
    omission) for a class outside the dimension's `applies_to_classes` --
    `dimensions/__init__.py`'s own module contract."""

    @pytest.mark.parametrize(
        "run_fn,check_id",
        [
            (run_d05, "repo.d05.cc_config_machine_sentinel"),
            (run_d06, "repo.d06.memory_entries_committed_db_ignored"),
            (run_d07, "repo.d07.knowledge_wiring_resolves"),
            (run_d09, "repo.d09.portable_declaration"),
        ],
    )
    def test_skips_class_e_explicitly(self, tmp_path, run_fn, check_id):
        repo = tmp_path / "scratch-dir"
        repo.mkdir()
        context = _context(repo, rubric_class="E")

        results = tuple(run_fn(context))
        assert len(results) == 1
        assert results[0].id == check_id
        assert results[0].verdict is Verdict.SKIP
        assert results[0].subject == context.subject

    def test_d05_run_pass_for_class_c(self, tmp_path):
        repo = tmp_path / "repo"
        init_git_repo(repo)
        (repo / ".claude" / "cc").mkdir(parents=True)
        (repo / ".claude" / "cc" / "config.json").write_text(
            json.dumps(
                {
                    "$schema": "cc-config-v1",
                    "version": 1,
                    "paths": {"knowledge_repo": "@machine"},
                }
            ),
            encoding="utf-8",
        )
        git_commit_all(repo, "add cc config")

        results = tuple(run_d05(_context(repo, rubric_class="C")))
        assert len(results) == 1
        assert results[0].verdict is Verdict.PASS

    def test_d06_run_fail_for_class_b(self, tmp_path):
        repo = tmp_path / "repo"
        init_git_repo(repo)

        results = tuple(run_d06(_context(repo, rubric_class="B", role="organization")))
        assert len(results) == 1
        assert results[0].verdict is Verdict.FAIL

    def test_d07_run_pass_for_class_a(self, tmp_path):
        repo = tmp_path / "repo"
        (repo / ".claude" / "cc").mkdir(parents=True)
        (repo / ".claude" / "cc" / "config.json").write_text(
            json.dumps({"paths": {"knowledge_repo": "@machine"}}), encoding="utf-8"
        )

        results = tuple(run_d07(_context(repo, rubric_class="A", role="foundation")))
        assert len(results) == 1
        assert results[0].verdict is Verdict.PASS

    def test_d09_run_fail_for_class_d(self, tmp_path):
        repo = tmp_path / "knowledge-repo"
        repo.mkdir()

        results = tuple(run_d09(_context(repo, rubric_class="D")))
        assert len(results) == 1
        assert results[0].verdict is Verdict.FAIL
        assert results[0].evidence[0].kind == "declaration-missing"

    def test_d08_run_skips_class_c_without_needing_a_manifest(self, tmp_path):
        """D8 is `applies_to_classes=("A","B","C","D","E")` at registration
        (every class gets an explicit verdict) but only A/B are ever
        `PASS`/`FAIL` -- C/D/E is `Verdict.SKIP`, computed WITHOUT ever
        resolving `layers.manifest` (proving the short-circuit really is
        first, so a consumer repo's D8 check never depends on the machine
        having a layer manifest configured at all)."""

        repo = tmp_path / "some-product-repo"
        repo.mkdir()
        results = tuple(run_d08(_context(repo, rubric_class="C")))
        assert len(results) == 1
        assert results[0].verdict is Verdict.SKIP

    def test_d08_run_could_not_run_when_no_manifest_configured(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.delenv("CC_LAYERS_MANIFEST", raising=False)
        repo = tmp_path / "claude-copilot"
        repo.mkdir()
        results = tuple(run_d08(_context(repo, rubric_class="A", role="foundation")))
        assert len(results) == 1
        assert results[0].verdict is Verdict.COULD_NOT_RUN

    def test_d08_run_pass_for_class_b_via_configured_manifest(
        self, tmp_path, monkeypatch
    ):
        import yaml

        repo = tmp_path / "cli-copilot-internal"
        repo.mkdir()
        manifest = tmp_path / "copilot.layers.yml"
        manifest.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "layers": [
                        {
                            "id": "cli-organization",
                            "role": "organization",
                            "rank": 30,
                            "product": "cli",
                            "source": {
                                "repo": "git@github-work:org/cli-copilot-internal.git",
                                "path": str(repo),
                                "ref": "main",
                            },
                            "auth": "work",
                            "activation": "always",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("CC_LAYERS_MANIFEST", str(manifest))

        results = tuple(run_d08(_context(repo, rubric_class="B", role="organization")))
        assert len(results) == 1
        assert results[0].verdict is Verdict.PASS
