# Update Claude Copilot

Update Claude Copilot to the latest version. This pulls the latest code and reinstalls the CLIs.

## Step 1: Check Current Version

```bash
cd ~/.claude/copilot

OLD_VERSION=$(cat VERSION.json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('framework','unknown'))" 2>/dev/null || echo "unknown")

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

NEW_VERSION=$(cat VERSION.json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('framework','unknown'))" 2>/dev/null || echo "unknown")

echo "New version: $NEW_VERSION"
git log --oneline -1
git fetch --quiet --tags origin 2>/dev/null || true
if ! git rev-parse -q --verify "refs/tags/v${NEW_VERSION}" >/dev/null; then
  echo "WARNING: v${NEW_VERSION} is untagged; updated projects fail FF12 until scripts/tag-release.sh runs."
fi
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

## Step 7: Verify Global Commands and Skills

The runtime installer already deployed all `machineCommands` and
`machineSkills` (`~/.claude/skills/<name>/`) from one snapshot.

```bash
python3 - <<'PY'
import hashlib, json
from pathlib import Path

h = Path.home()
active = json.loads((h / ".copilot/framework-runtime.json").read_text())
bad = [i["name"] for i in active["machine_commands"]
       if not (h / ".claude/commands" / i["name"]).is_file()]
for s in active.get("machine_skills", []):
    for rel, digest in s["files"].items():
        f = h / ".claude/skills" / s["name"] / rel
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != digest:
            bad.append(f"{s['name']}/{rel}")
if bad:
    raise SystemExit("Missing/changed: " + ", ".join(bad))
print("Verified")
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
# Ensure Python 3.10 or newer is available (cc and tc require it)
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
