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

ERRORS=0

# Check MCP Servers
echo -e "${BLUE}MCP Servers:${NC}"

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

# Check tc CLI
echo -e "${BLUE}Task Copilot CLI:${NC}"
if command -v tc >/dev/null 2>&1; then
    TC_VERSION=$(tc --version 2>/dev/null || echo "installed")
    echo -e "  ${GREEN}✅ tc CLI: $TC_VERSION${NC}"
elif [ -d "$COPILOT_PATH/tools/tc" ]; then
    echo -e "  ${YELLOW}⚠️  tc CLI: found at tools/tc/ but not on PATH${NC}"
    echo -e "      Install: cd $COPILOT_PATH/tools/tc && pip install -e ."
    ((ERRORS++))
else
    echo -e "  ${RED}❌ tc CLI: not found${NC}"
    ((ERRORS++))
fi

echo ""

# Check Agents
echo -e "${BLUE}Agents:${NC}"
AGENT_PATH="$COPILOT_PATH/.claude/agents"
EXPECTED_COUNT=$(node -p "require('$VERSION_FILE').components.agents.count")
ACTUAL_COUNT=$(ls "$AGENT_PATH"/*.md 2>/dev/null | wc -l | tr -d ' ')

if [ "$ACTUAL_COUNT" -eq "$EXPECTED_COUNT" ]; then
    echo -e "  ${GREEN}✅ Agent count: $ACTUAL_COUNT ($EXPECTED_COUNT expected)${NC}"
else
    echo -e "  ${YELLOW}⚠️  Agent count: $ACTUAL_COUNT (expected $EXPECTED_COUNT)${NC}"
    ((ERRORS++))
fi

# Check required sections on framework agents only
FRAMEWORK_AGENTS=$(node -p "require('$VERSION_FILE').components.agents.frameworkAgents.join(' ')")
REQUIRED_SECTIONS=$(node -p "require('$VERSION_FILE').components.agents.requiredSections.join('|')")
MISSING_SECTIONS=0

for agent_name in $FRAMEWORK_AGENTS; do
    agent="$AGENT_PATH/$agent_name.md"
    if [ ! -f "$agent" ]; then
        echo -e "  ${RED}❌ $agent_name.md: not found${NC}"
        MISSING_SECTIONS=$((MISSING_SECTIONS + 1))
        continue
    fi

    IFS='|' read -ra SECTIONS <<< "$REQUIRED_SECTIONS"
    for section in "${SECTIONS[@]}"; do
        if ! grep -q "## $section" "$agent" 2>/dev/null; then
            echo -e "  ${RED}❌ $agent_name.md missing: $section${NC}"
            MISSING_SECTIONS=$((MISSING_SECTIONS + 1))
        fi
    done
done

if [ $MISSING_SECTIONS -eq 0 ]; then
    echo -e "  ${GREEN}✅ All framework agents have required sections${NC}"
else
    ((ERRORS++))
fi

# Verify native agents exist
NATIVE_AGENTS=$(node -p "require('$VERSION_FILE').components.agents.nativeAgents.join(' ')")
MISSING_NATIVE=0
for agent_name in $NATIVE_AGENTS; do
    if [ ! -f "$AGENT_PATH/$agent_name.md" ]; then
        echo -e "  ${RED}❌ $agent_name.md (native): not found${NC}"
        MISSING_NATIVE=$((MISSING_NATIVE + 1))
    fi
done

if [ $MISSING_NATIVE -eq 0 ]; then
    echo -e "  ${GREEN}✅ All native agents present${NC}"
else
    ((ERRORS++))
fi

echo ""

# Check Commands
echo -e "${BLUE}Commands:${NC}"
COMMAND_PATH="$COPILOT_PATH/.claude/commands"
PROJECT_CMDS=$(node -p "require('$VERSION_FILE').components.commands.projectCommands.join(' ')")
MACHINE_CMDS=$(node -p "require('$VERSION_FILE').components.commands.machineCommands.join(' ')")

MISSING_CMDS=0
for cmd in $PROJECT_CMDS; do
    if [ ! -f "$COMMAND_PATH/$cmd" ]; then
        echo -e "  ${RED}❌ Project command missing: $cmd${NC}"
        MISSING_CMDS=$((MISSING_CMDS + 1))
    fi
done
for cmd in $MACHINE_CMDS; do
    if [ ! -f "$COMMAND_PATH/$cmd" ]; then
        echo -e "  ${RED}❌ Machine command missing: $cmd${NC}"
        MISSING_CMDS=$((MISSING_CMDS + 1))
    fi
done

if [ $MISSING_CMDS -eq 0 ]; then
    PROJECT_COUNT=$(echo $PROJECT_CMDS | wc -w | tr -d ' ')
    MACHINE_COUNT=$(echo $MACHINE_CMDS | wc -w | tr -d ' ')
    echo -e "  ${GREEN}✅ Project commands: $PROJECT_COUNT${NC}"
    echo -e "  ${GREEN}✅ Machine commands: $MACHINE_COUNT${NC}"
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
check_path "Tasks" "~/.claude/tasks"
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
    echo "  2. Install tc CLI: cd ~/.claude/copilot/tools/tc && pip install -e ."
    echo "  3. Update framework: /update-copilot"
fi
echo -e "${BLUE}========================================${NC}"

exit $ERRORS
