"""Shared test fixtures for Task Copilot CLI tests."""

import sqlite3
import tempfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tc.db.connection import init_db, get_db
from tc.main import app


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for test isolation."""
    return tmp_path


@pytest.fixture
def db_path(tmp_dir: Path) -> Path:
    """Create and return a fresh initialized database path."""
    path = tmp_dir / ".copilot" / "tasks.db"
    init_db(path)
    return path


@pytest.fixture
def db_conn(db_path: Path) -> sqlite3.Connection:
    """Return an open connection to the test database."""
    conn = get_db(db_path)
    yield conn
    conn.close()


@pytest.fixture
def runner() -> CliRunner:
    """Typer test runner."""
    return CliRunner()


@pytest.fixture
def cli(runner: CliRunner, db_path: Path, monkeypatch):
    """Return a callable that invokes CLI commands with the test database.

    Usage:
        result = cli(["prd", "create", "--title", "Test PRD"])
    """
    # Point find_db_path to our test database by changing cwd
    monkeypatch.chdir(db_path.parent.parent)

    def invoke(*args, **kwargs):
        return runner.invoke(app, *args, **kwargs)

    return invoke
