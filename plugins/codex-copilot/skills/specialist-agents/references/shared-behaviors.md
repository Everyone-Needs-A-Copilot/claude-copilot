# Shared Behaviors

Codex Copilot mirrors Claude Copilot's shared agent behaviors through Codex-native skills and repo instructions.

## Session Preamble

When the work is substantial or needs durable context:

1. Check task context with `tc task get <taskId> --json` when a task id exists.
2. Hydrate Copilot config when `cc` is available:

```bash
eval "$($HOME/.local/bin/cc env)"
```

1. Search memory for relevant decisions:

```bash
$HOME/.local/bin/cc memory search "<task topic>"
```

After framework updates, repo restructures, or work that relies heavily on
durable memory, check for deterministic drift:

```bash
$HOME/.local/bin/cc memory check --json
```

1. Check the working tree before edits:

```bash
git status --short
```

1. For third-party API planning or implementation, verify the installed package API with Live Docs:

```bash
$HOME/.local/bin/cc docs get <package> --topic <area> --json
```

If `cc docs` is unavailable, say so and inspect local package files or official docs before coding against that API.

## Skill Discovery

Codex skills are the primary path in Codex sessions. Use `cc skill search "<topic>"` or `cc skill get <name>` as a fallback when a reusable skill is not already visible in the session.

Optional parity specialists (`kc`, `cco`, `cw`, `cs`, `cpa`) live in dormant packs. Activate them with `scripts/activate-pack.py` when the project needs those capabilities; do not load them globally by default.

For optional context beyond an already loaded specialist, use
`cc skill select "<topic>" --required <necessary-skill> --max-chars 12000 --json`
when available. Store the selection receipt once in the task work product; compare
source identities to avoid repeated loading. Character counts are not tokens.
Mandatory repository/system constraints always apply and are never relevance-filtered.
`cc doctor --runtime-details --json` separates project installation from unknown
runtime trust/dispatch; `--exercise-runtime` runs direct diagnostic hooks only.

## Task Copilot Pattern

For substantial work, use `tc` as the execution record:

```bash
tc task get <taskId> --json
tc wp store --task <taskId> --type <type> --title "..." --content "..." --json
tc task update <taskId> --status completed --json
```

If no task exists, create a PRD and task rather than writing planning state into ad hoc markdown.

`--task` on `tc wp store` is optional (`task_id` is schema-nullable): if a
work product needs to be externalized and no task ID exists yet, omit
`--task` and store a standalone work product instead — it stays fully
listable/gettable/searchable. No task ID is never a valid reason to skip
storage and fall back to inlining the full deliverable in chat.

Never trust `which tc` as an availability gate — the common
`alias which='type -all'` dotfile pattern makes `which <anything>` fail
regardless of whether the target exists, producing false negatives. If you
need to check availability first, use `command -v tc`, or just attempt the
real command directly.

For formal multi-phase initiatives, store durable goals, phase designs, decisions, validation evidence, and retrospectives under `docs/40-initiatives/NN-slug/`. Link those documents to `tc`; do not duplicate live task state in Markdown.

For three or more related `tc` operations, prefer a single `python3` block importing `tc.api` and print one compact result. For three or more related `cc` memory or skill operations, use a separate block importing `cc.api`. Do not mix `tc.api` and `cc.api` in one process.

## Specification Workflow

Domain agents (`sd`, `ind`, `uxd`, `uids`, `cco`, `cw`) should create `specification` work products and route to `ta` for task creation. They do not directly create implementation tasks unless the user explicitly asks for a lightweight, single-session result.

## Memory Store

After meaningful decisions or lessons, store durable memory when `cc` is configured:

```bash
$HOME/.local/bin/cc memory store --type decision "<decision and rationale>"
```

Use `decision`, `context`, `lesson`, `reference`, or `person` as appropriate.

## Return Format

Lead user-facing output with the answer, decision, result, or blocker. Include only what the user needs to trust it, decide, or act; store detailed analysis, specs, command traces, and verification records as work products when `tc` context exists.

- Default to at most 6 sentences or 5 bullets unless requested depth, risk, complexity, or completeness requires more.
- Use one-sentence progress updates: material result plus next active step.
- Lead completion reports with the outcome, then give only changed scope, verification, and any remaining caveat or action.
- For a real decision, use an outcome headline, 2–3 numbered outcome options, and a question of at most 4 words. With no real decision, do not manufacture options or ask for approval.
- Never omit a required finding, uncertainty, citation, safety warning, QA artifact/verdict, Task/WP identifier, or blocker to meet a length target.

## Quality Gates

- `me` is not the final gate when tests or verification are relevant.
- `qa` verifies implementation before closure.
- implementation tasks that require verification should carry `metadata.requiresQa=true`
- `qa` stores a `test` work product and a verdict; `scripts/copilot-gate.sh` checks this convention
- `sec` reviews security-sensitive changes before closure.
- `do` owns deployment planning before deploy or CI changes.
- Destructive actions require explicit current user approval.

## Optional Context

Mandatory repository, project, and system instructions always apply. They are never
subject to relevance filtering and are never loaded through this step.

When the task needs knowledge beyond those instructions, load it once:

    cc skill select "<task topic>" --required <skill> --max-chars 12000 --json

Use the returned `selected[].content`. If you will not use it, do not load it.

Record the receipt once per task, not once per load:

    tc wp store --task <id> --type context --title "Context selection receipt" --file receipt.json

Keep `query`, `max_chars`, `loaded_characters`, `mandatory_over_budget`, and for every
entry in `selected` and `excluded` its `name`, `source`, `source_revision`,
`selection_reason` or exclusion `reason`. Do not re-store the content itself.

Before selecting again inside the same task, read that receipt. Skip any skill whose
`source_revision` you already hold. Reload only when the revision differs, and when it
does, record both revisions and say the source changed.

`mandatory_over_budget: true` means a `--required` skill was retained past the budget.
Report it: "Required context exceeded the `<max_chars>`-character budget by
`<loaded_characters - max_chars>` characters; retained in full." Never drop it to fit.

Character counts are not model tokens, and a receipt records selection, never proof
that content was read or obeyed.

**Visible fallbacks.** Name the one that applied, then continue:

- `cc` unavailable or non-zero exit: "Optional context unavailable (`cc skill select`
  failed: <stderr>); proceeding on repository instructions and prior memory only."
- Required skill not found (exit 2, `Required skill not found: <name>`): do not
  substitute a similar skill. State the missing name, then proceed without it — or emit
  `<promise>BLOCKED</promise>` if the task genuinely cannot proceed without it.
- No optional skill matched (`selected: []`): "No optional context matched '<query>';
  proceeding on repository instructions." Do not widen the query to manufacture a match.
- No knowledge repos configured (`CC_KNOWLEDGE_REPOS` empty): "Knowledge tier
  unconfigured; optional context limited to project and machine skills." Never block.

Every explicitly required skill name remains in `selected[]`. Identical required
content is emitted once: subsequent required aliases have `duplicate_of`, empty
`content`, and zero charged characters/bytes; use the named selected entry's
content. Optional duplicates remain in `excluded[]` as `duplicate-content`.
