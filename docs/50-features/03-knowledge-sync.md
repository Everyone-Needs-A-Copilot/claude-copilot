# Knowledge Sync Protocol

Automated knowledge updates when products evolve via git release tags.

## Problem

As products evolve through releases, knowledge repositories become stale:
- Features are added but documentation lags
- Architectural changes aren't captured
- New capabilities aren't discoverable
- Manual updates are error-prone and forgotten

## Solution

**Knowledge Sync Protocol** automatically updates product knowledge in `~/.claude/knowledge/03-products/` when release tags are created.

## Architecture

### Trigger: Git Release Tags

**Why tags?**
- Clean version boundaries
- Standard git workflow
- Already part of release process
- Non-invasive (no new tools required)

**Tag format:** `v*.*.*` (semantic versioning)

Examples: `v1.0.0`, `v2.4.0`, `v1.0.0-beta.1`

### Data Flow

```
Developer creates release tag (v2.4.0)
           ↓
    Git post-tag hook triggers
           ↓
    extract-release-changes.sh
           ↓
    Analyzes commits between v2.3.0 and v2.4.0
           ↓
    Categorizes: features, fixes, breaking changes
           ↓
    update-product-knowledge.sh
           ↓
    Updates ~/.claude/knowledge/03-products/product-name.md
           ↓
    Auto-commits to knowledge repository
           ↓
    Knowledge available across all projects
```

### Components

| Component | Purpose | Location |
|-----------|---------|----------|
| `extract-release-changes.sh` | Parse commits between tags | `scripts/knowledge-sync/` |
| `update-product-knowledge.sh` | Update knowledge file | `scripts/knowledge-sync/` |
| `sync-knowledge.sh` | Orchestrate sync process | `scripts/knowledge-sync/` |
| `post-tag` | Git hook to trigger sync | `templates/hooks/` |
| `/setup-knowledge-sync` | Installation command | `.claude/commands/` |

## Installation

### Prerequisites

1. Knowledge repository exists:
   ```bash
   ls ~/.claude/knowledge/knowledge-manifest.json
   ```
   If missing: `/knowledge-copilot`

2. Project is a git repository

### Setup

In Claude Code, from project root:
```
/setup-knowledge-sync
```

This command:
- Copies scripts to `.git/hooks/`
- Installs post-tag hook
- Makes everything executable
- Offers to test with current tag

### Manual Installation

```bash
cd .git/hooks

# Copy scripts
cp ~/.claude/copilot/scripts/knowledge-sync/*.sh ./
cp ~/.claude/copilot/templates/hooks/post-tag ./

# Make executable
chmod +x post-tag sync-knowledge.sh \
  extract-release-changes.sh update-product-knowledge.sh
```

## Usage

### Automatic (Recommended)

Create release tag as normal:

```bash
# Development work
git add .
git commit -m "feat: Add user authentication"
git commit -m "fix: Resolve login timeout"

# Create release tag
git tag v1.0.0

# Hook automatically:
# - Extracts changes
# - Updates knowledge
# - Commits to knowledge repo

# Push tag
git push --tags
```

### Manual Sync

```bash
# Sync latest tag
.git/hooks/sync-knowledge.sh

# Sync specific tag
.git/hooks/sync-knowledge.sh --tag v2.4.0

# Dry run (preview only)
.git/hooks/sync-knowledge.sh --tag v2.4.0 --dry-run

# Sync without auto-commit
.git/hooks/sync-knowledge.sh --tag v2.4.0 --no-commit
```

### Individual Scripts

```bash
# Extract changes only
.git/hooks/extract-release-changes.sh --to-tag v2.4.0

# Extract to file
.git/hooks/extract-release-changes.sh \
  --to-tag v2.4.0 --output /tmp/changes.md

# Update knowledge from file
.git/hooks/update-product-knowledge.sh \
  --version v2.4.0 --changes-file /tmp/changes.md

# Pipe together
.git/hooks/extract-release-changes.sh --to-tag v2.4.0 | \
  .git/hooks/update-product-knowledge.sh --version v2.4.0
```

## Commit Categorization

Uses **conventional commit format** for intelligent categorization:

| Pattern | Category | Example |
|---------|----------|---------|
| `feat!:` or `BREAKING CHANGE:` in body | ⚠️ Breaking Changes | `feat!: Change API format` |
| `feat:` or `feat(scope):` | ✨ Features | `feat: Add dark mode` |
| `fix:` or `fix(scope):` | 🐛 Fixes | `fix: Resolve timeout` |
| `chore:` | 🔧 Chores | `chore: Update deps` |
| `docs:` | 📚 Documentation | `docs: Update README` |
| Other | Other Changes | Any other format |

**Breaking change examples:**

```bash
# Method 1: Exclamation mark
git commit -m "feat!: Change API authentication to OAuth2"

# Method 2: Footer
git commit -m "feat: Change API authentication

BREAKING CHANGE: API now requires OAuth2 tokens instead of API keys"
```

## Product Knowledge File

### Structure

```markdown
# Product: my-product

## Overview
Manual content - preserved during updates.
Update this section to describe what the product does.

## Current Capabilities
Manual content - preserved during updates.
Update this section with major features and capabilities.

## Architecture
Manual content - preserved during updates.
Update this section with how the product works.

## Integration Points
Manual content - preserved during updates.
Update this section with how it integrates with other systems.

## Recent Changes
Auto-generated content below - DO NOT edit manually.

### v2.4.0
**Product:** my-product
**Release Date:** 2026-01-14
**Commits:** 15

#### ✨ Features
- feat: Add user authentication system
- feat: Implement role-based permissions

#### 🐛 Fixes
- fix: Resolve login timeout issue
- fix: Fix password reset flow

#### 🔧 Chores
- chore: Update dependencies
- chore: Improve test coverage

### v2.3.0
...older releases...
```

### Manual Sections (Preserved)

These sections are **preserved during updates**:
- Overview
- Current Capabilities
- Architecture
- Integration Points

**You should manually edit these** to provide context and high-level information.

### Auto-Generated Section

The **Recent Changes** section is **auto-generated** from git commits.

Do not manually edit this section - it will be overwritten on next sync.

## Version Tracking

**Design Decision:** Use git history for version tracking, not separate files.

### Why Git History?

- Git already tracks all changes with timestamps
- No duplication of version information
- Standard git commands work (`git log`, `git blame`)
- Knowledge repository itself is versioned
- Team members can see full history

### View Version History

```bash
cd ~/.claude/knowledge

# View all updates to product file
git log -- 03-products/my-product.md

# View specific version
git show HEAD:03-products/my-product.md
git show HEAD~1:03-products/my-product.md

# View blame
git blame 03-products/my-product.md

# Find when feature was added
git log --grep="dark mode" -- 03-products/my-product.md
```

## Knowledge Access

Once synced, knowledge is available across all Claude Copilot projects:

### Search Knowledge

```
knowledge_search("my-product authentication")
knowledge_search("my-product v2.4.0")
knowledge_search("my-product breaking changes")
```

### Get Product File

```
knowledge_get("03-products/my-product.md")
```

### Agent Access

Agents automatically access knowledge via Skills Copilot's `knowledge_search` tool when needed.

## Integration with Task Copilot

### Current: Git-Only

Currently, knowledge sync extracts from git commits only.

### Future: Work Product Integration

Could integrate with Task Copilot to capture:

```typescript
// Extract work products created during release cycle
const workProducts = await task_copilot.query({
  fromDate: git.getCommitDate(fromTag),
  toDate: git.getCommitDate(toTag),
  types: ['architecture', 'technical_design', 'security_review']
});

// Include in knowledge:
// - Architecture decisions from PRDs
// - Technical designs from @agent-ta
// - Security reviews from @agent-sec
// - Test strategies from @agent-qa
```

**Benefits:**
- Richer context beyond commit messages
- Capture decision rationale
- Link to original PRDs and tasks
- Include acceptance criteria and verification

**Not implemented yet** - requires Task Copilot CLI or API.

### Integration with Lifecycle Hooks

Could use **PostWorkProduct** hook for real-time capture:

```typescript
// Hook fires when work product is stored
hooks.on('PostWorkProduct', async (context) => {
  if (context.workProductType === 'architecture') {
    // Update knowledge immediately
    await updateProductKnowledge({
      product: context.projectName,
      section: 'Architecture',
      content: context.workProduct
    });
  }
});
```

**Benefits:**
- Knowledge updated as work completes
- No waiting for release tags
- Captures decisions in real-time
- Team has latest information immediately

**Not implemented yet** - design decision to keep sync simple and tag-based for v1.

## Workflow Examples

### Example 1: First Release

```bash
# Initial development
git commit -m "feat: Initialize project"
git commit -m "feat: Add core functionality"
git commit -m "docs: Add README"

# Create first release
git tag v1.0.0

# Hook runs automatically:
# ✓ Creates ~/.claude/knowledge/03-products/my-product.md
# ✓ Populates with features from commits
# ✓ Commits to knowledge repo

# Verify
cat ~/.claude/knowledge/03-products/my-product.md

# Push tag
git push --tags

# Push knowledge updates
cd ~/.claude/knowledge
git push
```

### Example 2: Incremental Release

```bash
# Development between v1.0.0 and v1.1.0
git commit -m "feat: Add export functionality"
git commit -m "feat: Implement batch processing"
git commit -m "fix: Resolve import bug"
git commit -m "chore: Update dependencies"

# Create release
git tag v1.1.0

# Hook extracts changes between v1.0.0 and v1.1.0
# Updates knowledge file with new section
# Auto-commits to knowledge repo

# Verify
cat ~/.claude/knowledge/03-products/my-product.md
# Should show:
# ### v1.1.0
# - feat: Add export functionality
# - feat: Implement batch processing
# - fix: Resolve import bug
# ...
# ### v1.0.0
# ...older changes...
```

### Example 3: Breaking Change Release

```bash
# Major version with breaking change
git commit -m "feat!: Change API authentication to OAuth2

BREAKING CHANGE: API now requires OAuth2 tokens instead of API keys.
Migration guide: https://docs.example.com/migration"

git commit -m "feat: Add OAuth2 scopes support"
git commit -m "docs: Update authentication guide"

# Create major release
git tag v2.0.0

# Knowledge file shows:
# ### v2.0.0
# #### ⚠️ Breaking Changes
# - feat!: Change API authentication to OAuth2
# #### ✨ Features
# - feat: Add OAuth2 scopes support
# #### 📚 Documentation
# - docs: Update authentication guide
```

### Example 4: Manual Sync (Retroactive)

```bash
# Tags were created in the past without hook
git tag  # Shows: v1.0.0, v1.1.0, v1.2.0

# Sync them retroactively
.git/hooks/sync-knowledge.sh --tag v1.0.0
.git/hooks/sync-knowledge.sh --tag v1.1.0
.git/hooks/sync-knowledge.sh --tag v1.2.0

# Knowledge file now has all releases
```

## Configuration

### Environment Variables

All scripts support:

| Variable | Default | Description |
|----------|---------|-------------|
| `KNOWLEDGE_REPO` | `~/.claude/knowledge` | Knowledge repository path |

### Override in Hook

Edit `.git/hooks/post-tag`:

```bash
#!/bin/bash
# Custom knowledge repository location
export KNOWLEDGE_REPO="$HOME/my-company-knowledge"

# Rest of hook...
```

### Per-Project Settings

Create `.git/hooks/knowledge-sync.conf`:

```bash
# Knowledge Sync Configuration
KNOWLEDGE_REPO="$HOME/my-company-knowledge"
PRODUCT_NAME="custom-product-name"
```

Source in hook:

```bash
# In .git/hooks/post-tag
if [ -f "$(git rev-parse --show-toplevel)/.git/hooks/knowledge-sync.conf" ]; then
    source "$(git rev-parse --show-toplevel)/.git/hooks/knowledge-sync.conf"
fi
```

## Testing

### Dry Run

Preview what would be updated:

```bash
# Test full sync
.git/hooks/sync-knowledge.sh --tag v2.4.0 --dry-run

# Test extraction only
.git/hooks/extract-release-changes.sh --to-tag v2.4.0

# Test update only
.git/hooks/extract-release-changes.sh --to-tag v2.4.0 | \
  .git/hooks/update-product-knowledge.sh --version v2.4.0 --dry-run
```

### Test Suite

Run automated tests:

```bash
cd ~/.claude/copilot/scripts/knowledge-sync
./test-knowledge-sync.sh
```

Tests verify:
- Scripts exist and are executable
- Syntax is valid
- Help messages work
- Extraction works (if tags exist)

## Troubleshooting

### Hook Not Running

**Symptom:** Tag created but knowledge not updated

**Diagnosis:**
```bash
# Check hook exists and is executable
ls -la .git/hooks/post-tag

# Test manually
.git/hooks/sync-knowledge.sh --dry-run
```

**Fix:**
```bash
# Make executable
chmod +x .git/hooks/post-tag

# Or reinstall
# In Claude Code: /setup-knowledge-sync
```

### Knowledge Repo Not Found

**Symptom:** Error: "Knowledge repository not found"

**Diagnosis:**
```bash
ls ~/.claude/knowledge/knowledge-manifest.json
```

**Fix:**
```bash
# Create knowledge repository
# In Claude Code: /knowledge-copilot
```

### Changes Not Categorized

**Symptom:** All commits show as "Other Changes"

**Diagnosis:** Not using conventional commit format

**Fix:** Use conventional commits:
```bash
# Before (bad)
git commit -m "Added feature"

# After (good)
git commit -m "feat: Add user profile page"
```

### Product File Not Updated

**Symptom:** Knowledge file exists but not updated

**Diagnosis:**
```bash
# Check if file is tracked in git
cd ~/.claude/knowledge
git status 03-products/my-product.md

# Check for uncommitted changes
git diff 03-products/my-product.md
```

**Fix:**
```bash
# Commit any pending changes
cd ~/.claude/knowledge
git add 03-products/my-product.md
git commit -m "Manual updates"

# Re-run sync
cd /path/to/project
.git/hooks/sync-knowledge.sh --tag v2.4.0
```

### Git Conflicts

**Symptom:** Sync fails with merge conflict

**Diagnosis:**
```bash
cd ~/.claude/knowledge
git status
```

**Fix:**
```bash
# Pull latest first
cd ~/.claude/knowledge
git pull

# Then re-run sync
cd /path/to/project
.git/hooks/sync-knowledge.sh --tag v2.4.0
```

## Best Practices

### 1. Use Conventional Commits

✅ **Good:**
```bash
git commit -m "feat(auth): Add OAuth2 support"
git commit -m "fix(api): Resolve timeout in batch endpoint"
git commit -m "docs: Update installation guide"
```

❌ **Bad:**
```bash
git commit -m "Added stuff"
git commit -m "Fixed bug"
git commit -m "Updates"
```

### 2. Tag Regularly

- Tag every release (major, minor, patch)
- Use semantic versioning
- Tag before pushing to production

### 3. Manual Edits

- Update Overview section with high-level description
- Update Architecture section when structure changes
- Update Integration Points when adding integrations
- Don't edit Recent Changes section (auto-generated)

### 4. Review Changes

After auto-commit:
```bash
cd ~/.claude/knowledge
git log -1 -p
```

Verify the update looks correct before pushing.

### 5. Share with Team

```bash
cd ~/.claude/knowledge
git push
```

Team members can pull to get latest product knowledge.

### 6. Breaking Changes

Mark clearly:
```bash
git commit -m "feat!: Change response format from XML to JSON"

# Or
git commit -m "refactor(api): Simplify authentication

BREAKING CHANGE: API keys are no longer supported. Use OAuth2 tokens."
```

### 7. Release Notes

For public releases, maintain separate `CHANGELOG.md`:
```bash
# Product repo
docs/CHANGELOG.md  # Public-facing, curated

# Knowledge repo
~/.claude/knowledge/03-products/product.md  # Internal, auto-generated
```

## Uninstallation

Remove from project:

```bash
# Remove hook and scripts
rm .git/hooks/post-tag
rm .git/hooks/sync-knowledge.sh
rm .git/hooks/extract-release-changes.sh
rm .git/hooks/update-product-knowledge.sh
```

Remove product knowledge (optional):

```bash
cd ~/.claude/knowledge
git rm 03-products/my-product.md
git commit -m "Remove my-product knowledge"
```

## Related Documentation

- [Knowledge Copilot Command](../../.claude/commands/knowledge-copilot.md) - Create knowledge repository
- [Setup Knowledge Sync Command](../../.claude/commands/setup-knowledge-sync.md) - Install sync system
- [Knowledge Structure Guide](../../templates/KNOWLEDGE-STRUCTURE-GUIDE.md) - Repository layout
- [Extension Spec](../40-extensions/00-extension-spec.md) - Knowledge repository format
- [Scripts README](../../scripts/knowledge-sync/README.md) - Technical details

## Future Enhancements

### 1. Task Copilot Integration

**Goal:** Capture work products created during release cycle

**Implementation:**
```bash
# Query Task Copilot for work products
work_products=$(task_copilot_client query \
  --from-date "2026-01-01" \
  --to-date "2026-01-14" \
  --types "architecture,technical_design,security_review")

# Include in knowledge update
# - Architecture decisions
# - Technical designs
# - Security findings
# - Test strategies
```

**Requires:** Task Copilot CLI or API

### 2. Real-Time Updates via Lifecycle Hooks

**Goal:** Update knowledge as work completes, not just at releases

**Implementation:**
```typescript
// PostWorkProduct hook
hooks.on('PostWorkProduct', async (context) => {
  if (shouldUpdateKnowledge(context)) {
    await updateProductKnowledge({
      product: context.projectName,
      section: getSectionForWorkProductType(context.type),
      content: context.workProduct
    });
  }
});
```

**Benefits:**
- Knowledge updated immediately
- No waiting for releases
- Real-time team visibility

### 3. Multi-Product Support (Monorepos)

**Goal:** Handle monorepos with multiple products

**Implementation:**
```bash
# Detect monorepo structure
if [ -f "lerna.json" ] || [ -f "pnpm-workspace.yaml" ]; then
  # Extract per-package changes
  for package in packages/*; do
    sync-knowledge.sh --product "$(basename $package)" --path "$package"
  done
fi
```

### 4. Knowledge Templates

**Goal:** Product-type-specific knowledge templates

**Implementation:**
```bash
# Detect product type from package.json, Cargo.toml, etc.
PRODUCT_TYPE=$(detect_product_type)

# Use type-specific template
case $PRODUCT_TYPE in
  "api")
    template="api-product-template.md"
    ;;
  "library")
    template="library-product-template.md"
    ;;
  "application")
    template="application-product-template.md"
    ;;
esac
```

### 5. Enhanced Categorization

**Goal:** Richer categorization beyond conventional commits

**Implementation:**
- Parse PR descriptions
- Extract issue numbers
- Link to documentation
- Include metrics (test coverage, performance)

---

**Version:** 1.0.0
**Status:** Production Ready
**Last Updated:** 2026-01-14
