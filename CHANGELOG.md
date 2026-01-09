# Changelog

All notable changes to Claude Copilot will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.0.0] - 2026-01-08

### Added

- **Parallel Stream Orchestration**: Run multiple Claude sessions simultaneously
  - `/orchestrate` command for headless parallel execution
  - `start-streams.py` template for automated stream management
  - `watch-status.py` for real-time terminal monitoring
  - Foundation → Parallel → Integration phase workflow
  - Automatic stream conflict detection

- **WebSocket Bridge**: New MCP server for real-time event streaming
  - `mcp-servers/websocket-bridge/` with JWT authentication
  - Live task status updates across sessions
  - Event subscription and filtering
  - Integration with Task Copilot events

- **HTTP API for Task Copilot**: REST endpoints for external integration
  - `/api/tasks`, `/api/streams`, `/api/activity`, `/api/checkpoints`
  - Python client library (`task_copilot_client.py`)
  - Enables dashboard and monitoring tools

- **New Project Commands** (5 new commands):
  - `/map` - Generate PROJECT_MAP.md with codebase analysis
  - `/pause [reason]` - Create checkpoint for context switching
  - `/orchestrate` - Parallel stream management
  - `/memory` - View current initiative state
  - `/extensions` - List agent extensions

- **Enhanced Pause/Resume**: Extended checkpoint expiry for manual pauses
  - `/pause` creates 7-day checkpoints (vs 24h for auto)
  - `/continue` checks pause checkpoints first
  - Named checkpoints with reason tracking

- **Progress Visibility Enhancements**:
  - ASCII progress bars in `progress_summary`
  - Velocity trends (7d/14d/30d) with directional indicators
  - Milestone tracking in PRDs

- **Worktree Conflict Handling**:
  - `worktree_conflict_status` tool
  - `worktree_conflict_resolve` tool
  - Git worktree manager utilities

### Changed

- **Major Version Bump**: 1.8.0 → 2.0.0 reflecting paradigm shift to parallel orchestration
- **Update Project Command**: Now copies 8 project commands (was 2)
- All MCP servers aligned to version 2.0.0

### Technical

- 18,246 lines of new code
- 91 compiled JavaScript files across 4 MCP servers
- 28 integration tests passing
- New event bus architecture in Task Copilot

## [1.7.1] - 2026-01-05

### Added

- **Stream Auto-Archive**: Streams automatically archive when switching initiatives
  - Prevents stream pollution when using `/continue` across different initiatives
  - `stream_list` and `stream_get` filter archived streams by default
  - Use `includeArchived: true` parameter to view archived streams
- **Stream Recovery Tools**:
  - `stream_unarchive`: Recover an archived stream to make it active again
  - `stream_archive_all`: One-time cleanup for legacy streams (requires `confirm: true`)
- **Task Protection**: Archived tasks cannot be updated (clear error with recovery instructions)

### Changed

- `initiative_link` now auto-archives streams from previous initiative when switching
- Database schema v6: Added `archived`, `archived_at`, `archived_by_initiative_id` columns to tasks table
- Updated `/continue` command documentation with archived stream handling

### Migration

After updating from pre-1.7.1, optionally run `stream_archive_all({ confirm: true })` once to clean up existing streams. Without this, legacy streams remain visible until you naturally switch initiatives.

## [1.7.0] - 2026-01-04

### Added

- **Context Engineering Features**: 6 enhancements from community research
  - **Self-improving Memory Schema**: Agents can store improvement suggestions via `agent_improvement` memory type with structured metadata (agentId, targetSection, currentContent, suggestedContent, rationale, status)
  - **Quality Gates Configuration**: Project-level `.claude/quality-gates.json` enforces automated checks (tests, lint, build) before task completion
  - **Activation Mode Detection**: Auto-detects work intensity from keywords in prompts (`quick`, `thorough`, `analyze`, `ultrawork`)
  - **Git Worktree Isolation**: Documentation and tooling for parallel stream development without merge conflicts
  - **Continuation Enforcement**: Agents must emit `<promise>COMPLETE</promise>` signals or be marked blocked
  - **Auto-compaction Threshold**: Agents auto-store work products at 85% context usage (3,482 tokens)
- **New Utilities**: Context engineering support
  - `context-monitor.ts`: Token estimation and threshold detection
  - `mode-detection.ts`: Keyword-based activation mode parsing
  - `continuation-guard.ts`: Promise-based completion validation
  - `quality-gates.ts`: Gate configuration and execution
  - `worktree-manager.ts`: Git worktree helpers for parallel streams
- **Enhanced Documentation**
  - `docs/ENHANCEMENT-FEATURES.md`: Comprehensive guide with user examples
  - Quick Start examples for activation modes, quality gates, worktrees
  - Updated README with Context Engineering feature row

### Changed

- All 12 agent files updated with "Automatic Context Compaction" section
- `/continue` command enhanced with worktree management documentation
- `/memory` command shows agent improvement suggestions
- `/protocol` command supports activation mode keywords

### Acknowledgements

- [oh-my-opencode](https://github.com/code-yeongyu/oh-my-opencode) by code-yeongyu (continuation enforcement, auto-compaction patterns)
- [mcp-shrimp-task-manager](https://github.com/cjo4m06/mcp-shrimp-task-manager) by cjo4m06 (quality gates, project rules)
- [BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) by bmad-code-org (activation modes, agent customization)

## [1.6.4] - 2025-12-31

### Security

- Updated `qs` dependency to 6.14.1 to fix CVE-2025-15284 (arrayLimit bypass DoS vulnerability)

## [1.6.3] - 2025-12-31

### Fixed

- Smoke test now validates actual agent structure (removed obsolete Identity/Decision Authority checks)
- Smoke test skips `.mcp.json` check in CI environments (file is gitignored)
- Updated CLAUDE.md "Required Agent Sections" to match current agent structure

## [1.6.2] - 2025-12-31

### Changed

- Added disclaimer to README clarifying no affiliation with Microsoft Copilot or GitHub Copilot

## [1.6.0] - 2025-12-30

### Added

- **Performance Tracking System**: Agent performance metrics and analytics
  - `agent_performance_get` tool to retrieve aggregated metrics by agent
  - Success rate, token usage, and validation tracking per agent
  - Performance database tables for historical analysis
  - Complexity-based filtering for targeted performance insights
- **Validation System**: Work product quality enforcement
  - `work_product_validate` tool with comprehensive quality checks
  - Validation status tracking (pending, passed, failed, skipped)
  - Quality gate enforcement before work product storage
  - Validation error reporting and remediation guidance
- **Checkpoint System**: Mid-task recovery capabilities
  - `checkpoint_create` tool for saving task state snapshots
  - `checkpoint_get` and `checkpoint_resume` for recovery workflows
  - `checkpoint_list` and `checkpoint_cleanup` for checkpoint management
  - Automatic expiry (24 hours for auto-checkpoints, 7 days for manual)
  - Sequence-based checkpoint ordering (max 5 per task)
- **Token Efficiency Enforcement**: Protocol-level guardrails
  - Critical rules in `/protocol` to prevent context bloat
  - Explicit prohibition of reading >3 files in main session
  - Mandatory delegation to framework agents for substantive work
  - Self-check requirements before every response
  - Framework vs generic agent guidance

### Changed

- Enhanced protocol enforcement with stricter token efficiency rules
- Updated all agent configurations to support performance tracking
- Improved Task Copilot database schema with new validation and performance tables

### Fixed

- Token usage optimization in agent routing and task management

## [1.5.0] - 2024-12-XX

### Added

- **New Commands**: Streamlined workflow management
  - `/memory` command to view current memory state and recent activity
  - `/extensions` command to list and manage agent extensions
- **Extension Support**: Enhanced agent customization
  - `extension_get` tool to retrieve agent extensions
  - `extension_list` tool to list all available extensions
  - `manifest_status` tool to check knowledge repository status
  - Section-level extension merging for flexible customization

### Changed

- **Simplified All 12 Agents**: Reduced each agent to ~60 lines
  - Streamlined agent structure for better maintainability
  - Focused agent responsibilities and clearer routing
  - Removed redundancy across agent definitions
- **Migrated to Task Copilot Exclusively**: Centralized task management
  - Removed `docs/tasks/` directory (tasks now stored in Task Copilot database)
  - All task tracking now uses Task Copilot MCP server
  - Eliminated file-based task management in favor of database persistence
- **Centralized Agent Routing**: Single source of truth
  - All routing logic moved to `protocol.md`
  - Consistent cross-agent routing rules
  - Removed duplicate routing tables from individual agents

### Removed

- `docs/tasks/` directory and file-based task tracking
- Redundant routing sections from individual agent files
- Duplicate decision matrices (consolidated in DECISION-GUIDE.md)

## [1.4.0] - 2024-11-XX

### Added

- **Task Copilot MCP Server**: Ephemeral task and work product storage
  - PRD management with `prd_create`, `prd_get`, `prd_list` tools
  - Task hierarchy with `task_create`, `task_update`, `task_get`, `task_list` tools
  - Work product storage with `work_product_store`, `work_product_get`, `work_product_list` tools
  - Progress tracking with `progress_summary` tool (~200 token summaries)
  - Initiative linking with `initiative_link` tool
  - Activity log for audit trail
  - Workspace-based database isolation
- **Framework-Wide Task Copilot Integration**: 96% context reduction
  - All 12 agents updated to store work products instead of returning to main session
  - Agent responses now return only summaries (~100-200 tokens)
  - Full work products stored in Task Copilot database
  - Clear guidance on when to use Task Copilot vs returning to session

### Changed

- Updated agent workflows to leverage Task Copilot for all detailed outputs
- Enhanced protocol to enforce Task Copilot usage patterns
- Improved memory efficiency across all agent interactions

## [1.3.0] - 2024-10-XX

### Added

- **Skills Copilot MCP Server**: On-demand skill and knowledge loading
  - `skill_get`, `skill_search`, `skill_list`, `skill_save` tools
  - `knowledge_search` and `knowledge_get` tools for documentation access
  - Two-tier resolution (project-level → machine-level)
  - Support for public skill marketplace (25,000+ skills)
  - Private skill storage in SQLite database
- **Knowledge Repository System**: Shared documentation framework
  - `/knowledge-copilot` command for repository setup
  - Global knowledge repository at `~/.claude/knowledge`
  - Project-specific knowledge via `KNOWLEDGE_REPO_PATH`
  - Knowledge manifest schema and validation

### Changed

- Enhanced agent system with automatic skill loading
- Improved documentation search across project and global sources

## [1.2.0] - 2024-09-XX

### Added

- **Extension System**: Agent customization via knowledge repositories
  - Override extensions (full agent replacement)
  - Extension type extensions (section-level merging)
  - Skills injection for specialized capabilities
  - Two-tier extension resolution (project → global → base)
  - `EXTENSION-SPEC.md` documentation

### Changed

- Agent loading system now supports extensions
- Updated agent structure to support extension merging

## [1.1.0] - 2024-08-XX

### Added

- **12 Specialized Agents**: Complete team of development specialists
  - `@agent-ta` (Tech Architect): System design and architecture
  - `@agent-me` (Engineer): Code implementation
  - `@agent-qa` (QA Engineer): Testing and quality assurance
  - `@agent-sec` (Security): Security review and threat modeling
  - `@agent-doc` (Documentation): Technical writing
  - `@agent-do` (DevOps): CI/CD and infrastructure
  - `@agent-sd` (Service Designer): Experience strategy
  - `@agent-uxd` (UX Designer): Interaction design
  - `@agent-uids` (UI Designer): Visual design
  - `@agent-uid` (UI Developer): UI implementation
  - `@agent-cw` (Copywriter): Content and microcopy
  - `@agent-kc` (Knowledge Copilot): Knowledge repository setup
- **Agent-First Protocol**: Structured workflow enforcement
  - `/protocol` command for fresh work sessions
  - Automatic agent routing based on request type
  - Protocol declaration requirements for all responses
- **Core Commands**: Project lifecycle management
  - `/setup-project` for new project initialization
  - `/update-project` for syncing with latest framework
  - `/update-copilot` for framework updates
  - `/continue` for session resumption

### Changed

- Enhanced routing between agents based on expertise
- Improved agent decision authority documentation

## [1.0.0] - 2024-07-XX

### Added

- **Memory Copilot MCP Server**: Persistent cross-session memory
  - `initiative_get`, `initiative_start`, `initiative_update`, `initiative_complete` tools
  - `memory_store` and `memory_search` tools with semantic search
  - SQLite-based storage with vector embeddings
  - Workspace isolation based on project path
  - `WORKSPACE_ID` support for explicit workspace management
- **Core Framework Structure**: Base installation and configuration
  - `.claude/` directory structure for agents and commands
  - `.mcp.json` configuration for MCP servers
  - `CLAUDE.md` project instructions
  - `/setup` command for machine-level initialization
- **Documentation**: Comprehensive guides and references
  - `README.md` with quick start guide
  - `SETUP.md` for manual installation
  - `PHILOSOPHY.md` explaining framework rationale
  - `ARCHITECTURE.md` for technical deep dive
  - `DECISION-GUIDE.md` with decision matrices
  - `USER-JOURNEY.md` for complete setup walkthrough

### Security

- No Time Estimates Policy implemented across all outputs
  - Prohibition of hours, days, weeks, months, quarters in all agent outputs
  - Enforcement through protocol and validation
  - Alternative phrasing using phases, priorities, complexity, dependencies

## [0.9.0] - 2024-06-XX (Beta)

### Added

- Initial beta release for testing
- Basic agent framework prototype
- Memory persistence proof of concept

---

## Version History Summary

| Version | Release Date | Key Features |
|---------|-------------|--------------|
| **1.7.0** | 2026-01-04 | Context engineering: activation modes, auto-compaction, quality gates |
| **1.6.0** | 2025-12-30 | Performance tracking, validation system, checkpoints, token efficiency |
| **1.5.0** | 2024-12-XX | Simplified agents, Task Copilot migration, centralized routing |
| **1.4.0** | 2024-11-XX | Task Copilot MCP server, 96% context reduction |
| **1.3.0** | 2024-10-XX | Skills Copilot, knowledge repositories |
| **1.2.0** | 2024-09-XX | Extension system for agent customization |
| **1.1.0** | 2024-08-XX | 12 specialized agents, Agent-First Protocol |
| **1.0.0** | 2024-07-XX | Memory Copilot, core framework structure |
| **0.9.0** | 2024-06-XX | Beta release |

---

## Migration Guides

### Upgrading from 1.5.x to 1.6.0

**Action Required:**

1. **Update Protocol Usage**: Review new token efficiency rules in `/protocol`
2. **Validate Work Products**: New validation system may flag quality issues
3. **Performance Metrics**: Optionally enable performance tracking for agents

**Database Changes:**

- New tables: `performance_tracking`, `work_product_validations`, `checkpoints`
- Automatic migration on first run
- No data loss expected

**Breaking Changes:**

- None

### Upgrading from 1.4.x to 1.5.0

**Action Required:**

1. **Migrate File-Based Tasks**: Move any tasks from `docs/tasks/` to Task Copilot
2. **Update Agent References**: Simplified agents may have different routing
3. **Review Extension Usage**: Extension system enhanced in this release

**Breaking Changes:**

- `docs/tasks/` directory removed (use Task Copilot exclusively)
- Agent file structure changed (~60 lines each vs previous verbosity)

### Upgrading from 1.3.x to 1.4.0

**Action Required:**

1. **Install Task Copilot**: Add to `.mcp.json` configuration
2. **Configure TASK_DB_PATH**: Set storage location for task database
3. **Update Agent Workflows**: Agents now use Task Copilot automatically

**Breaking Changes:**

- None (additive release)

---

## Support

For issues, questions, or contributions:

- **Issues**: [GitHub Issues](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/issues)
- **Discussions**: [GitHub Discussions](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/discussions)
- **Documentation**: [docs/](docs/)

---

## Contributors

Thank you to all contributors who have helped build Claude Copilot!

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

---

[unreleased]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v1.7.0...HEAD
[1.7.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v0.9.0...v1.0.0
[0.9.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/releases/tag/v0.9.0
