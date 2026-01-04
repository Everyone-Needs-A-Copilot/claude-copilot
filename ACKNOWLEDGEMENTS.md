# Acknowledgements

Claude Copilot builds upon the work of many talented developers and open source projects. We gratefully acknowledge the following sources that have inspired and informed this framework.

---

## Inspiration & Patterns

### Ralph Wiggum Iteration Pattern
**Source:** [github.com/anthropics/claude-code/tree/main/plugins/ralph-wiggum](https://github.com/anthropics/claude-code/tree/main/plugins/ralph-wiggum)

The iteration loop system in Task Copilot (Phase 2) is inspired by the Ralph Wiggum plugin's self-referential feedback loop pattern. This pattern enables autonomous, iterative task completion with intelligent stop conditions.

### claude-howto
**Source:** [github.com/luongnv89/claude-howto](https://github.com/luongnv89/claude-howto)
**Author:** [luongnv89](https://github.com/luongnv89)

Comprehensive Claude Code documentation and learning materials. Content has been incorporated into `docs/claude-howto-reference/` with permission. The multi-entry-point documentation approach significantly influenced our onboarding improvements.

### Alex's Claude Code Customization Guide
**Source:** [alexop.dev/posts/claude-code-customization-guide-claudemd-skills-subagents/](https://alexop.dev/posts/claude-code-customization-guide-claudemd-skills-subagents/)
**Author:** Alex

This detailed blog post on Claude Code customization patterns informed our documentation strategy and helped identify key developer needs around CLAUDE.md, skills, and subagents.

### Agent Skills for Context Engineering
**Source:** [github.com/muratcankoylan/Agent-Skills-for-Context-Engineering](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering)
**Author:** [muratcankoylan](https://github.com/muratcankoylan)

Comprehensive research on context engineering principles including attention budget awareness, the "lost-in-the-middle" phenomenon, and progressive disclosure patterns. This research directly informed our Attention Budget guidance in agent templates and work product compression strategies.

**Key Learnings:**
- Context windows are constrained by attention mechanics, not just token capacity
- U-shaped attention curves (high attention at start/end, low in middle)
- Front-loading critical decisions and back-loading action items
- Table-first writing for 25-50% token savings

### Awesome Agent Skills
**Source:** [github.com/heilcheng/awesome-agent-skills](https://github.com/heilcheng/awesome-agent-skills)
**Author:** [heilcheng](https://github.com/heilcheng)

Curated collection of AI agent skills with standardized SKILL.md format guidelines. This resource informed our skill size validation (500-line maximum) and progressive loading design (3-tier: index → summary → full).

**Key Learnings:**
- Skills as instruction bundles, not executable code
- 500-line maximum for maintainability
- Three-stage loading pattern for token efficiency
- Community contribution patterns for skill ecosystems

### Spec Kit
**Source:** [github.com/github/spec-kit](https://github.com/github/spec-kit)
**Author:** GitHub

Open-source toolkit for Spec-Driven Development introducing the "Constitution" concept for project governance. This directly inspired our CONSTITUTION.md template for defining project values, constraints, and decision authority.

**Key Learnings:**
- Constitution as persistent governance principles
- Separation of "what" (Constitution) from "how" (framework mechanics)
- 7-step workflow: Constitution → Specification → Clarification → Planning → Tasks → Implementation → Validation
- Agent-agnostic design patterns

---

## Context Engineering Research

The following projects provided key insights for our context engineering enhancements, including auto-compaction, continuation enforcement, and activation modes.

### Oh My OpenCode
**Source:** [github.com/code-yeongyu/oh-my-opencode](https://github.com/code-yeongyu/oh-my-opencode)
**Author:** [code-yeongyu](https://github.com/code-yeongyu)

An advanced agent harness for OpenCode with multi-agent orchestration and parallel execution. The project's disciplined approach to context management directly influenced our auto-compaction and continuation enforcement features.

**Key Learnings:**
- Todo Continuation Enforcer pattern (prevents agents from stopping mid-task)
- 85% context threshold for preemptive compaction
- Aggressive delegation to specialized agents
- Context intelligence strategies (dynamic pruning, tool output truncation)

### MCP Shrimp Task Manager
**Source:** [github.com/cjo4m06/mcp-shrimp-task-manager](https://github.com/cjo4m06/mcp-shrimp-task-manager)
**Author:** [cjo4m06](https://github.com/cjo4m06)

A task management tool for AI agents emphasizing chain-of-thought, reflection, and style consistency. The structured workflow approach influenced our quality gates and project rules implementation.

**Key Learnings:**
- Persistent memory patterns for tasks across sessions
- Project rules initialization workflow
- Research mode for systematic exploration
- Smart task decomposition with dependency tracking

### BMAD Method
**Source:** [github.com/bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD)
**Author:** [bmad-code-org](https://github.com/bmad-code-org)

Breakthrough Method for Agile AI Driven Development with 21 specialized agents and 50+ guided workflows. The agent customization patterns informed our extension system and activation modes.

**Key Learnings:**
- Agent customization without modifying core files
- Keyword-based activation modes for different work intensities
- Battle-tested workflows for agile development
- Expansion pack isolation patterns

---

## Standards & Specifications

### Model Context Protocol (MCP)
**Source:** [github.com/modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers)

Reference implementations for MCP servers. Our Memory Copilot, Skills Copilot, and Task Copilot MCP servers follow patterns established by the official MCP server examples.

### Contributor Covenant
**Source:** [contributor-covenant.org](https://www.contributor-covenant.org/)

Our Code of Conduct is adapted from the Contributor Covenant, version 2.0.

### Keep a Changelog
**Source:** [keepachangelog.com](https://keepachangelog.com/en/1.1.0/)

Our CHANGELOG.md follows the Keep a Changelog format specification.

---

## Tools & Libraries

The MCP servers in this framework use the following open source libraries:

- **[@modelcontextprotocol/sdk](https://www.npmjs.com/package/@modelcontextprotocol/sdk)** - Official MCP SDK
- **[better-sqlite3](https://www.npmjs.com/package/better-sqlite3)** - SQLite database driver
- **[zod](https://www.npmjs.com/package/zod)** - TypeScript schema validation
- **[ajv](https://www.npmjs.com/package/ajv)** - JSON Schema validator

---

## Contributors

Thank you to all contributors who have helped build Claude Copilot. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to get involved.

---

*If we've missed acknowledging your work, please open an issue or pull request.*
