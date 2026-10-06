# Project CLAUDE.md Standard

The rules a project's `CLAUDE.md` follows under Claude Copilot. `templates/CLAUDE.template.md` implements this standard; project setup renders it into new projects.

## What CLAUDE.md is for

Claude Code loads `CLAUDE.md` into every session in full. It is advisory context, not configuration: nothing in it is enforced. Every line costs context in every session and competes for attention with every other line. So the file holds only what Claude cannot learn from the code, the tools, or the hooks, and what applies to most sessions in the project.

Enforcement belongs to hooks. Discovery belongs to Claude Code. Detail belongs to the files Claude reads on demand.

| Need | Where it belongs |
|------|------------------|
| Mandatory behavior (protocol, delegation, destructive-command guard, QA gate) | Hooks registered in `.claude/settings.json` by `cc settings-hook add` |
| What agents, skills, and commands exist | Their own frontmatter; Claude Code lists them automatically |
| Detailed procedure for one kind of task | The agent, skill, or command that does that task |
| Rules for one area of the codebase | A file in that area, or a path-scoped rule in `.claude/rules/` |
| Project rules shared with Codex | Stated in both `CLAUDE.md` and `AGENTS.md` (see below) |
| Brand, voice, offerings, methodology | Knowledge Copilot, read through `$CC_KNOWLEDGE_REPOS` |
| Durable decisions and lessons | `cc memory` |
| Live initiative state | `tc` |

## Required content

1. **Project identity:** name, one-line description, stack.
2. **Project Rules:** the project's own standing rules. This section comes first because it is the part only the project can supply.
3. **`## Claude Copilot`:** the exact heading the project inspector recognizes (`project_integration._verify_claude_entry`). Under it, one line per Copilot surface: agents and skills, session commands, `tc`, `cc memory`, `cc skill`, `cc docs`, and `cc doctor`.
4. **`## Knowledge Copilot`:** the `$CC_KNOWLEDGE_REPOS` walk and the canonical sub-paths from the organization tier's consumption contract.
5. **`## Optional Context`:** byte-identical to `.claude/agents/_shared/optional-context.md` (enforced by `tests/instructions/test-optional-context-surfaces.sh`).
6. **Task acceptance:** the `tc` evidence-binding summary between the `cse-evidence-v2` markers. The full contract lives in the `me` and `qa` agents.
7. **Standing Rules:** framework rules that hold over a user's request, currently the no-time-estimates rule.

## Prohibited content

- Tables of agents, skills, or commands. Claude Code already lists them, and a copied table drifts.
- The session protocol itself. The SessionStart hook injects it; copying it doubles the cost and creates two versions.
- References to retired surfaces: the `copilot-memory`, `skills-copilot`, and `task-copilot` MCP servers, their `memory_*`, `skill_*`, and `initiative_*` tools, `knowledge_search`, and `knowledge_get`.
- The singular `$CC_KNOWLEDGE_REPO` used for a sub-path lookup. It carries only the first tier.
- Absolute machine paths. Use `cc env` variables or project-relative paths.
- Time estimates of any kind.

## Size and form

- Target under 100 lines for the rendered template; a project's additions should keep the file under 200.
- Headings and short bullets. One paragraph or bullet per line, with no hard wraps (the pinned Optional Context block is the only exception).
- When a section grows past a few bullets for one kind of task, move it to an agent, skill, command, or `.claude/rules/` file and leave a one-line pointer.

## Project-defined agents

A project may define its own agents in `.claude/agents/` (for example a studio of domain specialists). The `## Claude Copilot` section declares them first-class so the protocol's framework-agents-only rule routes to them rather than around them. Name them by group, not one by one, since Claude Code lists them.

## Projects that also run Codex

Do not import a Codex Copilot `AGENTS.md` into `CLAUDE.md` with `@AGENTS.md`. Claude Code supports the import, but a Codex Copilot `AGENTS.md` carries Codex routing (`$skill` invocations, `spawn_agent` rules, Codex hook notes) that conflicts with Claude Copilot's agents and hooks. Instead, state the project's own rules in `CLAUDE.md`'s Project Rules section, add a rule that project rules change in both files together, and leave tool-specific content in each tool's file. Import `@AGENTS.md` only when it holds tool-neutral content.
