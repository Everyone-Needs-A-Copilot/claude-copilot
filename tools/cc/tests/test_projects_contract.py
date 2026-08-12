"""WS-A contract test: Component Sync Stream-E -- machine-wide fan-out sync.

Schema sources of truth: copilot-control-tower/docs/01-architecture/schemas/
projects.schema.json (new) + update.schema.json's additive `path` property.
Vendored copies: tests/fixtures/schemas/ (same precedent as
test_update_contract.py / test_freshness_contract.py).

Every I/O root here is tmp_path-injected (project roots, the explicit-
project registry, the mirror/source content root, the advisory lock mutex
path) -- the `_no_real_home` autouse fixture additionally asserts
`Path.home()` is never resolved anywhere in the call graph. No test in this
file discovers/materializes against the real machine.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from cc.commands.projects import (
    build_all_projects_freshness,
    build_fanout_report,
    build_materialize_project_report,
    execute_fanout,
    execute_materialize_project,
    resolve_fanout_sources,
)
from cc.core.ecosystem.project_sources import resolve_claude_content
from cc.core.ecosystem.projects import (
    discover_projects,
    project_freshness,
    read_project_lock,
)
from cc.core.ecosystem.workspaces import mark_project_excluded
from cc.core.locking import copilot_lock
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

_SCHEMA_DIR = Path(__file__).parent / "fixtures" / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _registry() -> Registry:
    envelope = _load_schema("_envelope.schema.json")
    update_schema = _load_schema("update.schema.json")
    projects_schema = _load_schema("projects.schema.json")
    return Registry().with_resources(
        [
            ("_envelope.schema.json", Resource.from_contents(envelope)),
            (update_schema["$id"], Resource.from_contents(update_schema)),
            ("update.schema.json", Resource.from_contents(update_schema)),
            (projects_schema["$id"], Resource.from_contents(projects_schema)),
        ]
    )


def _validate(payload: dict, schema_name: str) -> None:
    schema = _load_schema(schema_name)
    validator = Draft202012Validator(schema, registry=_registry())
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


@pytest.fixture(autouse=True)
def _no_real_home(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "projects contract test attempted to resolve Path.home() -- "
            "inject tmp_path instead"
        )

    monkeypatch.setattr(Path, "home", staticmethod(_boom))


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _git_init(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)


def _git_commit_all(repo: Path, message: str = "commit") -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True)


def _write_files(repo: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _framework_file(
    path: str, *, content: str | None = None, checksum: str | None = None
) -> dict:
    """A framework-owned file entry. Pass `content` matching whatever
    `_write_files()` actually wrote at `path` to record a checksum that
    genuinely matches on-disk content -- the realistic "unmodified, safe to
    auto-apply" case (task-372: `build_materialize_project_report()` now
    checks recorded-checksum drift as its own hold signal, so a fixture
    using a placeholder/mismatched checksum would make EVERY project look
    "locally-modified" regardless of what the test intends). Pass an
    explicit `checksum` instead when a test deliberately wants a stale
    record that does NOT match on-disk content."""
    if checksum is None:
        checksum = f"sha256:{_sha256_text(content)}" if content is not None else "sha256:placeholder"
    return {"path": path, "ownership": "framework", "checksum": checksum}


def _project_file(path: str) -> dict:
    return {"path": path, "ownership": "project"}


def _component(component: str, version, *, files, release_tag=None) -> dict:
    return {
        "component": component,
        "version": version,
        "release_tag": release_tag,
        "files": files,
    }


def _write_manifest(project: Path, components: list[dict]) -> None:
    manifest = {"schema_version": "1.0", "components": components}
    (project / "copilot.lock.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _make_source_repo(tmp_path: Path, files: dict[str, str], *, name: str) -> Path:
    """A framework mirror-style content root: just a plain tree of files at
    the same relative layout the project's manifest paths use -- NOT a git
    repo (materialize's source content is a plain checked-out tree, mirrors
    the framework's own `layer_source_paths` convention in
    core/ecosystem/materialize.py, just without that module's dimension
    model -- see commands/projects.py's module docstring)."""
    root = tmp_path / name
    _write_files(root, files)
    return root


# ---------------------------------------------------------------------------
# discover_projects()
# ---------------------------------------------------------------------------


def test_discover_projects_finds_projects_under_roots_and_registry_union(tmp_path):
    root = tmp_path / "machine-root"
    proj_a = root / "proj-a"
    proj_b = root / "nested" / "proj-b"
    _git_init(proj_a)
    _write_manifest(proj_a, [])
    _git_commit_all(proj_a)
    _git_init(proj_b)
    _write_manifest(proj_b, [])
    _git_commit_all(proj_b)

    # A dangling symlink inside root -- must never crash or loop the scan.
    (root / "broken-link").symlink_to(root / "does-not-exist-at-all")

    proj_c = tmp_path / "elsewhere" / "proj-c"  # NOT under any root
    _git_init(proj_c)
    _write_manifest(proj_c, [])
    _git_commit_all(proj_c)

    registry_path = tmp_path / "projects.json"
    registry_path.write_text(json.dumps([str(proj_c), str(tmp_path / "not-a-project")]))

    found = discover_projects(roots=[root], _registry=registry_path)

    assert {p.resolve() for p in found} == {proj_a.resolve(), proj_b.resolve(), proj_c.resolve()}


def test_discover_projects_skips_unreadable_candidate_without_aborting_sweep(tmp_path):
    root = tmp_path / "machine-root"
    good = root / "good-project"
    _git_init(good)
    _write_manifest(good, [])
    _git_commit_all(good)

    blocked = root / "blocked-project"
    blocked.mkdir(parents=True)
    (blocked / "copilot.lock.json").write_text("{}")

    import os

    original_mode = blocked.stat().st_mode
    os.chmod(blocked, 0o000)
    try:
        found = discover_projects(roots=[root], _registry=None)
    finally:
        os.chmod(blocked, original_mode)

    resolved = {p.resolve() for p in found}
    assert good.resolve() in resolved


def test_discover_projects_deduped_when_reachable_both_ways(tmp_path):
    root = tmp_path / "machine-root"
    proj = root / "proj"
    _git_init(proj)
    _write_manifest(proj, [])
    _git_commit_all(proj)

    registry_path = tmp_path / "projects.json"
    registry_path.write_text(json.dumps([str(proj)]))

    found = discover_projects(roots=[root], _registry=registry_path)
    assert len(found) == 1


# ---------------------------------------------------------------------------
# project_freshness() / build_all_projects_freshness()
# ---------------------------------------------------------------------------


def test_all_projects_freshness_stale_and_fresh_correctness_and_schema(tmp_path):
    fresh_project = tmp_path / "fresh-project"
    _git_init(fresh_project)
    _write_files(fresh_project, {".claude/commands/x.md": "v1"})
    _write_manifest(
        fresh_project,
        [_component("claude", "1.0.0", files=[_framework_file(".claude/commands/x.md", content="v1")])],
    )
    _git_commit_all(fresh_project)

    stale_project = tmp_path / "stale-project"
    _git_init(stale_project)
    _write_files(stale_project, {".claude/commands/x.md": "v1"})
    _write_manifest(
        stale_project,
        [
            _component("claude", "0.9.0", files=[_framework_file(".claude/commands/x.md", content="v1")]),
            _component("knowledge", "3.0.0", files=[_framework_file(".claude/knowledge/a.md")]),
        ],
    )
    _git_commit_all(stale_project)

    report = build_all_projects_freshness(
        _projects=[fresh_project, stale_project],
        _latest_by_product={"claude": "1.0.0", "knowledge": "3.1.0"},
    )

    _validate(report, "projects.schema.json")
    assert report["total"] == 2

    by_path = {p["path"]: p for p in report["projects"]}
    assert by_path[str(fresh_project)]["stale"] is False
    assert by_path[str(fresh_project)]["components"][0]["stale"] is False

    assert by_path[str(stale_project)]["stale"] is True
    claude_component = next(
        c for c in by_path[str(stale_project)]["components"] if c["product"] == "claude"
    )
    assert claude_component["stale"] is True
    assert claude_component["held"] is False  # clean tree -- not held

    # Global-once component reported once at machine scope, never per project.
    assert all(
        c["product"] not in ("knowledge", "cli")
        for p in report["projects"]
        for c in p["components"]
    )
    assert report["global"] == [
        {"product": "knowledge", "current": "3.0.0", "latest": "3.1.0", "stale": True}
    ]


def test_project_freshness_unknown_latest_is_stale_none_never_coerced(tmp_path):
    project = tmp_path / "proj"
    _git_init(project)
    _write_files(project, {".claude/commands/x.md": "v1"})
    _write_manifest(
        project, [_component("claude", "1.0.0", files=[_framework_file(".claude/commands/x.md")])]
    )
    _git_commit_all(project)

    result = project_freshness(project, latest_by_product={})
    assert result["components"][0]["stale"] is None
    assert result["stale"] is None


def test_project_freshness_held_true_when_dirty_wip_touches_framework_path(tmp_path):
    project = tmp_path / "proj"
    _git_init(project)
    _write_files(project, {".claude/commands/x.md": "v1"})
    _write_manifest(
        project, [_component("claude", "1.0.0", files=[_framework_file(".claude/commands/x.md")])]
    )
    _git_commit_all(project)

    (project / ".claude" / "commands" / "x.md").write_text("uncommitted local edit")

    result = project_freshness(project, latest_by_product={"claude": "2.0.0"})
    component = result["components"][0]
    assert component["stale"] is True
    assert component["held"] is True


def test_project_freshness_held_true_when_customization_committed(tmp_path):
    """task-372: the read-only preview must never promise a project is
    safe to auto-apply when a real materialize run against it would
    actually hold -- so `held` must also go `True` for a COMMITTED
    customization (clean tree), not only an uncommitted one."""
    project = tmp_path / "proj"
    _git_init(project)
    _write_files(project, {".claude/commands/x.md": "v1"})
    _write_manifest(
        project,
        [_component("claude", "1.0.0", files=[_framework_file(".claude/commands/x.md", content="v1")])],
    )
    _git_commit_all(project, "initial framework embed")

    (project / ".claude" / "commands" / "x.md").write_text("customized and committed")
    _git_commit_all(project, "customize x.md")

    status = subprocess.run(
        ["git", "-C", str(project), "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    )
    assert status.stdout.strip() == ""  # clean tree -- not a dirty-tree hold

    result = project_freshness(project, latest_by_product={"claude": "2.0.0"})
    component = result["components"][0]
    assert component["stale"] is True
    assert component["held"] is True


def test_build_all_projects_freshness_fail_open_skips_bad_project(tmp_path):
    good = tmp_path / "good"
    _git_init(good)
    _write_manifest(good, [])
    _git_commit_all(good)

    # A "project" whose path does not exist at all -- read_project_lock()
    # degrades to {} (no components), which is itself a valid, non-crashing
    # fold; the real fail-open guard is proven by asserting the good
    # project's result is unaffected either way.
    report = build_all_projects_freshness(_projects=[good, tmp_path / "does-not-exist"])

    assert report["total"] == 2
    paths = {p["path"] for p in report["projects"]}
    assert str(good) in paths


# ---------------------------------------------------------------------------
# build_materialize_project_report() -- per-project materialize
# ---------------------------------------------------------------------------


def test_materialize_project_dirty_working_tree_is_held_byte_identical(tmp_path):
    """A dirty git working tree that does NOT change the file's actual
    content (a permissions/mode-only diff) -- proves `guard_personal()`'s
    dirty-tree fallback still holds even when the recorded-checksum check
    alone would see a match. Content-changing dirt is covered separately by
    `test_materialize_project_locally_modified_is_held_even_when_committed`
    below, which is the more common real case and reports the more
    specific `"locally-modified"` reason instead (checked first)."""
    project = tmp_path / "dirty-project"
    _git_init(project)
    _write_files(project, {".claude/commands/x.md": "v1", ".claude/agents/mine.md": "personal"})
    _write_manifest(
        project,
        [
            _component(
                "claude",
                "1.0.0",
                files=[
                    _framework_file(".claude/commands/x.md", content="v1"),
                    _project_file(".claude/agents/mine.md"),
                ],
            )
        ],
    )
    _git_commit_all(project)

    # Dirty WIP touching the framework-owned path WITHOUT changing its
    # content -- a permission-bit-only diff `git status` still reports.
    target = project / ".claude" / "commands" / "x.md"
    before_bytes = target.read_bytes()
    manifest_before = (project / "copilot.lock.json").read_text()
    os.chmod(target, 0o755)

    source_root = _make_source_repo(tmp_path, {".claude/commands/x.md": "v2"}, name="source-v2")

    report = build_materialize_project_report(
        project,
        component="claude",
        target_version="2.0.0",
        release_tag="claude@2.0.0",
        source_root=source_root,
    )

    _validate(report, "update.schema.json")
    assert report["result"] == "held"
    assert report["held_for_approval"][0]["reason"] == "dirty-working-tree"
    assert report["changed"] == []
    assert target.read_bytes() == before_bytes
    assert (project / "copilot.lock.json").read_text() == manifest_before


def test_materialize_project_locally_modified_is_held_even_when_committed(tmp_path):
    """task-372: the owner's vital never-clobber requirement. A project
    that customizes a framework-owned file (e.g. `commands/protocol.md`
    for a company-level override) and then COMMITS it -- the ordinary git
    workflow -- must still be held, not silently overwritten. Empirically,
    before this fix, a clean-but-customized tree returned `result:
    "applied"` here because `guard_personal()`'s dirty-tree check alone has
    nothing to see once the tree is clean; comparing the file's actual
    checksum against the checksum THIS manifest itself last recorded
    catches it regardless of commit status."""
    project = tmp_path / "customized-project"
    _git_init(project)
    _write_files(project, {".claude/commands/x.md": "v1"})
    _write_manifest(
        project,
        [_component("claude", "1.0.0", files=[_framework_file(".claude/commands/x.md", content="v1")])],
    )
    _git_commit_all(project, "initial framework embed")

    target = project / ".claude" / "commands" / "x.md"
    target.write_text("CUSTOMIZED -- company override, committed like any other change")
    _git_commit_all(project, "customize x.md for this project")
    before_bytes = target.read_bytes()
    manifest_before = (project / "copilot.lock.json").read_text()

    # Tree is clean -- proves this is NOT a dirty-tree hold.
    status = subprocess.run(
        ["git", "-C", str(project), "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    )
    assert status.stdout.strip() == ""

    source_root = _make_source_repo(tmp_path, {".claude/commands/x.md": "v2"}, name="source-v2")

    report = build_materialize_project_report(
        project,
        component="claude",
        target_version="2.0.0",
        release_tag="claude@2.0.0",
        source_root=source_root,
    )

    _validate(report, "update.schema.json")
    assert report["result"] == "held"
    assert report["held_for_approval"][0]["reason"] == "locally-modified"
    assert report["changed"] == []
    assert target.read_bytes() == before_bytes
    assert (project / "copilot.lock.json").read_text() == manifest_before


def test_materialize_project_applied_in_clean_project(tmp_path):
    project = tmp_path / "clean-project"
    _git_init(project)
    _write_files(project, {".claude/commands/x.md": "v1", ".claude/agents/mine.md": "personal"})
    _write_manifest(
        project,
        [
            _component(
                "claude",
                "1.0.0",
                files=[
                    _framework_file(".claude/commands/x.md", content="v1"),
                    _project_file(".claude/agents/mine.md"),
                ],
            )
        ],
    )
    _git_commit_all(project)

    source_root = _make_source_repo(tmp_path, {".claude/commands/x.md": "v2"}, name="source-v2")

    report = build_materialize_project_report(
        project,
        component="claude",
        target_version="2.0.0",
        release_tag="claude@2.0.0",
        source_root=source_root,
    )

    _validate(report, "update.schema.json")
    assert report["result"] == "applied"
    assert (project / ".claude" / "commands" / "x.md").read_text() == "v2"
    # Project-owned file untouched, byte-for-byte.
    assert (project / ".claude" / "agents" / "mine.md").read_text() == "personal"

    manifest = read_project_lock(project / "copilot.lock.json")
    claude_entry = manifest["components"][0]
    assert claude_entry["version"] == "2.0.0"
    assert claude_entry["release_tag"] == "claude@2.0.0"

    changed_item = report["changed"][0]
    assert changed_item["item"] == ".claude/commands/x.md"
    assert changed_item["op"] == "updated"
    assert changed_item["signed"] is True


# ---------------------------------------------------------------------------
# claude PER-ARTIFACT TIER RESOLUTION (component-sync fan-out reconnection):
# `build_materialize_project_report()` resolves `.claude/{commands,agents}/
# <item>.md` through `resolve_claude_content()` -- the SAME resolver
# `_claude_plan()`'s single-project install already consumes -- instead of
# always copying from `source_root`. `_claude_layers` is the test-only
# passthrough to `resolve_claude_content()`'s own `_layers` override (see
# `test_ecosystem_project_sources.py` for the resolver's own unit tests;
# these prove the WIRING, not the fold itself).
# ---------------------------------------------------------------------------


def _claude_layer(
    layer_id: str, *, role: str, rank: int, path: Path, subpath: str | None = None
) -> dict:
    """Mirrors the REAL live manifest's shape: a dedicated org/dept/personal
    authoring repo declares `commands/`/`agents/` at ITS OWN root (no
    `subpath`), while the foundation entry's `path` is the whole framework
    checkout with `subpath: .claude` joined on top (`synthesize_effective_
    layers()`) -- see `~/.config/copilot/copilot.layers.yml`'s real
    `claude-organization` (bare `path`) vs. `claude-foundation` (`path` +
    `subpath: .claude`) entries."""
    source = {"repo": f"https://example.invalid/{layer_id}.git", "path": str(path)}
    if subpath is not None:
        source["subpath"] = subpath
    return {
        "id": layer_id,
        "role": role,
        "rank": rank,
        "product": "claude",
        "source": source,
        "auth": "anon",
        "activation": "always",
    }


def test_materialize_project_claude_ladder_prefers_nearer_substantive_tier(tmp_path):
    """An organization-tier override for ONE agent reaches the project --
    not the foundation's copy of that same item -- and the report's
    `changed[].layer` names the REAL winning tier, not just `"claude"`."""
    project = tmp_path / "ladder-project"
    _git_init(project)
    _write_files(
        project,
        {
            ".claude/agents/cw.md": "old cw",
            ".claude/agents/qa.md": "old qa",
        },
    )
    _write_manifest(
        project,
        [
            _component(
                "claude",
                "1.0.0",
                files=[
                    _framework_file(".claude/agents/cw.md", content="old cw"),
                    _framework_file(".claude/agents/qa.md", content="old qa"),
                ],
            )
        ],
    )
    _git_commit_all(project)

    foundation_root = _make_source_repo(
        tmp_path,
        {
            ".claude/agents/cw.md": "foundation cw, real and substantive",
            ".claude/agents/qa.md": "foundation qa, real and substantive",
        },
        name="foundation-checkout",
    )
    org_root = tmp_path / "org-checkout"
    _write_files(org_root, {"agents/cw.md": "organization's OWN cw override, real content"})

    layers = [
        _claude_layer("claude-organization", role="organization", rank=30, path=org_root),
        _claude_layer(
            "claude-foundation", role="foundation", rank=40, path=foundation_root, subpath=".claude"
        ),
    ]

    report = build_materialize_project_report(
        project,
        component="claude",
        target_version="2.0.0",
        release_tag="claude@2.0.0",
        source_root=foundation_root,
        _claude_layers=layers,
    )

    _validate(report, "update.schema.json")
    assert report["result"] == "applied"
    # The organization's override reached the project -- never the
    # foundation's copy of the same item (E-1: org content reaches project).
    assert (
        project / ".claude" / "agents" / "cw.md"
    ).read_text() == "organization's OWN cw override, real content"
    # The sibling, non-overridden item is still installed from the
    # foundation -- overriding one artifact never costs another (E-2:
    # nearest-wins preserves siblings).
    assert (
        project / ".claude" / "agents" / "qa.md"
    ).read_text() == "foundation qa, real and substantive"

    by_item = {c["item"]: c for c in report["changed"]}
    assert by_item[".claude/agents/cw.md"]["layer"] == "claude-organization"
    assert by_item[".claude/agents/qa.md"]["layer"] == "claude-foundation"


def test_materialize_project_claude_draft_placeholder_never_shadows(tmp_path):
    """A `status: draft` organization override never wins over the
    foundation's real content, even though it is nearer (E-3)."""
    project = tmp_path / "draft-shadow-project"
    _git_init(project)
    _write_files(project, {".claude/commands/protocol.md": "old"})
    _write_manifest(
        project,
        [
            _component(
                "claude",
                "1.0.0",
                files=[_framework_file(".claude/commands/protocol.md", content="old")],
            )
        ],
    )
    _git_commit_all(project)

    foundation_root = _make_source_repo(
        tmp_path,
        {".claude/commands/protocol.md": "---\nstatus: active\n---\nreal foundation protocol, long enough to be substantive on its own"},
        name="foundation-checkout-draft",
    )
    org_root = tmp_path / "org-checkout-draft"
    _write_files(org_root, {"commands/protocol.md": "---\nstatus: draft\n---\nTODO(pablo): placeholder"})

    layers = [
        _claude_layer("claude-organization", role="organization", rank=30, path=org_root),
        _claude_layer(
            "claude-foundation", role="foundation", rank=40, path=foundation_root, subpath=".claude"
        ),
    ]

    report = build_materialize_project_report(
        project,
        component="claude",
        target_version="2.0.0",
        release_tag="claude@2.0.0",
        source_root=foundation_root,
        _claude_layers=layers,
    )

    assert report["result"] == "applied"
    assert (project / ".claude" / "commands" / "protocol.md").read_text().startswith(
        "---\nstatus: active\n---\nreal foundation protocol"
    )
    assert report["changed"][0]["layer"] == "claude-foundation"


def test_materialize_project_claude_non_ladder_paths_stay_single_root(tmp_path):
    """`fitness-check.sh` (no ladder concept -- `INSTALL_DIMENSIONS` is only
    `commands`/`agents`) is unaffected: it still comes from `source_root`
    verbatim and still reports `layer == component`."""
    project = tmp_path / "scaffold-project"
    _git_init(project)
    _write_files(project, {".claude/fitness-check.sh": "old"})
    _write_manifest(
        project,
        [
            _component(
                "claude",
                "1.0.0",
                files=[_framework_file(".claude/fitness-check.sh", content="old")],
            )
        ],
    )
    _git_commit_all(project)

    foundation_root = _make_source_repo(
        tmp_path, {".claude/fitness-check.sh": "new fitness check"}, name="foundation-scaffold"
    )
    org_root = tmp_path / "org-scaffold"  # declares nothing for fitness-check.sh -- no ladder concept

    layers = [
        _claude_layer("claude-organization", role="organization", rank=30, path=org_root),
        _claude_layer("claude-foundation", role="foundation", rank=40, path=foundation_root),
    ]

    report = build_materialize_project_report(
        project,
        component="claude",
        target_version="2.0.0",
        release_tag="claude@2.0.0",
        source_root=foundation_root,
        _claude_layers=layers,
    )

    assert report["result"] == "applied"
    assert (project / ".claude" / "fitness-check.sh").read_text() == "new fitness check"
    assert report["changed"][0]["layer"] == "claude"


def test_fanout_claude_ladder_matches_direct_materialize_no_second_implementation(tmp_path):
    """`build_fanout_report()`'s per-project materialize and a direct
    `build_materialize_project_report()` call resolve the SAME winning tier
    for the same item -- proving fan-out and single-project resolution can
    never drift apart (there is exactly one `resolve_claude_content()`
    consumer, not two competing folds)."""
    project = tmp_path / "fanout-ladder-project"
    _git_init(project)
    _write_files(project, {".claude/agents/cw.md": "old cw"})
    _write_manifest(
        project,
        [
            _component(
                "claude",
                "1.0.0",
                files=[_framework_file(".claude/agents/cw.md", content="old cw")],
            )
        ],
    )
    _git_commit_all(project)

    foundation_root = _make_source_repo(
        tmp_path, {".claude/agents/cw.md": "foundation cw, real content"}, name="fanout-foundation"
    )
    org_root = tmp_path / "fanout-org"
    _write_files(org_root, {"agents/cw.md": "organization cw override, real content"})

    layers = [
        _claude_layer("claude-organization", role="organization", rank=30, path=org_root),
        _claude_layer(
            "claude-foundation", role="foundation", rank=40, path=foundation_root, subpath=".claude"
        ),
    ]

    report = build_fanout_report(
        _projects=[project],
        _latest_by_product={"claude": "2.0.0"},
        _release_tags={"claude": "claude@2.0.0"},
        _source_roots={"claude": foundation_root},
        _claude_layers=layers,
    )

    assert report["summary"]["updated"] == 1
    fanout_report = report["results"][0]["report"]
    assert fanout_report["changed"][0]["layer"] == "claude-organization"
    assert (project / ".claude" / "agents" / "cw.md").read_text() == "organization cw override, real content"

    # Same inputs fed straight to the resolver fan-out itself consumes --
    # identical winning tier, never a second, possibly-disagreeing
    # resolution (there is exactly one `resolve_claude_content()` caller
    # for this dimension/item across both single-project and fan-out).
    direct = resolve_claude_content(
        foundation_root=foundation_root, items={"agents": ("cw",)}, _layers=layers
    )
    assert direct[("agents", "cw")].layer == fanout_report["changed"][0]["layer"]


# ---------------------------------------------------------------------------
# CONTENT-LEVEL STALENESS WIDENING (mechanism defect fix, 2026-08): a
# version-string match against `target_version` alone is no longer proof
# that a `claude` component has nothing pending -- org/department/personal
# tier content can change without ever bumping the foundation's version.
# ---------------------------------------------------------------------------


def test_materialize_project_claude_content_drift_at_matching_version_still_applies(tmp_path):
    """The exact live defect: `target_version == current_version` (a
    foundation version bump never happened), but the organization tier now
    declares REAL, substantive content for an already-tracked item. A bare
    version check would report `up-to-date` and never even resolve the
    ladder -- this must still detect the drift and apply it."""
    project = tmp_path / "drift-project"
    _git_init(project)
    _write_files(project, {".claude/agents/cw.md": "old cw content (foundation)"})
    _write_manifest(
        project,
        [
            _component(
                "claude",
                "1.0.0",
                release_tag="claude@1.0.0",
                files=[
                    _framework_file(
                        ".claude/agents/cw.md", content="old cw content (foundation)"
                    )
                ],
            )
        ],
    )
    _git_commit_all(project)

    foundation_root = _make_source_repo(
        tmp_path,
        {".claude/agents/cw.md": "old cw content (foundation)"},
        name="drift-foundation",
    )
    org_root = tmp_path / "drift-org"
    _write_files(
        org_root, {"agents/cw.md": "NEW real, substantive organization override for cw"}
    )

    layers = [
        _claude_layer("claude-organization", role="organization", rank=30, path=org_root),
        _claude_layer(
            "claude-foundation", role="foundation", rank=40, path=foundation_root, subpath=".claude"
        ),
    ]

    report = build_materialize_project_report(
        project,
        component="claude",
        target_version="1.0.0",  # SAME as current -- no version bump at all
        release_tag="claude@1.0.0",
        source_root=foundation_root,
        _claude_layers=layers,
    )

    assert report["result"] == "applied"
    assert (
        project / ".claude" / "agents" / "cw.md"
    ).read_text() == "NEW real, substantive organization override for cw"
    assert report["changed"][0]["layer"] == "claude-organization"

    manifest = read_project_lock(project / "copilot.lock.json")
    assert manifest["components"][0]["version"] == "1.0.0"  # unchanged, as expected


def test_materialize_project_claude_no_drift_at_matching_version_stays_up_to_date(tmp_path):
    """Regression guard on the ORIGINAL fast path: when the version matches
    AND the resolved tier content is byte-identical to what is recorded,
    the result must still be `up-to-date` with zero writes -- widening the
    gate must never turn every routine run into a full re-materialize."""
    project = tmp_path / "no-drift-project"
    _git_init(project)
    _write_files(project, {".claude/agents/cw.md": "foundation cw content"})
    _write_manifest(
        project,
        [
            _component(
                "claude",
                "1.0.0",
                release_tag="claude@1.0.0",
                files=[_framework_file(".claude/agents/cw.md", content="foundation cw content")],
            )
        ],
    )
    before_manifest = (project / "copilot.lock.json").read_text()
    _git_commit_all(project)

    foundation_root = _make_source_repo(
        tmp_path, {".claude/agents/cw.md": "foundation cw content"}, name="no-drift-foundation"
    )
    layers = [
        _claude_layer(
            "claude-foundation", role="foundation", rank=40, path=foundation_root, subpath=".claude"
        )
    ]

    report = build_materialize_project_report(
        project,
        component="claude",
        target_version="1.0.0",
        release_tag="claude@1.0.0",
        source_root=foundation_root,
        _claude_layers=layers,
    )

    assert report["result"] == "up-to-date"
    assert report["changed"] == []
    assert (project / "copilot.lock.json").read_text() == before_manifest


def test_fanout_claude_content_drift_at_matching_version_is_detected_and_propagated(tmp_path):
    """End-to-end at the fan-out roll-up level: adding real organization
    content for an already-tracked item, with NO version bump, must still
    be detected and applied by `cc update --fanout` -- the exact mechanism
    defect this fix closes (`cc update --fanout` previously reported
    `up_to_date` for every project whenever the recorded version already
    matched the foundation's, regardless of what any nearer tier declared)."""
    project = tmp_path / "fanout-drift-project"
    _git_init(project)
    _write_files(project, {".claude/agents/cw.md": "old cw content (foundation)"})
    _write_manifest(
        project,
        [
            _component(
                "claude",
                "1.0.0",
                release_tag="claude@1.0.0",
                files=[
                    _framework_file(
                        ".claude/agents/cw.md", content="old cw content (foundation)"
                    )
                ],
            )
        ],
    )
    _git_commit_all(project)

    foundation_root = _make_source_repo(
        tmp_path,
        {".claude/agents/cw.md": "old cw content (foundation)"},
        name="fanout-drift-foundation",
    )
    org_root = tmp_path / "fanout-drift-org"
    _write_files(
        org_root, {"agents/cw.md": "NEW real, substantive organization override for cw"}
    )

    layers = [
        _claude_layer("claude-organization", role="organization", rank=30, path=org_root),
        _claude_layer(
            "claude-foundation", role="foundation", rank=40, path=foundation_root, subpath=".claude"
        ),
    ]

    report = build_fanout_report(
        _projects=[project],
        _latest_by_product={"claude": "1.0.0"},  # SAME as recorded -- no version bump
        _release_tags={"claude": "claude@1.0.0"},
        _source_roots={"claude": foundation_root},
        _claude_layers=layers,
    )

    assert report["summary"]["updated"] == 1
    assert report["summary"]["up_to_date"] == 0
    assert (
        project / ".claude" / "agents" / "cw.md"
    ).read_text() == "NEW real, substantive organization override for cw"

    # Idempotent: a second run with nothing changed is a true no-op.
    second = build_fanout_report(
        _projects=[project],
        _latest_by_product={"claude": "1.0.0"},
        _release_tags={"claude": "claude@1.0.0"},
        _source_roots={"claude": foundation_root},
        _claude_layers=layers,
    )
    assert second["summary"]["updated"] == 0
    assert second["summary"]["up_to_date"] == 1


def test_fanout_claude_content_reverted_falls_back_to_foundation(tmp_path):
    """The negative half of the same proof: once the organization tier no
    longer declares the item (reverted), a subsequent fan-out run detects
    THAT drift too (recorded checksum is now the org's content, which no
    longer resolves) and falls the project back to the foundation's copy."""
    project = tmp_path / "fanout-revert-project"
    _git_init(project)
    _write_files(project, {".claude/agents/cw.md": "org override content"})
    _write_manifest(
        project,
        [
            _component(
                "claude",
                "1.0.0",
                release_tag="claude@1.0.0",
                files=[_framework_file(".claude/agents/cw.md", content="org override content")],
            )
        ],
    )
    _git_commit_all(project)

    foundation_root = _make_source_repo(
        tmp_path,
        {".claude/agents/cw.md": "foundation cw content, real and substantive"},
        name="fanout-revert-foundation",
    )
    # Organization tier no longer contributes anything for "agents" (reverted).
    org_root = tmp_path / "fanout-revert-org"
    org_root.mkdir()

    layers = [
        _claude_layer("claude-organization", role="organization", rank=30, path=org_root),
        _claude_layer(
            "claude-foundation", role="foundation", rank=40, path=foundation_root, subpath=".claude"
        ),
    ]

    report = build_fanout_report(
        _projects=[project],
        _latest_by_product={"claude": "1.0.0"},
        _release_tags={"claude": "claude@1.0.0"},
        _source_roots={"claude": foundation_root},
        _claude_layers=layers,
    )

    assert report["summary"]["updated"] == 1
    fanout_entry = report["results"][0]["report"]
    assert fanout_entry["changed"][0]["layer"] == "claude-foundation"
    assert (
        project / ".claude" / "agents" / "cw.md"
    ).read_text() == "foundation cw content, real and substantive"


def test_materialize_project_blocked_when_unverified_no_release_tag(tmp_path):
    project = tmp_path / "unverified-project"
    _git_init(project)
    _write_files(project, {".claude/commands/x.md": "v1"})
    _write_manifest(
        project,
        [_component("claude", "1.0.0", files=[_framework_file(".claude/commands/x.md")])],
    )
    _git_commit_all(project)

    source_root = _make_source_repo(tmp_path, {".claude/commands/x.md": "v2"}, name="source-v2")

    report = build_materialize_project_report(
        project,
        component="claude",
        target_version="2.0.0",
        release_tag=None,
        source_root=source_root,
    )

    _validate(report, "update.schema.json")
    assert report["result"] == "blocked"
    assert report["blocked"][0]["reason"] == "unverified"
    assert (project / ".claude" / "commands" / "x.md").read_text() == "v1"


def test_materialize_project_offline_when_source_root_unreachable(tmp_path):
    project = tmp_path / "offline-project"
    _git_init(project)
    _write_files(project, {".claude/commands/x.md": "v1"})
    _write_manifest(
        project,
        [_component("claude", "1.0.0", files=[_framework_file(".claude/commands/x.md", content="v1")])],
    )
    _git_commit_all(project)

    report = build_materialize_project_report(
        project,
        component="claude",
        target_version="2.0.0",
        release_tag="claude@2.0.0",
        source_root=tmp_path / "no-such-mirror-content",
    )

    _validate(report, "update.schema.json")
    assert report["result"] == "offline"
    assert report["changed"] == []
    assert (project / ".claude" / "commands" / "x.md").read_text() == "v1"


def test_materialize_project_blocked_for_global_once_component(tmp_path):
    project = tmp_path / "proj"
    _git_init(project)
    _write_manifest(
        project,
        [_component("knowledge", "1.0.0", files=[_framework_file(".claude/knowledge/a.md")])],
    )
    _git_commit_all(project)

    report = build_materialize_project_report(
        project,
        component="knowledge",
        target_version="2.0.0",
        release_tag="knowledge@2.0.0",
        source_root=tmp_path,
    )

    assert report["result"] == "blocked"
    assert "global-once" in report["blocked"][0]["reason"]


def test_materialize_project_up_to_date_when_already_at_target(tmp_path):
    project = tmp_path / "proj"
    _git_init(project)
    _write_files(project, {".claude/commands/x.md": "v1"})
    _write_manifest(
        project,
        [_component("claude", "2.0.0", files=[_framework_file(".claude/commands/x.md")])],
    )
    _git_commit_all(project)

    report = build_materialize_project_report(
        project, component="claude", target_version="2.0.0", release_tag="claude@2.0.0"
    )
    assert report["result"] == "up-to-date"
    assert report["changed"] == []


def test_materialize_project_dry_run_computes_plan_without_writing(tmp_path):
    project = tmp_path / "proj"
    _git_init(project)
    _write_files(project, {".claude/commands/x.md": "v1"})
    _write_manifest(
        project,
        [_component("claude", "1.0.0", files=[_framework_file(".claude/commands/x.md", content="v1")])],
    )
    _git_commit_all(project)

    source_root = _make_source_repo(tmp_path, {".claude/commands/x.md": "v2"}, name="source-v2")

    report = build_materialize_project_report(
        project,
        component="claude",
        target_version="2.0.0",
        release_tag="claude@2.0.0",
        source_root=source_root,
        dry_run=True,
    )

    assert report["result"] == "applied"
    assert (project / ".claude" / "commands" / "x.md").read_text() == "v1"
    manifest = read_project_lock(project / "copilot.lock.json")
    assert manifest["components"][0]["version"] == "1.0.0"


# ---------------------------------------------------------------------------
# execute_materialize_project() -- lock acquisition
# ---------------------------------------------------------------------------


def test_execute_materialize_project_lock_contention_reported_honestly(tmp_path):
    project = tmp_path / "proj"
    _git_init(project)
    _write_manifest(project, [])
    _git_commit_all(project)

    lock_mutex_path = tmp_path / "copilot.lock"
    with copilot_lock(path=lock_mutex_path):
        report, exit_code = execute_materialize_project(
            project, component="claude", _lock_path=lock_mutex_path
        )

    assert report["error"]["code"] == "lock-contention"
    assert exit_code == 2


def test_execute_materialize_project_applies_and_releases_lock(tmp_path):
    project = tmp_path / "proj"
    _git_init(project)
    _write_files(project, {".claude/commands/x.md": "v1"})
    _write_manifest(
        project,
        [_component("claude", "1.0.0", files=[_framework_file(".claude/commands/x.md", content="v1")])],
    )
    _git_commit_all(project)

    source_root = _make_source_repo(tmp_path, {".claude/commands/x.md": "v2"}, name="source-v2")
    lock_mutex_path = tmp_path / "copilot.lock"

    report, exit_code = execute_materialize_project(
        project,
        component="claude",
        target_version="2.0.0",
        release_tag="claude@2.0.0",
        source_root=source_root,
        _lock_path=lock_mutex_path,
    )

    assert report["result"] == "applied"
    assert exit_code == 0

    # Lock released -- a second acquisition succeeds immediately.
    with copilot_lock(path=lock_mutex_path):
        pass


# ---------------------------------------------------------------------------
# build_fanout_report() / execute_fanout() -- the roll-up
# ---------------------------------------------------------------------------


def _stale_project(tmp_path: Path, name: str, *, current: str) -> Path:
    project = tmp_path / name
    _git_init(project)
    _write_files(project, {".claude/commands/x.md": "v1"})
    _write_manifest(
        project,
        [_component("claude", current, files=[_framework_file(".claude/commands/x.md", content="v1")])],
    )
    _git_commit_all(project)
    return project


def test_fanout_roll_up_counts_correct_mixed_outcomes(tmp_path):
    applied_project = _stale_project(tmp_path, "applied-project", current="1.0.0")

    held_project = _stale_project(tmp_path, "held-project", current="1.0.0")
    (held_project / ".claude" / "commands" / "x.md").write_text("dirty")

    current_project = _stale_project(tmp_path, "current-project", current="2.0.0")

    offline_project = tmp_path / "offline-project"
    _git_init(offline_project)
    _write_files(offline_project, {".claude/commands/y.md": "v1"})
    _write_manifest(
        offline_project,
        [_component("codex", "1.0.0", files=[_framework_file(".claude/commands/y.md", content="v1")])],
    )
    _git_commit_all(offline_project)

    source_root = _make_source_repo(tmp_path, {".claude/commands/x.md": "v2"}, name="source-v2")

    report = build_fanout_report(
        _projects=[applied_project, held_project, current_project, offline_project],
        _latest_by_product={"claude": "2.0.0", "codex": "2.0.0"},
        _release_tags={"claude": "claude@2.0.0", "codex": "codex@2.0.0"},
        _source_roots={"claude": source_root},  # no source root registered for codex
    )

    _validate(report, "projects.schema.json")

    summary = report["summary"]
    assert summary["updated"] == 1
    assert summary["held"] == 1
    assert summary["up_to_date"] == 1
    assert summary["failed"] == 1  # codex's offline (no source root) result
    assert summary["total"] == 4

    by_key = {(r["path"], r["component"]): r for r in report["results"]}
    assert by_key[(str(applied_project), "claude")]["report"]["result"] == "applied"
    assert by_key[(str(held_project), "claude")]["report"]["result"] == "held"
    assert by_key[(str(current_project), "claude")]["result"] == "up-to-date"
    assert by_key[(str(offline_project), "codex")]["report"]["result"] == "offline"


def test_fanout_never_applies_global_once_products(tmp_path):
    project = tmp_path / "proj"
    _git_init(project)
    _write_manifest(
        project,
        [_component("knowledge", "1.0.0", files=[_framework_file(".claude/knowledge/a.md")])],
    )
    _git_commit_all(project)

    report = build_fanout_report(
        _projects=[project], _latest_by_product={"knowledge": "2.0.0"}
    )

    assert report["results"] == []
    assert report["summary"]["total"] == 0


def test_execute_fanout_lock_contention_reported_honestly(tmp_path):
    lock_mutex_path = tmp_path / "copilot.lock"
    with copilot_lock(path=lock_mutex_path):
        report, exit_code = execute_fanout(_projects=[], _lock_path=lock_mutex_path)

    assert report["error"]["code"] == "lock-contention"
    assert exit_code == 2


def test_execute_fanout_exit_code_reflects_held_and_failed(tmp_path):
    held_project = _stale_project(tmp_path, "held-project", current="1.0.0")
    (held_project / ".claude" / "commands" / "x.md").write_text("dirty")

    lock_mutex_path = tmp_path / "copilot.lock"
    report, exit_code = execute_fanout(
        _projects=[held_project],
        _latest_by_product={"claude": "2.0.0"},
        _release_tags={"claude": "claude@2.0.0"},
        _lock_path=lock_mutex_path,
    )

    assert report["summary"]["held"] == 1
    assert exit_code == 1


# ---------------------------------------------------------------------------
# task-fanout-total-zero fix: unknown-latest is reported, never vanished
# ---------------------------------------------------------------------------


def test_fanout_unknown_latest_is_reported_not_silently_dropped(tmp_path):
    """The exact defect this fixes: with no `_latest_by_product` entry for a
    tracked component (the pre-fix `cc update --fanout` call site's actual
    bug -- main.py wired neither `_source_roots` nor `_latest_by_product`),
    the pair must still show up in `results[]`/`total` with an honest
    `reason` -- never a bare `continue` that drops it from the count."""
    project = tmp_path / "proj"
    _git_init(project)
    _write_files(project, {".claude/commands/x.md": "v1"})
    _write_manifest(
        project,
        [_component("claude", "1.0.0", files=[_framework_file(".claude/commands/x.md", content="v1")])],
    )
    _git_commit_all(project)

    report = build_fanout_report(_projects=[project])  # no _latest_by_product at all

    _validate(report, "projects.schema.json")
    assert report["summary"]["total"] == 1
    assert report["summary"]["failed"] == 1
    assert report["summary"]["updated"] == 0
    assert report["summary"]["held"] == 0
    assert report["results"][0]["path"] == str(project)
    assert report["results"][0]["component"] == "claude"
    assert report["results"][0]["result"] == "blocked"
    assert "unknown" in report["results"][0]["reason"]


def test_fanout_global_once_component_still_silently_excluded_by_design(tmp_path):
    """Unlike the unknown-latest fix above, a `GLOBAL_ONCE_PRODUCTS`
    component (out of `build_fanout_report()`'s scope by architecture, not
    by accident) stays uncounted -- this is the existing, correct,
    already-tested behavior (`test_fanout_never_applies_global_once_
    products` above); re-asserted here alongside the fix so the
    distinction between "legitimate scope exclusion" and "silent bug" is
    pinned down in one place."""
    project = tmp_path / "proj"
    _git_init(project)
    _write_manifest(
        project, [_component("knowledge", "1.0.0", files=[_framework_file(".claude/knowledge/a.md")])]
    )
    _git_commit_all(project)

    report = build_fanout_report(_projects=[project], _latest_by_product={"knowledge": "2.0.0"})

    assert report["results"] == []
    assert report["summary"]["total"] == 0


# ---------------------------------------------------------------------------
# Q14 exclusions: excluded, but never invisible
# ---------------------------------------------------------------------------


def test_fanout_excludes_registered_project_without_touching_it(tmp_path):
    excluded_project = _stale_project(tmp_path, "excluded-project", current="1.0.0")
    kept_project = _stale_project(tmp_path, "kept-project", current="1.0.0")
    source_root = _make_source_repo(tmp_path, {".claude/commands/x.md": "v2"}, name="source-v2")

    registry_path = tmp_path / "excluded-projects.json"
    mark_project_excluded(excluded_project, registry=registry_path)

    before_checksum = hashlib.sha256((excluded_project / ".claude/commands/x.md").read_bytes()).hexdigest()

    report = build_fanout_report(
        _projects=[excluded_project, kept_project],
        _latest_by_product={"claude": "2.0.0"},
        _release_tags={"claude": "claude@2.0.0"},
        _source_roots={"claude": source_root},
        _excluded_registry=registry_path,
    )

    _validate(report, "projects.schema.json")
    summary = report["summary"]
    assert summary["excluded"] == 1
    assert summary["updated"] == 1
    assert summary["failed"] == 0
    assert summary["total"] == 2

    by_path = {r["path"]: r for r in report["results"]}
    excluded_entry = by_path[str(excluded_project)]
    assert excluded_entry["result"] == "excluded"
    assert excluded_entry["component"] is None
    assert "reason" in excluded_entry
    assert by_path[str(kept_project)]["report"]["result"] == "applied"

    # Never touched: on-disk content is bit-for-bit unchanged.
    after_checksum = hashlib.sha256((excluded_project / ".claude/commands/x.md").read_bytes()).hexdigest()
    assert after_checksum == before_checksum


def test_fanout_excluded_project_never_flips_exit_code(tmp_path):
    """An owner's opt-out is not a failure -- `excluded` must never make an
    otherwise-clean run report `exit_code == 1`."""
    excluded_project = _stale_project(tmp_path, "excluded-project", current="1.0.0")
    registry_path = tmp_path / "excluded-projects.json"
    mark_project_excluded(excluded_project, registry=registry_path)

    lock_mutex_path = tmp_path / "copilot.lock"
    report, exit_code = execute_fanout(
        _projects=[excluded_project],
        _latest_by_product={"claude": "2.0.0"},
        _excluded_registry=registry_path,
        _lock_path=lock_mutex_path,
    )

    assert report["summary"]["excluded"] == 1
    assert exit_code == 0


def test_fanout_second_run_after_exclusion_is_still_a_no_op(tmp_path):
    """Idempotency: running the sweep again against the same excluded
    project changes nothing and reports the same outcome."""
    excluded_project = _stale_project(tmp_path, "excluded-project", current="1.0.0")
    registry_path = tmp_path / "excluded-projects.json"
    mark_project_excluded(excluded_project, registry=registry_path)

    kwargs = dict(
        _projects=[excluded_project],
        _latest_by_product={"claude": "2.0.0"},
        _excluded_registry=registry_path,
    )
    first = build_fanout_report(**kwargs)
    second = build_fanout_report(**kwargs)

    assert first["summary"]["excluded"] == second["summary"]["excluded"] == 1
    assert first["results"] == second["results"]


def test_fanout_no_excluded_registry_supplied_never_touches_real_home(tmp_path):
    """Default (`_excluded_registry=None`) must be fully inert -- no
    exclusion check at all, no filesystem/config read outside what the
    caller injected. Regression guard for the `_UNSET`-vs-`None` sentinel
    choice: an unsupplied `_excluded_registry` must NEVER resolve to
    `default_excluded_registry()`'s real machine path."""
    project = _stale_project(tmp_path, "proj", current="1.0.0")

    report = build_fanout_report(
        _projects=[project],
        _latest_by_product={"claude": "1.0.0"},
    )

    assert report["summary"]["excluded"] == 0


# ---------------------------------------------------------------------------
# resolve_fanout_sources() -- the real `cc/main.py` `--fanout` wiring
# ---------------------------------------------------------------------------


def test_resolve_fanout_sources_reads_real_version_files(tmp_path, monkeypatch):
    claude_root = tmp_path / "claude-src"
    claude_root.mkdir()
    (claude_root / "VERSION.json").write_text(json.dumps({"framework": "9.9.9"}), encoding="utf-8")

    codex_root = tmp_path / "codex-src"
    plugin_dir = codex_root / "plugins" / "codex-copilot" / ".codex-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")

    monkeypatch.setenv("CC_PATHS_CLAUDE_COPILOT_ROOT", str(claude_root))
    monkeypatch.setenv("CC_PATHS_CODEX_COPILOT_ROOT", str(codex_root))

    source_roots, latest_by_product, release_tags = resolve_fanout_sources()

    assert source_roots["claude"] == str(claude_root)
    assert latest_by_product["claude"] == "9.9.9"
    assert release_tags["claude"] == "v9.9.9"
    assert source_roots["codex"] == str(codex_root)
    assert latest_by_product["codex"] == "1.2.3"
    assert release_tags["codex"] == "v1.2.3"


def test_resolve_fanout_sources_unknown_version_degrades_honestly(tmp_path, monkeypatch):
    """A root that resolves but has no readable version file folds to
    `None`, never a fabricated/guessed version (matches
    `compute_freshness()`'s own honesty rule) -- and is left OUT of
    `source_roots` so a materialize attempt can never be pointed at it."""
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    monkeypatch.setenv("CC_PATHS_CLAUDE_COPILOT_ROOT", str(empty_root))
    monkeypatch.setenv("CC_PATHS_CODEX_COPILOT_ROOT", str(empty_root))

    source_roots, latest_by_product, release_tags = resolve_fanout_sources()

    assert source_roots == {}
    assert latest_by_product == {"claude": None, "codex": None}
    assert release_tags == {"claude": None, "codex": None}
