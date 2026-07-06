# Red-Team A — Aviator (the menu-bar FACE+SUPERVISOR) vs the 12 ecosystem use cases

Scope: attack the **app layer** only. The 30 CLI-level gaps in §9 of the architecture are treated as fixed; every finding below is a failure Aviator *introduces or re-opens* by being the delivery/supervision surface — especially where a use case silently assumes Bob is a reliable actor. Ranked Critical → High → Med.

---

## CRITICAL

### C1 — Managed config missing a required key + `DisableWizard=true` = silent mis-provision
- **Use case:** UC1 (onboarding, MDM/silent path §3.2)
- **Failure (step-level):** Silent mode pre-fills W2/W4/W5/W6 from the `com.enac.aviator` profile and **removes the ability to ask**. If `managed.department` (or `managed.org`, or `ecosystem_url`) is absent while the wizard is suppressed, W5 can neither derive nor prompt. The wizard either hangs on a progress bar or completes wired to an empty/wrong department — and then marks the icon **Healthy**. Bob has no idea; IT has no idea (telemetry is off pre-setup, see C5).
- **Severity:** Critical
- **Root cause:** Silent mode strips the fallback (asking) without a guarantee that every suppressed field is derivable. No pre-flight validation that the managed profile is *complete* for the silent path.
- **Fix:** Schema-validate the managed profile before entering silent mode. Any required key missing → fail **closed** into a distinct **"IT configuration incomplete — contact IT"** state (never a guess, never a generic error, never Healthy), and emit an IT-escalation signal (see C5 fix).

### C2 — Vendored `~/.copilot/bin` binaries are killed by Gatekeeper/quarantine
- **Use case:** UC1 (cold-machine Bob path, §5.1 vendor-with-fallback)
- **Failure:** §5.1 unpacks the userland `copilot`/`cc`/`tc` binaries into `~/.copilot/bin` and invokes them by absolute path. Those files are **outside the signed/notarized app bundle**, so they carry the quarantine xattr and are subject to Gatekeeper as independent executables. On current macOS a background-spawned, un-notarized binary is hard-blocked with **no interactive override**. Every CLI spawn dies; Aviator (which computes nothing itself) can render nothing but failures — or worse, mis-reads the spawn failure as a benign state.
- **Severity:** Critical
- **Root cause:** The design notarizes the *app*, not the *payload it drops and executes*. "Admin-free binaries" solved the install-permission problem but not the code-signing/Gatekeeper problem.
- **Fix:** Notarize the vendored binaries independently (or exec them from *inside* the signed bundle rather than copying out); the `.pkg` postinstall strips quarantine (`xattr -d com.apple.quarantine`). Add a `cli-spawnable` doctor check so a Gatekeeper kill surfaces as a distinct, named finding, not a generic red.

### C3 — Security-shadow (UC8) relies on a Bob notification Bob never sees
- **Use case:** UC8 (override hides a security fix — the whole point is the signal reaches the user)
- **Failure:** The `security:` trailer + `override-stale` correctly *materializes* the upstream fix (good) but Bob's **personal override still wins** — he keeps running the vulnerable overridden agent. The only signals are (a) a UNUserNotification and (b) an "un-dismissable" red banner **inside a dropdown Bob never opens**. If Bob has Focus/DND on, never granted notification permission (C4), or is simply fatigued, the security exposure persists silently and indefinitely. The design **notifies but does not act** on the single case it calls Critical.
- **Severity:** Critical
- **Root cause:** For the one class where a shadow is dangerous, Aviator leaves the vulnerable override winning and delegates reconciliation to the least-reliable actor.
- **Fix:** Treat `severity_trailer: security` + `override-stale` as **auto-act + escalate**, not notify-and-hope. Auto-**suspend** the personal override (reversible — Bob can re-affirm) so the fixed version wins immediately, and escalate to IT in parallel. Extend UC11's capability policy so a security-fixed item's override requires explicit re-affirmation. Never let a Bob-facing notification be the *sole* control on a security exposure.

### C4 — Deprovision defeated by uninstalling the app (or offline leaver)
- **Use case:** Leaver/deprovision lifecycle (§4), re-opening B-C7
- **Failure:** §4 makes Aviator/its daemon the thing that observes the MDM `Deprovisioned=true` signal and invokes `copilot deprovision`. A motivated leaver simply **drags Aviator to Trash / unloads the LaunchAgent / stays offline** — the supervisor is gone or never polls, the MDM signal has no local actor, and materialized `.claude/` + org/dept clones persist forever. The CLI "fixed" B-C7, but Aviator re-introduces a *user-removable enforcement agent* as the trigger.
- **Severity:** Critical
- **Root cause:** A security-critical wipe is contingent on a user-facing, user-deletable app choosing to run it.
- **Fix:** Deprovision enforcement must be **MDM-native, not Aviator-contingent** — a Jamf/Intune policy runs `copilot deprovision` as its own managed agent regardless of whether Aviator exists. Aviator remains the *face* (shows "company content removed"); the *trigger* for the wipe is the MDM management channel + **server-side token revocation** (the real backstop: the next online `copilot update` fails-closed and wipes). Document honestly that an offline/powered-off machine cannot be wiped remotely — lean on "no secret ever materialized" (§8.1), not on a wipe guarantee.

### C5 — Safety escalations are gated behind off-by-default telemetry → "IT notified" is a no-op
- **Use case:** IT setup + UC11/UC12 + escalation ladder §7 (auth-revoked, signature-fail, version-conflict all say "Escalate to IT")
- **Failure:** §7's preamble: IT escalation "fires only when org telemetry (§6) is on **or** an admin contact is set." §6 telemetry is **opt-in, off by default.** So on a default managed machine, every "Escalate to IT" rung — signature failure, incompatible-version, permanent auth revoke — reaches **no one.** The §6.4 IT dashboard ("is a given Mac healthy?") is empty. IT literally cannot tell a healthy Mac from a bricked one, and Bob's un-actionable-by-him failures die in a local log.
- **Severity:** Critical
- **Root cause:** The design fuses *safety escalation* with *analytics telemetry* and inherits analytics' opt-in default for both.
- **Fix:** Split them. **Safety escalation** (content-free: sig-fail, auth-revoked, policy-conflict, stalled-onboarding) is a **required managed-profile key, on by default for managed machines.** **Analytics** (usage/adoption bytes) stays genuinely opt-in. Make `admin_contact`/escalation endpoint mandatory in the MDM profile so managed machines always have a live IT channel.

---

## HIGH

### H6 — Quit mid-wizard strands the machine with no daemon to finish
- **Use case:** UC1
- **Failure:** The LaunchAgent daemon is installed only on wizard *completion* (§3.1). If Bob quits after W7 (clone) but before W8 (materialize), there is **no daemon to resume**, `setup.complete` stays unset, and the next launch restarts from W0. If Bob never reopens, the machine sits half-provisioned, unsynced, invisible to IT.
- **Severity:** High
- **Root cause:** Persistence is bootstrapped last, so any interruption before the finish line has no safety net.
- **Fix:** Install the LaunchAgent and persist a wizard checkpoint at the **first** phase, not the last. The daemon resumes/completes onboarding headlessly and emits "onboarding incomplete" to the IT channel.

### H7 — Offline first-run marks foundation-only as Healthy
- **Use case:** UC1
- **Failure:** W7/W8 need network to clone org/dept. §1.1 says "offline remembers the pre-offline state" — but on first run there **is no prior Healthy state.** If Bob is offline on day one (new laptop, home wifi), the wizard can materialize foundation from the vendored bundle and has no defined behavior for the missing company layers except to finish and (falsely) show Healthy or throw a scary error.
- **Severity:** High
- **Root cause:** The offline-as-overlay model assumes a healthy baseline that first-run offline lacks.
- **Fix:** Wizard handles offline explicitly: complete foundation-only, enter a distinct **"waiting for network to finish company setup"** holding state (not Healthy, not an error); the daemon completes org/dept clones on reconnect.

### H8 — Daemon auto-pulls a *validly-signed* breaking change mid-session
- **Use case:** UC2 (daily update via daemon)
- **Failure:** §3's safety argument covers *unsigned/policy-denied* content. It does **not** cover a fully-signed org change that simply breaks Bob's workflow (a reworded agent, a removed skill) materialized into `.claude/` **while a host session is live.** Re-materializing under a running Claude/Codex causes mid-session inconsistency. §5 etiquette gates on power/network but **not on "user is actively working."**
- **Severity:** High
- **Root cause:** Cadence is time/power-aware, not activity-aware.
- **Fix:** Session-active backoff — defer non-security materialize while a host session is live (Aviator already hooks host launch, §2.2); apply at next idle or session-start. Security-class changes still go immediately (with C3's auto-act).

### H9 — Prunes are silent; UC2's "visible" ≠ "seen"
- **Use case:** UC2 (reconciling-sync prune)
- **Failure:** A `op: pruned` removal is surfaced only in the **"What changed?" menu item Bob never clicks.** §1.3's fire-list does *not* include prunes and the never-notify list doesn't either → prunes generate **no proactive signal at all.** A skill Bob used daily vanishes with zero notice. §3 multiplier #1 conflates "an audit log exists" with "Bob knows."
- **Severity:** High
- **Root cause:** "Auditable" was treated as equivalent to "communicated."
- **Fix:** A prune of an item with recent **local usage** (Aviator has usage counts, §6.2) should **notify** ("A tool you used was removed by an update"), not just log. Zero-usage prunes stay silent.

### H10 — Notification permission never granted → the entire notify tier is dead
- **Use case:** UC8, and every §7 "Notify the user" class
- **Failure:** Aviator's escalation ladder routes ~6 classes to UNUserNotificationCenter. If Bob denies/dismisses the one-time macOS notification-authorization prompt (non-technical users routinely do), **every notify-tier escalation is dropped by the OS** with no fallback and no detection.
- **Severity:** High
- **Root cause:** Single delivery channel with no liveness check.
- **Fix:** Detect notification-auth state. If denied: fall back to opening the popover for high-severity events, and **re-route notify-tier safety events to the IT channel** (the local channel is dead). Surface "notifications off" to IT telemetry.

### H11 — Held-major approval is handed to a Bob who cannot judge it
- **Use case:** UC12 (version pin / held major)
- **Failure:** §7: held major → "Review what changes, then approve — or wait for IT." Bob has no basis to approve or reject a major bump. Blind-approve to clear the badge → breakage; ignore → machine falls behind indefinitely, diverges from the fleet, and (telemetry off) IT can't see the stuck rollout. The UI presents a decision to whoever's at the menu bar; the *right* approver is IT/org.
- **Severity:** High
- **Root cause:** Approval authority is ambiguous — determined by physical proximity to the menu bar, not competence.
- **Fix:** `ecosystem.yml` declares approver authority. On a managed machine, held-majors are approved **centrally by IT**; Bob sees an informational, non-actionable "an update is waiting on IT," never a decision.

### H12 — IT ships Aviator before publishing `ecosystem.yml` → whole fleet false-Healthy
- **Use case:** IT setup + UC1
- **Failure:** W6/W7 read `ecosystem.yml` for products and repo resolution. If the `.pkg` is deployed before the org seed exists, every Bob machine's wizard 404s on the org seed simultaneously. With no way to distinguish "seed coming, wait" from "no org (solo)," the fleet either errors en masse or falls to foundation-only and marks **Healthy** while missing all company content.
- **Severity:** High
- **Root cause:** No ordering guard between app deployment and seed publication; the app can't know the seed is forthcoming.
- **Fix:** Managed profile carries `ecosystem_url`; wizard distinguishes "org seed not yet published (retry/hold)" from "solo"; enter a "waiting for company setup" state and let the daemon complete when the seed appears. IT runbook gates the push on seed existence; Aviator verifies before claiming Healthy.

### H13 — Bob-actionable alerts nudge once, then go silent forever
- **Use case:** UC1/UC2 (backup-missing §5.4; auth-expired) — the Bob-agency core
- **Failure:** §1.3 "persistent banner escalated once"; §7 auth-expired says "partner keeps working on cached content until you do." Bob ignores the single nudge → personal work is **never backed up** (data-loss risk §5.4 realized despite the banner) or the machine **runs on stale content indefinitely**, drifting from the fleet. IT never finds out (telemetry off). One nudge → permanent silent degradation.
- **Severity:** High
- **Root cause:** Single-nudge-then-silent for the exact actions only Bob can perform, with no IT fallback when Bob doesn't act.
- **Fix:** **Time-boxed escalation.** If a Bob-actionable alert is un-acted for N days, escalate to the IT channel ("Bob's machine hasn't been backed up / re-authed in 7 days"). Never let a Bob-only action fail silently forever.

---

## MEDIUM

### M14 — Two-host partial update: worst-wins icon blurs which host is broken
- **Use case:** UC2 + §4.3/§4.4 (both hosts on one machine)
- **Failure:** One `copilot update` materializes both host columns. If Claude succeeds and Codex fails, the worst-wins icon shows amber and the status *sentence* reads generic "needs attention" — a Claude-primary Bob thinks Claude broke. Worse, if the lock advanced for one host but not the other, the shared lock is left inconsistent (atomicity per-host unspecified).
- **Severity:** Medium
- **Root cause:** Worst-wins projection loses the per-host attribution Bob needs; per-host update transactionality undefined.
- **Fix:** Per-host transactional update; the status sentence **names** the failing host ("Codex needs sign-in; Claude is fine") rather than a blended verdict.

### M15 — Capability-policy denials (UC11) are pure noise to Bob → fatigue that erodes UC8
- **Use case:** UC11 (capability denial surfaced to Bob)
- **Failure:** §7: policy-denied → "Notify (expected, not an error)." Bob didn't request the item, can't change the policy, and it's IT's call. If re-reported each update, it trains Bob to ignore Aviator notifications — directly weakening the security notification (C3/UC8) that *does* matter.
- **Severity:** Medium (High as a compounding cause of C3)
- **Root cause:** Escalation tier chosen by event-class, not by *who can act.*
- **Fix:** Route capability-policy denials to the **IT action-log only**, never a Bob notification. Reserve Bob-facing notifications strictly for things Bob can act on.

### M16 — Urgent org changes propagate only as fast as the lazy freshness poll
- **Use case:** IT setup (updating `ecosystem.yml`)
- **Failure:** §2.2 freshness poll is 15m on AC, hourly on battery, **paused on metered/low-power.** An urgent revocation (compromised skill) propagates at the slowest-poll rate — a live exposure window of hours across a battery/metered fleet. The fast webhook is opt-in/org-hosted.
- **Severity:** Medium
- **Root cause:** No priority channel — security revocations ride the same battery-throttled poll as routine freshness.
- **Fix:** A cheap "urgent-since" marker in the freshness endpoint that **overrides** battery/metered backoff for security-class propagation; document the propagation floor honestly; recommend the webhook for orgs needing fast revocation.

### M17 — Deprovision wipe can race a scheduled sync (cross-verb, no global mutex)
- **Use case:** Leaver/deprovision (§4) vs §2.1 sync loop
- **Failure:** §5's "one in-flight invocation, coalesce overlapping triggers" is described for *update*. A `deprovision` and a `sync` are different verbs — a sync firing mid-wipe could re-clone a layer the wipe just removed, or the wipe runs against a half-materialized tree.
- **Severity:** Medium
- **Root cause:** Concurrency control scoped to `update`, not a global per-host CLI lock across all verbs.
- **Fix:** Global per-host CLI mutex across **all** verbs; deprovision takes an exclusive lock and drains/cancels pending sync jobs before wiping.

---

## Top 5 must-fix
1. **C5** — split safety-escalation from analytics; make the IT channel on-by-default for managed machines. Without it, half the escalation ladder and the whole IT dashboard are dead by default.
2. **C2** — notarize/de-quarantine the vendored binaries. Otherwise Gatekeeper silently kills every CLI spawn on a cold Bob machine.
3. **C3** — auto-suspend a security-shadowed personal override (+ escalate); stop relying on a Bob notification as the sole control on an active exposure.
4. **C4** — move deprovision enforcement to MDM-native + server-side token revocation; a user-deletable app must not be the sole wipe trigger.
5. **C1** — pre-flight-validate the managed profile; fail-closed on missing keys instead of silently mis-provisioning under `DisableWizard=true`.

## The Bob-agency problem — recommendation

Aviator today routes escalations by **event-class** (drift → auto-heal, auth → notify, sig-fail → escalate). That is the wrong axis. Route instead by **actor competence × reversibility**, because Bob is not a reliable actor and most notifications aimed at him silently degrade (H9, H10, H11, H13, M15).

Three lanes:

- **AUTO-ACT (never ask, within policy):** any reversible, disposable-surface change Bob can't meaningfully judge — re-materialize, re-clone read-only mirrors, ff-pull, apply signed patches, **defer (not block) updates while a session is live**, and **auto-suspend a personal override that shadows a security fix** (reversible: Bob re-affirms). This is already the design's default; widen it to cover the security-shadow case (C3).
- **ESCALATE TO IT (not Bob):** anything Bob is structurally unqualified to decide *or* can't action — held-major approval (H11), capability-policy conflicts (M15), signature failures, version conflicts, **and any Bob-actionable item left un-acted past a deadline** (backup-missing, re-auth → H13). Managed machines must always carry a live, content-free IT channel, on by default (C5).
- **ASK BOB (rare — only when he is the *sole competent actor* about *his own data*):** "commit your dirty personal work before I sync" (only Bob knows if that WIP matters) and the single sign-in approve (only Bob holds the credential). Nothing else should interrupt him.

**Principle:** a Bob-facing notification is justified *only* when Bob is the sole competent actor for a non-deferrable, personal-data decision. For everything else the default is **auto-act-if-reversible, else escalate-to-IT** — never "notify Bob and hope." Every alert Bob can't act on (M15) is not just useless; it burns down the credibility of the one alert that matters (C3).
