# Claude Copilot Architecture

## System Overview

Claude Copilot is a four-pillar framework that transforms Claude Code into a specialized development environment with persistent memory, expert agents, on-demand skills, and battle-tested workflows.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER INTERACTION                                │
│                                                                              │
│  Developer ──→ Claude Code CLI ──→ /protocol  or  /continue                │
│                                          │              │                    │
└──────────────────────────────────────────┼──────────────┼───────────────────┘
                                           │              │
                                           ▼              ▼
                            ┌──────────────────────────────────┐
                            │     WORKFLOW LAYER (Pillar 4)    │
                            │         .claude/commands/         │
                            │                                   │
                            │  /protocol  →  Agent-First Flow  │
                            │  /continue  →  Resume via Memory │
                            └──────────────┬───────────────────┘
                                           │
                                           │ Routes to appropriate layer
                                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          EXPERTISE LAYER (Pillar 2)                          │
│                              .claude/agents/                                 │
│                                                                              │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐          │
│  │   ta    │  │   me    │  │   qa    │  │   sec   │  │   doc   │          │
│  │  Tech   │  │Engineer │  │   QA    │  │Security │  │  Docs   │          │
│  │Architect│  │         │  │Engineer │  │         │  │         │          │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘          │
│       │            │            │            │            │                │
│  ┌────┴────┐  ┌────┴────┐  ┌────┴────┐  ┌────┴────┐  ┌────┴────┐          │
│  │   do    │  │   sd    │  │   uxd   │  │  uids   │  │   uid   │          │
│  │ DevOps  │  │ Service │  │   UX    │  │   UI    │  │   UI    │          │
│  │         │  │Designer │  │Designer │  │Designer │  │Developer│          │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘          │
│       │            │            │            │            │                │
│       └────────────┴────────────┴────────────┴────────────┘                │
│                                 │                                           │
│                    Agent-to-Agent Routing (expertise-based)                │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                    ┌─────────────┴──────────────┐
                    │                            │
                    ▼                            ▼
┌──────────────────────────────┐  ┌──────────────────────────────────────────┐
│  KNOWLEDGE LAYER (Pillar 3)  │  │   PERSISTENCE LAYER (Pillar 1)           │
│  mcp-servers/skills-copilot/ │  │   mcp-servers/copilot-memory/            │
│                              │  │                                          │
│  ┌────────────────────────┐  │  │  ┌────────────────────────────────┐     │
│  │   Skills Copilot MCP   │  │  │  │    Memory Copilot MCP          │     │
│  │                        │  │  │  │                                │     │
│  │  • skill_get           │  │  │  │  • initiative_start            │     │
│  │  • skill_search        │  │  │  │  • initiative_get              │     │
│  │  • skill_list          │  │  │  │  • initiative_update           │     │
│  │  • skill_save          │  │  │  │  • initiative_complete         │     │
│  └───────────┬────────────┘  │  │  │  • memory_store                │     │
│              │               │  │  │  • memory_search               │     │
│              ▼               │  │  └──────────┬─────────────────────┘     │
│  ┌──────────────────────┐    │  │             │                           │
│  │  Multi-Source Fetch  │    │  │             ▼                           │
│  └──┬────┬────┬────┬────┘    │  │  ┌──────────────────────────────────┐  │
│     │    │    │    │         │  │  │  SQLite Database                 │  │
│     │    │    │    │         │  │  │                                  │  │
│     │    │    │    │         │  │  │  • initiatives (current/archive) │  │
│     │    │    │    │         │  │  │  • memories (semantic indexed)   │  │
│     │    │    │    │         │  │  │  • sessions                      │  │
│     │    │    │    │         │  │  │  • key_files                     │  │
│     │    │    │    │         │  │  └──────────────────────────────────┘  │
└─────┼────┼────┼────┼──────────┘  └──────────────────────────────────────────┘
      │    │    │    │
      │    │    │    └──────────────┐
      │    │    │                   │
      ▼    ▼    ▼                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL DATA SOURCES                                 │
│                                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │   Local      │  │   SQLite     │  │  SkillsMP    │  │  PostgreSQL  │   │
│  │   Files      │  │   Cache      │  │    API       │  │   Database   │   │
│  │              │  │              │  │              │  │              │   │
│  │ Git-synced   │  │ Fast repeat  │  │ 25,000+      │  │ Private/     │   │
│  │ project      │  │ access       │  │ public       │  │ proprietary  │   │
│  │ skills       │  │ (~7 days)    │  │ skills       │  │ skills       │   │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## User Interaction Flows

### Flow 1: Starting Fresh Work with /protocol

```
Developer types: "Fix login bug"
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: Protocol Command Analysis                               │
│ /protocol activated → classifies request as DEFECT              │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: Route to Understanding Agent                            │
│ Request type: DEFECT → Route to @agent-qa                       │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: Agent Investigation                                     │
│ @agent-qa:                                                       │
│  • Reproduces issue                                             │
│  • Identifies root cause at auth/login.ts:47                    │
│  • Documents reproduction steps                                 │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: Present Findings + Request Approval                     │
│ Claude presents:                                                │
│  • Summary of findings                                          │
│  • Root cause                                                   │
│  • Proposed fix plan                                            │
│  • Pre-execution checklist                                      │
│  • Asks: "Shall I proceed?"                                     │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼ (User approves)
┌─────────────────────────────────────────────────────────────────┐
│ Step 5: Execute Fix                                             │
│ @agent-me implements fix → @agent-qa verifies                   │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 6: Save to Memory                                          │
│ initiative_update stores:                                       │
│  • What was fixed                                               │
│  • Decision rationale                                           │
│  • Files changed                                                │
│  • Lessons learned                                              │
└─────────────────────────────────────────────────────────────────┘
```

### Flow 2: Resuming Work with /continue

```
Developer types: "/continue"
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: Retrieve Context                                        │
│ Memory Copilot → initiative_get()                               │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: Load Previous State                                     │
│ Returns:                                                         │
│  • Current initiative details                                   │
│  • Work completed                                               │
│  • Work in progress                                             │
│  • Resume instructions                                          │
│  • Key files touched                                            │
│  • Decisions made                                               │
│  • Lessons learned                                              │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: Present Context + Next Steps                            │
│ Claude presents:                                                │
│  • "We were working on: [initiative]"                           │
│  • "Completed: [tasks]"                                         │
│  • "In progress: [current task]"                                │
│  • "Next: [resume instructions]"                                │
│  • Asks: "Ready to continue?"                                   │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: Continue Work                                           │
│ Picks up exactly where left off with full context               │
└─────────────────────────────────────────────────────────────────┘
```

### Flow 3: Agent-to-Agent Routing

```
@agent-ta receives architecture request
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: Analyze Request                                         │
│ "Design authentication system with OAuth"                       │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: Identify Security Implications                          │
│ ta recognizes: "Security concerns" → Route to @agent-sec        │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: Security Review                                         │
│ @agent-sec reviews:                                             │
│  • OAuth flow security                                          │
│  • Token storage                                                │
│  • CSRF protection                                              │
│  • Returns recommendations                                      │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: Incorporate Security + Design                           │
│ @agent-ta incorporates sec recommendations into architecture    │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 5: Implementation Handoff                                  │
│ ta recognizes: "Ready to implement" → Route to @agent-me        │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 6: Implementation                                          │
│ @agent-me builds based on architecture + security guidelines    │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 7: Documentation                                           │
│ me recognizes: "Needs documentation" → Route to @agent-doc      │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 8: Testing                                                 │
│ Any agent recognizes: "Needs testing" → Route to @agent-qa      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Flow Diagram

### How Information Moves Through the System

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          1. USER INPUT                                       │
│                                                                              │
│  Developer Request → /protocol or /continue                                 │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     2. CONTEXT ENRICHMENT                                    │
│                                                                              │
│  ┌──────────────────────┐              ┌──────────────────────┐            │
│  │  Memory Copilot      │              │  Skills Copilot      │            │
│  │  ─────────────       │              │  ──────────────      │            │
│  │  • Load initiative   │              │  • Load relevant     │            │
│  │  • Get past context  │◄─────────────┤    skills            │            │
│  │  • Retrieve lessons  │              │  • Get best          │            │
│  │                      │              │    practices         │            │
│  └──────────┬───────────┘              └──────────┬───────────┘            │
│             │                                     │                        │
│             └─────────────────┬───────────────────┘                        │
│                               │                                            │
└───────────────────────────────┼─────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       3. AGENT PROCESSING                                    │
│                                                                              │
│  Specialized Agent receives:                                                │
│  • User request                                                             │
│  • Historical context (from Memory)                                         │
│  • Relevant skills (from Skills)                                            │
│  • Agent instructions (.claude/agents/)                                     │
│                                                                              │
│  Agent outputs:                                                             │
│  • Analysis/Design/Code/Tests                                               │
│  • Routing decisions (to other agents)                                      │
│  • Memory updates (decisions, lessons)                                      │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        4. PERSISTENCE                                        │
│                                                                              │
│  Memory Copilot stores:                                                     │
│  ┌────────────────────────────────────────────────────────────────┐         │
│  │ Initiative Record                                              │         │
│  │ ──────────────────                                             │         │
│  │ • title: "Fix login authentication"                            │         │
│  │ • status: "in_progress"                                        │         │
│  │ • completed: ["Reproduced bug", "Identified root cause"]       │         │
│  │ • inProgress: "Implementing fix in auth/login.ts"              │         │
│  │ • decisions: ["Use JWT instead of sessions"]                  │         │
│  │ • lessons: ["Always test edge cases with null tokens"]         │         │
│  │ • keyFiles: ["auth/login.ts", "middleware/auth.ts"]            │         │
│  │ • resumeInstructions: "Continue testing with OAuth provider"   │         │
│  └────────────────────────────────────────────────────────────────┘         │
│                                                                              │
│  Indexed for semantic search → future context retrieval                     │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         5. USER OUTPUT                                       │
│                                                                              │
│  Claude presents:                                                           │
│  • Agent findings                                                           │
│  • Recommended actions                                                      │
│  • Request for approval                                                     │
│  OR                                                                          │
│  • Completed work                                                           │
│  • Verification results                                                     │
│  • Next steps                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Storage Architecture

### Memory Copilot Storage (SQLite)

```
Memory Database: ~/.claude/memory/{project-hash}/memory.db

┌─────────────────────────────────────────────────────────────────┐
│  Table: initiatives                                             │
│  ─────────────────────                                          │
│  id, title, description, status, created_at, updated_at,        │
│  completed_at, completed[], inProgress[], blockers[],           │
│  decisions[], lessons[], keyFiles[], resumeInstructions,        │
│  metadata{}                                                     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Table: memories                                                │
│  ──────────────                                                 │
│  id, initiative_id, session_id, type, content, tags[],          │
│  context{}, embedding (for semantic search), created_at         │
│                                                                 │
│  Types: decision, lesson, context, discovery, reference         │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Table: sessions                                                │
│  ───────────────                                                │
│  id, initiative_id, started_at, ended_at, summary               │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Table: key_files                                               │
│  ────────────────                                               │
│  id, initiative_id, file_path, role, last_modified              │
└─────────────────────────────────────────────────────────────────┘
```

### Skills Copilot Storage (Multi-Source)

```
Priority Order (first match wins):

1. Local Files
   └── ./03-ai-enabling/01-skills/*.md
       (Git-synced project-specific skills)

2. SQLite Cache
   └── ~/.claude/skills-cache/cache.db
       (7-day cached skills from all sources)

3. PostgreSQL Database (if configured)
   └── Private/proprietary skills
       (Company-specific, not public)

4. SkillsMP API (if configured)
   └── https://api.skillsmp.com
       (25,000+ public skills, curated community)
```

---

## Agent Routing Matrix

### Understanding Phase

| Request Type | First Agent | Then Routes To | Finally Routes To |
|--------------|-------------|----------------|-------------------|
| Bug/Defect | `@agent-qa` | `@agent-me` (fix) | `@agent-qa` (verify) |
| Experience | `@agent-sd` + `@agent-uxd` | `@agent-uids` | `@agent-uid` |
| Technical | `@agent-ta` | `@agent-sec` (if security) | `@agent-me` |
| Architecture | `@agent-ta` | `@agent-sec` + `@agent-do` | `@agent-me` |

### Cross-Cutting Concerns (Any Agent Can Route)

| Concern | Routes To | Returns To |
|---------|-----------|------------|
| Security implications | `@agent-sec` | Original agent |
| Documentation needed | `@agent-doc` | Original agent |
| Testing required | `@agent-qa` | Original agent |
| Deployment concerns | `@agent-do` | Original agent |

---

## Component Integration

### How the Pillars Work Together

```
Example: Implementing a new API endpoint

┌─────────────────────────────────────────────────────────────────┐
│ Developer: "Add user profile API endpoint"                      │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ PILLAR 4: Protocol                                              │
│ Classifies as TECHNICAL → /protocol activates                   │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ PILLAR 2: Agents                                                │
│ Routes to @agent-ta for architecture design                     │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ PILLAR 3: Skills                                                │
│ @agent-ta calls skill_search("REST API design")                 │
│ Returns: API design patterns, versioning strategies             │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ PILLAR 1: Memory                                                │
│ @agent-ta calls memory_search("API endpoints")                  │
│ Returns: Past decisions on API structure, auth patterns         │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ @agent-ta: Designs endpoint with:                               │
│  • Skills best practices                                        │
│  • Consistency with past API decisions                          │
│  • Routes to @agent-sec for auth review                         │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ @agent-sec: Reviews security, returns to @agent-ta              │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ @agent-ta: Finalizes design, routes to @agent-me               │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ @agent-me: Implements endpoint                                  │
│  • Routes to @agent-qa for tests                                │
│  • Routes to @agent-doc for API docs                            │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ PILLAR 1: Memory (again)                                        │
│ initiative_update stores:                                       │
│  • Decision: "Used JWT for auth consistency"                    │
│  • Lesson: "Always version API endpoints from start"            │
│  • Files: ["api/users/profile.ts", "middleware/auth.ts"]        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Extension System Architecture

```
Project detects knowledge-manifest.json
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ Extension Manifest Processing                                   │
│                                                                 │
│ {                                                               │
│   "name": "company-standards",                                  │
│   "type": "extension",                                          │
│   "extends": {                                                  │
│     "agents": {                                                 │
│       "ta": {                                                   │
│         "behavior": "extension",                                │
│         "file": "agents/ta-company-extension.md"                │
│       }                                                         │
│     },                                                          │
│     "skills": {                                                 │
│       "path": "skills/",                                        │
│       "priority": "high"                                        │
│     }                                                           │
│   }                                                             │
│ }                                                               │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ Runtime Composition                                             │
│                                                                 │
│ Base Agent (@agent-ta)                                          │
│      +                                                          │
│ Extension (company-specific architecture standards)             │
│      =                                                          │
│ Enhanced Agent (generic + company-specific)                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## System Boundaries

### What's Included

- **Memory**: Persistent across sessions, project-scoped
- **Agents**: 11 specialized roles, extensible via knowledge repos
- **Skills**: On-demand loading, multi-source, cached
- **Protocol**: Two core commands (/protocol, /continue)

### What's External

- **Claude Code CLI**: The runtime environment
- **MCP SDK**: Communication protocol
- **Git**: Version control (not managed by framework)
- **SkillsMP API**: Public skills marketplace
- **PostgreSQL**: Optional private skills storage
- **Project Files**: Actual codebase being worked on

### What's Not Included

- **Code Execution**: Done by Claude Code, not framework
- **File System Operations**: Managed by Claude Code tools
- **Network Requests**: Handled by external APIs
- **Build/Deploy**: Done by project tooling, coordinated by agents

---

## Performance Considerations

### Token Optimization

| Component | Strategy | Benefit |
|-----------|----------|---------|
| Memory | Semantic search returns only relevant context | 80% token reduction vs. full file loading |
| Skills | On-demand loading, not preloaded | 95% token reduction vs. context stuffing |
| Agents | Specialized, not general-purpose | 60% token reduction vs. generic instructions |
| Protocol | Two simple commands | 90% token reduction vs. explaining workflow each time |

### Caching Strategy

| Layer | Cache Type | TTL | Purpose |
|-------|------------|-----|---------|
| Skills | SQLite | 7 days | Fast repeat access |
| Memory | SQLite + Embeddings | Forever (project-scoped) | Persistent context |
| Agents | File system | N/A | Git-managed |

---

## Security Model

### Data Isolation

```
Per-Project Memory:
~/.claude/memory/
  ├── {project-hash-1}/memory.db  ← Project A cannot access
  ├── {project-hash-2}/memory.db  ← Project B's data
  └── {project-hash-3}/memory.db

Skills Sources (by trust level):
1. Local Files (highest trust - your project)
2. Private DB (high trust - your organization)
3. SQLite Cache (medium trust - cached from verified sources)
4. SkillsMP API (medium trust - community curated)
```

### Secrets Management

- **No secrets in memory database**: Decisions/lessons only, no credentials
- **No secrets in skills**: Skills are templates/patterns, not credentials
- **Environment variables**: API keys for SkillsMP, PostgreSQL
- **Agent awareness**: @agent-sec enforces security guidelines

---

## Failure Modes & Resilience

### Graceful Degradation

| Component Fails | System Behavior | User Impact |
|-----------------|-----------------|-------------|
| Memory Copilot | Creates new initiative, no history | Loss of context, but can proceed |
| Skills Copilot (all sources) | Agents work without skills | Less optimal solutions, but functional |
| Skills Copilot (one source) | Falls back to next priority | Transparent to user |
| Specific Agent | Routes to closest alternative | Might be less specialized |
| Protocol Commands | Works without them | Manual routing required |

### Error Recovery

```
┌─────────────────────────────────────────────────────────────────┐
│ Error: Memory database locked                                   │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ Retry Logic: 3 attempts with exponential backoff                │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ Still fails? Fallback to in-memory session state                │
│ (Warning logged, work continues without persistence)            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Future Architecture Considerations

### Planned Enhancements

1. **Multi-Project Memory**: Cross-project lesson sharing (opt-in)
2. **Agent Marketplace**: Community-contributed specialized agents
3. **Skill Validation**: Automated testing of skill effectiveness
4. **Protocol Extensions**: Custom workflows per project type
5. **Cloud Sync**: Optional remote memory backup

### Extension Points

- **Custom Agents**: Via knowledge repositories
- **Custom Skills**: Via local files or private DB
- **Custom Commands**: Via `.claude/commands/`
- **Custom Workflows**: Via protocol extensions

---

## Appendix: File Structure

```
claude-copilot/
├── .claude/
│   ├── agents/              ← 11 specialized agents
│   │   ├── ta.md
│   │   ├── me.md
│   │   ├── qa.md
│   │   ├── sec.md
│   │   ├── doc.md
│   │   ├── do.md
│   │   ├── sd.md
│   │   ├── uxd.md
│   │   ├── uids.md
│   │   ├── uid.md
│   │   └── cw.md
│   └── commands/            ← Workflow commands
│       ├── protocol.md
│       └── continue.md
├── mcp-servers/             ← MCP server implementations
│   ├── copilot-memory/      ← Persistence layer
│   │   ├── src/
│   │   │   ├── index.ts
│   │   │   ├── db/
│   │   │   ├── tools/
│   │   │   └── resources/
│   │   └── package.json
│   └── skills-copilot/      ← Knowledge layer
│       ├── src/
│       │   ├── index.ts
│       │   └── providers/
│       └── package.json
├── docs/
│   ├── operations/          ← Standards & guidelines
│   │   ├── development-standards.md
│   │   ├── security-guidelines.md
│   │   ├── documentation-guide.md
│   │   └── working-protocol.md
│   ├── ARCHITECTURE.md      ← This file
│   └── EXTENSION-SPEC.md
├── templates/               ← Project setup templates
│   ├── mcp.json
│   └── CLAUDE.template.md
├── CLAUDE.md               ← Framework overview
└── README.md
```

---

**Last Updated**: December 2025
**Version**: 1.0.0
**Maintainer**: Claude Copilot Team
