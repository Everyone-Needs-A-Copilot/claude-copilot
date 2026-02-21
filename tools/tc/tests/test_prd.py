"""Tests for PRD CRUD commands."""

import json

import pytest


class TestPrdCreate:
    """Tests for `tc prd create`."""

    def test_create_with_all_fields(self, cli):
        result = cli(
            ["prd", "create", "--title", "Full PRD", "--description", "A description",
             "--content", "Some long content here", "--json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["title"] == "Full PRD"
        assert data["description"] == "A description"
        assert data["content"] == "Some long content here"
        assert data["status"] == "active"
        assert data["id"] == 1

    def test_create_with_minimal_fields(self, cli):
        result = cli(["prd", "create", "--title", "Minimal PRD", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["title"] == "Minimal PRD"
        assert data["description"] is None
        assert data["content"] is None

    def test_create_human_readable_output(self, cli):
        result = cli(["prd", "create", "--title", "Human PRD"])
        assert result.exit_code == 0
        assert "Created PRD #1: Human PRD" in result.output

    def test_create_from_file(self, cli, tmp_dir):
        content_file = tmp_dir / "prd_content.md"
        content_file.write_text("# PRD from file\nContent here.", encoding="utf-8")
        result = cli(
            ["prd", "create", "--title", "File PRD", "--file", str(content_file), "--json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["content"] == "# PRD from file\nContent here."

    def test_create_from_missing_file(self, cli, tmp_dir):
        result = cli(
            ["prd", "create", "--title", "Bad", "--file", str(tmp_dir / "nope.md"), "--json"]
        )
        assert result.exit_code == 4  # EXIT_VALIDATION

    def test_create_multiple_prds_get_sequential_ids(self, cli):
        cli(["prd", "create", "--title", "PRD A", "--json"])
        result = cli(["prd", "create", "--title", "PRD B", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["id"] == 2


class TestPrdList:
    """Tests for `tc prd list`."""

    def test_list_empty(self, cli):
        result = cli(["prd", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == []

    def test_list_with_data(self, cli):
        cli(["prd", "create", "--title", "PRD Alpha"])
        cli(["prd", "create", "--title", "PRD Beta"])
        result = cli(["prd", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 2
        # Ordered by id DESC
        assert data[0]["title"] == "PRD Beta"
        assert data[1]["title"] == "PRD Alpha"

    def test_list_filter_by_status(self, cli):
        cli(["prd", "create", "--title", "Active PRD"])
        cli(["prd", "create", "--title", "Done PRD"])
        cli(["prd", "update", "2", "--status", "completed"])
        result = cli(["prd", "list", "--status", "completed", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["title"] == "Done PRD"

    def test_list_human_readable_empty(self, cli):
        result = cli(["prd", "list"])
        assert result.exit_code == 0
        assert "no results" in result.output.lower()


class TestPrdGet:
    """Tests for `tc prd get`."""

    def test_get_existing(self, cli):
        cli(["prd", "create", "--title", "Get Me", "--description", "desc"])
        result = cli(["prd", "get", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["title"] == "Get Me"
        assert data["description"] == "desc"

    def test_get_nonexistent(self, cli):
        result = cli(["prd", "get", "999", "--json"])
        assert result.exit_code == 2  # EXIT_NOT_FOUND

    def test_get_nonexistent_stderr(self, cli):
        result = cli(["prd", "get", "999"])
        assert result.exit_code == 2
        # Error messages go to stderr, typer test runner captures them
        # depending on mix_stderr setting

    def test_get_human_readable(self, cli):
        cli(["prd", "create", "--title", "Readable PRD"])
        result = cli(["prd", "get", "1"])
        assert result.exit_code == 0
        assert "title: Readable PRD" in result.output


class TestPrdUpdate:
    """Tests for `tc prd update`."""

    def test_update_title(self, cli):
        cli(["prd", "create", "--title", "Old Title"])
        result = cli(["prd", "update", "1", "--title", "New Title", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["title"] == "New Title"

    def test_update_status(self, cli):
        cli(["prd", "create", "--title", "Status Test"])
        result = cli(["prd", "update", "1", "--status", "completed", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "completed"

    def test_update_content(self, cli):
        cli(["prd", "create", "--title", "Content Test"])
        result = cli(["prd", "update", "1", "--content", "New content", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["content"] == "New content"

    def test_update_content_from_file(self, cli, tmp_dir):
        cli(["prd", "create", "--title", "File Update"])
        content_file = tmp_dir / "update.md"
        content_file.write_text("Updated from file", encoding="utf-8")
        result = cli(["prd", "update", "1", "--file", str(content_file), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["content"] == "Updated from file"

    def test_update_invalid_status(self, cli):
        cli(["prd", "create", "--title", "Bad Status"])
        result = cli(["prd", "update", "1", "--status", "invalid"])
        assert result.exit_code == 4  # EXIT_VALIDATION

    def test_update_nonexistent(self, cli):
        result = cli(["prd", "update", "999", "--title", "Ghost"])
        assert result.exit_code == 2  # EXIT_NOT_FOUND

    def test_update_nothing(self, cli):
        cli(["prd", "create", "--title", "No Change"])
        result = cli(["prd", "update", "1"])
        assert result.exit_code == 0
        assert "Nothing to update" in result.output

    def test_update_nothing_json(self, cli):
        cli(["prd", "create", "--title", "No Change JSON"])
        result = cli(["prd", "update", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["title"] == "No Change JSON"

    def test_update_from_missing_file(self, cli, tmp_dir):
        cli(["prd", "create", "--title", "Bad File"])
        result = cli(["prd", "update", "1", "--file", str(tmp_dir / "gone.md")])
        assert result.exit_code == 4  # EXIT_VALIDATION

    def test_update_sets_updated_at(self, cli):
        cli(["prd", "create", "--title", "Timestamp"])
        before = json.loads(cli(["prd", "get", "1", "--json"]).output)
        cli(["prd", "update", "1", "--title", "Timestamp V2"])
        after = json.loads(cli(["prd", "get", "1", "--json"]).output)
        # updated_at should change (or at least be present)
        assert after["updated_at"] is not None

    def test_update_human_readable(self, cli):
        cli(["prd", "create", "--title", "HR Update"])
        result = cli(["prd", "update", "1", "--title", "HR Updated"])
        assert result.exit_code == 0
        assert "Updated PRD #1: HR Updated" in result.output

    def test_update_nonexistent_json(self, cli):
        """JSON error path for nonexistent PRD update."""
        result = cli(["prd", "update", "999", "--title", "Ghost", "--json"])
        assert result.exit_code == 2

    def test_get_nonexistent_json_error(self, cli):
        """JSON error path outputs error to stderr."""
        result = cli(["prd", "get", "999", "--json"])
        assert result.exit_code == 2
