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

## Solo and organization setups

This command works with or without an organization. When the Mac has no
organization at all (no `layers.manifest` configured and no inherited
organization config), `cc` treats it as a **solo setup**: sign-in, the layer
manifest and organization config are optional, the assessment reports layers as
`not-configured`, and no signed layer pins are needed. The project is still
fully wired, including the hook shim, the supported hook registrations and
`copilot.lock.json`. A solo person gets personal and local content only; signed
layer resolution starts when an organization is configured. If a layer manifest
or organization config exists, the full organization checks apply unchanged, so
a broken or signed-out organization setup still blocks.

The project must sit inside an approved project folder (`projects.roots`). If
the request step says the project is not inside one, ask the person to confirm
the folder, then run `cc config add projects.roots "<absolute folder>"`
(prefer the project folder itself or its parent, never `$HOME`) and retry.

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
trap 'rm -f "$REQUEST_FILE"' EXIT
chmod 600 "$REQUEST_FILE"
"$CC_BIN" reconcile request --project "$PROJECT_ROOT" --output "$REQUEST_FILE"
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
trap 'rm -f "$REQUEST_FILE"' EXIT
chmod 600 "$REQUEST_FILE"
"$CC_BIN" reconcile request --project "$PROJECT_ROOT" --output "$REQUEST_FILE"
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
