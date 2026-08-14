#!/usr/bin/env bash
# install.sh — Install the cc CLI
#
# Creates a venv inside tools/cc/, installs cc in editable mode, then places
# a shim at ~/.local/bin/cc that points to the venv's Python interpreter.
# Safe to run multiple times (idempotent).
#
# The framework snapshot installer uses --shim-path/--no-profile-update to
# stage and verify this entry point before it atomically activates the whole
# machine runtime. Ordinary direct callers retain the historical defaults.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
TC_DIR="$SCRIPT_DIR/../tc"
SHIM="$HOME/.local/bin/cc"
UPDATE_PROFILES=1

usage() {
    cat <<'EOF'
Usage: install.sh [--shim-path ABSOLUTE_PATH] [--no-profile-update]

  --shim-path ABSOLUTE_PATH  Write and verify the cc shim at this path.
  --no-profile-update        Do not edit shell startup files.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --shim-path)
            [ "$#" -ge 2 ] || { echo "ERROR: --shim-path requires a value" >&2; exit 2; }
            SHIM="$2"
            case "$SHIM" in
                /*) ;;
                *) echo "ERROR: --shim-path must be absolute" >&2; exit 2 ;;
            esac
            shift 2
            ;;
        --no-profile-update)
            UPDATE_PROFILES=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

SHIM_DIR="$(dirname "$SHIM")"

echo "==> Installing cc CLI from $SCRIPT_DIR"

# Step 1: Create venv if not present
if [ ! -d "$VENV_DIR" ]; then
    echo "==> Creating virtual environment at $VENV_DIR"
    python3 -m venv "$VENV_DIR"
else
    echo "==> Virtual environment already exists at $VENV_DIR"
fi

# uv creates valid virtual environments without seeding pip by default. An
# existing cc development venv may therefore have Python but no pip entry
# point; bootstrap it in place instead of treating the venv as corrupt.
if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "ERROR: Existing cc virtual environment has no Python interpreter" >&2
    exit 1
fi
if ! "$VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1; then
    echo "==> Bootstrapping pip in the existing virtual environment"
    "$VENV_DIR/bin/python" -m ensurepip --upgrade >/dev/null
fi

# Step 2: Install/upgrade pip and install the runtime packages in editable mode.
# cc journey uses Task Copilot's public Python API as its durable evidence
# ledger. Installing only cc leaves every Agent dispatch unable to distinguish
# "no active journey" from "verifier unavailable" and therefore fail-closed.
echo "==> Installing cc in editable mode"
if [ ! -f "$TC_DIR/pyproject.toml" ]; then
    echo "ERROR: Bundled Task Copilot package not found at $TC_DIR" >&2
    exit 1
fi
"$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip
"$VENV_DIR/bin/python" -m pip install --quiet -e "$TC_DIR"
"$VENV_DIR/bin/python" -m pip install --quiet -e "$SCRIPT_DIR"
"$VENV_DIR/bin/python" -c 'import tc.api' || {
    echo "ERROR: cc runtime cannot import the Task Copilot evidence API" >&2
    exit 1
}

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
if [ "$UPDATE_PROFILES" -eq 1 ]; then
    PROFILES=("$HOME/.zshrc" "$HOME/.zprofile" "$HOME/.bashrc" "$HOME/.bash_profile")

    for profile in "${PROFILES[@]}"; do
        if [ -f "$profile" ] && ! grep -qF '.local/bin' "$profile"; then
            printf '\n%s\n%s\n' "$PATH_COMMENT" "$PATH_LINE" >> "$profile"
            echo "==> Added ~/.local/bin to PATH in $profile"
        fi
    done
fi

echo "cc is installed. Reload your shell or run:"
echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
