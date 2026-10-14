#!/usr/bin/env python3
"""Offline lifecycle packaging/installer checks; no project or installed-state writes.

Run with the cc environment's Python. Temporary negative controls are isolated.
"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/cc/src"))
from cc.core.ecosystem.canonical_transaction import (  # noqa: E402
    claude_reference_roster,
    claude_support_files,
)
from cc.core.ecosystem.reconciliation_types import RequestValidationError  # noqa: E402
from cc.core.ecosystem.project_integration import _claude_source_files  # noqa: E402
from cc.core.ecosystem.workspaces import _claude_plan  # noqa: E402
from cc.core.ecosystem.reconciliation_recipes import (  # noqa: E402
    _framework_files, _claude_support_paths, _validate_relative_target,
)


class LifecycleDelivery(unittest.TestCase):
    def test_declared_command_requires_complete_support(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.assertEqual({}, claude_support_files(root, ("protocol.md",)))
            with self.assertRaises(RequestValidationError):
                claude_support_files(root, ("optimize.md",))
            canonical = root / ".claude/agents/_shared/work-lifecycle.md"
            canonical.parent.mkdir(parents=True)
            canonical.write_text("contract")
            with self.assertRaises(RequestValidationError):
                claude_support_files(root, ("optimize.md",))
            skill = root / ".claude/skills/optimize/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.symlink_to(canonical)
            with self.assertRaises(RequestValidationError):
                claude_support_files(root, ("optimize.md",))
            skill.unlink()
            skill.write_text("entrypoint")
            self.assertEqual(2, len(claude_support_files(root, ("optimize.md",))))

    def test_all_entrypoints_and_template_reach_contract(self):
        commands, agents = claude_reference_roster(ROOT)
        self.assertIn("optimize.md", commands)
        paths = [ROOT / f".claude/agents/{agent}.md" for agent in agents]
        paths += [ROOT / f".claude/commands/{name}.md" for name in
                  ("protocol", "continue", "pause", "reflect", "optimize")]
        paths += [ROOT / name for name in ("CLAUDE.md", "AGENTS.md", "templates/CLAUDE.template.md")]
        for path in paths:
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertIn(".claude/agents/_shared/work-lifecycle.md", path.read_text())
        skill = ROOT / ".claude/skills/optimize/SKILL.md"
        self.assertTrue((skill.parent / "../../agents/_shared/work-lifecycle.md").is_file())
        self.assertLess(len((ROOT / ".claude/agents/_shared/work-lifecycle.md").read_text().split()), 1000)

    def test_both_installer_paths_include_required_local_references(self):
        # Prevent personal/org ladder state from changing this source-package test.
        from types import SimpleNamespace
        def local_content(*, foundation_root, items):
            return {(dimension, item): SimpleNamespace(path=foundation_root / f".claude/{dimension}/{item}.md")
                    for dimension, names in items.items() for item in names}
        with patch("cc.core.ecosystem.project_integration.resolve_claude_content", local_content), \
             patch("cc.core.ecosystem.workspaces.resolve_claude_content", local_content), \
             tempfile.TemporaryDirectory() as name:
            target = Path(name)
            files = _claude_source_files(ROOT)
            self.assertIsNotNone(files)
            copies, collisions = _claude_plan(target, ROOT)
            self.assertEqual([], collisions)
            planned = {destination.relative_to(target).as_posix(): source for source, destination in copies}
            commands, _ = claude_reference_roster(ROOT)
            for relative, source in claude_support_files(ROOT, commands).items():
                self.assertEqual(source, files[relative])
                self.assertEqual(source, planned[relative])
                self.assertIn(relative, {item["path"] for item in _framework_files(ROOT, "claude")})
                self.assertIn(relative, _claude_support_paths(ROOT))
                _validate_relative_target("claude", relative)
            skill = target / ".claude/skills/optimize/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("project-owned content")
            _, collisions = _claude_plan(target, ROOT)
            self.assertIn(skill, collisions)
            self.assertEqual("project-owned content", skill.read_text())


if __name__ == "__main__":
    unittest.main()
