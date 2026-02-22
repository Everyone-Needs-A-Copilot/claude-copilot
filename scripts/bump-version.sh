#!/bin/bash
# Version Bump Script
# Bumps version across all Claude Copilot components

set -e

COPILOT_PATH="${COPILOT_PATH:-$HOME/.claude/copilot}"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

usage() {
    cat <<EOF
Usage: bump-version.sh <new-version> [--component <name>]

Bump version across Claude Copilot framework.

Arguments:
    new-version         New version number (e.g., 2.6.0)

Options:
    --component <name>  Only bump specific component (mcp-memory, mcp-skills)
    --dry-run           Show what would be changed without modifying files
    -h, --help          Show this help

Examples:
    bump-version.sh 2.6.0              # Bump all versions to 2.6.0
    bump-version.sh 2.1.0 --component mcp-memory  # Bump only Memory Copilot
    bump-version.sh 2.6.0 --dry-run    # Preview changes
EOF
    exit 1
}

# Parse arguments
NEW_VERSION=""
COMPONENT=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --component)
            COMPONENT="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            if [ -z "$NEW_VERSION" ]; then
                NEW_VERSION="$1"
            fi
            shift
            ;;
    esac
done

if [ -z "$NEW_VERSION" ]; then
    echo "Error: Version number required"
    usage
fi

# Validate version format
if ! [[ "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: Invalid version format. Use X.Y.Z (e.g., 2.6.0)"
    exit 1
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Bumping to version $NEW_VERSION${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

update_file() {
    local file=$1
    local pattern=$2
    local replacement=$3
    local description=$4

    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would update $description"
        echo "  File: $file"
        echo "  Pattern: $pattern → $replacement"
    else
        if [ -f "$file" ]; then
            # Use node for JSON files, sed for others
            if [[ "$file" == *.json ]]; then
                node -e "
                    const fs = require('fs');
                    const content = JSON.parse(fs.readFileSync('$file', 'utf8'));
                    content.version = '$NEW_VERSION';
                    if (content.lastUpdated) content.lastUpdated = new Date().toISOString();
                    fs.writeFileSync('$file', JSON.stringify(content, null, 2) + '\n');
                "
            fi
            echo -e "${GREEN}✅ Updated $description${NC}"
        else
            echo -e "${YELLOW}⚠️  File not found: $file${NC}"
        fi
    fi
}

# Update main package.json
if [ -z "$COMPONENT" ] || [ "$COMPONENT" = "framework" ]; then
    update_file "$COPILOT_PATH/package.json" "version" "$NEW_VERSION" "Main framework (package.json)"
fi

# Update VERSION.json
if [ -z "$COMPONENT" ]; then
    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would update VERSION.json"
    else
        node -e "
            const fs = require('fs');
            const file = '$COPILOT_PATH/VERSION.json';
            const content = JSON.parse(fs.readFileSync(file, 'utf8'));
            content.framework = '$NEW_VERSION';
            content.lastUpdated = new Date().toISOString();
            content.components.agents.version = '$NEW_VERSION';
            content.components.commands.version = '$NEW_VERSION';
            content.components.skills.version = '$NEW_VERSION';
            content.components.templates.version = '$NEW_VERSION';
            fs.writeFileSync(file, JSON.stringify(content, null, 2) + '\n');
        "
        echo -e "${GREEN}✅ Updated VERSION.json${NC}"
    fi
fi

# Update MCP server versions
update_mcp_server() {
    local name=$1
    local pkg_path="$COPILOT_PATH/mcp-servers/$name/package.json"

    if [ -f "$pkg_path" ]; then
        if [ "$DRY_RUN" = true ]; then
            echo -e "${YELLOW}[DRY-RUN]${NC} Would update $name"
        else
            node -e "
                const fs = require('fs');
                const content = JSON.parse(fs.readFileSync('$pkg_path', 'utf8'));
                content.version = '$NEW_VERSION';
                fs.writeFileSync('$pkg_path', JSON.stringify(content, null, 2) + '\n');
            "

            # Also update VERSION.json
            node -e "
                const fs = require('fs');
                const file = '$COPILOT_PATH/VERSION.json';
                const content = JSON.parse(fs.readFileSync(file, 'utf8'));
                content.components['mcp-servers']['$name'].version = '$NEW_VERSION';
                fs.writeFileSync(file, JSON.stringify(content, null, 2) + '\n');
            "
            echo -e "${GREEN}✅ Updated $name to v$NEW_VERSION${NC}"
        fi
    fi
}

case "$COMPONENT" in
    ""|"all")
        update_mcp_server "copilot-memory"
        update_mcp_server "skills-copilot"
        ;;
    "mcp-memory"|"copilot-memory")
        update_mcp_server "copilot-memory"
        ;;
    "mcp-skills"|"skills-copilot")
        update_mcp_server "skills-copilot"
        ;;
esac

echo ""
echo -e "${BLUE}========================================${NC}"

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}Dry run complete. No files modified.${NC}"
else
    echo -e "${GREEN}Version bump complete!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Rebuild MCP servers: cd ~/.claude/copilot && npm run build:all"
    echo "  2. Run version check: ./scripts/check-versions.sh"
    echo "  3. Commit changes: git add -A && git commit -m 'chore(release): Bump version to $NEW_VERSION'"
fi
echo -e "${BLUE}========================================${NC}"
