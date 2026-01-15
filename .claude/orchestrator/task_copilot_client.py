#!/usr/bin/env python3
"""
Task Copilot Client - Abstraction layer for Task Copilot data access

This module provides a clean interface to Task Copilot data, abstracting
away the underlying storage mechanism (SQLite database).

Future: Can be replaced with MCP API calls when Task Copilot MCP server is available.
"""

import sqlite3
import json
from pathlib import Path
from typing import Dict, List, Optional, Set
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


class TaskCopilotClient:
    """
    Client for accessing Task Copilot data.

    Currently uses direct SQLite access. Can be refactored to use MCP API
    when Task Copilot MCP server becomes available.
    """

    def __init__(self, workspace_id: str):
        """
        Initialize Task Copilot client.

        Args:
            workspace_id: Workspace identifier (typically project folder name)
        """
        self.workspace_id = workspace_id
        self.db_path = Path.home() / ".claude" / "tasks" / workspace_id / "tasks.db"
        self.memory_db_path = Path.home() / ".claude" / "memory" / workspace_id / "memory.db"

    def _connect(self) -> sqlite3.Connection:
        """Create database connection with timeout"""
        if not self.db_path.exists():
            raise FileNotFoundError(f"Task Copilot database not found: {self.db_path}")

        return sqlite3.connect(str(self.db_path), timeout=5)

    def stream_list(self, initiative_id: Optional[str] = None) -> List[StreamInfo]:
        """
        Get list of all streams with their metadata.

        Args:
            initiative_id: Optional initiative ID to filter streams by

        Returns:
            List of StreamInfo objects

        Raises:
            FileNotFoundError: If database doesn't exist
            sqlite3.Error: If query fails
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()

            # Build query with optional initiative filter
            if initiative_id:
                cursor.execute("""
                    SELECT
                        json_extract(t.metadata, '$.streamId') as stream_id,
                        MIN(json_extract(t.metadata, '$.streamName')) as stream_name,
                        MIN(json_extract(t.metadata, '$.dependencies')) as dependencies_json
                    FROM tasks t
                    LEFT JOIN prds p ON t.prd_id = p.id
                    WHERE json_extract(t.metadata, '$.streamId') IS NOT NULL
                      AND t.archived = 0
                      AND p.initiative_id = ?
                    GROUP BY json_extract(t.metadata, '$.streamId')
                    ORDER BY stream_id
                """, (initiative_id,))
            else:
                cursor.execute("""
                    SELECT
                        json_extract(metadata, '$.streamId') as stream_id,
                        MIN(json_extract(metadata, '$.streamName')) as stream_name,
                        MIN(json_extract(metadata, '$.dependencies')) as dependencies_json
                    FROM tasks
                    WHERE json_extract(metadata, '$.streamId') IS NOT NULL
                      AND archived = 0
                    GROUP BY json_extract(metadata, '$.streamId')
                    ORDER BY stream_id
                """)

            streams = []
            for stream_id, stream_name, dependencies_json in cursor.fetchall():
                # Parse dependencies from JSON
                dependencies = []
                if dependencies_json:
                    try:
                        import json
                        deps = json.loads(dependencies_json)
                        if isinstance(deps, list):
                            dependencies = deps
                    except (json.JSONDecodeError, TypeError):
                        pass

                streams.append(StreamInfo(
                    stream_id=stream_id,
                    stream_name=stream_name or stream_id,
                    dependencies=dependencies
                ))

            return streams
        finally:
            conn.close()

    def stream_get(self, stream_id: str, initiative_id: Optional[str] = None) -> Optional[StreamProgress]:
        """
        Get progress information for a specific stream.

        Args:
            stream_id: Stream identifier
            initiative_id: Optional initiative ID to filter by

        Returns:
            StreamProgress object or None if stream not found

        Raises:
            FileNotFoundError: If database doesn't exist
            sqlite3.Error: If query fails
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()

            if initiative_id:
                cursor.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END) as completed,
                        SUM(CASE WHEN t.status = 'in_progress' THEN 1 ELSE 0 END) as in_progress,
                        SUM(CASE WHEN t.status = 'pending' THEN 1 ELSE 0 END) as pending,
                        SUM(CASE WHEN t.status = 'blocked' THEN 1 ELSE 0 END) as blocked
                    FROM tasks t
                    LEFT JOIN prds p ON t.prd_id = p.id
                    WHERE json_extract(t.metadata, '$.streamId') = ?
                      AND t.archived = 0
                      AND p.initiative_id = ?
                """, (stream_id, initiative_id))
            else:
                cursor.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                        SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as in_progress,
                        SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                        SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END) as blocked
                    FROM tasks
                    WHERE json_extract(metadata, '$.streamId') = ?
                      AND archived = 0
                """, (stream_id,))

            row = cursor.fetchone()
            if not row or row[0] == 0:
                return None

            total, completed, in_progress, pending, blocked = row

            return StreamProgress(
                stream_id=stream_id,
                total_tasks=total or 0,
                completed_tasks=completed or 0,
                in_progress_tasks=in_progress or 0,
                pending_tasks=pending or 0,
                blocked_tasks=blocked or 0
            )
        finally:
            conn.close()

    def progress_summary(self, initiative_id: Optional[str] = None) -> ProgressSummary:
        """
        Get overall progress summary across all streams.

        Args:
            initiative_id: Optional initiative ID to filter by

        Returns:
            ProgressSummary object

        Raises:
            FileNotFoundError: If database doesn't exist
            sqlite3.Error: If query fails
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()

            # Get overall task counts with optional initiative filter
            if initiative_id:
                cursor.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END) as completed,
                        SUM(CASE WHEN t.status = 'in_progress' THEN 1 ELSE 0 END) as in_progress,
                        SUM(CASE WHEN t.status = 'pending' THEN 1 ELSE 0 END) as pending,
                        SUM(CASE WHEN t.status = 'blocked' THEN 1 ELSE 0 END) as blocked
                    FROM tasks t
                    LEFT JOIN prds p ON t.prd_id = p.id
                    WHERE json_extract(t.metadata, '$.streamId') IS NOT NULL
                      AND t.archived = 0
                      AND p.initiative_id = ?
                """, (initiative_id,))
            else:
                cursor.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                        SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as in_progress,
                        SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                        SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END) as blocked
                    FROM tasks
                    WHERE json_extract(metadata, '$.streamId') IS NOT NULL
                      AND archived = 0
                """)

            row = cursor.fetchone()
            total = row[0] or 0
            completed = row[1] or 0
            in_progress = row[2] or 0
            pending = row[3] or 0
            blocked = row[4] or 0

            # Get stream counts (pass initiative_id for consistency)
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
                completed_stream_count=completed_stream_count
            )
        finally:
            conn.close()

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
            Falls back to returning None if Memory Copilot database doesn't exist
            or is not accessible.
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

        Args:
            stream_id: Stream identifier
            status: Task status to filter by

        Returns:
            List of task dictionaries
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    id,
                    title,
                    status,
                    metadata
                FROM tasks
                WHERE json_extract(metadata, '$.streamId') = ?
                  AND status = ?
                  AND archived = 0
                ORDER BY created_at
            """, (stream_id, status.value))

            tasks = []
            for task_id, title, task_status, metadata in cursor.fetchall():
                tasks.append({
                    'id': task_id,
                    'title': title,
                    'status': task_status,
                    'metadata': metadata
                })

            return tasks
        finally:
            conn.close()

    def get_non_me_agent_tasks(self, initiative_id: Optional[str] = None) -> List[Dict]:
        """
        Get all tasks assigned to agents other than 'me'.

        Workers run as 'me' agent, so tasks assigned to other agents will be skipped.
        This method helps identify such tasks before starting orchestration.

        Args:
            initiative_id: Optional initiative ID to filter by

        Returns:
            List of task dictionaries with non-'me' agent assignments
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()

            if initiative_id:
                cursor.execute("""
                    SELECT
                        t.id,
                        t.title,
                        t.assigned_agent,
                        json_extract(t.metadata, '$.streamId') as stream_id
                    FROM tasks t
                    LEFT JOIN prds p ON t.prd_id = p.id
                    WHERE json_extract(t.metadata, '$.streamId') IS NOT NULL
                      AND t.archived = 0
                      AND p.initiative_id = ?
                      AND t.assigned_agent IS NOT NULL
                      AND t.assigned_agent != 'me'
                    ORDER BY json_extract(t.metadata, '$.streamId'), t.created_at
                """, (initiative_id,))
            else:
                cursor.execute("""
                    SELECT
                        id,
                        title,
                        assigned_agent,
                        json_extract(metadata, '$.streamId') as stream_id
                    FROM tasks
                    WHERE json_extract(metadata, '$.streamId') IS NOT NULL
                      AND archived = 0
                      AND assigned_agent IS NOT NULL
                      AND assigned_agent != 'me'
                    ORDER BY json_extract(metadata, '$.streamId'), created_at
                """)

            tasks = []
            for task_id, title, agent, stream_id in cursor.fetchall():
                tasks.append({
                    'id': task_id,
                    'title': title,
                    'assigned_agent': agent,
                    'stream_id': stream_id
                })

            return tasks
        finally:
            conn.close()

    def reassign_task_to_me(self, task_id: str) -> bool:
        """
        Reassign a task to 'me' agent.

        Args:
            task_id: Task ID to reassign

        Returns:
            True if successful, False otherwise
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE tasks
                SET assigned_agent = 'me',
                    updated_at = datetime('now')
                WHERE id = ?
            """, (task_id,))
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error:
            return False
        finally:
            conn.close()


# Convenience function for creating a client
def get_client(workspace_id: str) -> TaskCopilotClient:
    """
    Get a Task Copilot client instance.

    Args:
        workspace_id: Workspace identifier

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
