#!/bin/bash
# Version Check Script
# Validates all Claude Copilot components are properly versioned and in sync

set -e

COPILOT_PATH="${COPILOT_PATH:-$HOME/.claude/copilot}"
VERSION_FILE="$COPILOT_PATH/VERSION.json"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Claude Copilot Version Check${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if VERSION.json exists
if [ ! -f "$VERSION_FILE" ]; then
    echo -e "${RED}❌ VERSION.json not found at $VERSION_FILE${NC}"
    exit 1
fi

# Get framework version
FRAMEWORK_VERSION=$(node -p "require('$VERSION_FILE').framework")
echo -e "Framework Version: ${GREEN}$FRAMEWORK_VERSION${NC}"
echo ""

# Check MCP Servers
echo -e "${BLUE}MCP Servers:${NC}"
ERRORS=0

check_mcp_server() {
    local name=$1
    local expected_version=$(node -p "require('$VERSION_FILE').components['mcp-servers']['$name'].version")
    local server_path="$COPILOT_PATH/mcp-servers/$name"

    if [ ! -d "$server_path" ]; then
        echo -e "  ${RED}❌ $name: Directory not found${NC}"
        ((ERRORS++))
        return
    fi

    # Check package.json version
    local actual_version=$(node -p "require('$server_path/package.json').version" 2>/dev/null || echo "unknown")

    # Check if built
    local check_file=$(node -p "require('$VERSION_FILE').components['mcp-servers']['$name'].checkFile")
    local is_built="no"
    if [ -f "$server_path/$check_file" ]; then
        is_built="yes"
    fi

    if [ "$actual_version" = "$expected_version" ] && [ "$is_built" = "yes" ]; then
        echo -e "  ${GREEN}✅ $name: v$actual_version (built)${NC}"
    elif [ "$actual_version" != "$expected_version" ]; then
        echo -e "  ${YELLOW}⚠️  $name: v$actual_version (expected v$expected_version)${NC}"
        ((ERRORS++))
    elif [ "$is_built" = "no" ]; then
        echo -e "  ${RED}❌ $name: v$actual_version (NOT BUILT - run npm run build)${NC}"
        ((ERRORS++))
    fi
}

check_mcp_server "copilot-memory"
check_mcp_server "skills-copilot"

echo ""

# Check Agents
echo -e "${BLUE}Agents:${NC}"
AGENT_PATH="$COPILOT_PATH/.claude/agents"
EXPECTED_COUNT=$(node -p "require('$VERSION_FILE').components.agents.count")
ACTUAL_COUNT=$(ls "$AGENT_PATH"/*.md 2>/dev/null | wc -l | tr -d ' ')

if [ "$ACTUAL_COUNT" -eq "$EXPECTED_COUNT" ]; then
    echo -e "  ${GREEN}✅ Agent count: $ACTUAL_COUNT${NC}"
else
    echo -e "  ${YELLOW}⚠️  Agent count: $ACTUAL_COUNT (expected $EXPECTED_COUNT)${NC}"
    ((ERRORS++))
fi

# Check required sections in agents
REQUIRED_SECTIONS=$(node -p "require('$VERSION_FILE').components.agents.requiredSections.join('|')")
MISSING_SECTIONS=0
for agent in "$AGENT_PATH"/*.md; do
    name=$(basename "$agent" .md)
    for section in "Task Copilot Integration" "Route To Other Agent"; do
        if ! grep -q "## $section" "$agent" 2>/dev/null; then
            echo -e "  ${RED}❌ $name.md missing: $section${NC}"
            MISSING_SECTIONS=$((MISSING_SECTIONS + 1))
        fi
    done
done

if [ $MISSING_SECTIONS -eq 0 ]; then
    echo -e "  ${GREEN}✅ All agents have required sections${NC}"
else
    ((ERRORS++))
fi

echo ""

# Check Global Paths
echo -e "${BLUE}Global Paths:${NC}"

check_path() {
    local name=$1
    local path=$2
    local expanded_path="${path/#\~/$HOME}"

    if [ -e "$expanded_path" ]; then
        if [ -L "$expanded_path" ]; then
            local target=$(readlink "$expanded_path")
            echo -e "  ${GREEN}✅ $name: $path → $target${NC}"
        else
            echo -e "  ${GREEN}✅ $name: $path${NC}"
        fi
    else
        echo -e "  ${YELLOW}⚠️  $name: $path (not found - will be created on first use)${NC}"
    fi
}

check_path "Skills" "~/.claude/skills"
check_path "Knowledge" "~/.claude/knowledge"
check_path "Memory DB" "~/.claude/memory"
echo ""

# Summary
echo -e "${BLUE}========================================${NC}"
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✅ All components verified${NC}"
else
    echo -e "${YELLOW}⚠️  $ERRORS issue(s) found${NC}"
    echo ""
    echo "To fix issues:"
    echo "  1. Rebuild MCP servers: cd ~/.claude/copilot && npm run build:all"
    echo "  2. Update framework: /update-copilot"
fi
echo -e "${BLUE}========================================${NC}"

exit $ERRORS
