# Claude Copilot Quick Start (15 Minutes)

This guide gets you up and running with Memory Copilot only - the fastest path to persistent session memory.

## What You Get

With this minimal setup:

| Feature | Status |
|---------|--------|
| **Memory Copilot** | Enabled - Persist decisions, lessons, and context across sessions |
| **`/continue` command** | Enabled - Resume previous work with full context |
| **Session persistence** | Enabled - All progress automatically saved |
| **Agents** | Not installed - Use default Claude behavior |
| **Skills Copilot** | Not installed - No on-demand skill loading |
| **Extensions** | Not installed - No custom agent behaviors |
| **`/protocol` command** | Not installed - No Agent-First Protocol |

**This is perfect if:**
- You want to try Memory Copilot first
- You need session persistence but not agents
- You want the fastest possible setup
- You plan to upgrade to the full framework later

**You'll miss out on:**
- 14 lean agents with auto-skill loading (Tech Architect, QA, Security, etc.)
- Context-aware skill evaluation (skill_evaluate)
- Knowledge repository integration
- Agent-First Protocol workflow

---

## Setup (5 Steps)

### Step 1: Clone the Repository

```bash
mkdir -p ~/.claude && cd ~/.claude
git clone https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git copilot
```

### Step 2: Build Memory Copilot

```bash
cd ~/.claude/copilot/mcp-servers/copilot-memory
npm install
npm run build
```

**Verify:** Check that `dist/index.js` exists:
```bash
ls ~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js
```

### Step 3: Create Memory Directory

```bash
mkdir -p ~/.claude/memory
```

### Step 4: Configure Your Project

In your project directory, create `.mcp.json`:

```json
{
  "mcpServers": {
    "copilot-memory": {
      "command": "node",
      "args": ["/Users/YOUR_USERNAME/.claude/copilot/mcp-servers/copilot-memory/dist/index.js"],
      "env": {
        "MEMORY_PATH": "/Users/YOUR_USERNAME/.claude/memory",
        "WORKSPACE_ID": "my-project"
      }
    }
  }
}
```

**IMPORTANT:** Replace:
- `/Users/YOUR_USERNAME` with your actual home directory path
- `my-project` with your project name (used as the memory workspace identifier)

### Step 5: Create Continue Command

Create `.claude/commands/continue.md` in your project:

```bash
mkdir -p .claude/commands
```

Then download or copy the continue command from:
```bash
cp ~/.claude/copilot/.claude/commands/continue.md .claude/commands/
```

---

## Verification

### 1. Restart Claude Code

Close and reopen Claude Code in your project directory.

### 2. Check MCP Connection

Run `/mcp` in Claude Code. You should see:

```
Connected MCP Servers:
● copilot-memory
```

### 3. Test Memory Tools

Try these commands in Claude:

```
# Start a new initiative
initiative_start({
  title: "Test Memory Setup",
  description: "Verifying Memory Copilot works"
})

# Store a memory
memory_store({
  type: "decision",
  content: "Memory Copilot is working!",
  tags: ["setup", "test"]
})

# Search memories
memory_search({ query: "working" })

# Get current initiative
initiative_get()
```

If these work, you're all set!

### 4. Test /continue Command

Say: `/continue`

You should see Claude load your current initiative and offer to resume work.

---

## Daily Usage

### Starting Work

```
/continue
```

Claude will:
1. Load your current initiative
2. Show recent progress
3. Review key decisions
4. Present next steps
5. Ask what you want to work on

### During Work

Memory is automatically saved when you:
- Make decisions
- Complete tasks
- Learn lessons
- Touch important files

### Ending Work

Just close Claude Code. Your progress is automatically saved.

To explicitly update before ending:

```
initiative_update({
  completed: ["Task 1", "Task 2"],
  inProgress: "Currently working on X",
  resumeInstructions: "Next: Start with Y",
  lessons: ["Learned that Z works better"],
  decisions: ["Decided to use approach A"],
  keyFiles: ["src/main.ts", "src/utils.ts"]
})
```

---

## Troubleshooting

### "MCP server not found"

**Check paths in `.mcp.json`:**
- Paths must be absolute (no `~` or `$HOME`)
- Verify file exists: `ls /path/to/dist/index.js`
- Match your actual home directory path

### "Build failed"

**Install build tools:**

macOS:
```bash
xcode-select --install
```

Linux:
```bash
sudo apt-get install build-essential python3
```

Windows:
```bash
npm install --global windows-build-tools
```

Then rebuild:
```bash
cd ~/.claude/copilot/mcp-servers/copilot-memory
npm install
npm run build
```

### "Memory not persisting"

**Check memory directory:**
```bash
ls ~/.claude/memory/
```

Should show a subdirectory with your workspace ID.

**Check workspace ID:**
- Make sure `WORKSPACE_ID` in `.mcp.json` matches across sessions
- Don't change the workspace ID or you'll lose access to previous memories

### "Commands not working"

**Verify command file:**
```bash
cat .claude/commands/continue.md
```

Should show the continue command content.

**Restart Claude Code** to reload commands.

---

## Upgrade Path

When you're ready for the full framework:

### Option 1: Full Setup Command

```bash
cd ~/.claude/copilot
# Open in Claude Code
/setup-copilot
```

Then in your project:
```bash
/setup-copilot
```

This will add:
- All 14 lean agents
- Skills Copilot (with skill_evaluate)
- Task management via `tc` CLI
- `/protocol` command
- Full command set

### Option 2: Manual Addition

Keep your `.mcp.json` and add components one at a time:

**Add Skills Copilot:**
1. Build: `cd ~/.claude/copilot/mcp-servers/skills-copilot && npm install && npm run build`
2. Add to `.mcp.json` (see `templates/mcp.json`)

**Add Agents:**
```bash
cp ~/.claude/copilot/.claude/agents/*.md .claude/agents/
```

**Add Commands:**
```bash
cp ~/.claude/copilot/.claude/commands/protocol.md .claude/commands/
```

**Add Task Management:**
Install the `tc` CLI tool for PRD, task, and work product management.

---

## What's Next?

With Memory Copilot running, you can:

1. **Use `/continue` daily** - Start every session by resuming context
2. **Store decisions** - Call `memory_store` for important choices
3. **Search history** - Use `memory_search` to find past context
4. **Track initiatives** - Manage work with `initiative_*` tools
5. **Upgrade when ready** - Add agents and skills later

---

## Need Help?

- **Full Setup Guide:** `~/.claude/copilot/SETUP.md`
- **Complete Documentation:** `~/.claude/copilot/README.md`
- **GitHub Issues:** https://github.com/Everyone-Needs-A-Copilot/claude-copilot/issues

---

## Summary

You now have:
- Persistent memory across sessions
- Context preservation between work sessions
- Decision and lesson tracking
- `/continue` command for seamless resumption

This is the foundation. Add agents and skills when you need specialized expertise.

**Next session:** Just say `/continue` and pick up where you left off.
