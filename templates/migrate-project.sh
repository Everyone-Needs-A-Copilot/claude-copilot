#!/bin/bash
# migrate-project.sh
# Migrates a project from local Claude Copilot to machine-level framework
#
# Usage: ~/.claude/copilot/templates/migrate-project.sh [project-path]
#        Or run from within project directory without arguments

set -e  # Exit on error

# Determine project root
if [ -n "$1" ]; then
  PROJECT_ROOT="$1"
  cd "$PROJECT_ROOT"
else
  PROJECT_ROOT=$(pwd)
fi

FRAMEWORK_PATH="$HOME/.claude/copilot"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║          Claude Copilot Migration Script                     ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Project: $PROJECT_ROOT"
echo "Framework: $FRAMEWORK_PATH"
echo ""

# ============================================================================
# PRE-FLIGHT CHECKS
# ============================================================================

echo "▶ Running pre-flight checks..."

# Check framework exists
if [ ! -d "$FRAMEWORK_PATH" ]; then
  echo "✗ ERROR: Machine-level framework not found at $FRAMEWORK_PATH"
  echo "  Install it first: git clone <repo> ~/.claude/copilot"
  exit 1
fi

# Check templates exist
if [ ! -f "$FRAMEWORK_PATH/templates/mcp.json" ]; then
  echo "✗ ERROR: Template mcp.json not found"
  exit 1
fi

if [ ! -f "$FRAMEWORK_PATH/templates/CLAUDE.template.md" ]; then
  echo "✗ ERROR: Template CLAUDE.template.md not found"
  exit 1
fi

# Check MCP servers are built
if [ ! -f "$FRAMEWORK_PATH/mcp-servers/copilot-memory/dist/index.js" ]; then
  echo "✗ ERROR: copilot-memory MCP server not built"
  echo "  Run: cd $FRAMEWORK_PATH/mcp-servers/copilot-memory && npm install && npm run build"
  exit 1
fi

if [ ! -f "$FRAMEWORK_PATH/mcp-servers/skills-copilot/dist/index.js" ]; then
  echo "✗ ERROR: skills-copilot MCP server not built"
  echo "  Run: cd $FRAMEWORK_PATH/mcp-servers/skills-copilot && npm install && npm run build"
  exit 1
fi

# Check git status
if [ -d ".git" ]; then
  if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    echo "⚠ WARNING: Uncommitted changes detected"
    echo "  Recommend: git add -A && git commit -m 'chore: pre-migration snapshot'"
    read -p "  Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
      exit 1
    fi
  fi
  IS_GIT_REPO=true
else
  IS_GIT_REPO=false
  echo "⚠ WARNING: Not a git repository. No backup tags will be created."
fi

echo "✓ Pre-flight checks passed"
echo ""

# ============================================================================
# PHASE 0.5: PRESERVE MEMORY WORKSPACE
# ============================================================================

echo "▶ Preserving memory workspace identity..."

# Compute current project hash (same algorithm as copilot-memory)
CURRENT_HASH=$(node -e "console.log(require('crypto').createHash('md5').update('$PROJECT_ROOT').digest('hex').substring(0, 12))" 2>/dev/null || echo "")

if [ -n "$CURRENT_HASH" ]; then
  # Check if this workspace has existing data
  MEMORY_DB="$HOME/.claude/memory/$CURRENT_HASH/memory.db"
  if [ -f "$MEMORY_DB" ]; then
    echo "  Found existing memory database: $CURRENT_HASH"
    echo "  This WORKSPACE_ID will be preserved in .mcp.json"
    PRESERVE_WORKSPACE_ID="$CURRENT_HASH"
  else
    echo "  No existing memory database found"
    PRESERVE_WORKSPACE_ID=""
  fi
else
  echo "  ⚠ Could not compute workspace hash (node not available)"
  PRESERVE_WORKSPACE_ID=""
fi

echo ""

# ============================================================================
# PHASE 1: DISCOVERY
# ============================================================================

echo "▶ Phase 1: Discovering local framework files..."

HAS_LOCAL_AGENTS=false
HAS_LOCAL_COMMANDS=false
HAS_LOCAL_MCP_SERVERS=false
HAS_LOCAL_OPS_DOCS=false
HAS_CUSTOMIZATIONS=false
CUSTOMIZED_AGENTS=()

# Check for local agents
if [ -d ".claude/agents" ]; then
  HAS_LOCAL_AGENTS=true
  echo "  Found: .claude/agents/"

  # Check for customizations
  for agent in .claude/agents/*.md 2>/dev/null; do
    if [ -f "$agent" ]; then
      agent_name=$(basename "$agent")
      if [ -f "$FRAMEWORK_PATH/.claude/agents/$agent_name" ]; then
        if ! diff -q "$agent" "$FRAMEWORK_PATH/.claude/agents/$agent_name" > /dev/null 2>&1; then
          echo "    ⚠ Customized: $agent_name"
          HAS_CUSTOMIZATIONS=true
          CUSTOMIZED_AGENTS+=("$agent_name")
        fi
      else
        echo "    ⚠ Custom agent (not in base): $agent_name"
        HAS_CUSTOMIZATIONS=true
        CUSTOMIZED_AGENTS+=("$agent_name")
      fi
    fi
  done
fi

# Check for local commands
if [ -d ".claude/commands" ]; then
  HAS_LOCAL_COMMANDS=true
  echo "  Found: .claude/commands/"
fi

# Check for local MCP servers
if [ -d "mcp-servers/copilot-memory" ] || [ -d "mcp-servers/skills-copilot" ]; then
  HAS_LOCAL_MCP_SERVERS=true
  echo "  Found: mcp-servers/"
fi

# Check for local operations docs
if [ -d "docs/operations" ]; then
  HAS_LOCAL_OPS_DOCS=true
  echo "  Found: docs/operations/"
fi

# Check for old MCP config locations
if [ -f ".claude/mcp.json" ]; then
  echo "  Found: .claude/mcp.json (old config)"
fi

if [ "$HAS_LOCAL_AGENTS" = false ] && [ "$HAS_LOCAL_COMMANDS" = false ] && \
   [ "$HAS_LOCAL_MCP_SERVERS" = false ] && [ "$HAS_LOCAL_OPS_DOCS" = false ]; then
  echo "  No local framework files found. Checking if already migrated..."

  if [ -f ".mcp.json" ] && [ -f "CLAUDE.md" ]; then
    echo "✓ Project appears to already be migrated!"
    echo "  .mcp.json and CLAUDE.md exist"
    exit 0
  fi
fi

echo ""

# ============================================================================
# PHASE 2: BACKUP
# ============================================================================

echo "▶ Phase 2: Creating backup..."

if [ "$IS_GIT_REPO" = true ]; then
  BACKUP_TAG="migration-backup-$(date +%Y%m%d-%H%M%S)"
  git add -A 2>/dev/null || true
  git commit -m "chore: pre-migration snapshot" 2>/dev/null || echo "  No changes to commit"
  git tag "$BACKUP_TAG" 2>/dev/null || true
  echo "  ✓ Created backup tag: $BACKUP_TAG"
fi

# Archive local files
mkdir -p .migration-archive
[ -d ".claude" ] && cp -r .claude .migration-archive/ 2>/dev/null || true
[ -d "mcp-servers" ] && cp -r mcp-servers .migration-archive/ 2>/dev/null || true
[ -d "docs/operations" ] && mkdir -p .migration-archive/docs && cp -r docs/operations .migration-archive/docs/ 2>/dev/null || true
echo "  ✓ Archived to .migration-archive/"

echo ""

# ============================================================================
# PHASE 3: HANDLE CUSTOMIZATIONS
# ============================================================================

if [ "$HAS_CUSTOMIZATIONS" = true ]; then
  echo "▶ Phase 3: Handling customizations..."
  echo ""
  echo "  ⚠ Customized agents detected: ${CUSTOMIZED_AGENTS[*]}"
  echo ""
  echo "  Options:"
  echo "    1) Extract to extensions (recommended for modified base agents)"
  echo "    2) Discard customizations (use base agents)"
  echo "    3) Abort migration (handle manually)"
  echo ""
  read -p "  Choose option (1/2/3): " -n 1 -r
  echo ""

  case $REPLY in
    1)
      echo "  Creating extensions directory..."
      mkdir -p .claude/extensions

      for agent_name in "${CUSTOMIZED_AGENTS[@]}"; do
        agent_base="${agent_name%.md}"
        echo "  Extracting: $agent_name -> .claude/extensions/$agent_base.extension.md"

        # Copy customized agent as extension
        if [ -f ".claude/agents/$agent_name" ]; then
          # Add extension frontmatter
          {
            echo "---"
            echo "extends: $agent_base"
            echo "type: extension"
            echo "description: Project-specific customizations for $agent_base"
            echo "---"
            echo ""
            echo "# Customizations extracted from local agent"
            echo ""
            cat ".claude/agents/$agent_name"
          } > ".claude/extensions/$agent_base.extension.md"
        fi
      done

      # Create knowledge-manifest.json
      echo "  Creating knowledge-manifest.json..."
      {
        echo "{"
        echo "  \"version\": \"1.0\","
        echo "  \"name\": \"$(basename "$PROJECT_ROOT")-knowledge\","
        echo "  \"description\": \"Project-specific extensions migrated from local framework\","
        echo "  \"framework\": {"
        echo "    \"name\": \"claude-copilot\","
        echo "    \"minVersion\": \"1.0.0\""
        echo "  },"
        echo "  \"extensions\": ["

        first=true
        for agent_name in "${CUSTOMIZED_AGENTS[@]}"; do
          agent_base="${agent_name%.md}"
          if [ "$first" = true ]; then
            first=false
          else
            echo ","
          fi
          echo -n "    {"
          echo -n "\"agent\": \"$agent_base\", "
          echo -n "\"type\": \"extension\", "
          echo -n "\"file\": \".claude/extensions/$agent_base.extension.md\", "
          echo -n "\"description\": \"Project-specific $agent_base customizations\", "
          echo -n "\"fallbackBehavior\": \"use_base\""
          echo -n "}"
        done

        echo ""
        echo "  ]"
        echo "}"
      } > knowledge-manifest.json

      echo "  ✓ Extensions extracted"
      ;;
    2)
      echo "  Discarding customizations, will use base agents"
      ;;
    3)
      echo "  Aborting migration. Review customizations manually:"
      echo "    - Customized agents: ${CUSTOMIZED_AGENTS[*]}"
      echo "    - Backup available at: .migration-archive/"
      exit 0
      ;;
    *)
      echo "  Invalid option. Aborting."
      exit 1
      ;;
  esac

  echo ""
fi

# ============================================================================
# PHASE 4: REMOVE LOCAL FRAMEWORK
# ============================================================================

echo "▶ Phase 4: Removing local framework files..."

# Remove agents (keep extensions if created)
if [ -d ".claude/agents" ]; then
  rm -rf .claude/agents
  echo "  ✓ Removed .claude/agents/"
fi

# Remove commands
if [ -d ".claude/commands" ]; then
  rm -rf .claude/commands
  echo "  ✓ Removed .claude/commands/"
fi

# Remove local MCP servers
if [ -d "mcp-servers/copilot-memory" ]; then
  rm -rf mcp-servers/copilot-memory
  echo "  ✓ Removed mcp-servers/copilot-memory/"
fi

if [ -d "mcp-servers/skills-copilot" ]; then
  rm -rf mcp-servers/skills-copilot
  echo "  ✓ Removed mcp-servers/skills-copilot/"
fi

# Remove mcp-servers if empty
if [ -d "mcp-servers" ]; then
  rmdir mcp-servers 2>/dev/null && echo "  ✓ Removed empty mcp-servers/" || true
fi

# Remove operations docs
if [ -d "docs/operations" ]; then
  rm -rf docs/operations
  echo "  ✓ Removed docs/operations/"
  # Remove docs if empty
  rmdir docs 2>/dev/null || true
fi

# Remove old MCP configs
if [ -f ".claude/mcp.json" ]; then
  rm -f .claude/mcp.json
  echo "  ✓ Removed .claude/mcp.json"
fi

if [ -f ".claude/config.json" ]; then
  rm -f .claude/config.json
  echo "  ✓ Removed .claude/config.json"
fi

# Remove .claude if empty (but keep if extensions exist)
if [ -d ".claude" ]; then
  if [ ! -d ".claude/extensions" ] && [ ! -d ".claude/skills" ]; then
    rmdir .claude 2>/dev/null && echo "  ✓ Removed empty .claude/" || true
  fi
fi

echo ""

# ============================================================================
# PHASE 5: ADD MACHINE-LEVEL CONFIGURATION
# ============================================================================

echo "▶ Phase 5: Adding machine-level configuration..."

# Copy .mcp.json template
cp "$FRAMEWORK_PATH/templates/mcp.json" ./.mcp.json
echo "  ✓ Created .mcp.json"

# Preserve WORKSPACE_ID if we found an existing database
if [ -n "$PRESERVE_WORKSPACE_ID" ]; then
  # Replace placeholder value with actual workspace ID
  if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s|\"WORKSPACE_ID\": \"your-project-name\"|\"WORKSPACE_ID\": \"$PRESERVE_WORKSPACE_ID\"|g" .mcp.json
  else
    sed -i "s|\"WORKSPACE_ID\": \"your-project-name\"|\"WORKSPACE_ID\": \"$PRESERVE_WORKSPACE_ID\"|g" .mcp.json
  fi
  echo "  ✓ Preserved WORKSPACE_ID: $PRESERVE_WORKSPACE_ID"
fi

# If knowledge-manifest.json exists, add KNOWLEDGE_REPO_PATH to skills-copilot env
if [ -f "knowledge-manifest.json" ]; then
  # Add KNOWLEDGE_REPO_PATH after LOCAL_SKILLS_PATH
  if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s|\"LOCAL_SKILLS_PATH\": \"./.claude/skills\"|\"LOCAL_SKILLS_PATH\": \"./.claude/skills\",\n        \"KNOWLEDGE_REPO_PATH\": \"$PROJECT_ROOT\"|g" .mcp.json
  else
    sed -i "s|\"LOCAL_SKILLS_PATH\": \"./.claude/skills\"|\"LOCAL_SKILLS_PATH\": \"./.claude/skills\",\n        \"KNOWLEDGE_REPO_PATH\": \"$PROJECT_ROOT\"|g" .mcp.json
  fi
  echo "  ✓ Added KNOWLEDGE_REPO_PATH to .mcp.json"
fi

# Copy CLAUDE.md if it doesn't exist
if [ ! -f "CLAUDE.md" ]; then
  cp "$FRAMEWORK_PATH/templates/CLAUDE.template.md" ./CLAUDE.md
  echo "  ✓ Created CLAUDE.md (customize with project details)"
else
  echo "  ⚠ CLAUDE.md already exists, preserving existing file"
fi

echo ""

# ============================================================================
# PHASE 5.5: FIX HOOK SYMLINKS
# ============================================================================

echo "▶ Phase 5.5: Checking hook symlinks..."

if [ -d ".claude/hooks" ]; then
  BROKEN_SYMLINKS=()

  for hook in .claude/hooks/*.sh 2>/dev/null; do
    if [ -L "$hook" ] && [ ! -e "$hook" ]; then
      BROKEN_SYMLINKS+=("$(basename "$hook")")
    fi
  done

  if [ ${#BROKEN_SYMLINKS[@]} -gt 0 ]; then
    echo "  ⚠ Found broken symlinks: ${BROKEN_SYMLINKS[*]}"
    echo ""
    echo "  Hook symlinks may point to old locations after migration."
    echo "  If you have a knowledge repository with hooks, enter its path."
    echo ""
    read -p "  Knowledge repo path (or press Enter to skip): " KNOWLEDGE_REPO_PATH

    if [ -n "$KNOWLEDGE_REPO_PATH" ] && [ -d "$KNOWLEDGE_REPO_PATH/.claude/hooks" ]; then
      for hook_name in "${BROKEN_SYMLINKS[@]}"; do
        if [ -f "$KNOWLEDGE_REPO_PATH/.claude/hooks/$hook_name" ]; then
          rm -f ".claude/hooks/$hook_name"
          ln -s "$KNOWLEDGE_REPO_PATH/.claude/hooks/$hook_name" ".claude/hooks/$hook_name"
          echo "  ✓ Fixed: $hook_name -> $KNOWLEDGE_REPO_PATH/.claude/hooks/$hook_name"
        else
          echo "  ⚠ Hook not found in knowledge repo: $hook_name"
        fi
      done
    else
      echo "  Skipping symlink repair. Fix manually with:"
      echo "    ln -sf /path/to/hooks/file.sh .claude/hooks/"
    fi
  else
    echo "  ✓ All hook symlinks are valid"
  fi
else
  echo "  No hooks directory found"
fi

echo ""

# ============================================================================
# PHASE 6: VERIFICATION
# ============================================================================

echo "▶ Phase 6: Verifying migration..."

ERRORS=0

# Check required files exist
if [ -f ".mcp.json" ]; then
  echo "  ✓ .mcp.json exists"
else
  echo "  ✗ .mcp.json missing"
  ERRORS=$((ERRORS + 1))
fi

if [ -f "CLAUDE.md" ]; then
  echo "  ✓ CLAUDE.md exists"
else
  echo "  ✗ CLAUDE.md missing"
  ERRORS=$((ERRORS + 1))
fi

# Check removed files are gone
if [ -d ".claude/agents" ]; then
  echo "  ✗ .claude/agents/ still exists"
  ERRORS=$((ERRORS + 1))
else
  echo "  ✓ .claude/agents/ removed"
fi

if [ -d ".claude/commands" ]; then
  echo "  ✗ .claude/commands/ still exists"
  ERRORS=$((ERRORS + 1))
else
  echo "  ✓ .claude/commands/ removed"
fi

# Validate JSON
if command -v jq &> /dev/null; then
  if jq empty .mcp.json 2>/dev/null; then
    echo "  ✓ .mcp.json is valid JSON"
  else
    echo "  ✗ .mcp.json is invalid JSON"
    ERRORS=$((ERRORS + 1))
  fi

  if [ -f "knowledge-manifest.json" ]; then
    if jq empty knowledge-manifest.json 2>/dev/null; then
      echo "  ✓ knowledge-manifest.json is valid JSON"
    else
      echo "  ✗ knowledge-manifest.json is invalid JSON"
      ERRORS=$((ERRORS + 1))
    fi
  fi
fi

# Check for remaining broken symlinks
if [ -d ".claude/hooks" ]; then
  REMAINING_BROKEN=0
  for hook in .claude/hooks/*.sh 2>/dev/null; do
    if [ -L "$hook" ] && [ ! -e "$hook" ]; then
      echo "  ⚠ Broken symlink remains: $hook"
      REMAINING_BROKEN=$((REMAINING_BROKEN + 1))
    fi
  done
  if [ $REMAINING_BROKEN -eq 0 ]; then
    echo "  ✓ All hook symlinks valid"
  fi
fi

echo ""

# ============================================================================
# SUMMARY
# ============================================================================

if [ $ERRORS -eq 0 ]; then
  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║                    Migration Successful!                     ║"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo ""
  if [ -n "$PRESERVE_WORKSPACE_ID" ]; then
    echo "Memory preserved:"
    echo "  WORKSPACE_ID: $PRESERVE_WORKSPACE_ID"
    echo "  Your previous initiatives and memories are accessible."
    echo ""
  fi
  echo "Next steps:"
  echo "  1. Customize CLAUDE.md with project-specific details"
  echo "  2. Review .mcp.json configuration"
  if [ -f "knowledge-manifest.json" ]; then
    echo "  3. Review extracted extensions in .claude/extensions/"
  fi
  echo "  4. Restart Claude Code to load new MCP configuration"
  echo "  5. Test with /continue to verify memory access"
  echo "  6. Test with /protocol command"
  echo ""
  if [ -n "$PRESERVE_WORKSPACE_ID" ]; then
    echo "Important for future moves/renames:"
    echo "  Your WORKSPACE_ID ($PRESERVE_WORKSPACE_ID) is now in .mcp.json."
    echo "  This ensures memory persists across project path changes."
    echo ""
  fi
  if [ "$IS_GIT_REPO" = true ]; then
    echo "To commit:"
    echo "  git add -A && git commit -m 'feat: Migrate to machine-level Claude Copilot'"
    echo ""
    echo "To rollback:"
    echo "  git checkout $BACKUP_TAG"
  fi
else
  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║              Migration Completed with Errors                 ║"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo ""
  echo "  $ERRORS error(s) detected. Review above and fix manually."
  echo ""
  echo "To rollback:"
  if [ "$IS_GIT_REPO" = true ]; then
    echo "  git checkout $BACKUP_TAG"
  else
    echo "  cp -r .migration-archive/.claude ./"
  fi
fi

echo ""
