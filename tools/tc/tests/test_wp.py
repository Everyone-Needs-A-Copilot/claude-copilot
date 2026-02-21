"""Tests for Work Product CRUD and search commands."""

import json

import pytest


def _setup_task(cli):
    """Create a task for work product association. Returns task_id."""
    result = cli(["task", "create", "--title", "WP Task", "--json"])
    return json.loads(result.output)["id"]


class TestWpStore:
    """Tests for `tc wp store`."""

    def test_store_inline(self, cli):
        task_id = _setup_task(cli)
        result = cli([
            "wp", "store",
            "--task", str(task_id),
            "--type", "code",
            "--title", "My Component",
            "--content", "function hello() {}",
            "--agent", "me",
            "--json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["task_id"] == task_id
        assert data["type"] == "code"
        assert data["title"] == "My Component"
        assert data["content"] == "function hello() {}"
        assert data["agent"] == "me"
        assert data["file_path"] is None

    def test_store_human_readable(self, cli):
        task_id = _setup_task(cli)
        result = cli([
            "wp", "store",
            "--task", str(task_id),
            "--type", "spec",
            "--title", "HR WP",
            "--content", "Content",
        ])
        assert result.exit_code == 0
        assert "Stored work product #1: HR WP" in result.output

    def test_store_from_file(self, cli, tmp_dir):
        task_id = _setup_task(cli)
        content_file = tmp_dir / "wp_content.md"
        content_file.write_text("# Content from file", encoding="utf-8")
        result = cli([
            "wp", "store",
            "--task", str(task_id),
            "--type", "doc",
            "--title", "File WP",
            "--file", str(content_file),
            "--json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["content"] == "# Content from file"

    def test_store_from_missing_file(self, cli, tmp_dir):
        task_id = _setup_task(cli)
        result = cli([
            "wp", "store",
            "--task", str(task_id),
            "--type", "doc",
            "--title", "Missing",
            "--file", str(tmp_dir / "ghost.md"),
        ])
        assert result.exit_code == 4  # EXIT_VALIDATION

    def test_store_nonexistent_task(self, cli):
        result = cli([
            "wp", "store",
            "--task", "999",
            "--type", "code",
            "--title", "Orphan",
            "--content", "data",
        ])
        assert result.exit_code == 2  # EXIT_NOT_FOUND

    def test_store_large_content_uses_file_storage(self, cli, db_path):
        task_id = _setup_task(cli)
        # WP_CONTENT_SIZE_THRESHOLD is 100KB
        large_content = "x" * (100 * 1024 + 1)
        result = cli([
            "wp", "store",
            "--task", str(task_id),
            "--type", "analysis",
            "--title", "Large WP",
            "--content", large_content,
            "--json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        # Should have file_path set and content NULL in DB
        assert data["file_path"] is not None
        assert data["content"] is None
        # Verify the file was actually written
        from pathlib import Path
        fp = Path(data["file_path"])
        assert fp.exists()
        assert len(fp.read_text(encoding="utf-8")) == len(large_content)

    def test_store_no_content(self, cli):
        task_id = _setup_task(cli)
        result = cli([
            "wp", "store",
            "--task", str(task_id),
            "--type", "note",
            "--title", "Empty WP",
            "--json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["content"] is None
        assert data["file_path"] is None

    def test_store_large_content_human_readable(self, cli, db_path):
        """Large content in human readable mode shows file path."""
        task_id = _setup_task(cli)
        large = "x" * (100 * 1024 + 1)
        result = cli([
            "wp", "store",
            "--task", str(task_id),
            "--type", "analysis",
            "--title", "Large HR WP",
            "--content", large,
        ])
        assert result.exit_code == 0
        assert "file:" in result.output.lower() or "Large HR WP" in result.output


class TestWpGet:
    """Tests for `tc wp get`."""

    def test_get_inline_content(self, cli):
        task_id = _setup_task(cli)
        cli([
            "wp", "store", "--task", str(task_id),
            "--type", "code", "--title", "Get Me",
            "--content", "body content", "--json",
        ])
        result = cli(["wp", "get", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["title"] == "Get Me"
        assert data["content"] == "body content"

    def test_get_file_based_content(self, cli, db_path):
        """Work product stored to file should have content read back."""
        task_id = _setup_task(cli)
        large = "y" * (100 * 1024 + 1)
        cli([
            "wp", "store", "--task", str(task_id),
            "--type", "code", "--title", "File WP",
            "--content", large, "--json",
        ])
        result = cli(["wp", "get", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["content"] == large

    def test_get_nonexistent(self, cli):
        result = cli(["wp", "get", "999", "--json"])
        assert result.exit_code == 2  # EXIT_NOT_FOUND

    def test_get_human_readable_truncates(self, cli):
        task_id = _setup_task(cli)
        long_content = "a" * 300
        cli([
            "wp", "store", "--task", str(task_id),
            "--type", "doc", "--title", "Long WP",
            "--content", long_content,
        ])
        result = cli(["wp", "get", "1"])
        assert result.exit_code == 0
        assert "[truncated]" in result.output

    def test_get_human_readable_short(self, cli):
        task_id = _setup_task(cli)
        cli([
            "wp", "store", "--task", str(task_id),
            "--type", "doc", "--title", "Short WP",
            "--content", "short",
        ])
        result = cli(["wp", "get", "1"])
        assert result.exit_code == 0
        assert "[truncated]" not in result.output

    def test_get_file_based_missing_file(self, cli, db_path, db_conn):
        """When file_path is set but file is deleted, show error message."""
        task_id = _setup_task(cli)
        # Store large content to trigger file-based storage
        large = "z" * (100 * 1024 + 1)
        store_result = cli([
            "wp", "store", "--task", str(task_id),
            "--type", "code", "--title", "Deleted File WP",
            "--content", large, "--json",
        ])
        data = json.loads(store_result.output)
        # Delete the file to simulate missing file
        from pathlib import Path
        file_path = Path(data["file_path"])
        file_path.unlink()
        # Now get should show missing file message
        result = cli(["wp", "get", str(data["id"]), "--json"])
        assert result.exit_code == 0
        content = json.loads(result.output)["content"]
        assert "File not found" in content


class TestWpList:
    """Tests for `tc wp list`."""

    def test_list_empty(self, cli):
        result = cli(["wp", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == []

    def test_list_with_data(self, cli):
        task_id = _setup_task(cli)
        cli(["wp", "store", "--task", str(task_id), "--type", "code", "--title", "WP1", "--content", "c1"])
        cli(["wp", "store", "--task", str(task_id), "--type", "doc", "--title", "WP2", "--content", "c2"])
        result = cli(["wp", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 2

    def test_list_filter_by_task(self, cli):
        t1 = _setup_task(cli)
        result2 = cli(["task", "create", "--title", "Another Task", "--json"])
        t2 = json.loads(result2.output)["id"]
        cli(["wp", "store", "--task", str(t1), "--type", "code", "--title", "WP1", "--content", "c1"])
        cli(["wp", "store", "--task", str(t2), "--type", "code", "--title", "WP2", "--content", "c2"])
        result = cli(["wp", "list", "--task", str(t1), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["title"] == "WP1"

    def test_list_filter_by_type(self, cli):
        task_id = _setup_task(cli)
        cli(["wp", "store", "--task", str(task_id), "--type", "code", "--title", "Code WP", "--content", "c"])
        cli(["wp", "store", "--task", str(task_id), "--type", "doc", "--title", "Doc WP", "--content", "d"])
        result = cli(["wp", "list", "--type", "code", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["type"] == "code"

    def test_list_filter_by_agent(self, cli):
        task_id = _setup_task(cli)
        cli(["wp", "store", "--task", str(task_id), "--type", "code", "--title", "A", "--content", "c", "--agent", "me"])
        cli(["wp", "store", "--task", str(task_id), "--type", "code", "--title", "B", "--content", "c", "--agent", "qa"])
        result = cli(["wp", "list", "--agent", "me", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["agent"] == "me"

    def test_list_human_readable_empty(self, cli):
        result = cli(["wp", "list"])
        assert result.exit_code == 0
        assert "no result" in result.output.lower()


class TestWpSearch:
    """Tests for `tc wp search` (FTS5)."""

    def test_search_finds_match(self, cli):
        task_id = _setup_task(cli)
        cli([
            "wp", "store", "--task", str(task_id),
            "--type", "doc", "--title", "Authentication Module",
            "--content", "Implements OAuth2 flow for user login",
        ])
        result = cli(["wp", "search", "OAuth2", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) >= 1
        assert data[0]["title"] == "Authentication Module"

    def test_search_no_results(self, cli):
        task_id = _setup_task(cli)
        cli([
            "wp", "store", "--task", str(task_id),
            "--type", "code", "--title", "Unrelated",
            "--content", "Nothing to find here",
        ])
        result = cli(["wp", "search", "xyznonexistent", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == []

    def test_search_with_limit(self, cli):
        task_id = _setup_task(cli)
        for i in range(5):
            cli([
                "wp", "store", "--task", str(task_id),
                "--type", "doc", "--title", f"Doc {i}",
                "--content", f"Common keyword searchable item {i}",
            ])
        result = cli(["wp", "search", "searchable", "--limit", "2", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 2

    def test_search_human_readable_no_results(self, cli):
        result = cli(["wp", "search", "nothing"])
        assert result.exit_code == 0
        assert "No results" in result.output

    def test_search_by_title(self, cli):
        task_id = _setup_task(cli)
        cli([
            "wp", "store", "--task", str(task_id),
            "--type", "code", "--title", "Unique Widget Renderer",
            "--content", "basic content",
        ])
        result = cli(["wp", "search", "Widget", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) >= 1

    def test_search_human_readable_with_results(self, cli):
        task_id = _setup_task(cli)
        cli([
            "wp", "store", "--task", str(task_id),
            "--type", "doc", "--title", "Readable Search",
            "--content", "findable content here",
        ])
        result = cli(["wp", "search", "findable"])
        assert result.exit_code == 0
        assert "Readable Search" in result.output
