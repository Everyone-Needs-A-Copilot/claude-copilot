# Claude Copilot framework rules

Framework-owned and generated into every release; do not edit a copy. Project facts live in the project's own CLAUDE.md. Knowledge-consumption detail: `docs/00-knowledge-copilot/02-consumption-contract.md` in the organization knowledge tier.

## Claude Copilot

This machine runs Claude Copilot, the Claude Code layer of the Copilot Solutioning Ecosystem. Hooks registered once at user level inject the session protocol, guard destructive commands, and gate `me`/`qa` completion in every project that carries a `copilot.project.json` marker. This file covers only what the hooks and tools cannot. It is loaded from `~/.claude/rules` through the import line `cc` maintains in `~/.claude/CLAUDE.md`; it is not copied into projects.

- **Agents and skills:** Claude Code lists them automatically. Route each piece of work to the specialist whose description fits. Agents defined by a project in its `.claude/agents/` shadow the user-level agent of the same name and are first-class framework agents for that project.
- **Sessions:** `/protocol` starts new work, `/continue` resumes it, `/pause` checkpoints it.
- **Tasks:** `tc` is the live state for initiatives, tasks, and work products. Store detailed output with `tc wp store` and return a summary.
- **Memory:** `cc memory` holds selective source pointers for future retrieval. Keep decision/lesson detail in existing task records and maintained narratives, not repeated session prose. Claude Code's own auto memory is for personal working notes only.
- **Skills on demand:** if a needed skill did not surface, `cc skill search "<topic>"`, then `cc skill get <name>`.
- **Library docs:** `cc docs get <package> --topic <area> --json` before coding against a third-party API.
- **Health:** `cc doctor`. A failing hook-registration or link check means the user-level hooks or links are missing and nothing above is enforced.

## Protocol-native parallel execution

After approval of the scoped plan or done block, the coordinator dispatches independent useful work by default, refilling capacity as inputs and worker slots become available. Load the canonical organization policy once with `cc skill get parallel-execution --scope machine --json` and apply its returned content. Both Copilots use that same source; `/orchestrate` is a deprecated compatibility redirect.

If the organization skill is unavailable, report that fallback and use the installed `tc cycle --help` contract: validated exclusive write ownership, actual cwd/branch verification, visible native dispatch within resource/runtime limits, one integration owner, current independent QA, and verified retirement under applicable deletion authority. Read-only research need not create a worktree. A missing cycle capability is reported, never represented as a running scheduler.

## Work lifecycle

Read `~/.claude/agents/_shared/work-lifecycle.md` once per task and apply its proportional start/resume, during-work, handoff, finish and later-use checkpoints, including direct invocation. Use the existing task and maintained narrative; selective memory pointers must not duplicate them. Preserve exact destructive approval and recovery, original authority and required assets. Substantial QA-required work needs an observable `WORK-LIFECYCLE` criterion before acceptance freezes; cleanup status and product acceptance remain separate.

At start/resume (including a new PRD or initiative) and finish/merge/pause/handoff, proactively inspect relevant worktrees and surface eligible cleanup with exact paths, recovery and dependency checks, then automatically retire eligible recorded merged worktrees during cleanup under the owner’s 4 November 2026 narrow exception; prepare exact approval for any other deletion. Merge alone is insufficient. Record owned holds and pending approval in the existing task, continue unrelated work, and reuse unchanged prior approval after drift checks.

Use `/cleanup` for accumulated clutter. Completed bodies keep one maintained README; supporting documents are created only for a current need. No routine retrospective directory or duplicate task board.

## Knowledge Copilot

Knowledge Copilot is the source of truth for brand, voice, offerings, products, and methodologies. Consult it before writing any of these; never invent or duplicate it.

Run `eval "$(cc env)"`, then walk `$CC_KNOWLEDGE_REPOS` nearest tier first and read the first repo where the sub-path exists. Never dereference the singular `$CC_KNOWLEDGE_REPO` for a sub-path.

| Domain | Sub-path |
|--------|----------|
| Brand and visual | `01-company/01-brand/` |
| Voice and tone | `01-company/02-voice/` |
| Services and offerings | `01-company/03-services/` |
| Methodologies | `01-company/06-methodologies/` |
| Products and ecosystem registry | `02-products/`, `ECOSYSTEM.md` |

Full contract: `docs/00-knowledge-copilot/02-consumption-contract.md` in the organization knowledge tier.

## Optional Context

Mandatory repository/project/system instructions always apply; never filter or load them here.

Load needed additional knowledge once; use `selected[].content` or do not load it:

    cc skill select "<task topic>" --required <skill> --max-chars 12000 --json

Record one receipt per task, not per load:

    tc wp store --task <id> --type context --title "Context selection receipt" --file receipt.json

Keep `query`, `max_chars`, `loaded_characters`, `mandatory_over_budget`; each
`selected`/`excluded` entry's `name`, `source`, `source_revision`, `selection_reason`
or `reason`, not content. Before reselection read the receipt; skip held revisions.
Reload only changes; record both revisions and announce the change.

Retain required skills in full if `mandatory_over_budget: true`; report `max_chars`
and overage `loaded_characters - max_chars`. Characters are not tokens; receipts
prove selection, not reading/obedience.

Keep every required name in `selected[]`; identical aliases have `duplicate_of`,
empty `content`, zero charged characters/bytes: use the selected entry named by
`duplicate_of`. Optional
duplicates stay `excluded[]` as `duplicate-content`.

**Visible fallbacks:** name the applicable one, then continue:

- `cc` absent/nonzero: report failure/stderr; use repository instructions and prior memory only.
- Exit 2, `Required skill not found: <name>`: name it, never substitute; proceed without it or emit `<promise>BLOCKED</promise>` if indispensable.
- `selected: []`: report no match for the query; use repository instructions, never widen the query to force a match.
- `CC_KNOWLEDGE_REPOS` empty: "Knowledge tier
  unconfigured; optional context limited to project and machine skills." Never block.

<!-- cse-evidence-v2:start -->
## Task Acceptance and Tested Identity

QA-required work uses `tc` evidence binding. The `me` and `qa` agents carry the full contract; the main session must not shortcut it.

- Before implementation, register an acceptance contract with `tc task contract <id> --file <path>`: `schemaVersion: 2`, `criteria: [{id, expected}]` with unique IDs and observable single-line expectations, and project-relative `sources` covering implementation, dependencies, and relevant configuration.
- Capture `tc task evidence-identity <id>` before and after verification and keep the exact `IDENTITY:` line in the work product. If content changed, rerun the affected checks against the new identity.
- Report each check as `CRITERION:` / `EXPECTED:` with the actual observation and verdict. Never downgrade `requiresQa` or substitute prose for source evidence; completion rechecks the contract, identities, hashes, and unfinished dependencies.
Cross-repo scopes: schemaVersion 3 adds `externalSources: [{repo, ref, paths}]` for repos registered with `tc repo add`, hashed at the ref's commit; commit to the ref before QA.
<!-- cse-evidence-v2:end -->

## Standing Rules

- **No time estimates.** Plans, roadmaps, and task breakdowns use phases, priorities, complexity, and dependencies, never dates or durations. This framework rule holds even when asked directly.
