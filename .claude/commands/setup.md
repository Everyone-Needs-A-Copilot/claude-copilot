# Claude Copilot Machine Setup

You are a friendly setup assistant. This command sets up Claude Copilot on the user's machine. It should only be run from the Claude Copilot repository (`~/.claude/copilot`).

## Step 1: Verify Running From Correct Location

```bash
pwd
```

**If NOT in `~/.claude/copilot` or similar:**

Tell user:

---

**This command is for machine setup only.**

It should be run from the Claude Copilot repository at `~/.claude/copilot`.

**For project operations, use:**
- `/setup-project` - Initialize a new project
- `/update-project` - Update an existing project

---

Then STOP.

---

## Step 2: Welcome Message

---

**Welcome to Claude Copilot Machine Setup!**

I'll set up Claude Copilot on your machine. This includes:
- Installing the `tc` CLI (manages PRDs, tasks, and work products)
- Installing the `cc` CLI (unified memory and skills manager)
- Installing global commands (`/setup-project`, `/update-project`, `/knowledge-copilot`)

Let me check what's already in place...

---

## Step 3: Check Prerequisites

```bash
# Check Python 3
python3 --version

# Get home directory
echo $HOME
```

**If Python 3 missing:**
Tell user: "Please install Python 3.9+ and run this setup again."
Then STOP.

---

## Step 4: Install tc CLI

Tell user: "Installing tc CLI (Task Copilot)..."

```bash
pip install -e ~/.claude/copilot/tools/tc
```

**Verify:**
```bash
tc version
```

---

## Step 5: Create Data Directories

```bash
mkdir -p ~/.claude/tasks
```

---

## Step 6: Install the Immutable Framework Runtime

Install `cc` and every global command declared by the exact source commit's
`VERSION.json`. The installer archives the full commit, verifies its Git tree,
and activates the cc shim and command set only after checksum verification.

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

Tell user: "Installing the reviewed framework snapshot and global commands..."

**Verify:**
```bash
python3 -m json.tool "$HOME/.copilot/framework-runtime.json" >/dev/null
cc --version
```

---

## Step 7: Initialize cc

### Step 7A: Initialize Machine Config

```bash
cc config init --machine
```

Create required directories:

```bash
mkdir -p ~/.claude/cache/models ~/.claude/skills
printf 'config.json\n' > ~/.claude/cc/.gitignore
```

### Step 7C: Configure Machine-Level Paths

Use AskUserQuestion to gather optional paths:

**Question 1:** "Path to your knowledge-copilot repository (optional, press Enter to skip)"
- Header: "Knowledge Copilot Path"
- Let user type freely or press Enter

**Question 2:** "Path to your knowledge repository (optional, press Enter to skip)"
- Header: "Knowledge Repo Path"
- Let user type freely or press Enter

For each non-empty path provided, run:
```bash
cc config set shared_docs <path>   # if provided
cc config set knowledge_repo <path>  # if provided
```

Then verify:
```bash
cc config doctor
```

### Step 7D: Configure the Output Contract

Tell user:

---

**Output style.** Every agent and `/protocol` now follows a canonical Output Contract: lead with the answer, bullets over paragraphs, plain language, no preamble or closing filler — full depth only when you ask for it. Findings, risks, and caveats are never cut to hit this shape; only the wording is. You can adjust it now or anytime with `cc config set output.verbosity <level> --project`.

---

Use AskUserQuestion:

**Question 1:** "How verbose should responses be by default?"
- Header: "Verbosity"
- Options:
  1. **"Concise (recommended)"** — BLUF + bullets, depth only on request
  2. **"Standard"** — concise plus brief rationale
  3. **"Detailed"** — full reasoning by default, still no preamble/closer

**Question 2:** "Default vocabulary register?"
- Header: "Audience"
- Options:
  1. **"Plain (recommended)"** — define technical terms inline, cut jargon that isn't load-bearing
  2. **"Technical"** — keep full technical vocabulary by default

Map answers to `concise|standard|detailed` and `plain|technical`, then run:
```bash
cc config set output.verbosity <answer1>
cc config set output.audience <answer2>
```

Tell user: "Set machine-wide. Override per project anytime with `cc config set output.verbosity <level> --project` (or `output.audience`)."

---

## Step 8: Check for Configured Knowledge

`~/.claude/knowledge/knowledge-manifest.json` is not the machine's real configured knowledge source (`extensions_resolver.py`'s own docs call it out explicitly as not among `CC_KNOWLEDGE_REPOS`) -- check the real `paths.knowledge_repo` config instead:

```bash
eval "$(cc env)"
if [[ -n "${CC_KNOWLEDGE_REPOS:-}" ]]; then
  echo "KNOWLEDGE_EXISTS"
  echo "$CC_KNOWLEDGE_REPOS"
else
  echo "NO_KNOWLEDGE"
fi
```

Store result (and the ladder itself, if present) for reporting.

---

## Step 9: Report Success

---

**Machine Setup Complete!**

Claude Copilot's authoring checkout is at `~/.claude/copilot`; the active
runtime is the exact immutable snapshot recorded in
`~/.copilot/framework-runtime.json`.

**What's ready:**
- tc CLI - Manages PRDs, tasks, and work products
- cc CLI - Unified memory and skills manager (replaces MCP servers)
- 16 Specialist Agents - Expert guidance for any task
- Output Contract - verbosity `{{OUTPUT_VERBOSITY}}`, audience `{{OUTPUT_AUDIENCE}}` (change: `cc config set output.verbosity <level>`)

**Global commands installed:**
| Command | Purpose |
|---------|---------|
| `/setup-copilot` | Universal setup (auto-detects context) |
| `/setup-project` | Initialize a new project |
| `/update-project` | Update an existing project |
| `/update-copilot` | Update Claude Copilot itself |
| `/knowledge-copilot` | Set up shared knowledge |

{{IF NO_KNOWLEDGE}}
**Optional: Set up shared knowledge**

You can create a knowledge repository for company/product information that's available across all projects.

Run `/knowledge-copilot` to set this up.
{{END IF}}

{{IF KNOWLEDGE_EXISTS}}
**Shared Knowledge Detected**

Found configured knowledge repositories: `{{CC_KNOWLEDGE_REPOS}}`
This ladder will be available in all your projects automatically (nearest tier first).
{{END IF}}

**Next: Set up a project**

Open Claude Code in any project directory and run:
```
/setup-project
```

---

## Troubleshooting

### cc Install Fails

```bash
# Retry the exact current checkout commit
COPILOT_SOURCE_ROOT="$(git -C "$HOME/.claude/copilot" rev-parse --show-toplevel)"
COPILOT_SOURCE_COMMIT="$(git -C "$COPILOT_SOURCE_ROOT" rev-parse HEAD)"
python3 "$COPILOT_SOURCE_ROOT/scripts/install-framework-snapshot.py" \
  --source-root "$COPILOT_SOURCE_ROOT" \
  --source-commit "$COPILOT_SOURCE_COMMIT" \
  --source-tree "$(git -C "$COPILOT_SOURCE_ROOT" rev-parse "$COPILOT_SOURCE_COMMIT^{tree}")"

# Verify PATH includes ~/.local/bin
echo $PATH
# Add if missing: export PATH="$HOME/.local/bin:$PATH"
```

### tc Install Fails

```bash
pip3 install -e ~/.claude/copilot/tools/tc
tc version
```

### Permission Errors

```bash
chmod -R 755 ~/.claude/copilot
```

---

## Remember

- Be patient and encouraging
- Run commands yourself instead of asking user to copy/paste
- Celebrate completion!
