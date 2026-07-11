# Red Team B — Aviator platform/lifecycle failure modes

Adversarial review of the macOS native-app / daemon / MDM / supply-chain layer. No praise. Findings ranked Critical → High → Med → Low. Each: **Area | Failure | Severity | Root cause | Fix**.

The three docs are internally inconsistent on the single most load-bearing decision (process model). That inconsistency is not cosmetic — it changes the failure surface of persistence, self-update, and double-sync. It is Finding 1 and I resolve it explicitly.

---

## CRITICAL

### C1 — Process-model contradiction produces double-sync races and a split-brain daemon
**Area:** Process model / lifecycle
**Failure (concrete):** The **core doc §2** mandates a *separate headless Rust sidecar* (`dev.enac.aviator.daemon`, `~/Library/LaunchAgents/`, `RunAtLoad=true KeepAlive=true`) that "owns the timer loop," PLUS an in-app timer loop as a "fallback" (§2b). The **dist doc §2** mandates a **single process** (tray + supervisor in one binary) with launchd as a *crash watchdog only* (`KeepAlive={SuccessfulExit:false}`). These are mutually exclusive designs shipped in the same architecture. If both are implemented as literally written, a machine runs (a) the always-on daemon's sync loop AND (b) the GUI app's fallback loop concurrently whenever the app is open — two independent schedulers both firing `copilot update --json` / `copilot repair --json` against the same `~/.copilot` tree. The integration doc §5 promises "one in-flight `copilot` invocation at a time per host" but that mutex lives *inside a single process's* coalescer — it cannot coordinate across two separate OS processes (daemon + app) that don't share the lock. Result: concurrent `rsync --delete` reconciles, a race on `copilot.lock`, and a re-materialize that can interleave with a prune → torn `.claude/` tree, or a repair firing while an update holds the tree.
**Severity:** Critical
**Root cause:** No single owner of the timer loop and no cross-process lock. "Fallback loop" + "always-on daemon" were designed by two streams that never reconciled who holds the write lock.
**Fix (this is the resolution the task asks for — see bottom):** Adopt the **dist doc's single-process model**. One signed binary is the tray + supervisor + scheduler. launchd is a **crash-only watchdog** (`KeepAlive={SuccessfulExit:false}`, NOT `KeepAlive=true`). Kill the headless sidecar target and the in-app fallback loop entirely. If a headless-when-logged-out need ever appears, it is a *future* second target that acquires an **exclusive flock on `~/.copilot/run/aviator.lock`** and the GUI then *attaches* read-only over IPC and never runs its own loop. The CLI must ALSO defend itself: `copilot update` must take its own file lock on `copilot.lock` and fail fast if held, so no GUI/daemon confusion can ever double-write. Do not rely on the app to serialize the CLI.

### C2 — `KeepAlive=true` (core doc) makes launchd fight the user and thrash on repeated crash
**Area:** Persistence / launchd
**Failure:** Core doc §2a specifies `KeepAlive=true`. That is unconditional resurrection: launchd relaunches the process the instant it exits *for any reason*, including a clean `Cmd-Q`/"Quit Aviator." Bob quits Aviator; launchd immediately relaunches it; the menu-bar icon reappears. The user cannot quit their own app. Worse, a bundle that crashes *on launch* (see C3/C6) under `KeepAlive=true` becomes a **crash-loop storm** — launchd relaunches as fast as the throttle allows (10s minimum), pegging CPU, spamming the action log, and (if a bad self-update is the cause) making the machine unusable until MDM force-pushes a good pkg. `SMAppService` login registration + a `KeepAlive=true` LaunchAgent *also* means two independent subsystems both try to launch at login → double-launch race, two processes briefly, both grabbing the tray.
**Severity:** Critical
**Root cause:** `KeepAlive=true` conflated with "keep synced." KeepAlive is a *crash* policy, not a *stay-running* policy.
**Fix:** `KeepAlive={SuccessfulExit:false}` ONLY (relaunch on crash, respect clean quit) — as the dist doc already says. Add `ThrottleInterval` and a launch-failure circuit breaker: if the app exits non-zero N times within a window, the watchdog writes a sentinel and *stops* relaunching, surfacing "Aviator can't start — reinstall" rather than crash-looping. Never run both `SMAppService.register()` AND a `RunAtLoad=true` plist; pick `SMAppService` for login, launchd for crash-only (`RunAtLoad=false`).

### C3 — Health-probe rollback cannot run if the bad update won't launch
**Area:** Self-update
**Failure:** Dist doc §4 promises "a post-update health probe (does `copilot doctor` return, does the webview mount, does auth resolve) must pass within a launch or two, else auto-revert." But the health probe is **code inside the new bundle**. If the bad update crashes *before* the probe runs — segfault on webview init, a panic in `main.rs` before the scheduler starts, a corrupt dylib — there is no running code to evaluate the probe, stage the rollback, or re-pin the feed. The rollback logic is trapped inside the thing that won't start. Under `KeepAlive`, this is C2's crash-loop. The "floor guarantee" (re-run bootstrap / MDM force-push) requires a *human* (IT) to notice — it is not auto-recovery, contradicting the "auto-revert" claim.
**Severity:** Critical
**Root cause:** Rollback owner lives inside the artifact being validated. Classic "who watches the watcher" — the new binary is asked to prove its own health.
**Fix:** Move the health gate to a **separate, older, trusted supervisor**: the launchd watchdog (a tiny stable stub that itself is *never* self-updated) performs the update swap and the post-swap launch check. Sequence: watchdog stages new bundle to `~/.aviator/staged/`, keeps current at `/Applications/Aviator.app`, launches staged copy with `--self-test`, waits for a **liveness heartbeat file** written by the new process within a timeout; only on heartbeat does it promote staged→current and repoint. No heartbeat → discard staged, keep current, mark the version poisoned so it's never retried, notify. The heartbeat must be written *early* in new-process startup (before webview), so "crashes after start" still counts as pass only if it got far enough to be functional. This makes rollback independent of the new bundle's ability to fully run.

### C4 — Compat-matrix deadlock: nobody is designated to update the vendored CLI
**Area:** Self-update / compat matrix / supply chain
**Failure:** The compat matrix (dist §4) gates **both** directions: Aviator refuses to update to a version whose `requires` excludes the installed CLI; and if the CLI drifts out of range it raises Needs-attention. But the docs never answer **who updates the vendored `copilot`/`cc` binaries** inside the app bundle. Three actors could: (a) Aviator's self-update (they're bundled, so a full `.app` swap replaces them — but only when Aviator itself updates, which the matrix may be *blocking*); (b) `copilot update` updating itself in `~/.copilot/bin`; (c) the bootstrap. Deadlock scenario: fleet CLI moves to `copilot 2.0`. Aviator 1.2 declares `requires copilot >=1.7 <2` → Aviator sees installed CLI (if `~/.copilot/bin` was bumped to 2.0) out of range → refuses to drive it, shows Needs-attention "bump CLI"… but the CLI is *already* at 2.0; the fix is to update *Aviator*, and the only Aviator that supports copilot 2.0 is Aviator 2.0 — which Aviator 1.2's updater may itself refuse to install if it checks candidate-compat against the *vendored* (still 1.7) binary rather than the installed 2.0. The two "prefer installed vs prefer vendored" resolution orders (dist §5.1) make it ambiguous which CLI version the matrix even reads. Bob is stuck with a red badge and no admin rights to fix it.
**Severity:** Critical
**Root cause:** Bidirectional gate with no designated escape actor and an ambiguous "which CLI version is authoritative" rule. A mutual-exclusion lock with no lock-breaker.
**Fix:** Declare an explicit ownership: **Aviator owns the vendored CLI; `copilot self-update` is disabled when running under Aviator** (`COPILOT_MANAGED_BY=aviator`) so there is ONE updater of the CLI, avoiding a & c fighting. The matrix must be evaluated against **one canonical version** — the one Aviator will actually invoke per §5.1 resolution order — not vendored-vs-installed ambiguously. Break deadlock: when the installed CLI is *newer* than Aviator supports, Aviator must treat that as "update ME" and the updater must check candidate-Aviator compat against the **installed** CLI, so a newer CLI *pulls* a newer Aviator rather than blocking it. MDM `AllowSelfUpdate=false` fleets: IT must push CLI and app as a **version-locked pair** (single pkg carrying both), never independently, or the deadlock is guaranteed.

### C5 — User-writable `dev.enac.aviator` preference domain = attacker-controlled update feed / mirror
**Area:** Security surface / MDM precedence
**Failure:** Managed config is delivered via `com.apple.ManagedClient.preferences` writing the `dev.enac.aviator` domain, read with `CFPreferences`/`UserDefaults`. The doc asserts "managed keys are read-only from Bob's side; a user-set value never overrides a managed one." That is **only true for keys that are actually managed**. `CFPreferences` merges domains: a *managed* value wins, but for **any key IT did not set**, the **user-domain value (`~/Library/Preferences/dev.enac.aviator.plist`, world-writable by that user, no admin) is honored**. On an *unmanaged* Mac (the developer / solo / small-team path — the majority of non-Bob installs) there is NO managed domain at all, so every key including `UpdateFeedURL`, `FoundationMirror`, `HTTPSProxy`, `AuthMode` is user-writable. A local attacker (or malware running as the user) runs `defaults write dev.enac.aviator UpdateFeedURL https://evil/appcast.json` and points the auto-updater at an attacker mirror. Even the Tauri minisign key defends the *bundle* signature — but `FoundationMirror`/`EcosystemSeedURL` repointing redirects **layer clones** (agents, skills, MCP decls = executable-adjacent content) to an attacker repo, and those are gated by the ecosystem `root_key` sig — *unless* the attacker also controls the seed that names the trust root. Repointing `HTTPSProxy` enables a full MITM of `gh`/`git`/updater traffic.
**Severity:** Critical
**Root cause:** Security-relevant config (update feed, mirror, proxy, trust seed) read from a **user-writable preference domain** with no integrity check on unmanaged machines. Trusting `UserDefaults` for a supply-chain input.
**Fix:** Security-sensitive keys (`UpdateFeedURL`, `FoundationMirror`, `EcosystemSeedURL`, `HTTPSProxy`, `GitHubHost`, `AuthMode`, `AllowSelfUpdate`, `Deprovisioned`) must be honored **only from the managed domain** (`CFPreferencesCopyAppValue` + verify it came from a managed source via `CFPreferencesAppValueIsForced`). If a key is present only in the user domain, IGNORE it and fall back to the compiled-in default (`releases.enac.dev`) — never let user-domain override the update feed. The Tauri updater's minisign pubkey (compiled-in) is the real defense for the *app*; extend the same "trust root is compiled-in, not config" principle to the ecosystem seed on unmanaged machines. Log any user-domain attempt to set a protected key as a tamper event.

---

## HIGH

### H1 — Cross-repo signing: vendored `copilot`/`cc` built in a DIFFERENT repo, signed with (maybe) a different key
**Area:** Notarization / supply chain
**Failure:** Every Mach-O in the bundle must carry the *same Team ID* signature and be notarized, or Gatekeeper rejects the whole `.app` (dist §1). But `copilot`/`cc` are built in `claude-copilot` (a separate repo/CI), and Aviator vendors them into `src-tauri/bin/`. If claude-copilot CI signs them with a different cert, doesn't sign them, or ships a Python/node userland tarball with hundreds of unsigned nested Mach-Os (`.so` files in a bundled interpreter), the Aviator notarization submit fails or — worse — the inside-out re-sign in Aviator CI silently re-signs someone else's binary, breaking any independent verification. There is no stated pinning of *which SHA* of the CLI gets vendored, so a release could vendor a CLI older than the fleet's, tripping the compat matrix (C4) on day one.
**Severity:** High
**Root cause:** Two repos, two CI pipelines, one signature requirement, no cross-repo artifact contract.
**Fix:** claude-copilot CI must publish `copilot`/`cc` as **already-signed, notarized, universal** artifacts with a Team-ID signature and a pinned SHA + version, consumed by Aviator CI as a locked dependency (checksum + version in `aviator.compat.json`). Aviator CI *verifies* (`codesign -dv --verbose=4`, `spctl -a`) rather than re-signs. If the CLI userland is an interpreter tarball with many nested Mach-Os, it must be signed nested-first in ITS repo. Aviator's release blocks if the vendored CLI version is older than the compat-matrix floor for that Aviator version.

### H2 — App deleted from /Applications but LaunchAgent + SMAppService persist = orphan
**Area:** Persistence / uninstall
**Failure:** User (or a naive uninstall) drags `Aviator.app` to Trash. The `~/Library/LaunchAgents/dev.enac.aviator.plist` (crash watchdog) remains and its `Program` path now points at a nonexistent binary → launchd logs errors every load, or if a stale/rollback copy exists at `~/.aviator/rollback/` it may relaunch *that*. `SMAppService` registration also persists as a dangling login item ("Aviator" ghost in Login Items pointing nowhere). MDM-uninstall via pkg removal has the same gap — pkg receipts remove `/Applications/Aviator.app` but do not run `launchctl bootout` or `SMAppService.unregister()`, both of which require the *app* to run them. Deprovision (dist §3) unregisters these, but plain deletion never calls deprovision.
**Severity:** High
**Root cause:** LaunchAgent/SMAppService lifecycle is owned by a process that no longer exists after deletion; no uninstaller.
**Fix:** Ship a signed uninstaller (`.command` or pkg preflight) that runs `launchctl bootout gui/$UID/dev.enac.aviator`, `SMAppService.mainApp.unregister()`, removes the plist, clears Keychain items. The launchd watchdog plist should include a guard: on load, if `Program` path is missing, `bootout` itself. MDM uninstall must run a pre-removal script doing the same. Document that "drag to Trash" is insufficient.

### H3 — `SMAppService` requires user approval Bob may never grant (or may toggle off)
**Area:** Persistence / macOS 13+ approval
**Failure:** On macOS 13+, `SMAppService.register()` surfaces "Aviator added a login item" and the item lands in System Settings > Login Items where the user can **toggle it off**. Bob (non-technical, told nothing) may see the notification as spam and disable it, or IT's onboarding never mentions it. Once off, Aviator doesn't launch at login → no background sync → the "stays on, self-healing" promise silently dies, and there is no signal to IT that it happened (the machine just stops reporting telemetry, indistinguishable from a powered-off Mac). Managed login-item approval via MDM (`com.apple.servicemanagement` payload with the bundle/team ID) is the only way to make it non-toggleable, and the docs never mention pushing that payload.
**Severity:** High
**Root cause:** Relying on user-granted login-item approval for an IT-mandated agent, with no managed-login-item MDM payload and no detection of the disabled state.
**Fix:** For managed fleets, MDM MUST push a **Service Management managed login item payload** (`com.apple.servicemanagement`, `RuleType=BundleIdentifier`) so the login item is force-approved and greyed-out (user can't disable). Aviator should detect `SMAppService.status == .requiresApproval / .notFound` on each launch and surface a "background running is off — turn it on" card; telemetry should emit a distinct "persistence disabled" signal so IT can tell it apart from an offline machine.

### H4 — `DisableWizard=true` with a missing required key: brick-vs-loud is under-tested and racy
**Area:** MDM / malformed config
**Failure:** Dist §3 says under `DisableWizard=true` with a missing required key, Aviator shows "ask your IT admin" rather than falling back to interactive. Good intent — but the failure modes multiply: (a) **partially-applied profile** — MDM pushes the profile but the network drops mid-apply, so `DisableWizard=true` lands but `EcosystemSeedURL` doesn't yet → Aviator hard-stops on first launch before MDM finishes; a transient becomes a permanent "ask IT" for a machine that would self-heal in 30s. (b) **malformed value** — `EcosystemSeedURL="htps://…"` (typo) or a URL to a repo that 404s: is that "missing" (→ ask IT) or "present but bad" (→ what?)? Undefined. (c) A managed `UpdateFeedURL` that's malformed disables self-update silently. (d) type coercion: `DisableWizard` delivered as string `"true"` vs bool `true` in the plist — `UserDefaults.bool(forKey:)` returns false for the string in some encodings, silently re-enabling the wizard for Bob who can't answer it.
**Severity:** High
**Root cause:** No schema validation / typing / settling-window on the managed domain; "missing" vs "malformed" vs "not-yet-applied" not distinguished.
**Fix:** Validate the managed domain against a typed schema on read (bool is bool, URL parses, host resolves-shaped). Distinguish three states: absent (retry with backoff for a settling window before declaring "ask IT"), present-but-invalid (immediate "IT config error: <key>" — loud, distinct string), present-valid (proceed). Never fall through to Bob-interactive under `DisableWizard`. Re-read the managed domain a few times over the first minutes to absorb partial-apply.

### H5 — HMAC `machine_id` collides / re-identifies across users on a shared Mac; personal-layer name can leak
**Area:** Multi-user + telemetry privacy
**Failure:** `machine_id = hmac_sha256(hardware_uuid, org_salt)`. The **hardware UUID is per-Mac, not per-user** — so two macOS accounts (Bob + Alice) on one shared Mac, same org, produce the **identical `machine_id`**. IT's "distinct machine" count is wrong (two humans = one id), and their per-machine health blends two users' state. Conversely `org_salt` shared across the fleet means the HMAC is a stable pseudonym an org admin can correlate with the single user assigned to a laptop → **re-identification is trivial** for org IT (they know who has which hardware UUID via MDM inventory). Combined with `usage[].name` at org/dept scope, IT can see "this identifiable person fired the `layoff-memo` skill 12 times." The doc claims personal-layer content is never collected, but §6.2's `usage` filters by layer — a **misclassified layer** (a personal skill that shadows an org skill, `override-stale`) could be counted under the org `name`, leaking a personal skill's *name* (H, because names can be sensitive: `divorce-filing`, `job-search`).
**Severity:** High
**Root cause:** machine_id keyed on per-*device* UUID not per-*user*; salt is org-wide (not per-install-random) so it's a stable cross-referenceable pseudonym; layer classification is the only guard against personal-name leakage and it's fallible.
**Fix:** Key `machine_id` on `hmac(hardware_uuid + posix_uid, per_install_random_salt)` so each *user account* is distinct AND not reversible from MDM inventory (store the random salt locally, never transmit it). For usage, emit only items whose `winning_layer ∈ {org,dept,foundation}` **as computed by the CLI's `resolve --explain`**, and drop any item where `shadowed_by` names a personal path — never trust a name string's apparent layer. Add an explicit allowlist test: personal names must be un-emittable by construction.

### H6 — `--json` schema drift gates only one direction; a newer CLI can feed an older Aviator
**Area:** --json contract (top risk per integration doc)
**Failure:** Integration §8 mitigates Aviator misparsing a NEW schema by hard-refusing an unrecognized `schema_version`. But the compat is asserted to gate BOTH directions and the design only guards one. Case: **CLI updated to schema 2.0, Aviator still 1.x** → Aviator sees `schema_version: 2.0`, refuses, degrades to "run doctor in a terminal" — safe but Bob can't use a terminal, so the app is bricked-to-useless for exactly the persona that can't recover. Reverse case: **Aviator updated to expect schema 2.0, CLI still emits 1.0** → if Aviator only checks "is this a version I recognize" and 1.0 is still in its recognized set, it may parse a 1.0 payload while *expecting* 2.0 fields (e.g. a new `destructive` flag absent in 1.0) → a field that's *missing* defaults to `false`/absent → Aviator treats a would-be-destructive repair as safe. Missing-field-defaults-to-safe-looking is the silent bypass §8 warns about, arriving through the *old-CLI* direction it doesn't cover.
**Severity:** High
**Root cause:** Version gate is a recognizer, not a **compatibility contract**; absent fields default to permissive; the Bob-can't-use-terminal degrade path is a dead end for the target persona.
**Fix:** Gate on an explicit `min_schema`/`max_schema` range per Aviator version, checked against the CLI's emitted `schema_version` on **both** sides; a CLI schema older than Aviator's floor is as fatal as one newer. Make missing security-relevant fields **fail-closed**: absent `destructive`/`signed`/`severity` ⇒ treat as destructive/unsigned/fail, never as safe. Replace the "run doctor in a terminal" dead-end with an in-app "Aviator and your CLI versions don't match — click to update" that drives the paired update (C4), because Bob has no terminal.

### H7 — Two users each run their own Aviator against one shared `~/.copilot`? No — but the daemon/lock story across users is unspecified
**Area:** Multi-user / shared state
**Failure:** `~/.copilot` is under `$HOME` (per-user), so two accounts get separate trees — mostly fine. But: (a) the **login keychain** is per-user, so `gh`'s token and Aviator's org token are per-user — a shared kiosk Mac where one auth is expected to serve all users breaks; each user must device-flow separately, and a kiosk/lab auto-login user can't. (b) **Fast user switching**: both users' Aviators are running *simultaneously* (fast-switch doesn't quit the background session's app), both with menu-bar items on their respective sessions, both watchdog LaunchAgents loaded under different `gui/$UID` domains — generally OK since trees differ, but if the org uses a machine-wide mirror path or a shared `/Users/Shared` cache (offline bundle §7 could land there), they collide with no lock. (c) The offline bundle's vendored binaries in `/Applications/Aviator.app` are shared, but each user's SMAppService/watchdog is separate — a per-user approval (H3) must happen for *each* account.
**Severity:** High
**Root cause:** Per-user vs per-machine boundary not drawn; keychain-per-user vs kiosk-shared-auth unaddressed; any `/Users/Shared` cache is unlocked.
**Fix:** State explicitly that Aviator is **per-user** (tree, keychain, login item, watchdog all per-`$UID`); no `/Users/Shared` mutable state, or if an offline binary cache lives there it is **read-only** and never written by a user session. For kiosk/lab (auto-login, no device flow possible), support a **machine credential** (`AuthMode=gh-app` with an MDM-provisioned token in the *system* keychain) rather than per-user device flow. Document that fast-user-switching runs N Aviators and that's expected because trees are disjoint.

---

## MEDIUM

### M1 — MDM removing the profile: deprovision or just un-manage? Ambiguous and dangerous either way
**Area:** MDM edges
**Failure:** Dist §3 lists "removes the config profile / uninstalls via MDM" as a deprovision trigger *alongside* `Deprovisioned=true`. But profile removal is the normal act of **un-enrolling a machine from MDM** or **re-scoping** — it does NOT necessarily mean "wipe this user." If profile-removal ⇒ deprovision, then an IT admin re-organizing Smart Groups accidentally wipes company content off compliant machines. If profile-removal ⇒ just un-manage (keep content), then true offboarding via un-enroll leaves company content on a departing employee's Mac. The doc wants it both ways.
**Severity:** Medium
**Root cause:** Overloading "profile absent" to mean both "un-managed" and "deprovisioned."
**Fix:** Only an **explicit** `Deprovisioned=true` (or a dedicated MDM command / sentinel) triggers wipe. Profile *absence* ⇒ Aviator reverts to unmanaged/degraded (surfaces "no longer managed by IT," keeps working on last-known config) and does NOT wipe. Offboarding must set the flag explicitly before un-enroll, or push a one-shot deprovision command — never rely on profile removal.

### M2 — `Deprovisioned` flipped true then flipped back (flapping) = wipe then can't cheaply restore
**Area:** MDM edges / idempotency
**Failure:** IT flips `Deprovisioned=true` (mis-scoped Smart Group), Aviator wipes materialized `.claude/` + org/dept clones + clears Keychain tokens. Seconds later IT fixes the scope, flag flips back to `false`. Aviator now must re-clone everything and Bob must **re-authenticate** (token was cleared) — the device flow needs a human. A transient admin fat-finger costs every affected user a re-auth and a full re-pull, and any dirty personal work that was in `retained_dirty` is fine but the disruption is fleet-wide.
**Severity:** Medium
**Root cause:** Deprovision is treated as instantaneous/irreversible on a flag that can flap; no debounce, no soft-delete.
**Fix:** Debounce the wipe (confirm the flag persists across a settling window before acting), and make deprovision a **two-phase soft-then-hard**: phase 1 stops serving + revokes tokens but *quarantines* clones for a grace window; a flip-back within the window restores from quarantine (still needs re-auth, but no re-clone). Only after the grace window does the hard wipe run. Log both transitions.

### M3 — Quarantine/Gatekeeper on the FIRST self-updated bundle (not MDM-delivered)
**Area:** Notarization / self-update
**Failure:** Dist §1 notes MDM-delivered installs skip the quarantine bit. But a **self-update** downloaded by the Tauri updater over the network (from `UpdateFeedURL`) *does* get written by the app — Tauri's updater replaces the bundle in place. If the internal mirror serves it over a path that triggers quarantine, or the swapped bundle's staple isn't re-verified offline, the *relaunch* after self-update can hit "cannot verify" on an air-gapped machine — exactly the §7 fleet that can't reach Apple. The staple is on the *shipped* artifact; does the updater preserve/verify the staple on the swapped bundle?
**Severity:** Medium
**Root cause:** Staple-preservation across self-update swap unspecified; offline Gatekeeper re-check after swap not guaranteed.
**Fix:** The updater must verify the new bundle is stapled (`stapler validate`) *before* swap, and the release artifact in the mirror must be the stapled one. On air-gapped fleets, prefer MDM-pushed updates (`AllowSelfUpdate=false`) so no self-written bundle ever needs an online Gatekeeper check; if self-update is on, `spctl -a -vv` the staged bundle offline before promoting.

### M4 — Malicious/compromised Aviator update: minisign key compromise ⇒ full fleet RCE on a timer
**Area:** Security surface / threat model
**Failure:** Aviator holds a live `gh` token and auto-materializes executable-adjacent content on a timer. If the **Tauri minisign private key** (CI secret) is compromised, an attacker ships a signed malicious Aviator update that passes minisign AND is Developer-ID signed (if the codesign cert is also popped) → every machine auto-installs it and now runs attacker code with the user's `gh` token and the ability to rewrite `~/.claude` agents. This is a single-key fleet-wide RCE with a timer as the delivery. The doc treats minisign as "defense in depth" but it's a single point whose compromise is catastrophic *because* the agent is always-on and auto-pulling.
**Severity:** Medium (High impact, lower likelihood given key custody)
**Root cause:** Single signing key + auto-install + live token + executable content = high blast radius; no update transparency or second signer.
**Fix:** Require **two-of-N signing** (or a transparency log / Rekor-style append-only witness) for Aviator releases so one popped key ≠ fleet RCE. Keep the codesign cert and minisign key in **separate custody/HSMs**. Consider a staged-rollout + anomaly-halt: if telemetry shows post-update crash/behavior spikes, auto-halt the rollout. Least-privilege the `gh` token scopes.

### M5 — Vendored CLI older than the fleet on a cold-install machine
**Area:** Supply chain / version lockstep
**Failure:** Bob's brand-new Mac gets Aviator.pkg via MDM. Aviator vendors `copilot 1.7`. The fleet has moved to `copilot 1.9` and the org's `ecosystem.yml` uses a feature only in 1.9. Aviator prefers the vendored 1.7 (nothing installed yet, §5.1), runs `copilot derive`, which chokes on a 1.9-only field → wizard fails on a fresh machine for the target persona.
**Severity:** Medium
**Root cause:** Vendored CLI pinned at Aviator build time can lag the fleet's live CLI; cold machine has no newer copy to prefer.
**Fix:** On first run, after network is up, Aviator should check the fleet/mirror for a newer compatible CLI and `copilot self-update` the vendored copy into `~/.copilot/bin` *before* running derive — vendored binary is a cold-start floor, not the final version. Gate the update through the compat matrix (C4). MDM offline fleets must keep the offline bundle's CLI reasonably current.

### M6 — Keychain ACL / prompt on the self-updated (re-signed) binary
**Area:** Auth / Keychain
**Failure:** Keychain items are ACL-bound to the *signing identity / designated requirement* of the app that created them. After a self-update swaps the bundle, if the designated requirement changes (cert rotation, different provisioning), macOS may prompt "Aviator wants to access the keychain" — which Bob, told nothing, denies, breaking the org token retrieval silently. Also `gh`'s own token is under `gh`'s keychain ACL, not Aviator's — Aviator "drives gh" but if it ever reads the token directly it'll prompt.
**Severity:** Medium
**Root cause:** Keychain ACL tied to code-signing designated requirement; self-update / cert rotation can invalidate it; cross-app (gh vs Aviator) keychain access.
**Fix:** Keep a **stable designated requirement** (same Team ID + a DR based on TeamID not cert serial) across updates so keychain ACLs survive. Never read `gh`'s keychain item directly — only invoke `gh` and parse its status (already the design; enforce it). Set keychain item ACL to allow the app's DR non-interactively.

### M7 — Notification permission denied ⇒ the escalation ladder's top rungs go silent
**Area:** Notifications / escalation
**Failure:** The entire escalation model (integration §7, core §1.3) depends on `UNUserNotificationCenter` to surface auth-expiry, security-trailer, held-major, "couldn't fix it." macOS requires a runtime permission prompt; Bob may deny it, or MDM may not pre-grant it. Denied ⇒ Aviator can change the icon but a Mac with the window closed shows nothing → a security-trailer change or an auth expiry sits invisible indefinitely. "Notifications are rare by design" makes each one high-value, so losing them is worse.
**Severity:** Medium
**Root cause:** Human-attention channel is optional and revocable, with no fallback for the closed-window case.
**Fix:** MDM should push a **Notifications configuration profile** (`com.apple.notificationsettings`) pre-authorizing Aviator's bundle ID for managed fleets. Detect denied-notification state and surface a persistent menu-bar badge + a first-launch "turn on notifications so I can warn you" card. For IT-critical classes (security, revoke), escalate via telemetry (§6) even when the local notification can't fire.

---

## LOW

### L1 — `LSUIElement`/Accessory app + wizard window focus
**Area:** UX/platform nit
**Failure:** An Accessory-policy app (no Dock icon) can have trouble bringing its wizard window to the foreground / getting keyboard focus on first launch — the window can open behind others with no Dock icon to click. Bob "double-clicks Aviator and nothing happens."
**Severity:** Low
**Fix:** Temporarily set `ActivationPolicy::Regular` while the wizard window is open (Dock icon appears during setup), revert to `Accessory` after. Explicitly `activate(ignoringOtherApps:)` the wizard window.

### L2 — Action log is "append-only" but lives in a user-writable path
**Area:** Observability / tamper-evidence
**Failure:** Integration §3 promises a "tamper-evident" append-only action log, but a file under `$HOME` is fully rewritable by the user (or malware as the user) — it is append-only by convention, not enforcement. "Tamper-evident" overclaims.
**Severity:** Low
**Fix:** Either drop the "tamper-evident" claim (call it a local history) or hash-chain entries and periodically anchor the head hash to the org telemetry endpoint so local truncation/edit is *detectable* server-side.

### L3 — `copilot`/`cc` absolute-path invocation vs a relocated bundle
**Area:** CLI invocation
**Failure:** §5.1 invokes the CLI "always by absolute path" to dodge the `gh copilot` PATH collision. But if the user moves `Aviator.app` (e.g. to a subfolder) or runs from a translocated (quarantined) path, the vendored-binary absolute path shifts; and `~/.copilot/bin` resolution assumes a fixed `$HOME`. Fine normally, but app translocation (Gatekeeper randomized path on first quarantined launch) can break the vendored-path assumption.
**Severity:** Low
**Fix:** Resolve the vendored binary relative to the running bundle's `Bundle.main.bundleURL` (translocation-safe), not a hardcoded `/Applications` path. MDM installs avoid translocation (no quarantine), so this mainly bites the developer/manual-install path — handle it, don't assume `/Applications`.

---

## RESOLUTION — the single-vs-daemon process model

**The dist doc is correct; the core doc is wrong. Ship ONE process.**

- **One signed binary** = tray + supervisor + scheduler. It owns the timer loops (sync 6h, doctor 1h, freshness 15m) *while running*.
- **launchd is a crash-only watchdog** — `KeepAlive={SuccessfulExit:false}`, `RunAtLoad=false`. NOT `KeepAlive=true` (C2). It respects Cmd-Q and does not fight the user.
- **`SMAppService` handles launch-at-login** (one mechanism), managed-login-item MDM payload for fleets (H3). launchd handles *only* crash resurrection. They never both `RunAtLoad`.
- **Delete the headless sidecar target AND the in-app fallback loop** from the core doc. They create the double-sync race (C1) and buy nothing: the supervisor's work is light (poll doctor, drive updates) and requires no headless-when-logged-out capability that justifies a second process and a doubled signing/update surface.
- The **CLI must self-serialize** (`flock` on `copilot.lock`) so even a future second process can never double-write. The app is not the lock; the CLI is.
- The **update health-gate/rollback must live in the tiny stable watchdog, not the self-updated bundle** (C3), because a bundle that won't launch can't roll itself back.

"Stays on, keeps synced" is satisfied by: SMAppService relaunch-at-login + a crash watchdog + a light supervisor loop that only runs while alive. You do **not** need a headless daemon for a poll-every-6h workload, and adding one doubles the notarization surface, the update surface, and creates the concurrency bug that is the worst failure in this design.

---

## TOP 5 MUST-FIX

1. **C1 — Kill the dual process model; ship single-process + CLI-side `flock`.** The core-doc daemon + the app fallback loop both firing `copilot update` is a concrete `copilot.lock`/prune race that corrupts `.claude/`. Resolve to the dist doc's model. (Also fixes C2's `KeepAlive=true`.)
2. **C3 — Move the self-update health probe/rollback into the stable launchd watchdog, gated on an early liveness heartbeat.** As written, a bad bundle that crashes on launch traps its own rollback logic → bricked app, and under `KeepAlive` a crash-loop. This is the failure that leaves Bob with a dead menu bar and no terminal.
3. **C5 — Read all security-sensitive config (`UpdateFeedURL`, `FoundationMirror`, `EcosystemSeedURL`, `HTTPSProxy`, `AllowSelfUpdate`, `Deprovisioned`) ONLY from the forced/managed domain; ignore user-domain values for those keys.** Otherwise any local user (esp. on the majority *unmanaged* installs) repoints the auto-updater/mirror at an attacker → supply-chain RCE via a preference write.
4. **C4 — Designate one owner of the vendored CLI (Aviator) and make the compat matrix evaluate ONE canonical version; a newer CLI must PULL a newer Aviator, not deadlock it.** Ship CLI+app as a version-locked pair on `AllowSelfUpdate=false` fleets. Prevents the red-badge-no-admin dead end.
5. **H1 — Establish a cross-repo signing contract: claude-copilot publishes already-signed/notarized `copilot`/`cc` with pinned SHA+version; Aviator CI verifies, never re-signs, and blocks release on a stale vendored CLI.** Without it, notarization is flaky and day-one compat-matrix failures are baked in.

**Single most dangerous platform failure:** C1 — the two schedulers (core-doc daemon loop + app fallback loop) concurrently driving `copilot update`/`repair` on one `~/.copilot` with no cross-process lock. It silently corrupts materialized state on ordinary machines, needs no attacker, and the docs actively specify both loops.
