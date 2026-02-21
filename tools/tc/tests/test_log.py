"""Tests for agent activity log command."""

import json

import pytest


class TestLog:
    """Tests for `tc log`."""

    def test_log_empty(self, cli):
        result = cli(["log", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == []

    def test_log_after_claim(self, cli):
        cli(["task", "create", "--title", "Claim Log"])
        cli(["task", "claim", "1", "--agent", "me"])
        result = cli(["log", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) >= 1
        assert any(e["action"] == "claimed" and e["agent"] == "me" for e in data)

    def test_log_after_completion(self, cli):
        cli(["task", "create", "--title", "Complete Log", "--agent", "me"])
        cli(["task", "update", "1", "--status", "completed"])
        result = cli(["log", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert any(e["action"] == "completed" for e in data)

    def test_log_after_handoff(self, cli):
        cli(["task", "create", "--title", "Handoff Log"])
        cli([
            "handoff", "--from", "me", "--to", "qa",
            "--task", "1", "--context", "Done",
        ])
        result = cli(["log", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert any(e["action"] == "handoff" for e in data)

    def test_log_filter_by_agent(self, cli):
        cli(["task", "create", "--title", "T1"])
        cli(["task", "create", "--title", "T2"])
        cli(["task", "claim", "1", "--agent", "me"])
        cli(["task", "claim", "2", "--agent", "qa"])
        result = cli(["log", "--agent", "me", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert all(e["agent"] == "me" for e in data)
        assert len(data) >= 1

    def test_log_filter_by_stream(self, cli):
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "s1", "--prd", "1"])
        cli(["stream", "create", "--name", "s2", "--prd", "1"])
        cli(["task", "create", "--title", "T1", "--stream", "1"])
        cli(["task", "create", "--title", "T2", "--stream", "2"])
        cli(["task", "claim", "1", "--agent", "me"])
        cli(["task", "claim", "2", "--agent", "qa"])
        result = cli(["log", "--stream", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert all(e["stream_id"] == 1 for e in data)

    def test_log_filter_by_task(self, cli):
        cli(["task", "create", "--title", "T1"])
        cli(["task", "create", "--title", "T2"])
        cli(["task", "claim", "1", "--agent", "me"])
        cli(["task", "claim", "2", "--agent", "qa"])
        result = cli(["log", "--task", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert all(e["task_id"] == 1 for e in data)

    def test_log_limit(self, cli):
        # Create multiple log entries
        for i in range(5):
            cli(["task", "create", "--title", f"T{i}"])
        for i in range(1, 6):
            cli(["task", "claim", str(i), "--agent", "me"])
        result = cli(["log", "--limit", "3", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 3

    def test_log_order_desc(self, cli):
        cli(["task", "create", "--title", "T1"])
        cli(["task", "create", "--title", "T2"])
        cli(["task", "claim", "1", "--agent", "me"])
        cli(["task", "claim", "2", "--agent", "qa"])
        result = cli(["log", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        # IDs should be descending
        ids = [e["id"] for e in data]
        assert ids == sorted(ids, reverse=True)

    def test_log_human_readable_empty(self, cli):
        result = cli(["log"])
        assert result.exit_code == 0
        assert "no result" in result.output.lower()

    def test_log_human_readable_with_data(self, cli):
        cli(["task", "create", "--title", "T1"])
        cli(["task", "claim", "1", "--agent", "me"])
        result = cli(["log"])
        assert result.exit_code == 0
        # Should have some output with agent info
        assert "me" in result.output
