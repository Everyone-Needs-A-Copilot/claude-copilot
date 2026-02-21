"""Tests for Stream CRUD commands."""

import json

import pytest


class TestStreamCreate:
    """Tests for `tc stream create`."""

    def test_create_stream(self, cli):
        cli(["prd", "create", "--title", "PRD for Stream"])
        result = cli(["stream", "create", "--name", "alpha", "--prd", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["name"] == "alpha"
        assert data["prd_id"] == 1
        assert data["status"] == "active"

    def test_create_stream_with_worktree(self, cli):
        cli(["prd", "create", "--title", "PRD"])
        result = cli(
            ["stream", "create", "--name", "beta", "--prd", "1",
             "--worktree-path", "/tmp/beta-tree", "--json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["worktree_path"] == "/tmp/beta-tree"

    def test_create_stream_human_readable(self, cli):
        cli(["prd", "create", "--title", "PRD"])
        result = cli(["stream", "create", "--name", "gamma", "--prd", "1"])
        assert result.exit_code == 0
        assert "Created stream #1: gamma" in result.output

    def test_create_duplicate_name(self, cli):
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "dupe", "--prd", "1"])
        result = cli(["stream", "create", "--name", "dupe", "--prd", "1"])
        assert result.exit_code == 4  # EXIT_VALIDATION (UNIQUE constraint)

    def test_create_stream_nonexistent_prd(self, cli):
        result = cli(["stream", "create", "--name", "orphan", "--prd", "999"])
        assert result.exit_code == 2  # EXIT_NOT_FOUND


class TestStreamList:
    """Tests for `tc stream list`."""

    def test_list_empty(self, cli):
        result = cli(["stream", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == []

    def test_list_with_data(self, cli):
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "s1", "--prd", "1"])
        cli(["stream", "create", "--name", "s2", "--prd", "1"])
        result = cli(["stream", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 2
        # Ordered by id DESC
        assert data[0]["name"] == "s2"
        assert data[1]["name"] == "s1"

    def test_list_filter_by_status(self, cli):
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "active-stream", "--prd", "1"])
        result = cli(["stream", "list", "--status", "active", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["name"] == "active-stream"

    def test_list_filter_returns_empty(self, cli):
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "active-only", "--prd", "1"])
        result = cli(["stream", "list", "--status", "archived", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == []

    def test_list_human_readable_empty(self, cli):
        result = cli(["stream", "list"])
        assert result.exit_code == 0
        assert "no results" in result.output.lower()


class TestStreamGet:
    """Tests for `tc stream get`."""

    def test_get_by_id(self, cli):
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "by-id-stream", "--prd", "1"])
        result = cli(["stream", "get", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["name"] == "by-id-stream"

    def test_get_by_name(self, cli):
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "by-name-stream", "--prd", "1"])
        result = cli(["stream", "get", "by-name-stream", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["name"] == "by-name-stream"

    def test_get_nonexistent_id(self, cli):
        result = cli(["stream", "get", "999", "--json"])
        assert result.exit_code == 2  # EXIT_NOT_FOUND

    def test_get_nonexistent_name(self, cli):
        result = cli(["stream", "get", "no-such-stream", "--json"])
        assert result.exit_code == 2

    def test_get_nonexistent_no_json(self, cli):
        result = cli(["stream", "get", "ghost"])
        assert result.exit_code == 2

    def test_get_human_readable(self, cli):
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "hr-stream", "--prd", "1"])
        result = cli(["stream", "get", "1"])
        assert result.exit_code == 0
        assert "hr-stream" in result.output

    def test_get_prefers_id_over_name(self, cli):
        """When argument is numeric, try ID first."""
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "first", "--prd", "1"])
        result = cli(["stream", "get", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["id"] == 1
