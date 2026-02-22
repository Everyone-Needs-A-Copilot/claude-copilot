# External Query API Reference

## Overview

The External Query API is a lightweight HTTP REST API for querying task and stream state. It enables external scripts (e.g., Python orchestration tools) to monitor progress without requiring MCP protocol integration.

### Purpose

- **External Integration**: Enable non-MCP tools to monitor task state
- **Orchestration**: Support parallel stream management via external scripts
- **Real-time Monitoring**: Query current agent activity and task progress
- **Dependency Polling**: Check stream completion for dependency resolution

### Architecture

- **Embedded Server**: Lightweight HTTP server process
- **Framework**: Fastify HTTP server (lightweight, production-ready)
- **Protocol**: Standard HTTP/REST (no authentication, localhost-only)
- **Default URL**: `http://localhost:9090`

### Security Model

The API is designed for localhost-only access:
- Default bind address: `127.0.0.1` (not accessible from network)
- No authentication required (assumes trusted localhost environment)
- Read-only operations (no mutations)

---

## Configuration

Configure the HTTP API via environment variables:

```bash
export HTTP_API_HOST="127.0.0.1"
export HTTP_API_PORT="9090"
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HTTP_API_HOST` | `127.0.0.1` | Bind address (use 127.0.0.1 for localhost-only) |
| `HTTP_API_PORT` | `9090` | Port number |

### Server Lifecycle

The HTTP API server:
- Starts when the query API process starts
- Fails gracefully if port is in use
- Logs startup message: `HTTP API listening on http://127.0.0.1:9090`

---

## Endpoints

### GET /health

Health check endpoint for monitoring server availability.

**Query Parameters**: None

**Response**:
```json
{
  "status": "ok",
  "timestamp": "2026-01-08T12:34:56.789Z"
}
```

**Status Codes**:
- `200 OK`: Server is running

---

### GET /api/streams

List all independent work streams with progress summary.

**Query Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `initiativeId` | string | No | Filter by initiative ID |
| `includeArchived` | string | No | Include archived streams (`"true"` or `"false"`, default: `"false"`) |

**Response**:
```json
{
  "streams": [
    {
      "streamId": "Stream-A",
      "streamName": "foundation",
      "streamPhase": "foundation",
      "totalTasks": 4,
      "completedTasks": 4,
      "inProgressTasks": 0,
      "blockedTasks": 0,
      "pendingTasks": 0,
      "progressPercentage": 100,
      "files": [
        "src/types.ts",
        "src/tools/stream.ts"
      ],
      "dependencies": []
    },
    {
      "streamId": "Stream-B",
      "streamName": "command-updates",
      "streamPhase": "parallel",
      "totalTasks": 3,
      "completedTasks": 1,
      "inProgressTasks": 1,
      "blockedTasks": 0,
      "pendingTasks": 1,
      "progressPercentage": 33,
      "files": [
        ".claude/commands/protocol.md",
        ".claude/commands/continue.md"
      ],
      "dependencies": ["Stream-A"]
    }
  ],
  "totalStreams": 2
}
```

**Status Codes**:
- `200 OK`: Success

**Stream Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `streamId` | string | Unique stream identifier (e.g., "Stream-A") |
| `streamName` | string | Human-readable stream name |
| `streamPhase` | string | Stream phase: `"foundation"`, `"parallel"`, or `"integration"` |
| `totalTasks` | number | Total tasks in stream |
| `completedTasks` | number | Tasks with status `"completed"` |
| `inProgressTasks` | number | Tasks with status `"in_progress"` |
| `blockedTasks` | number | Tasks with status `"blocked"` |
| `pendingTasks` | number | Tasks with status `"pending"` |
| `progressPercentage` | number | Completion percentage (0-100) |
| `files` | string[] | Files modified by stream tasks |
| `dependencies` | string[] | Stream IDs this stream depends on |

---

### GET /api/streams/:streamId

Get detailed information for a specific stream, including all tasks.

**Path Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `streamId` | string | Yes | Stream ID (e.g., "Stream-B") |

**Query Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `includeArchived` | string | No | Include archived streams (`"true"` or `"false"`, default: `"false"`) |

**Response**:
```json
{
  "streamId": "Stream-B",
  "streamName": "command-updates",
  "streamPhase": "parallel",
  "dependencies": ["Stream-A"],
  "progressPercentage": 33,
  "tasks": [
    {
      "id": "TASK-456",
      "title": "Update /protocol command",
      "description": "Add stream routing logic",
      "status": "in_progress",
      "assignedAgent": "me",
      "prdId": "PRD-123",
      "parentId": null,
      "blockedReason": null,
      "notes": "Working on implementation",
      "metadata": {
        "streamId": "Stream-B",
        "streamName": "command-updates",
        "streamPhase": "parallel",
        "files": [".claude/commands/protocol.md"],
        "streamDependencies": ["Stream-A"],
        "complexity": "medium"
      },
      "createdAt": "2026-01-08T10:00:00.000Z",
      "updatedAt": "2026-01-08T11:30:00.000Z"
    },
    {
      "id": "TASK-457",
      "title": "Update /continue command",
      "description": "Add stream argument support",
      "status": "pending",
      "assignedAgent": "me",
      "prdId": "PRD-123",
      "parentId": null,
      "blockedReason": null,
      "notes": null,
      "metadata": {
        "streamId": "Stream-B",
        "streamName": "command-updates",
        "streamPhase": "parallel",
        "files": [".claude/commands/continue.md"],
        "streamDependencies": ["Stream-A"]
      },
      "createdAt": "2026-01-08T10:00:00.000Z",
      "updatedAt": "2026-01-08T10:00:00.000Z"
    }
  ]
}
```

**Error Response** (404 Not Found):
```json
{
  "error": "Stream not found",
  "streamId": "Stream-X"
}
```

**Status Codes**:
- `200 OK`: Stream found
- `404 Not Found`: Stream does not exist or is archived (unless `includeArchived=true`)

**Task Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Task ID |
| `title` | string | Task title |
| `description` | string \| undefined | Task description |
| `status` | string | Task status: `"pending"`, `"in_progress"`, `"blocked"`, `"completed"`, `"cancelled"` |
| `assignedAgent` | string \| undefined | Agent ID (e.g., "me", "ta", "qa") |
| `prdId` | string \| undefined | Parent PRD ID |
| `parentId` | string \| undefined | Parent task ID (for subtasks) |
| `blockedReason` | string \| undefined | Reason if status is `"blocked"` |
| `notes` | string \| undefined | Task notes |
| `metadata` | object | Task metadata (includes stream info, files, dependencies) |
| `createdAt` | string | ISO 8601 timestamp |
| `updatedAt` | string | ISO 8601 timestamp |

---

### GET /api/tasks

Query tasks with flexible filtering.

**Query Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `status` | string | No | Filter by status: `"pending"`, `"in_progress"`, `"blocked"`, `"completed"`, `"cancelled"` |
| `streamId` | string | No | Filter by stream ID (e.g., "Stream-B") |
| `assignedAgent` | string | No | Filter by agent ID (e.g., "me", "ta", "qa") |
| `prdId` | string | No | Filter by PRD ID |
| `limit` | string | No | Maximum number of results (e.g., "10") |

**Response**:
```json
{
  "tasks": [
    {
      "id": "TASK-456",
      "title": "Update /protocol command",
      "description": "Add stream routing logic",
      "status": "in_progress",
      "assignedAgent": "me",
      "prdId": "PRD-123",
      "parentId": null,
      "blockedReason": null,
      "notes": "Working on implementation",
      "metadata": {
        "streamId": "Stream-B",
        "streamName": "command-updates",
        "streamPhase": "parallel",
        "files": [".claude/commands/protocol.md"],
        "streamDependencies": ["Stream-A"],
        "complexity": "medium"
      },
      "createdAt": "2026-01-08T10:00:00.000Z",
      "updatedAt": "2026-01-08T11:30:00.000Z"
    }
  ],
  "totalTasks": 1
}
```

**Status Codes**:
- `200 OK`: Success (empty array if no matches)

**Notes**:
- Archived tasks are excluded by default
- Tasks are ordered by `created_at DESC` (newest first)
- Combine filters for precise queries (e.g., `status=in_progress&streamId=Stream-B`)

---

### GET /api/activity

Get current agent activity across all streams or filtered by stream.

**Query Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `streamId` | string | No | Filter by stream ID |
| `active` | string | No | Show only active agents (`"true"`, default) or all (`"false"`) |

**Response**:
```json
{
  "activities": [
    {
      "streamId": "Stream-B",
      "streamName": "command-updates",
      "agentId": "me",
      "agentName": "Engineer",
      "taskId": "TASK-456",
      "taskTitle": "Update /protocol command",
      "activityDescription": "Implementing stream routing logic",
      "phase": "implementation",
      "startedAt": "2026-01-08T11:00:00.000Z",
      "lastHeartbeat": "2026-01-08T11:28:00.000Z",
      "isActive": true
    },
    {
      "streamId": "Stream-C",
      "streamName": "documentation",
      "agentId": "doc",
      "agentName": "Documentation",
      "taskId": "TASK-789",
      "taskTitle": "Write API reference",
      "activityDescription": null,
      "phase": null,
      "startedAt": "2026-01-08T09:00:00.000Z",
      "lastHeartbeat": "2026-01-08T10:45:00.000Z",
      "isActive": false
    }
  ],
  "totalActive": 1,
  "totalIdle": 1
}
```

**Status Codes**:
- `200 OK`: Success

**Activity Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `streamId` | string | Stream ID |
| `streamName` | string | Human-readable stream name |
| `agentId` | string | Agent ID (e.g., "me", "ta", "doc") |
| `agentName` | string | Human-readable agent name (e.g., "Engineer", "Tech Architect") |
| `taskId` | string | Task ID being worked on |
| `taskTitle` | string | Task title |
| `activityDescription` | string \| undefined | Current activity description |
| `phase` | string \| undefined | Current execution phase |
| `startedAt` | string | ISO 8601 timestamp when agent started task |
| `lastHeartbeat` | string | ISO 8601 timestamp of last activity update |
| `isActive` | boolean | Whether agent is currently active (heartbeat within 5 minutes) |

**Agent Name Mappings**:

| Agent ID | Agent Name |
|----------|------------|
| `me` | Engineer |
| `ta` | Tech Architect |
| `qa` | QA Engineer |
| `sec` | Security |
| `doc` | Documentation |
| `do` | DevOps |
| `sd` | Service Designer |
| `uxd` | UX Designer |
| `uids` | UI Designer |
| `uid` | UI Developer |
| `cw` | Copywriter |

**Active Threshold**:
- Agent is considered active if last heartbeat is within 5 minutes
- Idle agents have heartbeats older than 5 minutes

---

## Usage Examples

### Python Client Examples

#### List All Streams

```python
import requests

def list_streams():
    """Get all active streams with progress."""
    response = requests.get('http://localhost:9090/api/streams')
    response.raise_for_status()
    data = response.json()

    print(f"Total streams: {data['totalStreams']}")
    for stream in data['streams']:
        print(f"{stream['streamId']}: {stream['streamName']} - {stream['progressPercentage']}% complete")
        print(f"  Tasks: {stream['completedTasks']}/{stream['totalTasks']}")
        print(f"  Phase: {stream['streamPhase']}")
        if stream['dependencies']:
            print(f"  Depends on: {', '.join(stream['dependencies'])}")

if __name__ == '__main__':
    list_streams()
```

**Example Output**:
```
Total streams: 2
Stream-A: foundation - 100% complete
  Tasks: 4/4
  Phase: foundation
Stream-B: command-updates - 33% complete
  Tasks: 1/3
  Phase: parallel
  Depends on: Stream-A
```

#### Check Stream Completion (Dependency Polling)

```python
import requests
import time

def wait_for_stream_completion(stream_id, poll_interval=5, timeout=300):
    """Poll stream until completion or timeout."""
    start_time = time.time()

    while True:
        if time.time() - start_time > timeout:
            raise TimeoutError(f"Stream {stream_id} did not complete within {timeout}s")

        response = requests.get(f'http://localhost:9090/api/streams/{stream_id}')

        if response.status_code == 404:
            raise ValueError(f"Stream {stream_id} not found")

        response.raise_for_status()
        stream = response.json()

        completed = stream['completedTasks']
        total = len(stream['tasks'])
        progress = stream['progressPercentage']

        print(f"{stream_id}: {completed}/{total} tasks complete ({progress}%)")

        if completed == total:
            print(f"Stream {stream_id} completed!")
            return True

        # Check for blocked tasks
        blocked = sum(1 for t in stream['tasks'] if t['status'] == 'blocked')
        if blocked > 0:
            print(f"Warning: {blocked} blocked task(s)")

        time.sleep(poll_interval)

if __name__ == '__main__':
    # Wait for foundation stream before starting parallel work
    wait_for_stream_completion('Stream-A')
    print("Foundation complete, can start parallel streams")
```

**Example Output**:
```
Stream-A: 2/4 tasks complete (50%)
Stream-A: 3/4 tasks complete (75%)
Stream-A: 4/4 tasks complete (100%)
Stream-A completed!
Foundation complete, can start parallel streams
```

#### Monitor Agent Activity

```python
import requests

def get_active_agents():
    """Get currently active agents."""
    response = requests.get('http://localhost:9090/api/activity?active=true')
    response.raise_for_status()
    data = response.json()

    if data['totalActive'] == 0:
        print("No active agents")
        return

    print(f"Active agents: {data['totalActive']}")
    for activity in data['activities']:
        if activity['isActive']:
            print(f"\n{activity['agentName']} ({activity['agentId']})")
            print(f"  Stream: {activity['streamName']}")
            print(f"  Task: {activity['taskTitle']}")
            if activity['activityDescription']:
                print(f"  Activity: {activity['activityDescription']}")
            if activity['phase']:
                print(f"  Phase: {activity['phase']}")

if __name__ == '__main__':
    get_active_agents()
```

**Example Output**:
```
Active agents: 2

Engineer (me)
  Stream: command-updates
  Task: Update /protocol command
  Activity: Implementing stream routing logic
  Phase: implementation

Documentation (doc)
  Stream: api-docs
  Task: Write API reference
  Phase: documentation
```

#### Query In-Progress Tasks

```python
import requests

def get_in_progress_tasks():
    """Get all in-progress tasks."""
    response = requests.get('http://localhost:9090/api/tasks?status=in_progress')
    response.raise_for_status()
    data = response.json()

    print(f"In-progress tasks: {data['totalTasks']}")
    for task in data['tasks']:
        stream_name = task['metadata'].get('streamName', 'Unknown')
        agent = task.get('assignedAgent', 'Unassigned')
        print(f"\n{task['id']}: {task['title']}")
        print(f"  Stream: {stream_name}")
        print(f"  Agent: {agent}")
        if task['notes']:
            print(f"  Notes: {task['notes']}")

if __name__ == '__main__':
    get_in_progress_tasks()
```

---

## Error Handling

### Server Not Running

If the HTTP API server is not running, requests will fail with a connection error:

```python
import requests

try:
    response = requests.get('http://localhost:9090/api/streams')
    response.raise_for_status()
except requests.exceptions.ConnectionError:
    print("Error: HTTP API is not running")
    print("Ensure the query API server is started")
except requests.exceptions.RequestException as e:
    print(f"HTTP error: {e}")
```

### 404 Stream Not Found

```python
response = requests.get('http://localhost:9090/api/streams/Stream-X')

if response.status_code == 404:
    error = response.json()
    print(f"Error: {error['error']}")
    print(f"Stream ID: {error['streamId']}")
else:
    stream = response.json()
    # Process stream data
```

### Port Already in Use

If the configured port is already in use, the HTTP API server will fail to start. Check logs:

```
Failed to start HTTP API server: Error: listen EADDRINUSE: address already in use 127.0.0.1:9090
```

**Solution**: Change `HTTP_API_PORT` environment variable to an available port.

---

## Limitations

### Read-Only Access

The External Query API provides read-only access to task state. Mutations (creating tasks, updating status, etc.) must be done via the `tc` CLI.

**Why**: Maintains single source of truth through the `tc` CLI with proper validation and activity logging.

### No Authentication

The API does not implement authentication. It is designed for localhost-only access in trusted environments.

**Security Model**:
- Bind to `127.0.0.1` (not accessible from network)
- Assumes localhost is trusted
- No sensitive data exposure (task/stream metadata only)

### Polling Required

The API does not support WebSockets or Server-Sent Events. Clients must poll for state changes.

**Best Practices**:
- Use reasonable poll intervals (5-10 seconds)
- Implement exponential backoff for errors
- Cache responses to reduce load

---

## Performance Considerations

### Response Sizes

| Endpoint | Typical Response Size | Notes |
|----------|----------------------|-------|
| `/health` | ~50 bytes | Minimal overhead |
| `/api/streams` | ~500 bytes per stream | Depends on file list size |
| `/api/streams/:id` | ~1-5 KB | Includes full task list |
| `/api/tasks` | ~500 bytes per task | Use `limit` for large result sets |
| `/api/activity` | ~200 bytes per activity | Usually small (few concurrent agents) |

### Concurrency

The Fastify server handles concurrent requests efficiently. No special client-side throttling needed for typical orchestration workloads.

### Database Impact

All endpoints query the SQLite database. Impact is minimal for typical usage patterns:
- Simple indexed queries (by stream ID, status, etc.)
- No complex joins or aggregations
- Database is shared with MCP server (read-only queries don't block)

---

## Troubleshooting

### Server Not Starting

**Symptom**: Logs show "Failed to start HTTP API server"

**Causes**:
1. Port already in use
2. Insufficient permissions
3. Invalid host address

**Solution**:
```bash
# Check if port is in use
lsof -i :9090

# Try a different port
# Edit .mcp.json:
"HTTP_API_PORT": "9091"
```

### Empty Response

**Symptom**: Endpoints return empty arrays or no data

**Causes**:
1. No tasks/streams in current initiative
2. Archived streams (need `includeArchived=true`)
3. Filters too restrictive

**Solution**:
```python
# Check initiative context
response = requests.get('http://localhost:9090/api/streams?includeArchived=true')

# Try broader filters
response = requests.get('http://localhost:9090/api/tasks')  # No filters
```

### Stale Data

**Symptom**: Activity shows agents as idle when they're working

**Cause**: Agent heartbeat not updated (may indicate agent issue)

**Solution**: Check agent logs and task status. Activity heartbeat updates are managed by agents via the `tc` CLI.

---

## See Also

- **Task Management**: `tc` CLI tool
- **Stream Management**: Stream orchestration guide (`docs/orchestration/stream-management.md`)
