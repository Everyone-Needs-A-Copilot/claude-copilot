"""Tests for maintenance-session tagging (`tc upkeep ...`, O-9 upkeep tax,
Phase 4 outcome program): tag-task/tag-prd/list/summary, plus the lazy
schema-bootstrap path for pre-existing tasks.db stores that predate upkeep
tagging."""

import json

import pytest


def _task(cli, title="Test Task", prd=None):
    args = ["task", "create", "--title", title, "--json"]
    if prd is not None:
        args.extend(["--prd", str(prd)])
    result = cli(args)
    assert result.exit_code == 0, f"Task creation failed: {result.output}"
    return json.loads(result.output)


def _prd(cli, title="Test PRD"):
    result = cli(["prd", "create", "--title", title, "--json"])
    assert result.exit_code == 0, f"PRD creation failed: {result.output}"
    return json.loads(result.output)


# ---------------------------------------------------------------------------
# tag-task
# ---------------------------------------------------------------------------


class TestUpkeepTagTask:
    def test_tag_task_minimal(self, cli):
        _task(cli)
        result = cli(["upkeep", "tag-task", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["task_id"] == 1
        assert data["kind"] == "other"
        assert data["method"] == "explicit"

    def test_tag_task_with_kind_and_note(self, cli):
        _task(cli)
        result = cli(
            [
                "upkeep",
                "tag-task",
                "1",
                "--kind",
                "registry",
                "--note",
                "ECOSYSTEM.md rows",
                "--json",
            ]
        )
        data = json.loads(result.output)
        assert data["kind"] == "registry"
        assert data["note"] == "ECOSYSTEM.md rows"

    def test_tag_task_invalid_kind_fails(self, cli):
        _task(cli)
        result = cli(["upkeep", "tag-task", "1", "--kind", "bogus", "--json"])
        assert result.exit_code == 4  # EXIT_VALIDATION

    def test_tag_task_not_found(self, cli):
        result = cli(["upkeep", "tag-task", "999", "--json"])
        assert result.exit_code == 2  # EXIT_NOT_FOUND

    def test_retag_updates_kind_not_duplicates_row(self, cli):
        _task(cli)
        cli(["upkeep", "tag-task", "1", "--kind", "framework", "--json"])
        result = cli(["upkeep", "tag-task", "1", "--kind", "cli", "--json"])
        data = json.loads(result.output)
        assert data["kind"] == "cli"

        listing = json.loads(cli(["upkeep", "list", "--json"]).output)
        assert len(listing) == 1

    def test_tag_task_human_readable(self, cli):
        _task(cli)
        result = cli(["upkeep", "tag-task", "1", "--kind", "cli"])
        assert result.exit_code == 0
        assert "Task #1 tagged upkeep [cli] (method: explicit)" in result.output


# ---------------------------------------------------------------------------
# tag-prd (the retrospective-computability path)
# ---------------------------------------------------------------------------


class TestUpkeepTagPrd:
    def test_tag_prd_bulk_tags_existing_tasks(self, cli):
        _prd(cli, title="Maintenance PRD")
        _task(cli, title="R-1", prd=1)
        _task(cli, title="R-2", prd=1)
        _task(cli, title="Unrelated", prd=None)

        result = cli(["upkeep", "tag-prd", "1", "--kind", "registry", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["prd_id"] == 1
        assert data["tasks_under_prd"] == 2
        assert data["tasks_tagged"] == 2

        listing = json.loads(cli(["upkeep", "list", "--json"]).output)
        tagged_ids = {row["task_id"] for row in listing}
        assert tagged_ids == {1, 2}
        assert all(row["method"] == "prd-heuristic" for row in listing)

    def test_tag_prd_retroactively_covers_tasks_created_before_the_flag(self, cli):
        """The whole point of the PRD-level flag: tasks that already
        existed, filed long before anyone tagged anything, become
        countable in one call -- no prospective per-session tagging
        required."""
        _prd(cli, title="Old Remediation PRD")
        for i in range(5):
            _task(cli, title=f"Pre-existing task {i}", prd=1)

        result = cli(["upkeep", "tag-prd", "1", "--json"])
        data = json.loads(result.output)
        assert data["tasks_tagged"] == 5

    def test_tag_prd_is_idempotent_on_rerun(self, cli):
        _prd(cli)
        _task(cli, prd=1)
        cli(["upkeep", "tag-prd", "1", "--kind", "cli", "--json"])
        _task(cli, title="Task added later", prd=1)
        result = cli(["upkeep", "tag-prd", "1", "--kind", "cli", "--json"])
        data = json.loads(result.output)
        assert data["tasks_under_prd"] == 2
        assert data["tasks_tagged"] == 2

    def test_tag_prd_never_overrides_an_explicit_task_tag(self, cli):
        _prd(cli)
        _task(cli, prd=1)
        cli(["upkeep", "tag-task", "1", "--kind", "framework", "--json"])
        cli(["upkeep", "tag-prd", "1", "--kind", "registry", "--json"])

        listing = json.loads(cli(["upkeep", "list", "--json"]).output)
        assert len(listing) == 1
        assert listing[0]["kind"] == "framework"
        assert listing[0]["method"] == "explicit"

    def test_tag_prd_invalid_kind_fails(self, cli):
        _prd(cli)
        result = cli(["upkeep", "tag-prd", "1", "--kind", "bogus", "--json"])
        assert result.exit_code == 4  # EXIT_VALIDATION

    def test_tag_prd_not_found(self, cli):
        result = cli(["upkeep", "tag-prd", "999", "--json"])
        assert result.exit_code == 2  # EXIT_NOT_FOUND

    def test_tag_prd_with_no_tasks_yet(self, cli):
        _prd(cli)
        result = cli(["upkeep", "tag-prd", "1", "--json"])
        data = json.loads(result.output)
        assert data["tasks_under_prd"] == 0
        assert data["tasks_tagged"] == 0

    def test_tag_prd_human_readable(self, cli):
        _prd(cli)
        _task(cli, prd=1)
        result = cli(["upkeep", "tag-prd", "1", "--kind", "registry"])
        assert "PRD #1 flagged upkeep [registry]: 1/1 tasks tagged" in result.output


# ---------------------------------------------------------------------------
# list / summary
# ---------------------------------------------------------------------------


class TestUpkeepListSummary:
    def test_list_empty(self, cli):
        result = cli(["upkeep", "list", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == []

    def test_list_filter_by_kind(self, cli):
        _task(cli, title="A")
        _task(cli, title="B")
        cli(["upkeep", "tag-task", "1", "--kind", "framework", "--json"])
        cli(["upkeep", "tag-task", "2", "--kind", "cli", "--json"])
        result = cli(["upkeep", "list", "--kind", "cli", "--json"])
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["task_id"] == 2

    def test_list_invalid_kind_fails(self, cli):
        result = cli(["upkeep", "list", "--kind", "bogus", "--json"])
        assert result.exit_code == 4  # EXIT_VALIDATION

    def test_summary_empty_store(self, cli):
        result = cli(["upkeep", "summary", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_tasks"] == 0
        assert data["upkeep_tasks"] == 0
        assert data["task_count_share"] is None

    def test_summary_computes_task_count_share(self, cli):
        _task(cli, title="A")
        _task(cli, title="B")
        _task(cli, title="C")
        _task(cli, title="D")
        cli(["upkeep", "tag-task", "1", "--kind", "registry", "--json"])
        result = cli(["upkeep", "summary", "--json"])
        data = json.loads(result.output)
        assert data["total_tasks"] == 4
        assert data["upkeep_tasks"] == 1
        assert data["task_count_share"] == pytest.approx(0.25)
        assert data["by_kind"] == {"registry": 1}
        assert data["by_method"] == {"explicit": 1}

    def test_summary_counts_prds_flagged_and_sessions_tagged(self, cli, monkeypatch):
        _prd(cli)
        _task(cli, prd=1)
        cli(["upkeep", "tag-prd", "1", "--json"])

        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-summary")
        _task(cli, title="Session-tagged")
        cli(["upkeep", "tag-task", "2", "--kind", "cli", "--json"])

        result = cli(["upkeep", "summary", "--json"])
        data = json.loads(result.output)
        assert data["prds_flagged"] == 1
        assert data["sessions_tagged"] == 1

    def test_human_readable_summary(self, cli):
        result = cli(["upkeep", "summary"])
        assert result.exit_code == 0
        assert "total_tasks: 0" in result.output


# ---------------------------------------------------------------------------
# W-2-style session capture (mirrors TestSolutionSessionsW2 in test_solution.py)
# ---------------------------------------------------------------------------


class TestUpkeepSessionCapture:
    def test_no_session_id_env_no_capture(self, cli, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        _task(cli)
        cli(["upkeep", "tag-task", "1", "--json"])
        result = cli(["upkeep", "summary", "--json"])
        assert json.loads(result.output)["sessions_tagged"] == 0

    def test_session_id_env_captures_session(self, cli, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-abc-123")
        _task(cli)
        cli(["upkeep", "tag-task", "1", "--kind", "framework", "--json"])
        result = cli(["upkeep", "summary", "--json"])
        assert json.loads(result.output)["sessions_tagged"] == 1

    def test_different_sessions_recorded_separately(self, cli, monkeypatch):
        _task(cli, title="A")
        _task(cli, title="B")

        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "session-A")
        cli(["upkeep", "tag-task", "1", "--json"])

        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "session-B")
        cli(["upkeep", "tag-task", "2", "--json"])

        result = cli(["upkeep", "summary", "--json"])
        assert json.loads(result.output)["sessions_tagged"] == 2

    def test_tag_prd_sweep_does_not_capture_a_session(self, cli, monkeypatch):
        """The bulk PRD sweep is a retrospective, table-level operation --
        it never fabricates a session touch for tasks it didn't
        individually tag via tag-task."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-prd-sweep")
        _prd(cli)
        _task(cli, prd=1)
        cli(["upkeep", "tag-prd", "1", "--json"])
        result = cli(["upkeep", "summary", "--json"])
        assert json.loads(result.output)["sessions_tagged"] == 0


# ---------------------------------------------------------------------------
# Lazy schema bootstrap: a pre-existing store created BEFORE upkeep tagging
# existed must gain the new tables transparently the first time a `tc
# upkeep` command runs against it.
# ---------------------------------------------------------------------------


class TestLazySchemaBootstrap:
    def test_pre_existing_store_gains_upkeep_tables(self, tmp_path, runner, monkeypatch):
        import sqlite3

        from tc.db.schema import SCHEMA_SQL
        from tc.db.fts5_core import create_content_triggers, create_fts
        from tc.db.schema import WP_BASE_ROWID, WP_BASE_TABLE, WP_FTS_COLUMNS, WP_FTS_TABLE
        from tc.main import app

        db_path = tmp_path / ".copilot" / "tasks.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA_SQL)
        create_fts(conn, WP_FTS_TABLE, WP_FTS_COLUMNS, content_table=WP_BASE_TABLE, content_rowid=WP_BASE_ROWID)
        create_content_triggers(conn, WP_BASE_TABLE, WP_FTS_TABLE, WP_FTS_COLUMNS, rowid=WP_BASE_ROWID)
        conn.execute("INSERT INTO tasks (title) VALUES ('Legacy task')")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(str(db_path))
        tables = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        conn.close()
        assert "upkeep_tags" not in tables

        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["upkeep", "tag-task", "1", "--kind", "registry", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["task_id"] == 1
        assert data["kind"] == "registry"

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        version_row = conn.execute("SELECT version FROM schema_version").fetchone()
        assert version_row["version"] == 1

        tables_after = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert {"upkeep_tags", "upkeep_sessions", "prd_upkeep_flags"} <= tables_after
        conn.close()
