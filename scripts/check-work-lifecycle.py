#!/usr/bin/env python3
"""Offline lifecycle packaging checks; no project or installed-state writes.

Every entrypoint, agent and template must reach the work-lifecycle contract, and the contract stays
under its size budget. (The installer-path checks for the per-project copy delivery were retired with
the copy model.)
"""
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]


def claude_reference_roster(source):
    """Command and agent roster declared in VERSION.json (kc is the setup-only agent)."""
    components = json.loads((Path(source) / "VERSION.json").read_text(encoding="utf-8"))["components"]
    commands = tuple(components["commands"]["projectCommands"])
    agents = (*components["agents"]["frameworkAgents"], "kc")
    return commands, agents


class LifecycleDelivery(unittest.TestCase):
    def test_all_entrypoints_and_template_reach_contract(self):
        commands, agents = claude_reference_roster(ROOT)
        self.assertIn("cleanup.md", commands)
        paths = [ROOT / f".claude/agents/{agent}.md" for agent in agents]
        paths += [ROOT / f".claude/commands/{name}.md" for name in
                  ("protocol", "continue", "pause", "reflect", "cleanup")]
        paths += [ROOT / name for name in ("CLAUDE.md", "AGENTS.md", "templates/CLAUDE.template.md")]
        for path in paths:
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertIn(".claude/agents/_shared/work-lifecycle.md", path.read_text())
        skill = ROOT / ".claude/skills/cleanup/SKILL.md"
        self.assertTrue((skill.parent / "../../agents/_shared/work-lifecycle.md").is_file())
        self.assertLess(len((ROOT / ".claude/agents/_shared/work-lifecycle.md").read_text().split()), 1000)


if __name__ == "__main__":
    unittest.main()
