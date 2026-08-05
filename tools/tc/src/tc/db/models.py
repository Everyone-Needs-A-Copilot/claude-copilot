"""TypedDict row types for Task Copilot database tables."""

from typing import Optional, TypedDict


class PrdRow(TypedDict):
    id: int
    title: str
    description: Optional[str]
    content: Optional[str]
    status: str
    created_at: str
    updated_at: str


class StreamRow(TypedDict):
    id: int
    name: str
    prd_id: Optional[int]
    status: str
    worktree_path: Optional[str]
    created_at: str
    updated_at: str


class TaskRow(TypedDict):
    id: int
    prd_id: Optional[int]
    stream_id: Optional[int]
    title: str
    description: Optional[str]
    status: str
    agent: Optional[str]
    claimed_by: Optional[str]
    claimed_at: Optional[str]
    priority: int
    parent_task_id: Optional[int]
    metadata: Optional[str]
    created_at: str
    updated_at: str


class WorkProductRow(TypedDict):
    id: int
    task_id: Optional[int]
    type: str
    title: str
    content: Optional[str]
    file_path: Optional[str]
    agent: Optional[str]
    created_at: str


class AgentLogRow(TypedDict):
    id: int
    agent: str
    stream_id: Optional[int]
    task_id: Optional[int]
    action: str
    details: Optional[str]
    created_at: str


class TaskDependencyRow(TypedDict):
    task_id: int
    depends_on: int
