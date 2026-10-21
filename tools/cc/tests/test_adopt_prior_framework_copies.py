"""A release that starts managing a path the project already holds as an older
framework copy updates it, instead of holding the project for an owner decision.

Regression for 2026-10-06: admin-server, pipeline-copilot, force-readiness-
assessment, product-creation-copilot and spanish-copilot each carried
`.claude/agents/manifest.schema.json` (tracker: `.claude/commands/reflect.md`)
byte-identical to an older framework version that their lock never recorded.
The new release began managing that path, the update boundary saw unrecorded
bytes that differed from today's, and every one of those projects was refused
as `owner-decision`. Project-edited content must still be refused.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from cc.core.ecosystem.canonical_transaction import build_canonical_project_request
from cc.core.ecosystem.framework_history import HISTORY_MARKER, collect_history
from cc.core.ecosystem.project_plan_store import issue_plan
from cc.core.ecosystem.reconciliation import build_apply_report, build_plan_report
from cc.core.ecosystem.reconciliation_recipes import (
    ComponentSourceConflict,
    component_lock_update_required,
)

from tests.test_canonical_project_transaction import (
    _census,
    _configure_sources,
    _git_project,
    _machine,
    _reference_sources,
)

NEW_PATH = ".claude/agents/manifest.schema.json"
OLD = '{"schema": "v1"}\n'
NEW = '{"schema": "v2"}\n'


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _transaction(tmp_path: Path, project: Path, authority: Path):
    request = build_canonical_project_request(project, approved_roots=(authority,))
    state_root = tmp_path / "transaction-state"

    def machine() -> dict[str, Any]:
        return _machine(authority.resolve())

    census = _census(project, authority.resolve())

    def plan():
        return build_plan_report(
            request,
            machine_builder=machine,
            census_builder=census,
            plan_issuer=lambda **kwargs: issue_plan(**kwargs, root=state_root),
        )

    def apply(plan_id: str):
        return build_apply_report(
            request, plan_id, machine_builder=machine, census_builder=census,
            state_root=state_root,
        )

    return plan, apply


def _installed_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, on_disk: str):
    claude, codex, _ = _reference_sources(tmp_path)
    _configure_sources(monkeypatch, claude, codex)
    authority = tmp_path / "projects"
    project = _git_project(authority)
    plan, apply = _transaction(tmp_path, project, authority)
    assert apply(plan()["plan_id"])["result"] == "applied"
    # An earlier release left this file behind without the lock recording it.
    (project / NEW_PATH).write_text(on_disk, encoding="utf-8")
    subprocess.run(("git", "add", "-A"), cwd=project, check=True)
    subprocess.run(("git", "commit", "-qm", "installed"), cwd=project, check=True)
    lock = json.loads((project / "copilot.lock.json").read_text())
    claude_entry = next(c for c in lock["components"] if c["component"] == "claude")
    assert NEW_PATH not in {f["path"] for f in claude_entry["files"]}
    # The new release starts managing the path; its history knows both versions.
    (claude / NEW_PATH).write_text(NEW, encoding="utf-8")
    version = json.loads((claude / "VERSION.json").read_text())
    version["framework"] = "5.13.4"
    (claude / "VERSION.json").write_text(json.dumps(version))
    (claude / HISTORY_MARKER).write_text(
        json.dumps({"schema_version": 1, "paths": {NEW_PATH: [_sha(OLD), _sha(NEW)]}})
    )
    return project, plan, apply


def test_older_framework_copy_is_updated_not_held(tmp_path, monkeypatch):
    project, plan, apply = _installed_project(tmp_path, monkeypatch, OLD)

    assert component_lock_update_required(project, "claude") is True
    report = plan()
    assert report["result"] == "action-required", report
    targets = {op["target"] for p in report["plans"] for op in p["operations"]}
    assert NEW_PATH in targets
    assert apply(report["plan_id"])["result"] == "applied"
    assert (project / NEW_PATH).read_text() == NEW
    lock = json.loads((project / "copilot.lock.json").read_text())
    claude_entry = next(c for c in lock["components"] if c["component"] == "claude")
    recorded = {f["path"]: f["checksum"] for f in claude_entry["files"]}
    assert recorded[NEW_PATH] == _sha(NEW)
    assert component_lock_update_required(project, "claude") is False


def test_project_edited_content_at_a_newly_managed_path_is_still_refused(
    tmp_path, monkeypatch
):
    project, _plan, _apply = _installed_project(
        tmp_path, monkeypatch, '{"schema": "the project wrote this"}\n'
    )
    with pytest.raises(ComponentSourceConflict):
        component_lock_update_required(project, "claude")
    assert (project / NEW_PATH).read_text() == '{"schema": "the project wrote this"}\n'


def test_collect_history_reads_every_committed_version(tmp_path):
    repo = tmp_path / "framework"
    repo.mkdir()
    git = ("git", "-c", "user.name=T", "-c", "user.email=t@test.invalid", "-c",
           "commit.gpgsign=false")
    subprocess.run(("git", "init", "-q", str(repo)), check=True)
    target = repo / ".claude/commands/reflect.md"
    target.parent.mkdir(parents=True)
    for text in ("one\n", "two\n"):
        target.write_text(text)
        (repo / "README.md").write_text(text)
        subprocess.run((*git, "-C", str(repo), "add", "-A"), check=True)
        subprocess.run((*git, "-C", str(repo), "commit", "-qm", text), check=True)
    history = collect_history(repo)
    assert history == {".claude/commands/reflect.md": sorted([_sha("one\n"), _sha("two\n")])}
