# Setup Project

Initialise the current project for Claude and Codex Copilot with one command. Never copy framework files into the project: agents, commands, skills and hooks resolve from this machine's installed release (`~/.copilot/current`), so a project carries only its own state.

```bash
set -eu
CC_BIN=""
for CANDIDATE in "$(command -v cc 2>/dev/null || true)" "$HOME/.local/bin/cc"; do
  if [ -n "$CANDIDATE" ] && [ -x "$CANDIDATE" ] && "$CANDIDATE" --version 2>/dev/null | grep -q '^cc version'; then
    CC_BIN="$CANDIDATE"
    break
  fi
done
if [ -z "$CC_BIN" ]; then
  echo "Claude Copilot machine setup is required: the Copilot cc CLI must be available. Open ~/.claude/copilot, run /setup, open a fresh shell, then retry." >&2
  exit 3
fi
"$CC_BIN" project init "$(pwd)" --json
```

`cc project init` takes seconds and is idempotent. It writes `copilot.project.json` (always both runtimes), appends one delimited Copilot section to `CLAUDE.md` and `AGENTS.md` only when absent (existing project text is never rewritten), adds the Codex project trust entry to `~/.codex/config.toml` (backed up, atomic), and links any declared `activePacks`. There is no `projects.roots` requirement and Git is not required.

Report the JSON `result` (`changed` or `unchanged`) and `changed` list. On a nonzero exit, relay `error.message` and stop; do not work around it by editing files by hand.

## Project identity

Only after `result` is `changed` on a new project, and only when `CLAUDE.md` has no project-authored description above the Copilot section, use AskUserQuestion (free text with a skip option) to ask what the project is about, its main tech stack, and anything else a new teammate should know. Put the answers in `CLAUDE.md` outside the delimited section.

## Health

Run `cc doctor` and report its verdict. Retired: reconcile plans, `copilot.lock.json` and per-project framework copies.
