#!/usr/bin/env bash
# install.sh — Install the Claude Copilot CLI bundle
#
# Creates a venv inside tools/cc/, installs cc and its bundled Task Copilot
# ledger from the same framework source, then places a shim at ~/.local/bin/cc
# that points to the venv's Python interpreter. The supported runtime is this
# framework bundle; a standalone claude-cli wheel is not a supported journey
# enforcement installation.
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

Install the framework-owned cc + Task Copilot runtime bundle. A standalone cc
wheel does not contain the durable Task Copilot ledger required by journey
dispatch verification.

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

echo "==> Installing Claude Copilot CLI bundle from $SCRIPT_DIR"

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

# Step 2: Install/upgrade pip and install both framework-owned runtime packages.
# cc journey uses Task Copilot's public Python API as its durable evidence
# ledger. Installing both local packages non-editably makes the venv an exact
# installed artifact instead of relying on a checkout path injected by .pth.
# Source authors rerun this idempotent installer after changing either package.
echo "==> Installing cc + Task Copilot from the framework source"
if [ ! -f "$TC_DIR/pyproject.toml" ]; then
    echo "ERROR: Bundled Task Copilot package not found at $TC_DIR" >&2
    exit 1
fi
"$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip
"$VENV_DIR/bin/python" -m pip install --quiet --upgrade --force-reinstall "$TC_DIR" "$SCRIPT_DIR"
"$VENV_DIR/bin/python" - "$VENV_DIR" "$SCRIPT_DIR/src" "$TC_DIR/src" <<'PY' || {
import importlib.util
import pathlib
import site
import sys

venv, cc_source, tc_source = (pathlib.Path(value).resolve() for value in sys.argv[1:])
for package, source in (("cc", cc_source), ("tc", tc_source)):
    spec = importlib.util.find_spec(package)
    origin = pathlib.Path(spec.origin).resolve() if spec and spec.origin else None
    if origin is None or not origin.is_relative_to(venv):
        raise SystemExit(f"{package} did not install inside the private framework venv: {origin}")
    if origin.is_relative_to(source):
        raise SystemExit(f"{package} still resolves through its source checkout: {origin}")
for directory in map(pathlib.Path, site.getsitepackages()):
    for path in directory.glob("*.pth"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if str(cc_source) in text or str(tc_source) in text:
            raise SystemExit(f"editable source path remains in {path}")
import tc.api  # noqa: F401, E402
from tc.db.connection import find_db_path  # noqa: F401, E402
PY
    echo "ERROR: cc runtime is not an isolated cc + Task Copilot bundle" >&2
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

# Step 5: Verify the public command and the hidden fail-closed hook boundary.
if "$SHIM" --version > /dev/null 2>&1; then
    echo "==> Verification passed: $("$SHIM" --version)"
else
    echo "ERROR: cc shim installed but '--version' failed" >&2
    exit 1
fi

(
    PROBE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/cc-install-probe.XXXXXX")"
    trap 'rm -rf "$PROBE_ROOT"' EXIT
    mkdir -p "$PROBE_ROOT/home" "$PROBE_ROOT/work"
    cd "$PROBE_ROOT/work"
    PROBE_RESULT="$(
        env -i \
            HOME="$PROBE_ROOT/home" \
            PATH="/usr/bin:/bin" \
            "$SHIM" journey verify-dispatch \
                --session cc-install-probe \
                --subagent qa \
                --prompt-sha256 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
                --json
    )"
    if [ "$PROBE_RESULT" != '{"schema_version": "2.1", "state": "no_active"}' ]; then
        echo "ERROR: isolated journey dispatch verification returned: $PROBE_RESULT" >&2
        exit 1
    fi
)
echo "==> Verification passed: isolated journey dispatch ledger is available"

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

echo "The cc + Task Copilot runtime bundle is installed. Reload your shell or run:"
echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
