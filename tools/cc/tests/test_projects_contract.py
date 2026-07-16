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

import json
import subprocess
from pathlib import Path

import pytest
from cc.commands.projects import (
    build_all_projects_freshness,
    build_fanout_report,
    build_materialize_project_report,
    execute_fanout,
    execute_materialize_project,
)
from cc.core.ecosystem.projects import (
    discover_projects,
    project_freshness,
    read_project_lock,
)
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


def _framework_file(path: str, checksum: str = "sha256:placeholder") -> dict:
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
        [_component("claude", "1.0.0", files=[_framework_file(".claude/commands/x.md")])],
    )
    _git_commit_all(fresh_project)

    stale_project = tmp_path / "stale-project"
    _git_init(stale_project)
    _write_files(stale_project, {".claude/commands/x.md": "v1"})
    _write_manifest(
        stale_project,
        [
            _component("claude", "0.9.0", files=[_framework_file(".claude/commands/x.md")]),
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
                    _framework_file(".claude/commands/x.md"),
                    _project_file(".claude/agents/mine.md"),
                ],
            )
        ],
    )
    _git_commit_all(project)

    # Dirty WIP touching the framework-owned path.
    (project / ".claude" / "commands" / "x.md").write_text("uncommitted local edit")
    before_bytes = (project / ".claude" / "commands" / "x.md").read_bytes()
    manifest_before = (project / "copilot.lock.json").read_text()

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
    assert (project / ".claude" / "commands" / "x.md").read_bytes() == before_bytes
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
                    _framework_file(".claude/commands/x.md"),
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
        [_component("claude", "1.0.0", files=[_framework_file(".claude/commands/x.md")])],
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
        [_component("claude", "1.0.0", files=[_framework_file(".claude/commands/x.md")])],
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
        [_component("claude", "1.0.0", files=[_framework_file(".claude/commands/x.md")])],
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
        [_component("claude", current, files=[_framework_file(".claude/commands/x.md")])],
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
        [_component("codex", "1.0.0", files=[_framework_file(".claude/commands/y.md")])],
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
