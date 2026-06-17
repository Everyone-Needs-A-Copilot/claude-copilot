---
id: 70ddc4d4-d5d0-40f2-b73d-daebf8ddebcb
type: decision
tags: []
created: 2026-06-08T19:50:41Z
updated: 2026-06-08T19:50:41Z
scope: project
---

Live Docs (PRD-5, cc docs CLI) wired into framework as a shared agent behavior (TASK-105/Z1, WP-115). Added 'Live Docs — Verify upstream APIs before coding' bullet to CLAUDE.md > Agent Shared Behaviors (after Skill Discovery); added one-line cc-docs pointers to me.md and ta.md Workflow step 5. Trigger: before coding/planning against a third-party library/framework API where correctness depends on the INSTALLED version — use 'cc docs get <pkg>' instead of trusting training-data memory. Properties: version-exact, local-first/offline-safe, network fetch only with optional httpx extra. README cc-docs section deliberately NOT added (owned by impl streams B/C; HEAD README has no docs section) — flagged for doc-review.
