#!/usr/bin/env python3
"""
Check Streams Data Fetcher

Fetches stream and task data from Task Copilot for use in the check-streams bash script.
Outputs data in a simple format that bash can parse.
"""

import sys
from pathlib import Path

# Import Task Copilot client
from task_copilot_client import TaskCopilotClient


def main():
    if len(sys.argv) < 2:
        print("Usage: python check_streams_data.py <workspace_id>", file=sys.stderr)
        sys.exit(1)

    workspace_id = sys.argv[1]
    client = TaskCopilotClient(workspace_id)

    try:
        # Get overall summary
        summary = client.progress_summary()
        print(f"OVERALL {summary.completed_tasks} {summary.total_tasks} {summary.in_progress_tasks} {summary.pending_tasks} {summary.completion_percentage}")

        # Get all streams
        streams = client.stream_list()

        # Get progress for each stream
        for stream_info in streams:
            progress = client.stream_get(stream_info.stream_id)
            if progress:
                # Format: STREAM <id> <completed> <total> <pct> <in_progress> <pending> <blocked> <stream_name>
                stream_name = stream_info.stream_name if stream_info.stream_name else ""
                print(f"STREAM {progress.stream_id} {progress.completed_tasks} {progress.total_tasks} {progress.completion_percentage} {progress.in_progress_tasks} {progress.pending_tasks} {progress.blocked_tasks} {stream_name}")

    except FileNotFoundError as e:
        # Database doesn't exist - this is okay, just output nothing
        pass
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
