# Setup Knowledge Sync

Install automated knowledge updates when products evolve via git release tags.

## What This Does

Knowledge Sync automatically:
1. **Detects** when you create a release tag (e.g., `git tag v2.4.0`)
2. **Extracts** changes from commits between tags
3. **Updates** `~/.claude/knowledge/03-products/<product>.md`
4. **Commits** changes to knowledge repository

## Prerequisites

Check if knowledge repository exists:

```bash
ls ~/.claude/knowledge/knowledge-manifest.json
```

**If missing:**

Tell user:

---

**Knowledge repository not found.**

Please set up a knowledge repository first:

```
/knowledge-copilot
```

Then return here and run `/setup-knowledge-sync` again.

---

Then STOP.

---

## Step 1: Verify Git Repository

```bash
git rev-parse --is-inside-work-tree 2>/dev/null && echo "GIT_OK" || echo "NOT_GIT"
```

**If NOT_GIT:**

Tell user:

---

**This must be run in a git repository.**

Knowledge sync tracks product changes via git tags, so it requires a git repository.

Navigate to your product's repository and run this command again.

---

Then STOP.

---

## Step 2: Get Project Info

```bash
git rev-parse --show-toplevel
basename $(git rev-parse --show-toplevel)
```

Store:
- `PROJECT_ROOT` = result of show-toplevel
- `PROJECT_NAME` = result of basename

---

## Step 3: Check Existing Installation

```bash
ls "$PROJECT_ROOT/.git/hooks/post-tag" 2>/dev/null && echo "HOOK_EXISTS" || echo "HOOK_MISSING"
ls "$PROJECT_ROOT/.git/hooks/sync-knowledge.sh" 2>/dev/null && echo "SCRIPT_EXISTS" || echo "SCRIPT_MISSING"
```

If both exist:

Use AskUserQuestion:

**Question:** "Knowledge sync is already installed. What would you like to do?"
**Header:** "Action"
**Options:**
1. **"Reinstall"** - Overwrite with latest version
2. **"Test"** - Test with current tag
3. **"Cancel"** - Exit

Handle based on selection.

---

## Step 4: Ensure Hooks Directory

```bash
mkdir -p "$PROJECT_ROOT/.git/hooks"
```

---

## Step 5: Copy Scripts

```bash
# Copy main sync script to git hooks (where it will be called)
cp ~/.claude/copilot/scripts/knowledge-sync/sync-knowledge.sh "$PROJECT_ROOT/.git/hooks/"

# Copy helper scripts (they reference each other)
cp ~/.claude/copilot/scripts/knowledge-sync/extract-release-changes.sh "$PROJECT_ROOT/.git/hooks/"
cp ~/.claude/copilot/scripts/knowledge-sync/update-product-knowledge.sh "$PROJECT_ROOT/.git/hooks/"

# Copy post-tag hook
cp ~/.claude/copilot/templates/hooks/post-tag "$PROJECT_ROOT/.git/hooks/"

# Make executable
chmod +x "$PROJECT_ROOT/.git/hooks/post-tag"
chmod +x "$PROJECT_ROOT/.git/hooks/sync-knowledge.sh"
chmod +x "$PROJECT_ROOT/.git/hooks/extract-release-changes.sh"
chmod +x "$PROJECT_ROOT/.git/hooks/update-product-knowledge.sh"
```

**Verify:**

```bash
ls -la "$PROJECT_ROOT/.git/hooks/post-tag"
ls -la "$PROJECT_ROOT/.git/hooks/sync-knowledge.sh"
ls -la "$PROJECT_ROOT/.git/hooks/extract-release-changes.sh"
ls -la "$PROJECT_ROOT/.git/hooks/update-product-knowledge.sh"
```

All should be executable.

---

## Step 6: Test Installation

Check if there are any tags:

```bash
git describe --tags --abbrev=0 2>/dev/null || echo "NO_TAGS"
```

If tags exist, offer to test:

Use AskUserQuestion:

**Question:** "Would you like to test knowledge sync with the latest tag?"
**Header:** "Test"
**Options:**
1. **"Yes, test now"** - Run sync on latest tag
2. **"No, skip test"** - Installation only

If "Yes":

```bash
"$PROJECT_ROOT/.git/hooks/sync-knowledge.sh" --dry-run
```

Show the output and explain what would be updated.

---

## Step 7: Report Success

---

**Knowledge Sync Installed!**

**What was installed:**
- `.git/hooks/post-tag` - Git hook triggered on tag creation
- `.git/hooks/sync-knowledge.sh` - Main sync orchestrator
- `.git/hooks/extract-release-changes.sh` - Extract commits between tags
- `.git/hooks/update-product-knowledge.sh` - Update knowledge file

**How it works:**

1. **Create a release tag:**
   ```bash
   git tag v1.0.0
   git push --tags
   ```

2. **Hook automatically:**
   - Extracts changes between previous tag and new tag
   - Updates `~/.claude/knowledge/03-products/{{PROJECT_NAME}}.md`
   - Commits to knowledge repository

3. **Knowledge becomes available:**
   - In all Claude Copilot projects
   - Via `knowledge_search("{{PROJECT_NAME}}")`
   - Via `knowledge_get("03-products/{{PROJECT_NAME}}.md")`

**Manual sync:**

You can also run sync manually:

```bash
# Sync latest tag
.git/hooks/sync-knowledge.sh

# Sync specific tag
.git/hooks/sync-knowledge.sh --tag v2.4.0

# Dry run (preview changes)
.git/hooks/sync-knowledge.sh --tag v2.4.0 --dry-run
```

**Tag Format:**

The hook processes release tags matching: `v*.*.*`

Examples:
- ✅ `v1.0.0`, `v2.4.0`, `v1.0.0-beta.1`
- ❌ `draft`, `test`, `feature/xyz` (ignored)

**Next Release:**

On your next release:

```bash
git tag v{{NEXT_VERSION}}
git push --tags
```

Knowledge will be automatically updated!

---

## Optional: Uninstall

To remove knowledge sync:

```bash
rm "$PROJECT_ROOT/.git/hooks/post-tag"
rm "$PROJECT_ROOT/.git/hooks/sync-knowledge.sh"
rm "$PROJECT_ROOT/.git/hooks/extract-release-changes.sh"
rm "$PROJECT_ROOT/.git/hooks/update-product-knowledge.sh"
```

---

## Troubleshooting

**Hook not running:**
- Verify hook is executable: `ls -la .git/hooks/post-tag`
- Test manually: `.git/hooks/sync-knowledge.sh --dry-run`

**Knowledge repo not found:**
- Run `/knowledge-copilot` to create it
- Or verify symlink: `ls -la ~/.claude/knowledge`

**Changes not appearing:**
- Check commits follow conventional format: `feat:`, `fix:`, etc.
- View extracted changes: `.git/hooks/sync-knowledge.sh --dry-run`
- Check knowledge file: `cat ~/.claude/knowledge/03-products/{{PROJECT_NAME}}.md`

---

## Tips

- Use conventional commits for better categorization:
  - `feat: Add new feature`
  - `fix: Fix bug`
  - `docs: Update documentation`
  - `chore: Update dependencies`

- Breaking changes are highlighted with:
  - `feat!: Breaking change` (exclamation mark)
  - Or `BREAKING CHANGE:` in commit body

- Knowledge is versioned via git - you can see history:
  ```bash
  cd ~/.claude/knowledge
  git log -- 03-products/{{PROJECT_NAME}}.md
  ```
