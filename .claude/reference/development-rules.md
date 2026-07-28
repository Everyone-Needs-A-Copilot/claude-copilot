# Development Rules Reference

*Last Updated: 2025-12-13*

> **Note**: This is the detailed reference document. For everyday development, see `CLAUDE.md` (universal rules) and `.claude/agents/` (domain-specific rules).

---

## 1. Critical Data & Safety

### Database Access
- Access production/staging databases via SSH tunnel only
- No local DB clones unless explicitly approved
- Document tunnel commands in project context

### Destructive Operations
- **FORBIDDEN** without explicit, documented approval AND backups:
  - `DROP`, `TRUNCATE`, `DELETE` (SQL)
  - `rm`, `del` (files)
  - Force push to main/master
- Backups required before schema changes

### File Archival (NO DELETION)
- **NEVER delete files** — move to `_archive/` directory instead
- Preserve directory structure in archive:
  ```bash
  mkdir -p _archive/path/to/
  mv path/to/file.ext _archive/path/to/file.ext
  ```
- Document archived files in `.claude/project-context.md`

---

## 2. No Timelines in Plans

**NEVER include** timeline estimates, week numbers, or day counts.

**Include instead**:
- Task dependencies (what must complete before what)
- Phase groupings (logical order)
- Priority ordering (what to do first)

---

## 3. Multi-Agent Policy

### Required Agents for Non-Trivial Work

**Minimum (Always)**:
- **Architect**: Plans approach, identifies affected systems
- **Developer/Engineer**: Implements the solution
- **Tester**: Writes tests, validates implementation

**Spawn as Needed**:
- **Security Agent**: Auth flows, data handling
- **Performance Agent**: Optimization, caching

### When to Skip Multi-Agent
- Single-line fixes (typos, obvious bugs)
- Documentation-only changes
- Configuration updates with no code changes

---

## 4. Context Management

### Read Context at Session Start
**ALWAYS** read `.claude/project-context.md` before beginning work.

### Update Context After Changes

**Auto-Update Triggers**:
- Parent task completed
- Environment status changed
- Architecture decision made
- Issue discovered or resolved
- Files created or archived

---

## 5. Task Management Protocol

### Stop-and-Ask Protocol

**After completing each sub-task**:
1. Mark sub-task complete in task list
2. Output: "Sub-task X.Y complete. Ready for X.Y+1?"
3. **WAIT** for user response
4. Do NOT continue until user confirms

**User Response Options**:
- `yes` / `y` / `go` → Continue
- `skip` → Skip to next
- `stop` → Pause
- `redo` → Redo current

### Parent Task Completion Sequence

When ALL sub-tasks are complete:
1. Run full test suite
2. Only if tests pass: stage changes
3. Clean up (remove debug code)
4. Commit with conventional format
5. Mark parent task complete
6. Update context file

---

## 6. Development Workflow

### Standard Commands

```bash
pytest                        # Run tests
pytest -x -q                  # Fast mode
ruff check src                # Lint
mypy src/claude_monitor       # Type check
black src && isort src        # Format
```

### Pre-Push Checklist
- [ ] Lint passes
- [ ] Build succeeds
- [ ] Type check passes
- [ ] Tests pass
- [ ] No debug code

---

## 7. Git Commit Standards

### Conventional Commits Format

**Format**: `<type>(<scope>): <description>`

| Type | Use For |
|------|---------|
| `feat` | New feature |
| `fix` | Bug fix |
| `refactor` | Code restructuring |
| `docs` | Documentation |
| `test` | Tests |
| `chore` | Maintenance |
| `perf` | Performance |
| `style` | Formatting |

### Multi-line Format
```bash
git commit -m "feat(api): add health check" \
           -m "- Added /health route" \
           -m "- Returns status" \
           -m "Related to Task 2.0"
```

---

## 8. Error Handling Standards

### Correlation IDs
Every request should have a correlation ID for tracing.

### Structured Logging
Use key-value pairs, not string interpolation:
```python
# Good
logger.info("user_created", user_id=123, source="api")

# Bad
logger.info(f"Created user {user_id}")
```

### Retry Logic Pattern
- **Attempts**: 3
- **Backoff**: Exponential (2s, 4s, 8s)
- **Apply to**: External API calls, network operations
- **Do NOT retry**: Auth failures, validation errors

---

## 9. Security & Secrets

- Secrets in env vars only; never committed
- Verify `.env` is in `.gitignore`
- Mask secrets in logs (show only first/last 4 chars)
- Input validation on all external data

---

## 10. Quick Reference Checklist

### Before Starting Work
- [ ] Read `.claude/project-context.md`
- [ ] Check task list for next item
- [ ] Confirm environment ready

### After Sub-Task
- [ ] Mark complete in task list
- [ ] Report completion and wait

### After Parent Task
- [ ] Run full test suite
- [ ] Clean up temp/debug code
- [ ] Commit with conventional format
- [ ] Update context file

### File Operations
- [ ] Create files as needed
- [ ] **NEVER delete** — archive instead
- [ ] Document archived files
