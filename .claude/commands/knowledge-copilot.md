# Knowledge Copilot

Build a shared knowledge repository for your company or team. This knowledge becomes available across all your projects automatically.

## What This Does

Knowledge Copilot guides you through:
1. **Discovery** - Structured questions about your company, voice, products, and standards
2. **Documentation** - Creates organized markdown files as you answer
3. **Git Setup** - Initializes a repo you can push to GitHub
4. **Connection** - Links to `~/.claude/knowledge` for automatic access

## Why GitHub?

Your knowledge repository should be:
- **Version controlled** - Track changes over time
- **Shareable** - Team members can clone and contribute
- **Backed up** - Safe in the cloud
- **Collaborative** - PRs for knowledge updates

We'll help you set up a Git repo that can be pushed to GitHub (private repos are free).

---

## Detect Mode

First, check current state:

```bash
# Check for existing symlink
ls -la ~/.claude/knowledge 2>/dev/null

# Check for global knowledge manifest
cat ~/.claude/knowledge/knowledge-manifest.json 2>/dev/null

# Check for initiative in progress
```

Also call `initiative_get` to check for in-progress discovery.

### Team Context Detection

Before showing options, check if this appears to be a team member joining:

```bash
# Check if current project expects knowledge but none is configured
grep -q "knowledge_search\|knowledge_get" CLAUDE.md 2>/dev/null && echo "PROJECT_EXPECTS_KNOWLEDGE" || echo "NO_EXPECTATION"

# Check for team repo URL in project's .mcp.json or CLAUDE.md
grep -o 'git@github.com:[^"]*\.git' CLAUDE.md .mcp.json 2>/dev/null | head -1
```

**Decision Matrix:**

| Global Knowledge | Project Expects | Action |
|------------------|-----------------|--------|
| Yes | Any | Standard mode selection |
| No | Yes | Show "Join Team" prompt first |
| No | No | Standard mode selection |

**Based on results:**
- If symlink exists and points to valid repo → Offer to extend or verify
- If initiative exists for knowledge discovery → Resume
- If NO global but project expects → Show Team Knowledge Detected prompt
- Otherwise → Start fresh or link existing

---

## Team Knowledge Detected (Pre-Selection)

**If NO global knowledge but PROJECT_EXPECTS_KNOWLEDGE:**

Show this prompt BEFORE mode selection:

---

**Team Knowledge Detected**

This project references team knowledge (`knowledge_search`, `knowledge_get`), but no knowledge repository is configured on this machine.

{{IF TEAM_REPO_URL}}
**Team repository URL detected:** `{{TEAM_REPO_URL}}`
{{END IF}}

---

Use AskUserQuestion:

**Question:** "Would you like to set up team knowledge?"
**Header:** "Team"
**Options:**
1. **"Yes, set up team knowledge (Recommended)"** - Connect to your team's repository
2. **"No, I'll create my own"** - Start fresh with new knowledge

**If user selects "Yes":** Jump to **Mode: Join Team Knowledge** below.
**If user selects "No":** Continue to standard Mode Selection.

---

## Mode Selection

Use AskUserQuestion:

**Question:** "What would you like to do?"
**Header:** "Mode"
**Options:**
1. **"Create new knowledge repository"** - Start fresh with guided discovery
2. **"Link existing repository"** - Connect to a repo you or your team already created
3. **"Join team knowledge"** - Clone and link your team's knowledge repository
4. **"Check status"** - Verify your current knowledge setup
5. **"Continue discovery"** - Resume where you left off (if applicable)

---

## Mode: Create New Repository

### Step 1: Choose Location

Use AskUserQuestion:

**Question:** "Where should I create your knowledge repository?"
**Header:** "Location"
**Options:**
1. **"~/[company]-knowledge (Recommended)"** - Standard location, easy to find
2. **"Custom location"** - You specify the path

If custom, ask for the path.

**Also ask:**

**Question:** "What's your company or team name?"
**Header:** "Name"
**Options:** Let user type (will be used for folder name and manifest)

### Step 2: Create Structure

```bash
# Create directory (replace [company] with actual name, lowercase, hyphens)
mkdir -p ~/[company]-knowledge

cd ~/[company]-knowledge

# Create directory structure
mkdir -p 01-company
mkdir -p 02-voice
mkdir -p 03-products
mkdir -p 04-standards
mkdir -p .claude/extensions
```

### Step 3: Create Manifest

Create `knowledge-manifest.json`:

```json
{
  "version": "1.0",
  "name": "[company]",
  "description": "Knowledge repository for [Company Name]"
}
```

**Note:** After pushing to GitHub, update the manifest to include the repository URL:

```json
{
  "version": "1.0",
  "name": "[company]",
  "description": "Knowledge repository for [Company Name]",
  "repository": {
    "url": "git@github.com:[org]/[company]-knowledge.git",
    "type": "git"
  }
}
```

This helps team members auto-detect the repository when running `/knowledge-copilot`.

### Step 4: Create README

Create `README.md`:

```markdown
# [Company Name] Knowledge Repository

This repository contains shared knowledge for [Company Name], accessible across all projects via Claude Copilot.

## Structure

| Directory | Purpose |
|-----------|---------|
| `01-company/` | Company identity, values, mission |
| `02-voice/` | Communication style, terminology |
| `03-products/` | Product/service documentation |
| `04-standards/` | Development, design, operations standards |
| `.claude/extensions/` | Custom agent behaviors |

## Setup for Team Members

1. Clone this repo:
   ```bash
   git clone [repo-url] ~/[company]-knowledge
   ```

2. Create symlink:
   ```bash
   ln -sf ~/[company]-knowledge ~/.claude/knowledge
   ```

3. Verify:
   ```bash
   ls ~/.claude/knowledge/knowledge-manifest.json
   ```

## Usage

Once linked, use in any Claude Copilot project:
- `knowledge_search("company")` - Search company info
- `knowledge_search("voice")` - Search voice guidelines
- `knowledge_search("standards")` - Search standards

---

Built with [Claude Copilot](https://github.com/Everyone-Needs-A-Copilot/claude-copilot)
```

### Step 5: Create .gitignore

```
.DS_Store
*.swp
*.swo
*~
```

### Step 6: Initialize Git

```bash
cd ~/[company]-knowledge
git init
git add .
git commit -m "Initialize knowledge repository"
```

### Step 7: Create Symlink

```bash
# Remove existing symlink if present
rm -f ~/.claude/knowledge

# Create new symlink
ln -sf ~/[company]-knowledge ~/.claude/knowledge
```

**Verify:**
```bash
ls ~/.claude/knowledge/knowledge-manifest.json
```

### Step 8: Start Initiative

```
initiative_start({
  name: "[Company] Knowledge Discovery",
  goal: "Build comprehensive knowledge repository through guided discovery",
  status: "IN PROGRESS"
})
```

### Step 9: Begin Discovery

Now invoke the Knowledge Copilot agent behavior:

---

**Knowledge Repository Created!**

I've set up your knowledge repository at `~/[company]-knowledge` and linked it to `~/.claude/knowledge`.

**Ready for discovery.** I'll guide you through defining:
1. **Company Identity** - Who you are, values, mission
2. **Voice** - How you communicate
3. **Products/Services** - What you offer
4. **Standards** - How you work

We can do this in one session or across multiple. Each session, we'll save progress so you can resume anytime.

**Let's start with your company's foundation.**

Why does [Company] exist? What problem were you trying to solve when you started?

---

Continue with Phase 1 questions from the Knowledge Copilot agent profile.

---

## Mode: Link Existing Repository

### Step 1: Get Repository Location

Use AskUserQuestion:

**Question:** "Where is your knowledge repository?"
**Header:** "Source"
**Options:**
1. **"GitHub URL"** - Clone from GitHub
2. **"Local path"** - Already on this machine

### Step 2a: Clone from GitHub

If GitHub:

**Ask:** "What's the GitHub repository URL?"

```bash
# Clone the repo
git clone [url] ~/[company]-knowledge
```

### Step 2b: Use Local Path

If local:

**Ask:** "What's the full path to your knowledge repository?"

Verify it exists and has a manifest:
```bash
ls [path]/knowledge-manifest.json
```

### Step 3: Create Symlink

```bash
# Get company name from manifest
cat [path]/knowledge-manifest.json | grep '"name"'

# Remove existing symlink
rm -f ~/.claude/knowledge

# Create symlink
ln -sf [path] ~/.claude/knowledge
```

### Step 4: Verify

```bash
ls ~/.claude/knowledge/knowledge-manifest.json
```

### Step 5: Report Success

---

**Knowledge Repository Linked!**

Connected `~/.claude/knowledge` → `[path]`

This knowledge is now available in all your Claude Copilot projects.

**Test it:**
```
knowledge_search("company")
```

**To update knowledge:**
- Edit files in `[path]`
- Commit and push changes
- Team members: `git pull` to get updates

---

---

## Mode: Join Team Knowledge

Use this mode when joining an existing team that has a knowledge repository.

### Step 1: Get Repository URL

**If TEAM_REPO_URL was detected:** Use it as default.

Otherwise, use AskUserQuestion:

**Question:** "What's your team's knowledge repository URL?"
**Header:** "Repo URL"
**Options:** Let user type (e.g., `git@github.com:acme-corp/acme-knowledge.git`)

Store as `TEAM_REPO_URL`.

### Step 2: Determine Clone Location

Extract company name from URL:

```bash
# Extract repo name from URL (e.g., "acme-knowledge" from "git@github.com:acme-corp/acme-knowledge.git")
echo "{{TEAM_REPO_URL}}" | sed 's/.*[:/]\([^/]*\)\.git$/\1/'
```

Store as `REPO_NAME`.

Clone location: `~/${REPO_NAME}`

### Step 3: Clone Repository

```bash
# Clone the team's knowledge repository
git clone {{TEAM_REPO_URL}} ~/${REPO_NAME}
```

**Verify manifest exists:**

```bash
ls ~/${REPO_NAME}/knowledge-manifest.json && echo "MANIFEST_OK" || echo "MANIFEST_MISSING"
```

**If MANIFEST_MISSING:**

---

**Warning:** The cloned repository doesn't have a `knowledge-manifest.json`.

This may not be a valid Claude Copilot knowledge repository. Please verify the URL with your team.

---

Then STOP.

### Step 4: Create Symlink

```bash
# Remove existing symlink if present
rm -f ~/.claude/knowledge

# Create symlink to cloned repo
ln -sf ~/${REPO_NAME} ~/.claude/knowledge
```

### Step 5: Verify Setup

```bash
# Verify symlink works
ls ~/.claude/knowledge/knowledge-manifest.json

# Get knowledge name
cat ~/.claude/knowledge/knowledge-manifest.json | grep '"name"'

# Count knowledge files
find ~/.claude/knowledge -name "*.md" -type f 2>/dev/null | wc -l
```

### Step 6: Report Success

---

**Team Knowledge Connected!**

Successfully set up team knowledge:
- Repository: `{{TEAM_REPO_URL}}`
- Local path: `~/${REPO_NAME}`
- Linked at: `~/.claude/knowledge`
- Knowledge name: `{{KNOWLEDGE_NAME}}`

This knowledge is now available in all your Claude Copilot projects.

**Test it:**
```
knowledge_search("company")
```

**To get updates from your team:**
```bash
cd ~/${REPO_NAME}
git pull
```

**To contribute:**
- Edit files in `~/${REPO_NAME}`
- Commit and push changes (follow your team's PR process)

---

---

## Mode: Check Status

```bash
# Check symlink
ls -la ~/.claude/knowledge

# Check manifest
cat ~/.claude/knowledge/knowledge-manifest.json 2>/dev/null

# List directories
ls ~/.claude/knowledge/ 2>/dev/null

# Count files
find ~/.claude/knowledge -name "*.md" -type f 2>/dev/null | wc -l
```

Report:
- Whether knowledge is configured
- Repository name and location
- Number of knowledge files
- Directory structure

---

## Mode: Continue Discovery

1. Call `initiative_get` to load current state
2. Review what's been completed
3. Identify next phase
4. Resume questioning from Knowledge Copilot agent profile

---

## GitHub Setup Guide

When user is ready to push to GitHub:

### Step 1: Create GitHub Repository

---

**Let's push your knowledge to GitHub.**

1. Go to [github.com/new](https://github.com/new)
2. Name it: `[company]-knowledge`
3. Set to **Private** (recommended for company knowledge)
4. **Don't** initialize with README (we have content)
5. Click "Create repository"

What's your GitHub username or organization name?

---

### Step 2: Add Remote and Push

```bash
cd ~/[company]-knowledge
git remote add origin git@github.com:[username]/[company]-knowledge.git
git branch -M main
git push -u origin main
```

### Step 3: Update Manifest with Repository URL

Now that the repo is on GitHub, update the manifest to help team members auto-detect it:

```bash
cd ~/[company]-knowledge
```

Edit `knowledge-manifest.json` to add the repository field:

```json
{
  "version": "1.0",
  "name": "[company]",
  "description": "Knowledge repository for [Company Name]",
  "repository": {
    "url": "git@github.com:[username]/[company]-knowledge.git",
    "type": "git"
  }
}
```

Then commit and push:

```bash
git add knowledge-manifest.json
git commit -m "Add repository URL to manifest"
git push
```

### Step 4: Confirm

---

**Your knowledge is now on GitHub!**

Repository: `github.com/[username]/[company]-knowledge`

**Team members can now:**
1. Run `/knowledge-copilot` - It will auto-detect and offer to set up team knowledge
2. Or manually: Clone and link:
   ```bash
   git clone git@github.com:[username]/[company]-knowledge.git ~/[company]-knowledge
   ln -sf ~/[company]-knowledge ~/.claude/knowledge
   ```

**To update:**
- Make changes locally
- `git add . && git commit -m "Update"`
- `git push`

---

---

## Tips

- One topic per session is fine - discovery takes time
- Your words become the documentation - speak naturally
- Generic answers get challenged - be specific
- Progress is saved - resume anytime with `/knowledge-copilot`
- Commit often - version control is your friend

---

## Quick Reference

| Command | Purpose |
|---------|---------|
| `/knowledge-copilot` | Start or continue knowledge discovery |
| `/knowledge-copilot link` | Link to existing repository |
| `/knowledge-copilot status` | Check current knowledge setup |
| `knowledge_search(query)` | Search your knowledge |
| `knowledge_get(path)` | Get specific knowledge file |
