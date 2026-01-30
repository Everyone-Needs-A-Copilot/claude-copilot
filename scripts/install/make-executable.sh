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
chmod +x "$SCRIPT_DIR/build-servers.sh"
chmod +x "$SCRIPT_DIR/validate-installation.sh"

# Platform scripts
chmod +x "$SCRIPT_DIR/platforms/macos.sh"
chmod +x "$SCRIPT_DIR/platforms/linux.sh"

# NPM package scripts
chmod +x "$PROJECT_ROOT/packages/installer/bin/claude-copilot.js"
chmod +x "$PROJECT_ROOT/packages/installer/scripts/validate-package.js"

# This script itself
chmod +x "$SCRIPT_DIR/make-executable.sh"

echo "✓ All scripts are now executable"
echo ""
echo "Available scripts:"
echo "  ./scripts/install/check-dependencies.sh"
echo "  ./scripts/install/build-servers.sh"
echo "  ./scripts/install/validate-installation.sh"
echo "  ./scripts/install/platforms/macos.sh"
echo "  ./scripts/install/platforms/linux.sh"
echo ""
echo "NPM package:"
echo "  cd packages/installer && npm link"
echo "  claude-copilot install --help"
