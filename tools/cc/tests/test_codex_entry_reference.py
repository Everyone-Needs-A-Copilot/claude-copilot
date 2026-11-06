"""The Codex AGENTS.md entry is recognized in both spellings of the plugin path."""

from __future__ import annotations

import pytest

from cc.core.ecosystem.project_integration import _verify_codex_entry

HEADING = "# Project\n\n## Codex Copilot\n\n"


@pytest.mark.parametrize(
    "body",
    [
        "Use ./plugins/codex-copilot.\n",
        "Inspect `plugins/codex-copilot/skills/<name>/SKILL.md`.\n",
        "Read plugins/codex-copilot/skills/task-copilot/SKILL.md when managing tasks.\n",
    ],
)
def test_recognizes_dotted_and_bare_plugin_reference(tmp_path, body):
    (tmp_path / "AGENTS.md").write_text(HEADING + body, encoding="utf-8")
    _ok, _evidence, missing, _fingerprint = _verify_codex_entry(tmp_path)
    assert not any(item["id"] == "compatible-codex-entry" for item in missing)


@pytest.mark.parametrize(
    "text",
    [
        "# Project\n\nUse plugins/codex-copilot.\n",
        HEADING + "Only the organization plugin at plugins/codex-copilot-internal.\n",
        HEADING + "Elsewhere: vendor/plugins/codex-copilot.\n",
        HEADING + "Nothing about the plugin here.\n",
    ],
)
def test_still_rejects_entries_without_heading_or_plugin(tmp_path, text):
    (tmp_path / "AGENTS.md").write_text(text, encoding="utf-8")
    _ok, _evidence, missing, _fingerprint = _verify_codex_entry(tmp_path)
    assert any(item["id"] == "compatible-codex-entry" for item in missing)


def _entry(root, ownership):
    from cc.core.ecosystem.project_integration import _checksum

    target = root / ".claude/commands/protocol.md"
    return {
        "component": "claude",
        "version": "5.33.1",
        "ownership_mode": "full",
        "files": [
            {"path": ".claude/commands/protocol.md", "ownership": ownership, "checksum": _checksum(target)}
        ],
    }


def test_project_owned_lock_record_is_not_an_invalid_record(tmp_path):
    from cc.core.ecosystem.project_integration import _verify_lock_entry

    target = tmp_path / ".claude/commands/protocol.md"
    target.parent.mkdir(parents=True)
    target.write_text("---\nowner: project\n---\n\n# Mine\n", encoding="utf-8")
    entry = _entry(tmp_path, "project")
    target.write_text("---\nowner: project\n---\n\n# Mine, edited\n", encoding="utf-8")
    _ok, _evidence, missing, _fingerprint = _verify_lock_entry(tmp_path, "claude", entry)
    assert not any(item["id"] == "valid-framework-record" for item in missing)
    assert not any(item["id"] == "verified-framework-file" for item in missing)


def test_unknown_lock_ownership_is_still_invalid(tmp_path):
    from cc.core.ecosystem.project_integration import _verify_lock_entry

    target = tmp_path / ".claude/commands/protocol.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Framework\n", encoding="utf-8")
    entry = _entry(tmp_path, "someone-else")
    _ok, _evidence, missing, _fingerprint = _verify_lock_entry(tmp_path, "claude", entry)
    assert any(item["id"] == "valid-framework-record" for item in missing)


def test_required_path_claimed_by_project_is_satisfied_without_a_lock_record(tmp_path):
    from cc.core.ecosystem.project_integration import (
        _CLAUDE_REQUIRED_LOCK_PATHS,
        _checksum,
        _verify_lock_entry,
    )

    files = []
    for rel in _CLAUDE_REQUIRED_LOCK_PATHS:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if rel == ".claude/commands/protocol.md":
            target.write_text("---\nowner: project\n---\n\n# Mine\n", encoding="utf-8")
            continue
        target.write_text("framework\n", encoding="utf-8")
        files.append({"path": rel, "ownership": "framework", "checksum": _checksum(target)})
    agent = tmp_path / ".claude/agents/ta.md"
    agent.parent.mkdir(parents=True, exist_ok=True)
    agent.write_text("agent\n", encoding="utf-8")
    files.append({"path": ".claude/agents/ta.md", "ownership": "framework", "checksum": _checksum(agent)})
    entry = {"component": "claude", "version": "5.34.8", "ownership_mode": "full", "files": files}
    _ok, _evidence, missing, _fingerprint = _verify_lock_entry(tmp_path, "claude", entry)
    assert not any(item["id"] == "required-lock-path" for item in missing)

    (tmp_path / ".claude/commands/protocol.md").write_text("# Not claimed\n", encoding="utf-8")
    _ok, _evidence, missing, _fingerprint = _verify_lock_entry(tmp_path, "claude", entry)
    assert any(
        item["id"] == "required-lock-path" and "protocol.md" in item["detail"] for item in missing
    )
