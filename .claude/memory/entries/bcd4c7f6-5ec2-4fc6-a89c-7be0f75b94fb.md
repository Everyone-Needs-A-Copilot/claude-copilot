---
id: bcd4c7f6-5ec2-4fc6-a89c-7be0f75b94fb
type: decision
tags: []
created: 2026-06-29T18:13:32Z
updated: 2026-06-29T18:13:32Z
scope: project
---

Discord handoff re-arm moved from AI prompt (global CLAUDE.md) into cli-copilot via a Claude Code Stop hook. Stop-hook contract CONFIRMED: {"decision":"block","reason":...} blocks stop and injects reason as next turn input. New: copilot discord stop-hook subcommand (loop brain) + thin Claude shim; await flag on handoff registry record keyed by cwd; bounded 30m wait then graceful RELEASE; escape hatches COPILOT_DISCORD_LOOP/SAFETY=off, /return token. Spec: tc TASK-148 / PRD-10 / WP-168 (technical-design). Routes to @agent-me.
