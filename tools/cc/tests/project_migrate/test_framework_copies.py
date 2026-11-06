"""Content-matched framework copies: one classifier shared by the planner, apply and --scan."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from cc.commands.project import project_app
from cc.core.project_migrate import apply_migration, build_known, plan_migration, scan_project
from tests.project_migrate.conftest import Fx, build_project, make_known

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env={**os.environ, **ENV})


def _commit(root: Path, msg: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg)


def make_framework(tmp: Path) -> Path:
    """A framework repo whose HISTORY holds an old release no longer in the working tree."""
    repo = tmp / "fw"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for rel, data in {
        ".claude/commands/keyword-parser.ts": "old parser v1\n",
        ".claude/skills/security/stride-dread/SKILL.md": "stride v1\n",
        "plugins/codex-copilot/scripts/protocol-cycle.py": "cycle v1\n",
        "plugins/creative-base/skills/cs/SKILL.md": "cs v1\n",
    }.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data)
    (repo / ".agents/skills").mkdir(parents=True)
    (repo / ".agents/skills/codex-copilot").symlink_to("../../plugins/codex-copilot/skills")
    _commit(repo, "v1")
    for rel in (".claude/commands/keyword-parser.ts", ".claude/skills/security/stride-dread/SKILL.md",
                "plugins/codex-copilot/scripts/protocol-cycle.py"):
        (repo / rel).write_text("current release\n")
    (repo / ".agents/skills/codex-copilot").unlink()
    _commit(repo, "v2")
    return repo


def copies_project(tmp: Path, fw: Path) -> Path:
    root = tmp / "proj"
    root.mkdir()
    files = {
        ".claude/commands/keyword-parser.ts": "old parser v1\n",
        ".claude/skills/security/stride-dread/SKILL.md": "stride v1\n",
        "plugins/codex-copilot/scripts/protocol-cycle.py": "cycle v1\n",
        "plugins/creative-base/skills/cs/SKILL.md": "cs v1\n",
        "plugins/creative-base/skills/mine/SKILL.md": "project skill\n",
        ".claude/skills/own/SKILL.md": "cs v1\n",   # same bytes, but not under a framework name? still SKILL.md
        ".claude/commands/edited.ts": "old parser v1\n",  # name never existed in the framework
    }
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data)
    (root / ".agents/skills").mkdir(parents=True)
    (root / ".agents/skills/codex-copilot").symlink_to("../../plugins/codex-copilot/skills")
    (root / "plugins/codex-copilot/skills").mkdir(parents=True, exist_ok=True)
    (root / "plugins/creative-base/skills/owned").mkdir(parents=True)
    (root / "plugins/creative-base/skills/owned/SKILL.md").write_text("---\nowner: project\n---\ncs v1\n")
    _git(root, "init", "-q", "-b", "main")
    _commit(root, "synced")
    return root


def known_for(tmp: Path, fw: Path):
    codex = tmp / "codex-root"
    codex.mkdir(exist_ok=True)
    return build_known(claude_root=tmp / "none", codex_root=codex, framework_repos=[fw])


def test_history_content_match_removes_copies_the_lock_never_listed(tmp_path: Path):
    fw = make_framework(tmp_path)
    root = copies_project(tmp_path, fw)
    plan = plan_migration(root, known=known_for(tmp_path, fw), allow_missing_codex=True)
    deleted = {a.path for a in plan.actions if a.kind == "delete"}
    assert {".claude/commands/keyword-parser.ts", ".claude/skills/security/stride-dread/SKILL.md",
            "plugins/codex-copilot/scripts/protocol-cycle.py", "plugins/creative-base/skills/cs/SKILL.md"} <= deleted
    assert {a.path for a in plan.actions if a.kind == "unlink"} >= {".agents/skills/codex-copilot"}
    kept = deleted | {a.path for a in plan.actions}
    assert "plugins/creative-base/skills/mine/SKILL.md" not in kept          # project bytes
    assert "plugins/creative-base/skills/owned/SKILL.md" not in kept          # owner: project
    assert ".claude/commands/edited.ts" not in kept                           # basename never shipped


def test_scan_and_planner_share_one_classifier(tmp_path: Path):
    fw = make_framework(tmp_path)
    root = copies_project(tmp_path, fw)
    kn = known_for(tmp_path, fw)
    plan = plan_migration(root, known=kn, allow_missing_codex=True)
    row = scan_project(root, kn)
    expected = [a.path for a in plan.actions if a.detail.get("copy")]
    assert row["copied_files"] == len(expected) > 0 and not row["clean"]
    assert sorted(row["copied_paths"]) == sorted(expected)
    apply_migration(root, known=kn, codex_config=tmp_path / "c.toml", registry=tmp_path / "r.json",
                    packs_root=tmp_path / "pk", backup_root=tmp_path / "b")
    after = scan_project(root, kn)
    assert after["copied_files"] == 0 and after["clean"]
    assert not (root / ".agents/skills/codex-copilot").is_symlink()
    assert (root / "plugins/creative-base/skills/mine/SKILL.md").exists()


def test_cli_scan_reports_per_project_and_exits_nonzero(tmp_path: Path, monkeypatch):
    fw = make_framework(tmp_path)
    root = copies_project(tmp_path, fw)
    monkeypatch.setenv("CC_FRAMEWORK_REPOS", str(fw))
    monkeypatch.setenv("CC_CODEX_COPILOT_ROOT", str(tmp_path))
    res = CliRunner().invoke(project_app, ["migrate", "--scan", str(tmp_path), "--json"])
    assert res.exit_code == 1, res.output
    body = json.loads(res.output)
    rows = [r for r in body["projects"] if r["project"] == str(root)]
    assert rows and rows[0]["copied_files"] >= 5 and body["copied_files"] >= 5
    # clean tree: exit 0
    empty = tmp_path / "empty" / "p"
    (empty / ".claude").mkdir(parents=True)
    res = CliRunner().invoke(project_app, ["migrate", "--scan", str(tmp_path / "empty"), "--json"])
    assert res.exit_code == 0, res.output


def test_gitignore_write_is_in_plan_and_manifest(tmp_path: Path):
    root = tmp_path / "sb"
    root.mkdir()
    app = build_project(root, "app", shape="pipeline")
    (app / ".codex-copilot.json").write_text(json.dumps({"activePacks": [{"name": "writing-legal", "activatedBy": "./plugins/pipeline-copilot"}]}))
    _git(app, "commit", "-qam", "packs")
    kn = make_known()
    plan = plan_migration(app, known=kn)
    assert any(a.path == ".gitignore" and a.kind == "write" for a in plan.actions)
    packs = tmp_path / "pk" / "writing-legal" / "skills" / "legal-nda"
    packs.mkdir(parents=True)
    receipt = apply_migration(app, known=kn, codex_config=tmp_path / "c.toml", registry=tmp_path / "r.json",
                              packs_root=tmp_path / "pk", backup_root=tmp_path / "b")
    manifest = json.loads((Path(receipt["backup_dir"]) / "manifest.json").read_text())
    written = {e["path"] for e in manifest["entries"]}
    if (app / ".gitignore").exists():
        assert ".gitignore" in written
    # every project path the apply touched was announced by the plan
    announced = {a.path for a in plan.actions}
    assert {p for p in receipt["changed"]} <= announced | {".gitignore"}


def test_lock_listed_file_that_matches_a_newer_release_is_still_a_copy(fx: Fx, tmp_path: Path):
    """The lock records an older checksum; the bytes on disk are another released version."""
    fw = make_framework(tmp_path)
    rel = "plugins/codex-copilot/plugin.json"
    (fx.root / rel).parent.mkdir(parents=True, exist_ok=True)
    (fx.root / "plugins/codex-copilot/scripts").mkdir(parents=True, exist_ok=True)
    (fx.root / "plugins/codex-copilot/scripts/protocol-cycle.py").write_text("cycle v1\n")
    lock = json.loads((fx.root / "copilot.lock.json").read_text())
    lock["components"][1]["files"].append({"checksum": "sha256:" + "0" * 64, "ownership": "framework",
                                           "path": "plugins/codex-copilot/scripts/protocol-cycle.py"})
    (fx.root / "copilot.lock.json").write_text(json.dumps(lock))
    codex = tmp_path / "cr"
    codex.mkdir()
    kn = build_known(claude_root=tmp_path / "none", codex_root=codex, framework_repos=[fw])
    plan = plan_migration(fx.root, known=kn, allow_missing_codex=True)
    assert "plugins/codex-copilot/scripts/protocol-cycle.py" in {a.path for a in plan.actions if a.kind == "delete"}


# -- apply must never fail mid-way on overlapping decisions (PRD-16 release 5 defects) ----------

def _index_with(root: Path, *rels: str):
    from cc.core.project_migrate.framework_index import FrameworkIndex, blob_id

    idx = FrameworkIndex()
    for rel in rels:
        idx.add(blob_id((root / rel).read_bytes()), Path(rel).name, False)
    return idx


def test_file_matched_by_classifier_and_a_specific_rule_is_planned_once(fx: Fx):
    """.agents/plugins/marketplace.json is both a released blob and a framework-only marketplace."""
    from tests.project_migrate.conftest import tree_state

    fx.known.framework_index = _index_with(fx.root, ".agents/plugins/marketplace.json")
    plan = plan_migration(fx.root, known=fx.known)
    paths = [a.path for a in plan.actions if not a.path.startswith("~") and a.kind != "write"]
    assert len(paths) == len(set(paths)), [p for p in paths if paths.count(p) > 1]
    receipt = apply_migration(fx.root, **fx.kw())
    assert receipt["status"] == "applied"
    assert not (fx.root / ".agents/plugins/marketplace.json").exists()
    from cc.core.project_migrate import rollback_migration

    before = tree_state(fx.root)
    rollback_migration(receipt["backup_dir"])
    assert (fx.root / ".agents/plugins/marketplace.json").is_file()
    assert tree_state(fx.root) != before


def test_stale_plan_target_is_refused_before_any_write(fx: Fx):
    from cc.core.project_migrate.model import MigrateError
    from tests.project_migrate.conftest import tree_state

    plan = plan_migration(fx.root, known=fx.known)
    plan.actions.append(plan.actions[[a.kind for a in plan.actions].index("delete")])  # duplicate delete
    before = tree_state(fx.root)
    try:
        apply_migration(fx.root, plan=plan, **fx.kw())
    except MigrateError as exc:
        assert "nothing was changed" in exc.message
    else:
        raise AssertionError("expected refusal")
    assert tree_state(fx.root) == before


def test_receipt_lists_holds_with_reasons(fx: Fx):
    from cc.core.project_migrate.render import render_receipt

    (fx.root / "scripts/copilot-gate.sh").chmod(0o755)
    (fx.root / "scripts/copilot-gate.sh").write_bytes(b"#!/bin/bash\necho edited\n")
    _commit(fx.root, "edit gate")
    receipt = apply_migration(fx.root, **fx.kw())
    assert receipt["holds"], "fixture should hold the edited gate"
    for h in receipt["holds"]:
        assert h["path"] and h["reason"]
    text = render_receipt(receipt)
    assert all(h["path"] in text and h["reason"] in text for h in receipt["holds"])


def test_snapshot_release_siblings_without_git_are_indexed(tmp_path: Path):
    from cc.core.project_migrate.framework_index import discover_repos

    rel = tmp_path / "rel"
    for n in ("claude-copilot", "codex-copilot", "product-creation-copilot", "unrelated"):
        (rel / n).mkdir(parents=True)
    repos, trees = discover_repos([rel / "claude-copilot", rel / "codex-copilot"])
    names = {t.name for t in trees}
    assert {"claude-copilot", "codex-copilot", "product-creation-copilot"} <= names
    assert "unrelated" not in names


def test_lock_listed_framework_symlink_is_unlinked_and_replan_is_clean(fx: Fx):
    """A lock-listed link to a released target must not be held (it turned into an unlink once the lock was gone)."""
    from cc.core.project_migrate.framework_index import FrameworkIndex, blob_id

    link = fx.root / ".claude/agents/kc.md"
    link.symlink_to("../../../claude-copilot/.claude/agents/kc.md")
    lock = json.loads((fx.root / "copilot.lock.json").read_text())
    lock["components"][0]["files"].append({"checksum": "sha256:0", "ownership": "framework", "path": ".claude/agents/kc.md"})
    (fx.root / "copilot.lock.json").write_text(json.dumps(lock))
    idx = FrameworkIndex()
    idx.add(blob_id(os.readlink(link).encode()), "kc.md", True)
    fx.known.framework_index = idx
    # the target must exist for the classifier (a broken link is a pack link)
    (fx.root.parent / "claude-copilot/.claude/agents").mkdir(parents=True)
    (fx.root.parent / "claude-copilot/.claude/agents/kc.md").write_text("kc\n")
    _commit(fx.root, "kc link")
    apply_migration(fx.root, **fx.kw())
    assert not link.is_symlink()
    again = plan_migration(fx.root, known=fx.known)
    assert [a.path for a in again.actions if a.kind != "write"] == []


def test_marker_mode_survives_apply_and_rollback(fx: Fx):
    from cc.core.project_migrate import rollback_migration
    from tests.project_migrate.conftest import tree_state

    marker = fx.root / "copilot.project.json"
    marker.chmod(0o600)
    before = tree_state(fx.root)
    receipt = apply_migration(fx.root, **fx.kw())
    assert (marker.stat().st_mode & 0o777) == 0o600
    rollback_migration(receipt["backup_dir"])
    assert tree_state(fx.root) == before
