# Update Project

Update the current project's Claude + Codex Copilot installation through the
same canonical `cc` transaction used by `/setup-project`. Setup and update are
different user intentions, not different installers: current disk and lock
evidence determines whether the transaction performs a clean setup, a bounded
repair, an idempotent no-op, or a safety hold.

The canonical update repairs `.claude/hooks/copilot-hook.sh` only when ownership evidence permits it, preserves executable mode and hook registration, and refreshes its framework-owned checksum in `copilot.lock.json`. Independent verification must reject a missing, non-executable, unregistered, or unlocked shim; this command must never perform an untracked manual repair.

The former partial `minimal` profile is not a separate update target. Existing
minimal installations are degraded inputs to this complete transaction; their
project-authored instructions and memory are preserved while missing reference
artifacts are added.

Before planning, require the cc-owned prerequisite fact to report both the
actual Copilot `cc` CLI and `tc` ready. A missing CLI or macOS C compiler named
`cc` is a person-owned machine-setup prerequisite, not a project mutation.

## 1. Build and inspect the exact update plan

```bash
set -eu
CC_BIN=""
for CANDIDATE in "$(command -v cc 2>/dev/null || true)" "$HOME/.local/bin/cc"; do
  if [ -n "$CANDIDATE" ] && [ -x "$CANDIDATE" ] && "$CANDIDATE" --version 2>/dev/null | grep -q '^cc version'; then
    CC_BIN="$CANDIDATE"
    break
  fi
done
if [ -z "$CC_BIN" ] || ! command -v tc >/dev/null 2>&1; then
  echo "Claude Copilot machine setup is required: the Copilot cc and tc CLIs must both be available. Open ~/.claude/copilot, run /setup, open a fresh shell, then retry." >&2
  exit 3
fi
PROJECT_ROOT="$(git rev-parse --show-toplevel)"
REQUEST_FILE="$(mktemp -t cc-project-request.XXXXXX)"
CC_PATH_FILE="$(mktemp -t cc-project-cli.XXXXXX)"
trap 'rm -f "$REQUEST_FILE" "$CC_PATH_FILE"' EXIT
chmod 600 "$REQUEST_FILE" "$CC_PATH_FILE"
python3 - "$PROJECT_ROOT" "$REQUEST_FILE" "$CC_PATH_FILE" <<'PY'
import json
import sys
from pathlib import Path
from cc.core.ecosystem.canonical_transaction import (
    canonical_project_request_json,
    inspect_canonical_prerequisites,
)

prerequisites = inspect_canonical_prerequisites()
if not prerequisites["ready"]:
    print(json.dumps(prerequisites, sort_keys=True), file=sys.stderr)
    raise SystemExit(3)
Path(sys.argv[3]).write_text(str(prerequisites["cc"]["path"]), encoding="utf-8")
Path(sys.argv[2]).write_text(canonical_project_request_json(sys.argv[1]), encoding="utf-8")
PY
CC_BIN="$(cat "$CC_PATH_FILE")"
"$CC_BIN" reconcile plan --request "$REQUEST_FILE" --json
```

Explain the returned plan and any held or unverifiable state in plain language.
Ask the user to confirm the exact plan. Stop without mutation if they decline
or if the plan is blocked.

## 2. Apply and verify

Use only the fresh `plan_id` from the confirmed plan.

```bash
set -eu
CC_BIN=""
for CANDIDATE in "$(command -v cc 2>/dev/null || true)" "$HOME/.local/bin/cc"; do
  if [ -n "$CANDIDATE" ] && [ -x "$CANDIDATE" ] && "$CANDIDATE" --version 2>/dev/null | grep -q '^cc version'; then
    CC_BIN="$CANDIDATE"
    break
  fi
done
if [ -z "$CC_BIN" ] || ! command -v tc >/dev/null 2>&1; then
  echo "Claude Copilot machine setup is required: the Copilot cc and tc CLIs must both be available. Open ~/.claude/copilot, run /setup, open a fresh shell, then retry." >&2
  exit 3
fi
PROJECT_ROOT="$(git rev-parse --show-toplevel)"
REQUEST_FILE="$(mktemp -t cc-project-request.XXXXXX)"
CC_PATH_FILE="$(mktemp -t cc-project-cli.XXXXXX)"
trap 'rm -f "$REQUEST_FILE" "$CC_PATH_FILE"' EXIT
chmod 600 "$REQUEST_FILE" "$CC_PATH_FILE"
python3 - "$PROJECT_ROOT" "$REQUEST_FILE" "$CC_PATH_FILE" <<'PY'
import json
import sys
from pathlib import Path
from cc.core.ecosystem.canonical_transaction import (
    canonical_project_request_json,
    inspect_canonical_prerequisites,
)

prerequisites = inspect_canonical_prerequisites()
if not prerequisites["ready"]:
    print(json.dumps(prerequisites, sort_keys=True), file=sys.stderr)
    raise SystemExit(3)
Path(sys.argv[3]).write_text(str(prerequisites["cc"]["path"]), encoding="utf-8")
Path(sys.argv[2]).write_text(canonical_project_request_json(sys.argv[1]), encoding="utf-8")
PY
CC_BIN="$(cat "$CC_PATH_FILE")"
"$CC_BIN" reconcile apply --request "$REQUEST_FILE" --plan-id "<PLAN_ID>" --json
"$CC_BIN" reconcile verify --request "$REQUEST_FILE" --json
```

Report the ledger and independent verification. Success requires verified disk
state and the generated canonical lock to agree for both selected components.
Never run a repository-specific setup script, manually refresh a subset, or
replace project-owned content to make an update appear successful.
