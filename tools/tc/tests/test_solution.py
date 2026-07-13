"""Tests for the Outcome Ledger (`tc solution ...`, W-1 Phase-4 outcome
program): create/lock-brief/mark-working/mark-loveable/log-usage/close/get/
list, plus the lazy schema-bootstrap path for pre-existing tasks.db stores
that predate the Outcome Ledger."""

import json

import pytest


def _create(cli, title="Test Solution", **kwargs):
    args = ["solution", "create", "--title", title, "--json"]
    for flag, value in kwargs.items():
        args.extend([f"--{flag.replace('_', '-')}", str(value)])
    result = cli(args)
    assert result.exit_code == 0, f"Solution creation failed: {result.output}"
    return json.loads(result.output)


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestSolutionCreate:
    def test_create_minimal(self, cli):
        data = _create(cli, title="Minimal Solution")
        assert data["title"] == "Minimal Solution"
        assert data["status"] == "in_progress"
        assert data["brief_locked_at"] is None
        assert data["sessions_count"] == 0
        assert data["tokens_total"] == 0

    def test_create_with_all_options(self, cli):
        result = cli(
            [
                "solution",
                "create",
                "--title",
                "Full Solution",
                "--brief",
                "Draft brief text",
                "--beneficiary",
                "Pablo",
                "--repo-path",
                "/some/repo",
                "--components",
                "framework,knowledge",
                "--json",
            ]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["brief"] == "Draft brief text"
        assert data["beneficiary"] == "Pablo"
        assert data["repo_path"] == "/some/repo"
        assert json.loads(data["components_used"]) == ["framework", "knowledge"]

    def test_create_empty_title_fails(self, cli):
        result = cli(["solution", "create", "--title", "  ", "--json"])
        assert result.exit_code == 4  # EXIT_VALIDATION

    def test_create_invalid_component_fails(self, cli):
        result = cli(
            ["solution", "create", "--title", "X", "--components", "bogus", "--json"]
        )
        assert result.exit_code == 4  # EXIT_VALIDATION

    def test_create_human_readable(self, cli):
        result = cli(["solution", "create", "--title", "HR Solution"])
        assert result.exit_code == 0
        assert "Created solution #1: HR Solution [in_progress]" in result.output


# ---------------------------------------------------------------------------
# lock-brief
# ---------------------------------------------------------------------------


class TestSolutionLockBrief:
    def test_lock_brief_from_create_text(self, cli):
        _create(cli, brief="Locked at create")
        result = cli(["solution", "lock-brief", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["brief"] == "Locked at create"
        assert data["brief_locked_at"] is not None
        assert data["scope_change_recorded"] is False

    def test_lock_brief_with_new_text(self, cli):
        _create(cli)
        result = cli(["solution", "lock-brief", "1", "--brief", "Final wording", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["brief"] == "Final wording"

    def test_lock_brief_without_any_text_fails(self, cli):
        _create(cli)
        result = cli(["solution", "lock-brief", "1", "--json"])
        assert result.exit_code == 4  # EXIT_VALIDATION

    def test_relock_records_scope_change_not_rewrite(self, cli):
        _create(cli, brief="Original locked brief")
        cli(["solution", "lock-brief", "1", "--json"])
        result = cli(
            ["solution", "lock-brief", "1", "--brief", "Scope creep attempt", "--json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["scope_change_recorded"] is True
        # Original locked brief must NOT be rewritten.
        assert data["brief"] == "Original locked brief"

        get_result = cli(["solution", "get", "1", "--json"])
        get_data = json.loads(get_result.output)
        assert len(get_data["scope_log"]) == 1
        assert get_data["scope_log"][0]["note"] == "Scope creep attempt"

    def test_lock_brief_not_found(self, cli):
        result = cli(["solution", "lock-brief", "999", "--json"])
        assert result.exit_code == 2  # EXIT_NOT_FOUND


# ---------------------------------------------------------------------------
# mark-working / mark-loveable
# ---------------------------------------------------------------------------


class TestSolutionMarkWorkingLoveable:
    def test_mark_working(self, cli):
        _create(cli)
        result = cli(["solution", "mark-working", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["t_working"] is not None

    def test_mark_working_twice_conflicts(self, cli):
        _create(cli)
        cli(["solution", "mark-working", "1", "--json"])
        result = cli(["solution", "mark-working", "1", "--json"])
        assert result.exit_code == 3  # EXIT_CONFLICT

    def test_mark_working_not_found(self, cli):
        result = cli(["solution", "mark-working", "999", "--json"])
        assert result.exit_code == 2  # EXIT_NOT_FOUND

    def test_mark_loveable_before_working_fails(self, cli):
        _create(cli)
        result = cli(["solution", "mark-loveable", "1", "--json"])
        assert result.exit_code == 4  # EXIT_VALIDATION

    def test_mark_loveable_after_working(self, cli):
        _create(cli)
        cli(["solution", "mark-working", "1", "--json"])
        result = cli(["solution", "mark-loveable", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["t_loveable"] is not None
        assert data["t_working"] is not None

    def test_mark_loveable_twice_conflicts(self, cli):
        _create(cli)
        cli(["solution", "mark-working", "1", "--json"])
        cli(["solution", "mark-loveable", "1", "--json"])
        result = cli(["solution", "mark-loveable", "1", "--json"])
        assert result.exit_code == 3  # EXIT_CONFLICT


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


class TestSolutionClose:
    def test_close_ship_without_locked_brief_fails(self, cli):
        _create(cli)
        result = cli(["solution", "close", "1", "--status", "shipped", "--json"])
        assert result.exit_code == 4  # EXIT_VALIDATION

    def test_close_ship_with_locked_brief(self, cli):
        _create(cli, brief="Brief")
        cli(["solution", "lock-brief", "1", "--json"])
        result = cli(["solution", "close", "1", "--status", "shipped", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "shipped"
        assert data["closed_at"] is not None

    def test_close_abandoned_does_not_require_locked_brief(self, cli):
        _create(cli)
        result = cli(["solution", "close", "1", "--status", "abandoned", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "abandoned"

    def test_close_invalid_status_value_fails(self, cli):
        _create(cli)
        result = cli(["solution", "close", "1", "--status", "bogus", "--json"])
        assert result.exit_code == 4  # EXIT_VALIDATION

    def test_close_shipped_again_conflicts(self, cli):
        _create(cli, brief="Brief")
        cli(["solution", "lock-brief", "1", "--json"])
        cli(["solution", "close", "1", "--status", "shipped", "--json"])
        result = cli(["solution", "close", "1", "--status", "shipped", "--json"])
        assert result.exit_code == 3  # EXIT_CONFLICT

    def test_retire_from_shipped(self, cli):
        _create(cli, brief="Brief")
        cli(["solution", "lock-brief", "1", "--json"])
        cli(["solution", "close", "1", "--status", "shipped", "--json"])
        result = cli(["solution", "close", "1", "--status", "retired", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output)["status"] == "retired"

    def test_retire_from_in_progress_conflicts(self, cli):
        _create(cli)
        result = cli(["solution", "close", "1", "--status", "retired", "--json"])
        assert result.exit_code == 3  # EXIT_CONFLICT

    def test_close_not_found(self, cli):
        result = cli(["solution", "close", "999", "--status", "abandoned", "--json"])
        assert result.exit_code == 2  # EXIT_NOT_FOUND


# ---------------------------------------------------------------------------
# log-usage
# ---------------------------------------------------------------------------


class TestSolutionLogUsage:
    def _ship(self, cli):
        _create(cli, brief="Brief")
        cli(["solution", "lock-brief", "1", "--json"])
        cli(["solution", "close", "1", "--status", "shipped", "--json"])

    def test_log_usage_before_shipped_conflicts(self, cli):
        _create(cli)
        result = cli(["solution", "log-usage", "1", "--json"])
        assert result.exit_code == 3  # EXIT_CONFLICT

    def test_log_usage_flips_shipped_to_in_use(self, cli):
        self._ship(cli)
        result = cli(["solution", "log-usage", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "in_use"

    def test_log_usage_accumulates_sessions_and_tokens(self, cli):
        self._ship(cli)
        cli(["solution", "log-usage", "1", "--sessions", "2", "--tokens", "500", "--json"])
        result = cli(
            ["solution", "log-usage", "1", "--sessions", "1", "--tokens", "250", "--json"]
        )
        data = json.loads(result.output)
        assert data["sessions_count"] == 3
        assert data["tokens_total"] == 750

    def test_log_usage_fix_and_feature_kinds(self, cli):
        self._ship(cli)
        cli(["solution", "log-usage", "1", "--kind", "fix", "--json"])
        cli(["solution", "log-usage", "1", "--kind", "fix", "--json"])
        result = cli(["solution", "log-usage", "1", "--kind", "feature", "--json"])
        data = json.loads(result.output)
        assert data["post_ship_fixes"] == 2
        assert data["post_ship_features"] == 1

    def test_log_usage_invalid_kind_fails(self, cli):
        self._ship(cli)
        result = cli(["solution", "log-usage", "1", "--kind", "bogus", "--json"])
        assert result.exit_code == 4  # EXIT_VALIDATION

    def test_log_usage_not_found(self, cli):
        result = cli(["solution", "log-usage", "999", "--json"])
        assert result.exit_code == 2  # EXIT_NOT_FOUND


# ---------------------------------------------------------------------------
# get / list
# ---------------------------------------------------------------------------


class TestSolutionGetList:
    def test_get_includes_logs(self, cli):
        _create(cli, brief="Brief")
        cli(["solution", "lock-brief", "1", "--json"])
        cli(["solution", "close", "1", "--status", "shipped", "--json"])
        cli(["solution", "log-usage", "1", "--json"])
        result = cli(["solution", "get", "1", "--json"])
        data = json.loads(result.output)
        assert data["status"] == "in_use"
        assert len(data["usage_log"]) == 1
        assert data["scope_log"] == []

    def test_get_not_found(self, cli):
        result = cli(["solution", "get", "999", "--json"])
        assert result.exit_code == 2  # EXIT_NOT_FOUND

    def test_list_empty(self, cli):
        result = cli(["solution", "list", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == []

    def test_list_filter_by_status(self, cli):
        _create(cli, title="S1")
        _create(cli, title="S2")
        cli(["solution", "close", "2", "--status", "abandoned", "--json"])
        result = cli(["solution", "list", "--status", "abandoned", "--json"])
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["title"] == "S2"

    def test_list_invalid_status_fails(self, cli):
        result = cli(["solution", "list", "--status", "bogus", "--json"])
        assert result.exit_code == 4  # EXIT_VALIDATION


# ---------------------------------------------------------------------------
# Lazy schema bootstrap: a pre-existing store created BEFORE the Outcome
# Ledger existed (no solutions/solution_scope_log/solution_usage_log tables)
# must gain them transparently the first time a `tc solution` command runs
# against it -- no `tc init` re-run, no manual migration.
# ---------------------------------------------------------------------------


class TestLazySchemaBootstrap:
    def test_pre_existing_store_gains_solutions_tables(self, tmp_path, runner, monkeypatch):
        import sqlite3

        from tc.db.schema import SCHEMA_SQL
        from tc.db.fts5_core import create_content_triggers, create_fts
        from tc.db.schema import WP_BASE_ROWID, WP_BASE_TABLE, WP_FTS_COLUMNS, WP_FTS_TABLE
        from tc.main import app

        # Build a store using ONLY the pre-Outcome-Ledger schema (simulates a
        # sibling repo's tasks.db that predates this change).
        db_path = tmp_path / ".copilot" / "tasks.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA_SQL)
        create_fts(conn, WP_FTS_TABLE, WP_FTS_COLUMNS, content_table=WP_BASE_TABLE, content_rowid=WP_BASE_ROWID)
        create_content_triggers(conn, WP_BASE_TABLE, WP_FTS_TABLE, WP_FTS_COLUMNS, rowid=WP_BASE_ROWID)
        conn.commit()
        conn.close()

        # Confirm the legacy store genuinely has no solutions table yet.
        conn = sqlite3.connect(str(db_path))
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert "solutions" not in tables

        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["solution", "create", "--title", "First Real Solution", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["title"] == "First Real Solution"

        # Existing tables/data from the legacy store are untouched.
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        version_row = conn.execute("SELECT version FROM schema_version").fetchone()
        assert version_row["version"] == 1
        conn.close()
