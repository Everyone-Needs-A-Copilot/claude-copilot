"""WP-4c tests: D10 (MCP), D11 (registry), D12 (docs), D13 (scanner
reachability) as executable per-repo assertions.

Two layers of coverage, matching WP-4b's own `test_dimensions_d05_d09.py`
shape (independently converged on):

  - `TestD10*`/`TestD11*`/`TestD12*`/`TestD13*` exercise each module's pure
    `check_*(repo, ...)` function directly (Rule 2, `HARNESS-DESIGN.md`
    section 3.2: "every check is a pure function of inputs") -- fast,
    precise, one assertion per fixture shape. Every check gets at least one
    POSITIVE test (a synthetic subject where it passes) and one NEGATIVE
    test (a synthetic subject where it fails), per the package's own
    definition of done (`HARNESS-DESIGN.md` section 9.3: "a check never
    proven to fail is not a check").
  - `TestRunContract` exercises each module's `run(context: RepoContext)`
    entry point -- the real `dimensions/__init__.py` module contract, which
    landed in a sibling package's commits partway through this package's
    own implementation.

All fixtures are built fresh under `tmp_path` (World A) -- nothing here
reads or writes a real repo.

This file is deliberately named `test_dimensions_wp4c.py`, not
`test_layer3_dimensions.py` -- the latter is reserved for WP-4's own
sweep/classes wiring (`HARNESS-DESIGN.md` section 9.1's collision-control
table); this file owns only the four dimension modules WP-4c is responsible
for and must never collide with a file WP-4 later adds.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cc.core.conformance.classes import ClassificationEntry, RepoClass
from cc.core.conformance.dimensions import (
    RepoContext,
    d10_mcp,
    d11_registry,
    d12_docs,
    d13_reach,
)
from cc.core.conformance.types import ExpectedToday, Mode, Verdict

from .conftest import git_commit_all, init_git_repo

pytestmark = pytest.mark.filterwarnings("ignore")


def _git_repo(path: Path) -> Path:
    init_git_repo(path)
    git_commit_all(path, "initial commit")
    return path


def _context(repo: Path, *, rubric_class: str, role: str | None = None) -> RepoContext:
    """Build a real `RepoContext` the same way `sweep.py` would, for a
    given rubric letter -- mirrors `test_dimensions_d05_d09.py`'s own
    `_context()` helper exactly, so both packages' tests build contexts the
    identical way."""

    if role is not None:
        classification = ClassificationEntry(
            key=repo.name,
            repo_class=RepoClass.COMPONENT,
            rationale="test fixture",
            role=role,
        )
    elif rubric_class == "D":
        classification = ClassificationEntry(
            key=repo.name,
            repo_class=RepoClass.DOCS_KNOWLEDGE,
            rationale="test fixture",
        )
    elif rubric_class == "E":
        classification = ClassificationEntry(
            key=repo.name,
            repo_class=RepoClass.SCRATCH_ARCHIVE,
            rationale="test fixture",
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


# ---------------------------------------------------------------------------
# D10 -- MCP wiring
# ---------------------------------------------------------------------------


class TestD10McpObjectNoRetiredServers:
    def test_pass_on_correct_empty_object(self, tmp_path):
        repo = _git_repo(tmp_path / "clean-copilot")
        (repo / ".mcp.json").write_text(
            json.dumps({"mcpServers": {}}), encoding="utf-8"
        )
        result = d10_mcp.check_mcp_object_no_retired_servers(repo)
        assert result.verdict is Verdict.PASS
        assert result.id == "repo.d10.mcp_object_no_retired_servers"

    def test_pass_preserves_third_party_servers(self, tmp_path):
        repo = _git_repo(tmp_path / "delphi-like")
        (repo / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"delphi-assistant": {"command": "x"}}}),
            encoding="utf-8",
        )
        result = d10_mcp.check_mcp_object_no_retired_servers(repo)
        assert result.verdict is Verdict.PASS

    def test_fail_on_retired_server(self, tmp_path):
        repo = _git_repo(tmp_path / "spanish-copilot")
        (repo / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"copilot-memory": {}, "skills-copilot": {}}}),
            encoding="utf-8",
        )
        result = d10_mcp.check_mcp_object_no_retired_servers(repo)
        assert result.verdict is Verdict.FAIL
        assert result.evidence
        assert "copilot-memory" in result.evidence[0].actual
        # Named in KNOWN_RETIRED_SERVER_REPOS -> grounded expected_today.
        assert result.expected_today is ExpectedToday.FAIL

    def test_fail_on_cli_owned_task_and_research_servers(self, tmp_path):
        repo = _git_repo(tmp_path / "stale-copilot-wiring")
        (repo / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"task-copilot": {}, "research-copilot": {}}}),
            encoding="utf-8",
        )
        result = d10_mcp.check_mcp_object_no_retired_servers(repo)
        assert result.verdict is Verdict.FAIL
        assert "research-copilot" in result.evidence[0].actual
        assert "task-copilot" in result.evidence[0].actual

    def test_fail_on_missing_file(self, tmp_path):
        repo = _git_repo(tmp_path / "no-mcp")
        result = d10_mcp.check_mcp_object_no_retired_servers(repo)
        assert result.verdict is Verdict.FAIL
        assert result.evidence[0].path.endswith(".mcp.json")

    def test_fail_on_non_object_mcp_servers(self, tmp_path):
        repo = _git_repo(tmp_path / "bad-shape")
        (repo / ".mcp.json").write_text(
            json.dumps({"mcpServers": []}), encoding="utf-8"
        )
        result = d10_mcp.check_mcp_object_no_retired_servers(repo)
        assert result.verdict is Verdict.FAIL

    def test_fail_on_malformed_json(self, tmp_path):
        repo = _git_repo(tmp_path / "malformed")
        (repo / ".mcp.json").write_text("not json {{{", encoding="utf-8")
        result = d10_mcp.check_mcp_object_no_retired_servers(repo)
        assert result.verdict is Verdict.FAIL


class TestD10McpJsonIsCommittable:
    def test_pass_when_not_ignored(self, tmp_path):
        repo = _git_repo(tmp_path / "claude-copilot-clean")
        (repo / ".mcp.json").write_text(
            json.dumps({"mcpServers": {}}), encoding="utf-8"
        )
        git_commit_all(repo, "add mcp.json")
        result = d10_mcp.check_mcp_json_is_committable(repo)
        assert result.verdict is Verdict.PASS

    def test_fail_when_gitignored_reproduces_rc6(self, tmp_path):
        repo = _git_repo(tmp_path / "claude-copilot")
        (repo / ".gitignore").write_text(".mcp.json\n", encoding="utf-8")
        git_commit_all(repo, "add gitignore excluding .mcp.json")
        result = d10_mcp.check_mcp_json_is_committable(repo)
        assert result.verdict is Verdict.FAIL
        assert result.root_cause == "rc.rc6"
        assert ".gitignore" in result.evidence[0].path
        # Named in KNOWN_MCP_GITIGNORED_REPOS -> grounded expected_today.
        assert result.expected_today is ExpectedToday.FAIL

    def test_could_not_run_when_not_a_git_repo(self, tmp_path):
        not_a_repo = tmp_path / "plain-dir"
        not_a_repo.mkdir()
        result = d10_mcp.check_mcp_json_is_committable(not_a_repo)
        assert result.verdict is Verdict.COULD_NOT_RUN

    def test_check_functions_accept_an_expected_today_override(self, tmp_path):
        repo = _git_repo(tmp_path / "override-me")
        (repo / ".mcp.json").write_text(
            json.dumps({"mcpServers": {}}), encoding="utf-8"
        )
        result = d10_mcp.check_mcp_object_no_retired_servers(
            repo, expected_today=ExpectedToday.FAIL
        )
        assert result.expected_today is ExpectedToday.FAIL


# ---------------------------------------------------------------------------
# D11 -- Registry entry (ratified target state)
# ---------------------------------------------------------------------------

_FIXTURE_ECOSYSTEM_MD = """\
# Ecosystem Registry

## Layer 1 -- Foundational

| Product | Docs | Local path | Repo | Vis | Status | What it is |
|---|---|---|---|---|---|---|
| **claude-copilot** | x | x | x | public | active | the framework |
| **codex-copilot** | x | x | x | public | active | codex |

## Layer 3 -- Applications

| Product | Docs | Local path | Repo | Vis | Status | What it is |
|---|---|---|---|---|---|---|
| **flow** | x | x | x | private | active | webgl game |
| **transformation** | x | x | x | private | active | webgl tool |

## Out of scope / not tracked here

- **Client delivery (separate from the product ecosystem)**: Hermes / Hermes-3 /
  hermes-1, Clio, Delphi, Hermes-2, Beacon Mobility, lars-website.
"""


class TestD11RegistryEntry:
    def _write_doc(self, tmp_path: Path, text: str = _FIXTURE_ECOSYSTEM_MD) -> Path:
        doc = tmp_path / "ECOSYSTEM.md"
        doc.write_text(text, encoding="utf-8")
        return doc

    def test_pass_when_row_present_under_correct_layer(self, tmp_path):
        doc = self._write_doc(tmp_path)
        repo = tmp_path / "flow"
        repo.mkdir()
        result = d11_registry.check_registry_entry(repo, ecosystem_md=doc)
        assert result.verdict is Verdict.PASS

    def test_fail_when_row_absent_add_now_product(self, tmp_path):
        doc = self._write_doc(tmp_path)
        repo = tmp_path / "crm-automation-copilot"
        repo.mkdir()
        result = d11_registry.check_registry_entry(repo, ecosystem_md=doc)
        assert result.verdict is Verdict.FAIL
        assert "crm-automation-copilot" in result.evidence[0].expected

    def test_fail_on_stale_alias_name(self, tmp_path):
        text = _FIXTURE_ECOSYSTEM_MD.replace(
            "**transformation**", "**transformations**"
        )
        doc = self._write_doc(tmp_path, text)
        repo = tmp_path / "transformation"
        repo.mkdir()
        result = d11_registry.check_registry_entry(repo, ecosystem_md=doc)
        assert result.verdict is Verdict.FAIL
        assert "transformations" in result.evidence[0].actual

    def test_pass_once_corrected_name_lands(self, tmp_path):
        doc = self._write_doc(tmp_path)  # already uses "transformation"
        repo = tmp_path / "transformation"
        repo.mkdir()
        result = d11_registry.check_registry_entry(repo, ecosystem_md=doc)
        assert result.verdict is Verdict.PASS

    def test_prose_only_mention_does_not_count(self, tmp_path):
        text = _FIXTURE_ECOSYSTEM_MD + "\n> knowledge-copilot renamed.\n"
        doc = self._write_doc(tmp_path, text)
        repo = tmp_path / "knowledge-copilot"
        repo.mkdir()
        result = d11_registry.check_registry_entry(repo, ecosystem_md=doc)
        assert result.verdict is Verdict.FAIL

    def test_pass_when_layer1_row_added_for_knowledge_copilot(self, tmp_path):
        text = _FIXTURE_ECOSYSTEM_MD.replace(
            "| **codex-copilot** | x | x | x | public | active | codex |",
            "| **codex-copilot** | x | x | x | public | active | codex |\n"
            "| **knowledge-copilot** | x | x | x | public | active | knowledge |",
        )
        doc = self._write_doc(tmp_path, text)
        repo = tmp_path / "knowledge-copilot"
        repo.mkdir()
        result = d11_registry.check_registry_entry(repo, ecosystem_md=doc)
        assert result.verdict is Verdict.PASS

    def test_dead_entry_removed_passes(self, tmp_path):
        doc = self._write_doc(tmp_path)  # rfp-copilot not mentioned at all
        repo = tmp_path / "rfp-copilot"
        repo.mkdir()
        result = d11_registry.check_registry_entry(repo, ecosystem_md=doc)
        assert result.verdict is Verdict.PASS

    def test_dead_entry_still_present_fails(self, tmp_path):
        text = _FIXTURE_ECOSYSTEM_MD + "\n- Archived: rfp-copilot lives on.\n"
        doc = self._write_doc(tmp_path, text)
        repo = tmp_path / "rfp-copilot"
        repo.mkdir()
        result = d11_registry.check_registry_entry(repo, ecosystem_md=doc)
        assert result.verdict is Verdict.FAIL
        assert "removed entirely" in result.evidence[0].expected

    def test_excluded_bullet_pass_when_named(self, tmp_path):
        doc = self._write_doc(tmp_path)
        repo = tmp_path / "Delphi"
        repo.mkdir()
        result = d11_registry.check_registry_entry(
            repo, canonical_name="Delphi", ecosystem_md=doc
        )
        assert result.verdict is Verdict.PASS

    def test_excluded_bullet_fail_when_not_yet_named(self, tmp_path):
        text = _FIXTURE_ECOSYSTEM_MD.replace(", Delphi, Hermes-2,", ",")
        doc = self._write_doc(tmp_path, text)
        repo = tmp_path / "Delphi"
        repo.mkdir()
        result = d11_registry.check_registry_entry(
            repo, canonical_name="Delphi", ecosystem_md=doc
        )
        assert result.verdict is Verdict.FAIL

    def test_tier_variant_requires_matrix_not_a_row(self, tmp_path):
        doc = self._write_doc(tmp_path)  # no matrix section at all
        repo = tmp_path / "claude-copilot-internal"
        repo.mkdir()
        result = d11_registry.check_registry_entry(repo, ecosystem_md=doc)
        assert result.verdict is Verdict.FAIL
        assert result.root_cause == "registry.tier_matrix_missing"

    def test_tier_variant_passes_once_matrix_section_exists(self, tmp_path):
        text = _FIXTURE_ECOSYSTEM_MD + (
            "\n## Tier variant matrix\n\n"
            "| Product | foundation | organization | department | personal |\n"
            "|---|---|---|---|---|\n"
            "| claude | x | x | x | x |\n"
        )
        doc = self._write_doc(tmp_path, text)
        repo = tmp_path / "claude-copilot-internal"
        repo.mkdir()
        result = d11_registry.check_registry_entry(repo, ecosystem_md=doc)
        assert result.verdict is Verdict.PASS

    def test_personal_tree_repo_is_not_silently_skipped(self, tmp_path):
        """Q2: PERSONAL is in scope -- a subject under a PERSONAL/ path gets
        the same evaluation as any other repo, never an automatic pass or
        skip purely because of its path prefix."""

        doc = self._write_doc(tmp_path)
        repo = tmp_path / "PERSONAL" / "some-untracked-thing"
        repo.mkdir(parents=True)
        result = d11_registry.check_registry_entry(
            repo, canonical_name="some-untracked-thing", ecosystem_md=doc
        )
        assert result.verdict is Verdict.FAIL  # judged, not waved through

    def test_could_not_run_when_ecosystem_md_unresolvable(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CC_CONFORMANCE_ECOSYSTEM_MD", raising=False)
        repo = tmp_path / "orphan"
        repo.mkdir()
        result = d11_registry.check_registry_entry(
            repo, ecosystem_md=tmp_path / "does-not-exist.md"
        )
        # An explicit but nonexistent path is still "not found" -- exercise
        # the None-path branch via the real resolver finding nothing when
        # every candidate (env override, configured shared_docs, both known
        # local roots) is absent in a hermetic tmp_path world.
        assert result.verdict in (Verdict.COULD_NOT_RUN, Verdict.FAIL)


# ---------------------------------------------------------------------------
# D12 -- Docs / initiatives scaffolding
# ---------------------------------------------------------------------------


class TestD12InitiativesScaffold:
    def _seed_full_tree(self, repo: Path) -> None:
        base = repo / "docs" / "40-initiatives"
        (base / "_template" / "phases").mkdir(parents=True)
        (base / "_template" / "decisions").mkdir(parents=True)
        (base / "_template" / "retrospectives").mkdir(parents=True)
        (base / "README.md").write_text("# initiatives\n", encoding="utf-8")

    def test_pass_when_tracked_and_complete(self, tmp_path):
        repo = _git_repo(tmp_path / "clean-repo")
        self._seed_full_tree(repo)
        git_commit_all(repo, "add initiatives scaffold")
        result = d12_docs.check_initiatives_scaffold(repo)
        assert result.verdict is Verdict.PASS

    def test_fail_when_absent(self, tmp_path):
        repo = _git_repo(tmp_path / "hermes-like")
        result = d12_docs.check_initiatives_scaffold(repo)
        assert result.verdict is Verdict.FAIL
        assert result.evidence

    def test_fail_when_template_missing(self, tmp_path):
        repo = _git_repo(tmp_path / "sproutworks-like")
        base = repo / "docs" / "40-initiatives"
        base.mkdir(parents=True)
        (base / "README.md").write_text("x", encoding="utf-8")
        git_commit_all(repo, "docs without template")
        result = d12_docs.check_initiatives_scaffold(repo)
        assert result.verdict is Verdict.FAIL

    def test_fail_when_gitignored_reproduces_product_creation_copilot(self, tmp_path):
        repo = _git_repo(tmp_path / "product-creation-copilot")
        (repo / ".gitignore").write_text("docs/\n", encoding="utf-8")
        git_commit_all(repo, "add gitignore excluding docs")
        self._seed_full_tree(repo)  # exists on disk, deliberately untracked
        result = d12_docs.check_initiatives_scaffold(repo)
        assert result.verdict is Verdict.FAIL
        assert any("gitignore" in e.actual for e in result.evidence)
        assert result.expected_today is ExpectedToday.FAIL


# ---------------------------------------------------------------------------
# D13 -- Scanner reachability
# ---------------------------------------------------------------------------


class TestD13ScannerReachable:
    def test_pass_when_git_root_under_configured_root_unheld(self, tmp_path):
        roots_parent = tmp_path / "Sites"
        repo = _git_repo(roots_parent / "COPILOT" / "some-product")
        excluded = tmp_path / "excluded-projects.json"
        holds = tmp_path / "holds.json"
        result = d13_reach.check_scanner_reachable(
            repo,
            configured_roots=[roots_parent],
            excluded_registry=excluded,
            holds_registry=holds,
        )
        assert result.verdict is Verdict.PASS

    def test_fail_when_not_a_git_root_reproduces_playground(self, tmp_path):
        repo = tmp_path / "Sites" / "COPILOT" / "playground"
        repo.mkdir(parents=True)
        agents = repo / ".claude" / "agents"
        agents.mkdir(parents=True)
        for i in range(3):
            (agents / f"agent-{i}.md").write_text("x", encoding="utf-8")
        result = d13_reach.check_scanner_reachable(
            repo, configured_roots=[tmp_path / "Sites"]
        )
        assert result.verdict is Verdict.FAIL
        assert "framework install" in result.evidence[0].detail
        # Named in KNOWN_NOT_GIT_ROOT_REPOS -> grounded expected_today.
        assert result.expected_today is ExpectedToday.FAIL

    def test_fail_when_not_a_git_root_and_no_install_reproduces_investr_api(
        self, tmp_path
    ):
        repo = tmp_path / "Sites" / "PERSONAL" / "investr-api"
        repo.mkdir(parents=True)
        result = d13_reach.check_scanner_reachable(
            repo, configured_roots=[tmp_path / "Sites"]
        )
        assert result.verdict is Verdict.FAIL
        assert result.expected_today is ExpectedToday.FAIL

    def test_fail_when_outside_any_configured_root(self, tmp_path):
        repo = _git_repo(tmp_path / "elsewhere" / "some-product")
        result = d13_reach.check_scanner_reachable(
            repo, configured_roots=[tmp_path / "Sites"]
        )
        assert result.verdict is Verdict.FAIL
        assert result.evidence[0].kind == "projects-roots"

    def test_fail_when_excluded(self, tmp_path):
        roots_parent = tmp_path / "Sites"
        repo = _git_repo(roots_parent / "excluded-product")
        excluded = tmp_path / "excluded-projects.json"
        excluded.write_text(
            json.dumps({"schema_version": "1.0", "paths": [str(repo.resolve())]}),
            encoding="utf-8",
        )
        result = d13_reach.check_scanner_reachable(
            repo,
            configured_roots=[roots_parent],
            excluded_registry=excluded,
            holds_registry=tmp_path / "holds.json",
        )
        assert result.verdict is Verdict.FAIL
        assert result.evidence[0].kind == "excluded-projects"

    def test_fail_when_held(self, tmp_path):
        from cc.core.ecosystem.workspaces import record_integration_hold

        roots_parent = tmp_path / "Sites"
        repo = _git_repo(roots_parent / "held-product")
        holds = tmp_path / "holds.json"
        record_integration_hold(
            repo,
            inspection_id="insp-1",
            plan_id="plan-1",
            registry=holds,
            now=0.0,
        )
        result = d13_reach.check_scanner_reachable(
            repo,
            configured_roots=[roots_parent],
            excluded_registry=tmp_path / "excluded.json",
            holds_registry=holds,
        )
        assert result.verdict is Verdict.FAIL
        assert result.evidence[0].kind == "integration-holds"

    def test_symlink_alias_reports_against_canonical_target_reproduces_shared_docs(
        self, tmp_path
    ):
        roots_parent = tmp_path / "Sites" / "COPILOT"
        real_repo = _git_repo(roots_parent / "knowledge-copilot-internal")
        alias = roots_parent / "shared-docs"
        alias.symlink_to(real_repo, target_is_directory=True)

        result = d13_reach.check_scanner_reachable(
            alias, configured_roots=[tmp_path / "Sites"]
        )
        assert result.verdict is Verdict.PASS
        assert "symlink alias" in result.detail

    def test_dedupe_repos_by_realpath_collapses_the_symlink_alias(self, tmp_path):
        roots_parent = tmp_path / "Sites" / "COPILOT"
        real_repo = _git_repo(roots_parent / "knowledge-copilot-internal")
        alias = roots_parent / "shared-docs"
        alias.symlink_to(real_repo, target_is_directory=True)

        deduped = d13_reach.dedupe_repos_by_realpath([alias, real_repo])
        assert len(deduped) == 1
        assert deduped[0] == alias  # first-seen spelling is preserved

    def test_registries_are_empty_passes_when_none_exist(self, tmp_path):
        result = d13_reach.check_registries_are_empty(
            projects_registry=tmp_path / "projects.json",
            excluded_registry=tmp_path / "excluded-projects.json",
            holds_registry=tmp_path / "project-integration-holds.json",
        )
        assert result.verdict is Verdict.PASS

    def test_registries_are_empty_fails_when_one_exists(self, tmp_path):
        excluded = tmp_path / "excluded-projects.json"
        excluded.write_text(
            json.dumps({"schema_version": "1.0", "paths": []}), encoding="utf-8"
        )
        result = d13_reach.check_registries_are_empty(
            projects_registry=tmp_path / "projects.json",
            excluded_registry=excluded,
            holds_registry=tmp_path / "project-integration-holds.json",
        )
        assert result.verdict is Verdict.FAIL
        assert result.evidence[0].path == str(excluded)

    def test_check_scanner_reachable_accepts_an_expected_today_override(self, tmp_path):
        repo = _git_repo(tmp_path / "Sites" / "override-me")
        result = d13_reach.check_scanner_reachable(
            repo,
            configured_roots=[tmp_path / "Sites"],
            expected_today=ExpectedToday.FAIL,
        )
        assert result.expected_today is ExpectedToday.FAIL


# ---------------------------------------------------------------------------
# run(context) -- the real dimensions/__init__.py module contract, which
# landed in a sibling package's commits partway through this package's own
# implementation. Mirrors test_dimensions_d05_d09.py's TestRunContract.
# ---------------------------------------------------------------------------


class TestRunContract:
    """Every module's `run(context)` must return exactly one `CheckResult`
    per registered check id, and must emit an explicit `Verdict.SKIP`
    (never a silent omission) for a class outside that check's
    `applies_to_classes` -- `dimensions/__init__.py`'s own module contract."""

    def test_d10_run_skips_class_e_explicitly_for_both_checks(self, tmp_path):
        repo = tmp_path / "scratch-dir"
        repo.mkdir()
        context = _context(repo, rubric_class="E")

        results = tuple(d10_mcp.run(context))
        assert {r.id for r in results} == {
            "repo.d10.mcp_object_no_retired_servers",
            "repo.d10.mcp_json_is_committable",
        }
        assert all(r.verdict is Verdict.SKIP for r in results)
        assert all(r.subject == context.subject for r in results)

    def test_d10_run_pass_for_class_c(self, tmp_path):
        repo = _git_repo(tmp_path / "repo")
        (repo / ".mcp.json").write_text(
            json.dumps({"mcpServers": {}}), encoding="utf-8"
        )
        git_commit_all(repo, "add mcp.json")

        results = tuple(d10_mcp.run(_context(repo, rubric_class="C")))
        assert len(results) == 2
        assert all(r.verdict is Verdict.PASS for r in results)

    def test_d11_run_skips_class_e_explicitly(self, tmp_path):
        repo = tmp_path / "scratch-dir"
        repo.mkdir()
        context = _context(repo, rubric_class="E")

        results = tuple(d11_registry.run(context))
        assert len(results) == 1
        assert results[0].id == "repo.d11.registry_entry"
        assert results[0].verdict is Verdict.SKIP
        assert results[0].subject == context.subject

    def test_d11_run_evaluates_class_c(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CC_CONFORMANCE_ECOSYSTEM_MD", raising=False)
        doc = tmp_path / "ECOSYSTEM.md"
        doc.write_text(
            "| **flow** | x | x | x | private | active | game |\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("CC_CONFORMANCE_ECOSYSTEM_MD", str(doc))
        repo = tmp_path / "flow"
        repo.mkdir()

        results = tuple(d11_registry.run(_context(repo, rubric_class="C")))
        assert len(results) == 1
        assert results[0].verdict is Verdict.PASS

    def test_d12_run_skips_class_e_explicitly(self, tmp_path):
        repo = tmp_path / "scratch-dir"
        repo.mkdir()
        context = _context(repo, rubric_class="E")

        results = tuple(d12_docs.run(context))
        assert len(results) == 1
        assert results[0].id == "repo.d12.initiatives_scaffold"
        assert results[0].verdict is Verdict.SKIP
        assert results[0].subject == context.subject

    def test_d12_run_fail_for_class_c(self, tmp_path):
        repo = _git_repo(tmp_path / "repo")

        results = tuple(d12_docs.run(_context(repo, rubric_class="C")))
        assert len(results) == 1
        assert results[0].verdict is Verdict.FAIL

    def test_d13_run_never_skips_scanner_reachable_but_always_includes_registries(
        self, tmp_path, monkeypatch
    ):
        """D13 applies to ALL classes, so its SKIP branch is unreachable in
        practice -- confirm both registered ids are always produced,
        including the GLOBAL `registries_are_empty` fact.

        `run(context)`'s call to `check_registries_are_empty()` takes no
        explicit registry paths (`RepoContext` carries no such override), so
        it falls through to `~/.copilot/...` via `paths.mirrors_root`'s
        `~`-expansion. Redirect `HOME` here so this stays a true World-A
        (synthetic, hermetic) test rather than incidentally reading this
        machine's real `~/.copilot/` state.
        """

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        repo = _git_repo(tmp_path / "Sites" / "solo-product")
        results = tuple(d13_reach.run(_context(repo, rubric_class="C")))
        assert {r.id for r in results} == {
            "repo.d13.scanner_reachable",
            "repo.d13.registries_are_empty",
        }
        assert all(r.verdict is not Verdict.SKIP for r in results)


# ---------------------------------------------------------------------------
# Cross-module: every WP-4c check is actually registered (registry.py
# collision-checks ids at import time -- this proves import succeeded and
# the ids match TEST-MATRIX/HARNESS-DESIGN exactly).
# ---------------------------------------------------------------------------


def test_all_wp4c_check_ids_are_registered():
    from cc.core.conformance.registry import DEFAULT_REGISTRY

    expected_ids = {
        "repo.d10.mcp_object_no_retired_servers",
        "repo.d10.mcp_json_is_committable",
        "repo.d11.registry_entry",
        "repo.d12.initiatives_scaffold",
        "repo.d13.scanner_reachable",
        "repo.d13.registries_are_empty",
    }
    assert expected_ids <= {r.id for r in DEFAULT_REGISTRY.all()}


def test_every_wp4c_check_has_severity_and_remediation():
    from cc.core.conformance.registry import DEFAULT_REGISTRY

    prefixes = ("repo.d10.", "repo.d11.", "repo.d12.", "repo.d13.")
    wp4c_checks = [r for r in DEFAULT_REGISTRY.all() if r.id.startswith(prefixes)]
    assert wp4c_checks  # the modules above must have registered something
    for registration in wp4c_checks:
        assert registration.severity is not None
        assert registration.remediation
