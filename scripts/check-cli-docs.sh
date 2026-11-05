#!/bin/sh
# Fast documentation check. No service actions, credentials or network.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
standard=${CLI_STANDARD_ROOT:-$root/../cli-copilot}
checker="$standard/scripts/check-cli-guide.py"
if [ ! -f "$checker" ]; then
  printf "%s\n" "Set CLI_STANDARD_ROOT to the cli-copilot checkout containing docs/04-cli-standard.md." >&2
  exit 2
fi
cd "$root"
exec "${PYTHON_BIN:-python3}" "$checker" tools/cc/CLI.md tools/tc/CLI.md
