#!/usr/bin/env bash
# uninstall.sh — Remove the cc CLI shim
#
# Removes the shim at ~/.local/bin/cc. Does NOT remove the venv so that
# re-install is fast (no need to re-download packages).

set -euo pipefail

SHIM="$HOME/.local/bin/cc"

if [ -f "$SHIM" ]; then
    rm "$SHIM"
    echo "==> Removed shim at $SHIM"
else
    echo "==> No shim found at $SHIM (nothing to do)"
fi

echo "==> cc uninstalled."
echo "    To also remove the virtual environment, run:"
echo "      rm -rf $(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.venv"
