"""Tests for `/orchestrate generate` (.claude/commands/orchestrate.md).

AUDIT-claims.md finding 2: `generate` step 3 only ran `tc prd create` and
`tc task create --title ... --prd <id> --json` for each task -- it never
called `tc stream create` and never passed `--metadata`/`--stream` to `tc
task create`, despite step 1 requiring @agent-ta's JSON to carry per-task
`streamId`/`streamName`/`files`/`dependencies` metadata. Consequence: every
task's `stream_id` and `metadata` columns stayed NULL, so `start`'s hard
precondition `tc stream conflicts` (reads `tasks.metadata.files`) and `tc
task list --stream <id>` (each stream's work list) always operated on zero
stream-scoped rows -- the generate -> start handoff was silently broken even
though `tc stream conflicts` itself (tools/tc/tests/test_stream.py) and `tc
task list --stream` (tools/tc/tests/test_task.py) both work correctly in
isolation.

Two kinds of coverage here:
  - Doc-content: `generate`'s documented command sequence must literally
    include `tc stream create` and `tc task create` with `--stream` and
    `--metadata`, using the same markdown-parsing approach as
    test_claude_flag_existence.py.
  - End-to-end: running that exact sequence against a real tc database
    (mirroring what `generate` now documents step-by-step) must leave rows
    that `tc stream conflicts` and `tc task list --stream <id>` can actually
    read back -- closing the loop the doc-content check alone can't prove.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path("/Volumes/Dev/Sites/COPILOT/claude-copilot")
ORCHESTRATE_MD = REPO_ROOT / ".claude/commands/orchestrate.md"


def _generate_section(text: str) -> str:
    """Return the text between the `## `generate`` heading and the next
    `## ` heading (the `start` section)."""
    match = re.search(
        r"## `generate`.*?(?=\n## )", text, flags=re.DOTALL
    )
    assert match, "expected a `## `generate`` section in orchestrate.md"
    return match.group(0)


class TestGenerateDocRequiresStreamAndMetadata:
    """Doc-content: the exact defect from finding 2. Before the fix, this
    section only mentioned `tc prd create` and a bare `tc task create
    --title ... --prd <id>` -- no stream, no metadata."""

    def test_generate_section_calls_tc_stream_create(self):
        text = ORCHESTRATE_MD.read_text(encoding="utf-8")
        section = _generate_section(text)
        assert "tc stream create" in section, (
            "generate must create a stream row per unique streamId so "
            "`start`'s `tc stream conflicts` and `tc task list --stream "
            "<id>` have real stream ids to key off of"
        )

    def test_generate_section_passes_stream_and_metadata_to_task_create(self):
        text = ORCHESTRATE_MD.read_text(encoding="utf-8")
        section = _generate_section(text)
        # Find the `tc task create` line(s) and confirm both flags appear
        # on/near them, not just anywhere in the section.
        assert "tc task create" in section
        task_create_mentions = [
            line for line in section.splitlines() if "tc task create" in line
        ]
        assert task_create_mentions, "expected a `tc task create` line in generate"
        for line in task_create_mentions:
            assert "--stream" in line, (
                f"tc task create in generate must pass --stream <numeric-id> "
                f"so the task is queryable via `tc task list --stream <id>`: {line!r}"
            )
            assert "--metadata" in line, (
                f"tc task create in generate must pass --metadata so `tc "
                f"stream conflicts` has tasks.metadata.files to read: {line!r}"
            )

    def test_generate_section_does_not_use_streamid_label_as_numeric_stream(self):
        """@agent-ta's JSON uses a string label (`"Stream-A"`), but `tc task
        create --stream` takes a numeric DB id (verified: `tc task create
        --help` -> `--stream <int>`). generate must document mapping the
        label to the numeric id `tc stream create` returns, not passing the
        label straight through."""
        text = ORCHESTRATE_MD.read_text(encoding="utf-8")
        section = _generate_section(text)
        assert "numeric" in section.lower(), (
            "generate should document that the streamId label must be "
            "mapped to the numeric stream id tc stream create returns"
        )


class TestGenerateEndToEnd:
    """Run generate's documented recipe for real: prd create -> stream
    create (once per unique streamId) -> task create --stream <numeric-id>
    --metadata <json>. Then verify start's actual consumers
    (`tc stream conflicts`, `tc task list --stream <id>`) see real data."""

    def test_documented_sequence_populates_stream_scoped_tasks(self, cli):
        # Step 1 (abridged): @agent-ta's JSON for two streams, one task each.
        ta_tasks = [
            {
                "title": "Build auth middleware",
                "metadata": {
                    "streamId": "Stream-A",
                    "streamName": "Foundation",
                    "files": ["src/auth.ts"],
                    "dependencies": [],
                },
            },
            {
                "title": "Build billing service",
                "metadata": {
                    "streamId": "Stream-B",
                    "streamName": "Billing",
                    "files": ["src/billing.ts"],
                    "dependencies": [],
                },
            },
        ]

        # Step 3.1: tc prd create
        prd_result = cli(
            ["prd", "create", "--title", "Auth + Billing", "--json"]
        )
        assert prd_result.exit_code == 0
        prd_id = json.loads(prd_result.output)["id"]

        # Step 3.2: tc stream create per unique streamId, remember numeric id
        stream_id_by_label: dict[str, int] = {}
        for task in ta_tasks:
            label = task["metadata"]["streamId"]
            if label in stream_id_by_label:
                continue
            stream_result = cli(
                [
                    "stream",
                    "create",
                    "--name",
                    task["metadata"]["streamName"],
                    "--prd",
                    str(prd_id),
                    "--json",
                ]
            )
            assert stream_result.exit_code == 0
            stream_id_by_label[label] = json.loads(stream_result.output)["id"]

        # Step 3.3: tc task create --stream <numeric-id> --metadata <json>
        for task in ta_tasks:
            numeric_stream_id = stream_id_by_label[task["metadata"]["streamId"]]
            task_result = cli(
                [
                    "task",
                    "create",
                    "--title",
                    task["title"],
                    "--prd",
                    str(prd_id),
                    "--stream",
                    str(numeric_stream_id),
                    "--metadata",
                    json.dumps(task["metadata"]),
                    "--json",
                ]
            )
            assert task_result.exit_code == 0

        # `start` step 5's per-stream work list must be non-empty.
        stream_a_id = stream_id_by_label["Stream-A"]
        work_list = cli(
            ["task", "list", "--stream", str(stream_a_id), "--json"]
        )
        assert work_list.exit_code == 0
        work_list_data = json.loads(work_list.output)
        assert len(work_list_data) == 1, (
            "generate's documented sequence must leave `tc task list "
            "--stream <id>` with real rows, not zero -- this was the exact "
            "bug: task.stream_id stayed NULL so this always returned []"
        )
        assert work_list_data[0]["title"] == "Build auth middleware"

        # `start` step 3's `tc stream conflicts` precondition must have
        # real tasks.metadata.files to read (no overlap here -> exit 0).
        conflicts = cli(["stream", "conflicts", "--json"])
        assert conflicts.exit_code == 0
        assert json.loads(conflicts.output) == []

    def test_documented_sequence_surfaces_real_conflicts(self, cli):
        """Same recipe, but two streams claim the same file -- `tc stream
        conflicts` (start's hard precondition) must catch it, proving the
        metadata this sequence writes is exactly what that check reads."""
        prd_id = json.loads(
            cli(["prd", "create", "--title", "Conflicting PRD", "--json"]).output
        )["id"]

        stream_a = json.loads(
            cli(
                ["stream", "create", "--name", "Stream-A", "--prd", str(prd_id), "--json"]
            ).output
        )["id"]
        stream_b = json.loads(
            cli(
                ["stream", "create", "--name", "Stream-B", "--prd", str(prd_id), "--json"]
            ).output
        )["id"]

        metadata_a = json.dumps(
            {"streamId": "Stream-A", "files": ["src/shared.ts"], "dependencies": []}
        )
        metadata_b = json.dumps(
            {"streamId": "Stream-B", "files": ["src/shared.ts"], "dependencies": []}
        )
        cli(
            [
                "task", "create", "--title", "A task", "--prd", str(prd_id),
                "--stream", str(stream_a), "--metadata", metadata_a, "--json",
            ]
        )
        cli(
            [
                "task", "create", "--title", "B task", "--prd", str(prd_id),
                "--stream", str(stream_b), "--metadata", metadata_b, "--json",
            ]
        )

        result = cli(["stream", "conflicts", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["file"] == "src/shared.ts"
