#!/usr/bin/env bash
# Explicit development installation with verified source/dependency receipts.
set -euo pipefail
unset PYTHONPATH PYTHONHOME
TC_SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TC_VENV_DIR="$TC_SOURCE_DIR/.venv"
TC_SHIM="$HOME/.local/bin/tc"
if [[ "${1:-}" == "--shim-path" && "$#" == 2 && "$2" == /* ]]; then
  TC_SHIM="$2"
elif [[ "$#" != 0 ]]; then
  echo 'Usage: install.sh [--shim-path ABSOLUTE_PATH]' >&2
  exit 2
fi
if [[ ! -x "$TC_VENV_DIR/bin/python" ]]; then python3 -m venv "$TC_VENV_DIR"; fi
if ! "$TC_VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1; then
  "$TC_VENV_DIR/bin/python" -m ensurepip --upgrade >/dev/null
fi
"$TC_VENV_DIR/bin/python" -m pip install --quiet -e "$TC_SOURCE_DIR"
"$TC_VENV_DIR/bin/tc" provenance --record --json >/dev/null
mkdir -p "$(dirname "$TC_SHIM")"
if [[ -L "$TC_SHIM" ]]; then echo 'Refusing to replace a symlink tc launcher' >&2; exit 1; fi
if [[ -f "$TC_SHIM" ]]; then
  TC_BACKUP="$(mktemp "${TC_SHIM}.previous.XXXXXX")"
  cp -p "$TC_SHIM" "$TC_BACKUP"
fi
TC_STAGE="$(mktemp "${TC_SHIM}.stage.XXXXXX")"
trap 'rm -f "$TC_STAGE"' EXIT
cp "$TC_VENV_DIR/bin/tc" "$TC_STAGE"
chmod +x "$TC_STAGE"
"$TC_STAGE" provenance --json >/dev/null
mv "$TC_STAGE" "$TC_SHIM"
echo "tc installation verified: $TC_SHIM"
