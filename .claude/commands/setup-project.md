# Setup Project

Set up the current project with the complete Claude + Codex Copilot reference
installation. This command is a human-facing adapter over the canonical `cc`
transaction; it does not copy, delete, merge, or generate framework files
itself.

The canonical transaction installs `.claude/hooks/copilot-hook.sh`, marks it executable, registers the supported Claude hook events, and records the shim as a framework-owned file in `copilot.lock.json`. Independent verification must reject an installation whose shim is missing, non-executable, unregistered, or absent from the lock; this command must never replace that transaction with a manual copy.

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

## 3. Capture the project identity

This step is a person-authored addition after the transaction, not part of it. Run it only when apply returned `applied` in this run and verification reported this project's components `ready`. If apply was an already-ready no-op, if the run was an update, or if the plan was held, declined, or failed, skip this step entirely and do not ask the questions.

Also skip it when the project already has a project-authored description: read `CLAUDE.md` and `AGENTS.md` and treat any content outside the `<!-- cc:project-integration:...:start -->` / `<!-- cc:project-integration:...:end -->` blocks (an existing `## Project` section, an overview, or a description written by the person) as authoritative. Never overwrite it.

Otherwise use AskUserQuestion to ask, letting the person type freely and offering a skip option on every question (skipping every question writes nothing):

1. "What's this project about?" (header: "Description") - one or two sentences.
2. "What's the main tech stack?" (header: "Stack") - suggest options detected from the repository (for example `package.json`, `pyproject.toml`, `go.mod`) plus "Other (describe)".
3. "Anything else a new teammate or agent should know?" (header: "Notes") - conventions, how to run and test, constraints. Optional.

Write only the answers given, as a project-authored section, using the project folder name as the name:

```markdown
## Project

**Name:** <folder name>
**Description:** <answer>
**Stack:** <answer>
**Notes:** <answer>
```

Place the section in `CLAUDE.md`, and the same section in `AGENTS.md` so Codex sees it too. Put it above the framework block (directly after the title when there is one) and never edit between the framework's `cc:project-integration` markers, which the transaction owns; do not use the transaction's overwrite-project-instructions path. Omit lines for skipped questions. Do not duplicate machine-level settings such as output verbosity or Knowledge, which machine setup owns.

Finish by running `reconcile verify` again; the project must still report `ready`. If it does not, remove the section you added and report the verification result rather than leaving the project unverified.
