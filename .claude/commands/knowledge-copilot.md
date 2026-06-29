# Knowledge Copilot — Bootstrapper

Locates the Knowledge Copilot repository on this machine, then hands off to the methodology inside it. This command is a thin bootstrapper; the substantive KMS-building methodology lives in the repo at `docs/00-knowledge-copilot/01-build-a-kms.md`.

---

## Step 1 — Hydrate env vars

```bash
eval "$(cc env)"
```

This populates `CC_KNOWLEDGE_REPO` (and `CC_SHARED_DOCS`) if the machine config has a path set.

---

## Step 2 — Locate the Knowledge Copilot repo

Resolve `REPO_PATH` by checking these sources in order; stop at the first hit:

```bash
# 1. Canonical env var (set via cc env)
echo "${CC_KNOWLEDGE_REPO:-}"

# 2. Ecosystem root — post-rename canonical dir
ls -d /Volumes/Dev/Sites/COPILOT/knowledge-copilot 2>/dev/null && echo "FOUND_CANONICAL"

# 3. Ecosystem root — current/transition dir name
ls -d /Volumes/Dev/Sites/COPILOT/knowledge-copilot 2>/dev/null && echo "FOUND_SHARED_DOCS"

# 4. Generic install location (symlink at ~/.claude/knowledge)
readlink -f ~/.claude/knowledge 2>/dev/null
```

Set `REPO_PATH` to the first resolved path. If none resolve, proceed to Step 3.

---

## Step 3 — If repo not found: guide the user

The canonical GitHub repo during transition:
- **Current name:** `https://github.com/Everyone-Needs-A-Copilot/knowledge-copilot`
- **Future canonical:** `https://github.com/Everyone-Needs-A-Copilot/knowledge-copilot`

Ask the user (use AskUserQuestion):

**Question:** "No Knowledge Copilot repo found on this machine. What would you like to do?"
**Header:** "Setup"
**Options:**
1. **"Clone the canonical repo"** — `git clone git@github.com:Everyone-Needs-A-Copilot/knowledge-copilot.git /Volumes/Dev/Sites/COPILOT/knowledge-copilot`
2. **"Create a new knowledge repo"** — start fresh with guided discovery
3. **"Link an existing local repo"** — provide a path

After cloning or creating, set `REPO_PATH` and register it:

```bash
cc config set paths.knowledge_repo "$REPO_PATH"
cc config set paths.shared_docs "$REPO_PATH"
```

Then continue to Step 4.

---

## Step 4 — Hand off to in-repo methodology

With `REPO_PATH` resolved, read the methodology document:

```bash
cat "${REPO_PATH}/docs/00-knowledge-copilot/01-build-a-kms.md"
```

If that file does not exist (older repo without the `docs/00-knowledge-copilot/` structure), fall back to the `@agent-kc` discovery flow directly.

Otherwise, follow the methodology in that file step-by-step, delegating all substantive discovery work to `@agent-kc` with `REPO_PATH` set in context.

---

## Quick Reference

| Invocation | Result |
|-----------|--------|
| `/knowledge-copilot` | Locate repo → hand off to methodology |
| `/knowledge-copilot status` | Run Step 2 only and report what was found |
| `@agent-kc` directly | Discovery agent (requires `REPO_PATH` in context) |
