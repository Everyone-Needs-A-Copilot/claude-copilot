# GitHub Naming Convention & Repo Topology for the 3×4 Copilot Ecosystem

| | |
|---|---|
| **Status** | Design / Proposed (extends [`02-four-tier-and-github-topology.md`](../02-four-tier-and-github-topology.md)) |
| **Branch** | `ecosystem-extensions` |
| **Question answered** | "Give the ecosystem a GitHub naming convention + topology that is human-clear AND fully COMPUTABLE — so a bootstrap can DERIVE every repo URL from minimal input (org + department), across 3 product families × 4 tiers." |

---

## 0. The matrix we are naming

Three product families, each independently layered across the same four tiers:

| Axis | Values |
|---|---|
| **product** | `claude` / `codex` (foundation host, mutually exclusive per machine), `knowledge`, `cli` |
| **tier** | `personal` (rank 10) › `department` (20) › `org` (30) › `foundation` (40) |

Products are adopted **progressively**: everyone starts on the `claude`/`codex` foundation (it works standalone), then opts into `knowledge`, then `cli`. Each family layers independently but they all read through the **one shared resolver** in `cc`. Naming must therefore be a pure function of `(product, tier, org, dept, user)` so the installer can compute any cell without a lookup table.

---

## 1. The naming convention — a deterministic template

**One-line pattern** (owner and repo are each a deterministic slug function):

```
owner(tier)  = { personal: <user-slug>,  department|org: <org-slug>,  foundation: "Everyone-Needs-A-Copilot" }
repo(product,tier) = {
  foundation:  "<product>-copilot"                      # the real OSS repos
  org:         "copilot-<product>-org"
  department:  "copilot-<product>-dept-<dept-slug>"      # Option A (separate repo)
  personal:    "copilot-<product>-private"               # only if a personal REMOTE exists
}
URL = ssh_alias(tier) + ":" + owner(tier) + "/" + repo(product,tier) + ".git"
```

`ssh_alias(tier)` = `github-personal` (personal) · `github-work` (department, org) · `anon HTTPS` (foundation) — exactly the aliases §6 of doc 02 mandates. Every slug is `[a-z0-9-]` (lowercased, spaces→`-`), so names are collision-safe and shell-safe.

Reserved product token `claude`|`codex` collapses to the **host** the machine runs; `knowledge` and `cli` are host-agnostic and shared across both.

### 1.1 The filled 12-cell matrix (worked example)

Inputs: foundation owner `Everyone-Needs-A-Copilot`; enterprise `acme-corp`; department `finance`; user `bob`.

| tier ↓ / product → | **claude/codex** (foundation host) | **knowledge** | **cli** |
|---|---|---|---|
| **foundation** (`Everyone-Needs-A-Copilot`, anon HTTPS) | `Everyone-Needs-A-Copilot/claude-copilot` *(or `/codex-copilot`)* | `Everyone-Needs-A-Copilot/knowledge-copilot` | `Everyone-Needs-A-Copilot/cli-copilot` |
| **org** (`acme-corp`, `github-work`) | `acme-corp/copilot-claude-org` | `acme-corp/copilot-knowledge-org` | `acme-corp/copilot-cli-org` |
| **department=finance** (`acme-corp`, `github-work`) | `acme-corp/copilot-claude-dept-finance` | `acme-corp/copilot-knowledge-dept-finance` | `acme-corp/copilot-cli-dept-finance` |
| **personal=bob** (`bob`, `github-personal`) | `bob/copilot-claude-private` *(opt-in)* | `bob/copilot-knowledge-private` *(opt-in)* | `bob/copilot-cli-private` *(opt-in)* |

The three **foundation** cells are the real, existing OSS repos (`claude-copilot`, `knowledge-copilot`, `cli-copilot`) — the convention is bent exactly once, for the public floor, because those names predate the scheme and are the product's public identity. Everything private follows the strict `copilot-<product>-<tierslug>` grammar. `codex-copilot` swaps in for `claude-copilot` on Codex machines (§6).

### 1.2 Why this is computable from just "acme-corp" + "finance"

Bob (a new Finance employee) supplies **two tokens**. The installer needs nothing else to derive **every private URL** in his column-set:

```
given: org=acme-corp, dept=finance, host=claude   (host detected from which foundation is installed)
for product in [claude, knowledge, cli]:            # only those the org enabled — see §2
  org-repo  = git@github-work:acme-corp/copilot-<product>-org.git
  dept-repo = git@github-work:acme-corp/copilot-<product>-dept-finance.git
  found-repo= https://github.com/Everyone-Needs-A-Copilot/<product>-copilot.git   # (claude|knowledge|cli)-copilot
```

No human types a URL. `org` picks the GitHub owner + SSH alias; `dept` fills the `-dept-<slug>` suffix; `product` fills the middle token; the foundation is a constant. This is the whole point: **the convention IS the resolver's input, so the bootstrap is `derive(org, dept)` not `paste(url × 9)`.**

---

## 2. The org "ecosystem manifest" — the self-describing seed

The convention above computes *candidate* names, but an org must still declare **which products it enabled, what its departments are, any name overrides, auth mode, and pinned foundation versions**. That declaration is a single published artifact the installer fetches given **only the org name**.

**Where it lives — a well-known repo at a computable path:** `github.com/<org>/copilot-ecosystem`, file `ecosystem.yml` at repo root. This is the one seed name that is itself a constant (`copilot-ecosystem`), so discovery needs zero prior knowledge: given `acme-corp`, fetch `git@github-work:acme-corp/copilot-ecosystem.git//ecosystem.yml`.

**Discovery (deterministic fallback chain, first hit wins):**

1. `git@github-work:<org>/copilot-ecosystem.git` → `ecosystem.yml` (the canonical seed repo).
2. `gh api /orgs/<org>/.github` fallback: an `ecosystem.yml` in the org's `.github` profile repo (GitHub's own well-known-config convention).
3. Org **repo topic** `copilot-ecosystem` on any repo → read its `ecosystem.yml` (last-resort search so a renamed seed is still findable via `gh search repos --owner <org> --topic copilot-ecosystem`).

Seed repo is **public-readable to org members** (or anon for public orgs) so onboarding needs no credential beyond the SSH key that already authenticates `github-work`. It is the ONE thing IT publishes; everything else is derived.

### 2.1 Schema

```yaml
# acme-corp/copilot-ecosystem :: ecosystem.yml — published ONCE by IT
version: 1
org: acme-corp
owner_slug: acme-corp                 # GitHub owner (defaults to org)
auth: ssh-work                        # ssh-work | gh-app:<slug> | anon (drives §6 credential)
naming:
  # the convention (§1) is the DEFAULT; overrides only where an org deviates
  scheme: "copilot-<product>-<tier>"  # informational; installer ships the canon
  overrides:                          # explicit exceptions, keyed (product, tier)
    - { product: cli, tier: org, repo: acme-corp/devtools-copilot-org }
products:                             # which families this org has enabled + pinned floors
  claude:   { enabled: true,  foundation: "^5.14.0" }
  knowledge:{ enabled: true,  foundation: "^2.3.0", topology: subfolder }  # per-product topology (§5)
  cli:      { enabled: false }        # not adopted yet → installer skips its column
departments:                          # the authoritative dept list (drives -dept-<slug>)
  - { slug: finance,     lead: "@acme-corp/finance-leads" }
  - { slug: engineering, lead: "@acme-corp/eng-leads" }
  - { slug: platform,    lead: "@acme-corp/platform" }
foundation_owner: Everyone-Needs-A-Copilot   # override only for a fork/mirror
```

The installer's algorithm: fetch `ecosystem.yml` → for each `products.*.enabled` → for the user's `dept` and `personal` → apply `naming.overrides` if present, else compute via §1 canon → emit a `copilot.layers.yml` (§3). **One fetch, entire matrix derived.** `departments[]` is the closed set that makes `-dept-<slug>` names verifiable (an unknown dept slug errors instead of computing a 404 URL). This is what makes the ecosystem self-organizing: adding a department or enabling `cli` is a one-line edit to this seed, and every employee's next `copilot update` picks it up.

---

## 3. How the 3 products compose over the shared resolver

**Recommendation: ONE `copilot.layers.yml` manifest with per-product layer stacks (a `product` axis on each layer), not three separate manifests.**

The resolver in doc 02 §4 already keys precedence on `rank` and is arity-independent. Adding a `product:` field to each layer entry lets a single manifest carry all enabled products; the resolver groups by `product`, then folds each group by `rank` exactly as today. Materialization is per-product into that product's discovery target (`claude`→`.claude/`, `knowledge`→`paths.knowledge_repo`, `cli`→cli connector registry).

```yaml
version: 1
department: finance
layers:
  # --- claude foundation host ---
  - { id: found-claude, product: claude, role: foundation, rank: 40,
      source: { repo: https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git, ref: "^5.14.0" }, auth: anon }
  - { id: org-claude,   product: claude, role: org, rank: 30,
      source: { repo: git@github-work:acme-corp/copilot-claude-org.git, ref: v3.x }, auth: ssh-work }
  - { id: dept-claude,  product: claude, role: department, unit: finance, rank: 20,
      source: { repo: git@github-work:acme-corp/copilot-claude-dept-finance.git, ref: v3.x }, auth: ssh-work }
  # --- knowledge product (subfolder topology → (repo, path)) ---
  - { id: found-know,   product: knowledge, role: foundation, rank: 40,
      source: { repo: https://github.com/Everyone-Needs-A-Copilot/knowledge-copilot.git, ref: "^2.3.0" }, auth: anon }
  - { id: org-know,     product: knowledge, role: org, rank: 30,
      source: { repo: git@github-work:acme-corp/copilot-knowledge-org.git }, auth: ssh-work }
  - { id: dept-know,    product: knowledge, role: department, unit: finance, rank: 20,
      source: { repo: git@github-work:acme-corp/copilot-knowledge-org.git, path: departments/finance }, auth: ssh-work }
  # --- cli product: disabled in this org → absent ---
  # --- personal layers appended locally, per-product, only if Bob opts in (§4) ---
```

**Why one manifest, not three:**

- **Single lockfile / single `copilot update` fan-out.** Three manifests → three lockfiles, three update passes, three provenance diffs to reconcile. One manifest keeps `copilot update` one command and `copilot.lock` one reproducibility anchor across all products.
- **Shared auth + department selection.** `auth: ssh-work` and `department: finance` are identical across products — three manifests would duplicate (and risk desyncing) them.
- **The `product` axis is free.** It is one more grouping key on a fold the resolver already does per `rank`; it does not touch precedence logic.
- **Progressive adoption is an append, not a new file.** Enabling `cli` later adds three rows to the existing manifest (regenerated from `ecosystem.yml`), not a fourth manifest to wire.

The manifest is **generated**, never hand-written: `copilot derive` reads `ecosystem.yml` + `cc config get layers.department` + local personal opt-ins and emits it.

---

## 4. The personal tier for a non-technical user (Bob)

**Recommendation: the personal layer is LOCAL-FIRST — zero GitHub account required to start. It becomes GitHub-backed only when Bob opts into cross-machine portability.**

Bob in Finance is not a developer. Forcing a personal GitHub repo before he can save one personal note or a personal `accountant` agent is an adoption tax that kills the "everyone starts on the foundation" promise. So:

| Stage | Where personal content lives | GitHub account needed? |
|---|---|---|
| **Local (default)** | `~/.copilot/layers/<product>-personal/` — a plain local git repo (or bare dir), **no remote** | **No** |
| **Portable (opt-in)** | same dir, `git remote add origin git@github-personal:bob/copilot-<product>-private.git` | Yes, when Bob wants sync |

The naming convention **accommodates "no personal remote yet"** by making the personal layer's `source` a **local path**, with the remote as an optional, later-added field:

```yaml
- id: personal-bob
  product: claude
  role: personal
  rank: 10
  source: { path: ~/.copilot/layers/claude-personal }   # LOCAL — no repo:, no auth
  activation: always
# ...later, `copilot personal publish claude` adds:
#   source: { path: ~/.copilot/layers/claude-personal,
#             repo: git@github-personal:bob/copilot-claude-private.git, ref: main }
#   auth: ssh-personal
```

The resolver already treats a layer root as `(repo|path, path)` (doc 02 §4), so a `path`-only layer resolves and materializes identically to a remote one — the only difference is `copilot update` skips the pull for a remote-less layer. The computed name `bob/copilot-claude-private` is **reserved by the convention** but not **created** until `copilot personal publish` runs (which creates the private repo via `gh repo create` and pushes). So the name is always predictable; the repo's existence is lazy. Non-technical Bob never sees GitHub until he owns two machines and wants his accountant agent on both.

---

## 5. Department-as-repo vs department-as-subfolder — per product

Doc 02 §6.2 forces this choice by **read-confidentiality** (GitHub has no path-level read ACL). The key refinement here: **the decision is per-product, declared in `ecosystem.yml`'s `products.<name>.topology`,** because the products have different confidentiality shapes:

| Product | Typical topology | Rationale |
|---|---|---|
| **claude** (agents/skills/commands) | **Option A — separate repo** `copilot-claude-dept-<slug>` | Executable-adjacent content; departments often want isolation, and per-repo CODEOWNERS gives a real write boundary. Default. |
| **knowledge** | **Option B — subfolder** `copilot-knowledge-org//departments/<slug>` | Company knowledge is usually mutually readable; subfolder kills org↔dept version skew (one SHA) and makes dept→org promotion a `git mv`. |
| **cli** | **Option A — separate repo** | Integrations may carry scoped credentials/config; isolate. |

The manifest expresses both uniformly: Option A → `source.repo` differs, no `path`; Option B → same `source.repo`, distinct `source.path`. The resolver is identical either way (it resolves `(repo, path)` roots). So `ecosystem.yml` sets `topology: separate|subfolder` per product, and `copilot derive` emits the right `source` shape — the naming convention's `-dept-<slug>` suffix is used for Option A repos, and the `departments/<slug>` path for Option B. One org can run knowledge as subfolders and agents as separate repos with no resolver change.

---

## 6. Codex vs Claude — one scheme, both hosts

The foundation host is **either** `claude` **or** `codex`, chosen per machine (they are twin hosts over the shared `cc`/`tc` substrate, per doc 00 §3.4). The naming convention handles both by making the host product token a variable:

- Foundation repos: `Everyone-Needs-A-Copilot/claude-copilot` **and** `Everyone-Needs-A-Copilot/codex-copilot` both exist publicly; the installer picks by detected host.
- Private host layers mirror the token: `acme-corp/copilot-claude-org` vs `acme-corp/copilot-codex-org`, `…-dept-finance`, `…-private`.
- **Shared, host-agnostic layers stay single-token:** `knowledge` and `cli` are NOT host-specific — `acme-corp/copilot-knowledge-org` serves both a Claude machine and a Codex machine unchanged. Only the `claude`/`codex` product column forks by host; the other two columns are shared across hosts.

`ecosystem.yml` declares which host(s) the org supports:

```yaml
products:
  claude: { enabled: true, foundation: "^5.14.0" }
  codex:  { enabled: true, foundation: "^1.8.0" }   # org supports BOTH hosts
  knowledge: { enabled: true }                       # shared by both
  cli:    { enabled: true }                           # shared by both
```

A machine detects its host (which foundation binary is installed), selects that host's product column, and shares the `knowledge`/`cli` columns with the other host. So an org that runs a mix of Claude and Codex developers publishes **one** `ecosystem.yml`; each machine derives its own host column plus the two shared columns. The convention is host-parametric, not host-duplicated.

---

## 7. Summary — the whole thing is computable

| Question | Answer |
|---|---|
| Repo name of any private cell | `owner(tier)/copilot-<product>-<tierslug>` (foundation = `Everyone-Needs-A-Copilot/<product>-copilot`) |
| Credential for any cell | `ssh_alias(tier)`: personal→`github-personal`, dept/org→`github-work`, foundation→anon — encoded IN the URL |
| Minimal human input | `org` + `dept` (host auto-detected); everything else derived |
| The one thing IT publishes | `<org>/copilot-ecosystem :: ecosystem.yml` |
| How it's discovered | seed repo `copilot-ecosystem` (const name) → `.github` profile → topic search |
| Manifest shape | ONE `copilot.layers.yml` with a `product` axis; generated by `copilot derive`, never hand-typed |
| Bob's personal tier | local-first `path` layer, no GitHub account; `copilot personal publish` creates `bob/copilot-<product>-private` only on opt-in |
| Dept topology | per-product, from `ecosystem.yml`: claude/cli = separate repo, knowledge = subfolder |
| Codex vs Claude | host token is a variable; `knowledge`/`cli` columns shared across both hosts |

The convention is the input to the resolver, the `ecosystem.yml` seed is the one published fact, and every URL in the 3×4 matrix is a pure function of `(product, tier, org, dept, user)` — so the bootstrap **derives** the ecosystem rather than being handed it.
