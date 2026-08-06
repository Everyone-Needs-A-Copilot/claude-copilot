# Knowledge Sync Scripts

Automated knowledge updates when products evolve via git release tags.

## Overview

The Knowledge Sync Protocol automatically maintains product documentation in your knowledge repository by extracting changes from git commit history when release tags are created.

## Architecture

```
Release Tag Created
       ↓
  post-tag hook
       ↓
  sync-knowledge.sh ──→ extract-release-changes.sh ──→ Git commits
       ↓                         ↓
       └──→ update-product-knowledge.sh
                    ↓
         ~/.claude/knowledge/03-products/
                    ↓
              Auto-commit
```

## Components

### 1. extract-release-changes.sh

Extracts and categorizes commits between git tags.

**Features:**
- Auto-detects previous and current tags
- Categorizes commits by type (feat, fix, chore, etc.)
- Identifies breaking changes
- Outputs markdown or JSON format

**Usage:**
```bash
# Extract latest release
./extract-release-changes.sh --to-tag v2.4.0

# Extract between specific tags
./extract-release-changes.sh --from-tag v2.3.0 --to-tag v2.4.0

# Output to file
./extract-release-changes.sh --to-tag v2.4.0 --output /tmp/changes.md

# JSON format
./extract-release-changes.sh --to-tag v2.4.0 --format json
```

**Commit Categorization:**

Uses conventional commit format:

| Pattern | Category |
|---------|----------|
| `feat!:` or `BREAKING CHANGE:` in body | Breaking Changes |
| `feat:` | Features |
| `fix:` | Fixes |
| `chore:` | Chores |
| `docs:` | Documentation |
| Other | Other Changes |

### 2. update-product-knowledge.sh

Updates product knowledge file with release information.

**Features:**
- Creates product file if it doesn't exist
- Preserves manual edits to overview/architecture sections
- Maintains release history (up to last 10 releases)
- Auto-commits to knowledge repository (optional)
- Dry-run mode for preview

**Usage:**
```bash
# Update with changes from file
./update-product-knowledge.sh --version v2.4.0 --changes-file /tmp/changes.md

# Update with piped input
./extract-release-changes.sh --to-tag v2.4.0 | \
  ./update-product-knowledge.sh --version v2.4.0

# Dry run (preview only)
./update-product-knowledge.sh --version v2.4.0 \
  --changes-file /tmp/changes.md --dry-run

# Auto-commit to knowledge repo
./update-product-knowledge.sh --version v2.4.0 \
  --changes-file /tmp/changes.md --auto-commit
```

**Product File Structure:**

```markdown
# Product: my-product

## Overview
Manual content preserved during updates.

## Current Capabilities
Manual content preserved during updates.

## Architecture
Manual content preserved during updates.

## Integration Points
Manual content preserved during updates.

## Recent Changes
### v2.4.0
**Product:** my-product
**Release Date:** 2026-01-14
**Commits:** 15

#### Features
- feat: Add dark mode support
- feat: Implement user preferences

#### Fixes
- fix: Resolve authentication bug

### v2.3.0
...
```

### 3. sync-knowledge.sh

Main orchestrator that combines extraction and update.

**Features:**
- Auto-detects latest tag
- Auto-detects product name from repo
- One-command sync
- Dry-run support

**Usage:**
```bash
# Sync latest tag
./sync-knowledge.sh

# Sync specific tag
./sync-knowledge.sh --tag v2.4.0

# Dry run
./sync-knowledge.sh --tag v2.4.0 --dry-run

# Sync without auto-commit
./sync-knowledge.sh --tag v2.4.0 --no-commit

# Custom knowledge repo
./sync-knowledge.sh --knowledge-repo ~/my-company-knowledge
```

### 4. post-tag (Git Hook)

Git hook that triggers sync when release tags are created.

**Features:**
- Only processes release tags (v*.*.*)
- Fails gracefully if sync unavailable
- Non-blocking (won't prevent tag creation)

**Installation:**

Installed automatically via `/setup-knowledge-sync` command in Claude Code.

Manual installation:
```bash
cp templates/hooks/post-tag .git/hooks/
chmod +x .git/hooks/post-tag
```

## Installation

### Automatic (Recommended)

In Claude Code:
```
/setup-knowledge-sync
```

This command:
1. Verifies knowledge repository exists
2. Copies scripts to `.git/hooks/`
3. Installs post-tag hook
4. Makes everything executable
5. Offers to test with current tag

### Manual

```bash
# From your project root
cd .git/hooks

# Copy scripts
cp ~/.claude/copilot/scripts/knowledge-sync/*.sh ./
cp ~/.claude/copilot/templates/hooks/post-tag ./

# Make executable
chmod +x post-tag sync-knowledge.sh extract-release-changes.sh update-product-knowledge.sh
```

## Workflow

### Automatic (via Hook)

```bash
# Make changes, commit normally
git add .
git commit -m "feat: Add new feature"

# Create release tag
git tag v1.0.0
# → Hook automatically runs, knowledge synced

# Push tag
git push --tags
```

### Manual

```bash
# After creating tag
git tag v1.0.0

# Run sync manually
.git/hooks/sync-knowledge.sh --tag v1.0.0

# Or dry run first
.git/hooks/sync-knowledge.sh --tag v1.0.0 --dry-run
```

## Knowledge Repository Structure

Knowledge is stored in:
```
~/.claude/knowledge/
├── knowledge-manifest.json
└── 03-products/
    ├── product-a.md
    ├── product-b.md
    └── my-product.md
```

## Version Tracking

**Design Decision:** Use git history for version tracking, not separate version files.

**Why:**
- Git already tracks all changes with timestamps
- No duplication of version information
- Standard git commands work: `git log`, `git blame`, etc.
- Knowledge repo itself is versioned

**View version history:**
```bash
cd ~/.claude/knowledge
git log -- 03-products/my-product.md
git show HEAD:03-products/my-product.md
```

## Conventional Commits

For best results, follow conventional commit format:

| Type | Description | Example |
|------|-------------|---------|
| `feat:` | New feature | `feat: Add user authentication` |
| `fix:` | Bug fix | `fix: Resolve login timeout` |
| `docs:` | Documentation | `docs: Update API reference` |
| `chore:` | Maintenance | `chore: Update dependencies` |
| `test:` | Tests | `test: Add integration tests` |
| `refactor:` | Refactoring | `refactor: Simplify auth flow` |

**Breaking changes:**
```bash
# Method 1: Exclamation mark
git commit -m "feat!: Change API response format"

# Method 2: Footer
git commit -m "feat: Change API response

BREAKING CHANGE: Response format changed from XML to JSON"
```

## Integration with Task Copilot

### Current Implementation

Knowledge sync extracts information from git commits only.

### Future Enhancement

Could integrate with Task Copilot's work products:

```bash
# In update-product-knowledge.sh, add:

# Query Task Copilot for work products created during release
work_products=$(task_copilot_query \
  --from-date "$(git log -1 --format=%ai $FROM_TAG)" \
  --to-date "$(git log -1 --format=%ai $TO_TAG)" \
  --types "architecture,technical_design")

# Extract architecture decisions, technical designs
# Include in knowledge update
```

This would capture:
- Architecture decisions from PRDs
- Technical designs from @agent-ta
- Test strategies from @agent-qa
- Security reviews from @agent-sec

**Not implemented yet** - requires Task Copilot CLI or API.

## Troubleshooting

### Hook not running

```bash
# Verify hook is executable
ls -la .git/hooks/post-tag

# Make executable if needed
chmod +x .git/hooks/post-tag

# Test manually
.git/hooks/sync-knowledge.sh --dry-run
```

### Knowledge repo not found

```bash
# Check if knowledge repo exists
ls ~/.claude/knowledge/knowledge-manifest.json

# Create if missing
# Run in Claude Code:
/knowledge-copilot
```

### Changes not categorized correctly

Ensure commits follow conventional format:
```bash
# Bad
git commit -m "Added feature"

# Good
git commit -m "feat: Add user profile page"
```

### Product file not created

```bash
# Verify knowledge repo structure
ls ~/.claude/knowledge/03-products/

# Create products directory if missing
mkdir -p ~/.claude/knowledge/03-products
```

### Git conflicts in knowledge repo

```bash
cd ~/.claude/knowledge

# Pull latest changes first
git pull

# Then re-run sync
cd /path/to/project
.git/hooks/sync-knowledge.sh --tag v2.4.0
```

## Testing

### Dry Run

Preview what would be updated without making changes:

```bash
# Test sync
./sync-knowledge.sh --tag v2.4.0 --dry-run

# Test extraction only
./extract-release-changes.sh --to-tag v2.4.0

# Test update only (with existing changes file)
./update-product-knowledge.sh --version v2.4.0 \
  --changes-file /tmp/changes.md --dry-run
```

### Manual Verification

```bash
# After sync, check the product file
cat ~/.claude/knowledge/03-products/my-product.md

# View git log in knowledge repo
cd ~/.claude/knowledge
git log -1

# Test knowledge search
# In Claude Code:
knowledge_search("my-product v2.4.0")
```

## Uninstallation

```bash
# Remove hook and scripts
rm .git/hooks/post-tag
rm .git/hooks/sync-knowledge.sh
rm .git/hooks/extract-release-changes.sh
rm .git/hooks/update-product-knowledge.sh
```

Knowledge files remain in `~/.claude/knowledge` - remove manually if desired.

## Configuration

All scripts support environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `KNOWLEDGE_REPO` | `~/.claude/knowledge` | Knowledge repository path |

Override in hook:
```bash
# Edit .git/hooks/post-tag
export KNOWLEDGE_REPO="$HOME/my-company-knowledge"
```

## Best Practices

1. **Tag naming:** Use semantic versioning (`v1.0.0`, `v2.4.0`)
2. **Commit messages:** Follow conventional commits
3. **Breaking changes:** Mark clearly with `!` or `BREAKING CHANGE:`
4. **Manual edits:** Update Overview/Architecture sections manually
5. **Regular releases:** Knowledge stays current with frequent tags
6. **Review changes:** Check knowledge file after auto-commits
7. **Push knowledge:** Share updates with team via git push

## Examples

### Example 1: First Release

```bash
# Create first tag
git tag v1.0.0

# Hook runs, creates:
# ~/.claude/knowledge/03-products/my-product.md

# Commit is auto-created:
cd ~/.claude/knowledge
git log -1
# docs(products): Update my-product to v1.0.0
```

### Example 2: Subsequent Release

```bash
# Development work with conventional commits
git commit -m "feat: Add export functionality"
git commit -m "fix: Resolve import bug"
git commit -m "docs: Update README"

# Create release tag
git tag v1.1.0

# Hook extracts changes between v1.0.0 and v1.1.0
# Updates knowledge file with new section
# Auto-commits to knowledge repo
```

### Example 3: Breaking Change

```bash
# Breaking change
git commit -m "feat!: Change API authentication to OAuth2

BREAKING CHANGE: API now requires OAuth2 tokens instead of API keys"

# Create tag
git tag v2.0.0

# Knowledge file shows:
# ## ⚠️ Breaking Changes
# - feat!: Change API authentication to OAuth2
```

### Example 4: Manual Sync

```bash
# Tag was created earlier without hook
git tag v1.2.0

# Sync manually now
.git/hooks/sync-knowledge.sh --tag v1.2.0

# Verify
cat ~/.claude/knowledge/03-products/my-product.md
```

## Future Enhancements

Potential improvements:

1. **Task Copilot Integration**
   - Extract work products created during release cycle
   - Include architecture decisions, technical designs
   - Link to original PRDs and tasks

2. **Lifecycle Hook Integration**
   - Use PostWorkProduct hook for real-time capture
   - Update knowledge as work completes, not just at release

3. **Enhanced Categorization**
   - Parse work product types (architecture, technical_design, etc.)
   - Group by agent (ta, qa, sec, doc)
   - Include completion metrics

4. **Multi-Product Support**
   - Monorepo detection
   - Per-package versioning
   - Selective syncing

5. **Knowledge Templates**
   - Product-type-specific templates
   - Customizable sections
   - Industry standards integration

## Related Documentation

- [Extension Spec](../../docs/40-extensions/00-extension-spec.md) - Knowledge repository structure
- [Knowledge Structure Guide](../../templates/KNOWLEDGE-STRUCTURE-GUIDE.md) - Directory layout
- [/knowledge-copilot command](../../.claude/commands/knowledge-copilot.md) - Setup knowledge repo
- [/setup-knowledge-sync command](../../.claude/commands/setup-knowledge-sync.md) - Install sync system

---

Built for [Claude Copilot](https://github.com/Everyone-Needs-A-Copilot/claude-copilot)
