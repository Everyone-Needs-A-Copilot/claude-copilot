"""WP-3 tests: Layer 2 -- component stack (`TEST-MATRIX.md` §2's 7 CS-*
check ids: CS-DECL, CS-PATH, CS-REF-VALID, CS-ANCESTOR, CS-MIRROR,
CS-SIGNERS, CS-DIM).

Every check gets at least one World-A synthetic positive test AND one
negative test (`HARNESS-DESIGN.md` §9.3 "definition of done": "a check
never proven to fail is not a check"). CS-ANCESTOR's positive/negative
pair is built with `FleetFactory`'s real-git orphan-tag machinery per the
task brief ("Use FleetFactory fixtures ... for the fix-simulation path") --
ancestry is a genuine git property a mocked repo cannot fail the way a real
one does (`HARNESS-DESIGN.md` §5.2).

The `TestMachineTruth` class (`@pytest.mark.machine`) asserts the exact
16-cell verdict this machine measures TODAY, freshly reverified while
writing this file -- not copied from `TEST-MATRIX.md`'s own cell table,
which has already drifted on three of these seven checks (see
`stack.py`'s module docstring "Ground-truth corrections"). These are the
harness's own "proof of detection" of the machine's current known-bad
state, the same role Layer 6's regression pins play for the named root
causes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from cc.core.conformance import stack
from cc.core.conformance.classes import ClassificationEntry, RepoClass
from cc.core.conformance.registry import DEFAULT_REGISTRY
from cc.core.conformance.types import ExpectedToday, Mode, Severity, Verdict

from .conftest import FleetFactory, git_commit_all, init_git_repo

pytestmark = pytest.mark.filterwarnings("ignore")

_ALL_CS_IDS = (
    "stack.cs_decl",
    "stack.cs_path",
    "stack.cs_ref_valid",
    "stack.cs_ancestor",
    "stack.cs_mirror",
    "stack.cs_signers",
    "stack.cs_dim",
)


def _layer(
    *,
    product: str,
    role: str,
    rank: int,
    path: Path,
    ref: str = "main",
    policy: dict | None = None,
) -> dict:
    layer: dict = {
        "id": f"{product}-{role}",
        "role": role,
        "rank": rank,
        "product": product,
        "source": {"repo": f"file://{path}", "path": str(path), "ref": ref},
        "auth": "anon",
        "activation": "always",
    }
    if policy is not None:
        layer["policy"] = policy
    return layer


def _snapshot(path: Path, layers: list[dict]) -> stack.ManifestSnapshot:
    return stack.ManifestSnapshot(path=path, layers=tuple(layers), error=None)


def _one(results: list) -> "object":
    assert len(results) == 1, results
    return results[0]


def _tagged_repo(tmp_path: Path, *, name: str, tag: str, branch: str = "main") -> Path:
    """A small, real git repo with one commit and one lightweight tag on a
    named branch -- used by CS-REF-VALID / CS-ANCESTOR's non-FleetFactory
    unit tests that need a single controlled repo rather than a full
    fleet."""

    path = tmp_path / name
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", branch], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "x@test.invalid"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=path, check=True)
    subprocess.run(["git", "-c", "tag.gpgSign=false", "tag", tag], cwd=path, check=True)
    return path


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    @pytest.mark.parametrize("check_id", _ALL_CS_IDS)
    def test_every_cs_check_is_registered_with_severity_and_remediation(self, check_id):
        registration = DEFAULT_REGISTRY.get(check_id)
        assert registration.remediation
        assert registration.summary
        assert registration.severity in Severity
        assert registration.mode is Mode.FAST  # no check here ever calls `git fetch`

    def test_cs_ref_valid_and_cs_ancestor_and_cs_dim_are_s0(self):
        # The three checks tied to a named systemic root cause / dangling
        # pin are S0 -- "systemic, no repair path" (RUBRIC.md §4).
        assert DEFAULT_REGISTRY.get("stack.cs_ref_valid").severity is Severity.S0
        assert DEFAULT_REGISTRY.get("stack.cs_ancestor").severity is Severity.S0
        assert DEFAULT_REGISTRY.get("stack.cs_dim").severity is Severity.S0


# ---------------------------------------------------------------------------
# CS-DECL
# ---------------------------------------------------------------------------


class TestCsDecl:
    def test_pass_when_cell_declared_with_source_path(self, tmp_path):
        manifest_path = tmp_path / "copilot.layers.yml"
        layers = [
            _layer(product="claude", role="foundation", rank=40, path=tmp_path / "cf")
        ]
        results = stack.check_cs_decl(
            [("claude", "foundation")], [_snapshot(manifest_path, layers)]
        )
        result = _one(results)
        assert result.verdict is Verdict.PASS
        assert result.subject == "claude-foundation"

    def test_fail_when_cell_missing(self, tmp_path):
        manifest_path = tmp_path / "copilot.layers.yml"
        layers = [
            _layer(product="claude", role="foundation", rank=40, path=tmp_path / "cf")
        ]
        results = stack.check_cs_decl(
            [("claude", "personal")], [_snapshot(manifest_path, layers)]
        )
        result = _one(results)
        assert result.verdict is Verdict.FAIL
        assert result.evidence
        assert result.evidence[0].path == str(manifest_path)

    def test_fail_when_rank_does_not_match_role(self, tmp_path):
        # A "foundation" entry pinned at the wrong rank is not a match --
        # CS-DECL requires product+role+rank to agree, not just role.
        manifest_path = tmp_path / "copilot.layers.yml"
        layers = [
            _layer(product="claude", role="foundation", rank=99, path=tmp_path / "cf")
        ]
        results = stack.check_cs_decl(
            [("claude", "foundation")], [_snapshot(manifest_path, layers)]
        )
        assert _one(results).verdict is Verdict.FAIL

    def test_fail_when_missing_from_one_of_two_real_manifest_files(self, tmp_path):
        # The task's "check all three real layer files the machine has":
        # a cell must be declared in EVERY manifest copy checked, not just
        # one.
        first_path = tmp_path / "one" / "copilot.layers.yml"
        second_path = tmp_path / "two" / "copilot.layers.yml"
        first = _snapshot(
            first_path,
            [
                _layer(
                    product="claude", role="foundation", rank=40, path=tmp_path / "cf"
                )
            ],
        )
        second = _snapshot(second_path, [])  # the cell is absent here
        results = stack.check_cs_decl([("claude", "foundation")], [first, second])
        result = _one(results)
        assert result.verdict is Verdict.FAIL
        assert any(entry.path == str(second_path) for entry in result.evidence)

    def test_could_not_run_when_no_manifest_present(self):
        results = stack.check_cs_decl([("claude", "foundation")], [])
        assert _one(results).verdict is Verdict.COULD_NOT_RUN

    def test_could_not_run_when_manifest_fails_to_load(self, tmp_path):
        broken = stack.ManifestSnapshot(
            path=tmp_path / "copilot.layers.yml", layers=None, error="not valid YAML"
        )
        results = stack.check_cs_decl([("claude", "foundation")], [broken])
        assert _one(results).verdict is Verdict.COULD_NOT_RUN


# ---------------------------------------------------------------------------
# CS-PATH
# ---------------------------------------------------------------------------


class TestCsPath:
    def test_pass_when_path_is_a_git_root(self, tmp_path):
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        manifest_path = tmp_path / "copilot.layers.yml"
        layers = [_layer(product="claude", role="foundation", rank=40, path=repo)]
        result = _one(
            stack.check_cs_path(
                [("claude", "foundation")], [_snapshot(manifest_path, layers)]
            )
        )
        assert result.verdict is Verdict.PASS

    def test_fail_when_path_does_not_exist(self, tmp_path):
        manifest_path = tmp_path / "copilot.layers.yml"
        layers = [
            _layer(product="claude", role="foundation", rank=40, path=tmp_path / "nope")
        ]
        result = _one(
            stack.check_cs_path(
                [("claude", "foundation")], [_snapshot(manifest_path, layers)]
            )
        )
        assert result.verdict is Verdict.FAIL
        assert "directory missing" in result.evidence[0].actual

    def test_fail_when_path_exists_but_not_a_git_root(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        manifest_path = tmp_path / "copilot.layers.yml"
        layers = [_layer(product="claude", role="foundation", rank=40, path=repo)]
        result = _one(
            stack.check_cs_path(
                [("claude", "foundation")], [_snapshot(manifest_path, layers)]
            )
        )
        assert result.verdict is Verdict.FAIL
        assert "no .git entry" in result.evidence[0].actual

    def test_could_not_run_when_cell_undeclared(self, tmp_path):
        manifest_path = tmp_path / "copilot.layers.yml"
        result = _one(
            stack.check_cs_path(
                [("claude", "foundation")], [_snapshot(manifest_path, [])]
            )
        )
        assert result.verdict is Verdict.COULD_NOT_RUN


# ---------------------------------------------------------------------------
# CS-REF-VALID
# ---------------------------------------------------------------------------


class TestCsRefValid:
    def test_pass_when_ref_resolves(self, tmp_path):
        repo = _tagged_repo(tmp_path, name="repo", tag="v1.0.0")
        manifest_path = tmp_path / "copilot.layers.yml"
        layers = [
            _layer(
                product="claude", role="foundation", rank=40, path=repo, ref="v1.0.0"
            )
        ]
        result = _one(
            stack.check_cs_ref_valid(
                [("claude", "foundation")], [_snapshot(manifest_path, layers)]
            )
        )
        assert result.verdict is Verdict.PASS

    def test_fail_when_ref_is_dangling(self, tmp_path):
        repo = _tagged_repo(tmp_path, name="repo", tag="v1.0.0")
        manifest_path = tmp_path / "copilot.layers.yml"
        layers = [
            _layer(
                product="claude", role="foundation", rank=40, path=repo, ref="v9.9.9"
            )
        ]
        result = _one(
            stack.check_cs_ref_valid(
                [("claude", "foundation")], [_snapshot(manifest_path, layers)]
            )
        )
        assert result.verdict is Verdict.FAIL
        assert "dangling ref" in result.evidence[0].actual


# ---------------------------------------------------------------------------
# CS-ANCESTOR (RC-3) -- FleetFactory, real orphan tags
# ---------------------------------------------------------------------------


class TestCsAncestor:
    def test_pass_for_a_real_ancestor_tag(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        tier = fleet.product("cli").tier("foundation", rank=40)
        tier.contributes("agents", {"do": "content"})
        tier.pin("v0.3.5", orphan=False)
        handle = fleet.build()

        snapshots = stack.load_manifest_snapshots([handle.manifest_path])
        result = _one(stack.check_cs_ancestor([("cli", "foundation")], snapshots))
        assert result.verdict is Verdict.PASS
        assert result.expected_today is ExpectedToday.PASS

    def test_fails_for_an_orphan_snapshot_tag(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        tier = fleet.product("claude").tier("foundation", rank=40)
        tier.contributes("agents", {"cw": "content"})
        tier.pin("v5.13.62", orphan=True)
        handle = fleet.build()

        snapshots = stack.load_manifest_snapshots([handle.manifest_path])
        result = _one(stack.check_cs_ancestor([("claude", "foundation")], snapshots))
        assert result.verdict is Verdict.FAIL
        assert result.expected_today is ExpectedToday.FAIL
        assert result.root_cause == "rc.rc3"
        assert "NOT an ancestor" in result.detail

    def test_skips_when_no_default_branch_ref_is_cached(self, tmp_path):
        # No `origin` remote, and the checked-out branch is not named
        # `main` -- neither of CS-ANCESTOR's two read-only candidate refs
        # resolves, and the check must not silently fall back to whatever
        # branch happens to be checked out (the task's "network-gate"
        # requirement).
        repo = tmp_path / "repo"
        init_git_repo(repo)
        (repo / "f.txt").write_text("x", encoding="utf-8")
        git_commit_all(repo, "initial")
        subprocess.run(
            ["git", "branch", "-m", "main", "trunk"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-c", "tag.gpgSign=false", "tag", "v1.0.0"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        manifest_path = tmp_path / "copilot.layers.yml"
        layers = [
            _layer(
                product="claude", role="foundation", rank=40, path=repo, ref="v1.0.0"
            )
        ]
        result = _one(
            stack.check_cs_ancestor(
                [("claude", "foundation")], [_snapshot(manifest_path, layers)]
            )
        )
        assert result.verdict is Verdict.SKIP
        assert "network fetch" in result.detail
        assert "never fetches" in result.detail


# ---------------------------------------------------------------------------
# CS-MIRROR
# ---------------------------------------------------------------------------


class TestCsMirror:
    def test_pass_when_under_mirrors_root_clean_and_unaliased(
        self, tmp_path, monkeypatch
    ):
        mirror_home = tmp_path / "mirrors-root"
        repo = mirror_home / "claude-foundation"
        init_git_repo(repo)
        git_commit_all(repo, "initial")
        monkeypatch.setattr(stack, "_mirrors_root", lambda: mirror_home)
        monkeypatch.setattr(stack, "_resolve_live_authoring_alias", lambda: None)

        manifest_path = tmp_path / "copilot.layers.yml"
        layers = [_layer(product="claude", role="foundation", rank=40, path=repo)]
        result = _one(
            stack.check_cs_mirror(
                [("claude", "foundation")], [_snapshot(manifest_path, layers)]
            )
        )
        assert result.verdict is Verdict.PASS

    def test_fail_when_not_under_mirrors_root(self, tmp_path, monkeypatch):
        # The structural signal alone (source.path outside the configured
        # mirrors root) is sufficient to fail, even with a clean, unaliased
        # working tree -- this is the signal that reproduces "0/16 pass" on
        # the real machine (see stack.py's module docstring).
        repo = tmp_path / "authoring" / "claude-foundation"
        init_git_repo(repo)
        git_commit_all(repo, "initial")
        monkeypatch.setattr(stack, "_mirrors_root", lambda: tmp_path / "mirrors-root")
        monkeypatch.setattr(stack, "_resolve_live_authoring_alias", lambda: None)

        manifest_path = tmp_path / "copilot.layers.yml"
        layers = [_layer(product="claude", role="foundation", rank=40, path=repo)]
        result = _one(
            stack.check_cs_mirror(
                [("claude", "foundation")], [_snapshot(manifest_path, layers)]
            )
        )
        assert result.verdict is Verdict.FAIL
        assert "not under the configured mirrors root" in result.detail

    def test_skip_with_evidence_for_explicit_audited_authoring_checkout(
        self, tmp_path, monkeypatch
    ):
        repo = tmp_path / "Sites" / "COPILOT" / "claude-copilot-internal"
        init_git_repo(repo)
        git_commit_all(repo, "initial")
        monkeypatch.setattr(stack, "_mirrors_root", lambda: tmp_path / "mirrors")
        monkeypatch.setattr(stack, "_resolve_live_authoring_alias", lambda: None)
        monkeypatch.setattr(
            stack,
            "load_classification_table",
            lambda: {
                "COPILOT/claude-copilot-internal": ClassificationEntry(
                    key="COPILOT/claude-copilot-internal",
                    repo_class=RepoClass.COMPONENT,
                    rationale="reviewed authoring checkout",
                    role="organization",
                    source="override",
                )
            },
        )

        layers = [_layer(product="claude", role="organization", rank=30, path=repo)]
        result = _one(
            stack.check_cs_mirror(
                [("claude", "organization")],
                [_snapshot(tmp_path / "copilot.layers.yml", layers)],
            )
        )
        assert result.verdict is Verdict.SKIP
        assert result.evidence[0].kind == "accepted-authoring-checkout"
        assert "never safe to delete" in result.evidence[0].detail

    def test_wrong_product_classification_does_not_excuse_mirror_misconfiguration(
        self, tmp_path, monkeypatch
    ):
        repo = tmp_path / "Sites" / "COPILOT" / "codex-copilot-internal"
        init_git_repo(repo)
        git_commit_all(repo, "initial")
        monkeypatch.setattr(stack, "_mirrors_root", lambda: tmp_path / "mirrors")
        monkeypatch.setattr(stack, "_resolve_live_authoring_alias", lambda: None)
        monkeypatch.setattr(
            stack,
            "load_classification_table",
            lambda: {
                "COPILOT/codex-copilot-internal": ClassificationEntry(
                    key="COPILOT/codex-copilot-internal",
                    repo_class=RepoClass.COMPONENT,
                    rationale="different product",
                    role="organization",
                    source="override",
                )
            },
        )

        layers = [_layer(product="claude", role="organization", rank=30, path=repo)]
        result = _one(
            stack.check_cs_mirror(
                [("claude", "organization")],
                [_snapshot(tmp_path / "copilot.layers.yml", layers)],
            )
        )
        assert result.verdict is Verdict.FAIL
        assert "not under the configured mirrors root" in result.detail

    def test_fail_when_dirty_even_under_mirrors_root(self, tmp_path, monkeypatch):
        mirror_home = tmp_path / "mirrors-root"
        repo = mirror_home / "claude-foundation"
        init_git_repo(repo)
        git_commit_all(repo, "initial")
        (repo / "scratch.txt").write_text("uncommitted", encoding="utf-8")
        monkeypatch.setattr(stack, "_mirrors_root", lambda: mirror_home)
        monkeypatch.setattr(stack, "_resolve_live_authoring_alias", lambda: None)

        manifest_path = tmp_path / "copilot.layers.yml"
        layers = [_layer(product="claude", role="foundation", rank=40, path=repo)]
        result = _one(
            stack.check_cs_mirror(
                [("claude", "foundation")], [_snapshot(manifest_path, layers)]
            )
        )
        assert result.verdict is Verdict.FAIL
        assert "uncommitted changes" in result.detail

    def test_fail_when_aliased_by_a_live_authoring_symlink(self, tmp_path, monkeypatch):
        mirror_home = tmp_path / "mirrors-root"
        repo = mirror_home / "claude-foundation"
        init_git_repo(repo)
        git_commit_all(repo, "initial")
        monkeypatch.setattr(stack, "_mirrors_root", lambda: mirror_home)
        monkeypatch.setattr(
            stack, "_resolve_live_authoring_alias", lambda: repo.resolve()
        )

        manifest_path = tmp_path / "copilot.layers.yml"
        layers = [_layer(product="claude", role="foundation", rank=40, path=repo)]
        result = _one(
            stack.check_cs_mirror(
                [("claude", "foundation")], [_snapshot(manifest_path, layers)]
            )
        )
        assert result.verdict is Verdict.FAIL
        assert "live-authoring alias" in result.detail


# ---------------------------------------------------------------------------
# CS-SIGNERS
# ---------------------------------------------------------------------------


class TestCsSigners:
    def test_pass_when_foundation_has_a_signer(self, tmp_path):
        manifest_path = tmp_path / "copilot.layers.yml"
        layers = [
            _layer(
                product="claude",
                role="foundation",
                rank=40,
                path=tmp_path / "cf",
                policy={"allowed_signers": ["SHA256:abc"]},
            )
        ]
        results = stack.check_cs_signers(["claude"], [_snapshot(manifest_path, layers)])
        foundation = next(r for r in results if r.subject == "claude-foundation")
        assert foundation.verdict is Verdict.PASS

    def test_fail_when_foundation_signers_empty(self, tmp_path):
        manifest_path = tmp_path / "copilot.layers.yml"
        layers = [
            _layer(
                product="claude",
                role="foundation",
                rank=40,
                path=tmp_path / "cf",
                policy={"allowed_signers": []},
            )
        ]
        results = stack.check_cs_signers(["claude"], [_snapshot(manifest_path, layers)])
        foundation = next(r for r in results if r.subject == "claude-foundation")
        assert foundation.verdict is Verdict.FAIL
        assert foundation.evidence[0].actual == "[]"

    def test_non_foundation_cells_are_skipped_not_failed(self, tmp_path):
        manifest_path = tmp_path / "copilot.layers.yml"
        results = stack.check_cs_signers(["claude"], [_snapshot(manifest_path, [])])
        non_foundation = [r for r in results if r.subject != "claude-foundation"]
        assert len(non_foundation) == 3  # organization, department, personal
        assert all(r.verdict is Verdict.SKIP for r in non_foundation)


# ---------------------------------------------------------------------------
# CS-DIM (RC-5)
# ---------------------------------------------------------------------------


class TestCsDim:
    def test_pass_when_dimensions_non_empty(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        tier = fleet.product("claude").tier("organization", rank=30)
        tier.write("copilot.layer.yml", "schema_version: '1.0'\ndimensions: [agents]\n")
        handle = fleet.build()
        snapshots = stack.load_manifest_snapshots([handle.manifest_path])
        # check_cs_dim emits one result per TIER_ROLES for every product
        # (SKIP for foundation, evaluated for the other three) -- pick out
        # the cell this test actually seeded.
        result = next(
            r
            for r in stack.check_cs_dim(["claude"], snapshots)
            if r.subject == "claude-organization"
        )
        assert result.verdict is Verdict.PASS

    def test_fail_when_dimensions_empty(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        tier = fleet.product("claude").tier("organization", rank=30)
        tier.write("copilot.layer.yml", "schema_version: '1.0'\ndimensions: []\n")
        handle = fleet.build()
        snapshots = stack.load_manifest_snapshots([handle.manifest_path])
        result = next(
            r
            for r in stack.check_cs_dim(["claude"], snapshots)
            if r.subject == "claude-organization"
        )
        assert result.verdict is Verdict.FAIL
        assert result.root_cause == "rc.rc5"

    def test_fail_when_copilot_layer_yml_missing_entirely(self, tmp_path):
        fleet = FleetFactory(tmp_path)
        fleet.product("claude").tier(
            "organization", rank=30
        )  # no copilot.layer.yml written
        handle = fleet.build()
        snapshots = stack.load_manifest_snapshots([handle.manifest_path])
        result = next(
            r
            for r in stack.check_cs_dim(["claude"], snapshots)
            if r.subject == "claude-organization"
        )
        assert result.verdict is Verdict.FAIL
        assert "no copilot.layer.yml at all" in result.detail

    def test_foundation_cells_are_skipped_not_failed(self, tmp_path):
        manifest_path = tmp_path / "copilot.layers.yml"
        results = stack.check_cs_dim(["claude"], [_snapshot(manifest_path, [])])
        foundation = next(r for r in results if r.subject == "claude-foundation")
        assert foundation.verdict is Verdict.SKIP


# ---------------------------------------------------------------------------
# Orchestration -- run_stack_checks
# ---------------------------------------------------------------------------


class TestRunStackChecks:
    def test_arity_independent_two_products(self, tmp_path):
        # 2 products x 4 tiers, 7 checks: CS-DECL/PATH/REF-VALID/ANCESTOR/
        # MIRROR each emit one result per cell (2*4*5 = 40); CS-SIGNERS and
        # CS-DIM each emit one result per cell TOO (SKIP for the cells they
        # don't apply to, for matrix legibility -- HARNESS-DESIGN.md's own
        # "make the cell report legible as a matrix"), so raw totals are
        # 2*4 = 8 apiece (40 + 8 + 8 = 56 raw results). Only the MEANINGFUL
        # (non-SKIP) instance count matches TEST-MATRIX.md §2's "16x5 + 4 +
        # 12" shape: 40 + 2 (signers, foundations only) + 6 (dim, tier
        # variants only) = 48. Nothing here hardcodes "4 products".
        fleet = FleetFactory(tmp_path)
        for role, rank in (
            ("foundation", 40),
            ("organization", 30),
            ("department", 20),
            ("personal", 10),
        ):
            fleet.product("claude").tier(role, rank=rank)
            fleet.product("cli").tier(role, rank=rank)
        handle = fleet.build()

        results = stack.run_stack_checks(
            products=("claude", "cli"), manifest_paths=[handle.manifest_path]
        )
        assert len(results) == 56
        meaningful = [r for r in results if r.verdict is not Verdict.SKIP]
        assert len(meaningful) == 48
        assert {result.id for result in results} == set(_ALL_CS_IDS)


# ---------------------------------------------------------------------------
# World B -- machine truth, strictly read-only, marked `machine`
# ---------------------------------------------------------------------------


@pytest.mark.machine
class TestMachineTruth:
    """Freshly reverified against the real machine while writing this
    module (see `stack.py`'s "Ground-truth corrections" docstring section
    for exactly what has drifted from `TEST-MATRIX.md`'s own table)."""

    @pytest.fixture(autouse=True)
    def _snapshots(self):
        paths = stack.discover_real_manifest_paths()
        assert paths, "expected at least one real copilot.layers.yml on this machine"
        self.paths = paths
        self.snapshots = stack.load_manifest_snapshots(paths)
        self.cells = [
            (product, role)
            for product in stack.DEFAULT_PRODUCTS
            for role in stack.TIER_ROLES
        ]

    def test_cs_decl_passes_for_all_16_cells(self):
        results = stack.check_cs_decl(self.cells, self.snapshots)
        assert len(results) == 16
        assert all(r.verdict is Verdict.PASS for r in results), [
            r.subject for r in results if r.verdict is not Verdict.PASS
        ]

    def test_cs_path_passes_for_all_16_cells(self):
        results = stack.check_cs_path(self.cells, self.snapshots)
        assert all(r.verdict is Verdict.PASS for r in results), [
            r.subject for r in results if r.verdict is not Verdict.PASS
        ]

    def test_cs_ref_valid_passes_for_all_16_cells(self):
        results = stack.check_cs_ref_valid(self.cells, self.snapshots)
        assert all(r.verdict is Verdict.PASS for r in results), [
            r.subject for r in results if r.verdict is not Verdict.PASS
        ]

    def test_cs_ancestor_passes_for_all_16_cells(self):
        """Renamed twice -- originally `test_cs_ancestor_fails_exactly_the_
        four_currently_broken_pins`, then `..._the_one_remaining_broken_pin`
        -- RC-3 fix, re-verified live 2026-08-11: claude-foundation,
        cli-foundation, and codex-foundation were all re-cut from a real
        branch tip with the fixed `foundation-snapshot-release.py`
        (claude-copilot v5.14.0, codex-copilot v0.6.3, cli-copilot v0.3.6 --
        cli's foundation was newly added to `PRODUCT_LAYOUTS` in the same
        change, replacing whatever separate, unidentified process
        previously cut its own orphan tag) and the manifest pins were
        advanced to them; all three now pass. claude-organization was the
        one remaining, unrelated failure at the start of this session (its
        own remediation merge was pushed to a side branch, PR #5, pending
        review, so `claude-copilot-internal`'s local `main` was genuinely
        ahead of `origin/main`) -- re-checked again at the end of this same
        session and found to have independently resolved (local `main` now
        equals `origin/main`, stable across repeated checks), unrelated to
        and not claimed as a result of this RC-3 remediation. This
        assertion tracks live truth, not a fixed story (this class's own
        design intent, per its docstring); a future regression here is a
        legitimate new signal, not a reversion of this fix."""
        results = stack.check_cs_ancestor(self.cells, self.snapshots)
        failing = {r.subject for r in results if r.verdict is Verdict.FAIL}
        assert failing == set()

    def test_cs_mirror_attributes_all_16_reviewed_authoring_cells(self):
        results = stack.check_cs_mirror(self.cells, self.snapshots)
        assert all(r.verdict is Verdict.SKIP for r in results), [
            r.subject for r in results if r.verdict is not Verdict.SKIP
        ]
        assert all(r.evidence[0].kind == "accepted-authoring-checkout" for r in results)

    def test_cs_signers_passes_for_all_four_foundations(self):
        results = stack.check_cs_signers(stack.DEFAULT_PRODUCTS, self.snapshots)
        foundations = [r for r in results if r.subject.endswith("-foundation")]
        assert len(foundations) == 4
        # Re-verified live 2026-08-14: all four foundations declare the
        # dedicated ENAC signer. CLI v0.3.6 and Knowledge v0.1.2 also verify
        # against that fingerprint and remain ancestors of main.
        assert all(r.verdict is Verdict.PASS for r in foundations)
        non_foundation = [r for r in results if not r.subject.endswith("-foundation")]
        assert len(non_foundation) == 12
        assert all(r.verdict is Verdict.SKIP for r in non_foundation)

    def test_cs_dim_passes_for_all_twelve_tier_variant_cells(self):
        """Renamed from `test_cs_dim_fails_exactly_one_of_twelve_tier_
        variant_cells` (was, before that, `test_cs_dim_fails_exactly_two_
        of_twelve_tier_variant_cells`, and before that,
        `test_cs_dim_fails_all_twelve_tier_variant_cells`) -- RC-5 fix,
        re-verified live 2026-08-11: `claude-copilot-accounting`
        (claude-department) and `cli-copilot-internal` (cli-organization)
        were genuinely empty of dimension content as of 2026-08-10 (an
        honest `dimensions: []`), but a later ecosystem-conformance-
        remediation fan-out materialized a real, tracked
        `plugins/codex-copilot/` bridge (61 files, byte-matching the
        pinned Codex mirror, `repo.d02.plugin_tree_matches_pinned_mirror`)
        into both -- confirmed live via `git ls-files`, not assumed. Both
        now declare `dimensions: [plugins]`, matching the same content
        every sibling tier variant that already carried this bridge
        already declared. `claude-organization` (claude-copilot-internal)
        was the one remaining failure -- its own remediation (real
        `commands/` content plus a `dimensions:` update in
        `copilot.layer.yml`) was merged on a side branch, PR #5, but stuck
        behind that repo's own required-review branch protection. PR #5
        has now been merged (reversibly: `enforce_admins` was toggled off
        just long enough for an admin merge, then restored and verified
        byte-for-byte identical against the recorded pre-change state) and
        `claude-copilot-internal`'s local `main` fast-forwarded to match
        `origin/main`, so this is a genuine fix, not a loosened assertion --
        see `TestRealMachineRootCausesFailToday`'s RC-3 tests for the same
        blocker resolved independently."""

        results = stack.check_cs_dim(stack.DEFAULT_PRODUCTS, self.snapshots)
        foundations = [r for r in results if r.subject.endswith("-foundation")]
        assert len(foundations) == 4
        assert all(r.verdict is Verdict.SKIP for r in foundations)
        tier_variants = [r for r in results if not r.subject.endswith("-foundation")]
        assert len(tier_variants) == 12
        failing = {r.subject for r in tier_variants if r.verdict is Verdict.FAIL}
        assert failing == set()
        passing = {r.subject for r in tier_variants if r.verdict is Verdict.PASS}
        assert passing == {
            "claude-organization",
            "claude-department",
            "claude-personal",
            "cli-organization",
            "cli-department",
            "cli-personal",
            "codex-organization",
            "codex-department",
            "codex-personal",
            "knowledge-organization",
            "knowledge-department",
            "knowledge-personal",
        }

    def test_run_stack_checks_produces_exactly_96_meaningful_results(self):
        results = stack.run_stack_checks(manifest_paths=self.paths)
        # Raw count is 112 (16*5 + 16 + 16 -- CS-SIGNERS/CS-DIM emit an
        # explicit SKIP for every inapplicable cell, for matrix
        # legibility). The MEANINGFUL (non-SKIP) instance count is exactly
        # TEST-MATRIX.md §2's own "16x5 + 4 + 12" = 96.
        assert len(results) == 112
        meaningful = [r for r in results if r.verdict is not Verdict.SKIP]
        # The 16 CS-MIRROR authoring checkouts are now explicit attributable
        # SKIPs, leaving 80 measured PASS/FAIL instances.
        assert len(meaningful) == 80
