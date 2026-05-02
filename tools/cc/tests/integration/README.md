# cc Integration Tests

Self-contained integration tests that verify `cc` is correctly installed,
configured, and working in any git project directory.

## Quick start

Run the shell script (no dependencies beyond `bash`/`zsh` and `python3`):

```bash
bash tools/cc/tests/integration/run_integration_tests.sh
```

Run the pytest suite (requires the `cc` venv):

```bash
cd /path/to/claude-copilot
source tools/cc/.venv/bin/activate
pytest tools/cc/tests/integration/ -v
```

## Running against a different project

Both test runners work from any git repo:

```bash
# Shell script
cd /path/to/any-project
bash /path/to/tools/cc/tests/integration/run_integration_tests.sh

# Or pass project dir as argument
bash /path/to/run_integration_tests.sh /path/to/any-project

# Pytest
cd /path/to/any-project
pytest /path/to/tools/cc/tests/integration/ -v
```

## What each test covers

### Installation
- `cc --version` exits 0 from `/tmp` (confirms global install, not just in-venv)
- `cc` resolves on `PATH`

### Machine config
- `cc config list --scope machine` exits 0
- `cc env` outputs valid shell exports (`export CC_KEY="value"` format)

### Memory (project scope)
- `cc memory store` creates a UUID-named `.md` file in `.claude/memory/entries/`
- The `.md` file has valid YAML frontmatter with `id`, `type`, and `created` fields
- `cc memory search <keyword>` finds the stored entry
- `cc memory list --type context` shows the stored entry
- `.claude/memory/.gitignore` exists and contains `memory.db`
- `.claude/memory/entries/` directory exists and is tracked (has `.gitkeep` or entries)
- `cc memory delete --yes <id>` removes the `.md` file from disk

### Config
- `cc config list` exits 0 regardless of whether a project config exists
- If machine config has `shared_docs` set, `cc env` includes `CC_SHARED_DOCS`

### Skills
- `cc skill list` exits 0 (0 or more skills found is acceptable)

### Migration
- `cc memory migrate --status` exits 0

### MCP shim
- `cc mcp config` outputs valid JSON with a `cc` key containing `command` and `args`

## Cleanup

Both test runners clean up after themselves. Each memory entry created during
testing is tagged `cc-integration-test` so it can be identified and removed.
The shell script also runs a cleanup pass at the end for any leftover entries.

## Separation from unit tests

These integration tests live in `tests/integration/` and are excluded from the
default `pytest` run (which targets `tests/` with the unit tests only).

To run only unit tests:
```bash
pytest tools/cc/tests/ --ignore=tools/cc/tests/integration/
```

To run only integration tests:
```bash
pytest tools/cc/tests/integration/ -v
```
