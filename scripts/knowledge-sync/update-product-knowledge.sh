#!/bin/bash
# Update Product Knowledge
# Updates knowledge repository with release information

set -e

# Color codes
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

usage() {
    cat <<EOF
Usage: update-product-knowledge.sh [OPTIONS]

Update product knowledge file with release information.

OPTIONS:
    --version TAG           Release version/tag (required)
    --product-name NAME     Product name (default: repo name)
    --changes-file FILE     File with extracted changes (default: stdin)
    --knowledge-repo PATH   Knowledge repository path (default: ~/.claude/knowledge)
    --dry-run               Show what would be updated without writing
    --auto-commit           Auto-commit changes to knowledge repo
    -h, --help              Show this help

EXAMPLES:
    # Update with changes from file
    update-product-knowledge.sh --version v2.4.0 --changes-file /tmp/changes.md

    # Update with piped input
    extract-release-changes.sh --to-tag v2.4.0 | update-product-knowledge.sh --version v2.4.0

    # Dry run to preview
    update-product-knowledge.sh --version v2.4.0 --changes-file /tmp/changes.md --dry-run

    # Auto-commit changes
    update-product-knowledge.sh --version v2.4.0 --changes-file /tmp/changes.md --auto-commit
EOF
    exit 1
}

# Parse arguments
VERSION=""
PRODUCT_NAME=""
CHANGES_FILE=""
KNOWLEDGE_REPO="$HOME/.claude/knowledge"
DRY_RUN=false
AUTO_COMMIT=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --version)
            VERSION="$2"
            shift 2
            ;;
        --product-name)
            PRODUCT_NAME="$2"
            shift 2
            ;;
        --changes-file)
            CHANGES_FILE="$2"
            shift 2
            ;;
        --knowledge-repo)
            KNOWLEDGE_REPO="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --auto-commit)
            AUTO_COMMIT=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

# Validate required arguments
if [ -z "$VERSION" ]; then
    echo "Error: --version is required"
    usage
fi

# Auto-detect product name
if [ -z "$PRODUCT_NAME" ]; then
    PRODUCT_NAME=$(basename "$(git rev-parse --show-toplevel)")
    echo -e "${BLUE}Auto-detected product name: $PRODUCT_NAME${NC}" >&2
fi

# Verify knowledge repository exists
if [ ! -d "$KNOWLEDGE_REPO" ]; then
    echo -e "${RED}Error: Knowledge repository not found at: $KNOWLEDGE_REPO${NC}"
    echo ""
    echo "To create a knowledge repository:"
    echo "  1. Run /knowledge-copilot in Claude Code"
    echo "  2. Or manually create: mkdir -p ~/.claude/knowledge"
    exit 1
fi

# Verify manifest exists
if [ ! -f "$KNOWLEDGE_REPO/knowledge-manifest.json" ]; then
    echo -e "${RED}Error: knowledge-manifest.json not found${NC}"
    echo "This doesn't appear to be a valid knowledge repository."
    exit 1
fi

# Read changes from file or stdin
if [ -n "$CHANGES_FILE" ]; then
    if [ ! -f "$CHANGES_FILE" ]; then
        echo "Error: Changes file not found: $CHANGES_FILE"
        exit 1
    fi
    CHANGES=$(cat "$CHANGES_FILE")
else
    # Read from stdin
    CHANGES=$(cat)
fi

# Ensure products directory exists
PRODUCTS_DIR="$KNOWLEDGE_REPO/03-products"
if [ ! -d "$PRODUCTS_DIR" ]; then
    echo -e "${YELLOW}Creating products directory: $PRODUCTS_DIR${NC}" >&2
    mkdir -p "$PRODUCTS_DIR"
fi

# Product file path
PRODUCT_FILE="$PRODUCTS_DIR/${PRODUCT_NAME}.md"

# Check if product file exists
if [ -f "$PRODUCT_FILE" ]; then
    echo -e "${BLUE}Updating existing product file: $PRODUCT_FILE${NC}" >&2
    UPDATE_MODE="update"
else
    echo -e "${BLUE}Creating new product file: $PRODUCT_FILE${NC}" >&2
    UPDATE_MODE="create"
fi

# Create or update product file
create_product_file() {
    local temp_file=$(mktemp)

    # If updating, preserve content before ## Recent Changes
    if [ "$UPDATE_MODE" = "update" ]; then
        # Extract everything before ## Recent Changes
        awk '/^## Recent Changes$/{exit} {print}' "$PRODUCT_FILE" > "$temp_file"
        # Remove trailing empty lines (BSD-compatible)
        local trimmed
        trimmed=$(awk 'NF{p=1} p' "$temp_file" | awk '{a[NR]=$0} END{for(i=NR;i>=1&&a[i]=="";i--);for(j=1;j<=i;j++)print a[j]}')
        echo "$trimmed" > "$temp_file"
    else
        # Create new file with template
        cat > "$temp_file" <<EOF
# Product: $PRODUCT_NAME

## Overview
Auto-generated product knowledge from git releases.

## Current Capabilities
See recent changes below for features and capabilities.

## Architecture
Update this section with architectural details.

## Integration Points
Update this section with integration details.
EOF
    fi

    # Add Recent Changes section
    cat >> "$temp_file" <<EOF

## Recent Changes
EOF

    # Add current release
    echo "$CHANGES" | sed 's/^# Release: /### /' >> "$temp_file"

    # If updating, preserve older releases (limit to last 10)
    if [ "$UPDATE_MODE" = "update" ]; then
        # Extract old releases - everything after ## Recent Changes header
        awk '/^## Recent Changes$/{found=1; next} found' "$PRODUCT_FILE" | \
            head -n 500 >> "$temp_file" || true
    fi

    echo "$temp_file"
}

# Generate updated content
TEMP_FILE=$(create_product_file)

# Show diff if not a new file
if [ "$UPDATE_MODE" = "update" ]; then
    echo ""
    echo -e "${BLUE}Changes to be applied:${NC}"
    echo "-----------------------------------"
    diff -u "$PRODUCT_FILE" "$TEMP_FILE" || true
    echo "-----------------------------------"
    echo ""
fi

# Dry run or apply changes
if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}DRY RUN - No changes written${NC}"
    echo ""
    echo "Would write to: $PRODUCT_FILE"
    echo ""
    cat "$TEMP_FILE"
    rm "$TEMP_FILE"
    exit 0
fi

# Write changes
cp "$TEMP_FILE" "$PRODUCT_FILE"
rm "$TEMP_FILE"

echo -e "${GREEN}✅ Product knowledge updated: $PRODUCT_FILE${NC}"

# Auto-commit if requested
if [ "$AUTO_COMMIT" = true ]; then
    cd "$KNOWLEDGE_REPO"

    # Check if it's a git repo
    if [ ! -d ".git" ]; then
        echo -e "${YELLOW}Knowledge repository is not a git repo. Skipping commit.${NC}"
        exit 0
    fi

    # Stage changes
    git add "$PRODUCT_FILE"

    # Check if there are changes to commit
    if git diff --cached --quiet; then
        echo -e "${YELLOW}No changes to commit${NC}"
    else
        # Commit
        git commit -m "docs(products): Update $PRODUCT_NAME to $VERSION

Auto-generated knowledge update from release tag.
" 2>&1

        echo -e "${GREEN}✅ Changes committed to knowledge repository${NC}"

        # Check if remote exists
        if git remote get-url origin >/dev/null 2>&1; then
            echo ""
            echo "To push to remote:"
            echo "  cd $KNOWLEDGE_REPO && git push"
        fi
    fi
fi
