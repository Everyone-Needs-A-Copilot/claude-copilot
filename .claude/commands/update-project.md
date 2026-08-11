# Update Project

Update an existing Claude Copilot project with the latest files. This command only works on projects that have already been set up.

## Step 1: Verify This Is an Existing Project

A set-up project has a `.claude/` directory with framework commands and/or agents.
(`.mcp.json` is NOT a reliable marker: memory and skills moved to the `cc`/`tc`
CLIs in v5.0.0, so many set-up projects legitimately have no `.mcp.json`.)

```bash
if [ -d .claude ] && { ls .claude/commands/*.md >/dev/null 2>&1 || ls .claude/agents/*.md >/dev/null 2>&1; }; then
  echo "PROJECT_EXISTS"
else
  echo "NEW_PROJECT"
fi
```

**If NEW_PROJECT:**

Stop and tell the user:

---

**This project hasn't been set up yet.**

No `.claude/` framework files found - this project needs initial setup first.

To set up this project with Claude Copilot, use:

```
/setup-project
```

---

Then STOP. Do not continue.

**If PROJECT_EXISTS:** Continue to Step 2.

---

## Step 2: Verify Machine Setup

```bash
which cc >/dev/null 2>&1 && echo "CC_CLI_OK" || echo "CC_CLI_MISSING"
which tc >/dev/null 2>&1 && echo "TC_CLI_OK" || echo "TC_CLI_MISSING"
```

**If any MISSING:**

Tell user:

---

**Claude Copilot CLIs not found.**

One or more required CLIs (`cc`, `tc`) are missing.

Please run machine setup first:
```bash
cd ~/.claude/copilot
/setup
```

Or install manually:
```bash
bash ~/.claude/copilot/tools/cc/install.sh
pip install -e ~/.claude/copilot/tools/tc
```

---

Then STOP.

---

## Step 3: Check for Broken Symlinks

**CRITICAL:** Regular `ls` passes for broken symlinks. Must check if target exists.

```bash
# `2>/dev/null` inside a `for ... in LIST` word list is a hard parse error
# in BOTH bash and zsh -- redirection is not valid mid-list there --
# verified live; this block never actually ran under either shell as
# originally written. Fixed by dropping it and instead making an empty
# glob expand to zero words (nullglob) rather than the unmatched
# pattern's literal text (bash's default) or a hard abort (zsh's default
# -- verified live: an unmatched glob here made zsh exit the whole script
# with "no matches found").
if [ -n "${ZSH_VERSION:-}" ]; then
  setopt NULL_GLOB
elif [ -n "${BASH_VERSION:-}" ]; then
  shopt -s nullglob
fi

echo "=== Checking commands for broken symlinks ==="
BROKEN_FOUND=0
for f in .claude/commands/*.md; do
  if [ -L "$f" ] && [ ! -e "$f" ]; then
    echo "BROKEN_SYMLINK: $f"
    BROKEN_FOUND=1
  fi
done

echo "=== Checking agents for broken symlinks ==="
for f in .claude/agents/*.md; do
  if [ -L "$f" ] && [ ! -e "$f" ]; then
    echo "BROKEN_SYMLINK: $f"
    BROKEN_FOUND=1
  fi
done

if [ $BROKEN_FOUND -eq 0 ]; then
  echo "No broken symlinks found"
fi
```

Note any broken symlinks found - they will be fixed in the update.

---

## Step 4: Show Current State

```bash
echo "=== Current Commands ==="
ls -la .claude/commands/*.md 2>/dev/null | head -5

echo "=== Current Agents ==="
ls .claude/agents/*.md 2>/dev/null | wc -l
echo "agent files"

echo "=== Claude Copilot Version ==="
cd ~/.claude/copilot && git log --oneline -1
```

---

## Step 5: Confirm Update

Tell the user:

---

**Ready to update project**

This will refresh:
- `.claude/commands/` (the full project-command set: protocol, continue, pause, map, memory, extensions, orchestrate)
- `.claude/agents/` (the full framework agent roster from VERSION.json, plus kc setup-only — roster-aware: preserves project-specific agents, removes retired agents)
- `.claude/hooks/copilot-hook.sh` (the enforcement hook shim, re-vendored and re-registered)
- `copilot.lock.json` (the `claude` component entry, regenerated from what's actually installed — never a copied template; other components and any mutation ledger are preserved)
- `.claude/orchestrator/` (if present — retired Python scripts will be removed)

This will NOT touch:
- `CLAUDE.md` (your project instructions)
- `.claude/skills/` (your project skills)
- Project-specific agent files (only framework-owned agents from VERSION.json roster are updated)
- `.mcp.json` (any third-party MCP servers you added manually are left untouched)

---

Use AskUserQuestion:

**Question:** "Proceed with update?"
- Header: "Confirm"
- Options:
  - "Yes, update now"
  - "No, cancel"

**If cancelled:** Stop and tell user "Update cancelled."

---

## Step 6: Update Commands

Remove old command files and copy fresh ones:

```bash
# Remove old project commands
rm -f .claude/commands/protocol.md 2>/dev/null
rm -f .claude/commands/continue.md 2>/dev/null
rm -f .claude/commands/pause.md 2>/dev/null
rm -f .claude/commands/map.md 2>/dev/null
rm -f .claude/commands/memory.md 2>/dev/null
rm -f .claude/commands/extensions.md 2>/dev/null
rm -f .claude/commands/orchestrate.md 2>/dev/null

# Copy fresh from source (all project-level commands)
cp ~/.claude/copilot/.claude/commands/protocol.md .claude/commands/
cp ~/.claude/copilot/.claude/commands/continue.md .claude/commands/
cp ~/.claude/copilot/.claude/commands/pause.md .claude/commands/
cp ~/.claude/copilot/.claude/commands/map.md .claude/commands/
cp ~/.claude/copilot/.claude/commands/memory.md .claude/commands/
cp ~/.claude/copilot/.claude/commands/extensions.md .claude/commands/
cp ~/.claude/copilot/.claude/commands/orchestrate.md .claude/commands/

echo "Commands updated ($(ls .claude/commands/*.md 2>/dev/null | wc -l | tr -d ' ') project commands)"
```

---

## Step 7: Update Agents (Roster-Aware Sync)

Refresh only framework-owned agents; preserve any project-specific agents.

**Project-owned agent override:** If an existing agent file contains `owner: project` in its frontmatter, sync will never overwrite or remove it — even if its name appears in the framework roster. To override a framework agent at the project level, add `owner: project` to its frontmatter.

```bash
COPILOT_PATH=~/.claude/copilot

# Read framework agent roster from VERSION.json. One agent id PER LINE --
# never space-joined -- so every loop below reads it with `while read`
# instead of relying on word-splitting an unquoted scalar. bash splits an
# unquoted `$ROSTER`/`$RETIRED` on IFS whitespace by default; zsh does
# NOT, so `for agent in $ROSTER` (and the `$RETIRED` loop, and the nested
# `for a in $ROSTER` below) each silently ran ONCE with the entire list
# as a single value under zsh (this machine's login shell) -- every agent
# copy/removal was a silent no-op, while this step still reported success
# with its own freshly-computed counts. Verified live under both shells.
ROSTER=$(python3 -c "
import json, sys
with open('$COPILOT_PATH/VERSION.json') as f:
    v = json.load(f)
agents = list(v['components']['agents']['frameworkAgents'])
agents.append('kc')  # setup-only agent; VERSION.json's frameworkAgents deliberately excludes it
print('\n'.join(agents))
" 2>/dev/null || printf '%s\n' cco cpa cs cw do doc ind kc me qa sd sec ta uid uids uxd)

# Also read retired agents list to remove any stale copies
RETIRED=$(python3 -c "
import json, sys
with open('$COPILOT_PATH/VERSION.json') as f:
    v = json.load(f)
retired = v['components']['agents'].get('retired', [])
print('\n'.join(retired))
" 2>/dev/null || printf '%s\n' design)

# Remove retired agents from project (they should not remain)
# Exception: never remove an agent marked owner: project
# `while read` off a herestring (not a pipe) runs in THIS shell, not a
# subshell, and is correct under both bash and zsh regardless of
# word-splitting settings, since it never relies on unquoted splitting.
while IFS= read -r agent; do
  [ -z "$agent" ] && continue
  if [ -f ".claude/agents/${agent}.md" ]; then
    if grep -q '^owner: project' ".claude/agents/${agent}.md" 2>/dev/null; then
      echo "preserved project-owned agent: ${agent} (skipping retired-agent removal)"
    else
      rm -f ".claude/agents/${agent}.md"
      echo "Removed retired agent: ${agent}.md"
    fi
  fi
done <<< "$RETIRED"

# Refresh framework-owned agents only (preserve project-specific agents)
# Convention: if an existing agent file has frontmatter "owner: project", skip it
UPDATED=0
PROJECT_OWNED_SKIPPED=""
while IFS= read -r agent; do
  [ -z "$agent" ] && continue
  if [ -f "$COPILOT_PATH/.claude/agents/${agent}.md" ]; then
    existing=".claude/agents/${agent}.md"
    if [ -f "$existing" ] && grep -q '^owner: project' "$existing" 2>/dev/null; then
      echo "preserved project-owned agent: ${agent}"
      PROJECT_OWNED_SKIPPED="$PROJECT_OWNED_SKIPPED $agent"
    else
      cp "$COPILOT_PATH/.claude/agents/${agent}.md" ".claude/agents/"
      UPDATED=$((UPDATED + 1))
    fi
  fi
done <<< "$ROSTER"

# Report any project-specific agents that were preserved
echo "Framework agents refreshed: $UPDATED"
[ -n "$PROJECT_OWNED_SKIPPED" ] && echo "Project-owned agents preserved (owner: project):$PROJECT_OWNED_SKIPPED"
PRESERVED=$(ls .claude/agents/*.md 2>/dev/null | while IFS= read -r f; do
  name=$(basename "$f" .md)
  is_framework=0
  while IFS= read -r a; do
    [ "$a" = "$name" ] && is_framework=1 && break
  done <<< "$ROSTER"
  [ $is_framework -eq 0 ] && echo "$name"
done | tr '\n' ' ')
[ -n "$PRESERVED" ] && echo "Project-specific agents preserved: $PRESERVED"

echo "Agents updated (roster-aware)"
```

---

## Step 7B: Refresh Enforcement Hook

Re-vendor the enforcement hook shim and re-register it in `.claude/settings.json`. Safe to run every time this command runs: the copy is byte-identical when the framework source hasn't changed, and `cc settings-hook add` is idempotent (a matching registration reports "unchanged" and writes nothing).

```bash
mkdir -p .claude/hooks
cp ~/.claude/copilot/.claude/hooks/copilot-hook.sh .claude/hooks/copilot-hook.sh
chmod +x .claude/hooks/copilot-hook.sh

cc settings-hook add
```

**Verify:**
```bash
ls -la .claude/hooks/copilot-hook.sh
```

---

## Step 7C: Regenerate Project Lock (claude component)

Regenerate `copilot.lock.json`'s `claude` component entry from what this update just put on disk -- real per-path sha256 checksums computed here, never a value copied from the framework source or another project's lock (RC-4: `projects.generate_component_lock_entry()`). A repo whose agents/commands/hook were just refreshed above but whose lock was never regenerated would still carry a stale or templated lock -- this closes that gap on every `/update-project` run, not just at initial setup. A candidate path whose own frontmatter declares `owner: project` is never recorded as framework-owned -- that exclusion lives inside the generator itself, so `preflight-copilot`/`voice-copilot`/`spanish-copilot`/`sproutworks`/`TSM/h3`-style hand-authored agents stay out of the lock's `files[]` automatically, exactly like Step 7's copy/remove loops above already leave the files themselves untouched. This step reads back any existing `copilot.lock.json` first (any `mutations[]` ledger, any `codex` component entry) and only replaces the `claude` entry -- everything else in the file is preserved untouched.

This step is self-contained (recomputes the agent roster from `VERSION.json` itself rather than reusing Step 7's `$ROSTER`): each fenced command block in this file may run as its own shell invocation, so nothing here depends on shell state set by an earlier step.

```bash
COPILOT_PATH=~/.claude/copilot
python3 -c "
import json
from pathlib import Path
from cc.core.ecosystem.projects import (
    generate_component_lock_entry,
    read_project_lock,
    write_project_lock,
    PROJECT_LOCK_FILENAME,
)

copilot_path = Path('$COPILOT_PATH').expanduser()
with open(copilot_path / 'VERSION.json') as f:
    v = json.load(f)
roster = list(v['components']['agents']['frameworkAgents'])
roster.append('kc')  # setup-only agent; VERSION.json's frameworkAgents deliberately excludes it
version = v.get('framework', 'unknown')
release_tag = ('v' + version) if version != 'unknown' else 'unknown'

candidate_paths = [
    '.claude/commands/protocol.md', '.claude/commands/continue.md',
    '.claude/commands/pause.md', '.claude/commands/map.md',
    '.claude/commands/memory.md', '.claude/commands/extensions.md',
    '.claude/commands/orchestrate.md',
    '.claude/fitness-check.sh', '.claude/hooks/copilot-hook.sh',
] + [f'.claude/agents/{agent}.md' for agent in roster]

root = Path('.').resolve()
entry = generate_component_lock_entry(
    root, 'claude',
    version=version, release_tag=release_tag, ownership_mode='full',
    candidate_paths=candidate_paths,
)

lock_path = root / PROJECT_LOCK_FILENAME
manifest = read_project_lock(lock_path)
if not isinstance(manifest, dict):
    manifest = {}
manifest.setdefault('schema_version', '1.0')
existing = manifest.get('components')
components = (
    [c for c in existing if isinstance(c, dict) and c.get('component') != 'claude']
    if isinstance(existing, list) else []
)
components.append(entry)
components.sort(key=lambda c: str(c.get('component', '')))
manifest['components'] = components
write_project_lock(lock_path, manifest)
print(f'copilot.lock.json: claude component regenerated ({len(entry[\"files\"])} files, version {version})')
" 2>&1 || echo "WARN: could not regenerate copilot.lock.json's claude component (is the cc package importable from python3?). The project is still updated; re-run /update-project later to retry."
```

**Verify:**
```bash
python3 -c "
import json
d = json.load(open('copilot.lock.json'))
c = [x for x in d.get('components', []) if x.get('component') == 'claude']
print('claude component present:', bool(c))
print('files recorded:', len(c[0]['files']) if c else 0)
" 2>/dev/null || echo "copilot.lock.json missing or unreadable"
```

---

## Step 8: Remove Retired Orchestrator Files (if present)

The Python orchestration layer (`orchestrate.py`, `task_copilot_client.py`,
`monitor-workers.py`, etc.) is **retired**. `/orchestrate` now uses native `Task`
agents + `tc` + `git worktree` directly — no project-level scripts. If a project
still carries the old `.claude/orchestrator/` directory, remove it:

```bash
if [ -d ".claude/orchestrator" ]; then
  echo "=== Removing retired orchestrator scripts ==="
  rm -rf .claude/orchestrator
  echo "Removed .claude/orchestrator (Python orchestrator retired; see /orchestrate)"
  ORCHESTRATOR_REMOVED=true
else
  echo "No orchestrator directory found (nothing to remove)"
  ORCHESTRATOR_REMOVED=false
fi
```

---

## Step 9: Update cc CLI and Project Config

### 9A: Check cc Is Installed

```bash
which cc >/dev/null 2>&1 && echo "CC_OK" || echo "CC_MISSING"
```

**If CC_MISSING:**

Tell user: "Installing cc CLI..."

```bash
bash ~/.claude/copilot/tools/cc/install.sh
```

After install, verify:

```bash
which cc >/dev/null 2>&1 && echo "CC_INSTALLED" || echo "CC_INSTALL_FAILED"
```

If CC_INSTALL_FAILED, tell user:

---

**cc install failed.**

Try installing manually:
```bash
bash ~/.claude/copilot/tools/cc/install.sh
```

---

Then continue (do not stop — remaining steps may still work).

### 9B: Check cc Project Config

```bash
ls .claude/cc/config.json 2>/dev/null && echo "CC_CONFIG_OK" || echo "CC_CONFIG_MISSING"
```

**If CC_CONFIG_MISSING:**

Tell user: "Initializing cc project config..."

```bash
cc config init --project
```

### 9C: Ensure Memory Directory and .gitignore

```bash
# Ensure entries directory exists with a tracking file
if [ ! -d ".claude/memory/entries" ]; then
  mkdir -p .claude/memory/entries
  touch .claude/memory/entries/.gitkeep
  echo "Created .claude/memory/entries/"
fi

# Ensure .claude/memory/.gitignore exists with correct entries
if [ ! -f ".claude/memory/.gitignore" ]; then
  printf 'memory.db\nmemory.db-*\n' > .claude/memory/.gitignore
  echo "Created .claude/memory/.gitignore"
fi
```

### 9D: Run cc config doctor

```bash
cc config doctor 2>&1
```

If `cc config doctor` reports any issues (non-zero exit or lines containing "WARN" or "ERROR"), print the output and tell user:

---

**cc config doctor reported issues. Please review and resolve the items above before continuing.**

---

---

## Step 10: Verify Update

```bash
echo "=== Updated Commands ==="
ls -la .claude/commands/*.md

echo "=== Updated Agents ==="
ls .claude/agents/*.md | wc -l
echo "agent files"

echo "=== Enforcement Hook ==="
ls -la .claude/hooks/copilot-hook.sh 2>/dev/null || echo "MISSING: .claude/hooks/copilot-hook.sh"

AGENT_COUNT=$(ls .claude/agents/*.md 2>/dev/null | wc -l | tr -d ' ')
COMMAND_COUNT=$(ls .claude/commands/*.md 2>/dev/null | wc -l | tr -d ' ')
echo "AGENT_COUNT=$AGENT_COUNT"
echo "COMMAND_COUNT=$COMMAND_COUNT"

echo "=== Verification ==="
# Check commands are regular files (not symlinks)
for f in .claude/commands/*.md; do
  if [ -L "$f" ]; then
    echo "WARNING: $f is still a symlink"
  else
    echo "OK: $f"
  fi
done

echo ""
echo "=== Component Versions ==="
if [ -f ~/.claude/copilot/VERSION.json ]; then
  node -p "
    const v = require('$HOME/.claude/copilot/VERSION.json');
    console.log('Framework: v' + v.framework);
    console.log('Agents: v' + v.components.agents.version);
    console.log('Commands: v' + v.components.commands.version);
    console.log('Skills: v' + v.components.skills.version);
    console.log('cc: v' + v.components.cc.version);
    console.log('tc: v' + v.components.tc.version);
  "
fi
```

---

## Step 10B: Run Fitness Check

After updating agents, run the fitness check to verify the roster is healthy:

```bash
if [ -f .claude/fitness-check.sh ]; then
  bash .claude/fitness-check.sh \
    --agents-dir .claude/agents \
    --commands-dir .claude/commands \
    --copilot-path ~/.claude/copilot
  FITNESS_RESULT=$?
else
  # fitness-check.sh not yet copied — copy it first
  cp ~/.claude/copilot/.claude/fitness-check.sh .claude/fitness-check.sh
  chmod +x .claude/fitness-check.sh
  bash .claude/fitness-check.sh \
    --agents-dir .claude/agents \
    --commands-dir .claude/commands \
    --copilot-path ~/.claude/copilot
  FITNESS_RESULT=$?
fi
```

If `FITNESS_RESULT` is non-zero (check failed), print the failures and tell the user:

---

**Fitness check reported issues.** Review the failures above. Common fixes:
- Missing agent: `cp ~/.claude/copilot/.claude/agents/<name>.md .claude/agents/`
- Orphan route: Edit the agent file's Route To table to point to a valid agent
- Retired agent still present: `rm .claude/agents/design.md` (or other retired agent)

The project is updated but the fitness check should be resolved before using protocol chains.

---

Store `FITNESS_RESULT`, `AGENT_COUNT`, and `COMMAND_COUNT` (from Step 10) to include in Step 11 report.

---

## Step 11: Report Success

```bash
# Get Claude Copilot version
if [ -f ~/.claude/copilot/package.json ]; then
  COPILOT_VERSION=$(node -p "require('$HOME/.claude/copilot/package.json').version" 2>/dev/null || echo "unknown")
else
  COPILOT_VERSION="unknown"
fi

# Read version summary if available
if [ -f ~/.claude/copilot/CHANGELOG-SUMMARY.json ] && [ "$COPILOT_VERSION" != "unknown" ]; then
  # Extract summary for the version using node
  SUMMARY=$(node -p "
    try {
      const data = require('$HOME/.claude/copilot/CHANGELOG-SUMMARY.json');
      const version = data.versions['$COPILOT_VERSION'];
      if (version) {
        version.summary || 'See CHANGELOG.md for details';
      } else {
        'Version details not found in summary';
      }
    } catch (e) {
      'See CHANGELOG.md for details';
    }
  " 2>/dev/null || echo "See CHANGELOG.md for details")
else
  # Fallback to git log
  SUMMARY=$(cd ~/.claude/copilot && git log --oneline -1 2>/dev/null || echo "Latest version")
fi
```

Tell user:

---

**Project Updated!**

**Refreshed:**
- `.claude/commands/` ({{COMMAND_COUNT}} project commands: protocol, continue, pause, map, memory, extensions, orchestrate)
- `.claude/agents/` ({{AGENT_COUNT}} agent files: framework agents + kc setup-only, roster-aware sync)
- `.claude/hooks/copilot-hook.sh` (enforcement hook shim, re-vendored and re-registered)
- `copilot.lock.json` (`claude` component regenerated from what's actually installed; other components and any mutation ledger preserved)
{{IF_ORCHESTRATOR_REMOVED}}
- `.claude/orchestrator/` (retired Python orchestrator removed)
{{END_IF}}

**cc CLI:**
- cc installed and project config verified
- Memory directory and `.gitignore` ensured
- `cc config doctor` passed (or issues printed above)

**Unchanged:**
- `CLAUDE.md`
- `.claude/skills/`
- `.mcp.json` (any third-party MCP servers you added manually are left untouched)
{{IF_NO_ORCHESTRATOR}}
- `.claude/orchestrator/` not present (no action needed — `/orchestrate` requires no project-level scripts)
{{END_IF}}

**Claude Copilot Version:** $COPILOT_VERSION

**What's New:**
$SUMMARY

**Full details:** `~/.claude/copilot/CHANGELOG.md`

Your project now has the latest Claude Copilot commands and agents.

**Next step:** Run `cc memory index --rebuild` to refresh your local search index with any new memory entries.

---

## Troubleshooting

### Permissions Error

```bash
chmod -R 755 .claude
```

### Commands Still Not Working

Restart Claude Code to reload the files.

### Want to Reset Everything

If you need a complete reset (including .mcp.json and CLAUDE.md):
1. Remove the existing setup: `rm -rf .claude .mcp.json CLAUDE.md`
2. Run `/setup-project` for fresh initialization
