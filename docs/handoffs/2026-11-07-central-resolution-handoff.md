# Central Resolution (PRD-16): handoff

Written 7 November 2026 for the developer taking over. All agents from the previous session are stopped. Nothing from this work has been pushed except one accidental auto-push (voice-copilot, see Open decisions).

## Where things stand

The architecture is built, released locally and live on this machine: release `20261107T111725Z-e1a975e57fbb` (#11) is active through `~/.copilot/current`. 51 product projects and 13 framework source repos are migrated and committed locally. One complete parallel QA sweep ran and produced a single defect list (D1–D10 below). The fix round was interrupted by the owner. D5, D6 and part of D7 are fixed and committed. D1 and D7 were stopped part-way through, so check their state before doing anything else (see "Verified state at handoff" at the end). D2, D3, D4, D8, D9 and D10 were not started; the agents had only begun investigating.

Your job, in order:
1. Recover the two interrupted items.
2. Finish the fix list.
3. Retest only those defects.
4. Build one more release.
5. Publish.
6. Close out.

## What the owner asked for (requirements)

- **One central install.** Centralize the Copilot Solutioning Ecosystem so an ecosystem upgrade reaches all ~60 projects without per-project syncing. This applies to every component and layer: Claude Copilot, Codex Copilot, the Knowledge Copilot organization, department and personal tiers, CLI Copilot, Control Tower and product-creation.
- **Install and setup.** A one-time machine install is fine. Project setup must take under 10 seconds; `cc project init` measures about 0.35 s. claude.ai cloud is out of scope.
- **Project-specific rules stay.** Each project keeps its project-specific rules and capabilities: its own CLAUDE.md and AGENTS.md sections, and its project-owned agents and skills. Only framework-owned copies are removed.
- **Both Copilots.** Every project gets both Claude and Codex, never Claude only.
- **Release pointer.** Projects resolve through a release pointer, not the live dev repo. Company tiers are pinned to signed tags. The personal tier, knowledge-copilot-private, stays live on main.
- **Fleet commits stay local.** Fleet migrations are committed locally on each project's current branch and never pushed. The owner will deal with those commits in a separate conversation, so do not push or rework them.
- **Publish.** The owner said "Once complete, please publish". That means pushes, PRs, signed final tags and notarized builds, each through the repo's normal workflow. Never bypass claude-copilot's branch protection, signed-commit requirement or CodeQL.
- **Blast-Radius QA is the default.** Canonical text: `cc skill get blast-radius-qa --scope machine --json`. Run one round of checks in parallel across several QA agents, never serially. Every check runs to completion. Collect one defect list and fix it all. Retest only the failed checks plus anything that shares code with the fixes, then stop.
- **Owner's latest instruction.** "Do not do another test until all work is complete," followed by "a single round of checks… a single list of defects… address those issues, then test those specific issues until you're done." The single round has already happened. Only targeted retests of D1–D10 remain.

## Architecture in brief

- **Release pointer.** `~/.copilot/current` points to an immutable `~/.copilot/releases/<id>/`, which carries a `release.json` manifest covering every component and knowledge tier. Flip and rollback are atomic, and history is kept. Commands: `cc release build | flip | rollback [--steps N | --to ID] | status | doctor | publish`. ADR: `docs/40-initiatives/06-central-resolution/decisions/ADR-001-central-release-pointer.md`. Machine install, including `allowed_signers`: `docs/01-getting-started/03-machine-install.md`.
- **Claude user level.** `~/.claude/agents`, `skills` and `commands`, and `~/.codex/skills`, are symlinks into the release. Framework rules load through the import line `@~/.copilot/current/claude-copilot/templates/framework-rules.md` in `~/.claude/CLAUDE.md`. One hook shim is registered in `~/.claude/settings.json`. It acts only in projects that carry a `copilot.project.json` marker, and it exits early when the project registers its own `copilot-hook.sh`. Only claude-copilot itself does that.
- **Codex.** The plugin `codex-copilot@enac-materialized` (plugin version 1.0.0) is a frozen core: `.codex-plugin/plugin.json`, `hooks/hooks.json` and 5 shims. The real logic lives in `templates/central-hooks/` and resolves through the release pointer. Codex trust hashes cover the whole plugin directory, so it must stay byte-identical across releases. A trust gate compares per-hook keys before every flip. There is exactly one marketplace. The cmux wrapper adds `--dangerously-bypass-hook-trust`, so test trust with the plain `codex` binary.
- **Per-project commands.**
  - `cc project init` writes the marker, the thin CLAUDE.md and AGENTS.md sections, and the Codex trust entry.
  - `cc project migrate [--apply | --rollback --manifest F | --scan [--all] [--json] | --source-repo]`. Without `--apply` it is a dry run; there is no `--dry-run` flag.
  - **What migrate removes.** Only files byte-identical to a canonical copy anywhere in framework history, or lock and sync artefacts. Edited copies are held, and the central copy wins at runtime.
  - **Safety.** Migrate checks preconditions first and rolls back on failure. It restores byte-exactly, symlinks included, and honours `COPILOT_HOME` and `CODEX_HOME`.
  - **Source repos.** Migrate never removes release-read source or unique content, and a source repo's own hook registrations count as source (5d6feef0).
- **Retired commands.** `cc reconcile`, `cc update --fanout/--project` and `cc freshness --all-projects` exit 2. Use `cc project migrate --scan --all --json`, `cc release status` and `cc release doctor` instead.

## Repos, branches, commits and tags

Find worktrees with `git -C <repo> worktree list`. Several publish branches live in worktrees, not main checkouts.

| Repo | Branch | Head (latest known) | rc tag in release #11 | Notes |
|---|---|---|---|---|
| claude-copilot | `integration/central-resolution` (worktree `/Volumes/Dev/Sites/CSE/.worktrees/cr-integration`) | e1a975e5 | v5.35.0-rc11 at e1a975e5 | Framework 5.35.0, cc 2.19.0. Includes scan fix 5d6feef0, single hook registration fix 14c123ae, `cc release build` fix 5f533088, docs and changelog e1a975e5. Publish by PR to main (signed commits, CodeQL). |
| claude-copilot acceptance harness | worktree `/Volumes/Dev/Sites/CSE/.worktrees/cr-acceptance` | 2b2aa261 | n/a | `tests/acceptance/central_resolution/run.py` with checks CR-R/A/B/C/D/E/F/G/H. CR-S always runs and can't be passed to `--only`. |
| codex-copilot | `feat/central-resolution` | 0bb68a7 (D5 fix, after the tag) | v0.17.0-rc4 at 8969477 | 0.17.0. Frozen core stays 1.0.0. |
| cli-copilot | `feat/central-resolution` | 39085c8 (D6 fix, after the tag) | v0.3.14-rc3 at 32488d4 | 0.3.14 |
| claude-copilot-internal | worktree, branch `docs/blast-radius-qa` | 6a176b8 | v1.11.11-rc3 at 6a176b8 | blast-radius-qa skill, source migration 9200d1b, test fix 66def9f. Leave the 20 modified framework copies in the main checkout alone. |
| knowledge-copilot-internal | worktree; latest QA reported branch `docs/blast-radius-qa`, earlier reports said `kci-blast-radius-qa` | cb6c9c3e | v1.10.3-rc3 at cb6c9c3e | Leave the main checkout's `.copilot/tasks.db` uncommitted (runtime state). |
| copilot-control-tower | `feat/central-resolution` (worktree `/Volumes/Dev/Sites/CSE/copilot-control-tower-central-resolution`) | 0fd38bb, plus possible uncommitted partial edits (see D7) | stays pinned to the v0.6.11 app record | 0.7.0, build 39 |

All rc tags are signed and local. Final (non-rc) tags have not been created.

### Source repos migrated (signed, local, not pushed)

| Repo | Migration commit | Removed | Held |
|---|---|---|---|
| claude-copilot | 20021a0 (marker only), 5d6feef0 | 0 | 0 |
| codex-copilot | 8969477 (marker only) | 0 | 0 |
| cli-copilot | 7409aa8 | 7 | 23 |
| copilot-control-tower | c0894b5 | 124 | 2 |
| claude-copilot-accounting | a8e30d9, then test fix dc0d3f4 | 26 | 4 |
| claude-copilot-internal | 9200d1b, then test fix 66def9f | 26 | 5 |
| product-creation-copilot | e02a37e | 41 | 14 |
| cli-copilot-accounting | d94a287 | 65 | 30 |
| cli-copilot-internal | 8c4a378 | 149 | 5 |
| cli-copilot-private | c911be3 | 65 | 30 |
| codex-copilot-accounting | 6a5dda9 | 66 | 30 |
| codex-copilot-private | 9f26417 | 66 | 30 |
| codex-copilot-internal | 066a6c6 | 44 | 52 |
| knowledge-copilot-accounting | c912118 | 65 | 30 |
| knowledge-copilot-private | f576e2e | 49 | 46 |
| knowledge-copilot | c8767be | 40 | 50 |
| knowledge-copilot-internal | 1a02f4ed | 43 | 54 |

Partition QA (WP-383, WP-385) confirmed four things: every removal was byte-identical to a canonical copy or a lock or sync artefact, held files are unchanged, scans are clean, and nothing is pushed. No `-public` repos exist on disk.

### Product fleet

- **51 product projects.** These live under `/Volumes/Dev/Sites/COPILOT` and elsewhere. They are migrated and committed locally on their current branches, not pushed. The owner handles those commits separately.
- **h3.** Committed on `feature/pa/fit-and-finish` (latest be5d6004e), 9 commits ahead of origin, not pushed, clean tree.
  - Credential files in `.copilot/launch-plan-110/` are gitignored, not committed.
  - The 221 MB `.copilot/task116-local-recovery/vendor-before-security-patches/` folder is gitignored and still on disk.
- **Docker.** Docker was started for h3's PHP hook check, and h3's Sail containers were stopped afterwards. `convoco-redis-1` and `convoco-postgres-1` came up with Docker and were left running.

## Final QA sweep (single round, complete)

Seven parallel partitions ran against release #11. The reports are work products on TASK-210:

- WP-404: live machine
- WP-405: CR-R/A/B
- WP-406: codex, cli and internal suites
- WP-407: CR-E/F/G/H
- WP-408: CR-C/D
- WP-409: Control Tower and source repos
- WP-410: claude-copilot suites

JSON copies are in the previous session's scratchpad, `/private/tmp/claude-501/-Volumes-Dev-Sites-CSE-claude-copilot/39aeda4b-d7a4-4ebd-8479-6744d8b9ed0f/scratchpad/sweep11/`. `/private/tmp` can be cleared, so rely on the WPs.

What passed:

- every harness check except the CR-S sentinel (D3);
- release and cc doctor;
- live links;
- Claude hooks firing exactly once, in a migrated project and in claude-copilot;
- `cc project init` in 0.35 s;
- the cc suite (2512 passed) and the hook tests;
- version consistency;
- signed commits (72 on the claude-copilot branch);
- docs and mergeability;
- the internal repos;
- source repo and Control Tower signing and merge checks.

## Defect list and fix status

| ID | Defect | Where | Status |
|---|---|---|---|
| D1 | `~/.codex/config.toml` trusts only 5 of the 6 codex-copilot hooks: `pre_tool_use:1:0` under `enac-materialized` has no trust entry. Stale trust entries remain for the retired `codex-copilot-local` and `codex-copilot-project` marketplaces. A headless `codex exec` in convoco showed no hook events. | Real machine Codex config, possibly cc trust-write code | **Interrupted; check this first.** The agent's last message was that it had removed only the 13 stale entries and was about to verify. It is unknown whether it added the missing 6th entry or changed cc code. It was told to make a timestamped `.bak-` copy beside `~/.codex/config.toml` first. Older backups: `~/.codex/config.toml.bak-task195-20261106-112518` and `~/.codex/config.toml.bak-task195-trustwrite-20261106T174646`. |
| D2 | `cc project migrate --scan --all --json` from the integration-worktree cc reports 15 of 52 projects not clean, with 356 copied framework files, mostly under `plugins/codex-copilot-internal`. The worst are insights-copilot (93), convoco-creative-studio (54), convoco (47) and convoco-site (39). An earlier scan with a different cc build reported 51 of 51 clean. | Product projects | **Not started.** The agent was only categorising paths, read-only. First decide whether these are real framework copies that the release now provides, or false positives such as a company-tier plugin a project vendors on purpose. Fix the classifier for false positives. Migrate real copies under the normal guard, and check each project's `.git/hooks` for auto-push before committing. |
| D3 | The harness sentinel CR-S fails because it hashes convoco's `.claude/hooks/state/` (for example `session-turns.json`), which any Claude session in that project rewrites. | Acceptance harness | **Not started.** Exclude gitignored runtime hook state from the "framework files" sentinel; it must still catch real framework-file changes. Fix it wherever the harness runs from and keep the integration copy consistent. |
| D4 | The release `links-receipt.json` records 790 links but `links.json` has 793. The 3 owner items that were correctly kept (`.claude/skills/infographics`, `.codex/skills/infographics`, `.codex/skills/data-visualization`) appear in neither `kept` nor `personal_overrides`. | claude-copilot cc link adoption | **Not started.** Record them in `kept` with a reason and add a unit test. The owner keeps four user-level items: `infographics`, `synced` and two Codex skills. |
| D5 | A codex-copilot ADR linked to a claude-copilot file that doesn't exist. | codex-copilot | **Fixed** in 0bb68a7. The link now points at claude-copilot `blob/main` and resolves once claude-copilot's PR merges. |
| D6 | cli-copilot `ruff format --check` failed on `copilot_cli/launcher_install.py`. | cli-copilot | **Fixed** in 39085c8. |
| D7 | Control Tower called the retired `cc freshness --all-projects` from the tray refresh, and the `reconcile` wrappers in `native/cli-client.swift` (around lines 1040–1058) still call retired verbs. | Control Tower worktree | **Partly fixed.** 0fd38bb moves the tray to `projectScan()`, surfaces the retired exit as `retiredNotice`, removes the dead `freshness()` code and extends `scripts/tests/test_native_invariants.sh`. The reconcile-wrapper removal was **interrupted mid-edit**. Check `git status` and `git diff`, then finish or discard. Extend the invariants test to fail on any native `reconcile` call, and grep `native/` for `freshness\|reconcile\|update --fanout\|update --project`. |
| D8 | Two tc tests check files this branch retired: `test_claude_flag_existence.py` expects the old `orchestrate.md` (now a redirect), and `test_qa_fitness_functions.py::test_ff4...[SKILL.md]` expects `plugins/codex-copilot/skills/qa/SKILL.md` (removed). | claude-copilot `tools/tc` | **Not started.** The owner-requested change made these obsolete. Point them at the canonical release location without dropping coverage, and record the old and new expectations in the WP. |
| D9 | `scripts/check-no-hardcoded-paths.sh` exits 1 on five new files, which would fail the `no-hardcoded-paths.yml` CI: `tests/acceptance/central_resolution/replica.py`, `tests/acceptance/central_resolution/run.py`, `tests/hooks/test-session-start-registration.sh`, `tools/cc/tests/project_migrate/test_source_guard.py` and `tools/cc/tests/release_codex/fixtures/hooks_list_live_codex_0.167.0.json`. | claude-copilot | **Not started.** Remove the machine paths. Use the checker's allowlist only for fixture data that genuinely records a real path. Don't weaken the checker. |
| D10 | Four `test_skill_frontmatter.py` failures in the root tests. QA believes they are environmental (this machine's knowledge skills don't match their signed release) but did not check against origin/main. | claude-copilot | **Not started.** Run the tests on origin/main. If they fail there, record them as pre-existing with evidence; otherwise fix them. |

Known pre-existing issues (out of scope):

- In codex-copilot-internal, `test_guard_fails_on_an_untracked_file_and_a_tracked_edit` fails because `plugins/codex-copilot/skills/sd/SKILL.md` is mode 0444.
- In knowledge-copilot-internal, `check-crosslinks.py` reports 27 broken links (unchanged).
- `.claude/agents/kc.md` is a dangling link in the knowledge-copilot-internal worktree.
- Control Tower's vendored `packaging/cc` is still 2.12.7 while `controltower.compat.json` requires 2.19.0, so two vendored-cc gate scripts fail. The post-push CI build below fixes this.

## Remaining work, in order

1. **Recover the interrupted state.** See "Verified state at handoff" below. For D1, check the trust count from a fresh `codex` process (a long-running app-server gives stale answers), find the backup, and diff against the latest backup. For D7, run `git status` and `git diff` in the Control Tower worktree.
2. **Fix D1–D4 and D7–D10.**
   - Split agents by write ownership: claude-copilot (D3, D4, D8, D9, D10), Codex config (D1), fleet (D2) and Control Tower (D7).
   - Commits must be signed and scoped, end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, and stay unpushed.
3. **Retest only those defects.**
   - D1: all 6 hooks trusted, and hooks fire under plain `codex`.
   - D2: scan clean for the touched projects.
   - D3: CR-S passes and still fails on a real framework-file change.
   - D4: the receipt accounts for all 793.
   - D7: the invariants test passes and the grep is clean.
   - D8 and D10: the specific tests.
   - D9: `scripts/check-no-hardcoded-paths.sh`.
4. **Build release #12 and flip.** D3, D4, D8, D9, and D1 if it touched cc code, all change release content.
   - Create the next signed rc tags: claude-copilot v5.35.0-rc12, codex-copilot v0.17.0-rc5 (picks up 0bb68a7), cli-copilot v0.3.14-rc4 (39085c8), and any internal repo that changed.
   - Run `cc release build` from the integration-worktree source (`tools/cc`, `PYTHONPATH=src`). It is now fixed; don't call `build_release` directly.
   - Run `cc release flip`. The trust gate must pass and the Codex core must be byte-identical.
5. **Publish.** This runs under the owner's standing approval and the canonical "Publishing: finish the release" section in `/Volumes/Dev/Sites/CSE/knowledge-copilot-internal/03-ai-enabling/03-operations/09-research-strategy-capabilities.md`. Read `docs/30-operations/20-notarization-credentials.md` first.
   - **Pushes and PRs:**
     - claude-copilot `integration/central-resolution` to main through the PR workflow;
     - codex-copilot, cli-copilot and Control Tower `feat/central-resolution`;
     - the claude-copilot-internal and knowledge-copilot-internal publish branches;
     - the 13 source-repo migration commits, each through its repo's normal workflow.
   - **Final signed tags:** v5.35.0, v0.17.0, v0.3.14, v1.11.11, v1.10.3, and Control Tower 0.7.0 (build 39).
   - **Notarized builds by CI.** Local notarization fails with HTTP 401 on the `ct-notary` profile; the owner re-entered credentials for pablitoalejo@gmail.com with team 3SYGVX2HB8 and still got 401. The owner chose **option 2: let CI produce the signed and notarized cc and Control Tower builds after the push.** Control Tower CI uses App Store Connect API key secrets (`APPLE_NOTARY_KEY_ID`, `APPLE_NOTARY_KEY_ISSUER`, `APPLE_NOTARY_KEY`). The cc packaging script also requires the source commit to be on origin.
   - **After CI:** once CI produces the notarized cc 2.19.0, refresh Control Tower's `packaging/cc` and rerun its vendored-cc gate.
   - **Do not push** the 51 migrated product projects.
6. **Close out.**
   - Run the organization task-closeout skill (`cc skill get task-closeout --scope machine --json`) over PRD-16, including parked tasks 213–225.
   - Retire eligible merged worktrees only after their branches merge, under the owner's merged-worktree exception: internal-blast-radius-qa, kci-blast-radius-qa, the cr-* holds and cr-adr-doc-codex. See WP-388 for disposition.
   - Get exact owner approval for any other deletion: about 3.5 GB of snapshots, `.claude/worktrees/embed-codex-0.16.8` (merged, but with 27 dirty files), and stale mirrors and backups under `~/.copilot-backups/` and `~/.copilot/rollback/`.
7. **Final summary to the owner.** Include the Control Tower section below and the notes on h3, voice-copilot and holds.

## Open owner decisions

- **voice-copilot auto-push.** Its own untracked `.git/hooks/post-commit` runs `git push origin HEAD`, so migration commit 8a3668a is already on origin/main. The owner must decide whether to keep the hook or disable it for framework migrations. This is pending (WP-389) and blocks the TASK-209 PUSH-POLICY criterion. Undoing the push needs a force-push, so don't do it without explicit approval.
- **Deletions** listed in step 6.
- **Notarization** is decided (option 2, CI). Revisit only if CI can't notarize.

## Task tracking (`tc`, claude-copilot project)

- **TASK-209** (fleet and source-repo migration) and **TASK-210** (final acceptance and publish) are both in QA **rework**. The rejections were recorded deliberately (WP-402 and WP-401) so build work could continue.
  - **TASK-209:** BOTH, SCAN-ZERO and EXCLUSIONS are met. Its contract was re-registered as schemaVersion 3 with `externalSources` (repo id `claude-copilot`) so `tc task evidence-identity 209` works. Supporting WPs: the holds table WP-387 (32 rows), lifecycle WP-388 and PUSH-POLICY WP-389.
  - **TASK-210:** its 10 criteria are DONE, WORK-LIFECYCLE, INIT-TIMED, TEST-RELEASE, NO-RETRUST, ROLLBACK, ZERO-COPY, GUARD-LIVE, PRECEDENCE and SUITES.
- **Parked:** TASK-213 to TASK-225. They include TASK-224 (tc cycle claim with a non-git plan root) and TASK-225 (integrated event can't be recorded after re-signing). The task QA gates take precedence over tc cycle bookkeeping.
- **Useful WPs:**
  - 375: h3
  - 376–378: hook fix QA
  - 383 and 385: source QA
  - 386: TASK-209 rejection detail
  - 390: release #10
  - 396: build fix and notarization blocker
  - 403: release #11
  - 404–410: final sweep
  - 1133: D7 part 1

## Things that will trip you up

- **Coordinator hook.** In claude-copilot, the main session may only coordinate. Compound bash and most reads are blocked, so work through agents.
- **QA gate.** After any `@agent-me` stop with a `Task: TASK-N | WP:` header, every other agent type, and even main-session writes, is blocked until `@agent-qa` approves. A well-formed `VERDICT: REJECTED` also unblocks by putting the task into rework, which allows only `me` and `qa`.
  - The hook reads only the first `Task:` header, so use one task per QA message.
  - `tc task check-qa <id>` approves only when the evidence covers exactly all of that task's criterion IDs.
  - Don't set `COPILOT_QA_GATE=off`; that is a bypass.
  - Don't record a narrow fix against an umbrella task. That deadlocked the previous session.
- **Use the integration-worktree cc.** That is `/Volumes/Dev/Sites/CSE/.worktrees/cr-integration/tools/cc` with `PYTHONPATH=src`. The installed cc predates the fixes.
- **Sandbox every test that writes.** Point `COPILOT_HOME` and `CODEX_HOME` at a sandbox; a past QA run moved the real release pointer.
- **Codex trust.** Never touch the frozen Codex plugin core, and read trust state from a fresh `codex` process.
- **Background agents.** Don't let them run unchecked; the previous session lost about 9 hours to one serial agent. Give each agent a narrow scope, a stall rule (stop after about 10 minutes with no output) and parallel siblings.
- **Auto-push hooks.** Before committing in any project, check `.git/hooks` for auto-push.
- **Owner reporting style.** Lead with the result and say plainly whether it works. Don't relay agent reports or narrate progress. Every decision request starts with `DECISION NEEDED:`. No time estimates.

## Control Tower changes (for the owner summary)

- The retired `reconcile` and `update --fanout|--project` calls are replaced with `cc project migrate --scan --all --json`, `cc release status` and `cc release doctor`.
- The tray refresh no longer calls the retired `cc freshness`.
- The retired-command exit (code 2) shows as a plain UI message.
- The release gates are rewritten for central resolution.
- The source pass removed 124 synced framework copies and held 2.
- The version is 0.7.0, build 39, and `controltower.compat.json` requires cc 2.19.0.
- Pending: finish the D7 reconcile-wrapper cleanup, then vendor the CI-notarized cc 2.19.0 into `packaging/cc` and produce the notarized app from CI.

## Verified state at handoff

Read-only checks run after the previous session ended. Trust was read from `~/.codex/config.toml` (modified 7 Nov 06:40:54), not from a fresh `codex` process, so hook firing under plain `codex` is still unverified.

- **D1:** Nine `~/.codex/config.toml.bak-*` files exist (six `bak-release-*`, `bak-task195-20261106-112518`, `bak-task195-trustwrite-20261106T174646` and `bak-task210-20261107T064054`). The newest is `config.toml.bak-task210-20261107T064054` (the D1 agent's pre-edit backup; its file mtime is 6 Nov 20:05 because the copy preserved the source time, the same as `bak-release-20261107T114054815694Z`). `config.toml` now has 6 of 6 `codex-copilot@enac-materialized` hook trust entries, including `pre_tool_use:1:0`, and 0 `codex-copilot-local` or `codex-copilot-project` entries remain. The D1 config fix looks complete; confirm against a fresh `codex` process and diff against the `task210` backup. Whether cc code changed is not known from this check. The cr-integration worktree is clean (no uncommitted changes) and has three new commits after e1a975e5: 6439a628 (CR-S ignores gitignored runtime state, D3), c74a708d (hardcoded machine paths removed, D9) and 0995f609 (tc tests follow the retired orchestrate and codex qa skill, D8). These are beyond the rc11 tag, so D3, D8 and D9 are committed but untested.
- **D7:** The Control Tower worktree head is still 0fd38bb and has uncommitted partial edits: modified `native/cli-client.swift` (280 lines changed), `native/cli-dtos.swift` (1006 lines removed), `native/wizard.swift` (2226 lines changed), `scripts/tests/fixtures/smoke-cli/main.swift`, `scripts/tests/test_native_invariants.sh` and `scripts/tests/test_walkthrough_05_08_acceptance.sh`, plus 22 staged deletions (the `scripts/tests/fixtures/reconciliation/` fixtures and `test_reconciliation_contract.sh`, `test_reconciliation_wizard.sh`). Total 6 modified files, about 50 insertions and 3487 deletions. Yes, the D7 reconcile-wrapper removal is part-done and uncommitted; it has not been built or tested, so run the Swift build and invariants test before committing or discarding.
- **D2:** `git status --short` is empty in insights-copilot, convoco-creative-studio, convoco and convoco-site (all under `/Volumes/Dev/Sites/COPILOT`; ECOSYSTEM.md lists an older `/Users/pabs/Sites/COPILOT` path). Nothing was half-applied; the 15 not-clean scan results are still unresolved.
- **Release pointer:** `readlink ~/.copilot/current` returns `releases/20261107T111725Z-e1a975e57fbb`, as expected (release #11).
