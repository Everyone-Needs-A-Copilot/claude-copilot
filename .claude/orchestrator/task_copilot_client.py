#!/usr/bin/env python3
"""
Task Copilot Client - Abstraction layer for Task Copilot data access

This module provides a clean interface to Task Copilot data using the `tc` CLI
tool for task/stream operations and direct SQLite access for Memory Copilot
queries (initiative management).

The `tc` CLI finds the project-local .copilot/tasks.db automatically by walking
up from cwd. Memory Copilot data lives at ~/.claude/memory/{workspace_id}/memory.db
and is accessed directly via SQLite.
"""

import json
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from enum import Enum


class TaskStatus(Enum):
    """Task status values"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass
class StreamInfo:
    """Stream information"""
    stream_id: str
    stream_name: str
    dependencies: List[str]

    def __repr__(self):
        return f"StreamInfo(id={self.stream_id}, name={self.stream_name}, deps={self.dependencies})"


@dataclass
class StreamProgress:
    """Stream progress statistics"""
    stream_id: str
    total_tasks: int
    completed_tasks: int
    in_progress_tasks: int
    pending_tasks: int
    blocked_tasks: int

    @property
    def is_complete(self) -> bool:
        """Check if stream is complete"""
        return self.total_tasks > 0 and self.completed_tasks >= self.total_tasks

    @property
    def completion_percentage(self) -> int:
        """Get completion percentage (0-100)"""
        if self.total_tasks == 0:
            return 0
        return int((self.completed_tasks / self.total_tasks) * 100)

    def __repr__(self):
        return f"StreamProgress(id={self.stream_id}, {self.completed_tasks}/{self.total_tasks} tasks, {self.completion_percentage}%)"


@dataclass
class ProgressSummary:
    """Overall progress summary across all streams"""
    total_tasks: int
    completed_tasks: int
    in_progress_tasks: int
    pending_tasks: int
    blocked_tasks: int
    stream_count: int
    completed_stream_count: int

    @property
    def completion_percentage(self) -> int:
        """Get overall completion percentage (0-100)"""
        if self.total_tasks == 0:
            return 0
        return int((self.completed_tasks / self.total_tasks) * 100)


@dataclass
class InitiativeDetails:
    """Initiative details from Memory Copilot"""
    id: str
    name: str
    goal: Optional[str]
    status: str


def _find_task_db_path() -> Optional[Path]:
    """Walk up from cwd to find .copilot/tasks.db.

    Returns:
        Path to the database file, or None if not found.
    """
    current = Path.cwd()
    while True:
        candidate = current / ".copilot" / "tasks.db"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


class TaskCopilotClient:
    """
    Client for accessing Task Copilot data.

    Uses the `tc` CLI tool for task and stream operations, ensuring consistent
    WAL-mode database handling. Memory Copilot queries (initiatives) use direct
    SQLite access since `tc` does not handle memory data.
    """

    def __init__(self, workspace_id: str):
        """
        Initialize Task Copilot client.

        Args:
            workspace_id: Workspace identifier (used for Memory Copilot DB path)
        """
        self.workspace_id = workspace_id
        self.memory_db_path = Path.home() / ".claude" / "memory" / workspace_id / "memory.db"
        # Expose db_path for callers that check database existence.
        # This points to the project-local .copilot/tasks.db found by walking
        # up from cwd, matching the same discovery logic used by the tc CLI.
        self._task_db_path: Optional[Path] = None

    @property
    def db_path(self) -> Path:
        """Path to the project-local task database.

        Lazily resolved on first access. Returns a Path that may or may not
        exist -- callers should check with .exists() before using.
        """
        if self._task_db_path is None:
            found = _find_task_db_path()
            if found is not None:
                self._task_db_path = found
            else:
                # Return a plausible default so .exists() returns False
                self._task_db_path = Path.cwd() / ".copilot" / "tasks.db"
        return self._task_db_path

    def _run_tc(self, *args: str) -> Any:
        """Run a tc CLI command and return parsed JSON output.

        Args:
            *args: Command arguments to pass to tc (--json is appended automatically).

        Returns:
            Parsed JSON output from the tc command.

        Raises:
            RuntimeError: If the tc command exits with a non-zero return code.
            FileNotFoundError: If the tc binary is not found on PATH.
        """
        cmd = ["tc"] + list(args) + ["--json"]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"tc command failed (exit {result.returncode}): {' '.join(cmd)}\n"
                f"{result.stderr.strip()}"
            )
        return json.loads(result.stdout)

    def _connect_task_db(self) -> sqlite3.Connection:
        """Create a connection to the project-local task database.

        Used only for operations that the tc CLI does not support
        (e.g., batch archive).

        Returns:
            sqlite3.Connection configured with WAL mode and busy timeout.

        Raises:
            FileNotFoundError: If no .copilot/tasks.db can be found.
        """
        path = _find_task_db_path()
        if path is None:
            raise FileNotFoundError(
                "No .copilot/tasks.db found. Run `tc init` to create a database."
            )
        conn = sqlite3.connect(str(path), timeout=5)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def stream_list(self, initiative_id: Optional[str] = None) -> List[StreamInfo]:
        """
        Get list of all streams with their metadata.

        Uses `tc stream list --json` to retrieve streams from the dedicated
        streams table. The initiative_id parameter is accepted for API
        compatibility but is not used for filtering since the new schema
        scopes streams at the project level.

        Args:
            initiative_id: Optional initiative ID (accepted for compatibility,
                not used for filtering in the new schema).

        Returns:
            List of StreamInfo objects

        Raises:
            RuntimeError: If tc command fails
            FileNotFoundError: If tc binary not found
        """
        data = self._run_tc("stream", "list")

        streams: List[StreamInfo] = []
        if not isinstance(data, list):
            return streams

        for row in data:
            stream_id = str(row.get("id", ""))
            stream_name = row.get("name", "") or stream_id

            # The new streams table does not have a dependencies column.
            # Return an empty list for API compatibility.
            dependencies: List[str] = []

            streams.append(StreamInfo(
                stream_id=stream_id,
                stream_name=stream_name,
                dependencies=dependencies,
            ))

        return streams

    def stream_get(self, stream_id: str, initiative_id: Optional[str] = None) -> Optional[StreamProgress]:
        """
        Get progress information for a specific stream.

        Uses `tc progress --stream <id> --json` to get per-stream task counts.

        Args:
            stream_id: Stream identifier
            initiative_id: Optional initiative ID (accepted for compatibility,
                not used for filtering in the new schema).

        Returns:
            StreamProgress object or None if stream has no tasks

        Raises:
            RuntimeError: If tc command fails
            FileNotFoundError: If tc binary not found
        """
        data = self._run_tc("progress", "--stream", str(stream_id))

        # The progress JSON has the structure:
        # {
        #   "by_stream": [{"stream_id": ..., "stream_name": ..., "counts": {...}}],
        #   "totals": {"pending": N, "in_progress": N, "completed": N, ...}
        # }
        totals = data.get("totals", {})
        if not totals:
            return None

        completed = totals.get("completed", 0)
        in_progress = totals.get("in_progress", 0)
        pending = totals.get("pending", 0)
        blocked = totals.get("blocked", 0)
        cancelled = totals.get("cancelled", 0)
        total = completed + in_progress + pending + blocked + cancelled

        if total == 0:
            return None

        return StreamProgress(
            stream_id=stream_id,
            total_tasks=total,
            completed_tasks=completed,
            in_progress_tasks=in_progress,
            pending_tasks=pending,
            blocked_tasks=blocked,
        )

    def progress_summary(self, initiative_id: Optional[str] = None) -> ProgressSummary:
        """
        Get overall progress summary across all streams.

        Uses `tc progress --json` for overall task counts and `tc stream list`
        plus per-stream progress checks for stream completion counts.

        Args:
            initiative_id: Optional initiative ID (accepted for compatibility,
                not used for filtering in the new schema).

        Returns:
            ProgressSummary object

        Raises:
            RuntimeError: If tc command fails
            FileNotFoundError: If tc binary not found
        """
        data = self._run_tc("progress")

        totals = data.get("totals", {})
        completed = totals.get("completed", 0)
        in_progress = totals.get("in_progress", 0)
        pending = totals.get("pending", 0)
        blocked = totals.get("blocked", 0)
        cancelled = totals.get("cancelled", 0)
        total = completed + in_progress + pending + blocked + cancelled

        # Count streams and completed streams
        streams = self.stream_list(initiative_id)
        stream_count = len(streams)
        completed_stream_count = 0

        for stream_info in streams:
            progress = self.stream_get(stream_info.stream_id, initiative_id)
            if progress and progress.is_complete:
                completed_stream_count += 1

        return ProgressSummary(
            total_tasks=total,
            completed_tasks=completed,
            in_progress_tasks=in_progress,
            pending_tasks=pending,
            blocked_tasks=blocked,
            stream_count=stream_count,
            completed_stream_count=completed_stream_count,
        )

    def get_active_initiative_id(self) -> Optional[str]:
        """
        Get the currently active initiative ID from Memory Copilot.

        An initiative is considered "active" if its status is:
        - IN PROGRESS (highest priority)
        - BLOCKED (second priority)
        - NOT STARTED (lowest priority)

        Returns:
            Initiative ID string or None if no active initiative

        Note:
            Uses direct SQLite access to the Memory Copilot database.
            Falls back to returning None if database doesn't exist or
            is not accessible.
        """
        if not self.memory_db_path.exists():
            return None

        try:
            conn = sqlite3.connect(str(self.memory_db_path), timeout=5)
            cursor = conn.cursor()

            # Query for active initiative - prioritize by status
            cursor.execute("""
                SELECT id FROM initiatives
                WHERE status IN ('IN PROGRESS', 'BLOCKED', 'NOT STARTED')
                ORDER BY
                    CASE status
                        WHEN 'IN PROGRESS' THEN 1
                        WHEN 'BLOCKED' THEN 2
                        WHEN 'NOT STARTED' THEN 3
                    END,
                    created_at DESC
                LIMIT 1
            """)

            row = cursor.fetchone()
            conn.close()
            return row[0] if row else None
        except sqlite3.Error:
            return None

    def get_initiative_details(self, initiative_id: str) -> Optional[InitiativeDetails]:
        """
        Get details about a specific initiative from Memory Copilot.

        Args:
            initiative_id: Initiative ID to look up

        Returns:
            InitiativeDetails object or None if not found

        Note:
            Uses direct SQLite access to the Memory Copilot database.
        """
        if not self.memory_db_path.exists():
            return None

        try:
            conn = sqlite3.connect(str(self.memory_db_path), timeout=5)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, name, goal, status
                FROM initiatives
                WHERE id = ?
            """, (initiative_id,))

            row = cursor.fetchone()
            conn.close()

            if not row:
                return None

            return InitiativeDetails(
                id=row[0],
                name=row[1] or "Unnamed Initiative",
                goal=row[2],
                status=row[3] or "UNKNOWN"
            )
        except sqlite3.Error:
            return None

    def get_stream_tasks_by_status(self, stream_id: str, status: TaskStatus) -> List[Dict]:
        """
        Get tasks for a stream filtered by status.

        Uses `tc task list --stream <id> --status <status> --json`.

        Args:
            stream_id: Stream identifier
            status: Task status to filter by

        Returns:
            List of task dictionaries with keys: id, title, status, metadata
        """
        data = self._run_tc(
            "task", "list",
            "--stream", str(stream_id),
            "--status", status.value,
        )

        tasks: List[Dict] = []
        if not isinstance(data, list):
            return tasks

        for row in data:
            tasks.append({
                "id": row.get("id"),
                "title": row.get("title"),
                "status": row.get("status"),
                "metadata": row.get("metadata"),
            })

        return tasks

    def get_non_me_agent_tasks(self, initiative_id: Optional[str] = None) -> List[Dict]:
        """
        Get all tasks assigned to agents other than 'me'.

        Workers run as 'me' agent, so tasks assigned to other agents will be
        skipped. This method helps identify such tasks before starting
        orchestration.

        Uses `tc task list --json` and filters client-side for tasks where
        agent is not null and agent != 'me'.

        Args:
            initiative_id: Optional initiative ID (accepted for compatibility,
                not used for filtering in the new schema).

        Returns:
            List of task dictionaries with keys: id, title, assigned_agent,
            stream_id
        """
        data = self._run_tc("task", "list")

        tasks: List[Dict] = []
        if not isinstance(data, list):
            return tasks

        for row in data:
            agent = row.get("agent")
            if agent is not None and agent != "me":
                tasks.append({
                    "id": row.get("id"),
                    "title": row.get("title"),
                    "assigned_agent": agent,
                    "stream_id": row.get("stream_id"),
                })

        return tasks

    def reassign_task_to_me(self, task_id: str) -> bool:
        """
        Reassign a task to 'me' agent.

        Uses `tc task update <id> --agent me --json`.

        Args:
            task_id: Task ID to reassign

        Returns:
            True if successful, False otherwise
        """
        try:
            self._run_tc("task", "update", str(task_id), "--agent", "me")
            return True
        except (RuntimeError, FileNotFoundError):
            return False

    def archive_initiative_streams(self, initiative_id: str) -> int:
        """
        Archive all tasks with a stream_id that belong to a specific initiative.

        This is called when an initiative completes to clean up stream tasks
        and prevent them from appearing in future orchestration runs.

        Uses direct SQLite access to the project-local .copilot/tasks.db
        because the tc CLI does not have a batch archive command.

        Args:
            initiative_id: Initiative ID whose streams should be archived

        Returns:
            Number of tasks archived

        Note:
            Archives tasks by setting status='archived' on streams and
            status='cancelled' on remaining non-completed tasks in those
            streams. Falls back to archiving all stream tasks if PRD-based
            filtering is not applicable.
        """
        try:
            conn = self._connect_task_db()
        except FileNotFoundError:
            return 0

        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            # Archive streams that belong to PRDs associated with this
            # initiative. The new schema does not have initiative_id on PRDs
            # directly, so we archive all active streams as a reasonable
            # fallback when completing an initiative.
            cursor.execute("""
                UPDATE streams
                SET status = 'archived',
                    updated_at = ?
                WHERE status IN ('active', 'paused')
            """, (now,))
            archived_streams = cursor.rowcount

            # Cancel non-completed tasks in those streams
            cursor.execute("""
                UPDATE tasks
                SET status = 'cancelled',
                    updated_at = ?
                WHERE stream_id IN (
                    SELECT id FROM streams WHERE status = 'archived'
                )
                AND status NOT IN ('completed', 'cancelled')
            """, (now,))
            archived_tasks = cursor.rowcount

            conn.commit()
            return archived_streams + archived_tasks
        except sqlite3.Error as e:
            print(f"Error archiving streams: {e}")
            return 0
        finally:
            conn.close()

    def complete_initiative(self, initiative_id: str, summary: Optional[str] = None) -> bool:
        """
        Mark an initiative as COMPLETE in Memory Copilot.

        This updates the initiative status to 'COMPLETE' and optionally
        sets a completion summary in the resume_instructions field.

        Args:
            initiative_id: Initiative ID to complete
            summary: Optional completion summary

        Returns:
            True if successful, False otherwise

        Note:
            This modifies the Memory Copilot database, not the Task Copilot database.
        """
        if not self.memory_db_path.exists():
            print(f"Memory Copilot database not found: {self.memory_db_path}")
            return False

        try:
            conn = sqlite3.connect(str(self.memory_db_path), timeout=5)
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            if summary:
                cursor.execute("""
                    UPDATE initiatives
                    SET status = 'COMPLETE',
                        resume_instructions = ?,
                        updated_at = ?
                    WHERE id = ?
                """, (summary, now, initiative_id))
            else:
                cursor.execute("""
                    UPDATE initiatives
                    SET status = 'COMPLETE',
                        updated_at = ?
                    WHERE id = ?
                """, (now, initiative_id))

            conn.commit()
            success = cursor.rowcount > 0
            conn.close()
            return success
        except sqlite3.Error as e:
            print(f"Error completing initiative: {e}")
            return False


# Convenience function for creating a client
def get_client(workspace_id: str) -> TaskCopilotClient:
    """
    Get a Task Copilot client instance.

    Args:
        workspace_id: Workspace identifier (used for Memory Copilot DB path)

    Returns:
        TaskCopilotClient instance
    """
    return TaskCopilotClient(workspace_id)


# Example usage
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python task_copilot_client.py <workspace_id>")
        sys.exit(1)

    workspace_id = sys.argv[1]
    client = get_client(workspace_id)

    print(f"Task Copilot Client - Workspace: {workspace_id}\n")

    try:
        # Get all streams
        print("=== Streams ===")
        streams = client.stream_list()
        for stream in streams:
            print(f"  {stream}")
        print()

        # Get progress for each stream
        print("=== Stream Progress ===")
        for stream in streams:
            progress = client.stream_get(stream.stream_id)
            if progress:
                print(f"  {progress}")
        print()

        # Get overall summary
        print("=== Overall Summary ===")
        summary = client.progress_summary()
        print(f"  Total Tasks: {summary.total_tasks}")
        print(f"  Completed: {summary.completed_tasks} ({summary.completion_percentage}%)")
        print(f"  In Progress: {summary.in_progress_tasks}")
        print(f"  Pending: {summary.pending_tasks}")
        print(f"  Blocked: {summary.blocked_tasks}")
        print(f"  Streams: {summary.completed_stream_count}/{summary.stream_count} complete")

    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
