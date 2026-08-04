# Framework 5.12.0 — Doc Follow-ups for cli-copilot & shared-docs

# Instruction Set: cli-copilot + shared-docs Doc Updates (Framework 5.12.0)

**Purpose:** Copy-pasteable handoff for the two repos not touched by the claude-copilot PR docs/initiative-5.12.0. Apply these after that PR merges.

---

## REPO 1: cli-copilot README

**File:** README.md (root of cli-copilot repo)
**What is missing:** Only legacy commands handoff/notify/listen are shown. Missing: install-hook, handoff --await, stop-hook, discord close. COPILOT_DISCORD_LOOP=off escape absent. Away-mode flow not described.

### Draft replacement for the Discord section

Add or replace the discord command docs block with:

#### discord

Bounded async handoff for away-mode workflows. install-hook registers a Claude Code Stop hook so Claude re-arms automatically when you reply from Discord.

**Install the Stop hook (once per machine):**

    copilot discord install-hook

Writes a StopHook entry to ~/.claude/settings.json. Run once; persists across sessions.

**Start an away-mode handoff:**

    # Classic (manual re-arm -- you run /continue yourself)
    copilot discord handoff "Working on auth refactor." --title "Auth session" --harness claude

    # Bounded auto-rearm (requires Stop hook)
    copilot discord handoff "Reply here to continue." --title "Auth session" --harness claude --await

--await blocks until a Discord reply arrives, then passes the reply as Claude next prompt.

**Other commands:**

    copilot discord notify "Done. Reply here with what you want next." --thread-id <thread_id>
    copilot discord listen <thread_id>   # event-driven; preferred over wait
    copilot discord close <thread_id>    # mark thread resolved
    copilot discord stop-hook --remove   # deregister Stop hook

**Disable re-arm loop without removing hook:**

    export COPILOT_DISCORD_LOOP=off

**Away-mode end-to-end flow:**
1. Run `discord install-hook` once.
2. Run `discord handoff --await`.
3. Step away. Claude works, posts progress with `discord notify`.
4. When Claude stops, Stop hook fires; Discord notified automatically.
5. Reply from Discord. Stop hook picks up reply; Claude re-arms.
6. No manual /continue needed.

### Table rows to add to Available Commands or Services table

| discord install-hook | Register Claude Code Stop hook for auto re-arm |
| discord handoff [--await] | Start away-mode session; --await blocks for reply |
| discord notify | Send one-off message to active thread |
| discord listen | Block until reply arrives (event-driven) |
| discord stop-hook [--remove] | Manage Stop hook registration |
| discord close | Close/resolve a Discord thread |

---

## REPO 2: shared-docs -- claude-copilot product card

**File:** 02-products/02-foundational/claude-copilot/00-overview.md

**Edit 1:** Change version line from "Framework version 5.11.0" to "Framework version 5.12.0"

**Edit 2:** In the cc integration surface list, append:
  - cc eval -- cross-version regression harness; golden cases in .claude/evals/<agent>/*.yaml; scores persist to cc memory; CI gate on VERSION.json bumps (cc 1.6.0)

**Edit 3:** In the tc integration surface list, append:
  - --max-budget-usd <float> on tc task create/claim -- per-task cost cap (stored in metadata; enforcement is roadmap P1) (tc 1.3.0)
  - tc worker run <task_id> -- dispatch surface; respects budget cap when enforcement lands

---

## REPO 2: shared-docs -- cli-copilot product card

**File:** 02-products/02-foundational/cli-copilot/00-overview.md

**Edit 1:** Change version line from "Version 1.1.0" to "Version 1.2.0"

**Edit 2:** Replace existing Discord commands list with (cli-copilot 1.2.0):
  - discord install-hook -- register Claude Code Stop hook for auto re-arm loop
  - discord handoff [--await] -- start away-mode session; --await blocks for Discord reply
  - discord notify -- send one-off message to active thread
  - discord listen <thread_id> -- event-driven block until reply arrives
  - discord stop-hook [--remove] -- manage Stop hook registration
  - discord close <thread_id> -- close/resolve thread
  - COPILOT_DISCORD_LOOP=off -- env escape to disable re-arm without removing hook

**Edit 3:** Add architecture note under Discord section:
  Architecture (1.2.0): The re-arm loop is owned by a registered Claude Code Stop hook
  (install-hook), not by a CLAUDE.md behavioral instruction. The Stop hook fires when Claude
  stops responding, picks up the next Discord reply, and re-arms the session automatically.
  CLAUDE.md describes the behavior; install-hook is the runtime mechanism.

---

## Summary

| Repo | File | Changes |
|------|------|---------|
| cli-copilot | README.md | 6 new Discord commands, away-mode flow, COPILOT_DISCORD_LOOP=off |
| shared-docs | 02-products/02-foundational/claude-copilot/00-overview.md | Bump 5.12.0; add cc eval, --max-budget-usd, tc worker |
| shared-docs | 02-products/02-foundational/cli-copilot/00-overview.md | Bump 1.2.0; replace Discord list; add Stop hook arch note |
