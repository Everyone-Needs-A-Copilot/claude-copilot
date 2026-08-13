# Update Claude Copilot

Update Claude Copilot to the latest version. This pulls the latest code and reinstalls the CLIs.

## Step 1: Check Current Version

```bash
cd ~/.claude/copilot

OLD_VERSION=$(cat VERSION.json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','unknown'))" 2>/dev/null || echo "unknown")

echo "Current version: $OLD_VERSION"
git log --oneline -1
```

Store the OLD_VERSION for comparison.

---

## Step 2: Pull Latest Updates

Tell user: "Pulling latest Claude Copilot updates..."

```bash
cd ~/.claude/copilot && git pull origin main
```

**If pull fails:**

Tell user:

---

**Pull failed**

There may be local changes or network issues. Try:

```bash
cd ~/.claude/copilot
git status
git stash  # if you have local changes
git pull origin main
git stash pop  # restore local changes
```

---

Then STOP.

---

## Step 3: Check New Version

```bash
cd ~/.claude/copilot

NEW_VERSION=$(cat VERSION.json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','unknown'))" 2>/dev/null || echo "unknown")

echo "New version: $NEW_VERSION"
git log --oneline -1
```

Compare with OLD_VERSION. If same, tell user "Source is already up to date" and
continue to Step 4: the content-addressed installer is idempotent and also
repairs a stale shim or machine-command deployment.

---

## Step 4: Install the Exact Immutable Runtime

Tell user: "Installing the exact framework snapshot, cc CLI, and global commands..."

```bash
COPILOT_SOURCE_ROOT="$(git -C "$HOME/.claude/copilot" rev-parse --show-toplevel)"
COPILOT_SOURCE_COMMIT="$(git -C "$COPILOT_SOURCE_ROOT" rev-parse HEAD)"
COPILOT_SOURCE_TREE="$(git -C "$COPILOT_SOURCE_ROOT" rev-parse "$COPILOT_SOURCE_COMMIT^{tree}")"
python3 "$COPILOT_SOURCE_ROOT/scripts/install-framework-snapshot.py" \
  --source-root "$COPILOT_SOURCE_ROOT" \
  --source-commit "$COPILOT_SOURCE_COMMIT" \
  --source-tree "$COPILOT_SOURCE_TREE"
export PATH="$HOME/.local/bin:$PATH"
```

**Verify:**
```bash
python3 -m json.tool "$HOME/.copilot/framework-runtime.json" >/dev/null
cc --version
cc config doctor
```

---

## Step 5: Reinstall tc CLI

Tell user: "Reinstalling tc CLI (Task Copilot)..."

```bash
pip install -e ~/.claude/copilot/tools/tc
```

**Verify:**
```bash
tc version
```

---

## Step 6: Create Required Directories (if needed)

```bash
mkdir -p ~/.claude/tasks
mkdir -p ~/.claude/memory
```

---

## Step 7: Verify Global Commands

The immutable runtime installer already deployed every command in
`VERSION.json`'s `machineCommands` roster from the same source snapshot.

```bash
python3 - <<'PY'
import json
from pathlib import Path

active = json.loads((Path.home() / ".copilot/framework-runtime.json").read_text())
missing = [
    item["name"]
    for item in active["machine_commands"]
    if not (Path.home() / ".claude/commands" / item["name"]).is_file()
]
if missing:
    raise SystemExit("Missing global commands: " + ", ".join(missing))
print(f"Verified {len(active['machine_commands'])} global commands")
PY
```

---

## Step 8: Run Version Check

Tell user: "Verifying all components..."

```bash
cd ~/.claude/copilot && ./scripts/check-versions.sh 2>/dev/null || echo "check-versions.sh not found, skipping"
```

**If errors:** Address them before continuing.

---

## Step 9: Report Success

```bash
cd ~/.claude/copilot

SUMMARY=$(git log --oneline HEAD~3..HEAD 2>/dev/null | head -3 | sed 's/^[a-f0-9]* /- /' || echo "Recent updates applied")
```

Tell user:

---

**Claude Copilot Updated!**

**Version:** $OLD_VERSION → $NEW_VERSION

**What's New:**
$SUMMARY

**What was updated:**
- cc CLI reinstalled (memory + skills)
- tc CLI reinstalled
- Global commands refreshed

**Next steps:**

To update your projects with the latest agents and commands:
```
cd your-project
/update-project
```

**Full details:** `~/.claude/copilot/CHANGELOG.md`

---

## Troubleshooting

### cc install fails

```bash
# Ensure Python 3 is available
python3 --version

# Retry the exact checked-out commit; do not point the shim at mutable source
COPILOT_SOURCE_ROOT="$(git -C "$HOME/.claude/copilot" rev-parse --show-toplevel)"
COPILOT_SOURCE_COMMIT="$(git -C "$COPILOT_SOURCE_ROOT" rev-parse HEAD)"
python3 "$COPILOT_SOURCE_ROOT/scripts/install-framework-snapshot.py" \
  --source-root "$COPILOT_SOURCE_ROOT" \
  --source-commit "$COPILOT_SOURCE_COMMIT" \
  --source-tree "$(git -C "$COPILOT_SOURCE_ROOT" rev-parse "$COPILOT_SOURCE_COMMIT^{tree}")"
```

### Permission Errors

```bash
chmod -R 755 ~/.claude/copilot
```

### Want to Rollback

```bash
cd ~/.claude/copilot
git log --oneline -10  # find the commit to rollback to
git checkout <commit-hash>
```

Then run `/update-copilot` again to reinstall.
