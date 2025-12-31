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
