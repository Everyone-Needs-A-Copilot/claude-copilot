# Extensions Status

Show the status of the extension system, including knowledge repositories, active extensions, and setup guidance.

## Step 1: Check Knowledge Repository Status

`~/.claude/knowledge/knowledge-manifest.json` and `./knowledge-manifest.json` are NOT the machine's real configured knowledge sources — do not read them. The real sources are the ordered `CC_KNOWLEDGE_REPOS` ladder `cc env` exports (`paths.knowledge_repo`, nearest-tier-first: personal → department → org → foundation). Discover it and check each tier for a manifest:

```bash
eval "$(cc env)"
echo "Ladder (nearest tier first): ${CC_KNOWLEDGE_REPOS:-<none configured>}"

# Portable across bash and zsh (this framework's Bash tool may run either,
# depending on the harness/OS default shell) -- avoid `read -ra` array
# syntax, whose `-a` flag is bash-only; zsh needs `-A`. Splitting on
# newlines via `tr` and reading one line at a time with `while IFS= read -r`
# is the same idiom already used elsewhere in this repo's command files
# (setup-project.md, update-project.md) and works identically in both shells.
echo "${CC_KNOWLEDGE_REPOS:-}" | tr ',' '\n' | while IFS= read -r repo; do
  [[ -z "$repo" ]] && continue
  if [[ -f "$repo/knowledge-manifest.json" ]]; then
    name="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('name','?'))" "$repo/knowledge-manifest.json" 2>/dev/null)"
    echo "FOUND:   $repo  (name: $name)"
  else
    echo "MISSING: $repo  (no knowledge-manifest.json at this tier)"
  fi
done
```

Store the results (repo path, tier position, name, found/missing) per tier.

---

## Step 2: List Active Skills and Extensions

Extensions are per-agent entries inside each tier's `knowledge-manifest.json`, resolved with personal-over-org precedence by walking the SAME `CC_KNOWLEDGE_REPOS` ladder — never a fixed `~/.claude/knowledge/.claude/extensions/` path. Resolve every agent in one deterministic call instead of hand-listing directories:

```bash
# List all discovered skills
cc skill list

# Resolve every agent's extension across the real ladder (one deterministic
# call per agent id -- this is what /protocol and every wired agent's own
# Workflow step 3 now call too, so this status view matches what actually
# fires on invocation)
cc extensions resolve --all --json
```

Store the parsed JSON array (one object per agent id: `agent`, `action`, `matched`, `type`, `file`, `source_repo`, `description`, `requiredSkills`, `missingSkills`, `warning`).

---

## Step 3: Present Status

Based on the results, present the extension status.

### If the ladder resolves at least one manifest or extension:

```
## Knowledge Ladder (nearest tier first)

[For each entry in $CC_KNOWLEDGE_REPOS, in order:]
Tier N: [repo path]
Status: [✓ knowledge-manifest.json found (name: ...) / ✗ no manifest at this tier]

Resolution rule: for each agent, the FIRST tier (in the order above) whose
manifest declares an `extensions[]` entry for that agent wins outright --
personal-over-org precedence falls out of this list's order, not a separate
rank comparison.

## Active Skills

[Output from `cc skill list`]

## Active Extensions

[Build this table from the real `cc extensions resolve --all --json` output --
one row per agent where `matched: true`. Do not fabricate rows for agents
that returned `no_extension`.]

| Agent | Action | Type | Source Tier | Description |
|-------|--------|------|-------------|--------------|
| @agent-<id> | <action> | <type or --> | <source_repo> | <description> |

Agents not listed above returned `no_extension` (no repo in the ladder
declares an entry for them) -- they run on base framework instructions,
unchanged. This is a legitimate, honest outcome, not a failure.

## Extension Types

### override
Completely replaces the base agent with your methodology.
- Use when: You have a proprietary methodology fundamentally different from base
- Example: Service Designer using the Moments Framework instead of generic Service Blueprinting

### extension
Appends company-specific content after the base agent (never a section-level merge -- `cc.core.extensions_resolver.compose_agent_content()` guarantees both bodies of text reach the agent, in a fixed, labeled order; it does not attempt to decide which overlapping prose section "wins").
- Use when: You want base practices plus company-specific additions
- Example: UX Designer with company design system requirements

### skills
Injects additional skills into the agent (no content change).
- Use when: You have company-specific tools/patterns to make available
- Example: Tech Architect with company architecture patterns

## Ladder Resolution

The system checks for extensions in ladder order (nearest tier first, exactly
`$CC_KNOWLEDGE_REPOS`): the first tier whose manifest declares an entry for an
agent wins; if none do, the base agent runs unchanged. This same resolution
now fires automatically as step 3 of every wired agent's own Workflow (not
only when routed through `/protocol`) -- see `docs/00-knowledge-copilot/
02-consumption-contract.md`.

## Learn More

See: docs/40-extensions/00-extension-spec.md for extension file formats,
fallback behaviors, and required-skills validation.
```

### If no tier resolves a manifest or extension:

```
## Extension Status

No knowledge tier configured (or no tier declares any agent extensions).
Using base framework agents only.

## Knowledge Ladder Status

[List $CC_KNOWLEDGE_REPOS entries with ✗ next to each, or "No knowledge
tiers configured (CC_KNOWLEDGE_REPOS empty)" if the ladder itself is empty]

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
Appends company-specific content after the base agent (labeled, not merged).
Use when: You want to keep base practices but add company requirements.

### skills
Adds company-specific skills to an agent without changing behavior.
Use when: You want to provide access to proprietary tools/patterns.

## Get Started

1. Run `/knowledge-copilot` to create or link a knowledge repository -- it
   writes the repo path into `paths.knowledge_repo` via
   `cc config set paths.knowledge_repo <path>` (this key accepts an ORDERED
   LIST for multiple tiers -- personal, department, org, foundation --
   nearest tier first).
2. Add a `.claude/extensions/<agent>.override.md` or `.extension.md` file to
   that repo and declare it in the repo's own `knowledge-manifest.json`
   `extensions[]` array (see docs/40-extensions/00-extension-spec.md).
3. Re-run `/extensions` (or `cc extensions resolve --agent <id> --json`) to
   confirm it resolves.

## Ladder Resolution

The system checks for extensions in ladder order (nearest tier first): the
first tier whose manifest declares an entry for an agent wins; if none do,
the base agent runs unchanged.

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
- Distinguish which tier of the `CC_KNOWLEDGE_REPOS` ladder each active extension resolved from
- Emphasize that the ladder is auto-detected from `paths.knowledge_repo` once configured (no per-project config needed)
