# Setup Project

Set up the current project with the complete Claude + Codex Copilot reference
installation. This command is a human-facing adapter over the canonical `cc`
transaction; it does not copy, delete, merge, or generate framework files
itself.

The former partial `minimal` / `quick start` profile is retired. It could not
produce the declared reference state and created a second repair path. If the
user asks for that profile, explain that setup now installs the complete local
reference while preserving existing memory and project-authored files, then
ask whether to continue. A decline stops without mutation. An existing minimal
installation is treated as degraded input and repaired through this same
transaction.

## 0. Verify the local CLI prerequisites

The cc-owned prerequisite fact must report both Copilot CLIs ready. It rejects
macOS' unrelated C compiler even when it is named `cc`, and names machine setup
as the person's recovery when either `cc` or `tc` is unavailable. Do not plan
or mutate on a failed prerequisite report.

## 1. Build and inspect the exact plan

Run this from the project root. The helper only creates a temporary request;
planning is read-only and the request is removed when the shell exits.

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

The plan is the authority. Explain its result in plain language, including
every held, owner-decision, or could-not-verify state. Do not apply a blocked
plan and do not suggest overwriting, resetting, stashing, or deleting a
person's work.

Ask the user to confirm the exact plan. If they decline, stop without changing
the project.

## 2. Apply the confirmed plan

Use the exact `plan_id` returned above. Recreate the same canonical request
and pass both to the guarded transaction. Replace `<PLAN_ID>` only with that
opaque value; never infer or reuse an older plan id.

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

Report success only when apply returns `applied` or an already-ready receipt
and the independent verification returns `ready`. The transaction owns
preflight, identity binding, Claude and Codex materialization, lock generation,
the completed-actions receipt, postconditions, snapshots, and rollback.

If the project is degraded but eligible, the plan repairs only verified
framework-owned targets. If it is dirty, ambiguous, customized beyond a
reviewed recipe, or cannot be verified, it is held for the named actor. Never
bypass that decision with manual file operations or a legacy installer.
