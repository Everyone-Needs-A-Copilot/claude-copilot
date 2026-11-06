# Update Project

Releases reach every project through the machine's release pointer; a project is never updated file by file. This command is therefore verify-only on a migrated project.

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
"$CC_BIN" doctor
```

Init is idempotent: on a migrated project it reports `unchanged`. Report both results plainly. A project that still carries legacy framework copies or `copilot.lock.json` is handled by `cc project migrate`, not by this command; name it and stop. Never overwrite, reset, stash or delete the person's work.
