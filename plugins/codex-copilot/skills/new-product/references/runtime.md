# Runtime Adapter

The skill body is runtime-neutral. This file is the only place that names runtime-specific mechanics. Check once at the start of each session which row applies, say in one line what you will use, and continue. Nothing here is required: if no specialists or tools are available, facilitate single-handed, playing every role yourself, using `docs/TODO-DESIGN-PACKAGE.md` for progress.

## Specialist roles

The document sequence assigns roles (see `document-sequence.md`): Service Designer for Phases 1 to 3, UX Designer for Phases 3 and 4, UI Designer for Phase 4, Copywriter for Phase 4, Design Lead for Phase 5, Industrial Designer (essentialism lens) for the soul passes.

| Runtime | How to bring in a specialist |
|---------|------------------------------|
| Claude Code with Claude Copilot installed | Delegate to the matching subagent: `sd` (service design), `uxd` (UX), `uids` (UI design system), `uid` (UI implementation). Copywriting, the Design Lead role and the soul passes stay with you or `cw` when installed. |
| Codex with Codex Copilot installed | Invoke the matching skill in the main session: `$sd`, `$uxd`, `$uids`, `$uid`. Codex does not delegate unless the user asks. |
| Neither | Facilitate single-handed. Keep one voice and switch lenses explicitly when a document changes role. |

A specialist helps with the facilitation lens and the synthesis. The user's answers remain the source of content; never let a specialist invent what the user did not say.

## Detecting what is available

Use capability checks, not assumptions:

```bash
command -v tc >/dev/null 2>&1 && echo "tc available" || echo "tc not installed"
command -v cc >/dev/null 2>&1 && echo "cc available" || echo "cc not installed"
```

## Task tracking and memory

- Without `tc`: the tracker file `docs/TODO-DESIGN-PACKAGE.md` is the only progress record.
- With `tc`: keep the tracker file as the resume point and also record a PRD with one task per phase, updating task status as phases complete, so the user's task list reflects the process.
- With `cc`: store durable decisions that other sessions must see (for example the product name, the chosen prototype output, ratified soul decisions) with `cc memory`. Do not copy session transcripts into memory.

## Hand-off to build workflows

After the prototype, product development continues in the framework's own workflows, with `docs/` as the source specifications: the protocol workflow (`/protocol` in Claude Code, `$protocol` in Codex).
