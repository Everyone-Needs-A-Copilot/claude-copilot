# Aviator — Distribution, Packaging, Lifecycle & IT/MDM

| | |
|---|---|
| **Status** | Design / Proposed |
| **Repo** | `Everyone-Needs-A-Copilot/aviator` (its own repo) |
| **Stack** | Tauri v2, macOS-first (Windows = Phase D re-skin) |
| **Role** | FACE + SUPERVISOR over the `copilot`/`cc` CLI — not a second brain |
| **Governing persona** | Bob — non-technical accountant, **no admin rights**, possibly behind a corporate proxy |
| **Ties to** | `04-ecosystem-architecture.md` §4.2 (ecosystem.yml), §5 (installer), §8.1 (deprovision/DLP) |

This is the packaging/signing/deploy/self-update/lifecycle slice. The wizard, resolver, and `ecosystem.yml` schema are LOCKED upstream; this doc makes Aviator *ship* into a locked-down enterprise Mac fleet and *stay current* without ever asking Bob for a password he doesn't have.

---

## 1. Signing & notarization (macOS)

Aviator ships as a Developer ID-distributed `.app` inside a `.dmg` — **not** Mac App Store (the MAS sandbox forbids spawning arbitrary subprocesses, and Aviator's whole job is to spawn `copilot`/`cc`/`gh`/`git`). Developer ID + notarization is the only path that both runs outside the sandbox *and* passes Gatekeeper on a stock corporate Mac.

**The pipeline** (`aviator` repo CI, macOS runner):

1. **`tauri build`** produces `Aviator.app` (universal `aarch64` + `x86_64` via `--target universal-apple-darwin`).
2. **Codesign with Developer ID Application** cert (`Developer ID Application: Everyone Needs A Copilot LLC (TEAMID)`), **hardened runtime enabled** (`--options runtime`), `--timestamp`, and a `--deep`-avoiding *inside-out* sign order (sign nested helpers/frameworks first, the `.app` last — `--deep` is deprecated and misses embedded binaries). Tauri v2's bundler drives this via `tauri.conf.json > bundle.macOS.signingIdentity` + `hardenedRuntime: true`, but we pin an explicit `codesign` post-step in CI to control the ordering and the sidecar binaries.
3. **Notarize** the `.app` (zipped) with `notarytool submit --wait` against an App Store Connect API key (stored as CI secret). Notarization is Apple's malware scan + hardened-runtime audit; it returns a ticket.
4. **Staple** the ticket to both the `.app` and the `.dmg` (`xcrun stapler staple`) so Gatekeeper validates **offline** — critical for air-gapped/proxy sites (§7) where the machine can't reach Apple's notarization CDN at launch.
5. **Build + sign + notarize + staple the `.dmg`** itself (the DMG is a separately-signed container).

**Entitlements a menu-bar agent needs** (`Aviator.entitlements`, hardened-runtime-compatible, and deliberately minimal — reinforcing admin-free):

| Entitlement | Why | Not requested |
|---|---|---|
| `com.apple.security.network.client` | reach github.com, Apple notarization, drive `gh` device flow, self-update feed | `network.server` (Aviator is a client, not a listener) |
| `com.apple.security.cs.allow-jit` + `allow-unsigned-executable-memory` | WKWebView (Tauri's webview) needs JIT | — |
| `com.apple.security.cs.disable-library-validation` | load the sidecar `copilot`/`cc` binaries and the `gh` helper it drives | — |
| Keychain access (via `keychain-access-groups` / default app keychain) | store the GH OAuth token + any org token (§5) | — |
| Notifications (`UNUserNotificationCenter`, runtime prompt) | "Needs attention" surfacing (§5), update-ready, deprovision notices | — |
| **No** `com.apple.security.get-task-allow` in release | that's the debug entitlement; leaving it in **fails notarization** | — |

**Explicitly NOT requested:** anything requiring admin/root, no privileged helper (`SMJobBless`), no kernel/system extension, no Full Disk Access. Aviator runs **entirely in userland** — that is the design constraint, not an omission.

**What breaks Gatekeeper (and the guardrail against each):**
- Unsigned/ad-hoc-signed sidecar binaries (`copilot`, `cc`) embedded in `Contents/MacOS/` → **every** Mach-O in the bundle must carry the same Team ID signature. CI signs sidecars explicitly.
- Hardened runtime missing → notarization rejects. Enforced in `tauri.conf.json` + verified with `codesign -dv --verbose=4 | grep runtime`.
- `get-task-allow=true` shipped → reject. CI lints entitlements before submit.
- Unstapled ticket + offline first-launch → "cannot verify" quarantine dialog. We staple both `.app` and `.dmg`.
- Downloading the `.dmg` sets `com.apple.quarantine`; the staple lets Gatekeeper clear it without a network round-trip. IT-pushed installs (§3) land without the quarantine bit at all.

---

## 2. Login-item / background persistence

Aviator is a **single process** with a menu-bar (`NSStatusItem`) face and a background supervisor loop in the same binary — *not* a separate daemon + UI helper. Tauri v2's `tray-icon` feature gives the status-bar item; the app hides its Dock icon (`LSUIElement`/`ActivationPolicy::Accessory`). One process is correct here because the supervisor's job is light (poll `copilot doctor`, watch auth state, drive updates) and a split would double the signing/update surface for no benefit. If a future headless-supervisor need appears, it becomes a bundled `LaunchAgent`-run helper — designed-for, not built.

**Launch-at-login — `SMAppService` (macOS 13+), no admin:**
- `SMAppService.mainApp.register()` registers the app itself as a login item. This is the modern, admin-free replacement for the deprecated `SMLoginItemSetEnabled` and for a hand-installed LaunchAgent. It writes a per-user login item that survives reboot, requires **no** `/Library` write, and appears in System Settings > General > Login Items where the user (or MDM) can see it.
- Tauri wires this via the `tauri-plugin-autostart` plugin, which on macOS 13+ targets `SMAppService`; we pin that path (older `~/Library/LaunchAgents` plist fallback only for macOS 12, which we can drop).

**Survive-app-close & relaunch-on-crash:**
- "Close" in a menu-bar app = hide window, not quit; `tao`/Tauri keeps the run loop alive with the tray present. Cmd-Q is an explicit quit.
- Crash recovery: register a **per-user LaunchAgent** (`~/Library/LaunchAgents/dev.enac.aviator.plist`, `RunAtLoad` + `KeepAlive={SuccessfulExit:false}`) as the *watchdog* — launchd relaunches Aviator if it crashes. This is per-user (`launchctl bootstrap gui/$UID`), admin-free, and complements `SMAppService` (SMAppService handles login-launch; KeepAlive handles crash-relaunch). We ship one or the other by policy: **SMAppService for login + a lightweight launchd KeepAlive plist for crash resurrection**, both user-scoped.
- The supervisor never elevates. If `copilot` needs something privileged (it shouldn't — the ecosystem is admin-free by design, §5.1 of the architecture), Aviator surfaces it as a Needs-attention card, never a `sudo` prompt.

---

## 3. MDM / managed distribution — the IT story

This is the seam the architecture calls out: *"IT teams could modify it to set up their repos."* IT does three things — (a) push the signed app, (b) push a **managed configuration profile** that pre-seeds identity + points at the org's `ecosystem.yml`, (c) optionally push an offboarding command. When (a)+(b) land together, **the first-run wizard is silent — nothing is asked.**

**Deploy at scale (Jamf Pro / Kandji / Intune-for-Mac):**
- Package the notarized `.app` into a **signed `.pkg`** (Developer ID Installer cert) for MDM push, or upload the `.dmg` as a Jamf/Kandji "app". The `.pkg` installs to `/Applications/Aviator.app` (MDM installs as root, no user admin needed). Because MDM-delivered installs skip the quarantine bit, Gatekeeper passes cleanly.
- Ship a **Jamf Composer / Kandji "Custom App"** wrapper or just the raw signed pkg; VPP/ABM not required since this is a custom (non-MAS) app.

**The managed config — a `.mobileconfig` with an `com.apple.ManagedClient.preferences` payload writing the `dev.enac.aviator` preferences domain** (read at runtime via `CFPreferences`/`UserDefaults(suiteName:)`, or `defaults read dev.enac.aviator`). Managed keys (all optional; presence of `OrgSlug`+`EcosystemSeedURL` is what makes the wizard silent):

```xml
<!-- dev.enac.aviator managed preferences (mobileconfig payload) -->
OrgSlug                 = "acme-corp"                      <!-- → cc config layers.org; skips wizard Q2 -->
Department              = "finance"                        <!-- → cc config layers.department; skips Q3 -->
EcosystemSeedURL        = "https://github.acme.com/acme-corp/copilot-ecosystem"  <!-- the ecosystem.yml seed (§4.2). GHES host honored -->
GitHubHost              = "github.acme.com"                <!-- GHES; maps to ecosystem.yml host/api_base/ssh_host -->
AuthMode                = "gh-device" | "ssh-work" | "gh-app:acme-copilot"  <!-- ecosystem.yml auth -->
Host                    = "claude" | "codex"               <!-- which foundation host this fleet runs -->
FoundationMirror        = "https://mirror.acme.com/enac"   <!-- ecosystem.yml foundation.mirror; air-gapped/firewalled (§7) -->
HTTPSProxy             = "http://proxy.acme.com:8080"     <!-- seeds git/gh/updater proxy (§7) -->
UpdateFeedURL           = "https://mirror.acme.com/aviator/appcast.json"  <!-- internal update mirror (§4/§7) -->
UpdateChannel           = "stable" | "pinned:2.4.x"       <!-- staged rollout / version pin (§4) -->
AllowSelfUpdate         = true | false                     <!-- false = IT owns updates via MDM only -->
DisableWizard           = true                             <!-- assert fully-silent first run; error loudly if a required key is missing -->
TelemetryEnabled        = false                            <!-- default off; opt-in -->
Deprovisioned           = false                            <!-- flip true to trigger wipe (below) -->
```

**Silent first-run flow:** on launch, Aviator reads the managed domain *before* showing any wizard UI. If `DisableWizard=true` and the required keys are present, it writes them straight through to `cc config` / `~/.copilot/manifest.local.yml`, derives the seed URL, and runs `copilot doctor --bootstrap --yes` headless — Bob sees a menu-bar icon that goes from "setting up" to "ready," and is **never asked org, dept, host, or auth**. Managed keys are read-only from Bob's side; a user-set value never overrides a managed one (MDM precedence). If a required key is missing under `DisableWizard`, Aviator surfaces a single "ask your IT admin" card rather than falling back to interactive questions (which Bob can't answer).

**MDM-triggered deprovision / wipe (offboarding — ties to architecture §8.1 `copilot deprovision`):**
- IT flips `Deprovisioned=true` (or removes the config profile / uninstalls via MDM). Aviator's supervisor polls the managed domain each cycle; on seeing the flag it runs **`copilot deprovision <org> --yes`** — which wipes materialized `.claude/` items + the org/dept layer clones (the confidential business content), per §8.1 — then clears its Keychain items (GH/org tokens), unregisters `SMAppService` + the KeepAlive plist, and posts a "your Aviator company access was removed" notification.
- The honest boundary from §8.1 holds: local git clones already pulled are exfiltrable; deprovision removes the *sanctioned local copy and the live credential*, it can't claw back a copy someone manually exported. MDM can follow with an app-uninstall command to remove Aviator entirely.

---

## 4. App self-update

The tool that keeps everything updated must update itself. **Mechanism: Tauri v2's built-in updater** (`tauri-plugin-updater`) against a **signed update manifest** — chosen over Sparkle because it's in-stack, cross-platform (Windows re-skin gets it free, §6), and uses Tauri's own minisign/ed25519 signature independent of the Apple codesign chain (defense in depth: a compromised update host still can't ship an unsigned bundle the app will install).

- **Signed manifest:** `latest.json` (version, notes, per-platform `url` + `signature`). Aviator ships the updater **public key** compiled in; the private key signs releases in CI. The plugin verifies the signature *before* swapping the bundle — a bad/MITM'd update is refused, not installed.
- **Feed:** default `https://releases.enac.dev/aviator/latest.json`; overridable by MDM `UpdateFeedURL` to an **internal mirror** so locked-down fleets self-update from inside the perimeter (§7). `AllowSelfUpdate=false` disables it entirely (IT owns updates via MDM push).

**The meta-problem (updater updating the updater):** the updater logic lives *inside* the app bundle, so a normal update replaces the whole `.app` atomically (download → verify signature → verify it's notarized+stapled → swap `/Applications/Aviator.app` → relaunch). The updater never rewrites itself in place mid-run; it stages the new bundle and the *new* process carries the *new* updater. The one genuinely fragile case — a bug in the updater that breaks updating — is caught by the launchd/`SMAppService` watchdog + a floor guarantee: the bootstrap install can always be re-run (`copilot`-style Ring 0) to reinstall Aviator from scratch, and MDM can force-push a known-good pkg over the top.

**Staged rollout + rollback:**
- `UpdateChannel` (`stable`, `beta`, `pinned:2.4.x`) + a rollout percentage encoded in the feed → canary a release to N% before fleet-wide.
- **Rollback on a bad update:** keep the previous `.app` at `/Applications/Aviator.app` swapped to a `~/.aviator/rollback/` slot; a post-update **health probe** (does `copilot doctor` still return, does the webview mount, does auth still resolve) must pass within a launch or two, else auto-revert to the staged previous version and pin the feed to it. IT can also force a downgrade by setting `UpdateChannel=pinned:<good>`.

**App ↔ CLI compat guard (the real coordination problem):** Aviator drives `copilot`/`cc`, whose versions move independently (`VERSION.json` is the CLI's source of truth; Aviator has its own semver). Aviator ships a **compat matrix**: `aviator.compat.json` declares, per Aviator version, the `copilot`/`cc` version *ranges* it supports (`requires: { copilot: ">=1.7 <2", cc: "^2.3" }`). On every launch and before any self-update, Aviator runs `copilot --version` / `cc --version` and:
- **refuses to self-update to an Aviator version whose `requires` range excludes the installed CLI** — it won't jump ahead of the CLI the fleet actually has. The updater checks candidate-version compat against the *live* CLI before downloading.
- if the *installed* CLI drifts out of range under the current Aviator (e.g. CLI updated separately), Aviator surfaces a **Needs-attention** card offering `copilot update`/`cc` bump rather than silently misbehaving.
- the matrix is the same intersect-ranges idea the architecture uses for layer `requires` (§8.4) — one mental model. Neither side updates into a state incompatible with the other.

---

## 5. Auth in a GUI context

Aviator is the *face* over `gh`'s device flow — it never invents its own auth, it drives the CLI's.

- **Device flow, GUI-wrapped:** when a private (org/dept) layer needs auth, Aviator runs `gh auth login --web --hostname <GitHubHost>` (host from managed `GitHubHost`/ecosystem.yml), captures the **8-character user code** + verification URL from `gh`'s output, presents them in a native card ("Enter this code: `WXYZ-1234`"), and **opens the browser** to the verification URL (`open`/`NSWorkspace`). Bob approves in-browser; Aviator polls `gh auth status` until authorized. No PAT, no key, no copy-paste of secrets — just an 8-char code. This is exactly the Bob-path from bootstrap §4, surfaced graphically.
- **Token storage — macOS Keychain:** `gh` already stores its OAuth token in the login keychain via its keychain credential helper; Aviator does **not** duplicate it. Any *additional* secret Aviator itself holds (e.g. an org `gh-app` token) goes in the **login Keychain** via the Security framework (`SecItemAdd`, `kSecClassGenericPassword`, service `dev.enac.aviator`), never in a plist or `UserDefaults`. Tauri's `keyring`/`tauri-plugin-stronghold` is available but the system Keychain is preferred for enterprise (survives, is MDM-auditable, respects keychain ACLs).
- **Re-auth / expiry → Needs-attention state:** tokens and especially **SSO/SAML authorizations** expire. The supervisor's `auth-live` poll (mirrors the architecture's `auth-live` checker) detects a token that no longer authenticates or a lapsed SSO grant, and — critically — **classifies a 404/403 as "needs authorization," never "layer gone"** (architecture §5.3, A-H7). It raises a menu-bar **Needs-attention** badge + notification with a one-click "Re-authorize" that re-runs the device flow (or, for SAML, `gh auth login --web` through the org's SSO authorization URL). Aviator never silently drops a private layer on an auth blip — the foundation keeps working, the company layers show "sign-in needed," matching the anon-first degrade.
- **SSO/SAML orgs:** for orgs enforcing SAML SSO, after device-flow login Aviator drives the **SSO authorization** step and, if the org uses a GitHub App (`AuthMode=gh-app:<slug>`), the install/authorize URL. It surfaces the "Configure SSO for this credential" URL as a clickable card rather than a terminal string.

---

## 6. Windows-readiness (design-for, don't build — Phase D re-skin)

The Tauri core (Rust supervisor, the webview UI, the updater, the compat guard, the `copilot`/`cc` driving) is **shared unchanged**. Only the OS-integration edges swap. Enumerated so Phase D is a re-skin, not a rewrite:

| Concern | macOS (now) | Windows (Phase D) |
|---|---|---|
| Menu-bar / tray | `NSStatusItem` via Tauri `tray-icon` | **System tray** — same Tauri `tray-icon` API, Windows notification-area icon |
| Login + persistence | `SMAppService` + user LaunchAgent | **Task Scheduler** logon task (`schtasks`, per-user, no admin) via `tauri-plugin-autostart`'s Windows path (Run registry key / Startup) |
| Crash relaunch | launchd `KeepAlive` | Task Scheduler "restart on failure" |
| Code signing | Developer ID + notarization + staple | **EV (or OV) code-signing cert** + reputation to clear **SmartScreen**; `signtool` in CI |
| Packaging / delivery | `.dmg` / signed `.pkg` | **MSI** (WiX, Tauri's `wix` bundler) + **winget** manifest; per-user MSI so no admin |
| Secret storage | Keychain (`SecItem`) | **Windows Credential Manager** (DPAPI-backed) — same `keyring` crate abstracts both |
| Managed config | `.mobileconfig` / `defaults` domain | **Intune configuration profile / GPO ADMX** writing `HKCU\Software\ENAC\Aviator` — same key names |
| Deprovision | MDM `Deprovisioned` flag → `copilot deprovision` | Intune remediation / registry flag → same `copilot deprovision` |
| Self-update | Tauri updater | **same Tauri updater** (MSI-aware) |
| Auth | `gh` device flow + browser open | **same** `gh` device flow + `ShellExecute` browser open |

Confirm: the FACE+SUPERVISOR contract, the compat matrix, the managed-key *names*, the device-flow auth, and the update mechanism are all platform-neutral. Windows is a boundary-layer port (six shims), not a second product.

---

## 7. Distribution for locked-down / air-gapped / proxy environments

Ties directly to `ecosystem.yml`'s `foundation.mirror`, `host`/`api_base`, and the offline-bundle path from the bootstrap design.

- **Offline bundle:** IT gets a self-contained `Aviator-offline.dmg` (or pkg) carrying the notarized app *plus* a bundled `copilot`/`cc`/`gh`/`git` userland tarball (the same admin-free binaries the Ring-0 bootstrap unpacks) and a **local seed** — so first run needs **zero** public network. Gatekeeper passes offline because the ticket is **stapled** (§1). The updater feed points at an internal mirror.
- **Proxy-aware networking:** every outbound path honors the managed `HTTPSProxy`/`NO_PROXY`. Aviator seeds `git config http.proxy`, exports `HTTPS_PROXY` for the `gh`/`copilot` subprocesses it spawns, and configures the Tauri updater's HTTP client to use the system/managed proxy. SSH-over-443 fallback (`ssh.github.com:443`) is inherited from the CLI when port 22 is firewalled (architecture §5.1, A-M20).
- **Internal mirror (`foundation.mirror`):** when public github.com is firewalled, `ecosystem.yml.foundation.mirror` / managed `FoundationMirror` redirects all foundation clones to the org's mirror; Aviator's own `UpdateFeedURL` similarly points at an internal Aviator release mirror. GHES is fully parametric via `GitHubHost`/`api_base`. So a fully air-gapped fleet: MDM pushes the offline bundle + a config profile with `FoundationMirror` + `UpdateFeedURL` + `HTTPSProxy` set, and Aviator installs, runs, authenticates (against GHES), and self-updates without a single packet leaving the perimeter.

---

## 8. Summary

Developer ID + hardened runtime + notarize + **staple** (offline Gatekeeper), userland-only entitlements (no admin, no privileged helper). `SMAppService` login item + a user launchd `KeepAlive` watchdog, single process. MDM pushes a signed pkg + a `.mobileconfig` writing the `dev.enac.aviator` domain (`OrgSlug`/`Department`/`EcosystemSeedURL`/`GitHubHost`/`AuthMode`/`Host`/`FoundationMirror`/`UpdateFeedURL`/`DisableWizard`/`Deprovisioned`) → **silent first run**, MDM-flag → `copilot deprovision` wipe. Tauri signed-manifest self-updater with a live **app↔CLI compat matrix** guard (won't jump ahead of the installed `copilot`/`cc`), staged rollout + health-probe auto-rollback. `gh` device-flow auth wrapped in a GUI card, tokens in Keychain, expiry surfaced as Needs-attention. Windows = a six-shim boundary re-skin (tray, Task Scheduler, EV/SmartScreen, MSI/winget, Credential Manager, Intune/GPO) over the identical Tauri core.
