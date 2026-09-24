# Aviator — Integration, State, Security & Observability Design

| | |
|---|---|
| **Component** | Aviator — Tauri v2 macOS menu-bar agent |
| **Role** | FACE + SUPERVISOR over the `copilot`/`cc` CLI. Never a second brain. |
| **Branch** | `ecosystem-extensions` |
| **Depends on** | `04-ecosystem-architecture.md` §3/§5/§7/§8/§9 · `design-bootstrap-orchestration.md` · walkthrough §5/§6 |

> **The one invariant.** Aviator **parses; it never computes.** Every health verdict, resolution decision, signature check, prune, and wipe is performed by `copilot`/`cc` — the same hardened pipeline a headless developer runs. Aviator renders state, schedules invocations, and enforces UI-side confirmation gates. If Aviator disappeared, the CLI would still be correct. That is the design contract, and it is what makes an always-on auto-pulling agent *safer* than a human running `copilot update` by hand.

---

## 1. The app↔CLI contract (REQUIRED CLI ADDITION)

Aviator cannot shell out and screen-scrape human-formatted output — that is brittle and would tempt it to re-derive meaning. It needs a **stable, versioned, machine-readable surface**. This is a **required addition to the `copilot` CLI**, not an Aviator-internal format. Each command below MUST grow a `--json` mode emitting the schemas here. All schemas carry a top-level `schema_version` so Aviator can refuse an incompatible CLI rather than misparse it.

### 1.1 `copilot doctor --json` — the health surface

Mirrors `cc memory check`'s model exactly: a **0–100 score**, per-checker **findings**, each with a **severity** (`pass | warn | fail`). Exit code: `0` all-green, `1` any `fail`-severity finding, `2` CLI/environment error (couldn't run).

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-07-06T14:03:11Z",
  "host": "claude-code",                         // claude-code | codex
  "score": 82,
  "status": "needs-attention",                   // see §2 state machine
  "offline": false,
  "checkers": [
    { "id": "prereq-resolve",   "severity": "pass", "detail": "git,gh,node,cc,tc present" },
    { "id": "layer-present",    "severity": "pass", "detail": "4/4 layers cloned" },
    { "id": "layer-fresh",      "severity": "warn", "detail": "org tip a1b2 < remote c3d4",
      "layer": "org", "local_sha": "a1b2", "remote_sha": "c3d4", "repair": "git pull --ff-only" },
    { "id": "auth-live",        "severity": "fail", "detail": "dept-finance token expired",
      "layer": "dept-finance", "repair": "gh auth login", "escalate": "user" },
    { "id": "materialize-drift","severity": "warn", "detail": ".claude/agents/qa.md != source",
      "path": ".claude/agents/qa.md", "repair": "re-materialize", "destructive": false },
    { "id": "override-stale",   "severity": "warn", "detail": "personal qa shadows org qa (moved)" },
    { "id": "personal-safe",    "severity": "pass", "detail": "personal tree clean" },
    { "id": "signature-verify", "severity": "pass", "detail": "root_key match; 0 unsigned items" },
    { "id": "capability-policy","severity": "pass", "detail": "policy sig ok; 0 denied items" }
  ],
  "auth": [
    { "identity": "bob@acme", "scope": "org+dept-finance", "state": "expired",
      "expires_at": "2026-07-05T00:00:00Z" }
  ]
}
```

`status` is **computed by the CLI, not Aviator** — the CLI already owns the score→status mapping; Aviator only renders it. `repair` is a token the CLI understands, echoed back so Aviator can offer a one-click "Fix" that calls `copilot repair --only <checker.id>`. `destructive: true` on any finding forces Aviator to require explicit user consent before invoking the repair (see §3).

### 1.2 `copilot update --json` — the what-changed surface

```json
{
  "schema_version": "1.0", "host": "claude-code",
  "result": "applied",                           // applied | up-to-date | held | blocked | offline
  "lock_before": "sha-9f…", "lock_after": "sha-2c…",
  "changed": [
    { "dimension": "skills", "layer": "org", "item": "close-process",
      "op": "updated", "from": "aa11", "to": "bb22", "signed": true,
      "severity_trailer": null },
    { "dimension": "agents", "layer": "org", "item": "qa",
      "op": "updated", "from": "cc33", "to": "dd44", "signed": true,
      "severity_trailer": "security", "shadowed_by": "personal/agents/qa.md" },
    { "dimension": "cli-integrations", "layer": "dept-finance", "item": "quickbooks",
      "op": "pruned", "reason": "product cli.enabled=false" }
  ],
  "held_for_approval": [
    { "dimension": "foundation", "from": "5.13.0", "to": "6.0.0",
      "reason": "major; ecosystem.yml policy=hold-majors" }
  ],
  "blocked": []                                   // e.g. capability-policy denials, sig failures
}
```

`op ∈ {added, updated, pruned, unchanged}`. `pruned` is the reconciling-sync's `rsync --delete` verb (§3.2 of the architecture) surfaced so the UI can *show a removal* — the fleet's most easily-missed event. `severity_trailer` + `shadowed_by` is exactly the §7.4 "override can't hide a security fix" signal; Aviator renders it as a **red banner the user cannot dismiss silently**.

### 1.3 `copilot resolve --explain --json`

Per-item provenance for the "why do I have this?" inspector: `{ item, dimension, winning_layer, winning_sha, shadowed[], signer_of_introducing_commit, live_hash_matches (bool) }`. `live_hash_matches: false` renders as **"MODIFIED — no longer matches recorded SHA"** (§7.5), never a stale "signed ✓".

### 1.4 `copilot deprovision <org> --json`

`{ result: "wiped"|"partial"|"noop", removed: { materialized: N, clones: [layer…] }, retained_dirty: [paths…], secrets_touched: 0 }`. `secrets_touched` MUST always be `0` — the assertion that no secret ever lived in a layer to wipe (§8.1). `retained_dirty` lists any personal working tree left untouched by the never-destroy invariant.

### 1.5 `copilot freshness --json` (REQUIRED, cheap)

The push-poll endpoint from walkthrough §5. `{ latest_lock_sha, current_lock_sha, stale: bool, checked_at }`. One HTTP GET of a single SHA — this is what Aviator polls, **not** `copilot update`. See §2.

---

## 2. The state model

**Aviator's source of truth = `copilot.lock` SHA + doctor score + auth status, per host.** It holds no independent model of correctness. Two hosts (Claude Code, Codex) each get their own state; the menu-bar icon shows the **worst** of the two.

### 2.1 UI state machine

| State | Entry condition (from CLI output) | Icon |
|---|---|---|
| `healthy` | `doctor.status == healthy` (score ≥ threshold, 0 fail) AND `freshness.stale == false` | solid |
| `syncing` | an Aviator-scheduled `copilot update`/`repair` is in-flight | animated |
| `update-available` | `freshness.stale == true` OR `update.held_for_approval` non-empty | dot badge |
| `needs-attention` | `doctor.status == needs-attention` (any `warn`, or `fail` that auto-heals) | amber |
| `signed-out` | any `auth[].state ∈ {expired, revoked}` for a required layer | amber-key |
| `offline` | `doctor.offline == true` OR `update.result == offline` | grey |

Transitions are **driven only by fresh CLI JSON** — Aviator never infers a state it didn't read. `offline` explicitly is **not** `needs-attention`: unreachable ≠ drift (architecture §5.2). A stale-but-offline machine stays `offline`, showing "using cached content," never a false error.

### 2.2 Polling vs event-driven — cheaply

- **Freshness poll (default):** `copilot freshness --json` on an adaptive interval — the single-SHA endpoint from §5. Cheap enough to run every ~15 min on AC/unmetered; backs off to hourly on battery, pauses on metered/low-power (§4). A changed `latest_lock_sha` promotes the icon to `update-available`; it does **not** auto-pull unless policy says so.
- **Event-driven (opt-in):** if the org runs the publish webhook (§5 "Publish → propagate"), Aviator subscribes via a lightweight long-poll to the org endpoint and skips the timer entirely — a push lands in minutes. Webhook is org-hosted; absent it, the poll is the floor.
- **Session-start freshness:** Aviator hooks host launch (Claude Code / Codex start) and runs one freshness check — the walkthrough's "sync only if overdue" made real, but Aviator does the *check*; the CLI does the *sync*.

Full `doctor --json` runs on a slower cadence (self-heal timer, §4) and after every update — not on the fast poll, because it's heavier than a single-SHA fetch.

---

## 3. Enforcing the security posture (MUST NOT weaken it)

Aviator runs the **same hardened pipeline** with **zero bypass flags**. It never re-implements a control; it invokes the CLI's and refuses to proceed when the CLI refuses. An always-on agent that auto-pulls executable-adjacent content (agents, skills, MCP decls, commands) *is* a supply-chain surface — Aviator's job is to make that surface **visible, verified, policy-bounded, and auditable**, i.e. strictly safer than the same auto-pull run invisibly by a cron job nobody watches.

| Control (architecture ref) | How the daemon respects it |
|---|---|
| **Signature-verify-before-materialize (§7.1)** | Aviator calls `copilot update`, which verifies against the pinned `root_key` **before** writing any byte. Aviator has **no** `--skip-verify`. A `signature-verify: fail` finding blocks materialize and escalates (§6) — Aviator surfaces it, never overrides it. |
| **Pinned trust root + dual-sign rotation (§7.2)** | The `key_set` lives in `ecosystem.yml`; the CLI owns rotation. Aviator never carries or edits keys — it displays "trust root rotated (old∧new accepted)" from the update JSON so rotation is *visible*, not silent. |
| **Capability allow/deny policy (§7.3)** | Policy is signed by the `policy_signers` key distinct from push authority; the CLI enforces content-classified allow/deny. A `blocked` item in `update --json` renders as "IT policy blocked `<item>` — this is expected," never a retryable error Aviator tries to force through. |
| **Reconciling-sync prune (§3.2)** | Aviator's scheduled `copilot update` *is* the `rsync --delete` reconcile. Aviator surfaces every `op: pruned` so removals are auditable, and it never suppresses a prune to "keep things working." |
| **Never-destroy invariant (§5.2)** | **The hard line.** Aviator may freely re-materialize `.claude/` and re-clone read-only org/dept/foundation mirrors — those are disposable. It **MUST NOT** invoke any repair whose JSON carries `destructive: true` against a **dirty personal working tree**. Before any personal-layer-touching action, Aviator confirms the CLI reported `personal-safe: pass`; on `warn` it shows "you have unsaved work in your personal layer — commit it first," and the Fix button is disabled. It relies on the CLI's `guard_personal()` as the real enforcement and never passes a `--force`/`--yes` that would defeat it. |

**Why this is SAFER, not riskier — the four multipliers:**
1. **Visible.** Every auto-pull produces a what-changed panel; `op: pruned` and `severity_trailer` events that a headless cron would swallow become glanceable. A malicious or surprising change is *seen*.
2. **Verified.** Auto-pull runs through the *same* signature/policy gate as manual — Aviator adds no trusted path around it. Automation cannot lower the bar because Aviator has no lower-bar mode.
3. **Policy-bounded.** Cadence, hold-majors, and capability denials come from `ecosystem.yml` — the org, not the endpoint or the user, sets velocity. Aviator obeys centrally-set policy it cannot locally override.
4. **Auditable.** Every daemon action (poll, update, repair, wipe, held-major) is written to a local append-only action log with the before/after lock SHA and the triggering signal — a tamper-evident trail the user (and, opt-in, IT §5) can inspect. Silent autonomy is the dangerous kind; this is autonomy with a receipt.

---

## 4. Deprovision & DLP at the app layer

**MDM-signaled offboarding.** An MDM (Jamf/Intune) drops a signal — a config-profile key, a sentinel file, or a revoked auth Aviator observes. On detecting it, Aviator invokes `copilot deprovision <org> --json`, which wipes materialized `.claude/` items + the org/dept **layer clones** for that org. Aviator renders the result (`removed`, `retained_dirty`) and enters `signed-out`/`offline` for that org.

**Fail-closed on permanent auth revocation.** When a private layer's auth is **permanently** revoked (not merely expired), `copilot update` fails **closed** and returns the deprovision offer; Aviator surfaces "Access to `<org>` was revoked. Company content will be removed." and executes the wipe rather than continuing to serve now-unsanctioned content. Distinguish from a transient expiry (→ `signed-out`, re-auth offered) via the CLI's `auth[].state` (`expired` vs `revoked`).

**Never-destroy still holds during deprovision.** Deprovision wipes materialized + read-only-mirror content only. A **dirty personal working tree is never wiped** — it lands in `retained_dirty` and Aviator warns the user to reconcile it themselves. The honest architectural truth (§8.1) stands: local git copies can't be clawed back, so Aviator's guarantee is "removes what it can, transparently," not "guarantees exfiltration is undone."

**Secrets never materialize — Aviator surfaces, never stores.** Per the §8.1 three-tier DLP posture: true secrets (tokens, credentials, client PII) live **only** in runtime lookup (secrets manager / authenticated API); `secrets_touched` in deprovision is always `0` because there was nothing in a layer to wipe. Aviator may *display* a secret fetched at runtime (e.g. show an auth status, surface a connector's live state) but **writes none to disk, keychain-of-its-own, telemetry, or logs**. CLI Copilot remains the runtime gateway into systems of record; Aviator neither copies that data nor caches it.

---

## 5. Sync-automation, embodied

Aviator *is* the walkthrough §5 sync-automation stack made real — each row below maps to one automation card, all riding machinery the architecture already defines (lockfile, reconciling sync, doctor, `ecosystem.yml`):

| §5 automation | Aviator embodiment |
|---|---|
| Background refresh (scheduled) | A `launchd`-registered timer (Aviator owns it — no separate cron) runs `copilot update` on the org-set cadence, quietly, results to the what-changed panel. |
| Session-start freshness | Host-launch hook → `copilot freshness`; sync only if `stale`. |
| Publish → propagate | Freshness poll of the single-SHA endpoint, or webhook long-poll where the org runs one. |
| Cadence in the seed | Aviator **reads** `ecosystem.yml` update policy (never sets it): auto-pull **patches**, **hold majors** in `update-available`/`held_for_approval` until the user (or IT) approves. |
| Doctor on a timer | Slow-cadence `copilot doctor --json`; auto-invokes `copilot repair` for non-destructive findings, escalates the rest (§6). |

**Battery/network etiquette (non-negotiable):**
- **Backoff:** exponential on repeated failures; a 404/offline never becomes a hot loop.
- **Metered/low-power:** on `NWPathMonitor` metered or Low Power Mode, **pause** background update; freshness poll drops to hourly; nothing but a user-initiated action pulls.
- **Battery:** heavy work (full `doctor`, `update`) prefers AC + unmetered; on battery it defers to the next favorable window unless the user clicks "Update now."
- **No hammering:** one in-flight `copilot` invocation at a time per host; coalesce overlapping triggers (a webhook + a timer firing together run once).

---

## 6. Observability / telemetry — closing the named gap

The walkthrough flags **Observability** as `open`: *"no telemetry on what actually gets used, corpus health, or adoption — you can't improve descriptions/routing you can't measure."* Aviator is the natural collector: it already runs `doctor` and `resolve --explain` fleet-wide. The model is **opt-in, org-scoped, PII-minimizing**.

### 6.1 Principles
- **Opt-in, per org.** Off by default. Enabled only by an `ecosystem.yml` `telemetry.enabled: true` + `telemetry.endpoint: <org-owned URL>`. No signal leaves the machine until an admin turns it on for *their* org.
- **Org endpoint, NEVER ENAC.** Data flows to the **org's own** collector. ENAC/the foundation never receives fleet telemetry. This is the whole trust basis.
- **Content-free by construction.** Aviator sends **identifiers and counts**, never bytes of content. It emits what it can already see structurally (SHAs, item names, layer names, health scores) — nothing it would have to read a file's *body* to know.

### 6.2 What IS collected (per event, org-scoped)

```json
{
  "schema_version": "1.0",
  "org": "acme-corp", "dept": "finance",
  "machine_id": "hmac_sha256(hardware_uuid, org_salt)",   // pseudonymous, org-salted
  "host": "claude-code", "aviator_version": "1.2.0",
  "sent_at": "2026-07-06T14:00:00Z",
  "sync": { "lock_sha": "2c…", "score": 82, "status": "needs-attention",
            "offline": false, "last_update_result": "applied" },
  "drift_events": [ { "checker": "materialize-drift", "layer": "org", "count": 1 } ],
  "auth": [ { "layer": "dept-finance", "state": "expired", "days_to_expiry": -1 } ],
  "version_skew": { "foundation_local": "5.13.0", "foundation_latest": "5.14.0",
                    "behind_by": "minor" },
  "usage": [ { "kind": "skill", "layer": "org", "name": "close-process", "fires": 12 },
             { "kind": "agent", "layer": "foundation", "name": "qa", "invocations": 8 } ],
  "adoption": { "products": ["claude","knowledge"], "layers_resolved": 4 }
}
```

- `machine_id` is an **HMAC** of the hardware UUID salted per org — pseudonymous, non-reversible, lets IT count distinct machines and spot a stuck one without identifying a person.
- `usage` is **name + count only** — "the `close-process` skill fired 12 times," never the prompt, the query, or the answer.

### 6.3 What is NEVER collected
- **Personal-layer content** — no personal skill/agent bodies, names, or counts. (Personal usage stays personal; only org/dept/foundation item usage is eligible, and only if opted in.)
- **Knowledge contents** — never a knowledge doc's text, title, or a search query/result. Adoption = "knowledge product enabled," not what's in it.
- **Secrets / PII** — nothing from the runtime-lookup tier ever enters telemetry (§4).
- **Prompts, completions, memory entries, task/WP bodies.**
- **File paths under `$HOME`** beyond the layer-relative item name.

### 6.4 The IT dashboard (what closes the gap)
The org endpoint aggregates into a fleet view an IT admin reads directly: **sync health** (score distribution, % green), **drift events** (which layers drift most → which materializations are fragile), **auth-expiry** (machines about to lose access → pre-emptive re-auth), **version skew** (who's behind → is a rollout stuck), **usage/adoption** (which layers/skills are actually used → *improve the descriptions/routing you can now measure*, and retire dead content). This is precisely the measurement the walkthrough says is missing — and it lives on org infrastructure, PII-minimized, opt-in.

---

## 7. Failure escalation ladder

Each class declares the response tier — **auto-heal silently** / **notify the user** / **escalate to IT** — and the exact user-facing string. IT escalation fires only when org telemetry (§6) is on *or* an admin contact is set in `ecosystem.yml`.

| Failure class | Detected by | Response | User-facing message |
|---|---|---|---|
| **Drift** (materialize-drift, non-destructive) | `doctor` checker | **Auto-heal silently** (re-materialize); log to action trail | *(none — silent; visible in history)* |
| **Drift on a dirty personal edit** | `personal-safe` warn | **Notify** — never auto-heal | "You've edited your personal setup and haven't saved it. Commit your changes, then I'll sync." |
| **Auth expired** (transient) | `auth-live` fail, state=`expired` | **Notify**, offer one-click re-auth | "Your company sign-in expired. Click to sign in again — your partner keeps working on cached content until you do." |
| **Auth revoked** (permanent) | state=`revoked` | **Escalate to IT** + fail-closed deprovision offer | "Access to <org> was removed. Company content will be cleared from this machine. Contact IT if this is unexpected." |
| **Layer moved / renamed** | `layer-moved` (manifest slug change) | **Auto-heal silently** (update remote, re-fetch) | *(none unless it also 404s)* |
| **Layer 404 / deleted** | clone 404, classified | **Notify** (not "gone" — classified) | "Your <dept> team space isn't reachable right now. It may be moving — I'll keep the rest of your setup running and retry." |
| **Offline** | `doctor.offline` / update `offline` | **Auto-heal silently** (cached SHAs), icon → `offline` | *(none — "using cached content" tooltip only)* |
| **Policy-denied item** | `capability-policy` / `blocked` | **Notify** (expected, not an error) | "IT policy doesn't allow `<item>` — it wasn't installed. This is intentional." |
| **Incompatible version** (`requires` intersection empty) | `update` blocked, hard-error | **Escalate to IT** | "A company update conflicts with another team's setup and can't be applied safely. IT has been notified; your current setup is unchanged." |
| **Corrupt materialize / signature fail** | `signature-verify` fail | **Escalate to IT** + block materialize | "A company update didn't pass its safety check and was NOT installed. Your current setup is safe and unchanged. IT has been notified." |
| **Held major** | `held_for_approval` | **Notify** (approval gate) | "A big company update is ready but held for approval. Review what changes, then approve — or wait for IT." |

**Ladder rule:** auto-heal is reserved for **non-destructive, disposable-surface** repairs (re-materialize, re-clone a read-only mirror, update a remote URL). Anything touching the personal tree, requiring a credential, denied by policy, or failing a signature check **never** auto-heals — it notifies or escalates, because those are exactly the events where silent action would either destroy user work or paper over a supply-chain signal.

---

## 8. The one highest-risk integration concern

**Screen-scraping drift = silent security bypass.** If Aviator ever parses human-formatted CLI output instead of a versioned `--json` contract — or if the `--json` schema drifts from the CLI's actual behavior without a `schema_version` bump — Aviator can **misread a `fail` as a `pass`** and render "healthy" over a machine whose signature check failed, whose personal work is dirty, or whose policy denied an item. An always-on agent that confidently shows green while the pipeline is red is worse than no agent. **Mitigation:** the `--json` surface is a *required, versioned CLI addition* (§1), Aviator hard-refuses an unrecognized `schema_version` (degrading to "can't verify — run `copilot doctor` in a terminal" rather than guessing), and a CI contract test in the `copilot` repo asserts every `--json` command matches the published schema on every release. The contract is the safety boundary; everything else in this design assumes it holds.
