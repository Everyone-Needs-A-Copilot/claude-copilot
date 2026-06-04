"""Unit tests for _parse_skill_frontmatter block scalar support (TASK-61 fix).

These tests run entirely in-process — no cc subprocess needed — so they
complete quickly and verify the parser directly.
"""

import sys

sys.path.insert(0, "/Volumes/Dev/Sites/COPILOT/claude-copilot/tools/cc/src")

from cc.core.skill_store import _parse_skill_frontmatter, search_skills, SkillMeta
from pathlib import Path

STRIDE_PATH = "/Volumes/Dev/Sites/COPILOT/claude-copilot/.claude/skills/security/stride-dread/SKILL.md"


class TestParserBlockScalar:
    def test_gt_dash_resolves_to_prose(self):
        """A >- block scalar description must resolve to prose, not '>-'."""
        fm_text = "---\nname: test-skill\ndescription: >-\n  Line one of description.\n  Line two here.\nversion: 1.0.0\n---\n"
        fm = _parse_skill_frontmatter(fm_text)
        desc = fm.get("description", "")
        assert desc != ">-", f"description is still the literal '>-' sentinel: {desc!r}"
        assert "Line one" in desc, f"Block scalar not resolved: {desc!r}"
        assert "Line two" in desc, f"Block scalar not resolved: {desc!r}"

    def test_stride_dread_description_resolved(self):
        """stride-dread SKILL.md description must contain 'security' after parsing."""
        with open(STRIDE_PATH, encoding="utf-8") as f:
            content = f.read()
        fm = _parse_skill_frontmatter(content)
        desc = fm.get("description", "")
        assert desc != ">-", "Description not resolved from >- block scalar"
        assert len(desc) > 50, f"Description suspiciously short: {desc!r}"
        # The word 'security' appears in the resolved prose
        assert (
            "security" in desc.lower() or "stride" in desc.lower()
        ), f"Expected 'security' or 'stride' in resolved description, got: {desc[:120]!r}"

    def test_search_finds_stride_dread_by_security(self):
        """search_skills('security') must return stride-dread when description is resolved."""
        with open(STRIDE_PATH, encoding="utf-8") as f:
            content = f.read()
        fm = _parse_skill_frontmatter(content)
        skill = SkillMeta(
            name=fm.get("name", "stride-dread"),
            description=fm.get("description", ""),
            path=Path(STRIDE_PATH),
            tags=fm.get("tags") or [],
        )
        results = search_skills("security", [skill])
        assert results, (
            f"search_skills('security') returned no results.\n"
            f"description={skill.description[:120]!r}\ntags={skill.tags}"
        )

    def test_multiline_folded_joins_with_space(self):
        """Folded >- block scalar must join continuation lines with a single space."""
        fm_text = (
            "---\n"
            "name: test\n"
            "description: >-\n"
            "  First sentence.\n"
            "  Second sentence.\n"
            "version: 1.0\n"
            "---\n"
        )
        fm = _parse_skill_frontmatter(fm_text)
        desc = fm.get("description", "")
        assert (
            "First sentence. Second sentence." == desc
        ), f"Folded block scalar not joined correctly: {desc!r}"

    def test_plain_string_description_unchanged(self):
        """A plain (non-block-scalar) description must pass through unchanged."""
        fm_text = "---\nname: test\ndescription: A plain description here.\n---\n"
        fm = _parse_skill_frontmatter(fm_text)
        assert fm.get("description") == "A plain description here."

    def test_tags_as_yaml_list(self):
        """Tags written as YAML flow sequence [a, b, c] must parse to a list."""
        fm_text = (
            "---\nname: test\ndescription: desc\ntags: [python, testing, pytest]\n---\n"
        )
        fm = _parse_skill_frontmatter(fm_text)
        tags = fm.get("tags", [])
        assert isinstance(tags, list), f"tags should be list, got {type(tags)}"
        assert "python" in tags
        assert "testing" in tags
