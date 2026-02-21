"""Tests for progress summary command."""

import json

import pytest


class TestProgress:
    """Tests for `tc progress`."""

    def test_progress_empty_database(self, cli):
        result = cli(["progress", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["by_stream"] == []
        assert data["totals"] == {}

    def test_progress_with_tasks(self, cli):
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "stream-a", "--prd", "1"])
        cli(["task", "create", "--title", "T1", "--stream", "1"])
        cli(["task", "create", "--title", "T2", "--stream", "1"])
        cli(["task", "update", "2", "--status", "completed"])

        result = cli(["progress", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)

        assert len(data["by_stream"]) == 1
        stream_data = data["by_stream"][0]
        assert stream_data["stream_id"] == 1
        assert stream_data["stream_name"] == "stream-a"
        assert stream_data["counts"]["pending"] == 1
        assert stream_data["counts"]["completed"] == 1

        assert data["totals"]["pending"] == 1
        assert data["totals"]["completed"] == 1

    def test_progress_multiple_streams(self, cli):
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "s1", "--prd", "1"])
        cli(["stream", "create", "--name", "s2", "--prd", "1"])
        cli(["task", "create", "--title", "T1", "--stream", "1"])
        cli(["task", "create", "--title", "T2", "--stream", "2"])
        cli(["task", "create", "--title", "T3", "--stream", "2"])

        result = cli(["progress", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["by_stream"]) == 2
        assert data["totals"]["pending"] == 3

    def test_progress_filter_by_stream(self, cli):
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "s1", "--prd", "1"])
        cli(["stream", "create", "--name", "s2", "--prd", "1"])
        cli(["task", "create", "--title", "T1", "--stream", "1"])
        cli(["task", "create", "--title", "T2", "--stream", "2"])

        result = cli(["progress", "--stream", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["by_stream"]) == 1
        assert data["by_stream"][0]["stream_id"] == 1
        assert data["totals"]["pending"] == 1

    def test_progress_human_readable(self, cli):
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "s1", "--prd", "1"])
        cli(["task", "create", "--title", "T1", "--stream", "1"])

        result = cli(["progress"])
        assert result.exit_code == 0
        assert "Totals:" in result.output
        assert "pending" in result.output.lower()

    def test_progress_human_readable_empty(self, cli):
        result = cli(["progress"])
        assert result.exit_code == 0
        assert "Totals:" in result.output

    def test_progress_all_statuses(self, cli):
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "s1", "--prd", "1"])
        cli(["task", "create", "--title", "T1", "--stream", "1"])
        cli(["task", "create", "--title", "T2", "--stream", "1"])
        cli(["task", "create", "--title", "T3", "--stream", "1"])
        cli(["task", "create", "--title", "T4", "--stream", "1"])
        cli(["task", "create", "--title", "T5", "--stream", "1"])
        cli(["task", "update", "2", "--status", "in_progress"])
        cli(["task", "update", "3", "--status", "completed"])
        cli(["task", "update", "4", "--status", "blocked"])
        cli(["task", "update", "5", "--status", "cancelled"])

        result = cli(["progress", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        totals = data["totals"]
        assert totals["pending"] == 1
        assert totals["in_progress"] == 1
        assert totals["completed"] == 1
        assert totals["blocked"] == 1
        assert totals["cancelled"] == 1
