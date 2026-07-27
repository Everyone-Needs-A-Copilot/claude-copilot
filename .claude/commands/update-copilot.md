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

Compare with OLD_VERSION. If same, tell user "Already up to date" and skip to Step 6.

---

## Step 4: Reinstall cc CLI

Tell user: "Reinstalling cc CLI (Memory + Skills)..."

```bash
bash ~/.claude/copilot/tools/cc/install.sh
```

**Verify:**
```bash
cc version
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

## Step 7: Update Global Commands

Tell user: "Updating global commands..."

```bash
cp ~/.claude/copilot/.claude/commands/setup-project.md ~/.claude/commands/
cp ~/.claude/copilot/.claude/commands/update-project.md ~/.claude/commands/
cp ~/.claude/copilot/.claude/commands/update-copilot.md ~/.claude/commands/
cp ~/.claude/copilot/.claude/commands/knowledge-copilot.md ~/.claude/commands/
```

**Verify:**
```bash
ls -la ~/.claude/commands/
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

# Try manual install
cd ~/.claude/copilot/tools/cc
pip install -e .
ln -sf $(pwd)/.venv/bin/cc ~/.local/bin/cc
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
