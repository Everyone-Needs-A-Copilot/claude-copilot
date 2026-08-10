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
            [
                "stream",
                "create",
                "--name",
                "beta",
                "--prd",
                "1",
                "--worktree-path",
                "/tmp/beta-tree",
                "--json",
            ]
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


class TestStreamConflicts:
    """Tests for `tc stream conflicts` -- the real /orchestrate file-overlap
    check. Regression coverage for Gap 2: orchestrate.md claimed this check
    existed while the streams table had no files metadata to support it.
    These tests prove the check is real: it reads tasks.metadata.files
    (already written by /orchestrate generate) and fails when two streams
    claim the same file.
    """

    def _make_stream(self, cli, name, files_by_task):
        """Create a stream with tasks each carrying metadata.files."""
        cli(["prd", "create", "--title", f"PRD for {name}"])
        prd_id = json.loads(cli(["prd", "list", "--json"]).output)[0]["id"]
        stream_result = cli(
            ["stream", "create", "--name", name, "--prd", str(prd_id), "--json"]
        )
        stream_id = json.loads(stream_result.output)["id"]
        for title, files in files_by_task:
            metadata = json.dumps({"files": files})
            cli(
                [
                    "task",
                    "create",
                    "--title",
                    title,
                    "--stream",
                    str(stream_id),
                    "--metadata",
                    metadata,
                    "--json",
                ]
            )
        return stream_id

    def test_no_streams_no_conflicts(self, cli):
        """Positive control: nothing to compare -> exit 0, empty list."""
        result = cli(["stream", "conflicts", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == []

    def test_disjoint_file_sets_no_conflict(self, cli):
        """Positive control: two streams, no shared files -> exit 0."""
        self._make_stream(cli, "stream-a", [("A task", ["src/a.ts"])])
        self._make_stream(cli, "stream-b", [("B task", ["src/b.ts"])])
        result = cli(["stream", "conflicts", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == []

    def test_shared_file_is_a_conflict(self, cli):
        """Two streams' tasks both claim src/auth.ts -> exit non-zero, both named."""
        self._make_stream(cli, "stream-a", [("A task", ["src/auth.ts"])])
        self._make_stream(cli, "stream-b", [("B task", ["src/auth.ts", "src/b.ts"])])
        result = cli(["stream", "conflicts", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["file"] == "src/auth.ts"
        names = {s["name"] for s in data[0]["streams"]}
        assert names == {"stream-a", "stream-b"}

    def test_human_readable_names_file_and_streams(self, cli):
        self._make_stream(cli, "stream-a", [("A task", ["src/shared.ts"])])
        self._make_stream(cli, "stream-b", [("B task", ["src/shared.ts"])])
        result = cli(["stream", "conflicts"])
        assert result.exit_code == 1
        assert "src/shared.ts" in result.output
        assert "stream-a" in result.output
        assert "stream-b" in result.output

    def test_tasks_without_files_metadata_are_ignored(self, cli):
        """A task with no metadata.files must not blow up the scan."""
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "bare-stream", "--prd", "1"])
        cli(
            [
                "task",
                "create",
                "--title",
                "No metadata task",
                "--stream",
                "1",
                "--json",
            ]
        )
        result = cli(["stream", "conflicts", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == []

    def test_archived_stream_excluded_by_default(self, cli):
        """A completed/archived stream's file claims don't collide with a new one."""
        stream_a = self._make_stream(
            cli, "old-stream", [("Old task", ["src/shared.ts"])]
        )
        # `tc stream` has no `update`/archive command yet -- go straight at
        # the DB to set the status this test needs.
        import sqlite3

        from tc.db.connection import find_db_path

        conn = sqlite3.connect(str(find_db_path()))
        conn.execute("UPDATE streams SET status = 'archived' WHERE id = ?", (stream_a,))
        conn.commit()
        conn.close()

        self._make_stream(cli, "new-stream", [("New task", ["src/shared.ts"])])
        result = cli(["stream", "conflicts", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == []
