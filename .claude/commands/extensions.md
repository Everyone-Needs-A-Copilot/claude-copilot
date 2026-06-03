# Extensions Status

Show the status of the extension system, including knowledge repositories, active extensions, and setup guidance.

## Step 1: Check Knowledge Repository Status

Run these commands to discover knowledge repositories:

```bash
# Check for global knowledge repo
ls ~/.claude/knowledge/knowledge-manifest.json 2>/dev/null && echo "GLOBAL_EXISTS" || echo "GLOBAL_MISSING"

# Check for project knowledge repo
ls ./knowledge-manifest.json 2>/dev/null && echo "PROJECT_EXISTS" || echo "PROJECT_MISSING"

# Check project cc config for knowledge_repo path
cc config get paths.knowledge_repo 2>/dev/null || echo "not set"
```

If a manifest exists, read its name/description:
```bash
cat ~/.claude/knowledge/knowledge-manifest.json 2>/dev/null | head -10
cat ./knowledge-manifest.json 2>/dev/null | head -10
```

Store the results.

---

## Step 2: List Active Skills and Extensions

```bash
# List all discovered skills
cc skill list

# Check for local extensions directory
ls .claude/extensions/ 2>/dev/null && echo "PROJECT_EXTENSIONS_EXIST" || echo "NO_PROJECT_EXTENSIONS"
ls ~/.claude/knowledge/.claude/extensions/ 2>/dev/null && echo "GLOBAL_EXTENSIONS_EXIST" || echo "NO_GLOBAL_EXTENSIONS"
```

Store the results.

---

## Step 3: Present Status

Based on the results, present the extension status.

### If extensions or skills are configured:

```
## Knowledge Repositories

### Global (Machine-Level)
Location: ~/.claude/knowledge/
Status: [✓ Configured / ✗ Not found]
Name: [manifest name]
Extensions: [count from extensions dir]
Skills: [count from cc skill list with source: global]

### Project (This Directory)
Location: [./knowledge-manifest.json path or "Not configured"]
Status: [✓ Configured / Using global only]
Name: [manifest name if configured]
Extensions: [count if configured]

Resolution Priority: Project > Global > Base agents

## Active Skills

[Output from `cc skill list`]

## Active Extensions

| Agent | Type | Source | Description |
|-------|------|--------|-------------|
| @agent-sd | override | global | [description from frontmatter] |
| @agent-uxd | extension | project (overrides global) | [description] |
| @agent-ta | (base) | framework | Industry-standard methodologies |

Note: Only agents listed above have extensions. All other agents use base framework instructions.

## Extension Types

### override
Completely replaces the base agent with your methodology.
- Use when: You have a proprietary methodology fundamentally different from base
- Example: Service Designer using Moments Framework instead of Service Blueprinting

### extension
Adds to the base agent (section-level merge).
- Use when: You want base practices plus company-specific additions
- Example: UX Designer with company design system requirements

### skills
Injects additional skills into the agent.
- Use when: You have company-specific tools/patterns to make available
- Example: Tech Architect with company architecture patterns

## Two-Tier Resolution

The system checks for extensions in priority order:
1. **Project** repository (if configured) - highest priority
2. **Global** repository (~/.claude/knowledge) - auto-detected
3. **Base** framework agents - always available

Set up global once, override per-project only when needed.

## Learn More

See: docs/40-extensions/00-extension-spec.md for complete documentation on:
- Creating knowledge repositories
- Extension file formats
- Fallback behaviors
- Required skills validation
```

### If no extensions are configured:

```
## Extension Status

No extensions configured.
Using base framework agents only.

## Knowledge Repository Status

### Global (Machine-Level)
Location: ~/.claude/knowledge/
Status: ✗ Not found

### Project (This Directory)
Status: Not configured

## Active Skills

[Output from `cc skill list`, or "No skills found"]

## Why Use Extensions?

Extensions customize Claude Copilot agents for your team:
- **Override** agents with proprietary methodologies
- **Extend** agents with company-specific checklists and standards
- **Inject skills** to provide company-specific tools and patterns

This is Claude Copilot's biggest differentiator - bringing your company's expertise into the AI workflow.

## Extension Types

### override
Completely replaces the base agent with your methodology.
Use when: Your methodology is fundamentally different from generic approach.

### extension
Layers company-specific content on top of the base agent.
Use when: You want to keep base practices but add company requirements.

### skills
Adds company-specific skills to an agent without changing behavior.
Use when: You want to provide access to proprietary tools/patterns.

## Get Started

### Option 1: Global Knowledge Repository (Recommended)
Set up once, available in all projects automatically.

Run: /knowledge-copilot

This creates ~/.claude/knowledge/ with:
- knowledge-manifest.json (required)
- .claude/extensions/ (your agent extensions)
- skills/ (company-specific skills)
- docs/ (company glossary, standards)

### Option 2: Project-Specific Knowledge Repository
Only needed when this project requires different extensions than global.

1. Create knowledge repository in your project
2. Set the path in `.claude/cc/config.json`:
   ```json
   {
     "paths": {
       "knowledge_repo": "/absolute/path/to/knowledge"
     }
   }
   ```
3. Or run: `cc config set paths.knowledge_repo /path/to/knowledge`

## Two-Tier Resolution

The system checks for extensions in priority order:
1. Project repository (if configured) - highest priority
2. Global repository (~/.claude/knowledge) - auto-detected
3. Base framework agents - always available

Set up global once, override per-project only when needed.

## Learn More

See: docs/40-extensions/00-extension-spec.md
```

---

## Formatting Guidelines

- Use checkmarks (✓) and crosses (✗) for status indicators
- Show "Not configured" instead of error messages for missing repositories
- Group extensions by agent ID, sorted alphabetically
- Include helpful next steps if no extensions are active
- Keep output scannable with clear headers and tables
- Present information clearly based on actual extension state

---

## Error Handling

**If cc skill list fails:**
- Check that `cc` CLI is installed: `which cc`
- Install if missing: `bash ~/.claude/copilot/tools/cc/install.sh`

**If manifest files are unreadable:**
- Show knowledge repository status (may still work)
- Display "Unable to read manifest" message

---

## Important

- DO NOT create documentation or files unless explicitly requested
- ONLY show status and guidance
- Present information clearly based on actual extension state
- Include setup instructions appropriate to current state
- Distinguish between global (team-wide) and project (local) extensions
- Emphasize that global knowledge is auto-detected (no config needed)
