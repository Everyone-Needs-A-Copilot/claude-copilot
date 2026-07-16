# ADR-002: Auto-Apply Published Framework Updates; Hold On Dirty WIP

> Status: Accepted (owner, 2026-07-16)

## Context

Once the machine can compute what is outdated (ADR-001), the question is *what
to do about it*. Two forces pull against each other:

- The owner wants update-once-follows-everywhere **without** per-project human
  effort — i.e. automatic application.
- codex ADR-001 forbids *"silently updating framework-owned files without a
  reviewable version change,"* and the never-destroy posture forbids touching a
  personal working tree.

The routing rule (control-tower CLAUDE.md invariant #5) resolves the first
tension: **act autonomously on reversible things the user cannot judge; ask the
user only about non-deferrable decisions on their own data.**

## Decision

**Auto-apply** framework-owned updates when, and only when, all hold:

1. the target version exists as a **published release tag** the manifest points
   at (making the change reviewable — a real, inspectable, revertable diff);
2. the update touches **only** `ownership: framework` files;
3. the project's working tree is **not dirty in a way that touches a
   framework-owned path** scheduled for update.

Auto-apply is triggered by **cadence sync** (Control Tower supervises the timer)
noticing a newly published release, and it **reports in the past tense** with
version + per-project detail.

**Hold** (never ask-to-discard, never stash, never `--force`) when the working
tree is dirty in the way: emit `result: held`, `heldReason:
"dirty-working-tree"`, change zero files, and surface it as
*waiting on your unsaved changes* — a fact, not a warning. Only the user can
action their own unsaved work.

**Roll back** on a failed apply: restore the prior framework-owned content and
emit `result: rolled-back` — keep the version that worked.

## Consequences

- The Arc 4 experience is achievable: a fan-out roll-up reports
  *"Updated Claude Copilot across N of your projects to vX,"* with held projects
  listed distinctly.
- Auto-apply does **not** violate codex ADR-001's non-goal, because it only ever
  advances to an already-**published, reviewable** release tag and lands a
  reviewable diff — it is not silent (see the reconciliation table in the
  initiative README). Local silent drift (advancing to an unpublished version)
  remains impossible: there is no code path to a non-tagged version.
- Held projects require an eventual human touch (save/commit their WIP), then
  they pick up the update on the next cadence — no work is lost, none is forced.
- Cadence + auto-apply means a bad release could fan out widely; the mitigation
  is that each apply is reversible/rollback-guarded and the release is a
  reviewable tag that can be yanked/superseded upstream.

## Alternatives Rejected

- **Ask the user before each project update:** rejected — reduces update-once to
  update-N-times-with-prompts; the change is reversible and unjudgeable, so the
  routing rule says auto-act, not ask.
- **Stash/auto-resolve dirty WIP to apply anyway:** rejected — violates
  never-destroy; the user's unsaved work is the one thing only they can action.
- **Apply to any newer version, tagged or not:** rejected — that is exactly the
  local silent drift both initiatives forbid.
- **Apply immediately on publish (push) rather than on cadence:** rejected for
  now — cadence keeps Control Tower the single supervised timer (control-tower
  invariant #2) and avoids requiring an upstream push channel into each machine.
