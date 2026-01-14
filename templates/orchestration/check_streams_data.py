#!/usr/bin/env python3
"""
Check Streams Data Fetcher

Fetches stream and task data from Task Copilot for use in the check-streams bash script.
Outputs data in a simple format that bash can parse.

Supports initiative-scoped filtering - only shows streams belonging to the active initiative.
"""

import sys
import argparse
from pathlib import Path

# Import Task Copilot client
from task_copilot_client import TaskCopilotClient


def main():
    parser = argparse.ArgumentParser(description='Fetch stream data from Task Copilot')
    parser.add_argument('workspace_id', help='Workspace identifier')
    parser.add_argument('--initiative-id', help='Filter by initiative ID (default: auto-detect active)')
    parser.add_argument('--no-filter', action='store_true', help='Show all streams (no initiative filtering)')
    args = parser.parse_args()

    workspace_id = args.workspace_id
    client = TaskCopilotClient(workspace_id)

    # Check if database exists
    if not client.db_path.exists():
        print("NO_DATABASE")
        return

    try:
        # Determine initiative ID to filter by
        initiative_id = None
        initiative_name = None
        initiative_goal = None

        if not args.no_filter:
            if args.initiative_id:
                initiative_id = args.initiative_id
            else:
                # Auto-detect active initiative
                initiative_id = client.get_active_initiative_id()

            # Get initiative details if we have an ID
            if initiative_id:
                details = client.get_initiative_details(initiative_id)
                if details:
                    initiative_name = details.name
                    initiative_goal = details.goal

        # If no initiative found and filtering is enabled, report no initiative
        if not args.no_filter and not initiative_id:
            print("NO_INITIATIVE")
            return

        # Output initiative info if available
        if initiative_id and initiative_name:
            goal_str = initiative_goal if initiative_goal else ""
            print(f"INITIATIVE {initiative_id}|{initiative_name}|{goal_str}")

        # Get streams (filtered by initiative if applicable)
        streams = client.stream_list(initiative_id)

        # Check if there are any streams
        if not streams:
            if initiative_id:
                print("NO_ACTIVE_STREAMS")
            else:
                print("NO_STREAMS")
            return

        # Get overall summary (filtered by initiative if applicable)
        summary = client.progress_summary(initiative_id)
        print(f"OVERALL {summary.completed_tasks} {summary.total_tasks} {summary.in_progress_tasks} {summary.pending_tasks} {summary.completion_percentage}")

        # Check if ALL streams are 100% complete
        all_complete = True
        for stream_info in streams:
            progress = client.stream_get(stream_info.stream_id, initiative_id)
            if progress and not progress.is_complete:
                all_complete = False
                break

        if all_complete and streams:
            # All streams complete - still output them but signal completion
            print("ALL_STREAMS_COMPLETE")

        # Get progress for each stream
        for stream_info in streams:
            progress = client.stream_get(stream_info.stream_id, initiative_id)
            if progress:
                # Format: STREAM <id> <completed> <total> <pct> <in_progress> <pending> <blocked> <stream_name>
                stream_name = stream_info.stream_name if stream_info.stream_name else ""
                print(f"STREAM {progress.stream_id} {progress.completed_tasks} {progress.total_tasks} {progress.completion_percentage} {progress.in_progress_tasks} {progress.pending_tasks} {progress.blocked_tasks} {stream_name}")

    except FileNotFoundError:
        # Database doesn't exist - this is okay
        print("NO_DATABASE")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
