# Handoff: orchestration by default and Codex parity (2026-11-06)

Written for a new developer session that finishes a multi-day framework effort for Pablo (the owner). You should be able to work from this document alone.

## Outcome first

Claude Copilot enforces the coordinator rule mechanically today. Codex Copilot does not, in any folder on this machine, because Codex loads an old bundled copy of the plugin (0.16.0) that has no coordinator guard and no trust entry. Fixing that, proving it in a real Codex session, and rolling both components to every eligible project is the job. Nothing about the goal is open for decision.

## What the owner wants

1. **Orchestration by default, in both Copilots, enforced mechanically.**
   - The main session never does work itself. It coordinates and dispatches multiple parallel independent agents for every kind of work. This protects context and session integrity and finishes faster.
   - Divide-and-conquer applies to every role and stage: strategy, research, service design, UX, visual design, copy, architecture, development, QA/testing, security, docs, ops, sales, finance. Example: several strategy agents each take part of the strategy, with one synthesis owner.
   - Testing is partitioned across agents by criterion, journey, surface, shard or browser. Never one agent running a full E2E suite.
2. **Claude Copilot and Codex Copilot are both updated, and every eligible project on the machine has both at the latest version.** There is no ambiguity and no decision to make. Every project with Claude Copilot also gets Codex Copilot.
3. **"Done" means verified working in both runtimes.** The Codex coordinator guard must actually load and fire in a real Codex session, not just exist in a repo or a materialized root.

## Working rules (owner's explicit instructions as of 2026-11-06)

- Check both Claude and Codex up front, do all the work for both, and verify both before reporting. Never finish Claude and then discover Codex is not working. Never report "not done, want me to do it?"
- Fix bugs and blockers proactively along the way without asking permission.
- The only thing that needs the owner's permission is deleting something. Exception: worktrees for work that is already done and merged may be deleted without asking.
- Do not push product repos that deploy without asking. Pushing framework and tooling repos is fine.
- No force-push. Preserve others' work.
- Spending limit is $0.
- "Commit" means merge all uncommitted work, sync to GitHub (through a PR where the repo requires one), then update every project and commit each locally.
- Lead with the result in conversation.
- The main session coordinates only. The guard enforces this with an allowlist: `tc`, `cc status/list/progress/skill`, `git status/log/branch/worktree list/rev-parse`, `pwd/date/readlink`, and memory and scratchpad paths. Off switch: `COPILOT_COORDINATOR=off` (it is logged). Dispatch agents for everything else.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Verified live state (read-only checks, 2026-11-06)

| Fact | Value |
|---|---|
| claude-copilot latest tag; main HEAD | v5.34.8; `e4578de8f1269d5968356008b0db535cf7ada1f2` (equals origin/main at check time) |
| codex-copilot latest tag; main HEAD | v0.16.8; `2c1b67e26de5d3e33cb433ccc98f70f13e0b5108` (v0.16.8 commit is the same) |
| Bundled `claude-copilot/plugins/codex-copilot` on main | 0.16.0. `hooks/` has no `coordinator-guard.sh`. |
| Source `codex-copilot/plugins/codex-copilot` | 0.16.8. `hooks/coordinator-guard.sh` exists and `hooks/hooks.json` references it (1 match). |
| Codex cache `~/.codex/plugins/cache/codex-copilot-project/codex-copilot/` | Holds 0.15.0 and 0.16.0 only. Neither has `hooks/coordinator-guard.sh`. Both `hooks.json` files register only debug-circuit-breaker, design-feedback, subagent-return-contract and user-prompt-protocol. |
| `~/.codex/config.toml` enabled plugin | `[plugins."codex-copilot@codex-copilot-project"] enabled = true` |
| `codex-copilot-project` marketplace source | local, `/Users/pabs/.copilot/framework-snapshots/claude-copilot-8d1b0de6c3b6fb7dd77426cd4fb9b86afa5b3d5a` (an older snapshot than the one in `paths.claude_copilot_root`) |
| Other registered marketplaces | `enac-materialized` -> `/Users/pabs/.copilot/materialized/codex`; `codex-copilot-local` -> `/Volumes/Dev/Sites/CSE/codex-copilot`. Both registered but their codex-copilot plugins are not the enabled ones. |
| Trust entry for the guard (`pre_tool_use:1:0`) | None. `codex-copilot@codex-copilot-project` has trust entries only for `pre_tool_use:0:0`, `post_tool_use:0:0`, `post_tool_use:1:0`, `user_prompt_submit:0:0`, `subagent_start:0:0`. A grep for `coordinator` and `pre_tool_use:1` in the file matched nothing. |
| `~/.claude/cc/config.json` `paths.claude_copilot_root` | `/Users/pabs/.copilot/framework-snapshots/claude-copilot-e4578de8f1269d5968356008b0db535cf7ada1f2` (5.34.8) |
| `~/.claude/cc/config.json` `paths.codex_copilot_root` | `/Volumes/Dev/Sites/CSE/codex-copilot` |
| Claude guard | `~/.claude/hooks/coordinator-guard.sh` exists (executable, 8765 bytes). `~/.claude/settings.json` registers it under `PreToolUse`, matcher `Bash|Read|Grep|Glob|Edit|Write|NotebookEdit|MultiEdit`, timeout 5. It is live and blocked the coordinator twice on 2026-11-06. |
| Excluded projects | `~/.copilot/excluded-projects.json` exists (contents beyond the first lines not reviewed). |

### Interrupted worktree (left untouched)

Path: `/Volumes/Dev/Sites/CSE/claude-copilot/.claude/worktrees/embed-codex-0.16.8`. Branch: `fix/embed-codex-0.16.8`. HEAD: `e4578de` (same commit as main, so nothing is committed on the branch).

- Staged (25 files, 273 insertions, 40 deletions): `plugins/codex-copilot/` synced toward 0.16.8. `plugin.json` is 0.16.0 -> 0.16.8, `hooks/coordinator-guard.sh` is added, plus `hooks.json`, `user-prompt-protocol.sh`, `agent-catalog.json`, `scripts/protocol-cycle.py`, and skills (do, doc, ind, launcher, me, protocol-router, protocol, qa, sd, sec, specialist-agents, ta, uid, uids, uxd).
- Unstaged: `VERSION.json` gains a `codexPlugin` pin: version 0.16.8, path `plugins/codex-copilot`, sourceRepo `https://github.com/Everyone-Needs-A-Copilot/codex-copilot.git`, sourceTag `v0.16.8`, sourceCommit `2c1b67e2...`, pluginTree `b4a547f54c6692f6fe433a4d8d9a0c13f3c296cd`.
- Untracked: `scripts/check-codex-plugin-pin.py`. The pin note says it enforces the pin in CI and in `scripts/tag-release.sh`, but that wiring is not present in the diff (only `VERSION.json` is modified outside `plugins/`). Treat the gate as not wired.
- Nothing was released or installed. Review it, then continue or redo. Verify the sync is byte-for-byte (compare git tree ids of `plugins/codex-copilot` at tag v0.16.8 and in the bundle, and check for files that should be deleted in the bundle, since only modified or added paths show in the staged list).

### Per-project versions (from `copilot.lock.json` files, depth `<root>/<project>`)

`cc reconcile assess` did not finish within about 5 minutes when I ran it, so I stopped it and read the lock files instead. The numbers below come from the locks, not from reconcile.

- 64 projects at Claude 5.34.8 and Codex 0.16.7. This matches the owner's summary.
- `CSE/cli-copilot-internal` at 5.34.8 / 0.16.8 (PR #37 merged per the owner).
- `TSM/h3` at 5.33.1 / 0.15.0 (held: live sessions).
- Claude-only by declaration: `claude-copilot-accounting`, `claude-copilot-internal`, `cli-copilot` (locks show 5.33.1 and no Codex component).
- Not in the owner's summary and stale in their locks. Find out why for each (excluded, ineligible, or missed), then fix or record the reason: `CSE/knowledge-copilot-private` (5.33.1 / 0.6.5), `CSE/codex-copilot-private`, `CSE/codex-copilot-accounting`, `CSE/claude-copilot-private`, `CSE/knowledge-copilot-accounting`, `CSE/cli-copilot-accounting`, `CSE/cli-copilot-private` (all 5.33.1 / 0.15.0), `CSE/shared-docs`, `CSE/knowledge-copilot`, `CSE/codex-copilot-internal`, `CSE/knowledge-copilot-internal` (all 5.13.3 / 0.15.0), `CSE/claude-copilot` itself (5.14.10 / 0.7.0), `COPILOT/preflight-copilot` and `_archive/preflight-copilot` (excluded per the owner). Whether the owner's "64 eligible" intentionally leaves out the others is unverified; the owner said every eligible project, so the rule is: if it has Claude Copilot and is not excluded or Claude-only by declaration, it gets both.
- Other states the owner reported and I did not re-verify: pushed repos (copilot-bench, copilot-custodian, copilot-fleet, product-creation-copilot, the-herd); product repos, cse-101 and PERSONAL repos committed locally only; copilot-control-tower PR #16 merged; knktr-serve and preflight-copilot excluded.

## What is in place

- **Rule and skill.** The coordinator rule is in `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`. The canonical skill is `claude-copilot-internal/skills/parallel-execution/SKILL.md` (v1.11.9/1.11.10), symlinked from `~/.claude/skills` and `~/.codex/skills`. It has split axes for 13 roles, verification partitioning and functional-category fan-out.
- **Claude side.**
  - Guard `claude-copilot/.claude/hooks/coordinator-guard.sh`: finds subagents through `agent_id` in the hook stdin JSON and parses git arguments against an allowlist.
  - Supporting files: `pretool-check.sh` (force-delegate defers to the guard), `protocol.md`, `protocol-injection.md`, and partition lines in the agents (qa, me, ta, sec, doc, cco, cw, cs, cpa, ind, kc).
  - Installer `scripts/install-framework-snapshot.py` installs the guard and its settings.json hook, repoints `paths.claude_copilot_root`, validates config before side effects, and has `RollbackIncompleteError`.
- **Codex side (source repo only).** `codex-copilot/plugins/codex-copilot/hooks/coordinator-guard.sh` finds subagents through transcript line 1 and applies a git argument allowlist after quote removal. Also present: `hooks.json`, `user-prompt-protocol.sh`, `AGENTS.md`, `SOUL.md`, the protocol, launcher, router and specialist skills, the parallel-execution reference, and `qa/SKILL.md`.
- **browser-check** (`/Volumes/Dev/Sites/PERSONAL/browser-workbench`) supports `start --shard i/n --grep --grep-invert --project`.
- **Releases.** claude-copilot through v5.34.8. codex-copilot through v0.16.8 (0.16.8 only lint-sorts `scripts/protocol-cycle.py`). Layer pins are in `~/.config/copilot/copilot.layers.yml`.

## Remaining work, in order

### The critical gap (do this first)

**What is wrong.** Codex sessions in every folder load `codex-copilot@codex-copilot-project` 0.16.0 from `~/.codex/plugins/cache/codex-copilot-project/codex-copilot/0.16.0/`. That copy has no coordinator guard and no trust entry, so the coordinator rule is not enforced in Codex at all.

**Root cause.**
- Since claude-copilot 5.32.0, the installer (`scripts/codex_plugin_snapshot.py`) removes every other codex-copilot install and enables only `codex-copilot-project`.
- That marketplace points at the installed claude-copilot framework snapshot and its bundled `plugins/codex-copilot`.
- Every claude-copilot release through 5.34.8 still bundles 0.16.0.
- Updating codex-copilot itself, or the materialized root `~/.copilot/materialized/codex`, changes nothing Codex loads.
- The existing parity check did not catch it. Find out why (what it compares, and whether it reads the bundle or the source repo).

### Step 1: Bundle fix

1. Sync claude-copilot's bundled `plugins/codex-copilot` byte-for-byte to the latest codex-copilot tag (v0.16.8 at time of writing). Start from the interrupted worktree or redo it.
2. Add a release gate that fails when the bundled plugin differs from the paired codex-copilot version. Wire it into CI and `scripts/tag-release.sh`. Explain in the commit why the existing parity check missed the drift.
3. Release claude-copilot v5.34.9, plus a codex-copilot parity release if coherence requires one. Update the layer pins.
4. Install on the machine with the framework installer.
5. Verify:
   - `~/.codex/config.toml`'s `codex-copilot-project` marketplace source points at the new snapshot;
   - Codex's cache holds the new version, with `hooks/coordinator-guard.sh` present and registered in that version's `hooks/hooks.json`.
6. Do not hand-edit `~/.codex/config.toml`. If the installer does not re-cache, fix the installer.

### Step 2: Owner step (the only human step)

Pablo starts a new Codex session and trusts the guard hook (`pre_tool_use:1:0`, the second PreToolUse group) in `/hooks`. Trust is user-wide and is redone only when the hook content changes. Check whether Claude's settings need anything. Today `~/.claude/settings.json` already registers the guard, so likely nothing, but confirm after the 5.34.9 install. Ask Pablo for this one step once, with exact instructions, only after Step 1 is verified.

### Step 3: End-to-end proof in both runtimes

- In a real Codex session and a real Claude session, show that the main session is blocked from a write or work command and that a subagent is allowed. Record the evidence (command, block message, subagent success) in a work product.
- Prove that a verification task fans out across multiple QA agents (partitioned by criterion, journey, surface, shard or browser).

### Step 4: Project rollout

1. Reconcile every eligible project to the new versions of both components. `cc reconcile` assess/plan/apply/verify holds a machine-wide lock, so exactly one agent runs it. Record that reason in the work product.
2. Fan out local commits across parallel agents partitioned by root: COPILOT, CSE+PERSONAL, TSM/THD/other, `_archive`. Stage only the changed paths listed in the reconcile output. Never use `git add -A`, `.` or `-f`.
3. Push framework and tooling repos. Use PRs where main is protected (cli-copilot-internal, copilot-control-tower), merge when green, and delete the merged PR branch.
4. Do h3 when its sessions are idle.
5. Product repos that deploy stay local unless Pablo says push.

### Step 5: Parked defects (fix without asking)

- `cc reconcile apply` exits 1 "partial" even when every selected project applied and verified, because the final whole-machine check counts unselected or held projects.
- Codex lock entries for convoco, copilot-control-tower, gtm-copilot and insights-copilot lack reconcile's source-tracking fields (`ownership_mode`, `provenance`), so they show a false "update available". cli-copilot-internal was fixed by a proper apply.
- Reconcile does not update a project's `.codex-copilot.json` version.
- A previous apply deleted 69 files of gtm-copilot's `docs/` copy of the plugin; they were restored. Guard against it recurring.
- A dry run writes `~/.claude/cc/entitlements.json`. Dry runs must not write.
- Convoco's project-owned `scripts/copilot-gate.sh` adds a `TC_BIN` override that the shared Codex gate lacks. Upstream the optional `TC_BIN` override into codex-copilot's gate (additive and harmless), then drop Convoco's project-owned marking so it receives the shared file again.
- `cc reconcile assess` was very slow in the check above (over 5 minutes without finishing). Find out why while you are in there.

### Step 6: Cleanup

Retire merged worktrees (allowed without asking). Close out tasks through the task-closeout skill (`cc skill get task-closeout --scope machine --json`). Confirm both repos' mains equal their tags.

## Definition of done

- [ ] claude-copilot main equals the latest claude-copilot tag, and the bundled `plugins/codex-copilot` tree id equals the paired codex-copilot tag's `plugins/codex-copilot` tree id.
- [ ] A release gate fails when the bundle differs from the paired codex-copilot version (shown to fail on a deliberately drifted copy, then pass).
- [ ] `~/.codex/config.toml` `codex-copilot-project` marketplace points at the new snapshot, with no hand edits.
- [ ] Codex cache version equals the latest codex-copilot tag and contains `hooks/coordinator-guard.sh`, registered in `hooks.json`.
- [ ] `~/.claude/hooks/coordinator-guard.sh` exists and is registered in `~/.claude/settings.json`.
- [ ] `/hooks` trust for `pre_tool_use:1:0` is present in `~/.codex/config.toml` after Pablo's one step.
- [ ] A real Codex main session is blocked from a work command and a Codex subagent is allowed; evidence recorded.
- [ ] A real Claude main session is blocked from a work command and a Claude subagent is allowed; evidence recorded.
- [ ] A verification task fanned out across multiple QA agents in each runtime; evidence recorded.
- [ ] Every eligible project's `copilot.lock.json` shows the latest Claude and latest Codex versions (check by script across all roots, and list each exclusion, hold and Claude-only declaration with its reason).
- [ ] `cc reconcile` verify is clean for the selected set, and `apply` no longer exits "partial" when all selected projects verified.
- [ ] All repos committed; framework and tooling repos pushed; product repos committed locally and listed for Pablo.
- [ ] Parked defects in Step 5 are fixed and have tests.
- [ ] Merged worktrees retired; tasks closed out; both mains equal their tags.

## Mechanics and traps

- Codex loads the plugin bundled in claude-copilot (`plugins/codex-copilot`) through the `codex-copilot-project` marketplace. Fixing codex-copilot alone changes nothing Codex runs.
- `paths.claude_copilot_root` and `paths.codex_copilot_root` in `~/.claude/cc/config.json` decide what reconcile delivers. A stale root once delivered 5.34.1 to 28 projects. Check both before every reconcile.
- `framework_history.HISTORY_PATHSPECS` governs stale-file adoption.
- There is a codex-org lock overlay. Refresh codex-org overlays with codex-copilot's `update-project.sh`.
- `tag.gpgSign` is on, so bare `git tag` fails. Use `git update-ref` for tags and verify the signatures.
- cc accepts both `plugins/codex-copilot` and `./plugins/codex-copilot` AGENTS.md entries.
- Reconcile is blocked by dirty project trees, so commit between passes.
- A release must be installed on the machine before projects can receive it.
- Commit signing is not configured (only tags), so project commits are unsigned. That is expected.
- Earlier guard bypasses (`git log --output`, single `&`, `git branch -D`, abbreviated or quoted options) were closed with an allowlist parser. Keep that parser in both guards and add regression tests for each when you touch either one.
- The Codex guard identifies subagents from transcript line 1; the Claude guard uses `agent_id` in hook stdin JSON. The two detection methods differ, so test each in its own runtime.
- `COPILOT_COORDINATOR=off` disables the guard and is logged. Do not use it to get work done; dispatch agents.

## Unverified in this document

- Full `cc reconcile assess` output (did not complete; lock files used instead).
- Whether the omitted stale CSE repos listed above are intentionally out of the 64.
- Contents of `~/.copilot/excluded-projects.json` beyond its first entries.
- PR, push and merge states the owner reported for named repos.
- Whether `hooks.json` in the source codex-copilot registers the guard under the second PreToolUse group (one match for `coordinator-guard` found; position not checked).
