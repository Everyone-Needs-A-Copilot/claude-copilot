"""Contract tests for `cc skill select` (work package C, task C1/C4).

New test file only — no existing test module, case, or assertion is
modified. Covers the acceptance surface named in task 31 (C4):

- the receipt key set (top-level, `selected[]`, and `excluded[]`)
- a `--required` skill retained in full at `max_chars=0`, with
  `mandatory_over_budget` true
- an `optional-budget` exclusion that carries its `characters`
- identical bytes across two skills producing exactly one
  `duplicate-content` exclusion
- an empty query selecting nothing
- a missing required name raising rather than silently skipping

It also pins `cc skill get` and `cc skill search` output shape against a
synthetic fixture, to prove the additive `select` command has not disturbed
the pre-existing `get`/`search` contract (both commands share the same
`_load_trusted_skills` loader and `_skill_to_dict` serializer as `select`;
see `tools/cc/src/cc/commands/skill.py`).

All skill content here is synthetic. No production skill, real corpus, or
existing test fixture is read or depended on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cc.core.skill_store import (
    SkillMeta,
    find_skill_by_name,
    select_skill_context,
)
from cc.main import app

pytestmark = pytest.mark.filterwarnings("ignore")


# ---------------------------------------------------------------------------
# Synthetic skill tree
# ---------------------------------------------------------------------------


def _write_skill(root: Path, dirname: str, *, name: str, description: str, tags: list[str], body: str) -> Path:
    skill_dir = root / dirname
    skill_dir.mkdir(parents=True, exist_ok=True)
    tags_yaml = "[" + ", ".join(tags) + "]"
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"tags: {tags_yaml}\n"
        "version: 1.0.0\n"
        "---\n\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return skill_dir / "SKILL.md"


@pytest.fixture
def skills_root(tmp_path: Path) -> Path:
    """A synthetic, disposable skill tree — never the real repo or corpus."""
    root = tmp_path / "skills"
    root.mkdir()

    # A required skill, content large enough that max_chars=0 clearly forces
    # the over-budget branch (mandatory_over_budget=True) while still being
    # retained in full.
    _write_skill(
        root,
        "widget-required",
        name="widget-required",
        description="Synthetic required widget skill for contract testing",
        tags=["widget", "contract"],
        body="R" * 500,
    )

    # An optional skill that matches the query "widget" and is large enough
    # to exceed a small budget on its own, forcing an optional-budget
    # exclusion that must carry its `characters` count.
    _write_skill(
        root,
        "widget-optional-big",
        name="widget-optional-big",
        description="Synthetic large optional widget skill",
        tags=["widget"],
        body="O" * 5000,
    )

    # Two skills with byte-IDENTICAL file content (no `name:` frontmatter
    # field, so each parses its distinct name from its own directory,
    # per discover_skills's directory-name fallback) so dedup-by-
    # content-hash produces exactly one duplicate-content exclusion and
    # exactly one survives in selected[]. Content must be identical at the
    # full-file-bytes level, since `source_revision`/dedup hashes the bytes
    # `get_skill_content_with_receipt` returns (the whole SKILL.md, not
    # just the body) -- see skill_store.py:652 `digest = sha256(content)`.
    dup_content = (
        "---\n"
        "description: Synthetic duplicate widget skill\n"
        "tags: [widget]\n"
        "version: 1.0.0\n"
        "---\n\n"
        "DUPLICATE-BYTES-FOR-CONTRACT-TEST\n"
    )
    for dirname in ("widget-dup-a", "widget-dup-b"):
        d = root / dirname
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(dup_content, encoding="utf-8")

    return root


@pytest.fixture
def skills(skills_root: Path):
    from cc.core.skill_store import discover_skills_with_sources

    return discover_skills_with_sources([(skills_root, "project")])


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def patched_runner(runner: CliRunner, skills_root: Path, monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    """CLI runner with skill discovery patched to the synthetic tmp_path
    tree, following the same stub pattern as tests/test_skills.py's
    `patched_runner` fixture (a Stub of the loader, not a Mock — nothing
    here asserts on how the loader was called)."""
    import cc.commands.skill as skill_cmd

    def _patched_load(scope: str = "all"):
        from cc.core.skill_store import discover_skills_with_sources

        return discover_skills_with_sources([(skills_root, "project")])

    monkeypatch.setattr(skill_cmd, "_load_all_skills", _patched_load)
    return runner


# ---------------------------------------------------------------------------
# Receipt key set
# ---------------------------------------------------------------------------

TOP_LEVEL_RECEIPT_KEYS = {
    "schema_version",
    "query",
    "budget_unit",
    "max_chars",
    "loaded_characters",
    "mandatory_over_budget",
    "selected",
    "excluded",
    "token_count",
    "boundary",
}

SELECTED_ITEM_KEYS = {
    "name",
    "source",
    "source_revision",
    "selection_reason",
    "required",
    "characters",
    "utf8_bytes",
    "content",
    "receipt",
    "path",
}


class TestReceiptKeySet:
    def test_top_level_receipt_key_set_is_exact(self, patched_runner: CliRunner) -> None:
        result = patched_runner.invoke(app, ["skill", "select", "widget", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert set(data.keys()) == TOP_LEVEL_RECEIPT_KEYS

    def test_selected_item_key_set_is_exact(self, patched_runner: CliRunner) -> None:
        result = patched_runner.invoke(
            app, ["skill", "select", "", "--required", "widget-required", "--json"]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert len(data["selected"]) == 1
        assert set(data["selected"][0].keys()) == SELECTED_ITEM_KEYS

    def test_optional_budget_exclusion_key_set(self, patched_runner: CliRunner) -> None:
        # Budget small enough that the big optional widget skill cannot fit.
        result = patched_runner.invoke(
            app, ["skill", "select", "widget-optional-big", "--max-chars", "10", "--json"]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        budget_exclusions = [e for e in data["excluded"] if e["reason"] == "optional-budget"]
        assert len(budget_exclusions) == 1
        assert set(budget_exclusions[0].keys()) == {"name", "reason", "characters"}

    def test_duplicate_content_exclusion_key_set(self, patched_runner: CliRunner) -> None:
        result = patched_runner.invoke(app, ["skill", "select", "widget-dup", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        dup_exclusions = [e for e in data["excluded"] if e["reason"] == "duplicate-content"]
        assert len(dup_exclusions) == 1
        assert set(dup_exclusions[0].keys()) == {"name", "reason", "source_sha256"}


# ---------------------------------------------------------------------------
# --required retained in full at max_chars=0, mandatory_over_budget=True
# ---------------------------------------------------------------------------


class TestRequiredRetainedUnderZeroBudget:
    def test_required_retained_in_full_at_zero_budget(
        self, patched_runner: CliRunner, skills_root: Path
    ) -> None:
        expected_characters = len(
            (skills_root / "widget-required" / "SKILL.md").read_text(encoding="utf-8")
        )
        result = patched_runner.invoke(
            app,
            [
                "skill",
                "select",
                "",
                "--required",
                "widget-required",
                "--max-chars",
                "0",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)

        assert data["mandatory_over_budget"] is True
        assert data["max_chars"] == 0
        assert len(data["selected"]) == 1

        entry = data["selected"][0]
        assert entry["name"] == "widget-required"
        assert entry["required"] is True
        assert entry["selection_reason"] == "explicit-required"
        # Full file content, not truncated by the zero budget.
        assert entry["characters"] == expected_characters
        assert data["loaded_characters"] == entry["characters"]
        # No exclusion should record the required skill as budget-rejected —
        # required content is structurally unreachable by the budget branch.
        assert data["excluded"] == []

    def test_api_select_skill_context_matches_cli_shape(
        self, skills, skills_root: Path
    ) -> None:
        """Exercise the underlying function directly (not through the CLI)
        to pin the contract at the layer `cc.api.skill_select` also calls."""
        expected_characters = len(
            (skills_root / "widget-required" / "SKILL.md").read_text(encoding="utf-8")
        )
        result = select_skill_context(
            "", skills, required=("widget-required",), max_chars=0
        )
        assert result["mandatory_over_budget"] is True
        assert result["selected"][0]["characters"] == expected_characters


# ---------------------------------------------------------------------------
# optional-budget exclusion carries `characters`
# ---------------------------------------------------------------------------


class TestOptionalBudgetExclusion:
    def test_optional_budget_exclusion_carries_characters(
        self, patched_runner: CliRunner, skills_root: Path
    ) -> None:
        expected_characters = len(
            (skills_root / "widget-optional-big" / "SKILL.md").read_text(encoding="utf-8")
        )
        result = patched_runner.invoke(
            app, ["skill", "select", "widget-optional-big", "--max-chars", "10", "--json"]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)

        budget_exclusions = [e for e in data["excluded"] if e["reason"] == "optional-budget"]
        assert len(budget_exclusions) == 1
        assert budget_exclusions[0]["name"] == "widget-optional-big"
        assert budget_exclusions[0]["characters"] == expected_characters
        assert data["selected"] == []


# ---------------------------------------------------------------------------
# Identical bytes -> exactly one duplicate-content exclusion
# ---------------------------------------------------------------------------


class TestDuplicateContentDedup:
    def test_identical_bytes_yield_exactly_one_duplicate_exclusion(
        self, patched_runner: CliRunner
    ) -> None:
        result = patched_runner.invoke(app, ["skill", "select", "widget-dup", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)

        dup_exclusions = [e for e in data["excluded"] if e["reason"] == "duplicate-content"]
        assert len(dup_exclusions) == 1

        # Exactly one of the two identical-content skills survives in
        # selected[]; the excluded one names the OTHER of the pair.
        selected_names = {item["name"] for item in data["selected"]}
        excluded_names = {e["name"] for e in dup_exclusions}
        assert selected_names.isdisjoint(excluded_names)
        assert (selected_names | excluded_names) == {"widget-dup-a", "widget-dup-b"}


# ---------------------------------------------------------------------------
# Empty query selects nothing
# ---------------------------------------------------------------------------


class TestEmptyQuery:
    def test_empty_query_with_no_required_selects_nothing(self, patched_runner: CliRunner) -> None:
        result = patched_runner.invoke(app, ["skill", "select", "", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["selected"] == []
        assert data["excluded"] == []
        assert data["loaded_characters"] == 0
        assert data["mandatory_over_budget"] is False

    def test_empty_query_api_call_selects_nothing(self, skills) -> None:
        result = select_skill_context("", skills)
        assert result["selected"] == []


# ---------------------------------------------------------------------------
# Missing required raises, never silently skipped
# ---------------------------------------------------------------------------


class TestMissingRequiredRaises:
    def test_missing_required_exits_nonzero_with_stated_name(self, patched_runner: CliRunner) -> None:
        result = patched_runner.invoke(
            app, ["skill", "select", "widget", "--required", "no-such-skill-xyz", "--json"]
        )
        assert result.exit_code == 2
        assert "Required skill not found: no-such-skill-xyz" in result.output
        # No JSON receipt is printed on this failure path -- a caller must
        # not be able to parse a partial/silent-skip receipt out of it.
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.output)

    def test_missing_required_api_raises_value_error(self, skills) -> None:
        with pytest.raises(ValueError, match="Required skill not found: no-such-skill-xyz"):
            select_skill_context("widget", skills, required=("no-such-skill-xyz",))

    def test_find_skill_by_name_returns_none_for_missing_name(self, skills) -> None:
        # The primitive the required-resolution loop is built on: a miss is
        # `None`, never an exception here — the ValueError is raised one
        # layer up in select_skill_context, not swallowed anywhere in between.
        assert find_skill_by_name("no-such-skill-xyz", skills) is None


# ---------------------------------------------------------------------------
# `skill get` / `skill search` compatibility pin
#
# Captured against a synthetic fixture with `select` already implemented
# (select predates this work package per wp-c-evidence.md §1 — the
# mechanism was verified pre-existing, not authored by C1-C4). This pins
# the CURRENT shape as a regression guard: any future edit to `get`/
# `search`/`_skill_to_dict` that changes this shape will fail here first.
# ---------------------------------------------------------------------------


class TestSkillGetSearchCompatibilityPin:
    def test_skill_get_plain_output_is_raw_content_with_no_decoration(
        self, patched_runner: CliRunner, skills_root: Path
    ) -> None:
        result = patched_runner.invoke(app, ["skill", "get", "widget-required"])
        assert result.exit_code == 0, result.output
        raw = (skills_root / "widget-required" / "SKILL.md").read_text(encoding="utf-8")
        assert result.output == raw

    def test_skill_get_json_shape_is_pinned(self, patched_runner: CliRunner) -> None:
        result = patched_runner.invoke(app, ["skill", "get", "widget-required", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert set(data.keys()) == {
            "name",
            "description",
            "tags",
            "version",
            "source",
            "triggers",
            "metadata",
            "path",
            "content",
            "receipt",
        }
        assert data["name"] == "widget-required"
        assert data["description"] == "Synthetic required widget skill for contract testing"
        assert data["tags"] == ["widget", "contract"]
        assert data["receipt"] is None  # unsigned, non-Knowledge source
        assert "R" * 500 in data["content"]

    def test_skill_get_missing_name_exits_2(self, patched_runner: CliRunner) -> None:
        result = patched_runner.invoke(app, ["skill", "get", "no-such-skill-xyz"])
        assert result.exit_code == 2
        assert "Skill not found" in result.stderr

    def test_skill_search_json_shape_is_pinned(self, patched_runner: CliRunner) -> None:
        result = patched_runner.invoke(app, ["skill", "search", "widget", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert isinstance(data, list)
        names = {d["name"] for d in data}
        assert names == {
            "widget-required",
            "widget-optional-big",
            "widget-dup-a",
            "widget-dup-b",
        }
        for entry in data:
            # search never returns content, unlike get/select.
            assert "content" not in entry
            assert set(entry.keys()) == {
                "name",
                "description",
                "tags",
                "version",
                "source",
                "triggers",
                "metadata",
                "path",
            }

    def test_skill_search_no_match_returns_empty_list_not_error(
        self, patched_runner: CliRunner
    ) -> None:
        result = patched_runner.invoke(
            app, ["skill", "search", "zzzzqqqnothingmatches", "--json"]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == []

    def test_skill_search_plain_table_output_contains_name(
        self, patched_runner: CliRunner
    ) -> None:
        result = patched_runner.invoke(app, ["skill", "search", "widget"])
        assert result.exit_code == 0, result.output
        assert "widget-required" in result.output
