# Project Context - Claude Code Usage Monitor

*Last Updated: 2025-12-13*

## Current Status

| Item | Status |
|------|--------|
| Phase | Initial Development |
| Current Task | Human-centered development environment complete |
| Environment | Development |
| Tests | Not yet configured |

## Recent Changes

- [2025-12-13] Human-Centered Development Integration
  - Created `01-human-centered-development.md` philosophy doc
  - Renumbered all best practices files (claude-code-config is now 02)
  - Updated configuration guide with mandatory Human Advocate requirements
  - Created UX Designer profile, instructions, and subagent
  - Created UI Designer profile, instructions, and subagent
  - Updated Service Designer to route to UX Designer
  - Added full design trio (SD, UX, UI) to this project

- [2025-12-13] Set up AI-enabling development environment
  - Created `.claude/` directory structure (agents, reference, commands)
  - Updated CLAUDE.md with three-tier architecture
  - Created project context file
  - Added agent definitions
  - Created context-refs quick reference cards

## Environment Status

| Component | Status | Notes |
|-----------|--------|-------|
| Python | Ready | 3.9+ required |
| uv | Required | Package manager |
| Rich | Ready | Terminal UI library |
| pytest | Required | Install with dev dependencies |

## Active Development Areas

1. **Core Monitoring** (`src/claude_monitor/core/`)
   - Token usage calculations
   - ML-based predictions
   - Plan detection

2. **Data Handling** (`src/claude_monitor/data/`)
   - Claude usage data parsing
   - Agent data analysis

3. **UI Components** (`src/claude_monitor/ui/`)
   - Rich terminal interface
   - Layout management
   - Agent display panels

## Known Issues

*None currently tracked*

## Architecture Decisions

| Decision | Rationale | Date |
|----------|-----------|------|
| Human-centered development | Human Advocates have veto power on experience | 2025-12-13 |
| Full design trio (SD+UX+UI) | Terminal UI still serves humans, needs design thinking | 2025-12-13 |
| Three-tier CLAUDE.md | 85% token reduction per session | 2025-12-13 |
| Rich for UI | Terminal-native, no web server needed | Original |
| uv for packages | Fast, reliable Python package management | Original |

## Next Steps

1. [x] Complete agent definitions (all 6 agents configured)
2. [x] Create context reference cards
3. [x] Set up MCP server launcher
4. [ ] Configure pre-commit hooks
5. [ ] Write initial test suite
6. [ ] Run Service Designer to map developer journey
7. [ ] Run UX Designer to optimize terminal interaction
8. [ ] Run UI Designer to define Rich styling

## File Structure Map

```
.claude/
├── project-context.md    # This file
├── agents/
│   ├── sd.md                # Service Designer: journey mapping, blueprints
│   ├── uxd.md               # UX Designer: interaction design, task flows
│   ├── uids.md              # UI Designer: visual design, tokens, aesthetics
│   ├── architect.md         # Technical: system design
│   ├── engineer.md          # Technical: implementation
│   └── tester.md            # Technical: testing
├── reference/
│   └── development-rules.md  # Full development rules
└── commands/
    └── (custom slash commands)

docs/
├── context-refs/
│   ├── README.md
│   ├── architecture-quick.md
│   └── development-quick.md
└── shared-docs/
    └── 00-best-practices/
        ├── 01-human-centered-development.md  # Foundational philosophy
        ├── 02-claude-code-configuration.md   # AI environment setup
        └── ...
```

## Session Handoff Notes

**Human-Centered Environment Established:**
- Full design trio configured (Service Designer → UX Designer → UI Designer)
- Human Advocates have veto power on experience decisions
- Technical Implementers serve the human-centered vision
- Workflow: SD+Architect collaborate first, then parallel tracks, then integration

**Next Focus Areas:**
1. Run design agents to establish the developer experience vision
2. Then implement based on design agent outputs
3. Always route experience decisions through Human Advocates

**Key Philosophy:**
> "Software exists to serve humans. Every technical decision must answer to the human experience it enables."
