# Knowledge Sync - Quick Start

Automatically update product knowledge when you create release tags.

## 1. Prerequisites

- ✅ Knowledge repository exists: `~/.claude/knowledge`
  - If missing: run `/knowledge-copilot` in Claude Code

- ✅ Your project is a git repository
  - If missing: `git init`

## 2. Install (One Time)

In Claude Code, from your project root:

```
/setup-knowledge-sync
```

This installs:
- Git hook (`.git/hooks/post-tag`)
- Sync scripts (`.git/hooks/*.sh`)

## 3. Use (Every Release)

Just create release tags as normal:

```bash
# Development work with conventional commits
git commit -m "feat: Add user authentication"
git commit -m "fix: Resolve login bug"

# Create release tag
git tag v1.0.0

# Hook automatically runs and updates knowledge
# ✓ Extracts changes
# ✓ Updates ~/.claude/knowledge/03-products/your-product.md
# ✓ Commits to knowledge repo

# Push tag
git push --tags
```

Done! Your knowledge is updated.

## 4. Verify

Check the product knowledge file:

```bash
cat ~/.claude/knowledge/03-products/your-product.md
```

Or search in Claude Code:

```
knowledge_search("your-product")
```

## 5. Share with Team

Push knowledge updates:

```bash
cd ~/.claude/knowledge
git push
```

Team members pull to get updates:

```bash
cd ~/.claude/knowledge
git pull
```

## Conventional Commits (Recommended)

For best categorization, use conventional commit format:

| Type | Example |
|------|---------|
| Feature | `git commit -m "feat: Add OAuth login"` |
| Fix | `git commit -m "fix: Resolve timeout bug"` |
| Breaking | `git commit -m "feat!: Change API format"` |
| Chore | `git commit -m "chore: Update dependencies"` |
| Docs | `git commit -m "docs: Update README"` |

## Manual Sync (If Needed)

```bash
# Sync latest tag
.git/hooks/sync-knowledge.sh

# Sync specific tag
.git/hooks/sync-knowledge.sh --tag v2.4.0

# Preview (dry run)
.git/hooks/sync-knowledge.sh --tag v2.4.0 --dry-run
```

## Product Knowledge File

```markdown
# Product: your-product

## Overview
← YOU edit this section (manual)

## Current Capabilities
← YOU edit this section (manual)

## Architecture
← YOU edit this section (manual)

## Recent Changes
← AUTO-GENERATED - Do not edit

### v1.0.0
**Release Date:** 2026-01-14
**Commits:** 10

#### ✨ Features
- feat: Add user authentication
- feat: Implement permissions

#### 🐛 Fixes
- fix: Resolve login bug
```

**Key Point:** Only "Recent Changes" is auto-generated. You should manually edit the other sections to provide context.

## Troubleshooting

### Hook not running

```bash
# Check if executable
ls -la .git/hooks/post-tag

# Make executable
chmod +x .git/hooks/post-tag
```

### Knowledge repo not found

```bash
# Check if exists
ls ~/.claude/knowledge/knowledge-manifest.json

# Create if missing (in Claude Code)
/knowledge-copilot
```

### Changes not categorized

Use conventional commit format:
```bash
# Bad
git commit -m "Added feature"

# Good
git commit -m "feat: Add user profile page"
```

## Help

**Documentation:**
- Feature Guide: `docs/50-features/03-knowledge-sync.md`
- Technical Details: `scripts/knowledge-sync/README.md`

**Test Installation:**
```bash
cd scripts/knowledge-sync
./test-knowledge-sync.sh
```

**Get Help in Claude Code:**
```
/setup-knowledge-sync
```

---

That's it! Create tags, knowledge updates automatically.
