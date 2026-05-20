#!/bin/bash
# Version Consistency Check
# Verifies that VERSION.json .framework and package.json .version are in sync.
# Exit 0 if equal, exit 1 with a clear error message if they diverge.
#
# Usage: scripts/test-version-consistency.sh [--repo-root <path>]
#   --repo-root  Path to repository root (default: directory containing this script's parent)

set -euo pipefail

# Resolve repo root: default to parent of scripts/ dir
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(dirname "$SCRIPT_DIR")}"

VERSION_JSON="$REPO_ROOT/VERSION.json"
PACKAGE_JSON="$REPO_ROOT/package.json"

if [ ! -f "$VERSION_JSON" ]; then
    echo "ERROR: VERSION.json not found at $VERSION_JSON" >&2
    exit 1
fi

if [ ! -f "$PACKAGE_JSON" ]; then
    echo "ERROR: package.json not found at $PACKAGE_JSON" >&2
    exit 1
fi

# Parse with jq if available, else python3 (both are dependency-free in the project)
if command -v jq >/dev/null 2>&1; then
    FRAMEWORK_VERSION=$(jq -r '.framework' "$VERSION_JSON")
    PACKAGE_VERSION=$(jq -r '.version' "$PACKAGE_JSON")
else
    FRAMEWORK_VERSION=$(python3 -c "import json,sys; print(json.load(open('$VERSION_JSON'))['framework'])")
    PACKAGE_VERSION=$(python3 -c "import json,sys; print(json.load(open('$PACKAGE_JSON'))['version'])")
fi

if [ "$FRAMEWORK_VERSION" = "$PACKAGE_VERSION" ]; then
    echo "OK: VERSION.json .framework ($FRAMEWORK_VERSION) == package.json .version ($PACKAGE_VERSION)"
    exit 0
else
    echo "ERROR: Version mismatch — VERSION.json .framework is '$FRAMEWORK_VERSION' but package.json .version is '$PACKAGE_VERSION'" >&2
    echo "  Fix: update both files to the same version before releasing." >&2
    exit 1
fi
