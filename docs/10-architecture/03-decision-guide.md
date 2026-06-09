# Decision Guide: When to Use What

A comprehensive guide to help you choose the right tools, commands, agents, and approaches in Claude Copilot.

*Note: This is the complete reference. For a quick overview integrated into Claude Code's instructions, see [CLAUDE.md](../../CLAUDE.md#quick-decision-guide).*

---

## Feature Selection

### Feature Comparison

| Feature | Invocation | Persistence | Best For | When NOT to Use |
|---------|------------|-------------|----------|-----------------|
| **Memory** | Auto | Cross-session | Context preservation, decisions, lessons | Short-term notes, temporary data |
| **Agents** | Protocol | Session | Expert tasks, complex work | Simple commands, quick tasks |
| **Skills** | Auto | On-demand | Reusable patterns, workflows | One-off solutions |
| **Commands** | Manual | Session | Quick shortcuts, workflows | Complex multi-step processes |
| **Extensions** | Auto | Permanent | Team standards, custom methodologies | Personal preferences |

### Memory vs Skills vs Extensions

| Question | Use Memory | Use Skills | Use Extensions |
|----------|------------|------------|----------------|
| Does it change per project? | ✓ | | |
| Is it a one-time decision? | ✓ | | |
| Is it a reusable pattern? | | ✓ | |
| Does the whole team need it? | | | ✓ |
| Is it company-specific? | | | ✓ |
| Does it override base behavior? | | | ✓ |
| Is it a lesson learned? | ✓ | | |
| Is it a workflow/automation? | | ✓ | |

---

## Command Selection

### Command Decision Matrix

| I want to... | Command | When | Where to Run |
|--------------|---------|------|--------------|
| Set up Claude Copilot first time | `/setup` | Once per machine | `~/.claude/copilot` |
| Add Copilot to new project | `/setup-project` | Once per project | Project root |
| Update project files | `/update-project` | After framework updates | Project root |
| Update framework itself | `/update-copilot` | When new version available | Any directory |
| Create team knowledge | `/knowledge-copilot` | Once per team/company | Any directory |
| Start fresh work | `/protocol [task]` | Each work session | Project root |
| Resume previous work | `/continue [stream]` | When returning to work | Project root |
| Run parallel work streams | `/orchestrate start` | Set up worktrees, launch via Task tool | Project root |
| Monitor orchestration | `/orchestrate status` | During parallel execution | Project root |
| Merge completed streams | `/orchestrate merge` | After streams complete | Project root |
| Verify CLIs installed | `cc version && tc version` | After setup, troubleshooting | Any directory |

**Command Arguments:**
- `/protocol <task>` - Auto-detect task type and route to agent (e.g., `/protocol fix the login bug`)
- `/continue <stream>` - Resume specific parallel stream (e.g., `/continue Stream-B`)

### Setup Command Flowchart

```
Are you using Claude Copilot for the first time?
├─ YES → Run /setup in ~/.claude/copilot
│        ↓
│        Is this a new project?
│        ├─ YES → Run /setup-project in project
│        └─ NO → Run /update-project in existing project
│
└─ NO → Did you update Claude Copilot?
        ├─ YES → Run /update-project in all projects
        └─ NO → Just use /protocol or /continue to work
```

---

## Agent Selection

### Agent Routing Matrix

| Task Type | Primary Agent | Secondary Agent(s) | Why This Flow |
|-----------|---------------|-------------------|---------------|
| **Bug Fix** | `qa` | → `me` | QA reproduces, Engineer fixes |
| **New Feature** | `sd` | → `uxd` → `uids` → `uid` → `ta` → `me` | Service → Design chain → Architecture → Code |
| **API Design** | `ta` | → `me` → `doc` | Architecture → Code → Docs |
| **Security Review** | (skill) | load `security/stride-dread` | Security skill, no dedicated agent |
| **Performance Issue** | `ta` | → `me` | Design analysis → Implementation |
| **UI Component** | `uxd` | → `uids` → `uid` → `me` | UX → Design system → Component → Implementation |
| **Documentation** | `doc` | | Technical writing |
| **Deployment** | `do` | | DevOps expertise |
| **Architecture Decision** | `ta` | | System design |
| **User Research** | `sd` | | Experience strategy |
| **Copy/Messaging** | `cw` | | Copywriter — copy execution, messaging, microcopy |

### Scenario-Based Agent Selection

| Scenario | Start With | Reasoning |
|----------|------------|-----------|
| "Users can't login" | `/protocol` (DEFECT) → `@agent-qa` | Needs reproduction and diagnosis |
| "Add dark mode" | `/protocol` (EXPERIENCE) → `@agent-sd` | Experience change requires journey analysis |
| "Optimize database queries" | `/protocol` (FEATURE) → `@agent-ta` | Architecture-level optimization |
| "Deploy to production" | `/protocol` (DEVOPS) → `@agent-do` | Infrastructure task |
| "Security audit" | load `security/stride-dread` skill | Security skill, not a dedicated agent |
| "Write API docs" | `/protocol` (DOCUMENTATION) → `@agent-doc` | Documentation specialist |
| "Refactor auth module" | `/protocol` (ARCHITECTURE) → `@agent-ta` | Design decision needed |
| "Fix button alignment" | `/protocol` (DEFECT) → `@agent-uxd` | UI interaction fix |

---

## Extension vs Override vs Skills

### Extension Type Decision Tree

```
Do you need to customize agent behavior?
├─ NO → Use base agents as-is
│
└─ YES → Do you want to replace the entire agent?
         ├─ YES → Use OVERRIDE (.override.md)
         │        Example: Completely custom methodology
         │
         └─ NO → Do you want to add/enhance sections?
                  ├─ YES → Use EXTENSION (.extension.md)
                  │        Example: Add checklists, templates
                  │
                  └─ NO → Do you just need to inject skills?
                           └─ Use SKILLS (.skills.json)
                                Example: Company-specific tools
```

### Extension Type Comparison

| Goal | Extension Type | File Pattern | Scope | Difficulty |
|------|----------------|--------------|-------|------------|
| Add company checklist | `extension` | `agent.extension.md` | Section merge | Easy |
| Replace methodology | `override` | `agent.override.md` | Full replacement | Hard |
| Inject team tools | `skills` | `agent.skills.json` | Skill list only | Medium |
| Enhance templates | `extension` | `agent.extension.md` | Section merge | Easy |
| Custom process flow | `override` | `agent.override.md` | Full replacement | Hard |
| Add domain knowledge | `skills` | `agent.skills.json` | Skill list only | Medium |

---

## Work Session Decisions

### Starting Work Decision Matrix

| Situation | Use | Why |
|-----------|-----|-----|
| Brand new task | `/protocol` or `/protocol <task>` | Classify and route to expert |
| Continuing yesterday's work | `/continue` | Load context from memory |
| Resume specific parallel stream | `/continue <stream>` | Jump directly to stream work |
| Quick question | Just ask | No need for protocol |
| Exploring ideas | Just ask | Protocol is for execution |
| Complex multi-step task | `/protocol` | Agent expertise needed |
| Resume after interruption | `/continue` | Context restoration |

### Protocol vs Direct Conversation

| Use /protocol When... | Use Direct Conversation When... |
|----------------------|--------------------------------|
| Building a feature | Asking a question |
| Fixing a bug | Exploring ideas |
| Making architecture changes | Getting quick help |
| Need expert guidance | Simple task |
| Multi-step process | Single action |
| Want structured approach | Want flexibility |

---

## Knowledge Repository Decisions

### When to Create Knowledge Repository

| Indicator | Action |
|-----------|--------|
| Team > 1 person | Create knowledge repo |
| Company has style guide | Document in knowledge repo |
| Custom methodologies | Create agent extensions |
| Repeated explanations | Document once in knowledge |
| Onboarding takes days | Create knowledge repo |
| Inconsistent outputs | Define standards in knowledge |

### Knowledge vs Skills vs Memory

| Type of Information | Store In | Why |
|---------------------|----------|-----|
| Company values | Knowledge | Permanent, team-wide |
| Voice/tone guidelines | Knowledge | Permanent, team-wide |
| Design system | Knowledge | Permanent, team-wide |
| Reusable code patterns | Skills | On-demand, reusable |
| Project decisions | Memory | Project-specific, temporal |
| Lessons learned | Memory | Project-specific, evolving |
| API standards | Knowledge | Team standard |
| Deployment process | Skills | Reusable workflow |
| Why we chose X | Memory | Project context |

---

## Stream Management Decisions

### When to Use Streams

| Scenario | Use Streams? | Why |
|----------|--------------|-----|
| Single developer, sequential work | No | Standard task flow is simpler |
| Multiple parallel work areas | Yes | Prevent file conflicts |
| Large feature with independent components | Yes | Parallel development |
| Bug fix while feature in progress | Yes | Isolate changes |
| Foundation → parallel → integration workflow | Yes | Enforce dependencies |

### Stream Pattern

**Foundation Phase:**
- Stream-A: Core infrastructure that parallel work depends on
- Example: Schema changes, base types, shared utilities

**Parallel Phase:**
- Stream-B, Stream-C, Stream-D: Independent work streams
- Each touches different files
- Can run simultaneously in separate Claude Code sessions
- Example: Stream-B (API endpoints), Stream-C (UI components), Stream-D (tests)

**Integration Phase:**
- Stream-Z: Combines parallel streams
- Example: Documentation, final validation, release prep

### Stream Tools Usage

| Command | When to Use | Example |
|------|-------------|---------|
| `tc stream list --json` | View all streams in initiative | See progress across parallel work |
| `tc stream get <id> --json` | Get detailed stream info | Check Stream-B status before resuming |
| `git diff` | Before creating tasks | Ensure no file conflicts with other streams |

### Stream Metadata in Tasks

When creating tasks with streams, include:

```typescript
metadata: {
  streamId: "Stream-B",           // Auto-generated ID
  streamName: "command-updates",  // Human-readable name
  streamPhase: "parallel",        // foundation | parallel | integration
  files: [                        // Files this task will modify
    "path/to/file1.ts",
    "path/to/file2.md"
  ],
  streamDependencies: ["Stream-A"] // Must complete before this stream
}
```

---

## Troubleshooting Decisions

### When Something Goes Wrong

| Problem | Check First | Then Try | Last Resort |
|---------|-------------|----------|-------------|
| Command not found | Machine setup complete? | `/setup` in `~/.claude/copilot` | Reinstall |
| `cc` or `tc` not found | Check PATH | Run `bash tools/cc/install.sh` | Check install script |
| Agent not routing | Is task description clear? | Rephrase request | Use agent directly |
| Memory not persisting | `cc config get paths.shared_docs` | `cc memory index --rebuild` | Check SQLite path |
| Knowledge not found | Symlink exists? | `/knowledge-copilot` | Manual link |
| Skills not loading | `cc skill list` returns results? | `cc config set paths.shared_docs <path>` | Check cc config |

---

## Quick Reference Tables

### Installation Decision Matrix

| You Are... | Steps Required | Commands to Run |
|------------|----------------|-----------------|
| New solo user | Clone → Setup → Project | `/setup` → `/setup-project` |
| New team member | Clone → Setup → Link Knowledge → Project | `/setup` → `/knowledge-copilot` → `/setup-project` |
| Existing user, new project | Project setup only | `/setup-project` |
| Updating framework | Update → Rebuild → Sync projects | `/update-copilot` → `/update-project` |

### Daily Workflow Matrix

| Beginning of Day | During Day | End of Day |
|------------------|------------|------------|
| `/continue` to resume | Work naturally with agents | `cc memory store` to save progress |
| Or `/protocol` for new task | Route complex work to specialists | Document decisions in memory |
| Run `cc doctor` if needed | Use skills as needed | Note lessons learned |

---

## Best Practices Summary

### Do This

| Context | Best Practice |
|---------|--------------|
| Starting work | Use `/continue` to load context |
| Complex tasks | Use `/protocol` to engage experts |
| Team standards | Create knowledge repository |
| Reusable patterns | Save as skills |
| Project decisions | Store in memory with context |
| End of session | Update initiative with progress |

### Don't Do This

| Anti-Pattern | Instead Do |
|--------------|-----------|
| Hardcode paths in extensions | Use relative paths |
| Store secrets in knowledge | Use environment variables |
| Override agents unnecessarily | Use extensions first |
| Skip memory updates | Update at end of session |
| Create skills for one-offs | Just solve the problem |
| Ignore agent routing | Trust the protocol |

---

## Decision Flowchart: Complete Setup

```
START: Do you have Claude Copilot installed?
│
├─ NO → Clone to ~/.claude/copilot
│       ↓
│       Run /setup in ~/.claude/copilot
│       ↓
│       Are you part of a team?
│       ├─ YES → Clone team knowledge repo
│       │        Run /knowledge-copilot to link
│       │        ↓
│       └─ NO → Do you want to create team knowledge?
│                ├─ YES → Run /knowledge-copilot
│                └─ NO → Skip knowledge setup
│       ↓
│       Run /setup-project in your project
│       ↓
│       Done! Use /protocol to start working
│
└─ YES → Is this a new project?
         ├─ YES → Run /setup-project
         │        ↓
         │        Done! Use /protocol to start working
         │
         └─ NO → Do you need to update?
                  ├─ YES → Run /update-project
                  └─ NO → Just use /protocol or /continue
```

---

## Related Documentation

| Topic | Document |
|-------|----------|
| Complete setup walkthrough | [User Journey](../01-getting-started/01-user-journey.md) |
| Extension specifications | [Extension Spec](../40-extensions/00-extension-spec.md) |
| Agent details | [Agents](01-agents.md) |
| Configuration options | [Configuration](../20-configuration/01-configuration.md) |
| Customization guide | [Customization](../20-configuration/02-customization.md) |
