"""A project's own edits to CLAUDE.md never make its install unverifiable.

Regression for 2026-10-06: when a project had no CLAUDE.md, setup created one
(a bounded entry saying to keep project instructions in that file) and
recorded its fingerprint as a managed output. Rewriting CLAUDE.md to the new
standard then failed verification ("CLAUDE.md is missing or mismatched"), so
something-new and copilot-control-tower became could-not-verify and the
installer refused to update them. Compatibility is the `## Claude Copilot`
entry, not byte equality; a missing file is still a failure.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from cc.core.ecosystem.project_reconciliation import assess_project

from tests.test_adopt_prior_framework_copies import _transaction
from tests.test_canonical_project_transaction import (
    _configure_sources,
    _git_project,
    _reference_sources,
)


def _commit(project: Path, message: str) -> None:
    subprocess.run(("git", "add", "-A"), cwd=project, check=True)
    subprocess.run(("git", "commit", "-qm", message), cwd=project, check=True)


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    claude, codex, _ = _reference_sources(tmp_path)
    _configure_sources(monkeypatch, claude, codex)
    authority = tmp_path / "projects"
    project = _git_project(authority)
    plan, apply = _transaction(tmp_path, project, authority)
    assert apply(plan()["plan_id"])["result"] == "applied"
    lock = json.loads((project / "copilot.lock.json").read_text())
    claude_entry = next(c for c in lock["components"] if c["component"] == "claude")
    assert "CLAUDE.md" in {o["path"] for o in claude_entry["managed_outputs"]}
    _commit(project, "installed")
    return claude, project, authority, plan, apply


def _claude_state(project: Path, authority: Path) -> dict:
    report = assess_project(project, approved_root=authority, selected_components=("claude",))
    return next(c for c in report["components"] if c["component"] == "claude")


def test_edited_claude_md_stays_verified_and_updates(tmp_path, monkeypatch):
    claude, project, authority, plan, apply = _setup(tmp_path, monkeypatch)
    (project / "CLAUDE.md").write_text(
        "# project\n\n## Project Rules\n\n- Our own rule.\n\n## Claude Copilot\n\nRuns on Claude Copilot.\n"
    )
    _commit(project, "rewrite CLAUDE.md")

    assert _claude_state(project, authority)["state"] == "ready"

    version = json.loads((claude / "VERSION.json").read_text())
    version["framework"] = "5.13.4"
    (claude / "VERSION.json").write_text(json.dumps(version))
    (claude / ".claude/agents/me.md").write_text("me v2\n")
    report = plan()
    assert report["result"] == "action-required", report
    assert apply(report["plan_id"])["result"] == "applied"
    assert (project / ".claude/agents/me.md").read_text() == "me v2\n"
    assert "Our own rule." in (project / "CLAUDE.md").read_text()


def test_missing_claude_md_is_still_a_failure(tmp_path, monkeypatch):
    _claude, project, authority, _plan, _apply = _setup(tmp_path, monkeypatch)
    (project / "CLAUDE.md").unlink()
    _commit(project, "remove CLAUDE.md")
    state = _claude_state(project, authority)
    assert state["state"] != "ready"


def test_project_owned_agent_is_kept_and_never_holds_the_update(tmp_path, monkeypatch):
    """voice-copilot, 2026-10-06: its own `cco.md` (frontmatter `owner: project`)
    sat under a framework agent name, and the update held the whole project as
    owner-decision instead of leaving the project's agent alone."""
    claude, project, authority, plan, apply = _setup(tmp_path, monkeypatch)
    own = "---\nname: me\nowner: project\n---\n\nThe project's own engineer.\n"
    (project / ".claude/agents/me.md").write_text(own)
    _commit(project, "project-owned me agent")

    version = json.loads((claude / "VERSION.json").read_text())
    version["framework"] = "5.13.4"
    (claude / "VERSION.json").write_text(json.dumps(version))
    (claude / ".claude/agents/me.md").write_text("me v2\n")
    (claude / ".claude/agents/qa.md").write_text("qa v2\n")

    assert _claude_state(project, authority)["state"] == "safe-update-available"
    report = plan()
    assert report["result"] == "action-required", report
    assert apply(report["plan_id"])["result"] == "applied"
    assert (project / ".claude/agents/me.md").read_text() == own
    assert (project / ".claude/agents/qa.md").read_text() == "qa v2\n"
    lock = json.loads((project / "copilot.lock.json").read_text())
    claude_entry = next(c for c in lock["components"] if c["component"] == "claude")
    assert ".claude/agents/me.md" not in {f["path"] for f in claude_entry["files"]}
    assert _claude_state(project, authority)["state"] == "ready"


def test_absent_mcp_roster_is_recreated_not_unverifiable(tmp_path, monkeypatch):
    """research-copilot, 2026-10-06: it deleted `.mcp.json` along with its dead
    MCP servers and became could-not-verify with no repair offered, although
    setup's own recipe recreates exactly the empty roster."""
    _claude, project, authority, plan, apply = _setup(tmp_path, monkeypatch)
    (project / ".mcp.json").unlink()
    _commit(project, "drop MCP roster")

    assert _claude_state(project, authority)["state"] != "could-not-verify"
    report = plan()
    assert report["result"] == "action-required", report
    assert apply(report["plan_id"])["result"] == "applied"
    assert json.loads((project / ".mcp.json").read_text()) == {"mcpServers": {}}
    assert _claude_state(project, authority)["state"] == "ready"


def test_malformed_mcp_roster_still_needs_the_owner(tmp_path, monkeypatch):
    _claude, project, authority, _plan, _apply = _setup(tmp_path, monkeypatch)
    (project / ".mcp.json").write_text('{"servers": "not a roster"}\n')
    _commit(project, "malformed roster")
    assert _claude_state(project, authority)["state"] == "could-not-verify"
