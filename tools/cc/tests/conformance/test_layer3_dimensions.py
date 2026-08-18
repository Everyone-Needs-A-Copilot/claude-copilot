"""WP-4 tests: the fleet sweep engine (`sweep.py`), the repo taxonomy
(`classes.py` + `classification.toml`), and the dimension-module contract
(`dimensions/__init__.py`).

WP-4 does not implement any `dNN_*.py` check body itself (WP-4a/b/c own
those) -- so every dimension-module-facing test here injects its OWN
`DimensionModule` stand-ins via `run_dimension_modules(context,
modules=...)` / `unavailable_module_results(modules=...)`'s explicit
override parameter, rather than depending on whichever real `dNN_*.py`
files happen to exist on disk at test time. This keeps the suite
deterministic regardless of sibling work packages' landing order --
exactly the point of `dimensions/__init__.py`'s "missing module is a
COULD-NOT-RUN, not a crash" contract: WP-4's own tests must pass on a
checkout where zero dimension modules exist yet.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from cc.core.conformance import classes
from cc.core.conformance import sweep as sweep_mod
from cc.core.conformance.classes import (
    ClassificationEntry,
    ClassificationError,
    RepoClass,
)
from cc.core.conformance.dimensions import (
    DIMENSION_MODULE_NAMES,
    DimensionModule,
    RepoContext,
    discover_dimension_modules,
    run_dimension_modules,
    unavailable_module_results,
)
from cc.core.conformance.registry import REPO_CLASSES, Registry, register_check
from cc.core.conformance.sweep import (
    DiscoveredRepo,
    SweepOptions,
    discover_repos,
    run_sweep,
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
)

from .conftest import git_commit_all, init_git_repo

pytestmark = pytest.mark.filterwarnings("ignore")


# ---------------------------------------------------------------------------
# classes.py -- the taxonomy and its derived rubric letter
# ---------------------------------------------------------------------------


class TestRubricLetter:
    @pytest.mark.parametrize(
        "role,expected",
        [
            ("foundation", "A"),
            ("organization", "B"),
            ("department", "B"),
            ("personal", "B"),
        ],
    )
    def test_component_role_maps_to_rubric_letter(self, role, expected):
        entry = ClassificationEntry(
            key="COPILOT/claude-copilot",
            repo_class=RepoClass.COMPONENT,
            rationale="x",
            role=role,
        )
        assert entry.rubric_letter == expected

    def test_roleless_component_falls_back_to_c(self):
        entry = ClassificationEntry(
            key="COPILOT/product-creation-copilot",
            repo_class=RepoClass.COMPONENT,
            rationale="Q27: not one of the four synced families",
        )
        assert entry.rubric_letter == "C"

    @pytest.mark.parametrize(
        "repo_class,expected",
        [
            (RepoClass.PRODUCT, "C"),
            (RepoClass.SITE_CONTENT, "C"),
            (RepoClass.DOCS_KNOWLEDGE, "D"),
            (RepoClass.SCRATCH_ARCHIVE, "E"),
        ],
    )
    def test_non_component_class_maps_to_rubric_letter(self, repo_class, expected):
        entry = ClassificationEntry(
            key="PERSONAL/x", repo_class=repo_class, rationale="x"
        )
        assert entry.rubric_letter == expected

    def test_every_rubric_letter_this_module_can_produce_is_a_real_repo_class(self):
        # Guards the module-level assertion in classes.py itself staying true.
        for repo_class in RepoClass:
            for role in (None, "foundation", "organization", "department", "personal"):
                if role is not None and repo_class is not RepoClass.COMPONENT:
                    continue
                entry = ClassificationEntry(
                    key="x", repo_class=repo_class, rationale="x", role=role
                )
                assert entry.rubric_letter in REPO_CLASSES

    def test_role_on_non_component_raises(self):
        with pytest.raises(ClassificationError, match="only meaningful"):
            ClassificationEntry(
                key="x", repo_class=RepoClass.PRODUCT, rationale="x", role="foundation"
            )

    def test_unknown_role_raises(self):
        with pytest.raises(ClassificationError, match="unknown component role"):
            ClassificationEntry(
                key="x", repo_class=RepoClass.COMPONENT, rationale="x", role="galactic"
            )

    def test_empty_key_raises(self):
        with pytest.raises(ClassificationError, match="non-empty key"):
            ClassificationEntry(key="", repo_class=RepoClass.PRODUCT, rationale="x")

    def test_as_dict_includes_role_only_when_set(self):
        with_role = ClassificationEntry(
            key="x", repo_class=RepoClass.COMPONENT, rationale="x", role="foundation"
        )
        without_role = ClassificationEntry(
            key="y", repo_class=RepoClass.PRODUCT, rationale="x"
        )
        assert "role" in with_role.as_dict()
        assert "role" not in without_role.as_dict()
        assert with_role.as_dict()["rubric_letter"] == "A"


# ---------------------------------------------------------------------------
# classes.py -- classification.toml loading and the classify() seam
# ---------------------------------------------------------------------------


class TestClassificationTable:
    def test_load_missing_file_returns_empty_table(self, tmp_path):
        table = classes.load_classification_table(tmp_path / "does-not-exist.toml")
        assert table == {}

    def test_round_trips_one_row(self, tmp_path):
        toml_path = tmp_path / "classification.toml"
        toml_path.write_text(
            """
            [[repos]]
            path = "COPILOT/example-product"
            class = "PRODUCT"
            rationale = "test fixture"
            """,
            encoding="utf-8",
        )
        table = classes.load_classification_table(toml_path)
        assert set(table) == {"COPILOT/example-product"}
        entry = table["COPILOT/example-product"]
        assert entry.repo_class is RepoClass.PRODUCT
        assert entry.source == "override"
        assert entry.rubric_letter == "C"

    def test_component_row_carries_role(self, tmp_path):
        toml_path = tmp_path / "classification.toml"
        toml_path.write_text(
            """
            [[repos]]
            path = "COPILOT/claude-copilot"
            class = "COMPONENT"
            role = "foundation"
            rationale = "test fixture"
            """,
            encoding="utf-8",
        )
        entry = classes.load_classification_table(toml_path)["COPILOT/claude-copilot"]
        assert entry.role == "foundation"
        assert entry.rubric_letter == "A"

    def test_duplicate_key_raises(self, tmp_path):
        toml_path = tmp_path / "classification.toml"
        toml_path.write_text(
            """
            [[repos]]
            path = "COPILOT/dup"
            class = "PRODUCT"
            rationale = "first"

            [[repos]]
            path = "COPILOT/dup"
            class = "SCRATCH-ARCHIVE"
            rationale = "second"
            """,
            encoding="utf-8",
        )
        with pytest.raises(ClassificationError, match="duplicate"):
            classes.load_classification_table(toml_path)

    def test_unknown_class_value_raises(self, tmp_path):
        toml_path = tmp_path / "classification.toml"
        toml_path.write_text(
            """
            [[repos]]
            path = "COPILOT/bad"
            class = "NOT-A-REAL-CLASS"
            rationale = "x"
            """,
            encoding="utf-8",
        )
        with pytest.raises(ClassificationError):
            classes.load_classification_table(toml_path)

    def test_repos_field_must_be_an_array(self, tmp_path):
        toml_path = tmp_path / "classification.toml"
        toml_path.write_text('repos = "not a list"\n', encoding="utf-8")
        with pytest.raises(ClassificationError, match="array of tables"):
            classes.load_classification_table(toml_path)

    def test_repo_key_is_group_slash_name_under_root(self, tmp_path):
        root = tmp_path / "Sites"
        path = root / "COPILOT" / "claude-copilot"
        path.mkdir(parents=True)
        assert classes.repo_key(path, root) == "COPILOT/claude-copilot"

    def test_repo_key_falls_back_to_absolute_when_outside_root(self, tmp_path):
        root = tmp_path / "Sites"
        root.mkdir()
        outside = tmp_path / "elsewhere" / "thing"
        outside.mkdir(parents=True)
        assert classes.repo_key(outside, root) == outside.as_posix()

    def test_classify_uses_override_when_present(self, tmp_path):
        root = tmp_path / "Sites"
        path = root / "COPILOT" / "claude-copilot"
        path.mkdir(parents=True)
        table = {
            "COPILOT/claude-copilot": ClassificationEntry(
                key="COPILOT/claude-copilot",
                repo_class=RepoClass.COMPONENT,
                rationale="seeded",
                role="foundation",
                source="override",
            )
        }
        entry = classes.classify(path, root=root, table=table, is_git_root=True)
        assert entry.source == "override"
        assert entry.rubric_letter == "A"

    def test_classify_computed_default_for_git_root_is_product(self, tmp_path):
        root = tmp_path / "Sites"
        path = root / "COPILOT" / "brand-new-repo"
        path.mkdir(parents=True)
        entry = classes.classify(path, root=root, table={}, is_git_root=True)
        assert entry.repo_class is RepoClass.PRODUCT
        assert entry.rubric_letter == "C"
        assert entry.source == "computed-default"

    def test_classify_computed_default_for_non_git_is_scratch_archive(self, tmp_path):
        root = tmp_path / "Sites"
        path = root / "COPILOT" / "loose-scripts"
        path.mkdir(parents=True)
        entry = classes.classify(path, root=root, table={}, is_git_root=False)
        assert entry.repo_class is RepoClass.SCRATCH_ARCHIVE
        assert entry.rubric_letter == "E"
        assert entry.source == "computed-default"

    def test_computed_default_never_returns_component(self, tmp_path):
        # The "-internal/test-pilot trap" guard: a directory absent from
        # classification.toml must never be guessed into the inheritance
        # ladder from its name or git-root-ness alone.
        root = tmp_path / "Sites"
        for name, is_git in (("claude-copilot-internal", True), ("test-pilot", True)):
            path = root / "COPILOT" / name
            path.mkdir(parents=True)
            entry = classes.classify(path, root=root, table={}, is_git_root=is_git)
            assert entry.repo_class is not RepoClass.COMPONENT


# ---------------------------------------------------------------------------
# classes.py -- the REAL, committed classification.toml (seeded from
# CLASSIFICATION.md, corrected by the owner's ratified Q9/Q27/Q2/Q20
# answers -- see that file's own header).
# ---------------------------------------------------------------------------


class TestRealClassificationToml:
    @pytest.fixture(scope="class")
    def real_table(self):
        return classes.load_classification_table()

    def test_has_reviewed_audit_entries_plus_deferred_app_disposition(self, real_table):
        # 75 real directories from the 2026-08-10 audit, plus the app-only
        # public repo discovered afterward and explicitly deferred to PRD-24,
        # then one active Git root omitted from that static audit.
        assert len(real_table) == 77

    def test_every_entry_has_a_valid_rubric_letter(self, real_table):
        for key, entry in real_table.items():
            assert entry.rubric_letter in REPO_CLASSES, key

    def test_class_counts_match_the_corrected_audit(self, real_table):
        from collections import Counter

        counts = Counter(entry.repo_class for entry in real_table.values())
        assert counts[RepoClass.COMPONENT] == 17
        assert counts[RepoClass.PRODUCT] == 36
        assert counts[RepoClass.SITE_CONTENT] == 8
        assert counts[RepoClass.DOCS_KNOWLEDGE] == 1
        assert counts[RepoClass.SCRATCH_ARCHIVE] == 15

    def test_q9_reclassifies_control_tower_as_a_consumer(self, real_table):
        entry = real_table["COPILOT/copilot-control-tower"]
        assert entry.repo_class is RepoClass.PRODUCT
        assert entry.rubric_letter == "C"

    def test_public_control_tower_app_is_attributably_deferred(self, real_table):
        entry = real_table["COPILOT/copilot-control-tower-public"]
        assert entry.repo_class is RepoClass.SCRATCH_ARCHIVE
        assert entry.rubric_letter == "E"
        assert "Pablo Alejo" in entry.rationale
        assert "PRD-24/TASK-301" in entry.rationale
        assert "WP-838" in entry.rationale
        assert "2026-08-13" in entry.rationale

    def test_q27_bm_is_docs_knowledge_not_product(self, real_table):
        entry = real_table["COPILOT/BM"]
        assert entry.repo_class is RepoClass.DOCS_KNOWLEDGE
        assert entry.rubric_letter == "D"

    def test_q27_product_creation_copilot_is_a_roleless_component(self, real_table):
        entry = real_table["COPILOT/product-creation-copilot"]
        assert entry.repo_class is RepoClass.COMPONENT
        assert entry.role is None
        assert entry.rubric_letter == "C"

    def test_the_sixteen_tier_rungs_carry_correct_roles(self, real_table):
        for product in ("claude", "cli", "codex", "knowledge"):
            assert real_table[f"COPILOT/{product}-copilot"].role == "foundation"
            assert (
                real_table[f"COPILOT/{product}-copilot-internal"].role == "organization"
            )
            assert (
                real_table[f"COPILOT/{product}-copilot-accounting"].role == "department"
            )
            assert real_table[f"COPILOT/{product}-copilot-private"].role == "personal"

    def test_personal_dormant_repos_stay_product_not_excluded(self, real_table):
        # Q20 answer B for all four: kept maintained like an active repo.
        for name in (
            "financial-tracker",
            "investr-app",
            "revenue-projections",
            "investr-api",
        ):
            assert real_table[f"PERSONAL/{name}"].repo_class is RepoClass.PRODUCT

    def test_live_product_omission_is_explicitly_classified(self, real_table):
        assert (
            real_table["COPILOT/convoco-google-verification"].repo_class
            is RepoClass.PRODUCT
        )


# ---------------------------------------------------------------------------
# dimensions/__init__.py -- the module contract
# ---------------------------------------------------------------------------


def _fail_check() -> CheckResult:
    return CheckResult(
        id="repo.dtest.fake_check",
        layer=Layer.REPO,
        severity=Severity.S2,
        scope=Scope.PER_REPO,
        subject="/tmp/fake-repo",
        assertion="fake",
        verdict=Verdict.FAIL,
        expected_today=ExpectedToday.FAIL,
        evidence=(Evidence(kind="fake", path="/tmp/fake-repo/FAKE.md"),),
    )


class TestDiscoverDimensionModules:
    def test_returns_one_entry_per_expected_module_name(self):
        modules = discover_dimension_modules()
        assert [m.name for m in modules] == list(DIMENSION_MODULE_NAMES)

    def test_never_raises_even_when_every_module_is_missing(self):
        discover_dimension_modules()  # must not raise regardless of what is on disk

    def test_unavailable_entries_always_carry_an_error_string(self):
        for module in discover_dimension_modules():
            if not module.available:
                assert module.error


class TestRunDimensionModules:
    def _context(self, tmp_path: Path, *, mode: Mode = Mode.FAST) -> RepoContext:
        entry = ClassificationEntry(
            key="x", repo_class=RepoClass.PRODUCT, rationale="x"
        )
        return RepoContext.build(
            tmp_path, classification=entry, is_git_root=True, mode=mode
        )

    def test_aggregates_results_from_available_modules(self, tmp_path):
        good_module = SimpleNamespace(run=lambda context: [_fail_check()])
        modules = (DimensionModule(name="dtest", module=good_module),)
        results = run_dimension_modules(self._context(tmp_path), modules=modules)
        assert len(results) == 1
        assert results[0].id == "repo.dtest.fake_check"

    def test_skips_unavailable_modules_without_calling_them(self, tmp_path):
        modules = (DimensionModule(name="dtest", module=None, error="not built yet"),)
        results = run_dimension_modules(self._context(tmp_path), modules=modules)
        assert results == ()

    def test_a_crashing_module_produces_could_not_run_and_does_not_raise(
        self, tmp_path
    ):
        def _boom(context):
            raise RuntimeError("this dimension module has a bug")

        crashing = SimpleNamespace(run=_boom)
        working = SimpleNamespace(run=lambda context: [_fail_check()])
        modules = (
            DimensionModule(name="dbroken", module=crashing),
            DimensionModule(name="dtest", module=working),
        )
        results = run_dimension_modules(self._context(tmp_path), modules=modules)

        crashed = [r for r in results if r.id == "repo.dbroken.crashed"]
        assert len(crashed) == 1
        assert crashed[0].verdict is Verdict.COULD_NOT_RUN
        assert "RuntimeError" in crashed[0].evidence[0].actual
        # The OTHER (working) module's result still comes through --
        # one dimension crashing never takes its siblings down with it.
        assert any(r.id == "repo.dtest.fake_check" for r in results)

    def test_a_module_that_raises_while_iterating_a_generator_is_also_caught(
        self, tmp_path
    ):
        def _generator(context):
            yield _fail_check()
            raise ValueError("blew up mid-generator")

        flaky = SimpleNamespace(run=_generator)
        modules = (DimensionModule(name="dflaky", module=flaky),)
        results = run_dimension_modules(self._context(tmp_path), modules=modules)
        # Consumed eagerly (`tuple(module.run(context))`) -- a partial
        # yield before the raise is discarded in favor of one honest
        # COULD_NOT_RUN, never a silently-partial result set.
        assert len(results) == 1
        assert results[0].verdict is Verdict.COULD_NOT_RUN


class TestUnavailableModuleResults:
    def test_one_result_per_unavailable_module(self):
        modules = (
            DimensionModule(name="dmissing", module=None, error="ModuleNotFoundError"),
            DimensionModule(name="dworking", module=SimpleNamespace(run=lambda c: [])),
        )
        results = unavailable_module_results(modules)
        assert len(results) == 1
        assert results[0].id == "repo.dmissing.module_unavailable"
        assert results[0].verdict is Verdict.COULD_NOT_RUN
        assert results[0].scope is Scope.GLOBAL

    def test_empty_when_everything_is_available(self):
        modules = (
            DimensionModule(name="dworking", module=SimpleNamespace(run=lambda c: [])),
        )
        assert unavailable_module_results(modules) == ()

    def test_defaults_to_a_fresh_discovery_when_modules_not_passed(self):
        unavailable_module_results()  # must not raise


# ---------------------------------------------------------------------------
# sweep.py -- discovery
# ---------------------------------------------------------------------------


def _make_group_repo(root: Path, group: str, name: str, *, git: bool) -> Path:
    path = root / group / name
    path.mkdir(parents=True)
    if git:
        init_git_repo(path)
        git_commit_all(path, "initial commit")
    return path


class TestDiscoverRepos:
    def test_two_level_grouping_finds_every_repo(self, tmp_path):
        root = tmp_path / "Sites"
        _make_group_repo(root, "COPILOT", "alpha", git=True)
        _make_group_repo(root, "COPILOT", "beta", git=True)
        _make_group_repo(root, "PERSONAL", "gamma", git=True)

        discovered = discover_repos([root])
        names = {repo.path.name for repo in discovered}
        assert names == {"alpha", "beta", "gamma"}

    def test_includes_non_git_directories(self, tmp_path):
        # The playground / investr-api precedent: a directory with no
        # .git must still be discovered, not silently skipped.
        root = tmp_path / "Sites"
        _make_group_repo(root, "COPILOT", "playground-like", git=False)

        discovered = discover_repos([root])
        assert len(discovered) == 1
        assert discovered[0].is_git_root is False

    def test_short_circuits_when_a_group_itself_is_a_git_root(self, tmp_path):
        # A root laid out flat (no grouping level) still discovers
        # correctly -- the group IS the repo, so nothing beneath it (e.g.
        # a nested vendored `.git`-less directory) is separately reported.
        root = tmp_path / "Sites"
        flat_repo = root / "flat-repo"
        flat_repo.mkdir(parents=True)
        init_git_repo(flat_repo)
        (flat_repo / "src").mkdir()
        git_commit_all(flat_repo, "initial commit")

        discovered = discover_repos([root])
        assert len(discovered) == 1
        assert discovered[0].path == flat_repo.resolve()

    def test_dedupes_a_symlink_alias_by_realpath(self, tmp_path):
        root = tmp_path / "Sites"
        real = _make_group_repo(root, "COPILOT", "knowledge-copilot-internal", git=True)
        alias = root / "COPILOT" / "shared-docs"
        alias.symlink_to(real, target_is_directory=True)

        discovered = discover_repos([root])
        assert len(discovered) == 1
        assert discovered[0].path == real.resolve()
        assert discovered[0].raw_count == 2
        assert alias in discovered[0].aliases
        assert real in discovered[0].aliases

    def test_deterministic_sorted_order(self, tmp_path):
        root = tmp_path / "Sites"
        _make_group_repo(root, "COPILOT", "zeta", git=True)
        _make_group_repo(root, "COPILOT", "alpha", git=True)

        first = [r.path for r in discover_repos([root])]
        second = [r.path for r in discover_repos([root])]
        assert first == second == sorted(first)

    def test_missing_root_is_skipped_not_raised(self, tmp_path):
        discovered = discover_repos([tmp_path / "does-not-exist"])
        assert discovered == ()

    def test_repo_matches_filter_exact_and_suffix(self, tmp_path):
        root = tmp_path / "Sites"
        path = _make_group_repo(root, "COPILOT", "claude-copilot", git=True)
        repo = DiscoveredRepo(path=path, root=root, aliases=(path,), is_git_root=True)

        assert sweep_mod._repo_matches_filter(repo, ())
        assert sweep_mod._repo_matches_filter(repo, ["claude-copilot"])
        assert sweep_mod._repo_matches_filter(repo, [str(path)])
        assert not sweep_mod._repo_matches_filter(repo, ["some-other-repo"])


# ---------------------------------------------------------------------------
# sweep.py -- run_sweep end to end, against a synthetic tmp_path fleet with
# injected (never real) dimension modules, so this suite is deterministic
# regardless of which dNN_*.py files exist on disk.
# ---------------------------------------------------------------------------


class TestRunSweep:
    def _register_stub_check(self, registry: Registry, *, applies_to_classes=()):
        return register_check(
            id="repo.dtest.stub_check",
            layer=Layer.REPO,
            severity=Severity.S2,
            scope=Scope.PER_REPO,
            summary="stub check for WP-4's own sweep tests",
            remediation="n/a -- test fixture",
            applies_to_classes=applies_to_classes,
            registry=registry,
        )

    def _install_stub_dimension(
        self, monkeypatch, registration, *, verdict=Verdict.PASS
    ):
        def _stub_run(context: RepoContext):
            evidence = (
                ()
                if verdict is Verdict.PASS
                else (Evidence(kind="stub", path=context.subject),)
            )
            return [
                registration.result(
                    subject=context.subject, verdict=verdict, evidence=evidence
                )
            ]

        stub_modules = (
            DimensionModule(name="dtest", module=SimpleNamespace(run=_stub_run)),
        )
        monkeypatch.setattr(
            sweep_mod, "discover_dimension_modules", lambda: stub_modules
        )
        monkeypatch.setattr(
            sweep_mod, "unavailable_module_results", lambda modules=None: ()
        )

    def test_end_to_end_against_a_synthetic_fleet(self, tmp_path, monkeypatch):
        root = tmp_path / "Sites"
        _make_group_repo(root, "COPILOT", "widget-app", git=True)

        registry = Registry()
        registration = self._register_stub_check(registry)
        self._install_stub_dimension(monkeypatch, registration)

        result = run_sweep(
            SweepOptions(
                roots=(root,),
                registry=registry,
                jobs=1,
                cache_path=tmp_path / "cache.json",
                classification_path=tmp_path / "no-such-classification.toml",
            )
        )

        assert result.repos_discovered == 1
        assert result.repos_selected == 1
        assert result.cache_misses == 1
        assert result.cache_hits == 0
        assert len(result.results) == 1
        assert result.results[0].verdict is Verdict.PASS
        assert result.results[0].id == "repo.dtest.stub_check"

    def test_second_run_hits_the_cache(self, tmp_path, monkeypatch):
        root = tmp_path / "Sites"
        _make_group_repo(root, "COPILOT", "widget-app", git=True)

        registry = Registry()
        registration = self._register_stub_check(registry)
        self._install_stub_dimension(monkeypatch, registration)

        opts = SweepOptions(
            roots=(root,),
            registry=registry,
            jobs=1,
            cache_path=tmp_path / "cache.json",
            classification_path=tmp_path / "no-such-classification.toml",
        )
        first = run_sweep(opts)
        second = run_sweep(opts)

        assert first.cache_misses == 1
        assert second.cache_hits == 1
        assert second.cache_misses == 0
        assert second.results == first.results

    def test_full_mode_bypasses_the_cache(self, tmp_path, monkeypatch):
        root = tmp_path / "Sites"
        _make_group_repo(root, "COPILOT", "widget-app", git=True)

        registry = Registry()
        registration = self._register_stub_check(registry)
        self._install_stub_dimension(monkeypatch, registration)

        opts = SweepOptions(
            roots=(root,),
            registry=registry,
            jobs=1,
            mode=Mode.FULL,
            cache_path=tmp_path / "cache.json",
            classification_path=tmp_path / "no-such-classification.toml",
        )
        first = run_sweep(opts)
        second = run_sweep(opts)

        assert first.cache_misses == 1
        assert second.cache_misses == 1  # never 0 -- --full always bypasses the cache
        assert second.cache_hits == 0

    def test_repo_filter_narrows_the_swept_set(self, tmp_path, monkeypatch):
        root = tmp_path / "Sites"
        _make_group_repo(root, "COPILOT", "widget-app", git=True)
        _make_group_repo(root, "COPILOT", "gadget-app", git=True)

        registry = Registry()
        registration = self._register_stub_check(registry)
        self._install_stub_dimension(monkeypatch, registration)

        result = run_sweep(
            SweepOptions(
                roots=(root,),
                repos=("widget-app",),
                registry=registry,
                jobs=1,
                cache_path=tmp_path / "cache.json",
                classification_path=tmp_path / "no-such-classification.toml",
            )
        )
        assert result.repos_discovered == 2
        assert result.repos_selected == 1
        assert result.results[0].subject.endswith("widget-app")

    def test_class_filter_narrows_by_rubric_letter(self, tmp_path, monkeypatch):
        root = tmp_path / "Sites"
        _make_group_repo(root, "COPILOT", "widget-copilot", git=True)
        _make_group_repo(root, "COPILOT", "widget-copilot-internal", git=True)

        classification_path = tmp_path / "classification.toml"
        classification_path.write_text(
            """
            [[repos]]
            path = "COPILOT/widget-copilot"
            class = "COMPONENT"
            role = "foundation"
            rationale = "test fixture"

            [[repos]]
            path = "COPILOT/widget-copilot-internal"
            class = "COMPONENT"
            role = "organization"
            rationale = "test fixture"
            """,
            encoding="utf-8",
        )

        registry = Registry()
        registration = self._register_stub_check(registry)
        self._install_stub_dimension(monkeypatch, registration)

        result = run_sweep(
            SweepOptions(
                roots=(root,),
                classes=("A",),
                registry=registry,
                jobs=1,
                cache_path=tmp_path / "cache.json",
                classification_path=classification_path,
            )
        )
        assert result.repos_selected == 1
        assert result.results[0].subject.endswith("widget-copilot")

    def test_check_id_filter_excludes_unregistered_ids(self, tmp_path, monkeypatch):
        root = tmp_path / "Sites"
        _make_group_repo(root, "COPILOT", "widget-app", git=True)

        registry = Registry()
        registration = self._register_stub_check(registry)
        self._install_stub_dimension(monkeypatch, registration)

        result = run_sweep(
            SweepOptions(
                roots=(root,),
                check_ids=("repo.dtest.a_check_that_does_not_exist",),
                registry=registry,
                jobs=1,
                cache_path=tmp_path / "cache.json",
                classification_path=tmp_path / "no-such-classification.toml",
            )
        )
        assert result.results == ()

    def test_unavailable_dimension_module_produces_a_global_could_not_run_entry(
        self, tmp_path, monkeypatch
    ):
        root = tmp_path / "Sites"
        _make_group_repo(root, "COPILOT", "widget-app", git=True)

        registry = Registry()
        stub_modules = (
            DimensionModule(name="dmissing", module=None, error="not built yet"),
        )
        monkeypatch.setattr(
            sweep_mod, "discover_dimension_modules", lambda: stub_modules
        )

        result = run_sweep(
            SweepOptions(
                roots=(root,),
                registry=registry,
                jobs=1,
                cache_path=tmp_path / "cache.json",
                classification_path=tmp_path / "no-such-classification.toml",
            )
        )
        assert result.unavailable_dimensions == ("dmissing",)
        assert any(r.id == "repo.dmissing.module_unavailable" for r in result.results)
        assert any(r.verdict is Verdict.COULD_NOT_RUN for r in result.results)

    def test_a_crashing_module_still_produces_a_per_repo_could_not_run(
        self, tmp_path, monkeypatch
    ):
        root = tmp_path / "Sites"
        _make_group_repo(root, "COPILOT", "widget-app", git=True)

        def _boom(context):
            raise RuntimeError("simulated dimension bug")

        registry = Registry()
        stub_modules = (
            DimensionModule(name="dbroken", module=SimpleNamespace(run=_boom)),
        )
        monkeypatch.setattr(
            sweep_mod, "discover_dimension_modules", lambda: stub_modules
        )

        result = run_sweep(
            SweepOptions(
                roots=(root,),
                registry=registry,
                jobs=1,
                cache_path=tmp_path / "cache.json",
                classification_path=tmp_path / "no-such-classification.toml",
            )
        )
        crashed = [r for r in result.results if r.id == "repo.dbroken.crashed"]
        assert len(crashed) == 1
        assert crashed[0].verdict is Verdict.COULD_NOT_RUN
        assert crashed[0].subject.endswith("widget-app")

    def test_parallel_execution_with_jobs_greater_than_one_matches_serial(
        self, tmp_path, monkeypatch
    ):
        root = tmp_path / "Sites"
        for name in ("alpha", "beta", "gamma"):
            _make_group_repo(root, "COPILOT", name, git=True)

        registry = Registry()
        registration = self._register_stub_check(registry)
        self._install_stub_dimension(monkeypatch, registration)

        serial = run_sweep(
            SweepOptions(
                roots=(root,),
                registry=registry,
                jobs=1,
                cache_path=tmp_path / "cache-serial.json",
                classification_path=tmp_path / "no-such-classification.toml",
            )
        )
        # NOTE: process-pool workers re-import this module fresh, so the
        # monkeypatched `discover_dimension_modules` above does not apply
        # inside them -- this exercises the REAL (possibly empty, possibly
        # sibling-populated) dimensions/ package for the parallel path,
        # asserting only that parallel execution completes and aggregates
        # without raising, never a specific verdict count.
        parallel = run_sweep(
            SweepOptions(
                roots=(root,),
                registry=registry,
                jobs=3,
                cache_path=tmp_path / "cache-parallel.json",
                classification_path=tmp_path / "no-such-classification.toml",
            )
        )
        assert serial.repos_discovered == parallel.repos_discovered == 3
        assert serial.repos_selected == parallel.repos_selected == 3


# ---------------------------------------------------------------------------
# World B -- the real machine. Read-only: `discover_repos()` only ever
# calls `Path.iterdir()`/`Path.exists()`/`Path.resolve()`, never a git
# subprocess, so it is trivially safe under the autouse tripwire this
# suite already inherits (conftest.py's `_conformance_machine_readonly_tripwire`).
# ---------------------------------------------------------------------------


@pytest.mark.machine
class TestRealFleetDiscovery:
    @pytest.fixture
    def real_roots(self, monkeypatch) -> tuple[Path, ...]:
        """World-B tests need `resolve_key("projects.roots")` to resolve
        against the REAL machine config -- but `tests/conftest.py`'s
        autouse `_isolate_machine_config` fixture redirects `CC_MACHINE_ROOT`
        to an empty `tmp_path` for every test by default (deliberately, to
        make it structurally impossible for an ordinary test to touch real
        machine state). Un-set that redirect for the duration of THIS
        fixture only; `monkeypatch` reverts it automatically at teardown,
        restoring the isolated default for every other test in the suite.
        This is a READ-ONLY relaxation -- only `resolve_key()` reads
        through it here, nothing writes -- and `discover_repos()` itself
        never touches `CC_MACHINE_ROOT` at all once it has a `roots` list.
        """

        monkeypatch.delenv("CC_MACHINE_ROOT", raising=False)
        from cc.core.config import resolve_key

        roots = resolve_key("projects.roots") or []
        return tuple(Path(root) for root in roots)

    def test_discovers_every_classified_repo(self, real_roots):
        # Deliberately NOT a hardcoded exact count (that was
        # `test_discovers_the_audited_seventy_five_repos`'s original shape,
        # pinned to the 2026-08-10 audit's "76 scanned directories, 75
        # real"). Live machine state legitimately drifts as repos are
        # cloned, removed, or added under /Volumes/Dev/Sites between one
        # test run and the next -- `HARNESS-DESIGN.md` section 7
        # Untestable #6 says exactly this: a real-fleet sweep is
        # "inherently non-deterministic across machines/time as repos
        # change." An exact `== 75` assertion against that live count is
        # therefore not a conformance regression when it flips -- it is a
        # test-design bug, and multiple work packages independently
        # reported it as the cause of this suite's intermittent failures.
        #
        # The invariant that DOES hold, reproducibly, on every run: every
        # repo the owner has already classified (`classification.toml`,
        # committed and reviewed -- not live disk state) must still be
        # discoverable. A classified repo silently dropping out of
        # discovery is a real regression in `discover_repos()`'s walk; an
        # unclassified scratch directory appearing or disappearing is not
        # this test's business (it falls through to `compute_default()`).
        root = real_roots[0]
        classified = classes.load_classification_table()
        discovered_keys = {
            classes.repo_key(repo.path, root) for repo in discover_repos(real_roots)
        }
        missing = set(classified) - discovered_keys
        assert not missing, (
            f"{len(missing)} classified repo(s) in classification.toml are "
            f"no longer discoverable under {root}: {sorted(missing)} -- "
            "either the repo was removed (update classification.toml to "
            "match) or discover_repos()'s walk regressed."
        )

    def test_archive_and_movies_are_discovered_as_non_git_roots(self, real_roots):
        # Was `test_playground_and_investr_api_are_discovered_as_non_git_
        # roots`. Re-verified live 2026-08-11: both `playground` and
        # `investr-api` were git-initialized on this machine (unrelated to
        # RC-1/RC-4 fan-out -- both now have a real `.git/`), so they no
        # longer illustrate this capability. Swapped to two directories
        # that are currently non-git on this machine and are not part of
        # any sanctioned installer's write surface, following the same
        # "the precedent moved, swap it and say why" pattern
        # `TestMachineTruthUniqueness.test_li1_reproduces_the_two_real_hash_
        # clusters` used for sproutworks -> copilot-control-tower. The
        # underlying capability (discover a directory with no `.git` at
        # all, never silently skip it) stays independently, deterministically
        # proven by the synthetic `TestDiscoverRepos.test_includes_non_git_
        # directories` above, which this real-machine test only corroborates.
        discovered = {str(repo.path): repo for repo in discover_repos(real_roots)}
        archive = discovered.get("/Volumes/Dev/Sites/COPILOT/_archive")
        movies = discovered.get("/Volumes/Dev/Sites/PERSONAL/movies")
        assert archive is not None and archive.is_git_root is False
        assert movies is not None and movies.is_git_root is False

    def test_shared_docs_dedupes_into_knowledge_copilot_internal(self, real_roots):
        discovered = {str(repo.path): repo for repo in discover_repos(real_roots)}
        target = discovered["/Volumes/Dev/Sites/CSE/knowledge-copilot-internal"]
        assert target.raw_count == 2
        alias_names = {alias.name for alias in target.aliases}
        assert alias_names == {"knowledge-copilot-internal", "shared-docs"}

    def test_discovery_makes_no_git_subprocess_calls(self, monkeypatch):
        def _forbidden(*args, **kwargs):
            raise AssertionError(
                "discover_repos() must be a pure filesystem walk -- it must "
                "never shell out to git."
            )

        monkeypatch.setattr(subprocess, "run", _forbidden)
        # An explicit `roots=` bypasses `resolve_key()` entirely (which
        # itself may shell out as part of `cc`'s own unrelated project-scope
        # config resolution) -- this isolates the assertion strictly to
        # `discover_repos()`'s own body, which must never call subprocess.
        discover_repos([Path("/Volumes/Dev/Sites")])  # must not raise
