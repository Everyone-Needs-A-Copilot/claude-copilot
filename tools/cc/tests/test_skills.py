"""Tests for skill discovery, search, and cc skill CLI commands.

Covers:
- discover_skills finds all */SKILL.md files in a directory tree
- Frontmatter parsed correctly (name, description, tags, version)
- Tolerates alternate field names (skill_name)
- search_skills matches on name, description, and tags
- cc skill list outputs a table with correct entries
- cc skill search returns matching skills
- cc skill get returns full SKILL.md content
- cc skill path returns the correct absolute path
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc.core.skill_store import (
    SkillMeta,
    discover_skills,
    discover_skills_with_sources,
    find_skill_by_name,
    get_skill_content,
    search_skills,
)
from cc.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "skills"


@pytest.fixture
def tmp_skills(tmp_path: Path) -> Path:
    """Scaffold a minimal skills tree inside tmp_path and return the root."""
    # alpha/SKILL.md — standard frontmatter
    alpha = tmp_path / "alpha"
    alpha.mkdir()
    (alpha / "SKILL.md").write_text(
        "---\n"
        "name: alpha-skill\n"
        "description: Alpha description for testing\n"
        "tags: [alpha, testing, keyword]\n"
        "version: 2.0.0\n"
        "---\n\n"
        "Alpha skill body content.\n",
        encoding="utf-8",
    )

    # beta/SKILL.md — uses skill_name instead of name
    beta = tmp_path / "beta"
    beta.mkdir()
    (beta / "SKILL.md").write_text(
        "---\n"
        "skill_name: beta-skill\n"
        "description: Beta description for security review\n"
        "tags: [beta, security]\n"
        "version: 1.1.0\n"
        "---\n\n"
        "Beta skill body.\n",
        encoding="utf-8",
    )

    # gamma/SKILL.md — no frontmatter at all
    gamma = tmp_path / "gamma"
    gamma.mkdir()
    (gamma / "SKILL.md").write_text(
        "# Gamma Skill\n\nNo frontmatter here.\n",
        encoding="utf-8",
    )

    # nested/deep/SKILL.md — nested structure
    deep = tmp_path / "nested" / "deep"
    deep.mkdir(parents=True)
    (deep / "SKILL.md").write_text(
        "---\n"
        "name: deep-skill\n"
        "description: A deeply nested skill\n"
        "tags: [nested, deep]\n"
        "version: 0.5.0\n"
        "---\n\n"
        "Deep skill content.\n",
        encoding="utf-8",
    )

    return tmp_path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# discover_skills tests
# ---------------------------------------------------------------------------


class TestDiscoverSkills:
    def test_finds_all_skill_md_files(self, tmp_skills: Path) -> None:
        skills = discover_skills([tmp_skills])
        # alpha, beta, gamma (no-frontmatter), deep
        assert len(skills) == 4

    def test_parses_name_from_frontmatter(self, tmp_skills: Path) -> None:
        skills = discover_skills([tmp_skills])
        names = {s.name for s in skills}
        assert "alpha-skill" in names

    def test_parses_skill_name_alternate_field(self, tmp_skills: Path) -> None:
        """skill_name frontmatter key is tolerated as a fallback for name."""
        skills = discover_skills([tmp_skills])
        names = {s.name for s in skills}
        assert "beta-skill" in names

    def test_falls_back_to_directory_name_when_no_frontmatter(self, tmp_skills: Path) -> None:
        """When frontmatter is absent, the parent directory name is used."""
        skills = discover_skills([tmp_skills])
        names = {s.name for s in skills}
        assert "gamma" in names

    def test_parses_description(self, tmp_skills: Path) -> None:
        skills = discover_skills([tmp_skills])
        alpha = next(s for s in skills if s.name == "alpha-skill")
        assert alpha.description == "Alpha description for testing"

    def test_parses_tags_as_list(self, tmp_skills: Path) -> None:
        skills = discover_skills([tmp_skills])
        alpha = next(s for s in skills if s.name == "alpha-skill")
        assert "alpha" in alpha.tags
        assert "testing" in alpha.tags
        assert "keyword" in alpha.tags

    def test_parses_version(self, tmp_skills: Path) -> None:
        skills = discover_skills([tmp_skills])
        alpha = next(s for s in skills if s.name == "alpha-skill")
        assert alpha.version == "2.0.0"

    def test_path_is_absolute(self, tmp_skills: Path) -> None:
        skills = discover_skills([tmp_skills])
        for skill in skills:
            assert skill.path.is_absolute()

    def test_finds_nested_skill(self, tmp_skills: Path) -> None:
        skills = discover_skills([tmp_skills])
        names = {s.name for s in skills}
        assert "deep-skill" in names

    def test_empty_directory_returns_empty(self, tmp_path: Path) -> None:
        skills = discover_skills([tmp_path])
        assert skills == []

    def test_nonexistent_path_returns_empty(self, tmp_path: Path) -> None:
        skills = discover_skills([tmp_path / "nonexistent"])
        assert skills == []

    def test_source_label_applied(self, tmp_skills: Path) -> None:
        skills = discover_skills([tmp_skills], source_label="project")
        assert all(s.source == "project" for s in skills)

    def test_fixture_skills_parsed(self) -> None:
        """Verify the checked-in fixture skills are discoverable."""
        if not FIXTURES_DIR.exists():
            pytest.skip("Fixture skills directory not present")
        skills = discover_skills([FIXTURES_DIR])
        names = {s.name for s in skills}
        assert "python-idioms" in names
        assert "stride-dread" in names
        assert "pytest-patterns" in names


class TestDiscoverSkillsWithSources:
    def test_deduplicates_by_name(self, tmp_path: Path) -> None:
        """First match (earlier source) wins on name collision."""
        src1 = tmp_path / "src1"
        src1.mkdir()
        (src1 / "dupe" ).mkdir()
        (src1 / "dupe" / "SKILL.md").write_text(
            "---\nname: dupe-skill\ndescription: From source 1\ntags: []\nversion: 1.0\n---\nBody 1.\n",
            encoding="utf-8",
        )

        src2 = tmp_path / "src2"
        src2.mkdir()
        (src2 / "dupe").mkdir()
        (src2 / "dupe" / "SKILL.md").write_text(
            "---\nname: dupe-skill\ndescription: From source 2\ntags: []\nversion: 2.0\n---\nBody 2.\n",
            encoding="utf-8",
        )

        skills = discover_skills_with_sources([(src1, "project"), (src2, "machine")])
        dupe_skills = [s for s in skills if s.name == "dupe-skill"]
        assert len(dupe_skills) == 1
        assert dupe_skills[0].source == "project"
        assert dupe_skills[0].description == "From source 1"


# ---------------------------------------------------------------------------
# search_skills tests
# ---------------------------------------------------------------------------


class TestSearchSkills:
    @pytest.fixture
    def skill_set(self) -> list[SkillMeta]:
        """A fixed set of SkillMeta objects for search testing."""
        return [
            SkillMeta(
                name="python-idioms",
                description="Python idiomatic patterns",
                path=Path("/fake/python-idioms/SKILL.md"),
                tags=["python", "patterns"],
            ),
            SkillMeta(
                name="stride-dread",
                description="Security threat modeling",
                path=Path("/fake/stride-dread/SKILL.md"),
                tags=["security", "threat-modeling"],
            ),
            SkillMeta(
                name="pytest-patterns",
                description="Pytest testing patterns",
                path=Path("/fake/pytest-patterns/SKILL.md"),
                tags=["pytest", "testing", "python"],
            ),
        ]

    def test_matches_on_name(self, skill_set: list[SkillMeta]) -> None:
        results = search_skills("stride", skill_set)
        assert len(results) == 1
        assert results[0].name == "stride-dread"

    def test_matches_on_description(self, skill_set: list[SkillMeta]) -> None:
        results = search_skills("threat modeling", skill_set)
        assert any(s.name == "stride-dread" for s in results)

    def test_matches_on_tags(self, skill_set: list[SkillMeta]) -> None:
        results = search_skills("pytest", skill_set)
        assert len(results) == 1
        assert results[0].name == "pytest-patterns"

    def test_matches_multiple_skills_on_shared_tag(self, skill_set: list[SkillMeta]) -> None:
        results = search_skills("python", skill_set)
        names = {s.name for s in results}
        assert "python-idioms" in names
        assert "pytest-patterns" in names

    def test_empty_query_returns_all(self, skill_set: list[SkillMeta]) -> None:
        results = search_skills("", skill_set)
        assert len(results) == len(skill_set)

    def test_no_match_returns_empty(self, skill_set: list[SkillMeta]) -> None:
        results = search_skills("zyxzyx_nomatch", skill_set)
        assert results == []

    def test_case_insensitive(self, skill_set: list[SkillMeta]) -> None:
        results = search_skills("PYTHON", skill_set)
        assert any(s.name == "python-idioms" for s in results)

    def test_multi_token_any_match(self, skill_set: list[SkillMeta]) -> None:
        """Multi-token query: a skill matching ANY token is included."""
        results = search_skills("security patterns", skill_set)
        names = {s.name for s in results}
        assert "stride-dread" in names      # matches "security"
        assert "python-idioms" in names      # matches "patterns"


# ---------------------------------------------------------------------------
# get_skill_content tests
# ---------------------------------------------------------------------------


class TestGetSkillContent:
    def test_returns_full_file_content(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\nname: my-skill\ndescription: Test\ntags: []\nversion: 1.0\n---\n\nBody text.\n",
            encoding="utf-8",
        )
        meta = SkillMeta(
            name="my-skill",
            description="Test",
            path=skill_file.resolve(),
        )
        content = get_skill_content(meta)
        assert "Body text." in content
        assert "---" in content


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
def skills_root(tmp_path: Path) -> Path:
    """Create a minimal skills tree and return its root path."""
    for skill_name, desc, tags_str in [
        ("alpha", "Alpha skill description", "[alpha, testing]"),
        ("beta", "Beta security skill", "[beta, security]"),
    ]:
        d = tmp_path / skill_name
        d.mkdir()
        (d / "SKILL.md").write_text(
            f"---\nname: {skill_name}\ndescription: {desc}\ntags: {tags_str}\nversion: 1.0\n---\n\n{skill_name} body.\n",
            encoding="utf-8",
        )
    return tmp_path


@pytest.fixture
def patched_runner(runner: CliRunner, skills_root: Path, monkeypatch: pytest.MonkeyPatch):
    """Runner with skill discovery patched to use tmp skills_root."""
    import cc.commands.skill as skill_cmd

    def _patched_load(scope="all"):
        from cc.core.skill_store import discover_skills_with_sources
        pairs = [(skills_root, "project")]
        return discover_skills_with_sources(pairs)

    monkeypatch.setattr(skill_cmd, "_load_all_skills", _patched_load)
    return runner


class TestSkillListCommand:
    def test_exits_zero(self, patched_runner: CliRunner) -> None:
        result = patched_runner.invoke(app, ["skill", "list"])
        assert result.exit_code == 0

    def test_shows_skill_names(self, patched_runner: CliRunner) -> None:
        result = patched_runner.invoke(app, ["skill", "list"])
        assert "alpha" in result.output
        assert "beta" in result.output

    def test_shows_descriptions(self, patched_runner: CliRunner) -> None:
        result = patched_runner.invoke(app, ["skill", "list"])
        assert "Alpha skill description" in result.output

    def test_json_output(self, patched_runner: CliRunner) -> None:
        result = patched_runner.invoke(app, ["skill", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        names = [d["name"] for d in data]
        assert "alpha" in names
        assert "beta" in names

    def test_invalid_scope_exits_nonzero(self, patched_runner: CliRunner) -> None:
        result = patched_runner.invoke(app, ["skill", "list", "--scope", "bogus"])
        assert result.exit_code != 0


class TestSkillSearchCommand:
    def test_matches_by_name(self, patched_runner: CliRunner) -> None:
        result = patched_runner.invoke(app, ["skill", "search", "alpha"])
        assert result.exit_code == 0
        assert "alpha" in result.output

    def test_matches_by_tag(self, patched_runner: CliRunner) -> None:
        result = patched_runner.invoke(app, ["skill", "search", "security"])
        assert result.exit_code == 0
        assert "beta" in result.output

    def test_no_match_shows_message(self, patched_runner: CliRunner) -> None:
        result = patched_runner.invoke(app, ["skill", "search", "zyxzyx_nomatch"])
        assert result.exit_code == 0
        assert "No matching" in result.output

    def test_json_output(self, patched_runner: CliRunner) -> None:
        result = patched_runner.invoke(app, ["skill", "search", "alpha", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert any(d["name"] == "alpha" for d in data)


class TestSkillGetCommand:
    def test_returns_full_content(self, patched_runner: CliRunner) -> None:
        result = patched_runner.invoke(app, ["skill", "get", "alpha"])
        assert result.exit_code == 0
        assert "alpha body." in result.output

    def test_includes_frontmatter(self, patched_runner: CliRunner) -> None:
        result = patched_runner.invoke(app, ["skill", "get", "alpha"])
        assert result.exit_code == 0
        assert "---" in result.output

    def test_not_found_exits_2(self, patched_runner: CliRunner) -> None:
        result = patched_runner.invoke(app, ["skill", "get", "nonexistent"])
        assert result.exit_code == 2

    def test_output_is_plain_text(self, patched_runner: CliRunner) -> None:
        """get output should not contain Rich markup codes."""
        result = patched_runner.invoke(app, ["skill", "get", "beta"])
        assert result.exit_code == 0
        # Rich markup would leave [bold], [/bold] etc. in output when piped
        assert "[bold]" not in result.output
        assert "[/bold]" not in result.output


class TestSkillEvaluateRemoved:
    """TASK-29: cc skill evaluate must no longer be a registered subcommand."""

    def test_evaluate_not_in_help(self, patched_runner: CliRunner) -> None:
        """cc skill --help must not list 'evaluate' as a subcommand."""
        result = patched_runner.invoke(app, ["skill", "--help"])
        assert result.exit_code == 0
        assert "evaluate" not in result.output

    def test_evaluate_subcommand_exits_nonzero(self, patched_runner: CliRunner) -> None:
        """Invoking cc skill evaluate directly must exit non-zero (unknown command)."""
        result = patched_runner.invoke(app, ["skill", "evaluate"])
        assert result.exit_code != 0


class TestSkillPathCommand:
    def test_returns_absolute_path(self, patched_runner: CliRunner, skills_root: Path) -> None:
        result = patched_runner.invoke(app, ["skill", "path", "alpha"])
        assert result.exit_code == 0
        path = Path(result.output.strip())
        assert path.is_absolute()
        assert path.name == "SKILL.md"

    def test_path_points_to_correct_skill(self, patched_runner: CliRunner, skills_root: Path) -> None:
        result = patched_runner.invoke(app, ["skill", "path", "beta"])
        assert result.exit_code == 0
        path = Path(result.output.strip())
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "beta" in content

    def test_not_found_exits_2(self, patched_runner: CliRunner) -> None:
        result = patched_runner.invoke(app, ["skill", "path", "nonexistent"])
        assert result.exit_code == 2
