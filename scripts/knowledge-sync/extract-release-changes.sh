#!/bin/bash
# Extract Release Changes
# Parses git commits between two tags to extract release information

set -e

# Color codes
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

usage() {
    cat <<EOF
Usage: extract-release-changes.sh [OPTIONS]

Extract changes between git tags for knowledge documentation.

OPTIONS:
    --from-tag TAG          Previous release tag (default: auto-detect)
    --to-tag TAG            Current release tag (default: auto-detect latest)
    --product-name NAME     Product name (default: repo name)
    --output FILE           Output file (default: stdout)
    --format FORMAT         Output format: markdown|json (default: markdown)
    -h, --help              Show this help

EXAMPLES:
    # Extract latest release
    extract-release-changes.sh --to-tag v2.4.0

    # Extract between specific tags
    extract-release-changes.sh --from-tag v2.3.0 --to-tag v2.4.0

    # Output to file
    extract-release-changes.sh --to-tag v2.4.0 --output /tmp/changes.md
EOF
    exit 1
}

# Parse arguments
FROM_TAG=""
TO_TAG=""
PRODUCT_NAME=""
OUTPUT_FILE=""
FORMAT="markdown"

while [[ $# -gt 0 ]]; do
    case $1 in
        --from-tag)
            FROM_TAG="$2"
            shift 2
            ;;
        --to-tag)
            TO_TAG="$2"
            shift 2
            ;;
        --product-name)
            PRODUCT_NAME="$2"
            shift 2
            ;;
        --output)
            OUTPUT_FILE="$2"
            shift 2
            ;;
        --format)
            FORMAT="$2"
            shift 2
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

# Auto-detect tags if not provided
if [ -z "$TO_TAG" ]; then
    TO_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
    if [ -z "$TO_TAG" ]; then
        echo "Error: No tags found. Please create a release tag first."
        exit 1
    fi
    echo -e "${BLUE}Auto-detected latest tag: $TO_TAG${NC}" >&2
fi

if [ -z "$FROM_TAG" ]; then
    # Get the tag before TO_TAG
    FROM_TAG=$(git describe --tags --abbrev=0 "$TO_TAG^" 2>/dev/null || echo "")
    if [ -n "$FROM_TAG" ]; then
        echo -e "${BLUE}Auto-detected previous tag: $FROM_TAG${NC}" >&2
    else
        echo -e "${YELLOW}No previous tag found. Using all commits up to $TO_TAG${NC}" >&2
        FROM_TAG=""
    fi
fi

# Auto-detect product name
if [ -z "$PRODUCT_NAME" ]; then
    PRODUCT_NAME=$(basename "$(git rev-parse --show-toplevel)")
    echo -e "${BLUE}Auto-detected product name: $PRODUCT_NAME${NC}" >&2
fi

# Verify tags exist
if ! git rev-parse "$TO_TAG" >/dev/null 2>&1; then
    echo "Error: Tag '$TO_TAG' does not exist"
    exit 1
fi

if [ -n "$FROM_TAG" ] && ! git rev-parse "$FROM_TAG" >/dev/null 2>&1; then
    echo "Error: Tag '$FROM_TAG' does not exist"
    exit 1
fi

# Extract commit range
if [ -n "$FROM_TAG" ]; then
    COMMIT_RANGE="$FROM_TAG..$TO_TAG"
else
    COMMIT_RANGE="$TO_TAG"
fi

echo -e "${BLUE}Extracting changes: $COMMIT_RANGE${NC}" >&2

# Categorize commits
declare -a FEATURES
declare -a FIXES
declare -a BREAKING
declare -a CHORES
declare -a DOCS
declare -a OTHER

# Parse commits
while IFS= read -r commit; do
    # Get commit message
    message=$(git log -1 --format=%s "$commit")
    body=$(git log -1 --format=%b "$commit")

    # Categorize based on conventional commits
    if [[ $message =~ ^feat(\(.*\))?!: ]] || [[ $body =~ BREAKING\ CHANGE ]]; then
        BREAKING+=("$message")
    elif [[ $message =~ ^feat(\(.*\))?: ]]; then
        FEATURES+=("$message")
    elif [[ $message =~ ^fix(\(.*\))?: ]]; then
        FIXES+=("$message")
    elif [[ $message =~ ^chore(\(.*\))?: ]]; then
        CHORES+=("$message")
    elif [[ $message =~ ^docs(\(.*\))?: ]]; then
        DOCS+=("$message")
    else
        OTHER+=("$message")
    fi
done < <(git rev-list "$COMMIT_RANGE")

# Format output
format_markdown() {
    cat <<EOF
# Release: $TO_TAG

**Product:** $PRODUCT_NAME
**Release Date:** $(git log -1 --format=%ai "$TO_TAG" | cut -d' ' -f1)
**Commits:** $(git rev-list --count "$COMMIT_RANGE")
EOF

    if [ ${#BREAKING[@]} -gt 0 ]; then
        echo ""
        echo "## ⚠️ Breaking Changes"
        echo ""
        for item in "${BREAKING[@]}"; do
            echo "- $item"
        done
    fi

    if [ ${#FEATURES[@]} -gt 0 ]; then
        echo ""
        echo "## ✨ Features"
        echo ""
        for item in "${FEATURES[@]}"; do
            echo "- $item"
        done
    fi

    if [ ${#FIXES[@]} -gt 0 ]; then
        echo ""
        echo "## 🐛 Fixes"
        echo ""
        for item in "${FIXES[@]}"; do
            echo "- $item"
        done
    fi

    if [ ${#CHORES[@]} -gt 0 ]; then
        echo ""
        echo "## 🔧 Chores"
        echo ""
        for item in "${CHORES[@]}"; do
            echo "- $item"
        done
    fi

    if [ ${#DOCS[@]} -gt 0 ]; then
        echo ""
        echo "## 📚 Documentation"
        echo ""
        for item in "${DOCS[@]}"; do
            echo "- $item"
        done
    fi

    if [ ${#OTHER[@]} -gt 0 ]; then
        echo ""
        echo "## Other Changes"
        echo ""
        for item in "${OTHER[@]}"; do
            echo "- $item"
        done
    fi
}

format_json() {
    cat <<EOF
{
  "version": "$TO_TAG",
  "product": "$PRODUCT_NAME",
  "releaseDate": "$(git log -1 --format=%ai "$TO_TAG" | cut -d' ' -f1)",
  "commitCount": $(git rev-list --count "$COMMIT_RANGE"),
  "breaking": [$(printf '"%s",' "${BREAKING[@]}" | sed 's/,$//')],
  "features": [$(printf '"%s",' "${FEATURES[@]}" | sed 's/,$//')],
  "fixes": [$(printf '"%s",' "${FIXES[@]}" | sed 's/,$//')],
  "chores": [$(printf '"%s",' "${CHORES[@]}" | sed 's/,$//')],
  "docs": [$(printf '"%s",' "${DOCS[@]}" | sed 's/,$//')],
  "other": [$(printf '"%s",' "${OTHER[@]}" | sed 's/,$//')]
}
EOF
}

# Generate output
if [ "$FORMAT" = "json" ]; then
    OUTPUT=$(format_json)
else
    OUTPUT=$(format_markdown)
fi

# Write to file or stdout
if [ -n "$OUTPUT_FILE" ]; then
    echo "$OUTPUT" > "$OUTPUT_FILE"
    echo -e "${GREEN}✅ Changes extracted to: $OUTPUT_FILE${NC}" >&2
else
    echo "$OUTPUT"
fi
