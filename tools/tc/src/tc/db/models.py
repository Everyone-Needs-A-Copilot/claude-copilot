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


class SolutionRow(TypedDict):
    id: int
    title: str
    beneficiary: Optional[str]
    repo_path: Optional[str]
    components_used: Optional[str]
    brief: Optional[str]
    brief_locked_at: Optional[str]
    status: str
    started_at: str
    t_working: Optional[str]
    t_loveable: Optional[str]
    sessions_count: int
    tokens_total: int
    post_ship_fixes: int
    post_ship_features: int
    post_ship_window_days: Optional[int]
    closed_at: Optional[str]
    outcome_notes: Optional[str]
    created_at: str
    updated_at: str


class SolutionScopeLogRow(TypedDict):
    id: int
    solution_id: int
    logged_at: str
    note: str


class SolutionUsageLogRow(TypedDict):
    id: int
    solution_id: int
    kind: str
    logged_at: str
    sessions_delta: int
    tokens_delta: int
    note: Optional[str]
