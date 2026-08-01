#!/usr/bin/env bash
#
# Make all installation scripts executable
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "Making installation scripts executable..."

# Installation scripts
chmod +x "$SCRIPT_DIR/check-dependencies.sh"
chmod +x "$SCRIPT_DIR/validate-installation.sh"

# Platform scripts
chmod +x "$SCRIPT_DIR/platforms/macos.sh"
chmod +x "$SCRIPT_DIR/platforms/linux.sh"

# This script itself
chmod +x "$SCRIPT_DIR/make-executable.sh"

echo "✓ All scripts are now executable"
echo ""
echo "Available scripts:"
echo "  ./scripts/install/check-dependencies.sh"
echo "  ./scripts/install/validate-installation.sh"
echo "  ./scripts/install/platforms/macos.sh"
echo "  ./scripts/install/platforms/linux.sh"
