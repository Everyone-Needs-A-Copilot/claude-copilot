# Four-Tier Extension Model + GitHub Account Topology

| | |
|---|---|
| **Status** | Research / Proposed (extends [`00-findings-and-recommendations.md`](00-findings-and-recommendations.md)) |
| **Branch** | `ecosystem-extensions` |
| **Date** | 2026-07-06 |
| **Question answered** | "Generalize the model from 3 tiers to **PERSONAL › DEPARTMENT › ORG › FOUNDATION** (and N tiers), map each tier to a **different GitHub account/org**, and give ENAC — who owns the foundation — a way to author foundation changes too." |
| **Appendices** | [`research/research-ntier-arch.md`](research/research-ntier-arch.md) · [`research/research-github-topology.md`](research/research-github-topology.md) · [`research/research-foundation-governance.md`](research/research-foundation-governance.md) |

---

## 1. Bottom line up front

**Going from 3 tiers to 4 (and to N) is ~85% free, because the resolver's precedence is manifest *list order*, not a hardcoded count.** The `00-findings` resolver walk, lockfile, and `resolve --explain` chain are all arity-independent — they iterate an ordered list and keep the nearest winner per name. Adding a `department` tier between `personal` and `org` and re-labelling `public→foundation` is a *data* change, not a *logic* change. The running proof already ships: `cc`'s `paths.knowledge_repo` is an ordered list of arbitrary length that has never known about "3."

The genuinely new work that 4-tier introduces is **not** in the resolver. It is three things:

1. **A department *selection* step** — 3-tier had exactly one private-org layer; 4-tier must answer "*which* department layer applies to this user?" deterministically (no 3-layer analog).
2. **The GitHub account topology** — the four tiers live in three different GitHub namespaces (personal account, enterprise org, ENAC's public org), and one machine must pull all four non-interactively. This is a **credential-disambiguation** problem with exactly one clean answer.
3. **ENAC-owns-the-foundation authoring** — a one-way *promotion pipeline*, not a new resolution tier.

**One-line verdict:** the 4-tier vision is buildable on today's design plus a typed/ranked manifest, one `cc` `layers.*` config namespace, SSH host aliases for multi-account auth, and a `copilot promote` valve. No new GitHub features, no new resolution engine.

---

## 2. The four-tier stack

Precedence (nearest wins, per named unit): **PERSONAL › DEPARTMENT › ORG › FOUNDATION.**

| Rank | Tier | Who authors | GitHub namespace | Visibility | What lives here |
|------|------|-------------|------------------|------------|-----------------|
| 10 (highest) | **PERSONAL** | one individual | the user's **personal** account (`github.com/<user>`) | private | personal-only agents (the "accountant"), personal skills/knowledge |
| 20 | **DEPARTMENT** | a team/department | the **enterprise** org (`github.com/acme-corp`) | private, team-scoped | department-specific skills/agents/knowledge (Finance's tax skills; Eng's deploy commands) |
| 30 | **ORG** | enterprise platform team | the **same** enterprise org | private, org-wide | company-wide capabilities every department inherits |
| 40 (lowest/base) | **FOUNDATION** | ENAC maintainers | `github.com/Everyone-Needs-A-Copilot` | **public** | the open-source framework — global to everyone |

`rank` uses gaps of 10 so a 5th tier (a `squad` below department, a `region` between org and foundation) slots in with **no renumbering** — this is what makes the model N-tier, not merely 4-tier. `role` is an **open string**, not a closed enum: `personal|department|org|foundation` are the *known* roles the UX understands; a `squad` or `partner-consortium` role parses and resolves fine with no special handling.

---

## 3. What changes 3→N, and what does not

**Unchanged (arity-independent) — the entire resolution core:**

| Element | Why it already generalizes |
|---|---|
| **Precedence rule** (nearest-layer-wins per name) | A fold over an ordered list. Valid for any N. |
| **Resolver walk** (`for layer in layers_by_rank`) | Only the loop bound changes; no "3" anywhere. |
| **Lockfile** (resolved SHA per layer) | A per-entry map — 4 vs N is just more rows. |
| **`resolve --explain`** | A shadow-chain print of arbitrary length: `personal/qa shadows dept/qa shadows org/qa shadows foundation/qa`. |
| **Override-vs-accumulate split** | Per-dimension, already present at 3: agents/skills/commands override; knowledge (list-typed) accumulates across *all* layers. Unchanged at N. |
| **`cc` knowledge-list resolver** | `paths.knowledge_repo` is already an ordered list with no cap — the running proof N works. |

**The real deltas:**

1. **Typed, ranked manifest** — the manifest must declare order as a *contract* (explicit `rank`), and each layer must be self-describing (`id`/`role`/`source`/`auth`), so 5+ layers are a data edit with no schema change. See §4.
2. **Department selection** — new determination step; deterministic config value, not a live lookup. See §5.
3. **One `cc` config change** — a `layers.*` namespace (two scalars); `LIST_VALUED_KEYS` and `paths.knowledge_repo` stay untouched. See §7.
4. **Transitive version pins** — personal→department→org→foundation is a 4-deep chain; the flat lockfile handles it, and the recommended topology (§6) collapses one link. See §8.

---

## 4. Manifest schema for N ordered layers

Design goals: order is an **explicit declared contract** (not YAML-incidental); each layer is self-describing; adding a layer needs **no schema change**.

```yaml
# copilot.layers.yml — highest precedence FIRST; rank is the tiebreak of record
version: 1
layers:
  - id: personal-pablo
    role: personal              # open vocabulary, not a closed enum
    rank: 10                    # lower = higher precedence; gaps leave room to insert
    source:
      repo: git@github-personal:pablitoalejo/claude-copilot-private.git
      ref: main
    auth: ssh-personal          # → SSH Host alias "github-personal" (§6)
    activation: always          # always | includeIf:<glob>

  - id: dept-engineering
    role: department
    unit: engineering           # WHICH department this layer serves (§5)
    rank: 20
    source:
      repo: git@github-work:acme-corp/copilot-dept-engineering.git
      ref: v3.x
    auth: ssh-work              # → SSH Host alias "github-work" (§6)

  - id: org-acme
    role: org
    rank: 30
    source:
      repo: git@github-work:acme-corp/copilot-org.git
      ref: v3.x
    auth: ssh-work

  - id: foundation
    role: foundation
    rank: 40
    source:
      repo: https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git
      ref: ^5.13.0              # semver range against the public framework
    auth: anon                  # public HTTPS, no credential
```

**Rules that keep it N-extensible:**

- **`rank` is precedence of record; list order MUST agree** — the resolver asserts `ranks == sorted(ranks)` at load and hard-errors on an equal-rank pair (Nix's error-on-equal-priority). The human reads top-to-bottom; the machine verifies via `rank`.
- **`role` is an open string** — known roles get UX/defaults; unknown roles parse and resolve. This is what makes 5+ tiers free.
- **`source.path`** (optional) lets one repo serve multiple layers — the resolver treats `(repo, path)` as the layer root. This is the seam that makes the "subfolder" department topology (§6 option B) possible without new machinery.
- **`unit`** names which department a `department`-role layer serves — the selection key (§5).
- **`activation`** carries git-`includeIf`-style conditional engagement, so one machine holds many department layers and engages the right one per project context.

---

## 5. Department selection — the new deterministic step

3-tier had one private-org layer. 4-tier must answer "which department?" **deterministically and offline** — the framework is local-first (`cc docs`, `cc memory`, resolve must all work headless). So resolution must **never** depend on a live GitHub team-membership API.

**Recommendation: an explicit config value.**

```bash
cc config set layers.department engineering
```

Resolution reads `layers.department` and substitutes it into any `department`-role layer whose source is templated (`repo: …/copilot-dept-${layers.department}.git` or `path: departments/${layers.department}`). Determination reuses the **existing** `cc` config cascade — no new engine:

1. `CC_LAYERS_DEPARTMENT` env (per-shell / per-worktree override)
2. project `.claude/cc/config.json` — a repo can pin its department
3. machine `~/.claude/cc/config.json` — the user's default department

Git identity (`user.email` domain) or a Teams API lookup may **seed** this value once at `/setup-project` onboarding (to *suggest* the default), but the stored config is the contract — never a runtime lookup.

**A user in two departments** is handled by making it explicit and ordered, not magic: declare **two `department`-role layers** with distinct `unit` and distinct `rank` (engineering `rank: 20`, platform `rank: 21`). Both materialize; `platform/qa` shadows `engineering/qa` shadows `org/qa` — total-ordered by rank, zero ambiguity. Use `activation: includeIf:<glob>` when the second department should engage only in matching project contexts. **Never** infer a "primary department" from a membership set — that reintroduces non-determinism.

---

## 6. GitHub account topology — the multi-account problem

The four tiers span **three GitHub namespaces**, and one dev machine must authenticate as **three distinct credentials against what is, to git, one host (`github.com`)**:

- **personal identity** → `github.com/<user>/claude-copilot-private`
- **enterprise identity** → `github.com/acme-corp/copilot-org` **and** `…/copilot-dept-engineering`
- **anonymous HTTPS** → the public `Everyone-Needs-A-Copilot/claude-copilot`

### 6.1 Multi-account auth — SSH host aliases (the only clean answer)

**The decisive fact:** every HTTPS-based credential helper (`gh`, osxkeychain, PAT-in-keychain) keys credentials **by hostname**. Both private tiers are `github.com`, so two identities against one hostname **collide**. `gh auth switch` is *global per host* and stateful — it cannot disambiguate two github.com accounts in a headless fan-out (open issue [cli/cli#8875]).

**SSH host aliases are the only mechanism that selects the credential from the URL string itself**, because the alias (`github-personal` / `github-work`) is a distinct SSH `Host` block with its own `IdentityFile`, even though both resolve `HostName github.com`.

```sshconfig
# ~/.ssh/config
Host github-personal          # tier 1 (personal)
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_personal
    IdentitiesOnly yes        # MANDATORY — else ssh-agent offers every key and determinism breaks

Host github-work              # tiers 2 + 3 (department + org, same enterprise key)
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_work
    IdentitiesOnly yes
```

Layer remote URLs bake the alias in, so each clone self-selects its key:

```
tier 1 personal    → git@github-personal:<user>/claude-copilot-private.git   auth: ssh-personal
tier 2 department  → git@github-work:acme-corp/copilot-dept-engineering.git  auth: ssh-work
tier 3 org         → git@github-work:acme-corp/copilot-org.git               auth: ssh-work
tier 4 foundation  → https://github.com/Everyone-Needs-A-Copilot/…           auth: anon
```

- **Manifest `auth` enum:** `ssh-personal` / `ssh-work` / `anon` / `gh-app:<slug>`. The resolver maps `auth` → transport with **zero prompting** — the SSH alias in the URL *is* the credential selector, so `copilot update` pulls all four in one pass, three identities, no global state switch, no ordering hazard. `BatchMode=yes` makes a missing key fail fast instead of hanging headless.
- **Commit identity/signing** is a *separate* concern from auth — handled by `includeIf "hasconfig:remote.*.url:git@github-work:**/**"` (Git 2.36+) pointing at a per-tier `.inc` with the right `user.email` + `signingkey`. Auth follows the SSH alias; *who you commit as* follows the remote URL.
- **CI / shared runners** (no per-developer SSH key): use `auth: gh-app:<slug>` → the resolver mints a short-lived GitHub App installation token and clones over HTTPS with it.

### 6.2 Department-vs-org repo topology — the one open decision

This is the single point where the two research streams diverged, and it is a **real** decision the enterprise must make. GitHub's hard constraint drives it: **read-confidentiality on GitHub is per-repository — there are no path-level read ACLs. `CODEOWNERS` governs review routing, not read access.**

| | **Option A — separate repos** | **Option B — one org repo, subfolders** |
|---|---|---|
| Shape | `acme-corp/copilot-org` + `acme-corp/copilot-dept-<name>` per department | one `acme-corp/copilot` with `org/` + `departments/<unit>/`; department layer = `(repo, path)` |
| Cross-department read | **Isolated** — a department can't read another's repo | **All departments see every dept folder** (no path ACLs) |
| Version skew | org↔dept are separate pins (manageable via lockfile) | **org↔dept skew impossible** — same repo, same SHA |
| Write governance | per-repo CODEOWNERS + rulesets, clean isolation | dir-level CODEOWNERS (review only), coarser |
| Ops overhead | 1 + D repos, D grows with departments | one clone, one release train |

**Decision rule — pick by confidentiality, not by taste:**

- **If any department's content must be confidential from other departments → Option A (separate repos).** GitHub gives no other way to create a per-department read boundary. This is the safe enterprise default and the recommendation when in doubt.
- **If all departments are mutually readable (organizational scoping, not secrecy) → Option B (subfolders)** buys real wins: no org↔dept version skew (one SHA), one clone, and "promote dept→org" becomes moving a file up a directory.

**The architecture does not force the choice.** Because the manifest layer source is `(repo, path)`, a `department` layer can be *either* a separate repo (Option A: `repo` differs, no `path`) *or* a subfolder (Option B: same `repo`, distinct `path`). Enterprises pick per their confidentiality needs; the resolver is identical either way. **Recommended default: Option A**, because "department" usually exists precisely to scope content, and per-repo isolation is the only true read boundary GitHub offers.

### 6.3 GitHub teams mapping

Map access with GitHub's real primitives — and note the inheritance *direction*: **nested-team grants cascade parent→child.** So:

```
Team acme-corp/engineering  (department, a team)  → read/write acme-corp/copilot-dept-engineering
Org base permission = read  (every member)        → read       acme-corp/copilot-org
```

Do **not** model "org is the parent of department" via nesting — inheritance flows downward, so an org-as-parent team would grant *every* member every department's repo. Org-wide read is the org **base permission** (or an `everyone` team); department read is a *narrower* team grant on a *separate* repo. The resolver precedence (dept > org) lives in the manifest and is independent of GitHub's team tree.

### 6.4 Enterprise onboarding

One bootstrap wires org + department + foundation and leaves the personal seam open (mirrors the existing personal `claude-copilot-private/bootstrap.sh`):

1. Verify the enterprise SSH key authenticates as `github-work` (fail loud, headless-safe).
2. Determine department: `cc config get layers.department`, else *suggest* via `gh api /orgs/<org>/teams` and persist the answer as config.
3. Clone the three enterprise/public layers with the correct identity per URL.
4. `cc config` the manifest layers (foundation < org < dept), print the optional personal-layer opt-in.
5. `copilot update` materializes the resolved `.claude/`.

Full script sketch in [`research/research-github-topology.md`](research/research-github-topology.md) §5.

---

## 7. `cc` config changes

- **Add a `layers.*` scalar namespace:** `layers.manifest` (pointer to `copilot.layers.yml`) and `layers.department` (§5 selection key). Both are plain scalars that ride the **existing** env›project›machine cascade with zero new resolution logic; `CC_LAYERS_MANIFEST` / `CC_LAYERS_DEPARTMENT` env overrides come free from the `CC_<UPPER_DOTTED>` convention.
- **Leave `paths.knowledge_repo` unchanged** — it stays the list-valued key for the accumulate-dimension; the resolver *populates* it from the manifest's knowledge dirs, so `cc env` keeps emitting `CC_PATHS_KNOWLEDGE_REPO` (back-compat preserved).
- **Do NOT** add parallel index-aligned string lists (a reorder desyncs role↔path — a known bug farm). **Do NOT** turn department/org/foundation into `cc` config *scopes* — the config-file cascade (env/project/machine) is orthogonal to the layer stack. Keep the stack as *data the resolver reads* and `cc` config as the *pointer + selection* only.

Net: one new dotted-key namespace, two scalars, zero change to `LIST_VALUED_KEYS`. Complexity: **Low**.

---

## 8. ENAC owns the foundation — authoring & promotion

**The user's framing — "the foundation is ENAC's org layer, published" — is directionally right but geometrically inverted.** The foundation is not ENAC's org layer; it is the **public floor that ENAC's *private* org layer sits on top of.** If the foundation *were* ENAC's org layer, ENAC would have nowhere private to stage, and everything ENAC authored would be public by construction — which breaks the "ENAC-internal content that must never go public" requirement.

**So ENAC runs a normal 4-tier stack** — `personal › department › enac-org-private › FOUNDATION(public)` — identical to any enterprise. ENAC content has one of three fates:

| Fate | Lives in | Ever public? |
|---|---|---|
| **Never-public** (client names, internal ops agents, ENAC business knowledge) | `enac-org-private` permanently | No |
| **Not-yet-public** (a foundation change staged before it's vetted/generic) | `enac-org-private` temporarily | After promotion |
| **Generic/vetted** (the industrial-designer protocol step; a broadly useful skill) | promoted DOWN to `FOUNDATION` | Yes |

### 8.1 No 5th tier — a promotion pipeline instead

Reject a distinct "staging" resolution rank: staging is a *repo state* (a branch, a not-yet-promoted directory), not a *precedence rank*. Encoding it as a rank would pollute the clean 4-tier semantics and make every other enterprise carry a dead tier. **`enac-org-private` IS the staging area; promotion is a pipeline event.**

### 8.2 The promotion flow — `copilot promote` → cherry-pick → leak-scan → PR

Respecting this repo's constraints (PR-only, signed commits, CodeQL, branch protection), a raw mirror/subtree/direct-push is disallowed — it would bypass the PR gate. Promotion must land as a **normal PR into the public foundation**:

1. **Author** in `enac-org-private` on a signed branch; the content is exercised by ENAC's own daily use.
2. **Flag** generic, world-safe content with a `Promote-To: foundation` commit trailer (or a `promote/` path convention). Absence = stays private forever (never-public is the safe default).
3. **`copilot promote`** — cherry-picks the flagged commits (author + signature preserved, GitHub Private-Mirrors-style) onto a fresh branch in a checkout of the public foundation repo; runs a **hard-fail leak scan** (deny-list: client names, `.env`, tokens, `mcp.json` secrets, internal-knowledge globs); opens a **PR into public `foundation:main`**, which runs the *existing* CodeQL + required-review + signed-commit protection unchanged.
4. **Public review + merge** under foundation CODEOWNERS. ENAC pulls the change back as its foundation floor on the next `copilot update`; the temporary private copy is retired.

Egress is strictly **one-way** (private→public). Ingress is the ordinary `copilot update` pull every enterprise runs. Gate the public-PR job behind a **GitHub Environment approval** so promotion to the world is deliberate and logged. Guard the **open-core starvation anti-pattern** — because ENAC eats its own dogfood, an under-fed public foundation degrades ENAC's *own* floor, so "generic → promote" must be the reviewed default, and a growing never-promoted delta is a governance smell to review, not a moat to defend.

---

## 9. Governance & supply-chain integrity across 4 tiers

`copilot update` auto-pulls and **materializes executable-adjacent content** (agents, skills, MCP declarations, commands) from org and department private repos into a user's `.claude/`. A compromised department push becomes code the user's agent runs. Four controls, in priority order:

1. **SHA-pinned lockfile per layer** (`copilot.lock`) — the reproducibility anchor everything else verifies against.
2. **Signature-verify-before-materialize** — `copilot update` verifies each pulled layer's tip is signed by an allowed key (foundation = ENAC release key; org/dept = org-managed allow-list) before copying anything into `.claude/`. Unsigned/unknown-signer → refuse, don't silently proceed.
3. **Per-layer capability allow/deny policy — the highest-leverage new control.** A policy file declares which layers may contribute which dimension:
   ```yaml
   layers:
     department:
       may_add: [skills, knowledge, commands]
       may_override: []                  # dept may ADD skills but NOT override any agent
       may_never: [agents/sec.md, mcp]   # security agent + MCP decls off-limits
   ```
   Enforced at materialize time — a department item targeting a denied dimension/name is dropped and reported. This bounds blast radius **even when a layer is compromised**. If only one control ships first, ship this one.
4. **`resolve --explain` audit trail** — per materialized item: winning layer, shadowed layers, source SHA, signer, and any policy denials; persisted to `copilot.audit.json`. Pair with `resolve --check` (drift detection, mirroring `cc memory check`).

**Per-layer push governance:** signed commits + CODEOWNERS-per-dimension + GitHub required-reviewer rulesets at every non-personal layer, with executable-adjacent paths (`agents/**`, `skills/**`, `mcp`) carrying heavier review than knowledge/docs. Org SSO/SAML is the identity floor beneath CODEOWNERS. Trust in a department layer is transitive through (a) SSO proving the pusher is a real employee, (b) required CODEOWNER review (no solo malicious push), (c) signed commits, and (d) the capability policy capping what a department may contribute — so no single compromised account ships an executable to users.

---

## 10. Prior art that transferred

- **GitLab subgroups** (up to 20 nested levels; membership inherits parent→child) — validates precedence-as-a-tree and confirms inheritance cascades downward, which is why department is the parent team and org is the base permission, not the reverse. Also confirms the confidentiality unit is the container (→ separate repos per department).
- **npm scopes + org teams** (`@acme/*` namespace per owner) — backs the optional layer-namespacing (`acme/qa` vs `pablo/qa`) that closes the dependency-confusion-class collision.
- **chezmoi** (public dotfiles repo, per-machine secrets, one file = one owner) — backs materialize-don't-merge + whole-unit override extended to 4 tiers, and the public-repo-stays-clean-via-`@machine`-sentinels discipline.
- **GitHub Private Mirrors App** — private-ahead-of-public with history/signing/authorship preserved: the turnkey precedent for the promotion valve.
- **Upstream-first policy / open-core anti-pattern** — land-public-before-private discipline and the starvation trap ENAC must actively guard against.

---

## 11. Decisions to ratify

| # | Decision | Complexity | Priority |
|---|----------|-----------|----------|
| 1 | Precedence = manifest list ORDER + explicit `rank`; N-tier resolver = 3-tier walk with a larger loop bound | Low | P0 |
| 2 | Typed/ranked manifest (`id`/`role`(open)/`rank`/`source{repo,ref,path}`/`auth`/`activation`); 5+ tiers = data edit | Low | P0 |
| 3 | **Department-vs-org topology: default separate repos (Option A) for read-confidentiality; subfolders (Option B) allowed when all-readable. Manifest `(repo,path)` supports both — enterprise picks.** | Med | P0 |
| 4 | Department selection = explicit `cc config set layers.department`; API only *suggests* at onboarding | Low | P0 |
| 5 | Multi-account auth = **SSH host aliases** (`github-personal`/`github-work`, `IdentitiesOnly yes`); anon HTTPS for foundation; GitHub App tokens for CI. Manifest `auth`: `ssh-personal`/`ssh-work`/`anon`/`gh-app:<slug>` | Med | P0 |
| 6 | `cc` config: add `layers.manifest` + `layers.department` scalars; keep `paths.knowledge_repo` list; no parallel arrays; layers are NOT config scopes | Low | P0 |
| 7 | **ENAC = normal enterprise (`personal›dept›enac-org-private›FOUNDATION`) + a one-way promotion valve. No 5th tier.** | Med | P1 |
| 8 | Promotion = `copilot promote` → cherry-pick → hard-fail leak-scan → PR into public foundation; GitHub Environment-gated; never mirror/subtree/direct-push | High | P1 |
| 9 | Supply-chain: SHA lockfile + signature-verify-before-materialize + **per-layer capability allow/deny policy** + `resolve --explain` audit. Capability policy first. | High | P1 |
| 10 | Transitive version pins handled by flat per-layer lockfile + enforced per-layer `requires`/minVersion; Option B collapses org↔dept skew | Med | P1 |

**One-paragraph verdict:** the 4-tier (and N-tier) model costs far less than the number 4 suggests — the resolver, lockfile, and `--explain` are arity-independent, so the model is a typed manifest, a department selection scalar, and SSH host aliases away from working. The only genuinely new architecture is the department read-confidentiality decision (which GitHub forces to per-repo) and ENAC's one-way promotion valve to the public foundation. Build and dogfood the whole loop inside ENAC's own repos first — `claude-copilot` (public) = FOUNDATION, a new private ENAC-org repo above it, and the existing `claude-copilot-private` as the personal-layer fixture.

---

## Appendices

- [`research/research-ntier-arch.md`](research/research-ntier-arch.md) — full N-tier generalization ADR (manifest schema, resolver algorithm, dept-vs-org modeling, `cc` config change, version-skew).
- [`research/research-github-topology.md`](research/research-github-topology.md) — GitHub repo topology + multi-account credential architecture (SSH aliases, `includeIf`, GitHub App tokens, onboarding script, prior art).
- [`research/research-foundation-governance.md`](research/research-foundation-governance.md) — ENAC-owns-foundation authoring, the promotion pipeline, per-layer governance, and supply-chain controls.
