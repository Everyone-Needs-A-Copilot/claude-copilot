# Validate Setup Script

A standalone script to validate your environment before running orchestration.

## Purpose

The `validate-setup.py` script performs comprehensive pre-flight checks to ensure your environment is ready for parallel orchestration. It catches common setup issues early, before you invest time creating PRDs and tasks.

## Location

```
~/.claude/copilot/templates/orchestration/validate-setup.py
```

Or copy it to your project:
```bash
cp ~/.claude/copilot/templates/orchestration/validate-setup.py .
```

## Usage

### Basic Usage

Run all checks:
```bash
python validate-setup.py
```

### Verbose Mode

Show detailed information for each check:
```bash
python validate-setup.py --verbose
```

### Automatic Fixes

Attempt to fix issues automatically (where possible):
```bash
python validate-setup.py --fix
```

## What It Checks

| Check | Description | Fix Available |
|-------|-------------|---------------|
| Python version | Ensures Python >= 3.8 | No |
| Claude CLI | Verifies Claude CLI in PATH and executable | No |
| Git version | Ensures Git >= 2.5 with worktree support | No |
| Git repository | Verifies current directory is a git repo | Yes |
| Directory permissions | Tests write access to project root | No |
| tc CLI | Verifies tc CLI is installed and accessible | No |
| MCP servers built | Checks node_modules exist for MCP servers | Yes |
| Orchestration templates | Verifies templates exist in framework | No |

## Exit Codes

- **0** - All checks passed, ready for orchestration
- **1** - One or more checks failed

Use in scripts:
```bash
if python validate-setup.py; then
    echo "Ready to orchestrate!"
    /orchestrate generate
else
    echo "Environment not ready"
    exit 1
fi
```

## Output Examples

### Success

```
🔧 Orchestration Setup Validation
============================================================

Checking environment...

✓ Python version
✓ Claude CLI
✓ Git version
✓ Git repository
✓ Directory permissions
✓ MCP configuration
✓ MCP servers built
✓ Orchestration templates

============================================================
✓ All 8 checks passed. Ready for orchestration!

Next steps:
  1. Run: /orchestrate generate
  2. Review generated streams
  3. Run: /orchestrate start
```

### Failure

```
🔧 Orchestration Setup Validation
============================================================

Checking environment...

✓ Python version
✗ Claude CLI
  Not found in PATH. Install from https://docs.anthropic.com/en/docs/claude-code
✓ Git version
✓ Git repository
✓ Directory permissions
✗ tc CLI
  Not found in PATH. Install with: pip install -e ~/.claude/copilot/tools/tc
✓ MCP servers built
✓ Orchestration templates

============================================================
✗ 2 check(s) failed

Failed checks:
  • Claude CLI: Not found in PATH. Install from https://docs.anthropic.com/en/docs/claude-code
  • tc CLI: Not found in PATH. Install with: pip install -e ~/.claude/copilot/tools/tc

Try running with --fix to attempt automatic repairs:
  python validate-setup.py --fix
```

### With Fixes

```
🔧 Orchestration Setup Validation
============================================================

Checking environment...

✓ Python version
✓ Claude CLI
✓ Git version
✗ Git repository
  Not a git repository
  → Attempting fix: Initialize git repository
  ✓ Fixed: Initialize git repository
✓ Git repository
✓ Directory permissions
✓ tc CLI
✗ MCP servers built
  Missing node_modules: copilot-memory
  → Attempting fix: Build copilot-memory
  ✓ Fixed: Build copilot-memory
✓ MCP servers built
✓ Orchestration templates

============================================================
✓ All 8 checks passed. Ready for orchestration!

Fix attempts: 2/2 succeeded

Next steps:
  1. Run: /orchestrate generate
  2. Review generated streams
  3. Run: /orchestrate start
```

## When to Run

### Before First Orchestration

Run once to verify environment:
```bash
python validate-setup.py --verbose
```

### After Framework Updates

After updating Claude Copilot:
```bash
cd ~/.claude/copilot
git pull
npm run rebuild

# Then validate
cd your-project
python ~/.claude/copilot/templates/orchestration/validate-setup.py
```

### When Troubleshooting

If orchestration fails to start:
```bash
python validate-setup.py --verbose --fix
```

### In CI/CD Pipelines

Validate environment in automated workflows:
```yaml
# .github/workflows/orchestration.yml
- name: Validate orchestration setup
  run: python validate-setup.py

- name: Run orchestration
  if: success()
  run: |
    /orchestrate generate
    /orchestrate start
```

## Comparison with orchestrate.py preflight

| Feature | validate-setup.py | orchestrate.py preflight |
|---------|-------------------|--------------------------|
| Python version | ✓ | - |
| Claude CLI | ✓ | ✓ |
| Git version | ✓ | ✓ |
| Git repository | ✓ | ✓ |
| Permissions | ✓ | ✓ |
| MCP config | ✓ | - |
| MCP servers | ✓ | - |
| Templates | ✓ | - |
| Task Copilot data | - | ✓ |
| Stream metadata | - | ✓ |
| Active workers | - | ✓ |
| When to run | Before setup | Before execution |
| Purpose | Environment setup | Runtime readiness |

**Use both:**
1. Run `validate-setup.py` once during initial setup
2. `orchestrate.py preflight` runs automatically before spawning workers

## Customization

Copy the script to your project and add custom checks:

```python
def check_custom_requirement(self) -> bool:
    """Check project-specific requirement."""
    # Your custom validation logic
    passed = my_check()

    return self.check(
        "Custom requirement",
        passed,
        "Error message if failed"
    )

# Add to run_all_checks():
def run_all_checks(self) -> bool:
    # ... existing checks ...
    self.check_custom_requirement()
    return self.checks_failed == 0
```

## Integration with /orchestrate

The `/orchestrate` command references this script in:

1. **Prerequisites section:**
   ```
   1. Validate environment (optional but recommended):
      python validate-setup.py --verbose
   ```

2. **Troubleshooting section:**
   ```
   ### Environment issues
   - Run validation first:
     python validate-setup.py --verbose --fix
   ```

## Support

If validation fails and you can't resolve the issue:

1. Run with verbose mode to see details:
   ```bash
   python validate-setup.py --verbose
   ```

2. Try automatic fixes:
   ```bash
   python validate-setup.py --fix
   ```

3. Check the specific error messages for resolution steps

4. Consult `.claude/commands/orchestrate.md` for troubleshooting

5. Check framework documentation in `docs/50-features/02-orchestration-workflow.md`
