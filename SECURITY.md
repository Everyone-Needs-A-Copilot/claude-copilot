# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x.x   | :white_check_mark: |

## Reporting a Vulnerability

We take the security of Claude Copilot seriously. If you discover a security vulnerability, please follow these steps:

### Where to Report

Please **DO NOT** open a public GitHub issue for security vulnerabilities.

Instead, report security issues via:

1. **GitHub Security Advisory:** [Create a private security advisory](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/security/advisories/new)

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if available)

### Response Timeline

- **Initial Response:** Within 48 hours
- **Status Update:** Within 7 days
- **Fix Timeline:** Depends on severity
  - Critical: Within 7 days
  - High: Within 30 days
  - Medium: Within 90 days
  - Low: Next planned release

## Security Best Practices for Users

1. **Never commit secrets:** Keep API keys and database credentials in environment variables
2. **Use absolute paths:** The `~` tilde does NOT expand in MCP server arguments
3. **Don't commit .mcp.json:** This file may contain API keys - it's gitignored by default
4. **Validate extensions:** Only load extensions from trusted knowledge repositories
5. **Keep dependencies updated:** Run `npm audit` regularly in MCP server directories
6. **Workspace isolation:** Each project gets its own database by default via path hashing

## Known Security Considerations

- **Local storage:** Memory databases are stored locally in `~/.claude/memory`
- **No authentication:** MCP servers run locally without authentication (by design for local-first architecture)
- **Extension trust:** Extensions can modify agent behavior - only use trusted sources
- **Environment variables:** Credentials should be passed via environment variables, not hardcoded

## Security Features

- Parameterized SQL queries prevent SQL injection
- Local-first architecture keeps data on your machine
- Isolated workspaces per project via WORKSPACE_ID
- SQLite WAL mode for safe concurrent access
