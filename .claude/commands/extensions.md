# Extensions Status

Show the configured Knowledge ladder, reusable skills, and active agent extensions. Do not create or modify files.

## 1. Inspect the real Knowledge ladder

The only authoritative inputs are `paths.knowledge_repo` and the ordered `CC_KNOWLEDGE_REPOS` value from `cc env` (personal → department → organization → foundation). Do not inspect `~/.claude/knowledge/knowledge-manifest.json` or `./knowledge-manifest.json` unless that path is actually in the ladder.

```bash
eval "$(cc env)"
echo "${CC_KNOWLEDGE_REPOS:-}"
echo "${CC_KNOWLEDGE_REPOS:-}" | tr ',' '\n' | while IFS= read -r repo; do
  [[ -z "$repo" ]] && continue
  if [[ -f "$repo/knowledge-manifest.json" ]]; then
    name="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('name','?'))" "$repo/knowledge-manifest.json" 2>/dev/null)"
    echo "FOUND: $repo (name: $name)"
  else
    echo "MISSING: $repo"
  fi
done
```

Store each tier's position, path, manifest name, and found/missing state. The `tr`/`while` form is portable across bash and zsh.

## 2. Resolve skills and extensions

```bash
cc skill list
cc extensions resolve --all --json
```

Use the returned JSON as source truth. For every agent it supplies `agent`, `action`, `matched`, `type`, `file`, `source_repo`, `description`, `requiredSkills`, `missingSkills`, and `warning`. Resolution is nearest-first: the first tier declaring an agent wins; otherwise the base agent runs unchanged.

Interpret `action` without inventing state:

- `apply`: the declared extension is usable; show its type and source tier.
- `fallback_use_base`: no usable extension was selected; the base agent runs.
- `fallback_use_base_with_warning`: the base agent runs, and the returned warning must be shown.
- `fallback_fail`: show the returned warning as a blocking configuration error. Do not claim the agent can run.
- `no_extension`: no tier declares that agent; this is a healthy base-agent state.

`requiredSkills` and `missingSkills` are evidence, not suggestions. When skills are missing, list their exact names beside the affected agent. Do not scan directories or recompute whether a requirement is satisfied; the resolver already applied the same contract used during agent invocation.

## 3. Present status

If at least one Knowledge tier is configured, return:

```text
## Knowledge Ladder (nearest first)

Tier N: [repo path]
Status: [✓ manifest found (name: ...) / ✗ manifest missing]

## Active Skills

[cc skill list output]

## Active Extensions

| Agent | Action | Type | Source Tier | Description |
|-------|--------|------|-------------|-------------|
| @agent-<id> | <action> | <type or --> | <source_repo> | <description> |

[Agents with matched:false use the base framework unchanged. Surface any warning.]
```

Include only real `matched:true` rows. Sort them by agent ID; never fabricate examples.

After the table, summarize unmatched agents in two groups: healthy `no_extension`/`fallback_use_base` outcomes, and warnings or failures that need action. Preserve the resolver's wording for failures so the report cannot convert a fail-closed result into an apparently healthy status.

If the ladder is empty, return:

```text
## Extension Status

No Knowledge tiers configured. Base framework agents remain available.

## Active Skills

[cc skill list output, or "No skills found"]

## Get Started

1. Run /knowledge-copilot to create or link a repository.
2. Declare its path with `cc config set paths.knowledge_repo <path>`; multiple paths form a nearest-first list.
3. Add and declare `.claude/extensions/<agent>.override.md` or `.extension.md` in that repository.
4. Re-run /extensions to verify the resolved result.
```

## Explain the extension types

- `override`: replace the base agent with a proprietary methodology.
- `extension`: append company-specific instructions after the base agent, explicitly labeled; never section-merge them.
- `skills`: add reusable capabilities without changing agent instructions.

An `override` replaces the base instructions only after successful resolution. An `extension` appends a labeled company section; it does not merge headings or silently win conflicts. A `skills` entry changes availability, not behavior. These distinctions matter when explaining why an agent is using base behavior despite a manifest entry.

For format and fallback details, point to `docs/40-extensions/00-extension-spec.md`.

## Error handling

- If `cc skill list` fails, check `which cc`; if missing, use `bash ~/.claude/copilot/tools/cc/install.sh`.
- If a manifest is unreadable, show that tier as unreadable and continue reporting other verified tiers.
- Missing repositories and `no_extension` are honest states, not fabricated errors.

Never print raw manifest content, tokens, or credential-store values. Paths and manifest names are sufficient for this status command. If a configured tier cannot be read, report that bounded fact; do not fall through and present a farther tier as though it were the configured nearest winner.

Keep the report scannable. Use ✓/✗, show "Not configured" instead of a stack trace, distinguish source tiers, and state that `paths.knowledge_repo` drives automatic ladder discovery.
