# Red Team B — Adversarial Review: 3×4 Ecosystem Extension Architecture

**Branch:** `ecosystem-extensions` · **Posture:** find where it FAILS, especially at governance boundaries and lifecycle events. No praise.

**Scope reviewed:** `02-four-tier-and-github-topology.md`, `03-use-cases.md`, `design-naming-topology.md`, `design-bootstrap-orchestration.md`, `design-product-composition.md`.

Findings ranked Critical → High → Med. Each: **Failure (step-level) | Severity | Root cause | Fix.**

---

## CRITICAL

### C1 — Leak-scan is a deny-list guarding a *one-way public egress*: fail-open by construction
**Scenario:** UC9b `copilot promote` → foundation.
**Failure (step-level):** Promotion runs a "HARD-FAIL leak scan (deny-list: client names, `.env`, tokens, `mcp.json` secrets, internal-knowledge globs)" (02 §8.2, 03 UC9b). A deny-list can only catch shapes it already enumerates. Pablo promotes an industrial-designer protocol step whose example prose contains a **new** client name not yet in the deny-list, or an API token in a format the regex doesn't match (a new vendor's key prefix), or a plausible-looking internal URL. Scan passes. PR merges under 1-person review. The content is now in the **public** `Everyone-Needs-A-Copilot/claude-copilot`, cloned anonymously by every user on earth, and permanent in git history. Egress is explicitly one-way — there is no recall.
**Severity:** Critical. A single false-negative = irreversible public disclosure of confidential ENAC/client data.
**Root cause:** Deny-list is fail-open; the control is inverted relative to the risk direction (public egress must fail *closed*).
**Fix:** Invert to an **allow-list of promotable files** (only paths explicitly flagged `Promote-To:` AND on a curated allow-manifest may enter the scan), plus entropy/secret scanners (gitleaks/trufflehog) as a *secondary* net, plus mandatory human diff review as the actual gate — the scan is a backstop, never the decision.

### C2 — Personal override permanently shadows an upstream security fix, and `copilot update` never surfaces it
**Scenario:** UC8 override + `copilot update` diff (UC2).
**Failure (step-level):** Bob copies org `qa` into his personal layer, tightens it, sets `override: true` (03 UC8 — "override: true — no warning"). Months later the org ships a **critical security fix** to `qa` (e.g., closes a prompt-injection hole). On Bob's next `copilot update`, the UC2 diff prints `agents/qa.md  personal-jane  (still shadows org-acme › foundation)`. It reports the *winner's* provenance. It does **not** diff the *shadowed* org layer, so "the org qa you are overriding just changed" is invisible. `override: true` has *permanently suppressed* the shadow warning. Bob runs the vulnerable qa forever, believing he's current because `copilot update` said "0 conflicts."
**Severity:** Critical. Security fixes silently don't reach the users who most customized the thing being fixed; the diff actively reassures them.
**Root cause:** The update diff surfaces winner provenance only, not "a layer you are shadowing changed." `override: true` is an unconditional, permanent mute with no security-severity escape hatch. There is no `override-stale` checker.
**Fix:** `copilot update` must diff **shadowed** layers too and flag `your personal qa overrides org qa — org qa CHANGED (a1b2→c3d4)`. Add a `security:` / `severity:` trailer an upstream author can set that **breaks through** `override: true` (forces the warning regardless). Add a `doctor` checker `override-stale`.

### C3 — Signature-verify has no trust root: bootstrap TOFU with no pinned ENAC key
**Scenario:** UC11 supply-chain + bootstrap (`design-bootstrap-orchestration §8`).
**Failure (step-level):** `signature-verify-before-materialize` requires the resolver to know "foundation = ENAC release key" (02 §9.2). But the *only* thing that delivers that key is Ring 0: `curl -fsSL https://get.copilot.enac.dev/bootstrap.sh | bash`. That curl is anonymous, versionless, and unauthenticated beyond TLS. Whoever controls the `get.copilot.enac.dev` redirect (DNS takeover, CDN compromise, a lapsed domain) serves a `bootstrap.sh` that embeds an **attacker's** public key as the trusted foundation key. From then on every `signature-verify` "passes" — against the attacker. There is no pinned, out-of-band ENAC root key; trust is bootstrapped from the first unauthenticated fetch (TOFU).
**Severity:** Critical. The entire supply-chain control chain (lockfile → verify → policy) hangs off a key the attacker can substitute at install.
**Root cause:** No independent, multi-channel-distributed root of trust; the key travels in-band with the code it's supposed to authenticate.
**Fix:** Pin ENAC's public key as a checked-in constant distributed via multiple channels (repo, docs, `gh` attestation), verify the bootstrap script's *own* signature, and use a transparency log / Sigstore so key substitution is publicly detectable.

### C4 — Foundation signing-key rotation hard-fails every deployed install globally, with a chicken-and-egg update path
**Scenario:** Lifecycle — foundation-owner key rotation.
**Failure (step-level):** ENAC rotates its signing key (routine hygiene, or after a suspected compromise). Every deployed install pins "foundation = ENAC release key = OLD". The next foundation tip is signed with NEW. `signature-verify-before-materialize` sees an unknown signer → **refuses to materialize** (02 §9.2: "Unsigned/unknown-signer → refuse"). Every user's `copilot update` hard-fails on the foundation layer simultaneously — a global denial of service. Worse: the new trust root would normally ship *via a foundation update*, but foundation updates are gated on verifying with the old key, so the channel that must deliver the new key is the exact channel the rotation invalidated.
**Severity:** Critical (availability + unrecoverable-without-manual-touch).
**Root cause:** Single pinned key, no rotation protocol — no dual-sign overlap window, no trust-root-as-a-set, no separate channel for trust-root updates.
**Fix:** Dual-sign during a rollover window (tips signed by old **and** new key), model the trust root as a *set* with add-then-remove, deliver key updates through a channel independent of the signing gate (the pinned constant of C3, updated via signed release + transparency log).

### C5 — A second department in a *different org* breaks every single-org assumption in the model
**Scenario:** UC10 variant — "a user whose second department is in a DIFFERENT org."
**Failure (step-level):** Priya consults for acme-corp (Engineering) and also beta-inc (Finance). The model assumes exactly one enterprise: one `cc config get layers.org` **scalar**, one `ecosystem.yml` (discovered as `<org>/copilot-ecosystem`), one `github-work` SSH alias, one capability policy. Two orgs means: (a) `layers.org` can hold only one value; (b) two `ecosystem.yml` files with conflicting `products`, pins, and `departments[]`; (c) a **third** github.com identity → SSH-alias collision returns (the very problem 02 §6.1 claims aliases solved is only solved for personal-vs-*one*-work); (d) *whose* capability policy governs the merged stack — acme's `may_never` or beta's? Nothing in the design answers any of these.
**Severity:** Critical (structural — the whole topology is single-tenant).
**Root cause:** `layers.org`, ecosystem discovery, auth aliases, and capability-policy ownership are all modeled as singletons.
**Fix:** Namespace layers by org (`acme:dept-finance`, `beta:dept-finance`), make `layers.org` a set, require a distinct SSH alias per work org (`github-acme`/`github-beta`), and define cross-org policy composition (most-restrictive-wins, or per-org-scoped materialization into separate targets). This is a major design gap, not a tweak.

### C6 — Capability policy lives in-band with the layer it governs: a compromised org disables its own guard
**Scenario:** UC11 capability policy.
**Failure (step-level):** "The org ships a capability policy" (03 UC11) — it lives in the org layer. The policy is the highest-leverage control precisely because it bounds blast radius "even when a layer is compromised" (02 §9.3). But if the org layer is compromised, the same malicious push edits `policy.yml` to delete its own `may_never: [agents/sec.md, mcp]` in the same commit, then ships the malicious `sec.md`. The guard is governed by the thing it guards. Signed commits don't help if the compromised account is a valid CODEOWNER.
**Severity:** Critical.
**Root cause:** No separation between the policy's authority and the layer's push authority; no higher, immutable anchor holds acme's policy.
**Fix:** Require the capability policy to be signed by a **security-team key distinct from the platform-team push key**, treat any policy change as requiring a second signer, and have the resolver refuse to apply a policy whose signer isn't on a separately-pinned allow-list. (Note: no *tier* can anchor this — foundation is public/ENAC and can't carry acme secrets — so it must be a designated-key split within the org.)

### C7 — Leaver keeps all materialized + cloned confidential content; no `copilot deprovision`
**Scenario:** Lifecycle — Bob leaves acme-corp.
**Failure (step-level):** Bob's `gh` token / SSH key is revoked on offboarding. That stops *future* pulls. It does nothing about what's already local: materialize-by-copy has already written org + Finance-dept content into `.claude/`, and the full layer clones sit in `~/.copilot/layers/dept-finance` and `.../org-acme` — including Finance's confidential knowledge, client names, internal agents. There is no `copilot deprovision`, no wipe, no server-side reach. Bob walks out with a complete local copy of company-confidential capability content and can read it offline forever.
**Severity:** Critical (data exfiltration on every departure — the default case, not an attack).
**Root cause:** Materialize-by-copy + full local clones create durable local copies; revocation is server-side only; no offboarding command exists.
**Fix:** Ship `copilot deprovision` (wipes materialized `.claude/` items + layer clones for a given org), have `copilot update` **fail-closed and offer wipe** when a private layer's auth is permanently revoked, and — because local git copies fundamentally can't be clawed back — treat anything placed in a layer as already-exfiltrable: keep true secrets out of layers (DLP), scope confidential knowledge behind runtime lookups, not materialized files.

---

## HIGH

### H1 — Promotion creates dangling references: a promoted item depends on a private item that doesn't promote
**Scenario:** UC9b (and UC9a).
**Failure (step-level):** `copilot promote` cherry-picks *flagged commits* (02 §8.2). Pablo flags the industrial-designer protocol step; it `@include`s a skill or references a knowledge doc that lives in `enac-org-private` and is **not** flagged. The leak-scan checks for secrets, not referential completeness. The public foundation now ships a step that references an item no public user can resolve → broken for every downstream user worldwide. Same class at dept→org (H2).
**Severity:** High (public breakage; erodes trust in every promotion).
**Root cause:** Promotion is per-commit cherry-pick with no transitive dependency-closure check across dimensions.
**Fix:** Promotion must compute the dependency closure (agents→skills→knowledge→mcp it references) and either promote the whole closure or reject with the missing set named.

### H2 — Dept→org promotion of a skill that references a dept-only knowledge doc breaks it for other departments
**Scenario:** UC9a.
**Failure (step-level):** Mira's `tax-calc` skill references a knowledge doc in `copilot-knowledge-dept-finance`. Raj promotes the skill to `copilot-*-org` (via `git mv` or cross-repo PR). Now *every* department inherits `tax-calc`, but under Option A topology the Finance knowledge repo is unreadable to Engineering's credential (that's the whole point of separate-repo confidentiality, 02 §6.2). The skill resolves for Finance, 404s/empties for Engineering — a silent, per-consumer partial failure.
**Severity:** High.
**Root cause:** Dimensions promote independently; no check that a promoted item's cross-dimension references resolve at the *target* tier for *all* consumers.
**Fix:** Promotion validates that every reference resolves at the destination tier's visibility; if the skill needs the knowledge doc, promote the doc too (or reject).

### H3 — 1-person ENAC: the GitHub Environment approval gate is self-approval theater
**Scenario:** UC7/UC9b — "who runs the approver at a 1-person ENAC."
**Failure (step-level):** Promotion to public is "gated behind a GitHub Environment approval so promotion to the world is deliberate and logged" (02 §8.2). An approval gate is a separation-of-duties control — it means something only when approver ≠ author. At a 1-person ENAC, Pablo authors *and* approves. The gate logs the event but cannot stop a bad promotion; it's a speed bump, not a control. Combined with C1 (fail-open scan), nothing independent stands between a mistake and the public.
**Severity:** High.
**Root cause:** Design assumes separation of duties that a solo org structurally can't provide.
**Fix:** At N=1, require a *different kind* of second factor: a mandatory cooldown/preview window, a second hardware key, an external transparency notification, or gate public promotion on recruiting a co-maintainer. Document that the Environment gate is non-functional as a control at N=1.

### H4 — `may_never` keys on path/name; a department relabels the dimension to evade it
**Scenario:** UC11.
**Failure (step-level):** Policy: `may_never: [agents/sec.md, mcp]`. Enforcement is at materialize time by path/name. A department ships the identical malicious content as `agents/security.md` (different filename), or `skills/sec-helper/SKILL.md` (different dimension), or embeds an MCP-server registration *inside* a skill's invocation script rather than a top-level `mcp` declaration. Materialize-by-copy doesn't inspect content, so none match `agents/sec.md` or `mcp` → all materialize. The guard is trivially evaded by renaming.
**Severity:** High.
**Root cause:** Policy classifies by path/name, not by capability/behavior; the copy step never reads content.
**Fix:** Classify by *content signature* — does this file register a tool / declare an MCP server / define an agent named sec-equivalent? — not by literal path. Enforce on what the item *does*, not what it's *called*.

### H5 — Product disabled: already-materialized integrations are orphaned, not removed
**Scenario:** Lifecycle — org flips `cli.enabled: false` in `ecosystem.yml`.
**Failure (step-level):** `copilot derive` regenerates the manifest without CLI layers; `copilot update` re-materializes. But materialize-by-copy is **additive** — every described mechanism *adds* files from winning layers; nothing enumerates and *deletes* files whose owning layer/product vanished. The CLI connectors + MCP declarations already copied into the registry linger. The agent keeps loading a now-unsanctioned connector (possibly the reason it was disabled — a security incident). Same failure when a department is removed or a personal override's source is deleted.
**Severity:** High.
**Root cause:** Materialize is an additive overlay, not a full sync; no garbage collection keyed on the resolved set.
**Fix:** Make materialize a **reconciling sync**: compute the full target set from the current lockfile, then delete any materialized item not in it (prune). The old lockfile is the diff baseline.

### H6 — Transitive foundation pin conflict (personal ^5 vs org requires ^6): undefined resolution
**Scenario:** UC12.
**Failure (step-level):** Foundation is a **single** layer with one `ref` (02 §4 manifest; naming-topology §3). Personal-jane pins foundation `ref: ^5`. The org layer she pulls was authored against foundation ^6 APIs (its content `requires: foundation ^6`). There's exactly one foundation checkout — it can hold `^5` **or** `^6`, not both. 02 §8 asserts "per-layer `requires`/minVersion hard-errors," but the *mechanism* (one `ref` field) can only satisfy one constraint. Does resolve error, or silently honor the personal pin and run org content against an API version it wasn't written for? The docs claim hard-error but the single-ref data model can't detect the org's transitive requirement unless every layer declares `requires:` AND resolve intersects them — which isn't specified.
**Severity:** High.
**Root cause:** Foundation modeled as one shared layer with one ref, but version constraints originate from multiple consuming layers; no documented constraint-intersection step.
**Fix:** Require every layer to declare `requires: { foundation: <range> }`, have resolve **intersect all ranges** and pick the max satisfying SHA, and hard-error (naming the conflicting layers) when the intersection is empty — instead of last-writer-wins on a single `ref`.

### H7 — Committed `copilot.layers.yml` / `copilot.lock` leak private repo URLs, dept names, and org topology
**Scenario:** Lifecycle — manifest/lock as tracked files (echoes 02 §9 risk 4).
**Failure (step-level):** A developer commits `copilot.layers.yml` (and `copilot.lock`) into a shared — possibly **public OSS** — project repo. The manifest contains `git@github-work:acme-corp/copilot-claude-dept-finance.git`, `github-personal:alice/...`, `department: finance`, `org: acme-corp`, foundation pins, and developer home paths. A public contributor's commit now discloses acme's entire internal department topology, which teams exist, and naming that maps the org chart — to the world, permanently in history.
**Severity:** High.
**Root cause:** The manifest is simultaneously machine-local config and a plausibly-committed project file; it embeds org-confidential topology; no gitignore guidance.
**Fix:** Locate the manifest/lock under `~/.copilot/` (machine-scoped) and gitignore them in project trees by default; if a project must pin, ship only a public-safe rendered subset (SHAs + product/tier roles, no URLs/dept names).

### H8 — A committed `copilot.lock`/manifest with a local `path:` layer breaks Bob's different machine
**Scenario:** UC12 — "a `copilot.lock` committed by a developer breaks Bob's different-OS machine."
**Failure (step-level):** SHAs in the lock are OS-agnostic (fine). But the manifest carries `source: { path: ~/.copilot/layers/claude-personal }` (naming-topology §4) and `github-personal:alice/...` aliases. When Bob checks out the shared repo, his machine has no `alice` personal layer, no `~/.copilot/layers/claude-personal`, and possibly no `github-work` alias configured yet → resolve references a path/alias that doesn't exist on his machine and fails or silently drops layers, producing a *different* materialized set than the committing developer had.
**Severity:** High.
**Root cause:** The manifest mixes machine-specific (personal `path:`, SSH aliases, home dirs) with shareable (SHAs, product roles) in one committed artifact.
**Fix:** Split the manifest: a shareable, machine-agnostic core (roles, pins, org/product) vs. a machine-local overlay (personal paths, alias→identity map). Never commit the overlay; the SSH-alias→identity binding is resolved locally, not from the tracked file.

---

## MEDIUM

### M1 — Two departments, same-named skill: silent shadow with arbitrary, user-assigned rank
**Scenario:** UC10.
**Failure (step-level):** Priya's platform (rank 20) and engineering (rank 21) both ship a `deploy` skill with different semantics. `platform/deploy` shadows `engineering/deploy` — "total-ordered, zero ambiguity" (03 UC10). But the rank *between sibling departments* is arbitrary (why platform<engineering?) with no semantic basis, and the `override: true` warning is designed for personal-vs-lower, not dept-vs-dept collisions — so the accidental shadow of one real department's skill by another's is silent. Resolution is deterministic; the *outcome* is a surprise.
**Severity:** Medium.
**Root cause:** Sibling-department rank is user-assigned with no meaning; collision detection is scoped to personal overrides.
**Fix:** Warn on *any* cross-layer same-name collision (not just personal), and require an explicit tiebreak declaration when two same-rank-class (both `department`) layers collide on a name.

### M2 — Department reorg / rename: stale scalar, and a GitHub redirect *masks* the change
**Scenario:** Lifecycle — Finance→accounting rename, or Bob transfers Finance→Engineering.
**Failure (step-level):** `layers.department = finance` is a hand-pinned scalar (02 §5). On rename, `ecosystem.yml`'s `departments[]` becomes authoritative-but-diverged from every user's config. The `layer-moved`/404 checker is supposed to catch it — but a GitHub repo **rename leaves a redirect**, so `git pull` on `copilot-*-dept-finance` silently follows to `...-accounting` and Bob keeps pulling renamed content under the old alias, masking the reorg entirely. On a *transfer*, Bob's personal overrides that shadowed Finance items are now orphaned (shadowing nothing or the wrong dept), and his materialized Finance content lingers (H5).
**Severity:** Medium.
**Root cause:** Department is a manually-pinned scalar never reconciled against the authoritative `departments[]`; rename detection relies on a 404 that GitHub's redirect suppresses.
**Fix:** Reconcile `layers.department` against `ecosystem.yml.departments[]` on every `derive`/`update`; detect renames via the ecosystem manifest (slug changes), not via clone-404; prune orphaned overrides + materialized content on transfer.

### M3 — Concurrent foundation change: leak-scan TOCTOU against a shifting base
**Scenario:** UC7/UC9b — promotion races a concurrent foundation change.
**Failure (step-level):** `copilot promote` cherry-picks onto a fresh branch of public foundation and runs the leak-scan against *that* base. Meanwhile another maintainer merges a foundation change. The PR is now behind; on merge (or after a rebase), content lands against a base the scan never saw — a cherry-pick auto-resolve could reintroduce or expose text the scan on the old base cleared.
**Severity:** Medium.
**Root cause:** Leak-scan is time-of-check; merge is time-of-use; no re-scan on the post-merge tree.
**Fix:** Re-run the leak-scan as a **required merge-gate status on the final merge commit**, not only at promote time; block auto-merge if the base advanced since the scan.

### M4 — Capability policy blocks a legitimate dept skill with no appeal/exception path
**Scenario:** UC11 — "policy blocks a legit dept skill and the user is stuck."
**Failure (step-level):** A department's genuinely-fine skill matches a `may_never`/`may_override` pattern (e.g., a legit `agents/security-notes.md` caught by an `agents/sec*` rule) and is dropped at materialize (`POLICY … DENIED — not materialized`, 03 UC11). By design the department *cannot* override the policy — so the user has zero recourse except emailing the org security team and waiting. No per-item exception mechanism exists.
**Severity:** Medium.
**Root cause:** Policy is deny-only with no allow/exception granularity or appeal workflow.
**Fix:** Add a signed per-item exception list (security team grants `allow: [dept-finance/agents/security-notes.md]`) so legitimate items unblock without weakening the class rule.

### M5 — Dept→org promotion under Option A loses history / is a heavier cross-repo PR than the docs imply
**Scenario:** UC9a.
**Failure (step-level):** 03 UC9a shows the easy case: subfolder topology → `git mv departments/finance/skills/tax-calc org/skills/`. But 02 §6.2 / naming-topology §5 make **separate repos the default for claude/cli** dimensions. For those, dept→org is a *cross-repo* PR — `git mv` doesn't work across repos, and a naive copy loses authorship/signature/history (which the promotion valve elsewhere is careful to preserve). The use case advertises the frictionless path while the recommended topology forces the frictionful one.
**Severity:** Medium.
**Root cause:** Two topologies with divergent promotion mechanics; docs illustrate only the subfolder one.
**Fix:** Provide `copilot promote --to org` for the separate-repo case too (cherry-pick preserving author/signature, like the foundation valve), and document that `git mv` promotion applies only to subfolder (knowledge) topology.

---

## Top 5 must-fix before this ships

1. **C7 — Leaver data exfiltration.** Every departure leaves confidential org/dept content permanently on a former employee's disk (materialized + cloned). No `copilot deprovision`, no fail-closed, no wipe. This is the default lifecycle path, not an edge case — ship deprovisioning + a DLP posture (keep true secrets out of layers) before any enterprise touches it.
2. **C2 — Override shadows security fix, invisibly.** `copilot update` reassures users ("0 conflicts") while their customized agents run unpatched. Add shadowed-layer diffing + a security-severity trailer that breaks through `override: true`.
3. **C3 + C4 — No trust root / no key rotation.** Signature-verify is only as good as a key delivered by an unauthenticated `curl`, and rotating that key hard-fails every install with no recovery channel. Pin a multi-channel ENAC root key and define a dual-sign rollover protocol before the verify control means anything.
4. **C1 + H1/H2 — Fail-open leak-scan + no dependency closure on a one-way public egress.** Promotion can leak novel secrets and ship dangling public references, both irreversible. Invert to an allow-list scan, add secret scanners + mandatory human review, and enforce dependency-closure on every promotion.
5. **C6 + C5 — Governance singletons.** The capability policy disables itself under org compromise (in-band with what it guards), and the entire model collapses for a user with two orgs (single-tenant `layers.org`/`ecosystem.yml`/auth). Split policy-signing authority from push authority, and either scope the model to single-org explicitly or namespace layers per org.

**Counts:** 7 Critical, 8 High, 5 Medium = 20 findings (15 Critical/High).
