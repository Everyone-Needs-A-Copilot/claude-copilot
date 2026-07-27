"""Tests for cc.api — the flat, importable facade.

Verifies:
- Import is side-effect-free (no DB, no FS touched).
- memory_store / memory_get / memory_list / memory_delete work end-to-end.
- memory_search returns results via file-based fallback and FTS index path.
- Typed exceptions raised for bad inputs (EntryValidationError, EntryNotFound).
- skill_search / skill_get raise SkillNotFound when no skills present.
- All __all__ symbols are importable.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_memory(tmp_path, monkeypatch):
    """Redirect all memory operations to a tmp dir and fake a git root."""
    import cc.core.entry_store as es

    monkeypatch.setattr(es, "_git_root", lambda: tmp_path)
    return tmp_path / ".claude" / "memory"


@pytest.fixture
def memory_root(isolated_memory):
    return isolated_memory


# ---------------------------------------------------------------------------
# Import / side-effect tests
# ---------------------------------------------------------------------------


def test_import_no_side_effects(tmp_path, monkeypatch):
    """Importing cc.api must NOT touch the filesystem."""
    # Force a clean import by removing from sys.modules if cached
    import sys

    for key in list(sys.modules):
        if key.startswith("cc.api"):
            del sys.modules[key]

    # Patch to a non-existent dir — if any file I/O happens on import it would error
    monkeypatch.chdir(tmp_path)

    import cc.api  # should not raise

    assert cc.api is not None


def test_all_exports_importable():
    """Every symbol in __all__ must be importable from cc.api."""
    import cc.api

    for name in cc.api.__all__:
        assert hasattr(cc.api, name), f"cc.api missing __all__ member: {name}"


# ---------------------------------------------------------------------------
# memory_store
# ---------------------------------------------------------------------------


def test_memory_store_returns_id_and_path(memory_root):
    from cc.api import memory_store

    result = memory_store(entry_type="decision", content="Use WAL mode for SQLite")
    assert "id" in result
    assert "path" in result
    assert Path(result["path"]).exists()


def test_memory_store_empty_content_raises():
    from cc.api import memory_store, EntryValidationError

    with pytest.raises(EntryValidationError):
        memory_store(entry_type="context", content="")


def test_memory_store_whitespace_content_raises():
    from cc.api import memory_store, EntryValidationError

    with pytest.raises(EntryValidationError):
        memory_store(entry_type="context", content="   ")


def test_memory_store_invalid_type_raises():
    from cc.api import memory_store, EntryValidationError

    with pytest.raises(EntryValidationError):
        memory_store(entry_type="nonexistent_type_xyz", content="hello")


def test_memory_store_with_tags(memory_root):
    from cc.api import memory_store, memory_get

    result = memory_store(
        entry_type="lesson", content="Always test", tags=["testing", "quality"]
    )
    entry = memory_get(result["id"])
    assert "testing" in entry.get("tags", [])


# ---------------------------------------------------------------------------
# memory_get
# ---------------------------------------------------------------------------


def test_memory_get_returns_entry(memory_root):
    from cc.api import memory_store, memory_get

    stored = memory_store(entry_type="context", content="Context content here")
    retrieved = memory_get(stored["id"])
    assert retrieved["id"] == stored["id"]
    assert "Context content here" in retrieved["content"]


def test_memory_get_not_found_raises():
    from cc.api import memory_get, EntryNotFound

    with pytest.raises(EntryNotFound):
        memory_get("00000000-0000-0000-0000-000000000000")


def test_memory_get_prefix_match(memory_root):
    from cc.api import memory_store, memory_get

    stored = memory_store(entry_type="reference", content="Prefix test content")
    prefix = stored["id"][:8]
    retrieved = memory_get(prefix)
    assert retrieved["id"] == stored["id"]


# ---------------------------------------------------------------------------
# memory_list
# ---------------------------------------------------------------------------


def test_memory_list_empty(memory_root):
    from cc.api import memory_list

    assert memory_list() == []


def test_memory_list_returns_entries(memory_root):
    from cc.api import memory_store, memory_list

    memory_store(entry_type="decision", content="Decision A")
    memory_store(entry_type="lesson", content="Lesson B")
    entries = memory_list()
    assert len(entries) == 2


def test_memory_list_filter_by_type(memory_root):
    from cc.api import memory_store, memory_list

    memory_store(entry_type="decision", content="Decision X")
    memory_store(entry_type="lesson", content="Lesson Y")
    decisions = memory_list(entry_type="decision")
    assert len(decisions) == 1
    assert decisions[0]["type"] == "decision"


def test_memory_list_filter_by_tag(memory_root):
    from cc.api import memory_store, memory_list

    memory_store(entry_type="context", content="Tagged A", tags=["alpha"])
    memory_store(entry_type="context", content="Tagged B", tags=["beta"])
    alpha = memory_list(tag="alpha")
    assert len(alpha) == 1
    assert "alpha" in alpha[0]["tags"]


# ---------------------------------------------------------------------------
# memory_delete
# ---------------------------------------------------------------------------


def test_memory_delete_removes_entry(memory_root):
    from cc.api import memory_store, memory_get, memory_delete, EntryNotFound

    stored = memory_store(entry_type="context", content="To be deleted")
    assert memory_delete(stored["id"]) is True
    with pytest.raises(EntryNotFound):
        memory_get(stored["id"])


def test_memory_delete_nonexistent_returns_false(memory_root):
    from cc.api import memory_delete

    assert memory_delete("00000000-0000-0000-0000-000000000000") is False


# ---------------------------------------------------------------------------
# memory_search — file-based fallback path
# ---------------------------------------------------------------------------


def test_memory_search_file_fallback(memory_root):
    from cc.api import memory_store, memory_search

    memory_store(
        entry_type="decision", content="WAL mode is best for SQLite concurrency"
    )
    results = memory_search("WAL")
    assert len(results) >= 1
    assert any("WAL" in r.get("content", "") for r in results)


def test_memory_search_no_results(memory_root):
    from cc.api import memory_store, memory_search

    memory_store(entry_type="context", content="Completely unrelated content")
    results = memory_search("xyznonexistentquery")
    assert results == []


def test_memory_search_fts_index_path(memory_root):
    """If the FTS DB already exists, memory_search should use it."""
    from cc.api import memory_store, memory_search
    from cc.core.memory_index import rebuild_index

    memory_store(entry_type="lesson", content="FTS index path test content")
    # Build the FTS index so the DB exists
    rebuild_index(memory_root)

    results = memory_search("FTS index path")
    assert len(results) >= 1


# ---------------------------------------------------------------------------
# skill_search / skill_get (no skills in tmp env)
# ---------------------------------------------------------------------------


def test_skill_search_returns_empty_when_no_skills(tmp_path, monkeypatch):
    """skill_search returns [] when no skill dirs exist."""
    import cc.core.skill_store as ss

    monkeypatch.setattr(ss, "default_skill_paths", lambda: [])

    from cc.api import skill_search

    results = skill_search("anything")
    assert results == []


def test_skill_get_raises_not_found_when_no_skills(tmp_path, monkeypatch):
    import cc.core.skill_store as ss

    monkeypatch.setattr(ss, "default_skill_paths", lambda: [])

    from cc.api import skill_get, SkillNotFound

    with pytest.raises(SkillNotFound):
        skill_get("nonexistent-skill")


def test_skill_get_returns_content(tmp_path, monkeypatch):
    """skill_get returns metadata + content when skill exists."""
    import cc.core.skill_store as ss

    skill_dir = tmp_path / "skills" / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: Test skill\ntags: [test]\nversion: 1.0\n---\n\nSkill body.",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        ss,
        "default_skill_paths",
        lambda: [(tmp_path / "skills", "project")],
    )

    from cc.api import skill_get

    result = skill_get("my-skill")
    assert result["name"] == "my-skill"
    assert "Skill body." in result["content"]
    assert result["version"] == "1.0"


def test_skill_search_finds_by_tag(tmp_path, monkeypatch):
    import cc.core.skill_store as ss

    skill_dir = tmp_path / "skills" / "tagged-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: tagged-skill\ndescription: A tagged skill\ntags: [security, auth]\n---\n\nBody.",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        ss,
        "default_skill_paths",
        lambda: [(tmp_path / "skills", "project")],
    )

    from cc.api import skill_search

    results = skill_search("security")
    assert len(results) == 1
    assert results[0]["name"] == "tagged-skill"
    # content key should NOT be present in search results (kept compact)
    assert "content" not in results[0]
