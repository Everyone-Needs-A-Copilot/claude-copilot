#!/usr/bin/env python3
"""
Start Ready Streams - Called by workers after completing their tasks.

Checks for streams whose dependencies are now satisfied and starts them.
This enables worker chaining - each completing stream triggers the next.

Usage:
    python start-ready-streams.py [--completed-stream STREAM_ID]

If --completed-stream is provided, only checks streams that depend on it.
Otherwise, checks all streams.
"""

import sys
import subprocess
import argparse
from pathlib import Path

# Import Task Copilot client from same directory
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from task_copilot_client import TaskCopilotClient

# Configuration
PROJECT_ROOT = SCRIPT_DIR.parent.parent
WORKSPACE_ID = PROJECT_ROOT.name
PID_DIR = SCRIPT_DIR / "pids"
LOG_DIR = SCRIPT_DIR / "logs"


class Colors:
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'


def log(msg: str):
    print(f"{Colors.CYAN}[CHAIN]{Colors.NC} {msg}")


def success(msg: str):
    print(f"{Colors.GREEN}[CHAIN]{Colors.NC} {msg}")


def is_running(stream_id: str) -> bool:
    """Check if a stream worker is currently running."""
    pid_file = PID_DIR / f"{stream_id}.pid"
    if not pid_file.exists():
        return False

    try:
        import os
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        # Double-check with ps to catch zombies
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "pid="],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except:
        return False


def main():
    parser = argparse.ArgumentParser(description="Start streams whose dependencies are ready")
    parser.add_argument("--completed-stream", help="Stream that just completed (filters dependents)")
    args = parser.parse_args()

    client = TaskCopilotClient(WORKSPACE_ID)

    # Get active initiative
    initiative_id = client.get_active_initiative_id()
    if not initiative_id:
        return  # No active initiative, nothing to do

    # Get all streams for this initiative
    streams = client.stream_list(initiative_id=initiative_id)
    if not streams:
        return

    # Build dependency map and get status for each stream
    stream_deps = {}
    stream_status = {}

    for stream_info in streams:
        stream_deps[stream_info.stream_id] = set(stream_info.dependencies)
        progress = client.stream_get(stream_info.stream_id, initiative_id=initiative_id)
        if progress:
            stream_status[stream_info.stream_id] = {
                "complete": progress.is_complete,
                "total": progress.total_tasks,
                "completed": progress.completed_tasks
            }

    # Find streams that are ready to start
    ready_to_start = []

    for stream_id, deps in stream_deps.items():
        # Skip if already complete
        status = stream_status.get(stream_id, {})
        if status.get("complete"):
            continue

        # Skip if already running
        if is_running(stream_id):
            continue

        # If --completed-stream specified, only consider streams that depend on it
        if args.completed_stream and args.completed_stream not in deps:
            continue

        # Check if all dependencies are complete
        all_deps_complete = True
        for dep in deps:
            dep_status = stream_status.get(dep, {})
            if not dep_status.get("complete"):
                all_deps_complete = False
                break

        if all_deps_complete:
            ready_to_start.append(stream_id)

    # Start ready streams
    if not ready_to_start:
        if args.completed_stream:
            log(f"No streams ready to start after {args.completed_stream}")
        return

    for stream_id in ready_to_start:
        log(f"Starting {stream_id} (dependencies satisfied)")

        # Use orchestrate.py to start the stream
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "orchestrate.py"), "start", stream_id],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            success(f"Started {stream_id}")
        else:
            print(f"Failed to start {stream_id}: {result.stderr}", file=sys.stderr)


if __name__ == "__main__":
    main()
