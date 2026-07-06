# Aviator — The Menu-Bar Face & Supervisor of the Copilot Ecosystem

| | |
|---|---|
| **Status** | Design / Proposed |
| **Repo** | `Everyone-Needs-A-Copilot/aviator` (own project) |
| **Stack** | Tauri v2 · Rust core + minimal web UI · macOS-first (Windows = later re-skin) |
| **Brand** | Aviator-sunglasses silhouette, single color `#2D294E`, template-icon friendly |
| **One line** | Aviator is a **face + supervisor over the `copilot`/`cc` CLI verbs** — never a second brain. It schedules, runs, shows state, and escalates. Every real action (resolve, update, doctor, repair, deprovision) is a CLI call. |

The ecosystem architecture already ships the intelligence: a three-ring installer, a `copilot doctor`/`repair` state machine, a reconciling-sync resolver, an `ecosystem.yml` seed, and a DLP/deprovision lifecycle. Aviator does **not** re-implement any of it. It is the always-on GUI supervisor that (a) keeps the daemon alive, (b) turns doctor's health score into a glanceable status, (c) drives the first-run wizard as a GUI over the same CLI phases, and (d) is the primary delivery vehicle for the **Bob persona** — IT pushes an app, Bob double-clicks, the CLI does the work.

---

## 1. The menu-bar app

### 1.1 The status state machine

Aviator's menu-bar icon is a projection of `copilot doctor`'s output (health score 0–100 + findings) plus auth and network state. States are mutually exclusive; the resolver is `worst-wins` over the current signals.

| State | Meaning | Derived from | Icon rendering (template + treatment) |
|---|---|---|---|
| **Setup-needed** | No foundation materialized yet; wizard never completed | `~/.copilot/layers/foundation` absent OR `cc config get setup.complete` unset | Sunglasses **outline only** (hollow), slow pulse |
| **Healthy** | All doctor checks green, score 100, fresh, authed | `copilot doctor --json` → `score==100 && findings==[]` | Solid filled sunglasses, no badge |
| **Syncing** | A `copilot update`/`repair`/wizard phase is actively running | daemon job state = running | Solid glasses + **animated spinner** ring; menu shows live phase |
| **Needs-attention** | Doctor found a `fail`/`warn` the daemon could not auto-heal, OR a shadowed-security / override-stale / backup-missing flag | `doctor` findings with severity ≥ warn that survived auto-repair | Solid glasses + **amber dot badge** (top-right) |
| **Offline** | Network unreachable; running on cached SHAs (not drift) | clone/fetch fails, `NO_NETWORK`; doctor classifies unreachable≠deleted | Solid glasses **dimmed 50%** + small cloud-slash glyph |
| **Signed-out** | A private layer's auth is revoked/expired; `gh auth status` fails | `auth-live` checker fail | Solid glasses + **key badge**; primary action becomes "Sign in" |
| **Updating-app** | Aviator itself is self-updating (Tauri updater) | Tauri updater event | Spinner ring, tooltip "Updating Aviator" |

**Transition rules (event-driven, not just polled):**

- `Setup-needed → Syncing → Healthy` — wizard completion path.
- `Healthy → Syncing → Healthy` — scheduled `copilot update` cycle, silent.
- `Healthy → Needs-attention` — a timer `doctor` run surfaces a finding auto-repair can't clear (e.g. `override-stale`, `security:` trailer, personal-layer dirty guard, backup-missing banner).
- `Any → Offline` — network signal lost; **remembers the pre-offline state** and restores it on reconnect (offline is an overlay, not a terminal state).
- `Any → Signed-out` — `auth-live` fail; sticky until re-auth.
- `Needs-attention → Syncing → Healthy` — user hits **Repair** (or a later timer auto-heals a now-fixable finding).

Precedence when multiple signals fire: `Signed-out > Needs-attention > Offline > Syncing > Healthy`. Setup-needed dominates everything (pre-install nothing else is meaningful).

### 1.2 The dropdown menu

The menu is **state-adaptive** — the top line is always the current status sentence in plain language, and the primary action is contextual.

```
  ● Healthy — everything's in sync            ← status line (plain language)
  ─────────────────────────────
  Sync now                          ⌘S        → copilot update --json (background)
  Repair…                                     → copilot repair --json (shown when findings exist)
  What changed?                               → renders last update's diff (shadowed/security flags)
  ─────────────────────────────
  Add a skill…                                → GUI wrapper over `copilot add skill --personal`
  Open cheat-sheet                            → opens ~/.copilot/CHEATSHEET.md in a panel
  ─────────────────────────────
  Sign in…                                    → gh device flow (only when Signed-out / private layer needs it)
  Hosts ▸  Claude ✓ · Codex —                 → per-host submenu (§4.4)
  ─────────────────────────────
  Preferences…                                → schedule, notifications, MDM status, launch-at-login
  Quit Aviator                                → stops UI; daemon keeps running (see §2)
```

Contextual swaps: **Setup-needed** replaces the whole body with a single **"Finish setup…"** button that launches the wizard. **Signed-out** promotes **"Sign in…"** to the top. **Needs-attention** promotes **"Repair…"** and expands the finding list inline (one line each, plain-language, with the exact `copilot` verb that fixes it).

Every action is a spawn of the vendored CLI with `--json`; the menu never mutates state itself. Long actions flip the app to **Syncing** and stream the phase name into the status line.

### 1.3 Native notifications (macOS `UNUserNotificationCenter`)

Notifications are **rare by design** — the daemon auto-heals silently; a notification means *human attention is genuinely required*.

| Fires when | Notification | Action button |
|---|---|---|
| A `security:`-trailer or shadowed-upstream change lands (§7.4 of arch) | "A security update changed a component you override" | "What changed?" |
| `auth-live` fails (token expired/SSO) | "Your company setup needs you to sign in" | "Sign in" |
| Personal layer is not backed up (persistent banner escalated once) | "Your personal work isn't backed up" | "Back up now" |
| A finding survived N auto-repair attempts (self-heal gave up) | "Aviator couldn't fix something automatically" | "Repair" |
| `copilot deprovision` completed (offboarding) | "Company content was removed from this Mac" | — |

**Never notify** for: a successful scheduled sync, an offline blip that self-recovered, a routine auto-repaired drift. Those change the icon at most.

---

## 2. The background daemon — "stays on, keeps synced"

Two cooperating mechanisms, because the menu-bar app can be quit but the ecosystem must keep healing.

**(a) A per-user `launchd` LaunchAgent** — `dev.enac.aviator.daemon` in `~/Library/LaunchAgents/`. `RunAtLoad=true`, `KeepAlive=true`. This is a **headless Rust sidecar** (a second Tauri binary target, no WebView) that owns the timer loop and survives app quit, logout/login, and reboot. It is the source of truth for "stays on." The GUI app, when open, **attaches** to the daemon over a local IPC socket (`~/.copilot/run/aviator.sock`) to render live state; it does not run its own duplicate loop.

**(b) The app's own timer loop** — only relevant when the daemon is unavailable (e.g. LaunchAgent not yet installed on first launch). The app can run the loop itself as a fallback so a user who just downloaded Aviator and hasn't granted "launch at login" still gets sync while the window is open. On first successful run the app **installs the LaunchAgent** and hands the loop off to the daemon.

### 2.1 The three loops (all are CLI calls on a schedule)

| Loop | Cadence (default, tunable in Prefs) | CLI call | On result |
|---|---|---|---|
| **Sync loop** | every 6h + on network-regain + on wake | `copilot update --json` | resolves from lock, reconciling-sync materialize; icon → Syncing→Healthy |
| **Doctor-on-timer self-heal** | every 1h | `copilot doctor --json` → if findings, `copilot repair --json` | auto-repair the fixable; surface the rest as Needs-attention |
| **Freshness poll** | every 15m (cheap) | `copilot doctor --checks layer-fresh,auth-live --json` | detects remote-moved / auth-expired fast without a full update |

Self-heal escalation: `repair` is attempted up to **3 times** with backoff for a given finding-signature; if it still fails, the finding is promoted to Needs-attention and (for security/auth classes) a notification. The **never-destroy invariant** is honored entirely by the CLI (personal-layer dirty guard, read-only mirror reset vs personal stash-and-flag) — Aviator never writes layers itself, so it inherits the safety for free.

### 2.2 App-closed vs app-open

| | App **open** | App **closed** (Quit) |
|---|---|---|
| Sync loop | runs via daemon; live progress in menu | runs via daemon; result reflected on next open |
| Doctor self-heal | runs via daemon; findings shown live | runs via daemon silently |
| Notifications | delivered (app or daemon can post) | **daemon posts them** — clicking one relaunches the app to the right panel |
| Icon | present, live | absent (no menu bar) — daemon has no icon; it re-posts state when app relaunches |

"Quit" stops only the GUI; the LaunchAgent daemon keeps the ecosystem synced and healed. A true full stop is **Preferences → Disable background sync** (unloads the LaunchAgent) — a deliberate, reversible choice, never the default.

**Silent vs surfaced:** auto-heal silently for `layer-fresh` (ff-pull), `materialize-drift` (re-materialize), `layer-present` (re-clone), transient network. Surface (Needs-attention/notify) for `auth-live`, `override-stale`, `security:` trailer, personal-layer dirty, backup-missing, and any finding that exhausted auto-repair.

---

## 3. The first-run WIZARD — full flow

The wizard is a **GUI over the same Ring-1 phases** (`copilot doctor --bootstrap` P2–P10). It renders each phase as a step, and — critically — asks **only what can't be derived**, matching the bootstrap doc's question-flow rule. When an **MDM managed config** exists, the wizard runs **silently** and shows only progress.

### 3.1 Steps

| Step | What happens | Asked vs Derived |
|---|---|---|
| **W0 Welcome** | Brand splash; "Set up your AI copilot." | — |
| **W1 Detect host(s)** | Probe for Claude Code and/or Codex (see §4). Result shown: "Found Claude Code" / "Found both" / "None found." | **Derived** (detection) |
| **W2 Choose host** | If exactly one → auto-select, show confirmation. If both → pick primary (or "manage both"). If **neither** → offer to install a host (runs Ring-0 bootstrap for the chosen host) | **Asked only if ambiguous** (both/neither); else derived |
| **W3 Sign in** | If a private layer will be needed: GUI-driven `gh auth login --web` **device flow** — Aviator opens the browser and **displays the 8-char code in-window** with a copy button; polls `gh auth status` until authed. Solo/foundation-only → skipped | **Asked** (a browser approve + code), unless token already present |
| **W4 Company** | Plain language: "Is this for a company, or just you?" Company slug **pre-suggested** from `git config user.email` domain + `gh api /user/orgs` | **Derived-suggested, confirmed**; skipped in solo |
| **W5 Department** | "What team are you on?" — a **numbered pick-list** from `gh api /orgs/<org>/teams` membership (never free text). One team → auto-picked & skipped | **Derived-suggested pick-list**; skipped if single-team |
| **W6 Choose products** | Checkboxes for the host column + `knowledge` + `cli`, **pre-checked to `ecosystem.yml`'s `products.*.enabled`**. User can enable fewer, not more than the org allows | **Derived defaults, user may narrow** |
| **W7 Pull repos** | `copilot derive` (ecosystem.yml → lock) then clone the resolved layers with the right credential per tier. Live per-repo progress | **Derived** (no input) |
| **W8 Materialize + verify** | `copilot update` (reconciling-sync) → `copilot doctor --json` self-check | **Derived** |
| **W9 Teach** | Show the cheat-sheet in-panel; a **"Add your first skill"** button wired to `copilot add skill --personal` (asks two plain-English questions). Offer "Back up my personal work" if not yet backed up | one optional action |

On completion: `cc config set setup.complete true`, install the LaunchAgent, transition icon **Setup-needed → Healthy**.

### 3.2 The silent MDM path

When IT ships Aviator via MDM (Jamf/Intune) it drops a **managed config** — a `com.enac.aviator` configuration profile (macOS `defaults`/`NSUserDefaults` managed domain) and/or `~/.copilot/managed/ecosystem.local.yml`. If present at first launch:

- **W2** host is set from the profile (`managed.host`).
- **W4/W5** company + department are **pre-filled and skipped** (`managed.org`, `managed.department`) — Bob is never asked.
- **W6** products come from `ecosystem.yml` — no prompt.
- **W3** uses the org's `auth` mode; if a `gh-app`/SSO org, still requires the one browser approve (can't be truly zero-touch unless a device cert exists), but everything around it is pre-filled.

Result: **Bob double-clicks Aviator and watches a progress bar** — detect → pull → materialize → "Your copilot is ready." Zero questions. The wizard degrades from "guided Q&A" to "progress spectator" purely by the presence of managed config. That is the Bob promise, delivered as an app.

**Asked-vs-derived summary:** In the *unmanaged* case Aviator asks at most **three** human-answerable things — (host if ambiguous, sign-in approve, company/team) — and *derives* OS/arch, prereqs, all repo URLs, product set (from `ecosystem.yml`), and git identity. In the *managed* case it asks **zero** (at most one browser approve for SSO).

---

## 4. The Claude-vs-Codex distinction — the mechanism

### 4.1 Detection probes

Aviator runs a deterministic host-detection sweep (Rust, no CLI needed for the probe itself). It reports **each host independently** — a machine can have zero, one, or both.

| Host | Probes (any hit ⇒ present) | Version |
|---|---|---|
| **Claude (Claude Code host)** | `command -v claude`; `~/.claude/` dir; `~/.claude/copilot` symlink; `claude --version`; `claude-copilot` foundation clone at `~/.copilot/layers/foundation` with `product: claude` | `claude --version` + `VERSION.json.framework` in the foundation clone |
| **Codex (Codex host)** | `command -v codex`; the Codex host config dir; `codex --version`; `codex-copilot` foundation clone | `codex --version` + foundation `VERSION.json` |
| **Shared substrate** | `command -v cc` / `command -v tc` / `command -v copilot` (host-agnostic — present for either host) | `cc --version`, `copilot --version` |

Detection is re-run by the freshness poll so a host installed later is picked up without a re-wizard.

### 4.2 Selecting the host-parametric repos (naming-topology §6)

The detected host selects the **`claude`/`codex` product column**; `knowledge` and `cli` are **host-agnostic and shared**. Aviator passes the detected host to `copilot derive`, which fills the host token:

| Column | Claude machine | Codex machine | Shared? |
|---|---|---|---|
| Foundation | `Everyone-Needs-A-Copilot/claude-copilot` | `Everyone-Needs-A-Copilot/codex-copilot` | host-forked |
| Org | `acme-corp/copilot-claude-org` | `acme-corp/copilot-codex-org` | host-forked |
| Dept | `acme-corp/copilot-claude-dept-finance` | `acme-corp/copilot-codex-dept-finance` | host-forked |
| Personal | `bob/copilot-claude-private` | `bob/copilot-codex-private` | host-forked |
| **Knowledge** (all tiers) | `…/copilot-knowledge-*` | *same repos* | **shared** |
| **CLI** (all tiers) | `…/copilot-cli-*` | *same repos* | **shared** |

Aviator never hard-codes a URL — it hands `host` + `org` + `dept` to `copilot derive` and the CLI computes the column. Aviator's only host job is **detection and column selection**, exactly the naming convention's `host` variable.

### 4.3 Managing BOTH hosts on one machine

One Aviator, **two host columns, one shared knowledge/cli set, one daemon.** The lockfile already carries a `product` axis per layer, so a both-hosts machine simply has both `claude-*` and `codex-*` layers plus the single shared `knowledge`/`cli` layers. The daemon's loops run against the **whole** resolved set — one `copilot update` materializes both host columns (each into its own discovery target: `claude`→`~/.claude/`, `codex`→its config dir) and the shared columns once. No duplicate sync, no duplicate knowledge clone.

### 4.4 Per-host status in the UI

The **Hosts ▸** submenu shows a row per detected host with its own doctor sub-score and freshness:

```
  Hosts ▸
    Claude   ● Healthy   v5.14.0   synced 2m ago
    Codex    ▲ Needs sign-in  v1.8.0
    ─────────────
    Shared: Knowledge ● · CLI ●
```

The top-level icon is `worst-wins` across both hosts + shared columns. A user with only one host sees a single-row submenu (or it's hidden entirely when only one host and no ambiguity).

---

## 5. Own-project repo structure (`aviator`)

```
aviator/
├── src-tauri/                     # Rust core
│   ├── src/
│   │   ├── main.rs                # tray app entry (WebView menu-bar)
│   │   ├── daemon.rs              # headless sidecar target (LaunchAgent)
│   │   ├── cli.rs                 # the ONE contract boundary: spawn copilot/cc, parse --json
│   │   ├── state.rs               # status state machine (§1.1)
│   │   ├── detect.rs              # host-detection probes (§4.1)
│   │   ├── wizard.rs              # phase orchestration over copilot doctor --bootstrap
│   │   ├── schedule.rs            # launchd LaunchAgent install + timer loops
│   │   ├── ipc.rs                 # app↔daemon local socket
│   │   └── notify.rs              # UNUserNotificationCenter bridge
│   ├── tauri.conf.json            # tray, updater, entitlements, code-sign
│   ├── bin/                       # (optional) vendored copilot/cc userland binaries
│   └── Cargo.toml
├── ui/                            # minimal web UI (menu popover + wizard panels)
│   ├── index.html · wizard.html
│   └── src/ (Svelte/vanilla — kept tiny; no heavy framework)
├── assets/icons/                  # aviator template icons (per-state renderings)
├── installer/                     # .pkg + MDM profile template (com.enac.aviator)
├── VERSION.json                   # app version + min-compatible copilot CLI range
└── README.md
```

### 5.1 Locating & invoking the CLI — require vs vendor

**Recommendation: vendor-with-fallback.** Aviator ships the userland `copilot`/`cc`/`tc` tarballs (the same admin-free binaries Ring-0 unpacks into `~/.copilot/bin`) inside the app bundle, but **prefers an already-installed `~/.copilot/bin/copilot`** if present and version-compatible. Rationale:

- The Bob path (IT pushes the app to a machine with *nothing*) requires Aviator to be able to bootstrap from a cold machine — so it must carry the binaries.
- The developer path (CLI already installed) should not get a second, stale copy shadowing theirs — so prefer the installed one when compatible.
- Resolution order at launch: `~/.copilot/bin/copilot` (if `--version` satisfies `VERSION.json.min_cli`) → vendored bundle copy → offer to install.

Aviator **always invokes by absolute path** (never bare `copilot` on PATH) to avoid the GitHub `gh copilot` name collision (arch A-M21).

### 5.2 The app↔CLI contract

Aviator is a supervisor, so it needs **machine-readable output** from every verb it drives. The contract (detailed by the integration stream, asserted here):

- Every consumed verb supports **`--json`**: `copilot doctor --json` (→ `{score, findings:[{id,severity,repair,message}]}`), `copilot update --json` (→ `{changed:[…], shadowed:[…], security:[…]}`), `copilot derive --json`, `copilot repair --json`, `copilot deprovision --json`.
- **Streaming progress**: long verbs emit newline-delimited JSON phase events (`{phase, status, pct}`) on stdout so the wizard/Syncing state can render live progress.
- **Exit codes** mirror `cc memory check`: `0` clean, non-zero on any `fail` — Aviator keys Needs-attention off both the code and the parsed findings.
- **Version compat**: `VERSION.json.min_cli` gates; on a too-old CLI, Aviator offers to update the vendored binary rather than driving an incompatible one.

Aviator owns **no** ecosystem state — no manifest, no lock, no layers. It reads them only through `--json` verbs. This keeps it a pure face: the CLI can evolve independently as long as the JSON contract holds.

---

## 6. Relationship to the existing 3-ring installer

**Recommendation: Aviator is the primary delivery vehicle for Bob; the `curl` one-liner remains the developer path. They share one engine.**

Aviator does **not replace** Ring 0/Ring 1 — it **embeds and drives** them. The three-ring model is the CLI's internal contract; Aviator is a GUI that runs Ring 0 (unpack vendored binaries + clone foundation) and then Ring 1 (`copilot doctor --bootstrap`) as its wizard's back-half. So there is exactly **one** install engine, reached two ways:

| Persona | Entry point | What runs underneath |
|---|---|---|
| **Bob** (non-technical) | IT pushes **Aviator.pkg** via MDM → Bob double-clicks → wizard | Aviator runs Ring-0 (vendored binaries, foundation clone) then Ring-1 phases; MDM config makes it silent |
| **Developer** | `bash -c "$(curl …bootstrap.sh)"` | The classic three-ring CLI path, unchanged; can *also* install Aviator afterward for the always-on daemon |

Why this reconciliation:

- **Bob never opens a terminal.** The bootstrap doc's own fallback was already "IT hands Bob a double-clickable `.command`" — Aviator is the productized, self-updating, always-on version of that fallback. The terminal one-liner is a *developer convenience*, not Bob's path (bootstrap doc §1), so making the app Bob's front door is fully consistent.
- **One engine, no divergence.** Aviator shells the same `copilot` verbs, so there is no second install code path to keep in sync — the CLI stays the single source of truth and Aviator is a thin supervisor. This preserves every red-team hardening (admin-free binaries, proxy/offline, 404 classification, never-destroy) for free.
- **Aviator adds what the one-liner can't:** persistence (LaunchAgent daemon), glanceable health, notifications, and a GUI sign-in — the "stays on, self-healing" promise that a one-shot script can't keep.

So: **Aviator becomes the Bob delivery vehicle** (MDM-pushed app → silent Ring-0/Ring-1 → Bob does nothing but watch a progress bar), while the developer one-liner survives untouched as the terminal-native path. Both feed the same idempotent state machine; Aviator simply keeps running after it finishes.
