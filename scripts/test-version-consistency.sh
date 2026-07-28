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

FAIL=0

if [ "$FRAMEWORK_VERSION" = "$PACKAGE_VERSION" ]; then
    echo "OK: VERSION.json .framework ($FRAMEWORK_VERSION) == package.json .version ($PACKAGE_VERSION)"
else
    echo "ERROR: Version mismatch — VERSION.json .framework is '$FRAMEWORK_VERSION' but package.json .version is '$PACKAGE_VERSION'" >&2
    echo "  Fix: update both files to the same version before releasing." >&2
    FAIL=1
fi

# ── Runtime __version__ guards ────────────────────────────────────────────────
# Ensures tools/cc and tools/tc __init__.py __version__ strings are kept in
# sync with their respective pyproject.toml versions so stale runtime strings
# can't slip through a release bump again.

check_init_version() {
    local tool_name="$1"           # "cc" or "tc"
    local init_file="$2"           # absolute path to __init__.py
    local pyproject_file="$3"      # absolute path to pyproject.toml

    if [ ! -f "$init_file" ]; then
        echo "ERROR: $tool_name __init__.py not found at $init_file" >&2
        return 1
    fi
    if [ ! -f "$pyproject_file" ]; then
        echo "ERROR: $tool_name pyproject.toml not found at $pyproject_file" >&2
        return 1
    fi

    # Extract __version__ = "x.y.z" from __init__.py
    local init_ver
    init_ver=$(python3 -c "
import re, sys
content = open('$init_file').read()
m = re.search(r'__version__\s*=\s*[\"\\']([^\"\\'>]+)[\"\\']', content)
print(m.group(1) if m else '')
")

    # Extract version from pyproject.toml [project] table
    local pyproject_ver
    pyproject_ver=$(python3 -c "
import re, sys
content = open('$pyproject_file').read()
m = re.search(r'(?m)^\s*version\s*=\s*[\"\\']([^\"\\'>]+)[\"\\']', content)
print(m.group(1) if m else '')
")

    if [ -z "$init_ver" ]; then
        echo "ERROR: Could not parse __version__ from $init_file" >&2
        return 1
    fi
    if [ -z "$pyproject_ver" ]; then
        echo "ERROR: Could not parse version from $pyproject_file" >&2
        return 1
    fi

    if [ "$init_ver" = "$pyproject_ver" ]; then
        echo "OK: $tool_name __init__.__version__ ($init_ver) == pyproject.toml version ($pyproject_ver)"
    else
        echo "ERROR: $tool_name runtime __version__ mismatch — __init__.py is '$init_ver' but pyproject.toml is '$pyproject_ver'" >&2
        echo "  Fix: update $init_file __version__ to match pyproject.toml before releasing." >&2
        return 1
    fi
}

check_init_version "cc" \
    "$REPO_ROOT/tools/cc/src/cc/__init__.py" \
    "$REPO_ROOT/tools/cc/pyproject.toml" || FAIL=1

check_init_version "tc" \
    "$REPO_ROOT/tools/tc/src/tc/__init__.py" \
    "$REPO_ROOT/tools/tc/pyproject.toml" || FAIL=1

exit $FAIL
