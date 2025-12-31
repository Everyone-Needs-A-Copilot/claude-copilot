# Session Guard Tool

## Overview

The `session_guard` tool helps enforce main session guardrails to prevent context bloat, ensuring efficient use of Task Copilot and framework agents.

## Purpose

As outlined in CLAUDE.md, the main session should remain lightweight by:
- Limiting file reads to 3 files max
- Delegating code to framework agents
- Keeping responses under 500 tokens
- Using framework agents instead of generic agents
- Storing detailed work in work products

This tool provides automated checking and reporting against these guardrails.

## Usage

### Check Action

Validates current session behavior against guardrail rules:

```typescript
session_guard({
  action: 'check',
  context: {
    filesRead: 5,           // Number of files read
    codeWritten: true,      // Whether code was written directly
    agentUsed: 'Explore',   // Which agent was used
    responseTokens: 800     // Estimated response tokens
  }
})
```

**Returns:**
```json
{
  "allowed": false,
  "violations": [
    "Exceeded 3-file limit (read: 5). Delegate to framework agent.",
    "Code should be written by @agent-me, not main session.",
    "Generic agent \"Explore\" bypasses Task Copilot. Use framework agents."
  ],
  "warnings": [
    "Response exceeds 500 tokens (estimated: 800). Consider storing in work product."
  ],
  "suggestions": [
    "Use @agent-me for code implementation",
    "Use @agent-ta for architecture analysis",
    "Replace \"Explore\" with @agent-ta or @agent-me"
  ]
}
```

### Report Action

Provides a summary of guardrails and current initiative status:

```typescript
session_guard({
  action: 'report'
})
```

**Returns:**
```json
{
  "allowed": true,
  "violations": [],
  "warnings": [],
  "suggestions": [
    "Current initiative: Feature Development Initiative",
    "Total tasks: 10",
    "Work products: 5",
    "",
    "=== Session Guardrails ===",
    "1. Read max 3 files in main session",
    "2. Delegate code to @agent-me",
    "3. Keep responses <500 tokens",
    "4. Use framework agents only",
    "5. Store details in work products"
  ]
}
```

## Guardrail Rules

### 1. File Read Limit (3 files)
- **Violation**: `filesRead > 3`
- **Action**: Delegate to framework agent (@agent-me, @agent-ta, @agent-doc)

### 2. Code Writing
- **Violation**: `codeWritten === true`
- **Action**: Delegate to @agent-me

### 3. Response Token Limits
- **Warning**: `responseTokens > 500`
- **Violation**: `responseTokens > 1000`
- **Action**: Store detailed content in work products, return only summary

### 4. Generic Agents
- **Violation**: Using `Explore`, `Plan`, or `general-purpose` agents
- **Action**: Switch to framework agents that integrate with Task Copilot

**Generic Agents (Bypass Task Copilot):**
- `Explore` → Use @agent-ta or @agent-me
- `Plan` → Use @agent-ta
- `general-purpose` → Use specific framework agent

**Framework Agents (Integrate with Task Copilot):**
- `agent-ta` - Tech Architect
- `agent-me` - Engineer
- `agent-qa` - QA Engineer
- `agent-sec` - Security
- `agent-doc` - Documentation
- `agent-do` - DevOps
- `agent-sd` - Service Designer
- `agent-uxd` - UX Designer
- `agent-uids` - UI Designer
- `agent-uid` - UI Developer
- `agent-cw` - Copywriter

## Integration with Main Session

### Example: Self-Check Before Response

```typescript
// Main session checks itself before responding
const context = {
  filesRead: this.getFilesReadCount(),
  codeWritten: this.hasWrittenCode(),
  responseTokens: estimateTokens(this.plannedResponse)
};

const guard = await session_guard({ action: 'check', context });

if (!guard.allowed) {
  // Violations detected - adjust approach
  console.log('Guardrail violations:', guard.violations);
  // Delegate to appropriate agent instead
}
```

### Example: Periodic Report

```typescript
// Get guideline summary and initiative status
const report = await session_guard({ action: 'report' });
console.log(report.suggestions.join('\n'));
```

## Token Estimation Helper

The tool includes a helper function for estimating tokens from text:

```typescript
import { estimateTokens } from './tools/session-guard.js';

const text = "Your response text...";
const tokens = estimateTokens(text); // Rough estimate: 1 token ≈ 4 characters
```

## Testing

Run tests with:

```bash
npm run build
node dist/tools/session-guard.test.js
```

## Expected Behavior

| Scenario | Allowed | Output |
|----------|---------|--------|
| 2 files read, framework agent, 300 tokens | ✅ Yes | Positive suggestions |
| 5 files read | ❌ No | File limit violation |
| Code written directly | ❌ No | Delegation violation |
| 600 token response | ⚠️ Warning | Warning only |
| 1200 token response | ❌ No | Token limit violation |
| Used "Explore" agent | ❌ No | Generic agent violation |
| Used "agent-me" | ✅ Yes | Positive feedback |

## Implementation Details

**Location**: `mcp-servers/task-copilot/src/tools/session-guard.ts`

**Dependencies**:
- `DatabaseClient` for initiative/stats queries
- `SessionGuardInput` and `SessionGuardOutput` types

**Key Functions**:
- `sessionGuard()` - Main entry point
- `performCheck()` - Validates context against rules
- `generateReport()` - Generates guideline summary
- `estimateTokens()` - Helper for token estimation

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) - Main session guardrails
- [docs/DECISION-GUIDE.md](../../docs/DECISION-GUIDE.md) - Agent selection matrix
- [Task Copilot README](../README.md) - MCP server overview
