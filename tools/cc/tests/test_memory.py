"""Tests for cc memory commands: store, get, list, delete, search, index."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from cc.core.entry_format import (
    EntryValidationError,
    build_frontmatter,
    parse_frontmatter,
    parse_tags,
    render_entry,
    serialize_frontmatter,
    validate_entry_type,
)
from cc.core.entry_store import (
    delete_entry,
    get_entry,
    list_entries,
    resolve_memory_root,
    search_entries_files,
    store_entry,
)
from cc.core.memory_index import (
    index_status,
    rebuild_index,
    search_index,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_root(tmp_path, monkeypatch):
    """Patch resolve_memory_root so all stores go into tmp_path."""
    root = tmp_path / ".claude" / "memory"

    # Patch git root resolution so scope="project" resolves to tmp_path
    import cc.core.entry_store as es

    monkeypatch.setattr(es, "_git_root", lambda: tmp_path)
    return root


# ---------------------------------------------------------------------------
# entry_format tests
# ---------------------------------------------------------------------------

class TestEntryFormat:
    def test_validate_entry_type_valid(self):
        assert validate_entry_type("decision") == "decision"

    def test_validate_entry_type_invalid(self):
        with pytest.raises(EntryValidationError):
            validate_entry_type("unknown")

    def test_parse_tags_from_string(self):
        assert parse_tags("auth, security, api") == ["api", "auth", "security"]

    def test_parse_tags_from_list(self):
        assert parse_tags(["b", "a"]) == ["a", "b"]

    def test_parse_tags_none(self):
        assert parse_tags(None) == []

    def test_build_frontmatter_keys(self):
        fm = build_frontmatter(
            entry_id="abc-123",
            entry_type="lesson",
            tags=["x"],
            scope="project",
        )
        assert fm["id"] == "abc-123"
        assert fm["type"] == "lesson"
        assert fm["tags"] == ["x"]
        assert fm["scope"] == "project"
        assert "created" in fm
        assert "updated" in fm

    def test_serialize_and_parse_roundtrip(self):
        fm = build_frontmatter(
            entry_id="test-uuid",
            entry_type="decision",
            tags=["a", "b"],
            scope="global",
        )
        text = render_entry(fm, "Some body text")
        parsed_fm, body = parse_frontmatter(text)

        assert parsed_fm["id"] == "test-uuid"
        assert parsed_fm["type"] == "decision"
        assert "a" in parsed_fm["tags"]
        assert "b" in parsed_fm["tags"]
        assert body.strip() == "Some body text"

    def test_parse_frontmatter_missing_block_raises(self):
        with pytest.raises(EntryValidationError):
            parse_frontmatter("no frontmatter here")

    def test_parse_frontmatter_unclosed_raises(self):
        with pytest.raises(EntryValidationError):
            parse_frontmatter("---\nid: x\n")

    def test_render_entry_structure(self):
        fm = build_frontmatter(
            entry_id="u1",
            entry_type="context",
            tags=[],
            scope="project",
        )
        result = render_entry(fm, "hello")
        assert result.startswith("---\n")
        assert "id: u1" in result
        assert "hello" in result


# ---------------------------------------------------------------------------
# entry_store tests
# ---------------------------------------------------------------------------

class TestEntryStore:
    def test_store_creates_uuid_md_file(self, memory_root):
        result = store_entry(entry_type="decision", content="Use SQLite for search cache.", scope="project")

        assert "id" in result
        assert "path" in result
        path = Path(result["path"])
        assert path.exists()
        assert path.suffix == ".md"
        assert path.parent.name == "entries"

    def test_store_writes_correct_frontmatter(self, memory_root):
        result = store_entry(entry_type="lesson", content="Always test.", tags=["test"], scope="project")
        path = Path(result["path"])
        text = path.read_text(encoding="utf-8")

        assert "id:" in text
        assert "type: lesson" in text
        assert "test" in text

    def test_store_creates_gitignore(self, memory_root):
        store_entry(entry_type="context", content="x", scope="project")
        gitignore = memory_root / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text()
        assert "memory.db" in content

    def test_gitignore_created_on_first_store(self, memory_root):
        assert not (memory_root / ".gitignore").exists()
        store_entry(entry_type="context", content="first", scope="project")
        assert (memory_root / ".gitignore").exists()

    def test_get_by_full_uuid(self, memory_root):
        stored = store_entry(entry_type="reference", content="Full UUID retrieval.", scope="project")
        entry = get_entry(stored["id"], scope="project")

        assert entry is not None
        assert entry["id"] == stored["id"]
        assert "Full UUID retrieval" in entry["content"]

    def test_get_by_prefix_uuid(self, memory_root):
        stored = store_entry(entry_type="context", content="Prefix match test.", scope="project")
        prefix = stored["id"][:8]
        entry = get_entry(prefix, scope="project")

        assert entry is not None
        assert entry["id"] == stored["id"]

    def test_get_nonexistent_returns_none(self, memory_root):
        # Ensure entries dir exists
        (memory_root / "entries").mkdir(parents=True, exist_ok=True)
        result = get_entry("nonexistent-uuid", scope="project")
        assert result is None

    def test_get_ambiguous_prefix_raises(self, memory_root):
        # Store two entries whose UUIDs share a very short prefix artificially
        import uuid
        from cc.core.entry_format import build_frontmatter, render_entry
        from cc.core.entry_store import _atomic_write, entries_dir, _ensure_entries_dir

        e_dir = _ensure_entries_dir(memory_root)
        for suffix in ("aaaa-0000-0000-0000-000000000001", "aaaa-0000-0000-0000-000000000002"):
            uid = f"00000000-{suffix}"
            fm = build_frontmatter(entry_id=uid, entry_type="context", tags=[], scope="project")
            text = render_entry(fm, "body")
            _atomic_write(e_dir / f"{uid}.md", text)

        with pytest.raises(ValueError, match="Ambiguous"):
            get_entry("00000000-aaaa", scope="project")

    def test_list_all_entries(self, memory_root):
        store_entry(entry_type="decision", content="d1", scope="project")
        store_entry(entry_type="lesson", content="d2", scope="project")
        entries = list_entries(scope="project")
        assert len(entries) == 2

    def test_list_filter_by_type(self, memory_root):
        store_entry(entry_type="decision", content="decision entry", scope="project")
        store_entry(entry_type="lesson", content="lesson entry", scope="project")
        entries = list_entries(scope="project", entry_type="decision")
        assert len(entries) == 1
        assert entries[0]["type"] == "decision"

    def test_list_filter_by_tag(self, memory_root):
        store_entry(entry_type="context", content="tagged", tags=["auth"], scope="project")
        store_entry(entry_type="context", content="untagged", scope="project")
        entries = list_entries(scope="project", tag="auth")
        assert len(entries) == 1
        assert "auth" in entries[0]["tags"]

    def test_list_empty_dir_returns_empty(self, memory_root):
        entries = list_entries(scope="project")
        assert entries == []

    def test_delete_removes_file(self, memory_root):
        stored = store_entry(entry_type="context", content="to delete", scope="project")
        path = Path(stored["path"])
        assert path.exists()

        result = delete_entry(stored["id"], scope="project")
        assert result is True
        assert not path.exists()

    def test_delete_nonexistent_returns_false(self, memory_root):
        (memory_root / "entries").mkdir(parents=True, exist_ok=True)
        result = delete_entry("no-such-id", scope="project")
        assert result is False

    def test_search_finds_content(self, memory_root):
        store_entry(entry_type="lesson", content="Use atomic writes for safety.", scope="project")
        store_entry(entry_type="decision", content="Choose SQLite FTS5.", scope="project")

        results = search_entries_files("atomic", scope="project")
        assert len(results) == 1
        assert "atomic" in results[0]["content"].lower()

    def test_search_case_insensitive(self, memory_root):
        store_entry(entry_type="context", content="PostgreSQL is great.", scope="project")
        results = search_entries_files("postgresql", scope="project")
        assert len(results) == 1

    def test_search_no_match_returns_empty(self, memory_root):
        store_entry(entry_type="context", content="Something else.", scope="project")
        results = search_entries_files("xyznomatch", scope="project")
        assert results == []

    def test_search_empty_dir_returns_empty(self, memory_root):
        results = search_entries_files("anything", scope="project")
        assert results == []

    def test_search_finds_in_frontmatter_tags(self, memory_root):
        store_entry(entry_type="decision", content="body", tags=["uniquetag"], scope="project")
        results = search_entries_files("uniquetag", scope="project")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# memory_index tests
# ---------------------------------------------------------------------------

class TestMemoryIndex:
    def test_rebuild_creates_db(self, memory_root):
        store_entry(entry_type="context", content="indexed content", scope="project")
        stats = rebuild_index(memory_root)

        assert stats["indexed"] == 1
        assert stats["errors"] == 0
        assert (memory_root / "memory.db").exists()

    def test_rebuild_indexes_all_files(self, memory_root):
        store_entry(entry_type="lesson", content="lesson one", scope="project")
        store_entry(entry_type="lesson", content="lesson two", scope="project")
        stats = rebuild_index(memory_root)
        assert stats["indexed"] == 2

    def test_rebuild_is_idempotent(self, memory_root):
        store_entry(entry_type="context", content="stable content", scope="project")
        rebuild_index(memory_root)
        stats = rebuild_index(memory_root)
        assert stats["indexed"] == 1

    def test_rebuild_fts_schema(self, memory_root):
        store_entry(entry_type="decision", content="schema test", scope="project")
        rebuild_index(memory_root)

        db_path = memory_root / "memory.db"
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT * FROM memory_fts").fetchall()
        conn.close()

        assert len(rows) == 1
        # FTS5 row: (id, type, tags, content) — body may have trailing newline
        assert rows[0][3].strip() == "schema test"

    def test_index_status_in_sync(self, memory_root):
        store_entry(entry_type="context", content="x", scope="project")
        rebuild_index(memory_root)
        info = index_status(memory_root)
        assert info["files"] == 1
        assert info["indexed"] == 1
        assert info["in_sync"] is True

    def test_index_status_out_of_sync(self, memory_root):
        store_entry(entry_type="context", content="x", scope="project")
        rebuild_index(memory_root)
        # Write a second file directly to disk bypassing entry_store (so index is stale)
        import uuid as _uuid
        from cc.core.entry_format import build_frontmatter, render_entry
        from cc.core.entry_store import _atomic_write, entries_dir
        uid = str(_uuid.uuid4())
        fm = build_frontmatter(entry_id=uid, entry_type="lesson", tags=[], scope="project")
        _atomic_write(entries_dir(memory_root) / f"{uid}.md", render_entry(fm, "y"))
        info = index_status(memory_root)
        assert info["files"] == 2
        assert info["indexed"] == 1
        assert info["in_sync"] is False

    def test_index_status_no_db(self, memory_root):
        store_entry(entry_type="context", content="x", scope="project")
        info = index_status(memory_root)
        assert info["files"] == 1
        assert info["indexed"] == 0
        assert info["in_sync"] is False

    def test_search_index_finds_content(self, memory_root):
        store_entry(entry_type="lesson", content="unique phrase here", scope="project")
        rebuild_index(memory_root)
        results = search_index("unique", memory_root)
        assert len(results) == 1
        assert "unique phrase here" in results[0]["content"]

    def test_search_index_no_db_returns_empty(self, memory_root):
        results = search_index("anything", memory_root)
        assert results == []


# ---------------------------------------------------------------------------
# CLI integration tests (via Typer test runner)
# ---------------------------------------------------------------------------

@pytest.fixture
def cli_runner():
    from typer.testing import CliRunner
    return CliRunner()


@pytest.fixture
def cli_app():
    from cc.main import app
    return app


class TestMemoryCLI:
    def _invoke(self, runner, app, args, monkeypatch, memory_root):
        """Helper: patch git root then invoke CLI."""
        import cc.core.entry_store as es
        monkeypatch.setattr(es, "_git_root", lambda: memory_root.parent.parent)
        return runner.invoke(app, args)

    def test_store_exits_zero(self, cli_runner, cli_app, monkeypatch, tmp_path):
        import cc.core.entry_store as es
        monkeypatch.setattr(es, "_git_root", lambda: tmp_path)
        result = cli_runner.invoke(cli_app, ["memory", "store", "--type", "lesson", "Test lesson content"])
        assert result.exit_code == 0
        assert "Stored" in result.output

    def test_store_json_output(self, cli_runner, cli_app, monkeypatch, tmp_path):
        import cc.core.entry_store as es
        monkeypatch.setattr(es, "_git_root", lambda: tmp_path)
        result = cli_runner.invoke(cli_app, ["memory", "store", "--type", "decision", "--json", "Decision content"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "id" in data
        assert "path" in data

    def test_list_empty_shows_no_entries(self, cli_runner, cli_app, monkeypatch, tmp_path):
        import cc.core.entry_store as es
        monkeypatch.setattr(es, "_git_root", lambda: tmp_path)
        result = cli_runner.invoke(cli_app, ["memory", "list"])
        assert result.exit_code == 0
        assert "No entries" in result.output

    def test_store_then_list(self, cli_runner, cli_app, monkeypatch, tmp_path):
        import cc.core.entry_store as es
        monkeypatch.setattr(es, "_git_root", lambda: tmp_path)
        cli_runner.invoke(cli_app, ["memory", "store", "--type", "decision", "My decision"])
        result = cli_runner.invoke(cli_app, ["memory", "list"])
        assert result.exit_code == 0
        assert "decision" in result.output

    def test_get_by_id(self, cli_runner, cli_app, monkeypatch, tmp_path):
        import cc.core.entry_store as es
        monkeypatch.setattr(es, "_git_root", lambda: tmp_path)
        store_result = cli_runner.invoke(cli_app, ["memory", "store", "--type", "lesson", "--json", "Lesson body"])
        data = json.loads(store_result.output)
        entry_id = data["id"]

        result = cli_runner.invoke(cli_app, ["memory", "get", entry_id])
        assert result.exit_code == 0
        assert "Lesson body" in result.output

    def test_delete_with_yes(self, cli_runner, cli_app, monkeypatch, tmp_path):
        import cc.core.entry_store as es
        monkeypatch.setattr(es, "_git_root", lambda: tmp_path)
        store_result = cli_runner.invoke(cli_app, ["memory", "store", "--type", "context", "--json", "To delete"])
        data = json.loads(store_result.output)
        entry_id = data["id"]

        result = cli_runner.invoke(cli_app, ["memory", "delete", "--yes", entry_id])
        assert result.exit_code == 0
        assert "Deleted" in result.output

        # Confirm file gone
        assert not Path(data["path"]).exists()

    def test_search_finds_content(self, cli_runner, cli_app, monkeypatch, tmp_path):
        import cc.core.entry_store as es
        monkeypatch.setattr(es, "_git_root", lambda: tmp_path)
        cli_runner.invoke(cli_app, ["memory", "store", "--type", "context", "Unique searchable phrase xyzzy"])
        result = cli_runner.invoke(cli_app, ["memory", "search", "xyzzy"])
        assert result.exit_code == 0
        assert "xyzzy" in result.output

    def test_search_no_results(self, cli_runner, cli_app, monkeypatch, tmp_path):
        import cc.core.entry_store as es
        monkeypatch.setattr(es, "_git_root", lambda: tmp_path)
        result = cli_runner.invoke(cli_app, ["memory", "search", "nomatch_zyxzyx"])
        assert result.exit_code == 0
        assert "No results" in result.output

    def test_index_rebuild(self, cli_runner, cli_app, monkeypatch, tmp_path):
        import cc.core.entry_store as es
        monkeypatch.setattr(es, "_git_root", lambda: tmp_path)
        cli_runner.invoke(cli_app, ["memory", "store", "--type", "lesson", "index test"])
        result = cli_runner.invoke(cli_app, ["memory", "index", "--rebuild"])
        assert result.exit_code == 0
        assert "rebuilt" in result.output.lower()

    def test_index_status_in_sync(self, cli_runner, cli_app, monkeypatch, tmp_path):
        import cc.core.entry_store as es
        monkeypatch.setattr(es, "_git_root", lambda: tmp_path)
        cli_runner.invoke(cli_app, ["memory", "store", "--type", "context", "status test"])
        cli_runner.invoke(cli_app, ["memory", "index", "--rebuild"])
        result = cli_runner.invoke(cli_app, ["memory", "index", "--status"])
        assert result.exit_code == 0
        assert "in sync" in result.output

    def test_index_status_out_of_sync_exits_3(self, cli_runner, cli_app, monkeypatch, tmp_path):
        """Write a file directly to entries/ bypassing CLI so index is stale."""
        import cc.core.entry_store as es
        monkeypatch.setattr(es, "_git_root", lambda: tmp_path)
        # Store via CLI + rebuild
        cli_runner.invoke(cli_app, ["memory", "store", "--type", "context", "first"])
        cli_runner.invoke(cli_app, ["memory", "index", "--rebuild"])

        # Add a second entry directly to disk (bypassing CLI index update)
        memory_root = tmp_path / ".claude" / "memory"
        entries_d = memory_root / "entries"
        import uuid as _uuid
        uid = str(_uuid.uuid4())
        from cc.core.entry_format import build_frontmatter, render_entry
        from cc.core.entry_store import _atomic_write
        fm = build_frontmatter(entry_id=uid, entry_type="lesson", tags=[], scope="project")
        _atomic_write(entries_d / f"{uid}.md", render_entry(fm, "second"))

        result = cli_runner.invoke(cli_app, ["memory", "index", "--status"])
        assert result.exit_code == 3

    def test_index_no_flags_exits_nonzero(self, cli_runner, cli_app, monkeypatch, tmp_path):
        import cc.core.entry_store as es
        monkeypatch.setattr(es, "_git_root", lambda: tmp_path)
        result = cli_runner.invoke(cli_app, ["memory", "index"])
        assert result.exit_code == 1
