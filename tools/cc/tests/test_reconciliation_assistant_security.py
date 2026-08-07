"""Security invariants for Python-owned assistant reconciliation recipes."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from cc.core.ecosystem.project_reconciliation import (
    assess_project,
    build_project_plans,
)
from cc.core.ecosystem.reconciliation_transaction import execute_reconciliation
from cc.core.ecosystem.reconciliation_types import (
    RequestValidationError,
    canonical_request_json,
    parse_reconciliation_request,
)

from cc.core.ecosystem import project_integration as integration
from cc.core.ecosystem import project_reconciliation as reconciliation
from cc.core.ecosystem import reconciliation_recipes as recipes


def _git(project: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", *arguments),
        cwd=project,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _write(path: Path, value: str, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    path.chmod(mode)


def _claude_source(tmp_path: Path) -> Path:
    source = tmp_path / "claude-source"
    _write(
        source / "VERSION.json",
        json.dumps(
            {
                "framework": "5.13.3",
                "components": {"agents": {"frameworkAgents": ["me"]}},
            }
        ),
    )
    _write(source / ".claude/commands/protocol.md", "framework protocol\n")
    _write(source / ".claude/commands/continue.md", "framework continue\n")
    _write(source / ".claude/fitness-check.sh", "#!/bin/sh\nexit 0\n", mode=0o755)
    _write(source / ".claude/agents/me.md", "framework me\n")
    _write(source / ".claude/agents/kc.md", "framework kc\n")
    return source


def _codex_source(tmp_path: Path) -> Path:
    source = tmp_path / "codex-source"
    _write(
        source / "plugins/codex-copilot/.codex-plugin/plugin.json",
        json.dumps({"name": "codex-copilot", "version": "0.6.1"}),
    )
    _write(source / "plugins/codex-copilot/skills/me/SKILL.md", "skill\n")
    _write(source / "scripts/copilot-gate.sh", "#!/bin/sh\nexit 0\n", mode=0o755)
    return source


def _customized_project(tmp_path: Path) -> Path:
    project = tmp_path / "customized-project"
    project.mkdir()
    _git(project, "init", "-q")
    _git(project, "config", "user.email", "fixture@example.invalid")
    _git(project, "config", "user.name", "Fixture")
    _write(project / "CLAUDE.md", "# Project-owned instructions\n")
    _write(project / ".claude/agents/me.md", "project-owned agent\n")
    _write(project / ".claude/commands/project.md", "project-owned command\n")
    _git(project, "add", "-A")
    _git(project, "commit", "-qm", "fixture")
    return project


def _configure_source(
    monkeypatch: pytest.MonkeyPatch, claude_source: Path, codex_source: Path
) -> None:
    def resolve(key: str) -> str | None:
        return {
            "paths.claude_copilot_root": str(claude_source),
            "paths.codex_copilot_root": str(codex_source),
        }.get(key)

    monkeypatch.setattr(integration, "resolve_key", resolve)
    monkeypatch.setattr(reconciliation, "resolve_key", resolve)
    monkeypatch.setattr(recipes, "resolve_key", resolve)
    monkeypatch.setattr(reconciliation, "is_project_excluded", lambda _path: False)


def _component(report: dict, name: str) -> dict:
    return next(
        item for item in report["components"] if item["component"] == name
    )


def _proposal_request() -> dict:
    return {
        "schema_version": "1.0",
        "roots": ["/projects"],
        "projects": [
            {
                "path": "/projects/one",
                "components": ["claude", "codex"],
            }
        ],
        "assistant_proposal_id": "proposal_" + "a" * 32,
    }


def test_assistant_proposal_is_an_exact_additive_request_authority() -> None:
    payload = _proposal_request()
    schema_path = (
        Path(__file__).parent / "fixtures" / "schemas" / "reconcile-request.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    request = parse_reconciliation_request(payload)

    assert not list(Draft202012Validator(schema).iter_errors(payload))
    assert request.assistant_proposal_id == payload["assistant_proposal_id"]
    assert json.loads(canonical_request_json(request)) == payload

    hybrid = json.loads(json.dumps(payload))
    hybrid["projects"][0]["recipe_ids"] = {
        "claude": "claude.assistant-preserve-entry.v1"
    }
    hybrid_request = parse_reconciliation_request(hybrid)
    assert hybrid_request.projects[0].recipe_ids == hybrid["projects"][0]["recipe_ids"]
    assert not list(Draft202012Validator(schema).iter_errors(hybrid))


@pytest.mark.parametrize(
    "proposal_id",
    [
        "proposal_" + "A" * 32,
        "proposal_" + "a" * 31,
        "proposal_" + "a" * 33,
        "plan_" + "a" * 32,
        "proposal_../../outside",
        "proposal_" + "a" * 31 + "\x00",
    ],
)
def test_assistant_proposal_authority_rejects_nonopaque_ids(
    proposal_id: str,
) -> None:
    payload = _proposal_request()
    payload["assistant_proposal_id"] = proposal_id

    with pytest.raises(RequestValidationError, match="opaque proposal"):
        parse_reconciliation_request(payload)


def test_assistant_claude_recipe_preserves_custom_files_and_records_only_owned_subset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A preserved custom roster must not become a false framework checksum claim."""

    source = _claude_source(tmp_path)
    codex_source = _codex_source(tmp_path)
    _configure_source(monkeypatch, source, codex_source)
    project = _customized_project(tmp_path)
    preserved = {
        relative: (project / relative).read_bytes()
        for relative in (
            ".claude/agents/me.md",
            ".claude/commands/project.md",
        )
    }

    assessment = assess_project(
        project,
        approved_root=tmp_path,
        selected_components=("claude",),
    )
    assert assessment["route"] == "customized-guided-route"
    assert _component(assessment, "claude")["state"] == (
        "customized-guided-route"
    )
    _, plans = build_project_plans(
        [assessment],
        {str(project): ("claude",)},
        {
            str(project): {
                "claude": "claude.assistant-preserve-entry.v1",
            }
        },
    )

    receipts = execute_reconciliation(
        [plans[0].transaction_plan()],
        run_id="run_" + "d" * 32,
        root=tmp_path / "transaction-state",
    )

    assert receipts[0]["status"] == "applied"
    assert {
        relative: (project / relative).read_bytes() for relative in preserved
    } == preserved
    assert b"# Project-owned instructions" in (project / "CLAUDE.md").read_bytes()

    lock = json.loads((project / "copilot.lock.json").read_text(encoding="utf-8"))
    claude_lock = next(
        item for item in lock["components"] if item["component"] == "claude"
    )
    recorded = {item["path"] for item in claude_lock["files"]}
    assert recorded == {
        ".claude/commands/protocol.md",
        ".claude/commands/continue.md",
        ".claude/fitness-check.sh",
    }
    assert ".claude/agents/me.md" not in recorded

    fresh = integration.inspect_project_integration(project, detail=True)
    assert _component(fresh, "claude")["classification"] == "ready"


def test_bounded_assistant_recipe_and_standard_recipe_finish_both_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude_source = _claude_source(tmp_path)
    codex_source = _codex_source(tmp_path)
    _configure_source(monkeypatch, claude_source, codex_source)
    project = _customized_project(tmp_path)
    custom_agent = (project / ".claude/agents/me.md").read_bytes()
    custom_command = (project / ".claude/commands/project.md").read_bytes()

    assessment = assess_project(
        project,
        approved_root=tmp_path,
        selected_components=("claude", "codex"),
    )
    _, plans = build_project_plans(
        [assessment],
        {str(project): ("claude", "codex")},
        {
            str(project): {
                "claude": "claude.assistant-preserve-entry.v1",
            }
        },
    )

    receipts = execute_reconciliation(
        [plans[0].transaction_plan()],
        run_id="run_" + "e" * 32,
        root=tmp_path / "transaction-state",
    )

    assert receipts[0]["status"] == "applied"
    assert (project / ".claude/agents/me.md").read_bytes() == custom_agent
    assert (project / ".claude/commands/project.md").read_bytes() == custom_command
    fresh = integration.inspect_project_integration(project, detail=True)
    assert {
        item["component"]: item["classification"] for item in fresh["components"]
    } == {"claude": "ready", "codex": "ready"}

    repeat = assess_project(
        project,
        approved_root=tmp_path,
        selected_components=("claude", "codex"),
    )
    public, repeat_plans = build_project_plans(
        [repeat], {str(project): ("claude", "codex")}
    )
    assert public[0]["operations"] == []
    assert repeat_plans[0].operations == ()
