#!/usr/bin/env bash
# install.sh — Install the cc CLI
#
# Creates a venv inside tools/cc/, installs cc in editable mode, then places
# a shim at ~/.local/bin/cc that points to the venv's Python interpreter.
# Safe to run multiple times (idempotent).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
SHIM_DIR="$HOME/.local/bin"
SHIM="$SHIM_DIR/cc"

echo "==> Installing cc CLI from $SCRIPT_DIR"

# Step 1: Create venv if not present
if [ ! -d "$VENV_DIR" ]; then
    echo "==> Creating virtual environment at $VENV_DIR"
    python3 -m venv "$VENV_DIR"
else
    echo "==> Virtual environment already exists at $VENV_DIR"
fi

# Step 2: Install/upgrade pip and install cc in editable mode
echo "==> Installing cc in editable mode"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -e "$SCRIPT_DIR"

# Step 3: Ensure shim directory exists
mkdir -p "$SHIM_DIR"

# Step 4: Place shim at ~/.local/bin/cc
# The venv's generated entry-point script already works standalone (it embeds
# its interpreter path), so we copy it to the shim location.
VENV_CC="$VENV_DIR/bin/cc"

if [ ! -f "$VENV_CC" ]; then
    echo "ERROR: Expected entry-point not found at $VENV_CC" >&2
    exit 1
fi

cp "$VENV_CC" "$SHIM"
chmod +x "$SHIM"

echo "==> Shim installed at $SHIM"

# Step 5: Verify
if "$SHIM" --version > /dev/null 2>&1; then
    echo "==> Verification passed: $("$SHIM" --version)"
else
    echo "ERROR: cc shim installed but '--version' failed" >&2
    exit 1
fi

echo ""

# Step 6: Add ~/.local/bin to PATH in shell profiles (idempotent)
PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
PATH_COMMENT='# Added by cc install'
PROFILES=("$HOME/.zshrc" "$HOME/.zprofile" "$HOME/.bashrc" "$HOME/.bash_profile")

for profile in "${PROFILES[@]}"; do
    if [ -f "$profile" ] && ! grep -qF '.local/bin' "$profile"; then
        printf '\n%s\n%s\n' "$PATH_COMMENT" "$PATH_LINE" >> "$profile"
        echo "==> Added ~/.local/bin to PATH in $profile"
    fi
done

echo "cc is installed. Reload your shell or run:"
echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
