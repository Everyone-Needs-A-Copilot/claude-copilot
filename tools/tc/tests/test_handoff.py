"""Tests for agent handoff command."""

import json

import pytest


class TestHandoff:
    """Tests for `tc handoff`."""

    def test_successful_handoff(self, cli):
        cli(["task", "create", "--title", "Handoff Task", "--agent", "me"])
        result = cli([
            "handoff",
            "--from", "me",
            "--to", "qa",
            "--task", "1",
            "--context", "Completed implementation, ready for review",
            "--json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["task_id"] == 1
        assert data["from"] == "me"
        assert data["to"] == "qa"
        assert data["context"] == "Completed implementation, ready for review"
        assert data["status"] == "handed_off"

    def test_handoff_updates_task_agent(self, cli):
        cli(["task", "create", "--title", "Agent Update", "--agent", "me"])
        cli([
            "handoff", "--from", "me", "--to", "qa",
            "--task", "1", "--context", "Done",
        ])
        result = cli(["task", "get", "1", "--json"])
        data = json.loads(result.output)
        assert data["agent"] == "qa"

    def test_handoff_logs_action(self, cli):
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "s1", "--prd", "1"])
        cli(["task", "create", "--title", "Log Task", "--stream", "1", "--agent", "me"])
        cli([
            "handoff", "--from", "me", "--to", "qa",
            "--task", "1", "--context", "Review please",
        ])
        result = cli(["log", "--json"])
        data = json.loads(result.output)
        handoffs = [e for e in data if e["action"] == "handoff"]
        assert len(handoffs) == 1
        assert handoffs[0]["agent"] == "me"
        assert "me -> qa" in handoffs[0]["details"]

    def test_handoff_nonexistent_task(self, cli):
        result = cli([
            "handoff", "--from", "me", "--to", "qa",
            "--task", "999", "--context", "Ghost task",
        ])
        assert result.exit_code == 2  # EXIT_NOT_FOUND

    def test_handoff_context_truncation(self, cli):
        cli(["task", "create", "--title", "Truncate Task"])
        long_context = "x" * 300
        result = cli([
            "handoff", "--from", "me", "--to", "qa",
            "--task", "1", "--context", long_context,
            "--json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["context"]) == 200

    def test_handoff_human_readable(self, cli):
        cli(["task", "create", "--title", "HR Handoff"])
        result = cli([
            "handoff", "--from", "me", "--to", "qa",
            "--task", "1", "--context", "All done",
        ])
        assert result.exit_code == 0
        assert "Task #1 handed off from me to qa" in result.output
        assert "Context: All done" in result.output

    def test_handoff_with_stream_context(self, cli):
        """Handoff should log with stream_id from the task."""
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "s1", "--prd", "1"])
        cli(["task", "create", "--title", "Stream Task", "--stream", "1"])
        cli([
            "handoff", "--from", "me", "--to", "qa",
            "--task", "1", "--context", "Stream handoff",
        ])
        result = cli(["log", "--stream", "1", "--json"])
        data = json.loads(result.output)
        assert len(data) >= 1
        assert data[0]["stream_id"] == 1
