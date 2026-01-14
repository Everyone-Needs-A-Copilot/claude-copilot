#!/usr/bin/env python3
"""
Monitor Workers Daemon - Auto-restart dead/crashed workers

This daemon continuously monitors worker processes for crashes and automatically
restarts them with configurable retry limits. It uses the same zombie detection
pattern as check-streams (ps -p verification).

Usage:
    python monitor-workers.py                       # One-shot check (no restart)
    python monitor-workers.py --auto-restart        # Background daemon with auto-restart
    python monitor-workers.py --auto-restart --max-restarts 3  # Custom retry limit
    python monitor-workers.py --interval 30         # Custom check interval (seconds)

Features:
- Detects dead workers using ps -p verification (catches zombies)
- Auto-restarts failed workers with configurable max restart count
- Logs all restart attempts with timestamps
- Works as background daemon or one-shot check
- Integrates with existing worker-wrapper.sh
- Respects stream dependencies (only restarts if dependencies complete)
"""

import os
import sys
import time
import signal
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Set
from collections import defaultdict

# Import Task Copilot client
from task_copilot_client import TaskCopilotClient

# Configuration
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
PROJECT_NAME = PROJECT_ROOT.name
LOG_DIR = SCRIPT_DIR / "logs"
PID_DIR = SCRIPT_DIR / "pids"
MONITOR_LOG = LOG_DIR / "monitor.log"

# Default settings
DEFAULT_CHECK_INTERVAL = 30  # seconds
DEFAULT_MAX_RESTARTS = 2

# Task Copilot workspace ID
WORKSPACE_ID = PROJECT_NAME


class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    MAGENTA = '\033[0;35m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    NC = '\033[0m'


def log_message(msg: str, level: str = "INFO"):
    """Log message to both console and log file."""
    timestamp = datetime.now().isoformat()
    log_entry = f"[{timestamp}] [{level}] {msg}"

    # Console output with colors
    color = {
        "INFO": Colors.BLUE,
        "SUCCESS": Colors.GREEN,
        "WARNING": Colors.YELLOW,
        "ERROR": Colors.RED,
    }.get(level, Colors.NC)

    print(f"{color}[MONITOR]{Colors.NC} {msg}")

    # File output
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(MONITOR_LOG, 'a') as f:
        f.write(log_entry + '\n')


def success(msg: str):
    log_message(msg, "SUCCESS")


def warn(msg: str):
    log_message(msg, "WARNING")


def error(msg: str):
    log_message(msg, "ERROR")


class WorkerMonitor:
    def __init__(self, max_restarts: int = DEFAULT_MAX_RESTARTS, auto_restart: bool = False):
        self.tc_client = TaskCopilotClient(WORKSPACE_ID)
        self.max_restarts = max_restarts
        self.auto_restart = auto_restart
        self.restart_counts: Dict[str, int] = defaultdict(int)

        # Get active initiative
        self.initiative_id = self.tc_client.get_active_initiative_id()
        if not self.initiative_id:
            warn("No active initiative found")
            self.streams = {}
            return

        # Get initiative details
        self.initiative_details = self.tc_client.get_initiative_details(self.initiative_id)
        if self.initiative_details:
            log_message(f"Monitoring initiative: {self.initiative_details.name}")

        # Query streams
        self.streams = self._query_streams()
        self.stream_dependencies = self._build_dependency_graph()

        # Ensure directories exist
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        PID_DIR.mkdir(parents=True, exist_ok=True)

    def _query_streams(self) -> Dict[str, dict]:
        """Query streams dynamically using Task Copilot client."""
        try:
            stream_infos = self.tc_client.stream_list(initiative_id=self.initiative_id)

            if not stream_infos:
                return {}

            streams = {}
            for stream_info in stream_infos:
                worktree = "." if stream_info.stream_id == "main" else f".claude/worktrees/{stream_info.stream_id}"

                streams[stream_info.stream_id] = {
                    "id": stream_info.stream_id,
                    "name": stream_info.stream_name,
                    "dependencies": stream_info.dependencies,
                    "worktree": worktree,
                }

            return streams

        except FileNotFoundError as e:
            error(str(e))
            return {}
        except Exception as e:
            error(f"Failed to query streams: {e}")
            return {}

    def _build_dependency_graph(self) -> Dict[str, Set[str]]:
        """Build stream dependency graph from task metadata."""
        dependency_graph: Dict[str, Set[str]] = defaultdict(set)

        for stream_id, stream in self.streams.items():
            dependencies = stream.get("dependencies", [])

            for dep in dependencies:
                if dep in self.streams:
                    dependency_graph[stream_id].add(dep)
                else:
                    # Try to extract stream ID from task title format
                    for sid in self.streams.keys():
                        if dep.startswith(f"{sid}:") or dep.startswith(f"[{sid}]"):
                            dependency_graph[stream_id].add(sid)
                            break

        return dependency_graph

    def _is_running(self, stream_id: str) -> bool:
        """Check if a stream worker is currently running.

        Uses ps -p verification to detect zombie processes.
        Zombies pass kill -0 but ps -p will fail.
        """
        pid_file = PID_DIR / f"{stream_id}.pid"
        if not pid_file.exists():
            return False

        try:
            pid = int(pid_file.read_text().strip())

            # Check if process exists with kill -0
            os.kill(pid, 0)

            # Double-check with ps to catch zombies
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "pid="],
                capture_output=True,
                timeout=5
            )

            if result.returncode != 0:
                # Process is zombie or doesn't exist
                pid_file.unlink(missing_ok=True)
                return False

            return True

        except (ProcessLookupError, ValueError, subprocess.TimeoutExpired):
            pid_file.unlink(missing_ok=True)
            return False

    def _get_stream_status(self, stream_id: str):
        """Get stream status using Task Copilot client."""
        try:
            progress = self.tc_client.stream_get(stream_id)
            if not progress:
                return None

            return {
                "total_tasks": progress.total_tasks,
                "completed_tasks": progress.completed_tasks,
                "in_progress_tasks": progress.in_progress_tasks,
                "is_complete": progress.is_complete
            }
        except Exception as e:
            warn(f"Failed to get status for {stream_id}: {e}")
            return None

    def _are_dependencies_complete(self, stream_id: str) -> bool:
        """Check if all dependencies for a stream are complete."""
        dependencies = self.stream_dependencies.get(stream_id, set())

        if not dependencies:
            return True

        for dep_stream_id in dependencies:
            status = self._get_stream_status(dep_stream_id)
            if not status or not status["is_complete"]:
                return False

        return True

    def _get_log_file(self, stream_id: str) -> Path:
        """Get log file path using per-initiative naming."""
        return LOG_DIR / f"{stream_id}_{self.initiative_id[:8]}.log"

    def _detect_dead_workers(self) -> list:
        """Detect workers that died with incomplete tasks.

        Returns list of stream_ids where:
        - Worker was previously running (log file exists)
        - Process is now dead
        - Tasks are not complete
        - Dependencies are satisfied (was ready to run)
        """
        dead_workers = []

        for stream_id in self.streams.keys():
            # Skip if currently running
            if self._is_running(stream_id):
                continue

            # Skip if complete
            status = self._get_stream_status(stream_id)
            if status and status["is_complete"]:
                continue

            # Skip if dependencies not met
            if not self._are_dependencies_complete(stream_id):
                continue

            # Check if there's evidence of prior execution
            log_file = self._get_log_file(stream_id)
            if log_file.exists() and log_file.stat().st_size > 100:
                # Worker ran but died - has incomplete tasks
                if status and (status["completed_tasks"] > 0 or status["in_progress_tasks"] > 0):
                    dead_workers.append(stream_id)
                elif status and status["total_tasks"] > 0:
                    # Had tasks but no progress - likely died early
                    dead_workers.append(stream_id)

        return dead_workers

    def _build_prompt(self, stream: dict) -> str:
        """Build the prompt for a Claude Code worker."""
        dependencies = self.stream_dependencies.get(stream['id'], set())
        deps_str = ", ".join(dependencies) if dependencies else "None"

        return f"""You are a worker agent in the Claude Copilot orchestration system.

## Your Assignment
- Stream: {stream['id']}
- Stream Name: {stream['name']}
- Dependencies: {deps_str}

## MANDATORY PROTOCOL - YOU MUST FOLLOW THIS EXACTLY

### Step 1: Query Your Tasks
Call `task_list` with streamId filter to get your assigned tasks:
```
task_list(metadata.streamId="{stream['id']}")
```

### Step 2: For EACH Task (in order)

**Before starting work:**
```
task_update(id="TASK-xxx", status="in_progress")
```

**After completing work:**
```
task_update(id="TASK-xxx", status="completed", notes="Brief description of what was done")
```

**CRITICAL:** You MUST call task_update after EACH task. Do not batch updates.

### Step 3: Verify Before Exiting

**Before outputting any completion summary:**
1. Call `task_list(metadata.streamId="{stream['id']}")` again
2. Check that ALL tasks have `status: "completed"`
3. If ANY task is still `pending` or `in_progress`, go back and complete it
4. Only after verification passes, output your summary

### Step 4: Output Summary
Only after ALL tasks are verified complete in Task Copilot, output:
- List of completed tasks with brief notes
- Any commits made
- Any issues encountered

## CRITICAL RULES
- DO NOT claim "complete" without verifying in Task Copilot first
- DO NOT skip task_update calls - they are MANDATORY
- If task_update fails, retry or report the error - do not proceed silently
- Stay focused on {stream['id']} tasks only
- Commit after each significant change
- If blocked, call task_update with status="blocked" and blockedReason

## Anti-Patterns (NEVER DO THESE)
- Outputting "All tasks complete" without calling task_update for each
- Skipping verification step before exit
- Claiming success when Task Copilot shows pending tasks

Begin by querying your task list with task_list.
"""

    def restart_worker(self, stream_id: str) -> bool:
        """Restart a dead worker using worker-wrapper.sh."""
        if stream_id not in self.streams:
            error(f"Stream '{stream_id}' not found")
            return False

        stream = self.streams[stream_id]

        # Check restart limit
        if self.restart_counts[stream_id] >= self.max_restarts:
            error(f"Worker {stream_id} has reached max restart limit ({self.max_restarts})")
            return False

        # Increment restart count
        self.restart_counts[stream_id] += 1

        # Determine working directory
        if stream["worktree"] == ".":
            work_dir = PROJECT_ROOT
        else:
            work_dir = PROJECT_ROOT / stream["worktree"]

        if not work_dir.exists():
            work_dir.mkdir(parents=True, exist_ok=True)

        log_message(f"Restarting worker {stream_id} (attempt {self.restart_counts[stream_id]}/{self.max_restarts})")

        prompt = self._build_prompt(stream)
        pid_file = PID_DIR / f"{stream_id}.pid"
        wrapper_script = SCRIPT_DIR / "worker-wrapper.sh"

        # Spawn via wrapper script
        proc = subprocess.Popen(
            [
                str(wrapper_script),
                stream_id,
                str(pid_file),
                str(LOG_DIR),
                str(work_dir),
                self.initiative_id,
                prompt
            ],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Give wrapper a moment to write PID file
        time.sleep(0.5)

        # Read actual PID from file
        if pid_file.exists():
            actual_pid = pid_file.read_text().strip()
            success(f"Worker {stream_id} restarted (PID: {actual_pid})")
            return True
        else:
            error(f"Failed to restart worker {stream_id} - no PID file created")
            return False

    def check_once(self) -> dict:
        """Perform one-shot check for dead workers.

        Returns:
            dict with dead_workers list and restart_performed bool
        """
        if not self.streams:
            return {"dead_workers": [], "restart_performed": False}

        dead_workers = self._detect_dead_workers()

        if not dead_workers:
            log_message("All workers healthy")
            return {"dead_workers": [], "restart_performed": False}

        warn(f"Found {len(dead_workers)} dead worker(s): {', '.join(dead_workers)}")

        restart_performed = False
        if self.auto_restart:
            for stream_id in dead_workers:
                if self.restart_worker(stream_id):
                    restart_performed = True
        else:
            log_message("Auto-restart disabled. Use --auto-restart to enable.")

        return {
            "dead_workers": dead_workers,
            "restart_performed": restart_performed
        }

    def run_daemon(self, interval: int = DEFAULT_CHECK_INTERVAL):
        """Run as background daemon with periodic checks."""
        log_message(f"Starting monitor daemon (interval: {interval}s, max_restarts: {self.max_restarts})")

        # Signal handlers for graceful shutdown
        def signal_handler(sig, frame):
            log_message("Received shutdown signal")
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        while True:
            try:
                self.check_once()
                time.sleep(interval)
            except Exception as e:
                error(f"Error in monitor loop: {e}")
                time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(
        description="Monitor and auto-restart dead worker processes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python monitor-workers.py                       # One-shot check
  python monitor-workers.py --auto-restart        # Background daemon
  python monitor-workers.py --auto-restart --max-restarts 3
  python monitor-workers.py --daemon --interval 60
        """
    )

    parser.add_argument(
        "--auto-restart",
        action="store_true",
        help="Enable automatic restart of dead workers"
    )

    parser.add_argument(
        "--max-restarts",
        type=int,
        default=DEFAULT_MAX_RESTARTS,
        help=f"Maximum restart attempts per worker (default: {DEFAULT_MAX_RESTARTS})"
    )

    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as background daemon (continuous monitoring)"
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_CHECK_INTERVAL,
        help=f"Check interval in seconds for daemon mode (default: {DEFAULT_CHECK_INTERVAL})"
    )

    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Quiet mode - only output when action is taken (for integration with watch-status)"
    )

    args = parser.parse_args()

    # In quiet mode, suppress all output unless there's an action
    if args.quiet:
        import io
        sys.stdout = io.StringIO()

    # Create monitor instance
    monitor = WorkerMonitor(
        max_restarts=args.max_restarts,
        auto_restart=args.auto_restart
    )

    # Run daemon or one-shot check
    if args.daemon:
        if not args.auto_restart:
            warn("Daemon mode without --auto-restart will only report dead workers")
        monitor.run_daemon(interval=args.interval)
    else:
        result = monitor.check_once()

        # Exit with error code if dead workers found
        if result["dead_workers"]:
            sys.exit(1)


if __name__ == "__main__":
    main()
