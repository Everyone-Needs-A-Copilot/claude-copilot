---
name: specialist-agents
description: Use when you need specialist role guidance for architecture, engineering, QA, security, docs, devops, service design, UX, UI design, UI implementation, or industrial design in a Codex session or delegated subagent.
---

# Specialist Agents

This skill provides Codex-native specialist playbooks modeled on the original Claude Copilot team.

## Usage modes

### Local mode

Apply the specialist lens in the main session when the user did not ask for subagents.

### Delegated mode

If the user explicitly asked for delegation, pass the relevant specialist instructions into a `spawn_agent` task.

Keep prompts short. Give the subagent:

- the role
- the exact task
- the files or surface area it owns
- the expected output

## Roles

Read `references/agent-playbooks.md` and `references/shared-behaviors.md`, then load only the role section you need.

Core roles:

- `sd`
- `uxd`
- `uids`
- `uid`
- `ta`
- `me`
- `qa`
- `ind`
- `sec`
- `doc`
- `do`

## Quality gates

- `me` should not be the only gate on code correctness
- `qa` should verify implementation work
- `sec` should review security-sensitive changes
- design work should precede UI implementation when the problem is not already well-defined
