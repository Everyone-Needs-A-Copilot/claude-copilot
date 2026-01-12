#!/usr/bin/env python3
"""
Claude Copilot Orchestrator - Fully Dynamic Version

Spawns and manages multiple headless Claude Code sessions for parallel stream execution.
All stream information and dependencies are queried from Task Copilot SQLite database.

NO HARDCODED PHASES - Streams define their own dependencies, execution is fully dynamic.

Usage:
    python orchestrate.py start          # Start all streams (respects dependencies)
    python orchestrate.py start Stream-C # Start specific stream
    python orchestrate.py status         # Check status of all streams
    python orchestrate.py stop           # Stop all running streams
    python orchestrate.py logs Stream-A  # Tail logs for a stream
"""

import json
import subprocess
import os
import sys
import time
import signal
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Set
from collections import defaultdict

# Import Task Copilot client
from task_copilot_client import TaskCopilotClient

# Configuration
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # Go up from .claude/orchestrator to project root
PROJECT_NAME = PROJECT_ROOT.name  # Auto-detect from directory name
LOG_DIR = SCRIPT_DIR / "logs"
PID_DIR = SCRIPT_DIR / "pids"
POLL_INTERVAL = 30  # seconds

# Task Copilot workspace ID - auto-detect from project name
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
    NC = '\033[0m'  # No Color


def log(msg: str, color: str = Colors.BLUE):
    print(f"{color}[ORCHESTRATOR]{Colors.NC} {msg}")


def success(msg: str):
    print(f"{Colors.GREEN}[SUCCESS]{Colors.NC} {msg}")


def warn(msg: str):
    print(f"{Colors.YELLOW}[WARNING]{Colors.NC} {msg}")


def error(msg: str):
    print(f"{Colors.RED}[ERROR]{Colors.NC} {msg}")


class Orchestrator:
    def __init__(self):
        # Initialize Task Copilot client
        self.tc_client = TaskCopilotClient(WORKSPACE_ID)

        self.streams = self._query_streams()
        self.stream_dependencies = self._build_dependency_graph()
        self.dependency_depth = self._calculate_dependency_depth()
        self.running_processes: Dict[str, subprocess.Popen] = {}

        # Ensure directories exist
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        PID_DIR.mkdir(parents=True, exist_ok=True)

    def _query_streams(self) -> Dict[str, dict]:
        """Query streams dynamically using Task Copilot client."""
        try:
            stream_infos = self.tc_client.stream_list()

            if not stream_infos:
                error("No streams found in Task Copilot database")
                sys.exit(1)

            streams = {}
            for stream_info in stream_infos:
                # All parallel streams use worktrees, main stream uses project root
                worktree = "." if stream_info.stream_id == "main" else f".claude/worktrees/{stream_info.stream_id}"

                streams[stream_info.stream_id] = {
                    "id": stream_info.stream_id,
                    "name": stream_info.stream_name,
                    "dependencies": stream_info.dependencies,
                    "worktree": worktree,
                }

            log(f"Found {len(streams)} streams")
            return streams

        except FileNotFoundError as e:
            error(str(e))
            sys.exit(1)
        except Exception as e:
            error(f"Failed to query streams: {e}")
            sys.exit(1)

    def _build_dependency_graph(self) -> Dict[str, Set[str]]:
        """Build stream dependency graph from task metadata.

        Returns a dict mapping stream_id -> set of stream_ids it depends on.
        """
        dependency_graph: Dict[str, Set[str]] = defaultdict(set)

        for stream_id, stream in self.streams.items():
            dependencies = stream.get("dependencies", [])

            for dep in dependencies:
                # Dependencies can be streamIds or task titles
                # If it matches a stream ID, use it directly
                if dep in self.streams:
                    dependency_graph[stream_id].add(dep)
                else:
                    # Try to extract stream ID from task title format
                    # Common formats: "Stream-A: Task", "[Stream-A] Task", etc.
                    for sid in self.streams.keys():
                        if dep.startswith(f"{sid}:") or dep.startswith(f"[{sid}]"):
                            dependency_graph[stream_id].add(sid)
                            break

        return dependency_graph

    def _calculate_dependency_depth(self) -> Dict[str, int]:
        """Calculate the dependency depth for each stream.

        Depth 0: No dependencies
        Depth 1: Depends only on depth-0 streams
        Depth N: Depends on at least one depth-(N-1) stream
        """
        depths: Dict[str, int] = {}
        remaining = set(self.streams.keys())
        current_depth = 0

        while remaining:
            # Find streams where all dependencies are satisfied
            ready = set()
            for stream_id in remaining:
                deps = self.stream_dependencies.get(stream_id, set())
                if all(dep in depths for dep in deps):
                    ready.add(stream_id)

            if not ready:
                # Circular dependency detected
                warn(f"Circular dependency detected in streams: {remaining}")
                # Assign remaining to current depth to break the cycle
                for stream_id in remaining:
                    depths[stream_id] = current_depth
                break

            # Assign depth to ready streams
            for stream_id in ready:
                deps = self.stream_dependencies.get(stream_id, set())
                if deps:
                    max_dep_depth = max(depths[dep] for dep in deps)
                    depths[stream_id] = max_dep_depth + 1
                else:
                    depths[stream_id] = 0
                remaining.remove(stream_id)

            current_depth += 1

        return depths

    def _get_stream_status(self, stream_id: str) -> Optional[dict]:
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
        """Check if all dependencies for a stream are complete.

        A stream is ready when ALL streams it depends on have 100% tasks completed.
        """
        dependencies = self.stream_dependencies.get(stream_id, set())

        if not dependencies:
            # No dependencies, always ready
            return True

        # Check each dependency
        for dep_stream_id in dependencies:
            status = self._get_stream_status(dep_stream_id)
            if not status or not status["is_complete"]:
                return False

        return True

    def _get_ready_streams(self) -> List[str]:
        """Get list of streams that are ready to start (dependencies complete, not running, not complete)."""
        ready = []
        for stream_id in self.streams.keys():
            # Skip if already running
            if self._is_running(stream_id):
                continue

            # Skip if already complete
            status = self._get_stream_status(stream_id)
            if status and status["is_complete"]:
                continue

            # Check if dependencies are complete
            if self._are_dependencies_complete(stream_id):
                ready.append(stream_id)

        return ready

    def _get_blocked_streams(self) -> Dict[str, List[str]]:
        """Get streams that are blocked and what they're blocked by.

        Returns dict mapping stream_id -> list of incomplete dependency stream_ids
        """
        blocked = {}
        for stream_id in self.streams.keys():
            # Skip if already running or complete
            if self._is_running(stream_id):
                continue

            status = self._get_stream_status(stream_id)
            if status and status["is_complete"]:
                continue

            # Check dependencies
            dependencies = self.stream_dependencies.get(stream_id, set())
            incomplete_deps = []
            for dep_stream_id in dependencies:
                dep_status = self._get_stream_status(dep_stream_id)
                if not dep_status or not dep_status["is_complete"]:
                    incomplete_deps.append(dep_stream_id)

            if incomplete_deps:
                blocked[stream_id] = incomplete_deps

        return blocked

    def _preflight_check_agent_assignments(self) -> bool:
        """Pre-flight check for non-'me' agent assignments.

        Workers run as 'me' agent, so tasks assigned to other agents will be skipped.
        This check warns about such tasks and offers to auto-reassign them.

        Returns:
            True if check passes (no issues or user chose to continue)
            False if user chose to abort
        """
        non_me_tasks = self.tc_client.get_non_me_agent_tasks()

        if not non_me_tasks:
            return True

        # Group by stream for cleaner display
        by_stream: Dict[str, List[dict]] = defaultdict(list)
        for task in non_me_tasks:
            by_stream[task['stream_id']].append(task)

        print()
        warn(f"Found {len(non_me_tasks)} task(s) assigned to non-'me' agents:")
        print()

        for stream_id, tasks in sorted(by_stream.items()):
            print(f"  {Colors.CYAN}{stream_id}:{Colors.NC}")
            for task in tasks:
                title = task['title'][:50] + '...' if len(task['title']) > 50 else task['title']
                print(f"    • {title} → {Colors.YELLOW}@{task['assigned_agent']}{Colors.NC}")
        print()

        warn("Workers run as @agent-me and will SKIP these tasks.")
        print()
        print(f"  {Colors.BOLD}[r]{Colors.NC} Reassign all to 'me' and continue")
        print(f"  {Colors.BOLD}[c]{Colors.NC} Continue anyway (tasks will be skipped)")
        print(f"  {Colors.BOLD}[a]{Colors.NC} Abort")
        print()

        try:
            choice = input(f"  Choice [r/c/a]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            return False

        if choice == 'r':
            log("Reassigning tasks to 'me'...")
            reassigned = 0
            for task in non_me_tasks:
                if self.tc_client.reassign_task_to_me(task['id']):
                    reassigned += 1
                    title = task['title'][:40] + '...' if len(task['title']) > 40 else task['title']
                    log(f"  Reassigned: {title}")
            success(f"Reassigned {reassigned}/{len(non_me_tasks)} tasks")
            print()
            return True
        elif choice == 'c':
            warn("Continuing with non-'me' tasks (they will be skipped)")
            print()
            return True
        else:
            error("Aborted by user")
            return False

    def _get_pid_file(self, stream_id: str) -> Path:
        return PID_DIR / f"{stream_id}.pid"

    def _get_log_file(self, stream_id: str) -> Path:
        return LOG_DIR / f"{stream_id}.log"

    def _is_running(self, stream_id: str) -> bool:
        """Check if a stream worker is currently running."""
        pid_file = self._get_pid_file(stream_id)
        if not pid_file.exists():
            return False

        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)  # Check if process exists
            return True
        except (ProcessLookupError, ValueError):
            pid_file.unlink(missing_ok=True)
            return False

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

    def spawn_worker(self, stream_id: str, wait_for_deps: bool = True) -> bool:
        """Spawn a Claude Code worker for a stream."""
        if stream_id not in self.streams:
            error(f"Stream '{stream_id}' not found")
            return False

        stream = self.streams[stream_id]

        # Check if already running
        if self._is_running(stream_id):
            warn(f"Worker {stream_id} already running")
            return True

        # Check dependencies
        if wait_for_deps and not self._are_dependencies_complete(stream_id):
            dependencies = self.stream_dependencies.get(stream_id, set())
            warn(f"Dependencies not complete for {stream_id}: {', '.join(dependencies)}")
            return False

        # Determine working directory
        if stream["worktree"] == ".":
            work_dir = PROJECT_ROOT
        else:
            work_dir = PROJECT_ROOT / stream["worktree"]

        if not work_dir.exists():
            # Create worktree if needed
            log(f"Creating worktree for {stream_id}...")
            work_dir.mkdir(parents=True, exist_ok=True)

        dependencies = self.stream_dependencies.get(stream_id, set())
        deps_str = f" (depends on: {', '.join(dependencies)})" if dependencies else " (no dependencies)"

        log(f"Spawning worker for {stream_id}")
        log(f"  Name: {stream['name']}")
        log(f"  Dependencies: {deps_str}")
        log(f"  Working dir: {work_dir}")

        prompt = self._build_prompt(stream)
        log_file = self._get_log_file(stream_id)
        pid_file = self._get_pid_file(stream_id)

        # Spawn Claude Code headlessly
        with open(log_file, "a") as log_f:
            log_f.write(f"\n{'='*60}\n")
            log_f.write(f"Started: {datetime.now().isoformat()}\n")
            log_f.write(f"Stream: {stream_id}\n")
            log_f.write(f"Name: {stream['name']}\n")
            log_f.write(f"Dependencies: {deps_str}\n")
            log_f.write(f"{'='*60}\n\n")

            proc = subprocess.Popen(
                ["claude", "--print", "--dangerously-skip-permissions", "-p", prompt],
                cwd=work_dir,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                start_new_session=True  # Detach from parent
            )

        # Save PID
        pid_file.write_text(str(proc.pid))
        self.running_processes[stream_id] = proc

        success(f"Worker {stream_id} started (PID: {proc.pid})")
        success(f"Logs: {log_file}")
        return True

    def start_all(self):
        """Start all streams respecting dependencies dynamically.

        This method continuously polls for ready streams and spawns workers.
        No hardcoded phases - everything is determined by dependency graph.
        """
        log(f"Starting dynamic orchestration for {PROJECT_NAME}")
        print()

        # Pre-flight check: warn about non-'me' agent assignments
        if not self._preflight_check_agent_assignments():
            sys.exit(1)

        # Display dependency structure
        self._display_dependency_structure()
        print()

        # Track which streams we've attempted to start
        attempted = set()

        # Main execution loop
        while True:
            # Find streams that are ready to start
            ready_streams = self._get_ready_streams()

            # Filter out streams we've already attempted
            new_ready = [s for s in ready_streams if s not in attempted]

            if new_ready:
                log(f"Found {len(new_ready)} ready streams: {', '.join(new_ready)}")
                for stream_id in new_ready:
                    self.spawn_worker(stream_id, wait_for_deps=False)
                    attempted.add(stream_id)
                    print()

            # Check if all streams are complete
            all_complete = True
            for stream_id in self.streams.keys():
                status = self._get_stream_status(stream_id)
                if not status or not status["is_complete"]:
                    all_complete = False
                    break

            if all_complete:
                success("All streams complete!")
                break

            # Check if we're stuck (nothing ready, nothing running, not all complete)
            running_count = sum(1 for s in self.streams.keys() if self._is_running(s))
            if not new_ready and running_count == 0 and not all_complete:
                error("Orchestration stuck - no streams ready and none running")
                blocked = self._get_blocked_streams()
                if blocked:
                    error("Blocked streams:")
                    for stream_id, deps in blocked.items():
                        error(f"  {stream_id} waiting for: {', '.join(deps)}")
                break

            # Wait before next poll
            if not all_complete:
                time.sleep(POLL_INTERVAL)

        print()
        log("Orchestration complete")
        log("Use 'python orchestrate.py status' to check final status")

    def _display_dependency_structure(self):
        """Display stream dependency structure grouped by depth."""
        print(f"{Colors.BOLD}Stream Dependency Structure:{Colors.NC}")
        print()

        # Group by depth
        depths = defaultdict(list)
        for stream_id, depth in self.dependency_depth.items():
            depths[depth].append(stream_id)

        # Display each depth level
        for depth in sorted(depths.keys()):
            stream_ids = sorted(depths[depth])

            if depth == 0:
                print(f"  {Colors.GREEN}Depth {depth} (Independent):{Colors.NC}")
            else:
                print(f"  {Colors.CYAN}Depth {depth}:{Colors.NC}")

            for stream_id in stream_ids:
                stream = self.streams[stream_id]
                deps = self.stream_dependencies.get(stream_id, set())

                if deps:
                    deps_str = f" → depends on: {', '.join(sorted(deps))}"
                else:
                    deps_str = ""

                print(f"    • {Colors.BOLD}{stream_id}{Colors.NC} ({stream['name']}){deps_str}")

            print()

    def check_status(self):
        """Display status of all workers grouped by dependency depth."""
        print(f"\n{Colors.BOLD}{'='*75}{Colors.NC}")
        print(f"{Colors.BOLD}              {PROJECT_NAME.upper()} - WORKER STATUS{Colors.NC}")
        print(f"{Colors.BOLD}{'='*75}{Colors.NC}\n")

        # Group streams by dependency depth
        depths = defaultdict(list)
        for stream_id, depth in self.dependency_depth.items():
            depths[depth].append(stream_id)

        # Display overall progress
        total_streams = len(self.streams)
        completed_streams = 0
        running_streams = 0

        for stream_id in self.streams.keys():
            status = self._get_stream_status(stream_id)
            if status and status["is_complete"]:
                completed_streams += 1
            if self._is_running(stream_id):
                running_streams += 1

        print(f"  {Colors.BOLD}Overall:{Colors.NC} {completed_streams}/{total_streams} complete, {running_streams} running")
        print()

        # Display each depth level
        for depth in sorted(depths.keys()):
            stream_ids = sorted(depths[depth])

            if depth == 0:
                depth_label = f"Depth {depth} (Independent)"
            else:
                depth_label = f"Depth {depth}"

            print(f"  {Colors.MAGENTA}{depth_label}{Colors.NC}")

            for stream_id in stream_ids:
                stream = self.streams[stream_id]
                running = self._is_running(stream_id)
                status = self._get_stream_status(stream_id)

                # Determine status icon
                if status and status["is_complete"]:
                    icon = f"{Colors.GREEN}[DONE]{Colors.NC}"
                    status_text = "Complete"
                elif running:
                    icon = f"{Colors.YELLOW}[RUN]{Colors.NC}"
                    status_text = "Running"
                else:
                    # Check if blocked by dependencies
                    if not self._are_dependencies_complete(stream_id):
                        icon = f"{Colors.CYAN}[WAIT]{Colors.NC}"
                        deps = self.stream_dependencies.get(stream_id, set())
                        status_text = f"Waiting for: {', '.join(sorted(deps))}"
                    else:
                        pid_file = self._get_pid_file(stream_id)
                        if pid_file.exists():
                            icon = f"{Colors.RED}[STOP]{Colors.NC}"
                            status_text = "Stopped"
                        else:
                            icon = f"{Colors.DIM}[---]{Colors.NC}"
                            status_text = "Not started"

                # Progress bar
                if status and status["total_tasks"] > 0:
                    pct = int(status["completed_tasks"] / status["total_tasks"] * 100)
                    bar_filled = pct // 7
                    bar = "=" * bar_filled + "-" * (15 - bar_filled)
                    progress = f"[{bar}] {status['completed_tasks']}/{status['total_tasks']}"
                else:
                    progress = "[---------------] ?/?"

                # Get PID if running
                pid_str = ""
                if running:
                    pid_file = self._get_pid_file(stream_id)
                    if pid_file.exists():
                        pid_str = f" (PID: {pid_file.read_text().strip()})"

                print(f"    {icon} {Colors.BOLD}{stream_id}{Colors.NC} | {stream['name']}")
                print(f"      {progress} | {status_text}{pid_str}")
            print()

        # Show blocked streams summary
        blocked = self._get_blocked_streams()
        if blocked:
            print(f"  {Colors.YELLOW}Blocked Streams:{Colors.NC}")
            for stream_id, deps in blocked.items():
                print(f"    • {stream_id} waiting for: {', '.join(sorted(deps))}")
            print()

    def stop_all(self):
        """Stop all running workers."""
        log("Stopping all workers...")

        for pid_file in PID_DIR.glob("*.pid"):
            stream_id = pid_file.stem
            try:
                pid = int(pid_file.read_text().strip())
                os.kill(pid, signal.SIGTERM)
                log(f"Stopped {stream_id} (PID: {pid})")
            except (ProcessLookupError, ValueError):
                pass
            pid_file.unlink(missing_ok=True)

        success("All workers stopped")

    def stop_one(self, stream_id: str):
        """Stop a specific worker."""
        pid_file = self._get_pid_file(stream_id)
        if not pid_file.exists():
            warn(f"No PID file for {stream_id}")
            return

        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            log(f"Stopped {stream_id} (PID: {pid})")
        except (ProcessLookupError, ValueError):
            warn(f"Process not found for {stream_id}")

        pid_file.unlink(missing_ok=True)

    def tail_logs(self, stream_id: str):
        """Tail logs for a stream."""
        log_file = self._get_log_file(stream_id)
        if not log_file.exists():
            error(f"No logs found for {stream_id}")
            return

        subprocess.run(["tail", "-f", str(log_file)])


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Claude Copilot Orchestrator")
    parser.add_argument("command", choices=["start", "status", "stop", "logs"],
                       help="Command to run")
    parser.add_argument("stream_id", nargs="?", help="Stream ID (for start/stop/logs)")

    args = parser.parse_args()

    orchestrator = Orchestrator()

    if args.command == "start":
        if args.stream_id:
            orchestrator.spawn_worker(args.stream_id)
        else:
            orchestrator.start_all()
    elif args.command == "status":
        orchestrator.check_status()
    elif args.command == "stop":
        if args.stream_id:
            orchestrator.stop_one(args.stream_id)
        else:
            orchestrator.stop_all()
    elif args.command == "logs":
        if not args.stream_id:
            error("Usage: orchestrate.py logs <stream-id>")
            sys.exit(1)
        orchestrator.tail_logs(args.stream_id)


if __name__ == "__main__":
    main()
