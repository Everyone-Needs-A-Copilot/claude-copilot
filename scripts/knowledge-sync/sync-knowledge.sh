#!/bin/bash
# Knowledge Sync
# Main entry point for syncing product knowledge on release tags

set -e

# Color codes
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

usage() {
    cat <<EOF
Usage: sync-knowledge.sh [OPTIONS]

Sync product knowledge to knowledge repository based on git release tag.

This script:
  1. Extracts changes between git tags
  2. Updates product knowledge file
  3. Auto-commits to knowledge repository

OPTIONS:
    --tag TAG               Release tag to process (default: latest)
    --product-name NAME     Product name (default: repo name)
    --knowledge-repo PATH   Knowledge repository path (default: ~/.claude/knowledge)
    --dry-run               Show what would happen without making changes
    --no-commit             Don't auto-commit changes
    -h, --help              Show this help

EXAMPLES:
    # Sync latest tag
    sync-knowledge.sh

    # Sync specific tag
    sync-knowledge.sh --tag v2.4.0

    # Dry run
    sync-knowledge.sh --tag v2.4.0 --dry-run

    # Sync without committing
    sync-knowledge.sh --tag v2.4.0 --no-commit
EOF
    exit 1
}

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse arguments
TAG=""
PRODUCT_NAME=""
KNOWLEDGE_REPO="$HOME/.claude/knowledge"
DRY_RUN=false
AUTO_COMMIT=true

while [[ $# -gt 0 ]]; do
    case $1 in
        --tag)
            TAG="$2"
            shift 2
            ;;
        --product-name)
            PRODUCT_NAME="$2"
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
        --no-commit)
            AUTO_COMMIT=false
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

# Verify we're in a git repository
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo -e "${RED}Error: Not in a git repository${NC}"
    exit 1
fi

# Auto-detect tag if not provided
if [ -z "$TAG" ]; then
    TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
    if [ -z "$TAG" ]; then
        echo -e "${RED}Error: No tags found in repository${NC}"
        echo ""
        echo "To create a release tag:"
        echo "  git tag v1.0.0"
        echo "  git push --tags"
        exit 1
    fi
    echo -e "${BLUE}Auto-detected latest tag: $TAG${NC}"
fi

# Auto-detect product name
if [ -z "$PRODUCT_NAME" ]; then
    PRODUCT_NAME=$(basename "$(git rev-parse --show-toplevel)")
    echo -e "${BLUE}Auto-detected product name: $PRODUCT_NAME${NC}"
fi

# Verify knowledge repository
if [ ! -d "$KNOWLEDGE_REPO" ]; then
    echo -e "${RED}Error: Knowledge repository not found at: $KNOWLEDGE_REPO${NC}"
    echo ""
    echo "To create a knowledge repository, run in Claude Code:"
    echo "  /knowledge-copilot"
    exit 1
fi

if [ ! -f "$KNOWLEDGE_REPO/knowledge-manifest.json" ]; then
    echo -e "${RED}Error: Invalid knowledge repository (missing manifest)${NC}"
    exit 1
fi

echo ""
echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}Knowledge Sync${NC}"
echo -e "${BLUE}=========================================${NC}"
echo ""
echo "Product:    $PRODUCT_NAME"
echo "Tag:        $TAG"
echo "Repository: $KNOWLEDGE_REPO"
echo ""

# Step 1: Extract changes
echo -e "${BLUE}Step 1: Extracting release changes...${NC}"
TEMP_CHANGES=$(mktemp)

"$SCRIPT_DIR/extract-release-changes.sh" \
    --to-tag "$TAG" \
    --product-name "$PRODUCT_NAME" \
    --output "$TEMP_CHANGES"

echo ""

# Step 2: Update knowledge
echo -e "${BLUE}Step 2: Updating product knowledge...${NC}"

UPDATE_ARGS="--version $TAG --product-name $PRODUCT_NAME --changes-file $TEMP_CHANGES --knowledge-repo $KNOWLEDGE_REPO"

if [ "$DRY_RUN" = true ]; then
    UPDATE_ARGS="$UPDATE_ARGS --dry-run"
fi

if [ "$AUTO_COMMIT" = true ]; then
    UPDATE_ARGS="$UPDATE_ARGS --auto-commit"
fi

"$SCRIPT_DIR/update-product-knowledge.sh" $UPDATE_ARGS

# Cleanup
rm "$TEMP_CHANGES"

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}Knowledge Sync Complete!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""

if [ "$DRY_RUN" = false ]; then
    echo "Next steps:"
    echo ""
    if [ "$AUTO_COMMIT" = true ]; then
        echo "  1. Review the commit in your knowledge repository:"
        echo "     cd $KNOWLEDGE_REPO && git log -1"
        echo ""
        echo "  2. Push to remote (if configured):"
        echo "     cd $KNOWLEDGE_REPO && git push"
    else
        echo "  1. Review changes:"
        echo "     cat $KNOWLEDGE_REPO/03-products/$PRODUCT_NAME.md"
        echo ""
        echo "  2. Commit manually:"
        echo "     cd $KNOWLEDGE_REPO"
        echo "     git add 03-products/$PRODUCT_NAME.md"
        echo "     git commit -m 'docs: Update $PRODUCT_NAME to $TAG'"
    fi
fi
