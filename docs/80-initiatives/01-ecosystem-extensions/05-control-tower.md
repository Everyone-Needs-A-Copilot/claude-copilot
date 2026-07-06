# Copilot Control Tower — Architecture

| | |
|---|---|
| **Status** | Design / Proposed — **validated against the 12 use cases + two adversarial red-teams** |
| **Product** | **Copilot Control Tower** (short: **Control Tower**) — the always-on, self-healing menu-bar client of the Copilot ecosystem |
| **Repo** | `Everyone-Needs-A-Copilot/control-tower` (its own project) |
| **Stack** | Tauri v2 · Rust core + minimal web UI · **single process** · macOS-first (Windows = re-skin) |
| **Bundle / MDM domain** | `dev.enac.controltower` |
| **Brand** | Aviator-sunglasses silhouette (`#2D294E`), template-icon friendly |
| **Branch** | `ecosystem-extensions` |
| **Design appendices** | [`research/design-control-tower-core.md`](research/design-control-tower-core.md) · [`design-control-tower-dist.md`](research/design-control-tower-dist.md) · [`design-control-tower-integration.md`](research/design-control-tower-integration.md) |
| **Validation appendices** | [`research/redteam-control-tower-A.md`](research/redteam-control-tower-A.md) (use-case layer, 17 findings) · [`redteam-control-tower-B.md`](research/redteam-control-tower-B.md) (platform layer, 18 findings) |

> **The one invariant.** Control Tower is a **face + supervisor over the `copilot`/`cc` CLI — it parses, it never computes.** Every health verdict, resolution, signature check, prune, and wipe is done by the CLI, the same hardened pipeline a headless developer runs. If Control Tower vanished, the CLI would still be correct. That contract is what makes an always-on auto-pulling agent *safer* than a human running `copilot update` by hand — and it is why the whole thing is a well-scoped skin, not a second brain.

> **How to read this.** §1 is what it is. §2–§9 are the hardened architecture. **§10 is the validation** — the 25 Critical/High failures the red-team found and how each is addressed. The name is Control Tower throughout; the appendices were written under the working codename "Aviator" and are otherwise current.

---

## 1. What it is, and why a tower

The ecosystem already ships the intelligence: a three-ring installer, a `copilot doctor`/`repair` state machine, a reconciling-sync resolver, the `ecosystem.yml` seed, a DLP/deprovision lifecycle. **Control Tower does not re-implement any of it.** It is the always-on GUI supervisor that (a) keeps the machine synced and healed on a schedule, (b) turns `doctor`'s health score into a glanceable menu-bar status, (c) runs the first-run wizard as a GUI over the same CLI phases, and (d) is the **primary delivery vehicle for the non-technical "Bob" persona** — IT pushes an app, Bob double-clicks, the CLI does the work.

The name is the model: a control tower doesn't fly the plane — it watches every flight, keeps them coordinated and on schedule, clears them to proceed, and raises the alarm when something's off. That is exactly the supervisor role, and it maps onto the IT-facing side (a tower is who ops calls). **Control Tower is the productization of the ecosystem's Rings 0–2 + the sync-automation stack into a native, IT-deployable, always-on presence.**

**Two faces, one open-source binary.** Control Tower is not only Bob's client — it is also the **IT team's setup and deployment tool** for standing up the whole ecosystem for their org, and it is **open source** (`Everyone-Needs-A-Copilot/control-tower`, public). Open source is a *requirement*, not goodwill: an always-on agent that holds a live token and auto-materializes executable-adjacent content must be **auditable** for an enterprise to trust it on every employee's machine — open source + reproducible builds + two-of-N signing (§7) are that trust basis. §2–§7 describe **Operator mode** (the end-user client); **§8 describes Admin mode** (the IT enablement tool + its documentation).

---

## 2. The status model & the menu

Control Tower's icon is a projection of `copilot doctor --json` (health score 0–100 + findings) plus auth and network state, **per host**, worst-wins across hosts.

| State | Meaning | Icon |
|---|---|---|
| **Setup-needed** | Wizard never completed | hollow outline |
| **IT-config-incomplete** | Managed profile missing a required key (fails closed, never "healthy") | outline + wrench badge |
| **Healthy** | All checks green, fresh, authed | solid |
| **Syncing** | An `update`/`repair` is in-flight | animated ring |
| **Update-available** | Freshness stale or a held-major awaits | dot badge |
| **Needs-attention** | A `warn`/unhealable `fail` survived auto-repair | amber badge |
| **Signed-out** | A required layer's auth expired/revoked | key badge |
| **Offline** | Network unreachable; on cached SHAs (overlay, restores prior state) | dimmed |
| **Waiting-for-network** | First-run completed foundation-only; company layers pending | dimmed + clock |
| **Updating-app** | Control Tower self-updating | spinner |

`status` is **computed by the CLI**, not Control Tower (§6). Precedence: `IT-config-incomplete > Signed-out > Needs-attention > Offline > Syncing > Update-available > Healthy`. The dropdown's top line is always a plain-language status sentence that **names the failing host** ("Codex needs sign-in; Claude is fine") rather than a blended verdict *(fixes A-M14)*. Menu actions (Sync now, Repair, What changed, Add a skill, Sign in, Hosts ▸, Preferences, Quit) each spawn a CLI verb with `--json`; the menu never mutates state itself.

Notifications are governed by the **Bob-agency model (§9)** — they fire *only* when Bob is the sole competent actor for a non-deferrable decision about his own data. Everything else auto-acts or escalates to IT.

---

## 3. Process model & persistence (resolved)

The core and distribution streams disagreed on the single most load-bearing decision. **Resolved: one process.** *(fixes B-C1, the single most dangerous platform failure.)*

- **One signed binary** = tray + supervisor + scheduler. It owns the timer loops (sync ~6h, doctor ~1h, freshness ~15m) **while running**. There is **no** separate headless daemon and **no** in-app fallback loop — the two-scheduler design was a concrete `copilot.lock`/prune race that could tear the `.claude/` tree.
- **The CLI self-serializes.** `copilot update`/`repair`/`deprovision` each take an **exclusive `flock` on `copilot.lock`** and fail fast if held. *Control Tower is not the lock; the CLI is* — so no process arrangement (a stray second instance, a manual CLI run, fast-user-switching) can ever double-write. A **global per-host CLI mutex across all verbs** means a `deprovision` drains pending syncs before wiping *(fixes A-M17)*.
- **`launchd` is a crash-only watchdog** — `KeepAlive={SuccessfulExit:false}`, `RunAtLoad=false`. **Never `KeepAlive=true`** (that would resurrect the app after a clean Quit and crash-loop a bad build) *(fixes B-C2)*. A `ThrottleInterval` + a launch-failure circuit breaker (N non-zero exits in a window → stop relaunching, surface "reinstall") prevents crash storms.
- **`SMAppService` handles launch-at-login** (one mechanism); for managed fleets, MDM pushes a **Service Management managed login item payload** (`com.apple.servicemanagement`) so the login item is force-approved and non-toggleable — and Control Tower detects `SMAppService.status == .requiresApproval` and surfaces "background running is off" *(fixes B-H3)*.
- **Self-update rollback lives in the watchdog, not the new bundle.** A bad update that crashes on launch can't roll itself back, so a tiny **stable watchdog** (never self-updated) stages the new bundle, launches it with `--self-test`, and waits for an **early liveness heartbeat file**; no heartbeat → discard, keep current, mark the version poisoned, notify *(fixes B-C3)*.

"Stays on, keeps synced" = SMAppService relaunch-at-login + a crash watchdog + a light supervisor loop that only runs while alive. A poll-every-6h workload needs no headless daemon.

---

## 4. The first-run wizard

A GUI over the same Ring-1 phases (`copilot doctor --bootstrap` P2–P10), asking **only what can't be derived**. It persists a checkpoint and installs the login-item + crash-watchdog at the **first** phase, not the last, so an interrupted setup resumes headlessly *(fixes A-H6)*.

**Steps:** Welcome → detect host(s) → choose host (only if both/neither) → sign in (GUI device flow: show 8-char code, open browser) → company (suggested, confirmed) → department (pick-list from Teams API) → choose products (pre-checked from `ecosystem.yml`) → pull repos → materialize + verify → teach (cheat-sheet + "add your first skill" + offer backup).

**Asked vs derived:** unmanaged asks at most **three** things (host if ambiguous, sign-in approve, company/team); derives OS/arch, prereqs, all repo URLs, product set, git identity.

**The silent managed path** — when IT ships a `.mobileconfig` writing `dev.enac.controltower` with `DisableWizard=true`, the wizard **runs silently** (Bob watches a progress bar, is asked nothing). Hardened:
- **Schema-validate the managed profile before entering silent mode.** Any required key missing/malformed → fail **closed** into the distinct **IT-config-incomplete** state (never a guess, never false-Healthy) *(fixes A-C1, B-H4)*. Distinguish *absent* (retry over a settling window to absorb partial MDM apply) vs *present-but-invalid* (immediate "IT config error: `<key>`") vs *valid*. Type-check (`bool` is bool, URL parses).
- **Offline first-run** completes foundation-only and enters **Waiting-for-network**, not Healthy and not a scary error; the supervisor finishes company clones on reconnect *(fixes A-H7)*.
- **Seed-not-yet-published** (IT shipped the app before `ecosystem.yml`) is distinguished from "solo user" via the managed `EcosystemSeedURL`; the machine holds in Waiting-for-network and completes when the seed appears, rather than falsely reporting Healthy *(fixes A-H12)*.

---

## 5. Host distinction — Claude vs Codex

Control Tower detects and manages **Claude Copilot (Claude Code host)** and/or **Codex Copilot (Codex host)** independently — a machine may have zero, one, or both. A Rust probe sweep (`command -v claude`/`~/.claude/`/`claude --version` + foundation clone `product`; the `codex` equivalents; shared `cc`/`tc`/`copilot`) determines presence; re-run by the freshness poll so a later install is picked up without a re-wizard.

The detected host selects the **`claude`/`codex` product column** via `copilot derive` (naming-topology §6): foundation `claude-copilot` vs `codex-copilot`, private `copilot-claude-*` vs `copilot-codex-*`; **`knowledge` and `cli` columns are host-agnostic and shared**. Both hosts on one machine = two host columns + one shared knowledge/cli set, **one** Control Tower, one lock. Updates are **per-host transactional** — if Claude succeeds and Codex fails, the lock is consistent per host and the status names the failing host *(fixes A-M14)*. Control Tower never hard-codes a URL; its only host job is detection + column selection.

---

## 6. The app↔CLI contract (a required CLI addition)

Control Tower cannot screen-scrape human output — that is the **single highest integration risk** (a misread `fail`→`pass` shows green over a red pipeline). So every consumed verb grows a **versioned `--json`** mode; this is a required addition to `copilot`, with a **CI contract test in the `copilot` repo** asserting the schema on every release.

- `copilot doctor --json` → `{schema_version, host, score, status, offline, checkers:[{id,severity,repair,…}], auth:[…]}` (mirrors `cc memory check`: 0–100, `pass|warn|fail`, exit 0/1/2). `status` computed CLI-side.
- `copilot update --json` → `{result, lock_before/after, changed:[{dimension,layer,item,op,from,to,signed,severity_trailer,shadowed_by}], held_for_approval, blocked}`. `op ∈ {added,updated,pruned,unchanged}`.
- `copilot resolve --explain --json`, `copilot deprovision <org> --json` (`secrets_touched` MUST be 0), and a cheap `copilot freshness --json` (single latest-lock-SHA) — the poll target, *not* full `update`.
- **Schema gating is bidirectional** *(fixes B-H6):* Control Tower declares a `min_schema`/`max_schema` range; a CLI schema **older** than its floor is as fatal as one newer. **Missing security-relevant fields fail closed** — absent `destructive`/`signed`/`severity` ⇒ treated as destructive/unsigned/fail, never as safe. The dead-end "run doctor in a terminal" degrade is replaced with an in-app "versions don't match — click to update" that drives the paired update (§7), because Bob has no terminal.

---

## 7. Distribution, signing & self-update

- **Developer ID** (not Mac App Store — the sandbox forbids spawning `copilot`), hardened runtime, notarize + **staple** both `.app` and `.dmg` (offline Gatekeeper for air-gapped fleets). Userland-only entitlements — **no admin, no privileged helper**.
- **Vendored CLI binaries are a cross-repo signing contract** *(fixes B-C2, B-H1):* `claude-copilot` CI publishes `copilot`/`cc` as **already-signed, notarized, universal** artifacts at a **pinned SHA+version**; Control Tower CI *verifies* (`codesign`, `spctl`), never re-signs, and **blocks release if the vendored CLI is older than the compat floor**. The `.pkg` postinstall strips quarantine; a `cli-spawnable` doctor check surfaces a Gatekeeper kill as a named finding, not a generic red.
- **Self-update** via Tauri's signed-manifest updater (minisign key independent of the Apple chain). **Two-of-N signing or a transparency-log witness** so one popped key isn't fleet-wide RCE; codesign cert and minisign key in separate custody; staged rollout with anomaly-halt *(fixes B-M4)*. The watchdog verifies the staged bundle is stapled offline before promoting *(fixes B-M3)*.
- **One owner of the vendored CLI** *(fixes B-C4):* Control Tower owns it; `copilot self-update` is disabled under `COPILOT_MANAGED_BY=controltower`. The compat matrix evaluates **one canonical version** (the one actually invoked), and a **newer CLI *pulls* a newer Control Tower** rather than deadlocking. `AllowSelfUpdate=false` fleets receive CLI+app as a **version-locked pair** in one pkg. On cold machines the vendored CLI is a floor: after network is up, upgrade it through the matrix before `derive` *(fixes B-M5)*.
- **A signed uninstaller** runs `launchctl bootout` + `SMAppService.unregister()` + Keychain cleanup; the watchdog self-`bootout`s if its `Program` path goes missing — so "drag to Trash" doesn't orphan a login item *(fixes B-H2)*.

---

## 8. Admin mode, MDM & IT enablement (open source)

Control Tower has **two faces over one open-source binary**: **Operator mode** (the end-user client, §2–§7) and **Admin mode** (`control-tower admin`, or an IT-unlocked Admin window) — the guided tool that lets an IT team **stand up the entire ecosystem for their org** without hand-editing YAML or crafting MDM profiles by hand.

### 8.1 Admin mode — the IT setup & deployment tool

Admin mode is the productization of the ecosystem's one-time IT setup (walkthrough §4), delivered as a guided flow:

1. **Seed generator** — authors the org `ecosystem.yml` (products, departments, foundation pins, `auth`/`host`/`mirror`, `policy_signers`, telemetry) and opens the PR to `<org>/copilot-ecosystem`. No hand-written YAML.
2. **Repo & access scaffolding** — creates/verifies the org + **separate per-department** repos (confidentiality), and emits the exact GitHub team / CODEOWNERS / branch-protection setup (or runs it via `gh` where the admin has rights), including the declared-repo existence check so a typo can't ship a 404.
3. **Capability-policy authoring & signing** — guided policy editor; signs with the security-team key distinct from push authority (ecosystem §7).
4. **MDM profile generator** — the high-leverage piece: emits a ready-to-upload `.mobileconfig` for the `dev.enac.controltower` domain pre-filled with the org's values, **plus** the managed login-item and notifications payloads — so IT uploads one artifact to Jamf/Kandji/Intune and every employee's wizard runs silent.
5. **Preflight validation** — before rollout, validate end-to-end: seed parses, declared dept repos exist, policy is signed by an authorized signer, the managed profile is *complete for the silent path* (the A-C1/B-H4 completeness check run proactively), the foundation pin resolves, the mirror is reachable. A red/green report IT reads before pushing to the fleet.
6. **Fleet dashboard** — the §9 observability view: who's healthy, stuck, behind, or needs re-auth.
7. **Deployment runbooks** — per-MDM (Jamf / Kandji / Intune) step-by-step instructions generated with the org's real values filled in.

### 8.2 Documentation — a first-class deliverable

Control Tower ships with **clear, complete IT documentation**, versioned in the open-source repo:
- a **quickstart** ("stand up the ecosystem for your org in N guided steps");
- per-MDM **deployment guides** (Jamf, Kandji, Intune) with the generated artifacts;
- a **configuration reference** for every `ecosystem.yml` and managed-profile key;
- a **security & trust** document (what the always-on agent does, what it never does, how to audit it, the signing/verification model) — the enablement an enterprise security review demands;
- an **operations runbook** (rollout, offboarding/deprovision, the offline/air-gapped path, troubleshooting each escalation state).

### 8.3 MDM managed config, deprovision & the always-on security surface

**MDM managed config** (`dev.enac.controltower` via `com.apple.ManagedClient.preferences`) pre-seeds `OrgSlug`, `Department`, `EcosystemSeedURL`, `GitHubHost`, `AuthMode`, `Host`, `FoundationMirror`, `HTTPSProxy`, `UpdateFeedURL`, `AllowSelfUpdate`, `DisableWizard`, `Deprovisioned`, plus a **mandatory `AdminContact`/escalation endpoint** (§9) and a **Notifications configuration profile** pre-authorizing the bundle *(fixes B-M7)*.

**Security-sensitive keys are honored ONLY from the managed (forced) domain** *(fixes B-C5, the supply-chain preference-write attack):* `UpdateFeedURL`, `FoundationMirror`, `EcosystemSeedURL`, `HTTPSProxy`, `GitHubHost`, `AuthMode`, `AllowSelfUpdate`, `Deprovisioned` are read via `CFPreferencesAppValueIsForced`; a value present only in the user domain is **ignored** in favor of the compiled-in default, and logged as a tamper event. On unmanaged machines the compiled-in trust root (minisign pubkey + default feed) is authoritative — trust roots are code, not config.

**Deprovision is MDM-native, not app-contingent** *(fixes A-C4):* the real backstop is **server-side token revocation** (the next online `copilot update` fails closed and wipes) + an MDM-run `copilot deprovision` as its own managed agent — so a leaver who trashes Control Tower or stays offline can't defeat it. Only an **explicit `Deprovisioned=true`** (never mere profile removal) triggers a wipe *(fixes B-M1)*, debounced over a settling window with a **soft-then-hard** two-phase (quarantine clones for a grace window; a flip-back restores without a re-clone) *(fixes B-M2)*. The honest boundary from §8.1 holds: an offline/powered-off machine can't be remotely wiped — the guarantee is "no secret ever materialized," not "exfiltration undone."

**The always-on surface is made SAFER, not riskier** — Control Tower runs the same pipeline with **zero bypass flags** (no `--skip-verify`, no `--force`), so every auto-pull is **visible** (what-changed panel surfaces prunes + security trailers a cron would swallow), **verified** (same signature/policy gate — no lower-bar mode exists), **policy-bounded** (cadence/holds/denials from `ecosystem.yml`), and **auditable** (a hash-chained action log anchored to the org endpoint so truncation is server-detectable). The **never-destroy invariant is the hard line**: it may re-materialize `.claude/` and re-clone read-only mirrors freely, but **never** touches a dirty personal tree.

**Per-user, not per-machine** *(fixes B-H5, B-H7):* tree, keychain, login item, watchdog are all per-`$UID`; no writable `/Users/Shared` state. Kiosk/lab machines (auto-login, no device flow) use a **machine credential** (`AuthMode=gh-app` token in the system keychain). Keychain items use a **stable designated requirement** (Team-ID-based) so self-update doesn't invalidate ACLs *(fixes B-M6)*.

---

## 9. The Bob-agency model — the escalation reframe

The original escalation ladder routed by **event-class** (drift→auto-heal, auth→notify, sig-fail→escalate). That's the wrong axis: **Bob is not a reliable actor**, so most notifications aimed at him silently degrade, and every un-actionable alert burns the credibility of the one that matters. **Route by *actor-competence × reversibility* instead** *(fixes A-C3, A-H9/H10/H11/H13, A-M15).* Three lanes:

1. **AUTO-ACT (never ask, within policy)** — anything reversible on a disposable surface Bob can't judge: re-materialize, re-clone mirrors, ff-pull, apply signed patches, **defer (not block) a non-security update while a host session is live** *(fixes A-H8)*, and — critically — **auto-suspend a personal override that shadows a security fix** so the fixed version wins immediately (reversible: Bob re-affirms). Never leave a Bob notification as the *sole* control on an active security exposure *(fixes A-C3)*.
2. **ESCALATE TO IT (not Bob)** — anything Bob is unqualified to decide or can't action: **held-major approval** (approver authority declared in `ecosystem.yml`; on managed machines IT approves centrally, Bob sees a non-actionable "waiting on IT") *(fixes A-H11)*, capability-policy conflicts (IT action-log only, never a Bob notification) *(fixes A-M15)*, signature failures, version conflicts, **and any Bob-actionable item left un-acted past a deadline** (backup-missing, re-auth → **time-boxed escalation**, "Bob's Mac hasn't been backed up in 7 days") *(fixes A-H13)*.
3. **ASK BOB (rare)** — only when he is the sole competent actor about his own data: "commit your dirty personal work before I sync," and the one sign-in approve. Nothing else interrupts him.

**Safety-escalation is split from analytics telemetry and is ON by default for managed machines** *(fixes A-C5):* the IT channel carries **content-free safety signals** (sig-fail, auth-revoked, policy-conflict, stalled-onboarding, persistence-disabled, notifications-off) via a **mandatory** `AdminContact` — so "IT notified" is never a no-op. **Analytics** (usage/adoption) stays genuinely opt-in per org. A prune of a **recently-used** item notifies ("a tool you used was removed") rather than only logging *(fixes A-H9)*; if notification permission is denied, high-severity events fall back to opening the popover and re-route to the IT channel *(fixes A-H10)*.

**Observability** (the ecosystem's named gap) is closed here: opt-in, **org-scoped** (never ENAC), PII-minimizing telemetry → an IT fleet dashboard (sync health, drift, auth-expiry, version skew, usage/adoption). `machine_id = hmac(hardware_uuid + posix_uid, per-install-random-salt)` — per **user**, non-reversible from MDM inventory *(fixes B-H5)*; usage emits only items whose CLI-computed winning layer ∈ {org,dept,foundation}, never a personal name.

---

## 10. Validation — the 25 Critical/High findings and how they're addressed

Full reports: [`redteam-control-tower-A.md`](research/redteam-control-tower-A.md) (use-case layer), [`redteam-control-tower-B.md`](research/redteam-control-tower-B.md) (platform layer). All addressed above.

| ID | Sev | Failure | Addressed |
|---|---|---|---|
| A-C1 | Crit | Managed profile missing a key + silent wizard → mis-provision, false-Healthy | §4 schema-validate → fail-closed IT-config-incomplete |
| A-C2 | Crit | Vendored binaries killed by Gatekeeper/quarantine | §7 cross-repo signed+notarized + de-quarantine + `cli-spawnable` check |
| A-C3 | Crit | Security-shadow relies on a Bob notification he never sees | §9 auto-suspend the override + escalate |
| A-C4 | Crit | Deprovision defeated by trashing the app / staying offline | §8 MDM-native + server-side revocation |
| A-C5 | Crit | Safety escalations gated behind off-by-default telemetry | §9 split safety from analytics; IT channel on by default |
| A-H6 | High | Quit mid-wizard strands, no daemon to finish | §4 persist + install watchdog at first phase |
| A-H7 | High | Offline first-run marks foundation-only as Healthy | §4 Waiting-for-network state |
| A-H8 | High | Daemon materializes a breaking change mid-session | §9 session-active backoff for non-security |
| A-H9 | High | Prunes silent; "visible" ≠ "seen" | §9 notify on prune of a recently-used item |
| A-H10 | High | Notification permission denied → notify tier dead | §8 MDM notifications profile; §9 popover + IT fallback |
| A-H11 | High | Held-major approval handed to a Bob who can't judge | §9 IT approves centrally |
| A-H12 | High | App shipped before `ecosystem.yml` → fleet false-Healthy | §4 Waiting-for-network, seed-vs-solo distinction |
| A-H13 | High | Bob-actionable alerts nudge once then silent forever | §9 time-boxed escalation to IT |
| B-C1 | Crit | Dual scheduler → double-sync race, torn `.claude/` | §3 single process + CLI-side `flock` |
| B-C2 | Crit | `KeepAlive=true` fights the user / crash-loops | §3 `KeepAlive={SuccessfulExit:false}` + circuit breaker |
| B-C3 | Crit | Rollback trapped inside a bundle that won't launch | §3 watchdog-owned rollback + liveness heartbeat |
| B-C4 | Crit | Compat-matrix deadlock; no vendored-CLI owner | §7 one owner; newer CLI pulls newer app; locked pair |
| B-C5 | Crit | User-writable prefs repoint update feed/mirror → RCE | §8 security keys honored only from forced/managed domain |
| B-H1 | High | Cross-repo binary signing/version lockstep | §7 signed artifact contract + pinned SHA + verify-not-resign |
| B-H2 | High | Deleted app orphans LaunchAgent/login item | §7 signed uninstaller + self-`bootout` guard |
| B-H3 | High | `SMAppService` approval Bob toggles off | §3 managed login-item payload + disabled-state detection |
| B-H4 | High | `DisableWizard` + missing key: brick-vs-loud racy | §4 typed schema, settling window, absent/invalid/valid |
| B-H5 | High | HMAC machine_id collides/re-identifies; name leak | §9 per-user salted id; layer-verified usage only |
| B-H6 | High | `--json` gate one-directional; missing fields default safe | §6 bidirectional range gate; missing security fields fail closed |
| B-H7 | High | Multi-user / kiosk auth & shared-state unspecified | §8 per-user everything; machine credential for kiosk |

*(Med/Low — propagation floor for urgent revocations, deprovision debounce, staple-on-self-update, keychain ACL, notification profile, translocation-safe paths, action-log tamper-evidence — are folded into §3–§9 or listed in the appendices as P2 polish.)*

---

## 11. Open decisions

1. **Signing custody** — two-of-N signing vs a transparency-log witness for Control Tower releases (§7/B-M4); who holds the second key.
2. **Urgent-revocation propagation** — accept the freshness-poll floor, or require the publish webhook for orgs that need fast kill of a compromised skill (§8/A-M16).
3. **Kiosk/lab support depth** — first-class machine-credential path now, or defer (§8/B-H7).
4. **Codex host readiness** — Control Tower is host-agnostic by design, but Codex Copilot's own installer maturity gates the Codex column; confirm parity timing.

---

## 12. Phased roadmap (parallelizable — see the PRD)

*No time estimates — phases, priorities, complexity only. The [PRD](#) decomposes these into parallel workstreams.*

- **P0 — CLI contract + shell.** The `--json` additions + `flock` + `COPILOT_MANAGED_BY` in `copilot` (prereq); the single-process Tauri shell, status state machine, host detection, menu.
- **P1 — Wizard + persistence + signing.** GUI wizard (silent-MDM + fail-closed validation + Waiting-for-network), SMAppService + crash-watchdog, Developer ID signing/notarization + the cross-repo binary contract, self-update via the stable watchdog + heartbeat.
- **P2 — MDM + security + Bob-agency.** Managed config (forced-domain security keys, managed login item, notifications profile), MDM-native deprovision + soft-then-hard, the actor-competence escalation model, safety-channel-on-by-default.
- **P2/P3 — Admin mode + docs (open source enablement).** The IT setup tool (seed generator, repo/access scaffolding, capability-policy signing, **MDM profile generator**, preflight validation, fleet dashboard, deployment runbooks) and the first-class IT documentation set (§8). Public repo, reproducible builds.
- **P3 — Observability + hardening.** Opt-in org telemetry + IT dashboard, two-of-N signing, anomaly-halt rollout, per-user privacy.
- **P4 — Windows re-skin.** The six boundary shims (tray, Task Scheduler, EV/SmartScreen, MSI/winget, Credential Manager, Intune/GPO) over the shared Tauri core.

**Dependency spine:** the `copilot --json`/`flock` contract (P0) gates everything — Control Tower can't supervise a CLI it can't read machine-readably. Signing (P1) gates any real distribution. MDM (P2) gates the Bob/enterprise path.

---

## Appendices

**Design:** [`research/design-control-tower-core.md`](research/design-control-tower-core.md) · [`design-control-tower-dist.md`](research/design-control-tower-dist.md) · [`design-control-tower-integration.md`](research/design-control-tower-integration.md)
**Validation:** [`research/redteam-control-tower-A.md`](research/redteam-control-tower-A.md) · [`redteam-control-tower-B.md`](research/redteam-control-tower-B.md)
**Parent architecture:** [`04-ecosystem-architecture.md`](04-ecosystem-architecture.md)
