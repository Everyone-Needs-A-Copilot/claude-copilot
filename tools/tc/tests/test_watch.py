"""Tests for watch dashboard data fetching and rendering."""

import sqlite3
from pathlib import Path

import pytest

from tc.db.connection import init_db, get_db
from tc.commands.watch import (
    _fetch_dashboard_data,
    _truncate,
    _build_layout,
    _render_header,
    _render_stream_panel,
    _render_agents_panel,
    _render_status_panel,
    _render_log_panel,
    DashboardData,
    StatusCounts,
    StreamProgress,
    ActiveAgent,
    LogEntry,
)


@pytest.fixture
def watch_db(tmp_path):
    """Create and populate a test database for watch tests."""
    db_file = tmp_path / ".copilot" / "tasks.db"
    init_db(db_file)
    conn = get_db(db_file)
    return conn


def _populate_watch_db(conn):
    """Populate database with varied data for dashboard testing."""
    # PRD
    conn.execute("INSERT INTO prds (title) VALUES ('Test PRD')")
    # Streams
    conn.execute("INSERT INTO streams (name, prd_id) VALUES ('alpha', 1)")
    conn.execute("INSERT INTO streams (name, prd_id) VALUES ('beta', 1)")
    # Tasks in stream 1 (alpha)
    conn.execute(
        "INSERT INTO tasks (title, stream_id, status, agent) VALUES ('T1', 1, 'completed', 'me')"
    )
    conn.execute(
        "INSERT INTO tasks (title, stream_id, status, agent, claimed_by, claimed_at) "
        "VALUES ('T2', 1, 'in_progress', 'me', 'me', datetime('now'))"
    )
    conn.execute(
        "INSERT INTO tasks (title, stream_id, status) VALUES ('T3', 1, 'pending')"
    )
    # Tasks in stream 2 (beta)
    conn.execute(
        "INSERT INTO tasks (title, stream_id, status, agent, claimed_by, claimed_at) "
        "VALUES ('T4', 2, 'in_progress', 'qa', 'qa', datetime('now'))"
    )
    conn.execute(
        "INSERT INTO tasks (title, stream_id, status) VALUES ('T5', 2, 'blocked')"
    )
    # Agent log entries
    conn.execute(
        "INSERT INTO agent_log (agent, stream_id, task_id, action, details) "
        "VALUES ('me', 1, 1, 'completed', 'Finished T1')"
    )
    conn.execute(
        "INSERT INTO agent_log (agent, stream_id, task_id, action, details) "
        "VALUES ('me', 1, 2, 'claimed', 'Claimed by me')"
    )
    conn.execute(
        "INSERT INTO agent_log (agent, stream_id, task_id, action, details) "
        "VALUES ('qa', 2, 4, 'claimed', 'Claimed by qa')"
    )
    conn.commit()


class TestFetchDashboardData:
    """Tests for _fetch_dashboard_data."""

    def test_empty_database(self, watch_db):
        data = _fetch_dashboard_data(watch_db)
        assert data.totals.total == 0
        assert data.streams == []
        assert data.agents == []
        assert data.log_entries == []
        assert data.last_refresh != ""
        watch_db.close()

    def test_populated_database(self, watch_db):
        _populate_watch_db(watch_db)
        data = _fetch_dashboard_data(watch_db)

        # Totals
        assert data.totals.completed == 1
        assert data.totals.in_progress == 2
        assert data.totals.pending == 1
        assert data.totals.blocked == 1
        assert data.totals.total == 5

        # Streams
        assert len(data.streams) == 2
        stream_names = {s.name for s in data.streams}
        assert "alpha" in stream_names
        assert "beta" in stream_names

        # Active agents (claimed + in_progress)
        assert len(data.agents) == 2
        agent_names = {a.agent for a in data.agents}
        assert "me" in agent_names
        assert "qa" in agent_names

        # Log entries
        assert len(data.log_entries) == 3
        watch_db.close()

    def test_stream_filter(self, watch_db):
        _populate_watch_db(watch_db)
        data = _fetch_dashboard_data(watch_db, stream_filter=1)

        # Only stream 1 data
        assert data.totals.completed == 1
        assert data.totals.in_progress == 1
        assert data.totals.pending == 1
        assert data.totals.blocked == 0

        # Only stream 1
        assert len(data.streams) == 1
        assert data.streams[0].name == "alpha"

        # Only agents in stream 1
        assert len(data.agents) == 1
        assert data.agents[0].agent == "me"

        # Only log entries for stream 1
        assert all(e.task_id in (1, 2) for e in data.log_entries if e.task_id)
        watch_db.close()

    def test_stream_progress_aggregation(self, watch_db):
        _populate_watch_db(watch_db)
        data = _fetch_dashboard_data(watch_db)

        alpha = next(s for s in data.streams if s.name == "alpha")
        assert alpha.completed == 1
        assert alpha.in_progress == 1
        assert alpha.total == 3

        beta = next(s for s in data.streams if s.name == "beta")
        assert beta.in_progress == 1
        assert beta.blocked == 1
        assert beta.total == 2
        watch_db.close()

    def test_active_agents_only_in_progress(self, watch_db):
        """Only tasks with claimed_by AND status in_progress should show."""
        conn = watch_db
        conn.execute("INSERT INTO prds (title) VALUES ('PRD')")
        conn.execute("INSERT INTO streams (name, prd_id) VALUES ('s1', 1)")
        # Completed but claimed - should NOT appear
        conn.execute(
            "INSERT INTO tasks (title, stream_id, status, claimed_by, claimed_at) "
            "VALUES ('Done', 1, 'completed', 'me', datetime('now'))"
        )
        # In progress and claimed - should appear
        conn.execute(
            "INSERT INTO tasks (title, stream_id, status, claimed_by, claimed_at) "
            "VALUES ('Active', 1, 'in_progress', 'qa', datetime('now'))"
        )
        conn.commit()

        data = _fetch_dashboard_data(conn)
        assert len(data.agents) == 1
        assert data.agents[0].agent == "qa"
        conn.close()

    def test_log_entries_limit(self, watch_db):
        """Log entries should be limited to 10."""
        conn = watch_db
        conn.execute("INSERT INTO prds (title) VALUES ('PRD')")
        conn.execute("INSERT INTO streams (name, prd_id) VALUES ('s1', 1)")
        conn.execute("INSERT INTO tasks (title, stream_id, status) VALUES ('T1', 1, 'pending')")
        for i in range(15):
            conn.execute(
                "INSERT INTO agent_log (agent, stream_id, task_id, action, details) "
                f"VALUES ('me', 1, 1, 'action', 'detail {i}')"
            )
        conn.commit()

        data = _fetch_dashboard_data(conn)
        assert len(data.log_entries) <= 10
        conn.close()


class TestTruncate:
    """Tests for _truncate helper."""

    def test_short_text(self):
        assert _truncate("hello", 10) == "hello"

    def test_exact_length(self):
        assert _truncate("hello", 5) == "hello"

    def test_long_text(self):
        result = _truncate("hello world", 6)
        assert len(result) == 6
        assert result.endswith("\u2026")  # ellipsis

    def test_single_char_max(self):
        result = _truncate("hello", 1)
        assert result == "\u2026"


class TestStatusCounts:
    """Tests for StatusCounts dataclass."""

    def test_total(self):
        sc = StatusCounts(pending=1, in_progress=2, completed=3, blocked=4, cancelled=5)
        assert sc.total == 15

    def test_total_default_zeros(self):
        sc = StatusCounts()
        assert sc.total == 0


class TestDashboardData:
    """Tests for DashboardData dataclass."""

    def test_defaults(self):
        data = DashboardData()
        assert data.totals.total == 0
        assert data.streams == []
        assert data.agents == []
        assert data.log_entries == []


class TestRendering:
    """Tests for rendering functions (smoke tests - verify no exceptions)."""

    def _make_sample_data(self):
        return DashboardData(
            totals=StatusCounts(pending=3, in_progress=2, completed=5, blocked=1, cancelled=0),
            streams=[
                StreamProgress(stream_id=1, name="alpha", total=6, completed=3, in_progress=2, blocked=1),
                StreamProgress(stream_id=2, name="beta", total=5, completed=2, in_progress=1, blocked=0),
            ],
            agents=[
                ActiveAgent(agent="me", task_id=1, task_title="Build feature", stream_name="alpha"),
            ],
            log_entries=[
                LogEntry(timestamp="12:00:00", agent="me", action="claimed", task_id=1, details="Claimed task"),
                LogEntry(timestamp="12:01:00", agent="me", action="completed", task_id=2, details=None),
            ],
            last_refresh="12:05:00",
        )

    def test_render_header(self):
        data = self._make_sample_data()
        panel = _render_header(data, 5)
        assert panel is not None

    def test_render_header_zero_total(self):
        data = DashboardData(last_refresh="12:00:00")
        panel = _render_header(data, 5)
        assert panel is not None

    def test_render_stream_panel(self):
        data = self._make_sample_data()
        panel = _render_stream_panel(data)
        assert panel is not None

    def test_render_stream_panel_empty(self):
        data = DashboardData()
        panel = _render_stream_panel(data)
        assert panel is not None

    def test_render_agents_panel(self):
        data = self._make_sample_data()
        panel = _render_agents_panel(data)
        assert panel is not None

    def test_render_agents_panel_empty(self):
        data = DashboardData()
        panel = _render_agents_panel(data)
        assert panel is not None

    def test_render_status_panel(self):
        data = self._make_sample_data()
        panel = _render_status_panel(data)
        assert panel is not None

    def test_render_log_panel(self):
        data = self._make_sample_data()
        panel = _render_log_panel(data)
        assert panel is not None

    def test_render_log_panel_empty(self):
        data = DashboardData()
        panel = _render_log_panel(data)
        assert panel is not None

    def test_build_layout_full(self):
        data = self._make_sample_data()
        layout = _build_layout(data, 5, compact=False)
        assert layout is not None

    def test_build_layout_compact(self):
        data = self._make_sample_data()
        layout = _build_layout(data, 5, compact=True)
        assert layout is not None

    def test_render_stream_panel_with_blocked(self):
        data = DashboardData(
            streams=[
                StreamProgress(stream_id=1, name="blocked-stream", total=10, completed=2, in_progress=1, blocked=5),
            ]
        )
        panel = _render_stream_panel(data)
        assert panel is not None

    def test_log_entry_with_no_task_id(self):
        data = DashboardData(
            log_entries=[
                LogEntry(timestamp="12:00:00", agent="me", action="unknown", task_id=None, details="No task"),
            ]
        )
        panel = _render_log_panel(data)
        assert panel is not None

    def test_log_entry_styled_actions(self):
        """Verify all known action styles render without error."""
        entries = [
            LogEntry(timestamp="12:00:00", agent="me", action="completed", task_id=1, details="d"),
            LogEntry(timestamp="12:00:01", agent="me", action="started", task_id=2, details="d"),
            LogEntry(timestamp="12:00:02", agent="me", action="claimed", task_id=3, details="d"),
            LogEntry(timestamp="12:00:03", agent="me", action="handoff", task_id=4, details="d"),
            LogEntry(timestamp="12:00:04", agent="me", action="blocked", task_id=5, details="d"),
            LogEntry(timestamp="12:00:05", agent="me", action="other", task_id=6, details="d"),
        ]
        data = DashboardData(log_entries=entries)
        panel = _render_log_panel(data)
        assert panel is not None
