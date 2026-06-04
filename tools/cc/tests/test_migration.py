"""Tests for cc memory migrate command."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers to build a fake legacy memory.db
# ---------------------------------------------------------------------------

_LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  content TEXT NOT NULL,
  type TEXT NOT NULL,
  tags TEXT DEFAULT '[]',
  metadata TEXT DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  session_id TEXT
);
"""


def _make_legacy_db(db_path: Path, rows: list[dict]) -> None:
    """Create a minimal legacy memory.db with the given rows."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_LEGACY_SCHEMA)
    for row in rows:
        conn.execute(
            "INSERT INTO memories (id, project_id, content, type, tags, metadata, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, '{}', ?, ?)",
            (
                row.get("id", str(uuid.uuid4())),
                row.get("project_id", "proj-1"),
                row["content"],
                row.get("type", "context"),
                json.dumps(row.get("tags", [])),
                row.get("created_at", "2024-01-01T00:00:00Z"),
                row.get("updated_at", "2024-01-01T00:00:00Z"),
            ),
        )
    conn.commit()
    conn.close()


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Redirect Path.home() and LEGACY_MEMORY_DIR to tmp_path."""
    import cc.commands.memory as mem_mod

    legacy_dir = tmp_path / ".claude" / "memory"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mem_mod, "_LEGACY_MEMORY_DIR", legacy_dir)
    return legacy_dir


@pytest.fixture
def patched_project_root(tmp_path, monkeypatch):
    """Make project scope resolve inside tmp_path."""
    import cc.core.entry_store as es

    monkeypatch.setattr(es, "_git_root", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def cli_runner():
    from typer.testing import CliRunner

    return CliRunner()


@pytest.fixture
def cli_app():
    from cc.main import app

    return app


# ---------------------------------------------------------------------------
# Unit tests for internal helpers
# ---------------------------------------------------------------------------


class TestFindLegacyDbs:
    def test_finds_db_in_workspace_subdir(self, fake_home):
        import cc.commands.memory as mem_mod

        ws_dir = fake_home / "workspace-abc"
        db_path = ws_dir / "memory.db"
        _make_legacy_db(db_path, [])

        found = mem_mod._find_legacy_dbs()
        assert db_path in found

    def test_returns_empty_when_no_dbs(self, fake_home):
        import cc.commands.memory as mem_mod

        found = mem_mod._find_legacy_dbs()
        assert found == []

    def test_finds_multiple_dbs(self, fake_home):
        import cc.commands.memory as mem_mod

        for ws in ("ws-1", "ws-2"):
            db = fake_home / ws / "memory.db"
            _make_legacy_db(db, [])

        found = mem_mod._find_legacy_dbs()
        assert len(found) == 2


class TestCountEntries:
    def test_counts_rows(self, fake_home):
        import cc.commands.memory as mem_mod

        db_path = fake_home / "ws" / "memory.db"
        _make_legacy_db(
            db_path,
            [
                {"content": "a", "type": "context"},
                {"content": "b", "type": "decision"},
            ],
        )
        assert mem_mod._count_entries(db_path) == 2

    def test_empty_db_returns_zero(self, fake_home):
        import cc.commands.memory as mem_mod

        db_path = fake_home / "ws" / "memory.db"
        _make_legacy_db(db_path, [])
        assert mem_mod._count_entries(db_path) == 0


class TestReadLegacyEntries:
    def test_reads_all_columns(self, fake_home):
        import cc.commands.memory as mem_mod

        entry_id = str(uuid.uuid4())
        db_path = fake_home / "ws" / "memory.db"
        _make_legacy_db(
            db_path,
            [
                {
                    "id": entry_id,
                    "content": "test content",
                    "type": "lesson",
                    "tags": ["auth", "security"],
                    "created_at": "2024-03-01T10:00:00Z",
                    "updated_at": "2024-03-02T11:00:00Z",
                }
            ],
        )

        rows = mem_mod._read_legacy_entries(db_path)
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == entry_id
        assert row["content"] == "test content"
        assert row["type"] == "lesson"
        assert row["created_at"] == "2024-03-01T10:00:00Z"


class TestMigrateEntries:
    def test_creates_md_file_from_row(self, fake_home, patched_project_root):
        import cc.commands.memory as mem_mod
        from cc.core.entry_format import parse_frontmatter

        entry_id = str(uuid.uuid4())
        rows = [
            {
                "id": entry_id,
                "content": "a useful decision",
                "type": "decision",
                "tags": json.dumps(["auth"]),
                "created_at": "2024-01-15T09:00:00Z",
                "updated_at": "2024-01-15T09:00:00Z",
            }
        ]

        stats = mem_mod._migrate_entries(rows, "project", dry_run=False)
        assert stats["migrated"] == 1
        assert stats["skipped"] == 0
        assert stats["errors"] == 0

        from cc.core.entry_store import resolve_memory_root

        memory_root = resolve_memory_root("project")
        entry_file = memory_root / "entries" / f"{entry_id}.md"
        assert entry_file.exists()

        fm, body = parse_frontmatter(entry_file.read_text())
        assert fm["type"] == "decision"
        assert body.strip() == "a useful decision"
        assert fm["created"] == "2024-01-15T09:00:00Z"

    def test_dry_run_does_not_create_files(self, fake_home, patched_project_root):
        import cc.commands.memory as mem_mod
        from cc.core.entry_store import resolve_memory_root

        rows = [
            {
                "id": str(uuid.uuid4()),
                "content": "dry run content",
                "type": "context",
                "tags": "[]",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }
        ]

        stats = mem_mod._migrate_entries(rows, "project", dry_run=True)
        assert stats["migrated"] == 1

        memory_root = resolve_memory_root("project")
        entries_path = memory_root / "entries"
        assert not entries_path.exists() or len(list(entries_path.glob("*.md"))) == 0

    def test_skips_duplicate_content(self, fake_home, patched_project_root):
        import cc.commands.memory as mem_mod

        rows = [
            {
                "id": str(uuid.uuid4()),
                "content": "same content",
                "type": "context",
                "tags": "[]",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            },
            {
                "id": str(uuid.uuid4()),
                "content": "same content",
                "type": "context",
                "tags": "[]",
                "created_at": "2024-01-02T00:00:00Z",
                "updated_at": "2024-01-02T00:00:00Z",
            },
        ]

        stats = mem_mod._migrate_entries(rows, "project", dry_run=False)
        assert stats["migrated"] == 1
        assert stats["skipped"] == 1

    def test_skips_existing_content_already_on_disk(
        self, fake_home, patched_project_root
    ):
        """If an entry with same content already exists in entries/, it should be skipped."""
        import cc.commands.memory as mem_mod
        from cc.core.entry_store import store_entry

        # Pre-store an entry with the same content
        store_entry(entry_type="context", content="existing content", scope="project")

        rows = [
            {
                "id": str(uuid.uuid4()),
                "content": "existing content",
                "type": "context",
                "tags": "[]",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }
        ]

        stats = mem_mod._migrate_entries(rows, "project", dry_run=False)
        assert stats["migrated"] == 0
        assert stats["skipped"] == 1

    def test_skips_empty_content(self, fake_home, patched_project_root):
        import cc.commands.memory as mem_mod

        rows = [
            {
                "id": str(uuid.uuid4()),
                "content": "",
                "type": "context",
                "tags": "[]",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }
        ]

        stats = mem_mod._migrate_entries(rows, "project", dry_run=False)
        assert stats["migrated"] == 0
        assert stats["skipped"] == 1

    def test_type_mapping_discussion_becomes_context(
        self, fake_home, patched_project_root
    ):
        import cc.commands.memory as mem_mod
        from cc.core.entry_format import parse_frontmatter
        from cc.core.entry_store import resolve_memory_root

        entry_id = str(uuid.uuid4())
        rows = [
            {
                "id": entry_id,
                "content": "a discussion",
                "type": "discussion",
                "tags": "[]",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }
        ]

        mem_mod._migrate_entries(rows, "project", dry_run=False)

        memory_root = resolve_memory_root("project")
        entry_file = memory_root / "entries" / f"{entry_id}.md"
        fm, _ = parse_frontmatter(entry_file.read_text())
        assert fm["type"] == "context"

    def test_type_mapping_agent_improvement_becomes_lesson(
        self, fake_home, patched_project_root
    ):
        import cc.commands.memory as mem_mod
        from cc.core.entry_format import parse_frontmatter
        from cc.core.entry_store import resolve_memory_root

        entry_id = str(uuid.uuid4())
        rows = [
            {
                "id": entry_id,
                "content": "an improvement note",
                "type": "agent_improvement",
                "tags": "[]",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }
        ]

        mem_mod._migrate_entries(rows, "project", dry_run=False)

        memory_root = resolve_memory_root("project")
        entry_file = memory_root / "entries" / f"{entry_id}.md"
        fm, _ = parse_frontmatter(entry_file.read_text())
        assert fm["type"] == "lesson"

    def test_type_mapping_file_becomes_reference(self, fake_home, patched_project_root):
        import cc.commands.memory as mem_mod
        from cc.core.entry_format import parse_frontmatter
        from cc.core.entry_store import resolve_memory_root

        entry_id = str(uuid.uuid4())
        rows = [
            {
                "id": entry_id,
                "content": "some file info",
                "type": "file",
                "tags": "[]",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }
        ]

        mem_mod._migrate_entries(rows, "project", dry_run=False)

        memory_root = resolve_memory_root("project")
        entry_file = memory_root / "entries" / f"{entry_id}.md"
        fm, _ = parse_frontmatter(entry_file.read_text())
        assert fm["type"] == "reference"

    def test_tags_parsed_from_json_array(self, fake_home, patched_project_root):
        import cc.commands.memory as mem_mod
        from cc.core.entry_format import parse_frontmatter
        from cc.core.entry_store import resolve_memory_root

        entry_id = str(uuid.uuid4())
        rows = [
            {
                "id": entry_id,
                "content": "tagged entry",
                "type": "decision",
                "tags": json.dumps(["auth", "api"]),
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }
        ]

        mem_mod._migrate_entries(rows, "project", dry_run=False)

        memory_root = resolve_memory_root("project")
        entry_file = memory_root / "entries" / f"{entry_id}.md"
        fm, _ = parse_frontmatter(entry_file.read_text())
        assert "auth" in fm["tags"]
        assert "api" in fm["tags"]

    def test_preserves_timestamps(self, fake_home, patched_project_root):
        import cc.commands.memory as mem_mod
        from cc.core.entry_format import parse_frontmatter
        from cc.core.entry_store import resolve_memory_root

        entry_id = str(uuid.uuid4())
        rows = [
            {
                "id": entry_id,
                "content": "timestamp test",
                "type": "context",
                "tags": "[]",
                "created_at": "2023-06-15T08:30:00Z",
                "updated_at": "2023-07-01T12:00:00Z",
            }
        ]

        mem_mod._migrate_entries(rows, "project", dry_run=False)

        memory_root = resolve_memory_root("project")
        entry_file = memory_root / "entries" / f"{entry_id}.md"
        fm, _ = parse_frontmatter(entry_file.read_text())
        assert fm["created"] == "2023-06-15T08:30:00Z"
        assert fm["updated"] == "2023-07-01T12:00:00Z"


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestMigrateCLI:
    def _setup(self, monkeypatch, tmp_path, fake_home):
        """Patch git root for project scope."""
        import cc.core.entry_store as es

        monkeypatch.setattr(es, "_git_root", lambda: tmp_path)

    def test_no_flags_exits_nonzero(
        self, cli_runner, cli_app, monkeypatch, tmp_path, fake_home
    ):
        self._setup(monkeypatch, tmp_path, fake_home)
        result = cli_runner.invoke(cli_app, ["memory", "migrate"])
        assert result.exit_code == 1
        assert "Error" in result.output or "Error" in (result.stderr or "")

    def test_status_no_dbs(self, cli_runner, cli_app, monkeypatch, tmp_path, fake_home):
        self._setup(monkeypatch, tmp_path, fake_home)
        result = cli_runner.invoke(cli_app, ["memory", "migrate", "--status"])
        assert result.exit_code == 0
        assert "No legacy databases" in result.output

    def test_status_shows_db_counts(
        self, cli_runner, cli_app, monkeypatch, tmp_path, fake_home
    ):
        self._setup(monkeypatch, tmp_path, fake_home)
        db_path = fake_home / "ws-abc" / "memory.db"
        _make_legacy_db(
            db_path,
            [
                {"content": "entry one", "type": "context"},
                {"content": "entry two", "type": "lesson"},
            ],
        )
        result = cli_runner.invoke(cli_app, ["memory", "migrate", "--status"])
        assert result.exit_code == 0
        assert "entries: 2" in result.output

    def test_dry_run_prints_without_creating_files(
        self, cli_runner, cli_app, monkeypatch, tmp_path, fake_home
    ):
        self._setup(monkeypatch, tmp_path, fake_home)
        db_path = fake_home / "ws-1" / "memory.db"
        _make_legacy_db(db_path, [{"content": "my dry run entry", "type": "context"}])

        result = cli_runner.invoke(
            cli_app, ["memory", "migrate", "--from-global", "--dry-run", "--all"]
        )
        assert result.exit_code == 0
        assert "would migrate" in result.output
        assert "my dry run entry" in result.output

        # No files should have been created
        entries_path = tmp_path / ".claude" / "memory" / "entries"
        assert not entries_path.exists() or len(list(entries_path.glob("*.md"))) == 0

    def test_from_global_migrates_single_db(
        self, cli_runner, cli_app, monkeypatch, tmp_path, fake_home
    ):
        self._setup(monkeypatch, tmp_path, fake_home)
        entry_id = str(uuid.uuid4())
        db_path = fake_home / "ws-2" / "memory.db"
        _make_legacy_db(
            db_path,
            [{"id": entry_id, "content": "migrated entry content", "type": "lesson"}],
        )

        result = cli_runner.invoke(
            cli_app, ["memory", "migrate", "--from-global", "--all"]
        )
        assert result.exit_code == 0
        assert "migrated: 1" in result.output

        entries_path = tmp_path / ".claude" / "memory" / "entries"
        assert (entries_path / f"{entry_id}.md").exists()

    def test_duplicate_content_skipped(
        self, cli_runner, cli_app, monkeypatch, tmp_path, fake_home
    ):
        self._setup(monkeypatch, tmp_path, fake_home)
        db_path = fake_home / "ws-3" / "memory.db"
        _make_legacy_db(
            db_path,
            [
                {"content": "duplicate content", "type": "context"},
                {"content": "duplicate content", "type": "context"},
            ],
        )

        result = cli_runner.invoke(
            cli_app, ["memory", "migrate", "--from-global", "--all"]
        )
        assert result.exit_code == 0
        assert "migrated: 1" in result.output
        assert "skipped" in result.output

    def test_no_dbs_exits_zero(
        self, cli_runner, cli_app, monkeypatch, tmp_path, fake_home
    ):
        self._setup(monkeypatch, tmp_path, fake_home)
        result = cli_runner.invoke(cli_app, ["memory", "migrate", "--from-global"])
        assert result.exit_code == 0
        assert "No legacy databases" in result.output

    def test_global_scope_flag(
        self, cli_runner, cli_app, monkeypatch, tmp_path, fake_home
    ):
        """Entries with --scope global go to patched global root's entries/."""
        import cc.commands.memory as mem_mod
        from cc.core import entry_store as es

        # Patch global scope to a controlled tmp location
        global_root = tmp_path / "global_home" / ".claude" / "memory"
        monkeypatch.setattr(es, "_git_root", lambda: tmp_path)

        original_resolve = es.resolve_memory_root

        def patched_resolve(scope: str) -> Path:
            if scope == "global":
                return global_root
            return original_resolve(scope)

        # Patch in both modules that use resolve_memory_root
        monkeypatch.setattr(es, "resolve_memory_root", patched_resolve)
        monkeypatch.setattr(mem_mod, "resolve_memory_root", patched_resolve)

        entry_id = str(uuid.uuid4())
        db_path = fake_home / "ws-g" / "memory.db"
        _make_legacy_db(
            db_path,
            [{"id": entry_id, "content": "global scope entry", "type": "decision"}],
        )

        result = cli_runner.invoke(
            cli_app,
            ["memory", "migrate", "--from-global", "--all", "--scope", "global"],
        )
        assert result.exit_code == 0

        entries_path = global_root / "entries"
        assert (entries_path / f"{entry_id}.md").exists()
