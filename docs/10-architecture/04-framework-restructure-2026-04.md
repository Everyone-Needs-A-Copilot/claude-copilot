# Framework Restructure — April 2026

**Diátaxis mode:** Explanation + Reference

This document explains why the framework was restructured in April 2026, what changed in each pillar, and how to use the new features. Future sessions can use this to understand why the framework works the way it does.

---

## Why the Restructure Happened

### The Diagnostic

A cross-session diagnostic covered 15 sessions from Apr 17–22 2026 (18.3 MB of session data). Three systemic failures surfaced with concrete numbers:

**1. Delegation was not happening (94% main-session work)**

The framework was designed so specialists do the work. In practice, the main session did 94% of all tool calls itself. Delegation rate: 6%. Protocol declarations appeared in only 3.5% of assistant turns — the framework was defined in CLAUDE.md but not enforced anywhere.

Root cause: a 14-agent roster created choice paralysis. Users avoided routing to agents when the cost of choosing wrong felt higher than just doing it inline.

**2. Deploy polling was done manually (57 Bash calls in one incident)**

A 5-day staging saga (4 sessions, 12 MB, 26 polling loops) showed what happens without a deploy-wait primitive. The worst session (Apr 19 PM) had 15 polling loops, 19 long bash runs, and zero protocol declarations. The pattern was: write `until curl ...; do sleep 5; done`, run it, fail, repeat. No first-class `tc` command existed for this.

**3. Sessions grew without bound (22-hour sessions observed)**

Average session metrics before the restructure: 671 turns/session, 452 bash calls/session. Without a session-length signal, `/continue` accumulated context indefinitely. "Run free until done" prompt patterns made this worse — the model would execute dozens of tool calls before checking in.

**4. Model tier was inverted**

The orchestrator (main session) ran on Opus 4.7. Specialist agents ran on Sonnet. But 94% of tool calls were in the main session — meaning the expensive model was doing the cheap, repetitive work (Bash polling, file reading, etc.), not the high-value architectural decisions it's suited for.

### The Three Root Causes

| Root Cause | Evidence | Fix |
|------------|---------|-----|
| Roster too large → choice paralysis → 6% delegation | 94% main-session tool calls (diagnostic: 15 sessions) | Roster 14 → 8; merged uxd/uids/uid → design |
| No deploy-wait primitive → manual polling | 57 bash polling calls, 26 loops/week (diagnostic) | `tc deploy wait` + Flow E |
| No enforcement → advisory ignored | 3.5% protocol declaration rate (diagnostic) | Hook-based mechanical enforcement |

---

## What Changed Per Pillar

### Agents (Pillar 2) — Roster Consolidation

**Before:** 14 standalone agents (ta, me, qa, sec, doc, do, sd, uxd, uids, uid, cw, cco, cs, cpa, kc)

**After:** 8 active agents + 1 setup utility + archived specialists-as-skills

| Active Agents | Role |
|--------------|------|
| `ta` | Architecture, ADR, fitness functions |
| `me` | Implementation (Kent Beck / TDD) |
| `qa` | Testing, validation (Meszaros) |
| `do` | DevOps, infra, deploy (12-Factor / SRE) |
| `sd` | Service design, discovery (IDEO) |
| `design` | UX interaction + visual design + component implementation (merged uxd + uids + uid) |
| `doc` | Documentation (Diátaxis) |
| `kc` | Knowledge repo setup utility |

**Archived agents (demoted to skills or removed):**

| Archived | Replacement |
|----------|-------------|
| `sec` | `@include .claude/skills/security/stride-dread/SKILL.md` |
| `cw` | `@include .claude/skills/voice-tone/SKILL.md` |
| `cco` | `@include .claude/skills/litmus-test/SKILL.md` |
| `uxd`, `uids`, `uid` | Merged into `@agent-design` |
| `cs`, `cpa` | Archived; re-introduce as skills if needed |

**Rationale:** Separate uxd/uids/uid created three hand-off steps for what is one creative act. Security, copywriting, and creative direction are better as loaded skills that augment any agent than as standalone routing targets. The 14-agent roster was causing choice paralysis and underuse.

---

### Task Copilot (Pillar 4) — Deploy Wait Primitive

**New command:** `tc deploy wait`

```bash
tc deploy wait <app-uuid>                            # wait for deploy to complete
tc deploy wait <app-uuid> --test <spec-path>         # wait + run post-deploy tests
tc deploy wait <app-uuid> --timeout 300              # custom timeout (seconds)
```

**Calls the `copilot` CLI** from the cli-copilot project. If `copilot` is not on PATH, exits with code 4 and a clear error. Does not hang.

**Why this matters:** The April staging incident used 57 manual `Bash` polling loops (`until curl ... ; do sleep 5; done`) to track deploy status. `tc deploy wait` wraps this in a single blocking call that `@agent-do` and `@agent-qa` can use directly. See `ADR-004` (stored as WP-6) for architecture decision.

**Dependency:** Optional. Only needed if you use Flow E (Infrastructure) or call `tc deploy wait` directly. See [SETUP.md](../../SETUP.md#external-dependencies) for installation.

---

### Protocol (Pillar 5) — Infra Flow (Flow E)

The protocol command now recognizes infrastructure-specific keywords and routes directly to `@agent-do` (DevOps) rather than the technical flow.

**Trigger keywords:** deploy, staging, production, docker, kubernetes, ci/cd, infra, terraform, migration

**Flow E routing:**

```
/protocol deploy to staging
  → @agent-do   (plan + execute infra changes)
  → @agent-me   (any required code changes)
  → @agent-qa   (verify via tc deploy wait or health checks)
```

**Keyword precedence:** If both infra keywords and technical keywords (refactor, optimize) are present, Flow E takes precedence. Pure technical keywords without infra context still route to Flow C (Technical).

---

### Hooks (Cross-Cutting) — Mechanical Enforcement

The hook system was extended from advisory (SessionStart injection) to mechanical enforcement of the three main guardrails.

**Hook architecture:**

| Hook | File | Event | What it enforces |
|------|------|-------|-----------------|
| Force-delegate | `pretool-check.sh` | PreToolUse | Blocks >5 consecutive same-tool calls; suggests delegation |
| QA gate | `pretool-check.sh` + `subagent-stop.sh` | PreToolUse + SubagentStop | Gates main session until @agent-qa approves after @agent-me |
| Session cap | `user-prompt-submit.sh` | UserPromptSubmit | Advisory at 500 and 750 turns |

**Dispatcher pattern:** `pretool-check.sh` is a single dispatcher that runs multiple rule functions in priority order. Adding a new enforcement rule means adding a `rule_<name>()` function — no new hook registration needed.

**QA gate retry logic:** After 3 consecutive QA failures, the gate auto-unblocks and emits a human-review advisory. This prevents permanent lock-out on flaky tests.

**State files** (`.claude/hooks/state/`, gitignored):
- `streak-<session_id>.json` — consecutive tool call counter
- `qa-gate.json` — pending tasks and QA retry state
- `session-turns.json` — turn count per session

**Escape hatches:**

```bash
export COPILOT_FORCE_DELEGATE=off   # disable force-delegate for this shell
export COPILOT_QA_GATE=off          # disable QA gate for this shell
export COPILOT_SESSION_CAP=off      # disable session-cap advisories
```

---

### Model Pinning (Launcher) — Per-Project Default Model

The project-local launcher allows teams to pin a default model for every Claude Code session.

**Files:**
- `.claude/.model` — plain text, e.g. `claude-sonnet-4-6[1m]`. Committed to the repo so all team members share the same default.
- `.claude/claude-launcher` — executable wrapper. Run instead of `claude`.

```bash
.claude/claude-launcher                              # uses .claude/.model
CLAUDE_MODEL=claude-opus-4-5 .claude/claude-launcher # env var overrides file
```

A multi-line-content bugfix was applied in the R0.3 follow-up: the launcher now strips trailing whitespace and newlines from `.model` before passing to `--model`, preventing `claude: unknown model` errors when editors append a trailing newline.

---

## Before vs After — Concrete Changes

| Metric | Before (diagnostic) | After |
|--------|--------------------|----|
| Deploy polling | 26 manual loops/week, 57 bash calls in one incident | `tc deploy wait` — one blocking call |
| Session length | 671 turns/session average, 22-hour sessions | Advisory at 500 turns; cap signal at 750 |
| Delegation rate | 6% (94% main-session) | Hook blocks after 5 consecutive same-tool calls |
| QA gate | Advisory (CLAUDE.md text) | Mechanically enforced — tools blocked until @agent-qa passes |
| Agent roster | 14 agents | 8 agents (~800-1200 tokens/turn removed from prompt) |
| Model cost | Opus 4.7 for 94% of tool calls | Sonnet for ~94% of work; Opus reserved for design/architecture |
| Bash polling pattern | `until curl ...; do sleep 5; done` (repeated manually) | `tc deploy wait <app-uuid>` |

**The QA gate change is the highest-leverage fix.** Before, @agent-me could complete and the session could move on without ever running tests. The gate makes this structurally impossible — not policy-impossible.

**The roster change reduces per-turn token cost mechanically.** Every agent description that appears in a prompt costs tokens. 14 → 8 agents removes 800-1200 tokens from every assisted turn, compounding across a session.

---

## How to Use the New Features

### Deploy and Infrastructure Work (previously ad-hoc, now Flow E)

The staging saga that triggered this restructure was largely unstructured — bash polling loops invented in-session. The fix is a dedicated flow and a blocking primitive.

**Trigger Flow E:**

```
/protocol deploy to staging
/protocol set up staging for X
/protocol fix the production deployment
```

Any request containing: deploy, staging, production, docker, kubernetes, ci/cd, infra, terraform, migration.

**Flow E routing:**

```
/protocol deploy to staging
  → @agent-do   (plan + execute infra changes)
  → @agent-me   (any required code changes)
  → @agent-qa   (verify via tc deploy wait or health checks)
```

**Replace polling loops with `tc deploy wait`:**

```bash
# Old pattern (what caused the 5-day saga)
until curl -s https://staging.example.com/health | grep -q '"ok"'; do
  sleep 5
done

# New pattern
tc deploy wait <app-uuid>
tc deploy wait <app-uuid> --test tests/e2e/staging.spec.ts   # wait + run tests
tc deploy wait <app-uuid> --timeout 300                       # custom timeout (seconds)
```

`tc deploy wait` is a single blocking call. It wraps the `copilot` CLI (from cli-copilot). If `copilot` is not on PATH, it exits with code 4 and a clear error — it does not hang. See [SETUP.md](../../SETUP.md#external-dependencies) for installation.

---

### Feature Development (unchanged routing, updated agent names)

```
/protocol add <feature>
```

Routes: sd → design → ta → me → qa

Note: `@agent-uxd`, `@agent-uids`, and `@agent-uid` are archived. All three steps now invoke `@agent-design`.

---

### Bug Fixes (QA gate now mechanically enforced)

```
/protocol fix <issue>
```

Routes: qa → me → qa

The QA gate after @agent-me is now mechanically enforced by a hook. @agent-me cannot be the final step — the main session's tools are blocked until @agent-qa runs and provides a pass verdict.

After 3 consecutive QA failures, the gate auto-unblocks and emits a human-review advisory (prevents permanent lock-out on flaky tests).

---

### What the Hooks Do Automatically

You do not need to invoke these — they run on every tool call via Claude Code's hook system:

| Hook | Trigger | What Happens |
|------|---------|-------------|
| Force-delegate | 5 consecutive Bash/Read/Edit calls | PreToolUse blocks; message tells you to delegate |
| QA gate | @agent-me SubagentStop | Main session tools gated until @agent-qa passes |
| Session cap | 500+ turns (UserPromptSubmit) | Advisory to pause and start a fresh session |

**Escape hatches** (when you genuinely need to bypass):

```bash
export COPILOT_FORCE_DELEGATE=off   # disable force-delegate for this shell
export COPILOT_QA_GATE=off          # disable QA gate for this shell
export COPILOT_SESSION_CAP=off      # disable session-cap advisories
```

---

### Running on Sonnet by Default (Model Pinning)

The model tier inversion (Opus doing cheap work) is fixed by pinning the main session to Sonnet. The launcher reads `.claude/.model` (committed to the repo) so all team members share the same default.

```bash
# Use the launcher instead of claude directly
.claude/claude-launcher

# Override per-session
CLAUDE_MODEL=claude-opus-4-5 .claude/claude-launcher
```

The default is `claude-sonnet-4-6[1m]`. This runs Sonnet for orchestration (routing, summarizing, delegating) and reserves Opus for agents that need it (design, architecture). Net effect: ~94% of tool calls run on the cheaper, faster model.

---

### Security, Copy, and Creative Direction (now skills, not agents)

These were standalone agents. They are now `@include` skills that augment any agent:

```bash
@include .claude/skills/security/stride-dread/SKILL.md   # STRIDE/DREAD threat modeling
@include .claude/skills/voice-tone/SKILL.md              # MailChimp Voice & Tone
@include .claude/skills/litmus-test/SKILL.md             # Creative direction
```

Load them at the start of any agent session that needs them, or include them inline in a prompt. No routing hop required.

---

## Migration Notes

**Coming from pre-restructure (before April 2026):**

| If you were using | Now use |
|-------------------|---------|
| `@agent-uxd` | `@agent-design` |
| `@agent-uids` | `@agent-design` |
| `@agent-uid` | `@agent-design` |
| `@agent-sec` | `@include .claude/skills/security/stride-dread/SKILL.md` |
| `@agent-cw` | `@include .claude/skills/voice-tone/SKILL.md` |
| `@agent-cco` | `@include .claude/skills/litmus-test/SKILL.md` |
| Manual `curl` polling loops for deploy | `tc deploy wait <app-uuid>` |
| `claude` directly | `.claude/claude-launcher` (recommended for pinned model) |

**Project files to update if migrating:**
1. Any `CLAUDE.md` that references the old 14-agent list — update the "Framework agents:" line
2. Any `/protocol` workflows that explicitly route to `uxd`, `uids`, or `uid`
3. Any shell scripts that call `claude` directly — swap to `.claude/claude-launcher`

**Archived agent files** remain in `.claude/agents/_archive/` with deprecation banners. Content is preserved for reference.

---

## Hook Enforcement Model — Mandatory vs Advisory

| Guardrail | Pre-April 2026 | Post-April 2026 |
|-----------|---------------|----------------|
| Don't write code in main session | Advisory (CLAUDE.md text) | Mandatory (force-delegate hook, exit 2) |
| QA after every @agent-me | Advisory (CLAUDE.md text) | Mandatory (QA gate, blocks all tools) |
| Don't run >N consecutive same-tool calls | Not enforced | Mandatory (force-delegate, N=5) |
| Keep sessions under 500 turns | Not enforced | Advisory (session cap, systemMessage) |
| Don't use Explore/Plan agents | Advisory | Advisory |

The shift from advisory to mandatory for the two highest-impact guardrails (implementation delegation and QA gate) is what closes the 94%/6% delegation-rate gap. The hooks cannot be silently bypassed — they require an explicit env var override.

---

## Related Documents

- [SETUP.md — External Dependencies](../../SETUP.md#external-dependencies) — `copilot` CLI installation
- [SETUP.md — Model Pinning](../../SETUP.md#per-project-main-session-model-pinning) — launcher setup
- [Hooks README](../../.claude/hooks/README.md) — full hook reference
- [Agents](01-agents.md) — current agent roster
- [Architecture Overview](00-overview.md) — system overview
