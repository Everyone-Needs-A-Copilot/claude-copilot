"""Regression coverage for the C7/D1 bug: a `VERSION.json` project-command
roster addition that was never mirrored into
`reconciliation_recipes._COMPONENT_TARGETS["claude"]`'s static allowlist.

D1 found that `reflect.md` was added to `VERSION.json`'s
`components.commands.projectCommands`, but the static allowlist in
`reconciliation_recipes.py` (a *separate*, hand-maintained enumeration of
`.claude/commands/*.md` targets) was never updated, so `_claude_setup()`
constructed an operation `RecipeOperation.__post_init__` then rejected with
`RecipeValidationError: Recipe target '.claude/commands/reflect.md' is not
allowlisted for claude.` -- surfaced to callers of `cc reconcile plan` /
`/setup-project` / `/update-project` as an uncaught `invalid-recipe` error
for *any* consumer project.

The fix makes `_validate_relative_target()` accept any
`.claude/commands/<name>.md` target structurally for the "claude" component
(mirroring the pre-existing `.claude/agents/**` structural exemption), so the
static tuple's `.claude/commands/*.md` entries are no longer load-bearing for
validation -- only informational for `allowed_targets_for_components()`. This
means a *future* `VERSION.json` project-command addition can never again
reproduce this failure mode, regardless of whether anyone remembers to touch
the static tuple.

These tests intentionally do NOT modify `test_reconciliation_recipes.py`
(existing tests are read-only); they are a new, standalone file.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from cc.core.ecosystem import project_integration as integration_module
from cc.core.ecosystem import project_reconciliation as project_module
from cc.core.ecosystem import reconciliation_recipes as recipes
from cc.core.ecosystem.canonical_transaction import claude_reference_roster
from cc.core.ecosystem.project_reconciliation import assess_project, build_project_plans
from cc.core.ecosystem.reconciliation_recipes import RecipeValidationError

REPO_ROOT = Path(__file__).resolve().parents[3]


def _git(project: Path, *arguments: str) -> None:
    subprocess.run(
        ("git", *arguments),
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    )


def _write(path: Path, value: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    path.chmod(mode)


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-q")
    _git(project, "config", "user.email", "fixture@example.invalid")
    _git(project, "config", "user.name", "Fixture")
    return project


def _framework_sources_with_extra_command(
    tmp_path: Path, extra_command: str
) -> tuple[Path, Path]:
    """A synthetic framework source pair whose Claude `projectCommands`
    roster includes a command name that is deliberately absent from
    `_COMPONENT_TARGETS["claude"]`'s static literal enumeration -- the exact
    shape of the D1 defect, reproduced with a name that can never collide
    with a real, already-allowlisted command. `assess_project()` requires
    evidence for every `SUPPORTED_COMPONENTS` entry, so a minimal codex
    source is provided too even though these tests only select "claude".
    """

    claude = tmp_path / "claude-source"
    codex = tmp_path / "codex-source"
    _write(
        claude / "VERSION.json",
        json.dumps(
            {
                "framework": "5.15.0-test",
                "components": {
                    "agents": {"frameworkAgents": ["me"]},
                    "commands": {
                        "projectCommands": [
                            "protocol.md",
                            "continue.md",
                            extra_command,
                        ]
                    },
                },
            }
        ),
    )
    _write(claude / ".claude/commands/protocol.md", "protocol\n")
    _write(claude / ".claude/commands/continue.md", "continue\n")
    _write(claude / f".claude/commands/{extra_command}", "brand new command\n")
    _write(claude / ".claude/fitness-check.sh", "#!/bin/sh\nexit 0\n", 0o755)
    _write(claude / ".claude/hooks/copilot-hook.sh", "#!/bin/sh\nexit 0\n", 0o755)
    _write(claude / ".claude/agents/me.md", "me\n")
    _write(claude / ".claude/agents/kc.md", "kc\n")

    _write(
        codex / "plugins/codex-copilot/.codex-plugin/plugin.json",
        json.dumps({"name": "codex-copilot", "version": "0.6.1"}),
    )
    _write(codex / "plugins/codex-copilot/skills/me/SKILL.md", "skill\n")
    _write(codex / "scripts/copilot-gate.sh", "#!/bin/sh\nexit 0\n", 0o755)
    return claude, codex


def _configure_sources(monkeypatch: pytest.MonkeyPatch, claude: Path, codex: Path) -> None:
    def resolve(key: str) -> str | None:
        if key == "paths.claude_copilot_root":
            return str(claude)
        if key == "paths.codex_copilot_root":
            return str(codex)
        return None

    monkeypatch.setattr(recipes, "resolve_key", resolve)
    monkeypatch.setattr(project_module, "resolve_key", resolve)
    monkeypatch.setattr(integration_module, "resolve_key", resolve)
    monkeypatch.setattr(project_module, "is_project_excluded", lambda path: False)


def _empty_report(path: Path) -> dict[str, Any]:
    return {
        "inspection": {"id": "sha256:" + "2" * 64},
        "components": [
            {
                "component": component,
                "classification": "safe-finish",
                "recognized_setup": None,
                "missing_requirements": [
                    {
                        "id": "component-setup",
                        "detail": f"The {component.title()} integration is absent.",
                    }
                ],
            }
            for component in ("claude", "codex")
        ],
        "preservation": {"must_preserve": []},
    }


def test_a_new_version_json_project_command_is_not_blocked_by_the_static_allowlist(
    tmp_path: Path,
) -> None:
    """Direct unit coverage of the D1 fix: a command name absent from the
    static `_COMPONENT_TARGETS["claude"]` tuple must still validate, because
    `.claude/commands/*.md` is accepted structurally now (parity with
    `.claude/agents/**`)."""

    target = ".claude/commands/a-brand-new-project-command.md"
    assert target not in recipes._COMPONENT_TARGETS["claude"]
    # Must not raise.
    recipes._validate_relative_target("claude", target)


def test_non_md_and_nested_commands_paths_remain_rejected(tmp_path: Path) -> None:
    """The structural exemption is narrower than the agents one on purpose:
    it only covers a direct `.claude/commands/<name>.md` file, not arbitrary
    depth or non-`.md` files, so it cannot become a write-anywhere escape
    hatch."""

    with pytest.raises(RecipeValidationError, match="not allowlisted"):
        recipes._validate_relative_target("claude", ".claude/commands/not-markdown.sh")
    with pytest.raises(RecipeValidationError, match="not allowlisted"):
        recipes._validate_relative_target(
            "claude", ".claude/commands/nested/deep.md"
        )


def test_end_to_end_plan_build_succeeds_for_a_new_project_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduces D1's exact failure path end-to-end: `assess_project()` +
    `build_project_plans()` (the machinery behind `cc reconcile plan`) must
    succeed for a project command that only exists in `VERSION.json`, not in
    the static allowlist -- instead of raising
    `RecipeValidationError: ... is not allowlisted for claude.`
    """

    extra_command = "a-brand-new-project-command.md"
    claude, codex = _framework_sources_with_extra_command(tmp_path, extra_command)
    _configure_sources(monkeypatch, claude, codex)
    project = _project(tmp_path)

    monkeypatch.setattr(
        project_module,
        "inspect_project_integration",
        lambda path, detail: _empty_report(Path(path)),
    )
    assessment = assess_project(
        project,
        approved_root=project.parent,
        selected_components=("claude",),
    )

    # This is the exact call D1 found raising RecipeValidationError before
    # the fix.
    public, _internal = build_project_plans([assessment], {str(project): ("claude",)})

    targets = {operation["target"] for operation in public[0]["operations"]}
    assert f".claude/commands/{extra_command}" in targets


def test_every_currently_declared_project_command_validates(tmp_path: Path) -> None:
    """Guards against the same class of drift for THIS repo's own, real
    `VERSION.json` roster (the actual source of truth `cc reconcile plan`
    reads via `claude_reference_roster()`): every command it currently
    declares must pass `_validate_relative_target()`. This is the divergence
    check the task calls for -- it fails the moment a future project command
    is added to `VERSION.json` but the recipe validator no longer accepts
    `.claude/commands/*.md` targets structurally (i.e. if the structural
    exemption above is ever narrowed or removed without a replacement)."""

    commands, _agents = claude_reference_roster(REPO_ROOT)
    assert commands, "VERSION.json must declare at least one project command."
    for command in commands:
        recipes._validate_relative_target("claude", f".claude/commands/{command}")
