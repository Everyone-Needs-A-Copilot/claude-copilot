#!/usr/bin/env python3
"""
Task Copilot Client - Abstraction layer for Task Copilot data access

This module provides a clean interface to Task Copilot data, abstracting
away the underlying storage mechanism (SQLite database).

Future: Can be replaced with MCP API calls when Task Copilot MCP server is available.
"""

import sqlite3
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

    def _connect(self) -> sqlite3.Connection:
        """Create database connection with timeout"""
        if not self.db_path.exists():
            raise FileNotFoundError(f"Task Copilot database not found: {self.db_path}")

        return sqlite3.connect(str(self.db_path), timeout=5)

    def stream_list(self) -> List[StreamInfo]:
        """
        Get list of all streams with their metadata.

        Returns:
            List of StreamInfo objects

        Raises:
            FileNotFoundError: If database doesn't exist
            sqlite3.Error: If query fails
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
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

    def stream_get(self, stream_id: str) -> Optional[StreamProgress]:
        """
        Get progress information for a specific stream.

        Args:
            stream_id: Stream identifier

        Returns:
            StreamProgress object or None if stream not found

        Raises:
            FileNotFoundError: If database doesn't exist
            sqlite3.Error: If query fails
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
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

    def progress_summary(self) -> ProgressSummary:
        """
        Get overall progress summary across all streams.

        Returns:
            ProgressSummary object

        Raises:
            FileNotFoundError: If database doesn't exist
            sqlite3.Error: If query fails
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()

            # Get overall task counts
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

            # Get stream counts
            streams = self.stream_list()
            stream_count = len(streams)
            completed_stream_count = 0

            for stream_info in streams:
                progress = self.stream_get(stream_info.stream_id)
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
