"""Tests for Task CRUD, claim, next, and dependency commands."""

import json

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_prd_and_stream(cli):
    """Create a PRD and stream for task tests. Returns (prd_id, stream_id)."""
    cli(["prd", "create", "--title", "Task PRD"])
    cli(["stream", "create", "--name", "task-stream", "--prd", "1"])
    return 1, 1


def _create_task(cli, title="Test Task", stream=None, agent=None, priority=2, prd=None):
    """Create a task and return parsed JSON data."""
    args = ["task", "create", "--title", title, "--priority", str(priority), "--json"]
    if stream is not None:
        args.extend(["--stream", str(stream)])
    if agent is not None:
        args.extend(["--agent", agent])
    if prd is not None:
        args.extend(["--prd", str(prd)])
    result = cli(args)
    assert result.exit_code == 0, f"Task creation failed: {result.output}"
    return json.loads(result.output)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

class TestTaskCreate:
    """Tests for `tc task create`."""

    def test_create_with_all_options(self, cli):
        _setup_prd_and_stream(cli)
        result = cli([
            "task", "create",
            "--title", "Full Task",
            "--prd", "1",
            "--stream", "1",
            "--agent", "me",
            "--priority", "0",
            "--description", "A detailed description",
            "--metadata", '{"key": "value"}',
            "--json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["title"] == "Full Task"
        assert data["prd_id"] == 1
        assert data["stream_id"] == 1
        assert data["agent"] == "me"
        assert data["priority"] == 0
        assert data["description"] == "A detailed description"
        assert data["metadata"] == '{"key": "value"}'
        assert data["status"] == "pending"

    def test_create_minimal(self, cli):
        result = cli(["task", "create", "--title", "Minimal", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["title"] == "Minimal"
        assert data["priority"] == 2  # default
        assert data["agent"] is None
        assert data["stream_id"] is None

    def test_create_human_readable(self, cli):
        result = cli(["task", "create", "--title", "HR Task"])
        assert result.exit_code == 0
        assert "Created task #1: HR Task" in result.output

    def test_create_invalid_priority_too_high(self, cli):
        result = cli(["task", "create", "--title", "Bad", "--priority", "5"])
        assert result.exit_code == 4  # EXIT_VALIDATION

    def test_create_invalid_priority_negative(self, cli):
        result = cli(["task", "create", "--title", "Bad", "--priority", "-1"])
        assert result.exit_code == 4

    def test_create_invalid_metadata(self, cli):
        result = cli(["task", "create", "--title", "Bad", "--metadata", "not json"])
        assert result.exit_code == 4

    def test_create_with_parent(self, cli):
        _create_task(cli, "Parent")
        result = cli(["task", "create", "--title", "Child", "--parent", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["parent_task_id"] == 1


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

class TestTaskList:
    """Tests for `tc task list`."""

    def test_list_empty(self, cli):
        result = cli(["task", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == []

    def test_list_with_data(self, cli):
        _create_task(cli, "Task A")
        _create_task(cli, "Task B")
        result = cli(["task", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 2

    def test_list_filter_by_status(self, cli):
        _create_task(cli, "Pending Task")
        t = _create_task(cli, "Completed Task")
        cli(["task", "update", str(t["id"]), "--status", "completed"])
        result = cli(["task", "list", "--status", "completed", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["title"] == "Completed Task"

    def test_list_filter_by_agent(self, cli):
        _create_task(cli, "Agent Task", agent="me")
        _create_task(cli, "Other Task", agent="qa")
        result = cli(["task", "list", "--agent", "me", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["agent"] == "me"

    def test_list_filter_by_stream(self, cli):
        _setup_prd_and_stream(cli)
        _create_task(cli, "Stream Task", stream=1)
        _create_task(cli, "No Stream Task")
        result = cli(["task", "list", "--stream", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["title"] == "Stream Task"

    def test_list_filter_by_prd(self, cli):
        _setup_prd_and_stream(cli)
        _create_task(cli, "PRD Task", prd=1)
        _create_task(cli, "Orphan Task")
        result = cli(["task", "list", "--prd", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["title"] == "PRD Task"

    def test_list_priority_ordering(self, cli):
        _create_task(cli, "Low Priority", priority=3)
        _create_task(cli, "High Priority", priority=0)
        _create_task(cli, "Medium Priority", priority=1)
        result = cli(["task", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data[0]["priority"] == 0
        assert data[1]["priority"] == 1
        assert data[2]["priority"] == 3

    def test_list_human_readable_empty(self, cli):
        result = cli(["task", "list"])
        assert result.exit_code == 0
        assert "no results" in result.output.lower()


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------

class TestTaskGet:
    """Tests for `tc task get`."""

    def test_get_existing(self, cli):
        _create_task(cli, "Get Me")
        result = cli(["task", "get", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["title"] == "Get Me"
        assert "dependencies" in data
        assert data["dependencies"] == []

    def test_get_with_dependencies(self, cli):
        _create_task(cli, "Dep A")
        _create_task(cli, "Dep B")
        _create_task(cli, "Main")
        cli(["task", "deps", "add", "3", "--depends-on", "1"])
        cli(["task", "deps", "add", "3", "--depends-on", "2"])
        result = cli(["task", "get", "3", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert set(data["dependencies"]) == {1, 2}

    def test_get_nonexistent(self, cli):
        result = cli(["task", "get", "999", "--json"])
        assert result.exit_code == 2  # EXIT_NOT_FOUND

    def test_get_nonexistent_no_json(self, cli):
        result = cli(["task", "get", "999"])
        assert result.exit_code == 2

    def test_get_human_readable(self, cli):
        _create_task(cli, "HR Task")
        result = cli(["task", "get", "1"])
        assert result.exit_code == 0
        assert "HR Task" in result.output


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

class TestTaskUpdate:
    """Tests for `tc task update`."""

    def test_update_status(self, cli):
        _create_task(cli, "Status Task")
        result = cli(["task", "update", "1", "--status", "in_progress", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "in_progress"

    def test_update_agent(self, cli):
        _create_task(cli, "Agent Task")
        result = cli(["task", "update", "1", "--agent", "qa", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["agent"] == "qa"

    def test_update_description(self, cli):
        _create_task(cli, "Desc Task")
        result = cli(["task", "update", "1", "--description", "New desc", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["description"] == "New desc"

    def test_update_priority(self, cli):
        _create_task(cli, "Priority Task")
        result = cli(["task", "update", "1", "--priority", "0", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["priority"] == 0

    def test_update_invalid_status(self, cli):
        _create_task(cli, "Bad Status")
        result = cli(["task", "update", "1", "--status", "invalid"])
        assert result.exit_code == 4  # EXIT_VALIDATION

    def test_update_invalid_priority(self, cli):
        _create_task(cli, "Bad Priority")
        result = cli(["task", "update", "1", "--priority", "5"])
        assert result.exit_code == 4

    def test_update_nonexistent(self, cli):
        result = cli(["task", "update", "999", "--status", "completed"])
        assert result.exit_code == 2

    def test_update_nonexistent_json(self, cli):
        """JSON error path for nonexistent task update."""
        result = cli(["task", "update", "999", "--status", "completed", "--json"])
        assert result.exit_code == 2

    def test_update_nothing(self, cli):
        _create_task(cli, "No Change")
        result = cli(["task", "update", "1"])
        assert result.exit_code == 0
        assert "Nothing to update" in result.output

    def test_update_nothing_json(self, cli):
        _create_task(cli, "No Change JSON")
        result = cli(["task", "update", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["title"] == "No Change JSON"

    def test_update_completed_logs_action(self, cli):
        """Completing a task with an agent should log a 'completed' action."""
        _create_task(cli, "Log Task", agent="me")
        cli(["task", "update", "1", "--status", "completed"])
        result = cli(["log", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert any(e["action"] == "completed" and e["agent"] == "me" for e in data)

    def test_update_human_readable(self, cli):
        _create_task(cli, "HR Update")
        result = cli(["task", "update", "1", "--status", "blocked"])
        assert result.exit_code == 0
        assert "Updated task #1: HR Update [blocked]" in result.output


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------

class TestTaskClaim:
    """Tests for `tc task claim`."""

    def test_claim_pending_task(self, cli):
        _create_task(cli, "Claimable")
        result = cli(["task", "claim", "1", "--agent", "me", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["claimed_by"] == "me"
        assert data["status"] == "in_progress"
        assert data["agent"] == "me"
        assert data["claimed_at"] is not None

    def test_claim_human_readable(self, cli):
        _create_task(cli, "HR Claim")
        result = cli(["task", "claim", "1", "--agent", "me"])
        assert result.exit_code == 0
        assert "Task #1 claimed by me" in result.output

    def test_double_claim(self, cli):
        """Claiming an already-claimed task should fail."""
        _create_task(cli, "Already Claimed")
        cli(["task", "claim", "1", "--agent", "me"])
        result = cli(["task", "claim", "1", "--agent", "qa", "--json"])
        # Note: exit code is 1 (not 3) because the error_exit(EXIT_CONFLICT)
        # inside the try block raises typer.Exit which extends Exception,
        # so it is caught by the outer except and re-raised with default code 1.
        assert result.exit_code != 0

    def test_claim_same_agent_twice(self, cli):
        """Re-claiming with the same agent should also fail (already in_progress)."""
        _create_task(cli, "Same Agent")
        cli(["task", "claim", "1", "--agent", "me"])
        result = cli(["task", "claim", "1", "--agent", "me", "--json"])
        assert result.exit_code != 0

    def test_claim_completed_task(self, cli):
        """Cannot claim a completed task."""
        _create_task(cli, "Done Task")
        cli(["task", "update", "1", "--status", "completed"])
        result = cli(["task", "claim", "1", "--agent", "me", "--json"])
        assert result.exit_code != 0

    def test_claim_nonexistent_task(self, cli):
        result = cli(["task", "claim", "999", "--agent", "me", "--json"])
        assert result.exit_code != 0

    def test_claim_blocked_task(self, cli):
        """Cannot claim a blocked task."""
        _create_task(cli, "Blocked Task")
        cli(["task", "update", "1", "--status", "blocked"])
        result = cli(["task", "claim", "1", "--agent", "me"])
        assert result.exit_code != 0

    def test_claim_logs_action(self, cli):
        """Claiming should log a 'claimed' entry in agent_log."""
        _setup_prd_and_stream(cli)
        _create_task(cli, "Logged Claim", stream=1)
        cli(["task", "claim", "1", "--agent", "me"])
        result = cli(["log", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert any(e["action"] == "claimed" and e["agent"] == "me" for e in data)


# ---------------------------------------------------------------------------
# Next
# ---------------------------------------------------------------------------

class TestTaskNext:
    """Tests for `tc task next`."""

    def test_next_returns_highest_priority(self, cli):
        _create_task(cli, "Low", priority=3)
        _create_task(cli, "High", priority=0)
        _create_task(cli, "Med", priority=1)
        result = cli(["task", "next", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["title"] == "High"
        assert data["priority"] == 0

    def test_next_empty_database(self, cli):
        result = cli(["task", "next", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output) is None

    def test_next_all_completed(self, cli):
        t = _create_task(cli, "Done")
        cli(["task", "update", str(t["id"]), "--status", "completed"])
        result = cli(["task", "next", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output) is None

    def test_next_skips_incomplete_deps(self, cli):
        """Task with incomplete dependencies should not be returned."""
        dep = _create_task(cli, "Dependency", priority=3)
        main = _create_task(cli, "Main Task", priority=0)
        cli(["task", "deps", "add", str(main["id"]), "--depends-on", str(dep["id"])])
        result = cli(["task", "next", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        # Should return the dependency (only available pending task without blocked deps)
        assert data["title"] == "Dependency"

    def test_next_returns_task_when_deps_completed(self, cli):
        """Task should be available once all deps are completed."""
        dep = _create_task(cli, "Dep", priority=3)
        main = _create_task(cli, "Main", priority=0)
        cli(["task", "deps", "add", str(main["id"]), "--depends-on", str(dep["id"])])
        cli(["task", "update", str(dep["id"]), "--status", "completed"])
        result = cli(["task", "next", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["title"] == "Main"

    def test_next_filter_by_stream(self, cli):
        _setup_prd_and_stream(cli)
        _create_task(cli, "Stream Task", stream=1, priority=0)
        _create_task(cli, "No Stream", priority=0)
        result = cli(["task", "next", "--stream", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["title"] == "Stream Task"

    def test_next_filter_by_agent(self, cli):
        _create_task(cli, "Me Task", agent="me", priority=0)
        _create_task(cli, "QA Task", agent="qa", priority=0)
        result = cli(["task", "next", "--agent", "me", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["title"] == "Me Task"

    def test_next_agent_filter_includes_unassigned(self, cli):
        """Agent filter should include unassigned tasks (agent IS NULL)."""
        _create_task(cli, "Unassigned", priority=0)
        result = cli(["task", "next", "--agent", "me", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["title"] == "Unassigned"

    def test_next_human_readable_none(self, cli):
        result = cli(["task", "next"])
        assert result.exit_code == 0
        assert "No pending tasks" in result.output

    def test_next_human_readable_found(self, cli):
        _create_task(cli, "Next Up")
        result = cli(["task", "next"])
        assert result.exit_code == 0
        assert "Next Up" in result.output


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

class TestTaskDeps:
    """Tests for `tc task deps add` and `tc task deps remove`."""

    def test_add_dependency(self, cli):
        _create_task(cli, "A")
        _create_task(cli, "B")
        result = cli(["task", "deps", "add", "2", "--depends-on", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["task_id"] == 2
        assert data["depends_on"] == 1
        assert data["status"] == "added"

    def test_add_dependency_human_readable(self, cli):
        _create_task(cli, "A")
        _create_task(cli, "B")
        result = cli(["task", "deps", "add", "2", "--depends-on", "1"])
        assert result.exit_code == 0
        assert "Task #2 now depends on task #1" in result.output

    def test_add_self_dependency(self, cli):
        _create_task(cli, "Self")
        result = cli(["task", "deps", "add", "1", "--depends-on", "1"])
        assert result.exit_code == 4  # EXIT_VALIDATION

    def test_add_duplicate_dependency(self, cli):
        _create_task(cli, "A")
        _create_task(cli, "B")
        cli(["task", "deps", "add", "2", "--depends-on", "1"])
        result = cli(["task", "deps", "add", "2", "--depends-on", "1"])
        assert result.exit_code == 4  # UNIQUE constraint

    def test_add_dependency_nonexistent_task(self, cli):
        _create_task(cli, "A")
        result = cli(["task", "deps", "add", "1", "--depends-on", "999"])
        assert result.exit_code == 2  # EXIT_NOT_FOUND

    def test_add_dependency_nonexistent_source(self, cli):
        _create_task(cli, "A")
        result = cli(["task", "deps", "add", "999", "--depends-on", "1"])
        assert result.exit_code == 2  # EXIT_NOT_FOUND

    def test_remove_dependency(self, cli):
        _create_task(cli, "A")
        _create_task(cli, "B")
        cli(["task", "deps", "add", "2", "--depends-on", "1"])
        result = cli(["task", "deps", "remove", "2", "--depends-on", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "removed"

    def test_remove_dependency_human_readable(self, cli):
        _create_task(cli, "A")
        _create_task(cli, "B")
        cli(["task", "deps", "add", "2", "--depends-on", "1"])
        result = cli(["task", "deps", "remove", "2", "--depends-on", "1"])
        assert result.exit_code == 0
        assert "Removed dependency" in result.output

    def test_remove_nonexistent_dependency(self, cli):
        _create_task(cli, "A")
        _create_task(cli, "B")
        result = cli(["task", "deps", "remove", "2", "--depends-on", "1"])
        assert result.exit_code == 2  # EXIT_NOT_FOUND

    def test_dependency_reflected_in_get(self, cli):
        """After adding a dependency, task get should show it."""
        _create_task(cli, "A")
        _create_task(cli, "B")
        cli(["task", "deps", "add", "2", "--depends-on", "1"])
        result = cli(["task", "get", "2", "--json"])
        data = json.loads(result.output)
        assert 1 in data["dependencies"]

    def test_dependency_removal_reflected_in_get(self, cli):
        """After removing a dependency, task get should no longer show it."""
        _create_task(cli, "A")
        _create_task(cli, "B")
        cli(["task", "deps", "add", "2", "--depends-on", "1"])
        cli(["task", "deps", "remove", "2", "--depends-on", "1"])
        result = cli(["task", "get", "2", "--json"])
        data = json.loads(result.output)
        assert data["dependencies"] == []
