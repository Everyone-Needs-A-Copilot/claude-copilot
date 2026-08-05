"""MCP server implementation for cc — wraps core CLI functions as MCP tools.

Starts an MCP server on stdio. Import only when mcp package is available.
"""

from __future__ import annotations

import json
from typing import Any


def _memory_store_fn(
    content: str,
    entry_type: str = "context",
    tags: str = "",
    scope: str | None = None,
) -> dict[str, Any]:
    from cc.core.entry_format import parse_tags
    from cc.core.entry_store import (
        default_scope,
        resolve_memory_root,
        store_entry,
    )
    from cc.core.memory_index import index_entry

    tag_list = parse_tags(tags)
    resolved_scope = scope or default_scope()
    result = store_entry(
        entry_type=entry_type,
        content=content,
        tags=tag_list,
        scope=resolved_scope,
    )
    memory_root = resolve_memory_root(resolved_scope)
    db_path = memory_root / "memory.db"
    if db_path.exists():
        try:
            index_entry(result["id"], entry_type, tag_list, content, memory_root)
        except Exception:
            pass
    return result


def _memory_search_fn(query: str, scope: str | None = None) -> list[dict[str, Any]]:
    from cc.core.entry_store import (
        default_scope,
        resolve_memory_root,
        search_entries_files,
    )
    from cc.core.memory_index import search_index

    resolved_scope = scope or default_scope()
    memory_root = resolve_memory_root(resolved_scope)
    results = search_index(query, memory_root)
    if not results:
        results = search_entries_files(query, scope=resolved_scope)
    return results


def _memory_get_fn(entry_id: str, scope: str | None = None) -> dict[str, Any] | None:
    from cc.core.entry_store import default_scope, get_entry

    resolved_scope = scope or default_scope()
    return get_entry(entry_id, scope=resolved_scope)


def _memory_list_fn(
    entry_type: str | None = None,
    tag: str | None = None,
    scope: str | None = None,
) -> list[dict[str, Any]]:
    from cc.core.entry_store import default_scope, list_entries

    resolved_scope = scope or default_scope()
    return list_entries(scope=resolved_scope, entry_type=entry_type, tag=tag)


def _memory_delete_fn(entry_id: str, scope: str | None = None) -> bool:
    from cc.core.entry_store import default_scope, delete_entry, resolve_memory_root
    from cc.core.memory_index import remove_from_index

    resolved_scope = scope or default_scope()
    memory_root = resolve_memory_root(resolved_scope)
    deleted = delete_entry(entry_id, scope=resolved_scope)
    if deleted:
        try:
            remove_from_index(entry_id, memory_root)
        except Exception:
            pass
    return deleted


def _skill_list_fn(scope: str = "all") -> list[dict[str, Any]]:
    from cc.core.skill_store import _git_root, discover_skills_with_sources
    from pathlib import Path

    pairs: list[tuple[Path, str]] = []
    if scope in ("project", "all"):
        repo = _git_root()
        if repo is not None:
            project_skills = repo / ".claude" / "skills"
            if project_skills.exists():
                pairs.append((project_skills, "project"))
    if scope in ("machine", "all"):
        machine_skills = Path.home() / ".claude" / "skills"
        if machine_skills.exists():
            pairs.append((machine_skills, "machine"))

    skills = discover_skills_with_sources(pairs)
    return [
        {
            "name": s.name,
            "description": s.description,
            "tags": s.tags,
            "version": s.version,
            "source": s.source,
            "path": str(s.path),
        }
        for s in skills
    ]


def _skill_search_fn(query: str, scope: str = "all") -> list[dict[str, Any]]:
    from cc.core.skill_store import (
        _git_root,
        discover_skills_with_sources,
        search_skills,
    )
    from pathlib import Path

    pairs: list[tuple[Path, str]] = []
    if scope in ("project", "all"):
        repo = _git_root()
        if repo is not None:
            project_skills = repo / ".claude" / "skills"
            if project_skills.exists():
                pairs.append((project_skills, "project"))
    if scope in ("machine", "all"):
        machine_skills = Path.home() / ".claude" / "skills"
        if machine_skills.exists():
            pairs.append((machine_skills, "machine"))

    all_skills = discover_skills_with_sources(pairs)
    results = search_skills(query, all_skills)
    return [
        {
            "name": s.name,
            "description": s.description,
            "tags": s.tags,
            "source": s.source,
            "path": str(s.path),
        }
        for s in results
    ]


def _skill_get_fn(name: str, scope: str = "all") -> str | None:
    from cc.core.skill_store import (
        _git_root,
        discover_skills_with_sources,
        find_skill_by_name,
        get_skill_content,
    )
    from pathlib import Path

    pairs: list[tuple[Path, str]] = []
    if scope in ("project", "all"):
        repo = _git_root()
        if repo is not None:
            project_skills = repo / ".claude" / "skills"
            if project_skills.exists():
                pairs.append((project_skills, "project"))
    if scope in ("machine", "all"):
        machine_skills = Path.home() / ".claude" / "skills"
        if machine_skills.exists():
            pairs.append((machine_skills, "machine"))

    all_skills = discover_skills_with_sources(pairs)
    skill = find_skill_by_name(name, all_skills)
    if skill is None:
        return None
    return get_skill_content(skill)


def _config_get_fn(key: str, scope: str | None = None) -> dict[str, Any]:
    from cc.core.config import resolve_key

    value = resolve_key(key, scope=scope)
    return {"key": key, "value": value}


def _config_set_fn(key: str, value: str, project: bool = False) -> dict[str, Any]:
    from cc.core.config import write_config

    written_path = write_config(key, value, project=project)
    layer = "project" if project else "machine"
    return {"key": key, "value": value, "layer": layer, "path": str(written_path)}


# ---------------------------------------------------------------------------
# MCP server definition
# ---------------------------------------------------------------------------


def build_server():
    """Build and return the configured MCP Server instance."""
    from mcp.server import Server
    from mcp.types import Tool, TextContent
    import mcp.types as types

    server = Server("cc")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="memory_store",
                description="Store a new memory entry.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Memory content to store.",
                        },
                        "entry_type": {
                            "type": "string",
                            "description": "Entry type: decision|context|lesson|reference|person",
                            "default": "context",
                        },
                        "tags": {
                            "type": "string",
                            "description": "Comma-separated tags.",
                            "default": "",
                        },
                        "scope": {
                            "type": "string",
                            "description": "Scope: project or global.",
                        },
                    },
                    "required": ["content"],
                },
            ),
            Tool(
                name="memory_search",
                description="Search memory entries (FTS index when available, file-based fallback).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query."},
                        "scope": {
                            "type": "string",
                            "description": "Scope: project or global.",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="memory_get",
                description="Retrieve a memory entry by UUID (full or prefix match).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "entry_id": {
                            "type": "string",
                            "description": "Entry UUID (full or prefix).",
                        },
                        "scope": {
                            "type": "string",
                            "description": "Scope: project or global.",
                        },
                    },
                    "required": ["entry_id"],
                },
            ),
            Tool(
                name="memory_list",
                description="List memory entries, optionally filtered by type or tag.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "entry_type": {
                            "type": "string",
                            "description": "Filter by entry type.",
                        },
                        "tag": {"type": "string", "description": "Filter by tag."},
                        "scope": {
                            "type": "string",
                            "description": "Scope: project or global.",
                        },
                    },
                    "required": [],
                },
            ),
            Tool(
                name="memory_delete",
                description="Delete a memory entry by UUID (full or prefix match).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "entry_id": {
                            "type": "string",
                            "description": "Entry UUID (full or prefix).",
                        },
                        "scope": {
                            "type": "string",
                            "description": "Scope: project or global.",
                        },
                    },
                    "required": ["entry_id"],
                },
            ),
            Tool(
                name="skill_list",
                description="List all discovered skills.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "scope": {
                            "type": "string",
                            "description": "Scope: project | machine | all",
                            "default": "all",
                        },
                    },
                    "required": [],
                },
            ),
            Tool(
                name="skill_search",
                description="Search skills by keyword (matches name, description, tags).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query."},
                        "scope": {
                            "type": "string",
                            "description": "Scope: project | machine | all",
                            "default": "all",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="skill_get",
                description="Get the full SKILL.md content for a named skill.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Skill name."},
                        "scope": {
                            "type": "string",
                            "description": "Scope: project | machine | all",
                            "default": "all",
                        },
                    },
                    "required": ["name"],
                },
            ),
            Tool(
                name="config_get",
                description="Get a resolved configuration value.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Dotted config key (e.g. paths.shared_docs).",
                        },
                        "scope": {
                            "type": "string",
                            "description": "machine | project | effective",
                        },
                    },
                    "required": ["key"],
                },
            ),
            Tool(
                name="config_set",
                description="Set a configuration value.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Dotted config key."},
                        "value": {"type": "string", "description": "Value to set."},
                        "project": {
                            "type": "boolean",
                            "description": "Write to project config instead of machine config.",
                            "default": False,
                        },
                    },
                    "required": ["key", "value"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        result: Any

        if name == "memory_store":
            result = _memory_store_fn(
                content=arguments["content"],
                entry_type=arguments.get("entry_type", "context"),
                tags=arguments.get("tags", ""),
                scope=arguments.get("scope"),
            )
        elif name == "memory_search":
            result = _memory_search_fn(
                query=arguments["query"],
                scope=arguments.get("scope"),
            )
        elif name == "memory_get":
            entry = _memory_get_fn(
                entry_id=arguments["entry_id"],
                scope=arguments.get("scope"),
            )
            if entry is None:
                return [
                    TextContent(
                        type="text", text=f"Entry not found: {arguments['entry_id']}"
                    )
                ]
            result = entry
        elif name == "memory_list":
            result = _memory_list_fn(
                entry_type=arguments.get("entry_type"),
                tag=arguments.get("tag"),
                scope=arguments.get("scope"),
            )
        elif name == "memory_delete":
            deleted = _memory_delete_fn(
                entry_id=arguments["entry_id"],
                scope=arguments.get("scope"),
            )
            result = {"deleted": deleted, "entry_id": arguments["entry_id"]}
        elif name == "skill_list":
            result = _skill_list_fn(scope=arguments.get("scope", "all"))
        elif name == "skill_search":
            result = _skill_search_fn(
                query=arguments["query"],
                scope=arguments.get("scope", "all"),
            )
        elif name == "skill_get":
            content = _skill_get_fn(
                name=arguments["name"],
                scope=arguments.get("scope", "all"),
            )
            if content is None:
                return [
                    TextContent(
                        type="text", text=f"Skill not found: {arguments['name']}"
                    )
                ]
            return [TextContent(type="text", text=content)]
        elif name == "config_get":
            result = _config_get_fn(
                key=arguments["key"],
                scope=arguments.get("scope"),
            )
        elif name == "config_set":
            result = _config_set_fn(
                key=arguments["key"],
                value=arguments["value"],
                project=arguments.get("project", False),
            )
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    return server


async def run_server() -> None:
    """Run the MCP server on stdio."""
    from mcp.server.stdio import stdio_server

    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
