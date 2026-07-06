# The Copilot Ecosystem — Final Architecture

| | |
|---|---|
| **Status** | Design / Proposed — **validated against 12 use cases + adversarial red-team** |
| **Branch** | `ecosystem-extensions` |
| **Date** | 2026-07-06 |
| **Question answered** | "What technical architecture lets an enterprise run THREE product families (Claude/Codex Copilot, Knowledge Copilot, CLI Copilot), each layered PERSONAL › DEPARTMENT › ORG › FOUNDATION, so that a non-technical person (Bob the accountant) runs ONE command and gets a working AI partner — self-healing, self-organizing, zero manual work?" |
| **Design appendices** | [`research/design-naming-topology.md`](research/design-naming-topology.md) · [`research/design-bootstrap-orchestration.md`](research/design-bootstrap-orchestration.md) · [`research/design-product-composition.md`](research/design-product-composition.md) |
| **Validation appendices** | [`research/redteam-A.md`](research/redteam-A.md) (onboarding/authoring, 24 findings) · [`research/redteam-B.md`](research/redteam-B.md) (governance/lifecycle, 20 findings) |
| **Prior docs** | [`02-four-tier-and-github-topology.md`](02-four-tier-and-github-topology.md) · [`03-use-cases.md`](03-use-cases.md) |

> **How to read this.** §1–§8 are the architecture. **§9 is the validation** — the 30 Critical/High failures the red-team found and exactly how the design below addresses each. The architecture in §1–§8 is *already hardened* with those fixes; §9 is the audit trail proving it. If you read one thing, read §1 then §9.

---

## 1. Bottom line up front

**The ecosystem is one resolver, one manifest, one command — parameterized three ways (product × tier × dimension).** Everything else is derivation and governance around that spine.

- **Three products** are just **bundles of dimensions**: Claude/Codex Copilot owns agents/skills/commands/protocol/memory/tasks; Knowledge Copilot owns knowledge; CLI Copilot owns integrations. The resolver resolves *dimensions*, not products, so adding a product is additive by construction.
- **Four tiers** (personal › department › org › foundation) are an **ordered list**; precedence is list order, so 4 (or N) tiers cost almost nothing over 3.
- **One published fact per enterprise** — an `ecosystem.yml` seed — lets an installer **derive every repo URL** from just a company name + a department. Nobody types a URL.
- **One command** (`copilot`, invoked by absolute path) is install, repair, and update. A dependency-free bootstrap installs a capable foundation that then drives a self-healing, idempotent, guided setup.
- **The value prop — "focus, not corpus"** — falls out for free: department-scoped resolution bounds a Finance user's world to Finance + org + foundation, so they go deep in their area without carrying the whole org.

**What the red-team changed.** The original design worked on a developer's happy path but **failed the Bob test and the enterprise-lifecycle test.** The hardened architecture adds: an **admin-free / proxy-aware / offline / Windows / GHES** install path; a **reconciling sync** that prunes (not just adds) so disabling a product actually removes it; **`copilot deprovision`** and a DLP posture so a leaver can't keep confidential content; **shadowed-layer diffing + a security trailer** so an override can't hide an upstream security fix; a **multi-channel pinned trust root + dual-sign key rotation**; an **allow-list promotion scan + dependency-closure check**; a **capability policy signed by a key distinct from push authority and classified by content, not filename**; and a **split manifest** (shareable core vs machine-local overlay) so nothing leaks org topology into a committed repo.

---

## 2. The vision & the shape

Three product families, each independently layered across the same four tiers, **adopted progressively**:

```
                        PERSONAL (10)   DEPARTMENT (20)   ORG (30)    FOUNDATION (40)
                        highest ─────────── precedence ──────────────► lowest (base)
 Claude/Codex Copilot     yours          your team         company     public OSS
   (agents, skills,       overrides      capabilities      standards   (ENAC-owned)
    commands, protocol,
    memory, tasks)
 Knowledge Copilot        your notes     dept knowledge    company KB  public/empty
   (knowledge)                                             (1 truth)
 CLI Copilot              personal       dept tools        company     public connectors
   (integrations)         connectors                       tooling
```

- **Start with the foundation product** (Claude or Codex Copilot). It works standalone — Memory Copilot, Task Copilot, the protocol, agents. Bob has a partner immediately.
- **Extend when ready:** `copilot extend knowledge`, then `copilot extend cli`. Each is additive; nothing prior breaks.
- **Focus, not corpus:** a Finance user's manifest engages Finance + org + foundation only. Engineering's content is never named, never cloned, never loaded. You get deep, not drowned.

The layered picture is in the companion **diagram artifact** (see §10); this section is its legend.

---

## 3. Part A — The resolver & dimension semantics (the spine)

There is **one** resolution engine (from [`02`](02-four-tier-and-github-topology.md) §4): load the manifest, sort layers by `rank`, and per **dimension** apply that dimension's semantics, then **materialize** the winning set into the discovery paths the host actually scans (copy, not read-time merge — the host is layer-unaware). A **product is a set of dimension-subtrees**; the resolver has no concept of "product."

### 3.1 The authoritative resolution-semantics matrix

Rows = dimensions; columns = tiers. Cell = the semantics applied.

| Dimension (owning product) | PERSONAL (10) | DEPARTMENT (20) | ORG (30) | FOUNDATION (40) |
|---|---|---|---|---|
| **agents** (Claude/Codex) | override | override | override | override (base) |
| **skills** (Claude/Codex) | override | override | override | override (base) |
| **commands** (Claude/Codex) | override | override | override | override (base) |
| **protocol** (Claude/Codex) | override¹ | override¹ | override¹ | override¹ (base) |
| **knowledge** (Knowledge Copilot) | accumulate | accumulate (dept-scoped) | accumulate | accumulate (base) |
| **memory** (Memory Copilot) | personal-write | accumulate-read (dept-scoped) | accumulate-read | accumulate-read (base) |
| **tasks** (Task Copilot) | project-local | project-local | project-local | project-local |
| **CLI-integrations** (CLI Copilot) | override² | override² | override² | override² (base) |

- **override** = nearest-tier whole-unit wins; shadow reported. **accumulate** = all tiers contribute, ordered. **personal-write** = reads accumulate down the stack, writes land in personal only (up-tier sharing is the `copilot promote memory` valve, never a silent store). **project-local** = bound to the working tree, not tiered.
- ¹ protocol is whole-chain override today; chain-*composition* (a dept inserting a stage) is the P2 hard dimension. ² CLI connectors default override, with opt-in accumulate for connector *lists*.
- **memory read/write split is the one asymmetry:** a Finance user recalls company + Finance + personal decisions in one search, but `cc memory store` only ever writes personal/project.
- **Separate-repo-per-department is the confidentiality default, not a style choice:** the repository is GitHub's only read boundary — there are no path-level read ACLs, and CODEOWNERS governs review, not read access. A subfolder scopes *resolution* (which content a user's manifest engages, i.e. focus) but never *readability* — any member with read on the parent repo can clone and read every department's subfolder. So a real per-department read boundary requires a per-department repo; `topology: subfolder` is reserved for departmental content that is explicitly non-confidential (§4.2, §8.1).

### 3.2 Materialize is a **reconciling sync**, not an additive overlay *(fixes B-H5, B-M2 orphaning)*

The original "copy winners in" was **additive** — it never removed anything. So disabling a product, leaving a department, or deleting a personal override left **orphaned executable content** loading forever. **Fixed:** every `copilot update` computes the full target set from the *current* lockfile, diffs it against the *previous* lockfile, and **prunes** any materialized item whose owning layer/product is no longer in the resolved set. Materialize = `rsync --delete` semantics against the resolved set, not `cp`.

### 3.3 The manifest is **split**: shareable core vs machine-local overlay *(fixes B-H7, B-H8 topology leak & cross-machine break)*

The manifest embeds private repo URLs, SSH aliases, department names, and home paths — committing it to a shared/public repo would **leak the org chart** and **break on another machine**. **Fixed** by splitting:

- **`copilot.lock` (shareable, machine-agnostic):** resolved SHAs + product/tier/role + pins. Safe to commit — no URLs, no dept names, no personal paths. This is the reproducibility artifact.
- **`~/.copilot/manifest.local.yml` (machine-local, never committed):** the URL/alias/path bindings and the `alias→identity` map. Lives under `~/.copilot/`, gitignored in every project tree by default.

`copilot update` resolves from the **lock** by default (reproducible), re-resolving semver ranges only on explicit `copilot update --upgrade` *(fixes A-H8 machine drift)*.

---

## 4. Part B — GitHub naming & the self-describing `ecosystem.yml`

### 4.1 The computable naming convention

Every private repo URL is a **pure function** of `(product, tier, org, dept, user)` — so the installer *derives* names, never asks for them:

```
owner(tier)         = { personal: <user>, department|org: <org>, foundation: "Everyone-Needs-A-Copilot" }
repo(product,tier)  = { foundation: "<product>-copilot",  org: "copilot-<product>-org",
                        department: "copilot-<product>-dept-<slug>",  personal: "copilot-<product>-private" }
URL = transport(tier, host) + owner + "/" + repo + ".git"
```

Worked example (`Everyone-Needs-A-Copilot` foundation, `acme-corp` enterprise, `finance` dept, `bob`): `acme-corp/copilot-claude-dept-finance`, `acme-corp/copilot-knowledge-dept-finance`, `Everyone-Needs-A-Copilot/cli-copilot`, etc. The three foundation repos are the real OSS repos (`claude-copilot`, `knowledge-copilot`, `cli-copilot`) — the convention bends once, for the public floor. Full 12-cell matrix in [`research/design-naming-topology.md`](research/design-naming-topology.md).

### 4.2 The `ecosystem.yml` seed — the one thing IT publishes

Given only the org name, the installer fetches ONE artifact and derives the entire matrix. It lives at the const-named seed repo `<org>/copilot-ecosystem` (discovery fallback: seed repo → org `.github` profile → `copilot-ecosystem` topic search). Hardened schema:

```yaml
version: 1
org: acme-corp
host: github.com                 # ← GHES: github.acme.com  (fixes A-C5)
api_base: https://api.github.com # ← GHES: https://github.acme.com/api/v3
ssh_host: github.com             # ← GHES SSH endpoint
foundation:
  owner: Everyone-Needs-A-Copilot
  mirror: null                   # ← self-hosted mirror URL if public github.com is firewalled (fixes A-C5)
  root_key: "ssh-ed25519 AAAA…"  # ← PINNED trust root, multi-channel (fixes B-C3)
  key_set: ["<old>", "<new>"]    # ← dual-sign rollover set (fixes B-C4)
auth: gh-device | ssh-work | gh-app:<slug>
products:
  claude:    { enabled: true,  foundation: "^5.14.0", topology: separate }
  # topology: separate is the DEFAULT for every product — department content is
  # confidential business data (financials, forecasts, proprietary process), and
  # the repo is GitHub's only read boundary. `topology: subfolder` is a narrow,
  # explicit opt-in reserved for genuinely non-confidential departmental content.
  knowledge: { enabled: true,  foundation: "^2.3.0",  topology: separate }
  cli:       { enabled: false }
departments:
  - { slug: finance,     renamed_from: [],        lead: "@acme-corp/finance-leads" }
  - { slug: engineering, renamed_from: [fin-eng], lead: "@acme-corp/eng-leads" }
policy_signers: ["ssh-ed25519 <security-team-key>"]  # ← policy authority ≠ push authority (fixes B-C6)
```

- **`host`/`api_base`/`ssh_host`/`foundation.mirror`** make the whole model work on **GitHub Enterprise Server** and behind a public-github.com firewall *(fixes A-C5)*.
- **`renamed_from`** aliases let a department rename reconcile instead of 404-ing *(fixes A-H10, B-M2)*.
- **`departments[]` is verified to exist** at derive/CI time — `copilot doctor` runs `gh repo view` per declared repo and distinguishes "declared but not created" from "deleted" *(fixes A-H12)*.
- **`root_key`/`key_set`/`policy_signers`** are the supply-chain anchors (§7).
- **No `ecosystem.yml`?** Explicit degrade: "no ecosystem found for `<org>` — foundation-only mode; give IT this template" + a `copilot ecosystem init` scaffold *(fixes A-M16)*.

`copilot derive` turns `ecosystem.yml` + `layers.department` + local personal opt-ins into **one** `copilot.lock` (product axis), regenerated on every update. Never hand-written.

---

## 5. Part C — The zero-friction installer (the Bob path, hardened)

**Bob runs one thing and gets a partner before anything can fail.** The chicken-and-egg (the foundation orchestrates setup, but you need the foundation first) is resolved by **three rings**: a dependency-free bootstrap installs a capable foundation whose own `copilot doctor` drives every guided, idempotent phase.

```
RING 0  bootstrap  (curl'd OR handed as an offline bundle; assumes only a shell)
          │  installs prereqs (ADMIN-FREE), installs foundation + the `copilot` binary on PATH
          ▼
RING 1  copilot doctor --bootstrap   (ships with the foundation; idempotent state machine)
          ▼
RING 2  the foundation  (agents, cc, tc, memory — Bob's partner)
```

### 5.1 The install must actually run on a real corporate machine *(fixes A-C1, A-C2, A-C3, A-C4, A-M20, A-M21)*

The red-team's most damaging cluster: the naive installer aborted before Bob got anything. Hardened Ring 0:

| Failure the red-team found | Fix baked in |
|---|---|
| **A-C1** No admin → Homebrew install `sudo`-aborts *before* the foundation | **Admin-free binary bundle:** userland tarballs of git/gh/node/cc/tc/**copilot** unpacked into `~/.copilot/bin` (no brew, no sudo). Prereq failure **never** aborts before the foundation clone — the "you always keep a partner" invariant holds. |
| **A-C2** Nothing installs/PATHs the `copilot` binary the whole handoff needs | Ring 0 explicitly installs `copilot` into `~/.copilot/bin`, verifies `command -v`, and **invokes it by absolute path** thereafter. |
| **A-C3** curl → `raw.githubusercontent` redirect that corp proxies block | Serve `bootstrap` bytes **directly** (not a raw-github redirect); honor `HTTPS_PROXY`/`NO_PROXY`; ship an **air-gapped offline bundle** IT can hand out (`.command`/`.tar` carrying foundation + binaries, zero network). |
| **A-C4** Windows has no bash | Parallel `bootstrap.ps1` (winget/scoop prereqs, same Ring-1 handoff) + normalized path handling; or explicit WSL-guided path. Not "macOS only." |
| **A-M20** git clone ignores authenticated proxy; SSH:22 blocked | Configure `git http.proxy`; **SSH-over-443** fallback (`ssh.github.com:443`) when 22 is firewalled; `BatchMode=yes` fails fast, never hangs. |
| **A-M21** `copilot` name collides with GitHub's own `copilot`/`gh copilot` CLI | Invoke by absolute path in bootstrap; `doctor` detects a conflicting `copilot` on PATH and warns. **Open decision (§8):** keep `copilot` or pick a distinct verb. |

### 5.2 The state machine (idempotent, self-healing, never-destroy)

Each phase declares **precondition · action · idempotent-check · repair**. The runner is the *same engine* for install (`--bootstrap`), diagnosis (`doctor`, read-only), and fix (`repair`).

```
P0 prereqs   → P1 foundation  ── Bob has a working partner HERE; everything below is additive ──
P2 identity  → P3 org → P4 ask-dept → P5 dept → P6 personal → P7 lock → P8 materialize(sync) → P9 verify → P10 teach
```

- **Repair is split by layer role** *(fixes A-H11):* read-only mirrors (org/dept/foundation) → `git fetch && reset --hard` or reclone on non-ff/force-push; the **personal** layer → stash-and-flag, **never discard**. One rule for two ownership models was the bug.
- **Offline = "using cached SHAs"**, skip the pull, still materialize from local clones *(fixes A-M17)*. Unreachable ≠ drift.
- **Never-destroy invariant:** `doctor` owns `.claude/` (disposable, re-materializable) and the read-only mirrors (re-cloneable). It **never** writes the personal working tree while `git status` is dirty.
- **The materialization root is defined for a project-less Bob** *(fixes A-H15):* the solo/Bob path materializes into the **user-global `~/.claude/`** (independent of cwd); when Bob is also inside a project, project `.claude/` composes on top per the host's native precedence. `doctor` asserts the root is on the discovery path.

### 5.3 Auth — persona-split, hardened *(fixes A-H7 SAML, A-M19 rate-limit)*

| | Bob (non-technical, ≤1 identity) | Developer (2+ identities) |
|---|---|---|
| Foundation (public) | anon HTTPS (or authenticated once a token exists, to dodge shared-NAT rate limits) | anon HTTPS |
| Org/Dept (private) | **`gh auth login` device flow** — browser code, no keys | **SSH host aliases**, installer-generated |
| SSO/SAML orgs | driver runs `gh auth login --web` **SSO authorization**; a SAML 404 is classified **"needs authorization," never "layer gone"** | prints the "Configure SSO" URL for the uploaded key |

The SSH-alias machinery from [`02`](02-four-tier-and-github-topology.md) §6 activates **only** when a real second-identity hostname collision exists — Bob never sees it. **A 404 is never silently "deleted"** — it is classified as unauthorized-SSO / not-yet-created / offline / actually-deleted, each with a distinct message *(fixes A-H7, A-H12)*.

### 5.4 Personal-layer data safety *(fixes A-C6, B-C7)*

The persona least likely to have backup hygiene was defaulted into the lose-everything option. Hardened:

- **Backup by default once auth exists:** if Bob has (or gets) a work identity, `copilot personal publish` auto-creates a private backup repo; if he stays local-only, **every `add skill --personal` and every `doctor` run prints a persistent "your personal work is NOT backed up" banner** with the one command to fix it.
- **Edit-model fix** *(fixes A-H14):* Bob is taught to edit via `copilot add/edit skill` (which writes the personal *layer*, the source of truth). Materialized `.claude/` files are made **read-only** where the OS allows; on detected drift, `doctor` **offers to fold the edit back into the personal layer** rather than silently clobbering.

### 5.5 Teaching (P10) & progressive extension

Install ends by teaching self-service: a printed/`~/.copilot/CHEATSHEET.md` cheat-sheet, plus a **guided authoring command** — `copilot add skill --personal` *asks* in plain English, *scaffolds* a valid trigger-rich SKILL.md, files it in the right layer, and materializes. `--department`/`--org` variants exist for Mira/Raj, gated on write permission. `copilot extend <product>` reuses the same idempotent runner, skipping every already-green phase.

---

## 6. Part D — Foundation ownership & the promotion valve (ENAC, hardened)

ENAC owns the foundation but is a **normal enterprise** (`personal › dept › enac-org-private › FOUNDATION`) with a **one-way promotion valve** — no 5th tier. Content flows *down* to the public foundation only through a governed pipeline. Hardened against the red-team:

- **Allow-list, not deny-list, scan** *(fixes B-C1, B-L24):* only files on a curated promotable allow-manifest *and* flagged `Promote-To:` may enter; entropy/secret scanners (gitleaks/trufflehog) are a **secondary** net; **mandatory human diff review is the actual gate.** The scan is a backstop, never the decision. A one-way *public* egress must fail **closed**.
- **Dependency-closure check** *(fixes B-H1, B-H2):* promotion computes the transitive closure (agent→skill→knowledge→mcp it references) and **promotes the whole closure or rejects, naming the missing items.** No dangling public references; no dept→org skill that references a dept-only knowledge doc other departments can't read.
- **Solo-ENAC reality** *(fixes B-H3):* a GitHub Environment approval is self-approval theater when approver = author. At N=1, require a *different* second factor — a mandatory **cooldown/preview window** + external transparency-log notification — and document that the gate is non-functional as separation-of-duties until a co-maintainer exists.
- **TOCTOU re-scan** *(fixes B-M3):* the leak-scan runs again as a **required status on the final merge commit**, blocking auto-merge if the base advanced since the promote-time scan.
- **`copilot promote --to org`** exists for the **separate-repo** case too (cherry-pick preserving author/signature), not just the subfolder `git mv` *(fixes B-M5)*.

Details in [`research/research-foundation-governance.md`](research/research-foundation-governance.md).

---

## 7. Part E — Governance & supply-chain integrity (hardened)

Because `copilot update` **materializes executable-adjacent content** (agents, skills, MCP decls, commands) from private repos onto a user's machine, the resolved set is a build artifact and gets SLSA-style controls. The red-team broke the naive version four ways; all four are fixed.

### 7.1 A real trust root *(fixes B-C3)*

Signature-verify is worthless if the key arrives via the same unauthenticated `curl` as the code (TOFU). **Fixed:** ENAC's public **`root_key` is a pinned, checked-in constant distributed over multiple channels** (the foundation repo, the docs site, `gh` attestation), the bootstrap verifies **its own** signature before running, and releases are logged to a **transparency log (Sigstore)** so key substitution is publicly detectable.

### 7.2 Key rotation that doesn't brick the world *(fixes B-C4)*

A single pinned key + rotation = global hard-fail (the channel that must deliver the new key is gated on the old key). **Fixed:** the trust root is a **set** (`key_set`), releases are **dual-signed** during a rollover window (old ∧ new), keys are add-then-remove, and trust-root updates ship through a channel **independent of the signing gate** (the pinned constant, updated via signed release + transparency log).

### 7.3 Capability policy that a compromised org can't disable *(fixes B-C6, B-H4, B-M4)*

The policy ("department may add skills but never override `agents/sec.md` or `mcp`") is the highest-leverage control *only if* it can't be disabled by the thing it guards. Fixed:

- **Signed by a security-team key distinct from the platform push key** (`policy_signers` in `ecosystem.yml`); a policy change requires that second signer; the resolver **refuses to apply a policy whose signer isn't on the separately-pinned allow-list**. A compromised push identity can't edit away its own guard.
- **Classified by content signature, not filename** *(fixes B-H4):* the guard asks "does this item register a tool / declare an MCP server / define a security-equivalent agent?" — so renaming `sec.md`→`security.md` or hiding an MCP registration inside a skill script **doesn't evade it**. Enforce on behavior, not name.
- **Signed per-item exceptions** *(fixes B-M4):* the security team can `allow: [dept-finance/agents/security-notes.md]` so a legit item unblocks without weakening the class rule. Denials are also mirrored as a **pre-receive/CI check on the author's repo** so Mira fails at push, not silently at 500 consumers *(fixes A-M18)*.

### 7.4 Override can't hide a security fix *(fixes B-C2)*

The scariest finding: Bob overrides org `qa`, org later ships a security fix to `qa`, and `copilot update` says "0 conflicts" while Bob runs the vulnerable version forever. Fixed:

- `copilot update` **diffs shadowed layers too** and flags `your personal qa overrides org qa — org qa CHANGED (a1b2→c3d4)`.
- An upstream author can set a **`security:`/`severity:` trailer that breaks through `override: true`**, forcing the warning regardless.
- A new `doctor` checker **`override-stale`** surfaces every personal override whose shadowed upstream has moved.

### 7.5 Provenance you can trust *(fixes A-M22)*

`resolve --explain` **re-hashes the live file** and flags `MODIFIED — no longer matches recorded SHA` instead of printing stale "signed ✓"; it records the **per-file introducing-commit signer**, not just the tip signer.

---

## 8. Part F — Lifecycle (the events the use cases didn't cover)

### 8.1 The leaver — `copilot deprovision` + a DLP posture *(fixes B-C7, the #1 governance gap)*

Materialize-by-copy + full local clones mean a departing employee keeps a **permanent offline copy** of confidential org/dept content; server-side token revocation does nothing about it. Fixed on two fronts:

1. **`copilot deprovision <org>`** wipes materialized `.claude/` items + layer clones for that org; `copilot update` **fails closed and offers the wipe** when a private layer's auth is permanently revoked.
2. **The honest truth: local git copies can't be clawed back.** So the architecture treats **anything placed in a layer as already-exfiltrable** and adopts a **three-tier DLP posture** — where each class of data is *allowed to live* is a first-class design constraint, not a footnote:

   | Tier | Examples | Where it lives |
   |---|---|---|
   | **Secrets** | passwords, tokens, credentials, client PII | **Never** in any layer. Runtime lookup only — a secrets manager or authenticated API. Materialize-by-copy never touches this tier. |
   | **Systems of record / bulk data** | the company's accounting databases, CRM records, ERP tables | **Stay in those systems.** CLI Copilot is the **runtime gateway** into them — its connectors reach the data at call time with scoped auth; it does **not** copy or materialize the data into a layer. A department's `cli` layer carries connector *definitions* and scoped config — the *door* into the system of record, not the data behind it. |
   | **Proprietary knowledge & process** | department financial processes, forecasts, proprietary methods, confidential-but-not-catastrophic context | **Separate, team-scoped department repos** (§3.1, §4.2) — `topology: separate` by default. Protected by per-repo read access + org SSO; materialized only to authorized members' machines; wiped by `copilot deprovision` on offboarding. |

   Department content (tier 3) is exactly why the topology default flipped to separate-repo: it is confidential business data, and a subfolder can't create a read boundary for it (§3.1, §4.2).

### 8.2 Reorg / transfer *(fixes A-H10, B-M2)*

Department rename or a Bob-transfers-teams event reconciles `layers.department` against `ecosystem.yml.departments[]` (with `renamed_from` aliases) on every `derive` — **detected via the manifest slug change, not a clone-404** (a GitHub rename-redirect would mask the 404). On transfer, the reconciling sync (§3.2) **prunes** orphaned overrides and stale materialized content.

### 8.3 Product disabled

Org flips `cli.enabled: false` → `derive` drops the CLI layers → the **reconciling sync prunes** the already-materialized connectors/MCP decls (§3.2). No orphaned, now-unsanctioned integrations linger.

### 8.4 Version constraints across layers *(fixes A-H9, B-H6)*

The single-`ref` foundation can't satisfy conflicting transitive pins by last-writer-wins. Fixed: **every layer declares `requires: { foundation: <range> }`; resolve intersects all ranges and picks the max satisfying SHA; empty intersection = hard-error naming the conflicting layers.** `requires` is validated against the org's pinned floor **at author/CI time** in the dept/org repo, so one dept push can't break every consumer's update.

Separate-repo-per-department (the confidentiality default, §3.1/§4.2) reintroduces org↔dept **version skew** — the one thing the subfolder topology eliminated for free (same repo, same SHA). This is handled by the same machinery, not new machinery: the per-layer SHA lockfile pins each department repo independently, and the `requires` intersection above still computes the max satisfying foundation SHA across org and dept layers, hard-erroring on a genuine conflict instead of silently drifting.

### 8.5 Multi-org users *(addresses B-C5 — scoped, with the seam pre-built)*

A consultant in two orgs breaks every single-tenant assumption (`layers.org` scalar, one `ecosystem.yml`, one work SSH alias, one policy). This is a **major** gap. Decision: **v1 is explicitly single-org**, but the design pre-builds the seam — layers carry an optional `org` namespace (`acme:dept-finance`), so multi-org is *additive* later (make `layers.org` a set, one SSH alias + one `ecosystem.yml` per org, cross-org policy = most-restrictive-wins, per-org materialization targets). Documented as a known boundary, not silently single-tenant.

---

## 9. Validation — the 30 Critical/High gaps and how the architecture addresses them

This is the filter you asked for: every use case + Bob's journey + enterprise lifecycle, run adversarially against the design. Full reports: [`research/redteam-A.md`](research/redteam-A.md), [`research/redteam-B.md`](research/redteam-B.md). **All 13 Critical and 17 High are addressed above**; the map:

| ID | Severity | The failure | Addressed in |
|---|---|---|---|
| A-C1 | Crit | No-admin Homebrew abort strands Bob before the foundation | §5.1 admin-free bundle |
| A-C2 | Crit | `copilot` binary never installed → handoff `command not found` | §5.1 install+PATH copilot |
| A-C3 | Crit | Corp proxy blocks raw.githubusercontent fetch | §5.1 direct host + proxy-aware + offline bundle |
| A-C4 | Crit | No Windows path | §5.1 `bootstrap.ps1` / WSL |
| A-C5 | Crit | GitHub Enterprise Server unsupported (hardcoded github.com) | §4.2 `host`/`api_base`/`ssh_host`/`mirror` |
| A-C6 | Crit | Local-only personal default = silent data loss | §5.4 backup-default + persistent banner |
| A-H7 | High | SAML 404 misread as "layer gone," silently dropped | §5.3 classify 404 + SSO authorization |
| A-H8 | High | Two machines drift (caret ranges + unsynced lock) | §3.3 shareable lock + resolve-from-lock |
| A-H9 | High | Dept `requires` newer than org floor bricks everyone's update | §8.4 author-time validation + intersect |
| A-H10 | High | Dept rename → stale scalar → 404 → layer dropped | §4.2 `renamed_from` + §8.2 reconcile |
| A-H11 | High | Force-push repair stuck flagging phantom divergence | §5.2 repair split by layer role |
| A-H12 | High | Declared-but-uncreated dept repo 404-dropped | §4.2 existence verify + distinct message |
| A-H13 | High | Org silently shadows a foundation skill for everyone | §7.4 shadowed-layer diff; §8 collision warn |
| A-H14 | High | `materialize-drift` clobbers Bob's direct edits | §5.4 read-only + fold-back |
| A-H15 | High | Undefined `.claude/` root for a project-less Bob | §5.2 user-global `~/.claude/` root |
| B-C1 | Crit | Fail-open deny-list scan on one-way public egress | §6 allow-list + scanners + human gate |
| B-C2 | Crit | Personal override permanently hides upstream security fix | §7.4 shadowed diff + `security:` trailer + `override-stale` |
| B-C3 | Crit | Signature-verify has no trust root (curl TOFU) | §7.1 pinned multi-channel root key |
| B-C4 | Crit | Key rotation hard-fails every install globally | §7.2 key-set + dual-sign rollover |
| B-C5 | Crit | Two-org user breaks single-tenant model | §8.5 scoped v1 + pre-built namespace seam |
| B-C6 | Crit | Compromised org disables its own capability guard | §7.3 policy signed by distinct key |
| B-C7 | Crit | Leaver keeps all confidential content locally | §8.1 `deprovision` + DLP posture |
| B-H1 | High | Promotion ships dangling public references | §6 dependency-closure check |
| B-H2 | High | Dept→org skill references unreadable dept knowledge | §6 reference-resolvability at target tier |
| B-H3 | High | Solo-ENAC approval gate is self-approval theater | §6 cooldown/preview + transparency |
| B-H4 | High | `may_never` evaded by renaming the dimension | §7.3 classify by content, not filename |
| B-H5 | High | Disabled product's integrations orphaned, not removed | §3.2 reconciling sync (prune) |
| B-H6 | High | Transitive foundation pin conflict undefined | §8.4 intersect ranges + hard-error |
| B-H7 | High | Committed manifest leaks org topology | §3.3 split manifest, gitignore |
| B-H8 | High | Committed lock/manifest breaks another machine | §3.3 shareable core vs local overlay |

*(Medium/Low findings — proxy edge cases, rate limits, dept-dept collision warnings, vanity-domain SPOF, provenance re-hash — are folded into §5–§7 or listed in the red-team appendices as P2 polish.)*

---

## 10. The diagram

A companion visual (published as an Artifact) shows: the **3 × 4 matrix** (products × tiers), the **resolution flow** (derive → pull → resolve → materialize-sync → `.claude/`), and the **install flow** (Bob's one command → three rings → working partner). See the linked artifact in the session; source intent is this document's §2–§5.

---

## 11. Open decisions for you

1. **Binary name** — keep `copilot` (brand-consistent, but collides with GitHub's `copilot`/`gh copilot` CLI, §5.1/A-M21) or pick a distinct primary verb (`ccx`, `enac`, invoke via `cc copilot …`)? Affects every command in every doc.
2. **Multi-org scope** (§8.5) — ratify **single-org v1** with the namespacing seam pre-built, or is a two-org consultant a day-one requirement (materially larger design)?
3. **DLP boundary and department topology (§8.1, §3.1, §4.2) — DECIDED (2026-07-06).** Department content is confidential business data (financial figures, forecasts, proprietary methods), so **separate-repo-per-department is the default topology across all products**; `subfolder` is a narrow, explicit opt-in only for genuinely non-confidential departmental content. Confirmed alongside it: **true secrets never materialize into a layer** (runtime lookup only) and **CLI Copilot is a runtime gateway into systems of record, never a copy of their data** (§8.1's three-tier model). This shapes what Knowledge/CLI Copilot layers may contain — no longer open.
4. **Windows strategy** (§5.1/A-C4) — native `bootstrap.ps1`, or WSL-only with a guided WSL install? Determines reach into non-technical corporate desktops.
5. **GHES support depth** (§4.2/A-C5) — first-class (self-hosted foundation mirror + parametric hosts) or "cloud GitHub only" for v1?

---

## 12. Phased roadmap

*No time estimates — phases, priorities, complexity only.*

**P0 — Prove the spine on the cheap dimensions + make Bob's install real.**
Resolver + reconciling-sync materialize (agents/skills/commands + knowledge); `ecosystem.yml` + `copilot derive`; split lock/overlay; the three-ring installer **with the §5.1 corporate-machine fixes** (admin-free bundle, PATH the binary, proxy/offline, `~/.claude/` root, 404 classification, backup-default). *Exit: Bob on a locked-down machine runs one command and gets a working, backed-up, focus-scoped partner.*

**P1 — Governance & lifecycle (the red-team must-fixes).**
Pinned trust root + dual-sign rotation; allow-list promotion + dependency-closure; capability policy (distinct signer, content-classified, signed exceptions); shadowed-layer diff + `security:` trailer + `override-stale`; `copilot deprovision` + DLP posture; reconcile-on-reorg. *Exit: an enterprise can adopt it without a leaver, an override, or a compromised layer becoming an incident.*

**P2 — The hard dimensions + reach.**
Protocol chain-as-data composer; CLI-integration scoping (the net-new seam); Codex parity; Windows/GHES first-class; multi-org namespacing; Cloud Copilot (scope TBD). *Exit: full-fidelity 3×4 across both hosts and all environments.*

**Dependency order:** P0 spine → P1 hangs off the resolver + manifest → P2's hard dimensions reuse P0's composer patterns.

---

## Appendices

**Design:** [`research/design-naming-topology.md`](research/design-naming-topology.md) · [`research/design-bootstrap-orchestration.md`](research/design-bootstrap-orchestration.md) · [`research/design-product-composition.md`](research/design-product-composition.md)
**Validation:** [`research/redteam-A.md`](research/redteam-A.md) · [`research/redteam-B.md`](research/redteam-B.md)
**Foundations:** [`02-four-tier-and-github-topology.md`](02-four-tier-and-github-topology.md) · [`03-use-cases.md`](03-use-cases.md) · [`00-findings-and-recommendations.md`](00-findings-and-recommendations.md)
