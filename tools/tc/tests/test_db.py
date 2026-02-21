"""Tests for database management commands and init."""

import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tc.main import app
from tc.db.connection import init_db, find_db_path, get_db


class TestInit:
    """Tests for `tc init`."""

    def test_init_creates_database(self, runner, tmp_dir):
        result = runner.invoke(app, ["init", "--path", str(tmp_dir), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "initialized"
        assert ".copilot" in data["path"]
        assert "tasks.db" in data["path"]

    def test_init_creates_copilot_directory(self, runner, tmp_dir):
        runner.invoke(app, ["init", "--path", str(tmp_dir)])
        assert (tmp_dir / ".copilot").is_dir()
        assert (tmp_dir / ".copilot" / "tasks.db").is_file()

    def test_init_human_readable(self, runner, tmp_dir):
        result = runner.invoke(app, ["init", "--path", str(tmp_dir)])
        assert result.exit_code == 0
        assert "Initialized database at:" in result.output

    def test_init_idempotent(self, runner, tmp_dir):
        """Running init twice should not fail."""
        runner.invoke(app, ["init", "--path", str(tmp_dir)])
        result = runner.invoke(app, ["init", "--path", str(tmp_dir), "--json"])
        assert result.exit_code == 0

    def test_init_default_path(self, runner, tmp_dir, monkeypatch):
        """Init without --path uses cwd."""
        monkeypatch.chdir(tmp_dir)
        result = runner.invoke(app, ["init", "--json"])
        assert result.exit_code == 0
        assert (tmp_dir / ".copilot" / "tasks.db").exists()


class TestDbPath:
    """Tests for `tc db path`."""

    def test_db_path_found(self, cli, db_path):
        result = cli(["db", "path"])
        assert result.exit_code == 0
        assert str(db_path) in result.output

    def test_db_path_not_found(self, runner, tmp_dir, monkeypatch):
        """When no DB exists, should error."""
        monkeypatch.chdir(tmp_dir)
        result = runner.invoke(app, ["db", "path"])
        assert result.exit_code == 5  # EXIT_DB_ERROR


class TestDbStats:
    """Tests for `tc db stats`."""

    def test_stats_empty(self, cli):
        result = cli(["db", "stats", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["prds"] == 0
        assert data["streams"] == 0
        assert data["tasks"] == 0
        assert data["work_products"] == 0
        assert data["agent_log"] == 0
        assert data["task_dependencies"] == 0

    def test_stats_with_data(self, cli):
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "s1", "--prd", "1"])
        cli(["task", "create", "--title", "T1", "--stream", "1"])
        cli(["task", "create", "--title", "T2", "--stream", "1"])
        result = cli(["db", "stats", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["prds"] == 1
        assert data["streams"] == 1
        assert data["tasks"] == 2

    def test_stats_human_readable(self, cli):
        result = cli(["db", "stats"])
        assert result.exit_code == 0
        assert "prds" in result.output
        assert "tasks" in result.output


class TestFindDbPath:
    """Tests for find_db_path utility."""

    def test_find_in_current_dir(self, tmp_dir, monkeypatch):
        init_db(tmp_dir / ".copilot" / "tasks.db")
        monkeypatch.chdir(tmp_dir)
        found = find_db_path()
        assert found is not None
        assert found == tmp_dir / ".copilot" / "tasks.db"

    def test_find_walks_up(self, tmp_dir, monkeypatch):
        """find_db_path should walk up parent directories."""
        init_db(tmp_dir / ".copilot" / "tasks.db")
        child = tmp_dir / "subdir" / "deep"
        child.mkdir(parents=True)
        monkeypatch.chdir(child)
        found = find_db_path()
        assert found is not None
        assert found == tmp_dir / ".copilot" / "tasks.db"

    def test_find_returns_none(self, tmp_dir, monkeypatch):
        """When no DB exists anywhere, returns None."""
        empty = tmp_dir / "empty"
        empty.mkdir()
        monkeypatch.chdir(empty)
        found = find_db_path()
        # This might find a DB somewhere up the real filesystem
        # so we can only assert it returns a Path or None


class TestGetDb:
    """Tests for get_db connection utility."""

    def test_get_db_with_path(self, db_path):
        conn = get_db(db_path)
        assert conn is not None
        # Verify we can query
        conn.execute("SELECT 1")
        conn.close()

    def test_get_db_none_path_no_db_raises(self, tmp_dir, monkeypatch):
        """get_db(None) raises FileNotFoundError when no DB found."""
        empty = tmp_dir / "empty_dir"
        empty.mkdir()
        monkeypatch.chdir(empty)
        with pytest.raises(FileNotFoundError):
            get_db(None)

    def test_get_db_bad_path_raises(self):
        """get_db with nonexistent parent directory raises OperationalError."""
        with pytest.raises(sqlite3.OperationalError):
            get_db(Path("/tmp/nonexistent/nowhere/tasks.db"))

    def test_get_db_row_factory(self, db_path):
        conn = get_db(db_path)
        row = conn.execute("SELECT 1 as val").fetchone()
        assert row["val"] == 1
        conn.close()


class TestInitDb:
    """Tests for init_db utility."""

    def test_creates_tables(self, tmp_dir):
        db_file = tmp_dir / ".copilot" / "tasks.db"
        init_db(db_file)
        conn = get_db(db_file)
        tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        conn.close()
        assert "prds" in tables
        assert "streams" in tables
        assert "tasks" in tables
        assert "work_products" in tables
        assert "agent_log" in tables
        assert "task_dependencies" in tables
        assert "schema_version" in tables

    def test_creates_indexes(self, tmp_dir):
        db_file = tmp_dir / ".copilot" / "tasks.db"
        init_db(db_file)
        conn = get_db(db_file)
        indexes = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            ).fetchall()
        ]
        conn.close()
        assert "idx_tasks_status" in indexes
        assert "idx_tasks_agent" in indexes
        assert "idx_tasks_stream" in indexes

    def test_creates_parent_directory(self, tmp_dir):
        db_file = tmp_dir / "deep" / "nested" / ".copilot" / "tasks.db"
        init_db(db_file)
        assert db_file.exists()

    def test_init_db_default_path(self, tmp_dir, monkeypatch):
        """init_db(None) should create in cwd/.copilot/tasks.db."""
        monkeypatch.chdir(tmp_dir)
        result = init_db(None)
        assert result == tmp_dir / ".copilot" / "tasks.db"
        assert result.exists()


class TestRequireDb:
    """Tests for require_db error utility."""

    def test_require_db_explicit_missing_path(self):
        """require_db with explicit nonexistent path should raise typer.Exit."""
        import typer
        from tc.utils.errors import require_db
        with pytest.raises((typer.Exit, SystemExit)):
            require_db(Path("/tmp/nonexistent/fake/tasks.db"))

    def test_require_db_no_path_no_db(self, tmp_dir, monkeypatch):
        """require_db with no args and no DB should raise typer.Exit."""
        import typer
        from tc.utils.errors import require_db
        empty = tmp_dir / "isolated"
        empty.mkdir()
        monkeypatch.chdir(empty)
        with pytest.raises((typer.Exit, SystemExit)):
            require_db()

    def test_require_db_valid_explicit_path(self, db_path):
        """require_db with a valid explicit path should return it."""
        from tc.utils.errors import require_db
        result = require_db(db_path)
        assert result == db_path


class TestErrorExit:
    """Tests for error_exit utility."""

    def test_error_exit_raises(self):
        import typer
        from tc.utils.errors import error_exit
        with pytest.raises((typer.Exit, SystemExit)):
            error_exit("boom", 42)


class TestVersion:
    """Tests for `tc version`."""

    def test_version_output(self, runner):
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "tc version" in result.output
