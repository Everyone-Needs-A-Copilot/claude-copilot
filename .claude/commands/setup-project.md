# Setup Project

Install the complete Claude + Codex reference through the canonical cc transaction. Never manually copy framework files. The transaction installs executable .claude/hooks/copilot-hook.sh, registers supported hook events and records the shim in copilot.lock.json. Verification rejects a missing, non-executable, unregistered or unlocked shim.

The former partial `minimal` / `quick start` profile is retired. If requested, explain complete setup preserves memory and project-authored files and ask whether to continue; a decline stops without mutation. Repair existing minimal installs through this transaction.

## Solo and organization setups

Without configured or inherited organization settings, solo setup needs no sign-in, layer manifest or signed pins. Layers report `not-configured`; personal/local content and full hook wiring still install. When an organization is configured, all organization checks apply: broken or signed-out configurations block.

Projects must be inside `projects.roots`. If outside, ask the person to confirm a folder, run `cc config add projects.roots "<absolute folder>"` and retry. Prefer the project or parent folder, never `$HOME`.

## 0. Verify the local CLI prerequisites

Both Copilot CLIs must be ready. The cc-owned prerequisite fact rejects macOS' unrelated C compiler and names machine setup as recovery. Never plan or mutate on failed prerequisites.

## 1. Build and inspect the exact plan

Run from the project root. Planning is read-only; shell exit removes the temporary request.

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

Explain every held, owner-decision or could-not-verify state. Never apply a blocked plan or suggest overwriting, resetting, stashing or deleting the person's work. Confirm the exact plan; a decline stops without mutation.

## 2. Apply the confirmed plan

Recreate the same request with the exact returned `plan_id`. Replace `<PLAN_ID>` only with that opaque value; never infer or reuse an old ID.

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

Report success only after apply returns `applied` or an already-ready receipt and independent verification returns `ready`. The transaction owns preflight, identity binding, materialization, locks, receipts, postconditions, snapshots and rollback. Repair only verified framework-owned targets. Dirty, ambiguous, unsupported customizations or unverifiable states stay held for the named actor; never bypass with manual operations or legacy installers.

## 3. Capture the project identity

Only run after a new setup returned `applied` and verification reported `ready`. For updates, already-ready no-ops, held, declined or failed runs, skip this step entirely. Also skip when the project already has a project-authored description in CLAUDE.md or AGENTS.md; existing authored text is authoritative.

Otherwise use AskUserQuestion with free text and a skip option for each question:

1. "What's this project about?" — one or two sentences.
2. "What's the main tech stack?" — suggest detected repository choices and allow a typed answer.
3. "Anything else a new teammate or agent should know?" — optional conventions, run/test commands or constraints.

Write only supplied answers under `## Project` in both CLAUDE.md and AGENTS.md, with the folder name and Description, Stack and Notes fields. Omit skipped fields; all skipped means no writes. Insert above the framework block, after any title, and never edit between the framework's `cc:project-integration` markers. Preserve existing content; never use overwrite-project-instructions or duplicate machine-level settings.

Run `reconcile verify` again. If not ready, undo only the section just added and report the failure.
