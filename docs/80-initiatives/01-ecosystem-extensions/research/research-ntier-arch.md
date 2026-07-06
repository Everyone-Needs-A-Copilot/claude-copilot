# N-Tier Layer Generalization — Architecture Design (ADR)

| | |
|---|---|
| **Status** | Proposed (extends `00-findings-and-recommendations.md` §5) |
| **Branch** | `ecosystem-extensions` |
| **Question answered** | "Generalize the 3-tier (public→company→personal) resolver to a FOUR-tier — personal › department › org › foundation — and in principle N-tier — stack, deterministically." |
| **Decision axis** | precedence = manifest list ORDER; department-vs-org modeling; minimal `cc` config change |

---

## 1. How much of the 3-layer design already generalizes to N

**Thesis: precedence is manifest list ORDER, so N is almost free.** The §5 design never actually encodes "3" as a semantic constant — it encodes an *ordered walk* over a list. Everything that makes it work (per-name last-writer-wins, whole-unit override, reported shadowing, hard-error on same-layer collision) is a property of *"iterate an ordered list and keep the nearest winner per key,"* which is arity-independent. The number 3 appears only in prose, examples, and one config affordance — never in a resolution invariant.

| Design element (§5) | Fixed-at-3? | Why it generalizes / where 3 leaks |
|---|---|---|
| **Precedence rule** (`personal > company > public`, last-writer-wins per named unit) | **N-ready** | It is a fold over an ordered list. Adding `department` and re-labelling `company→org`, `public→foundation` is a data change, not a logic change. The rule is "nearest layer wins," valid for any N. |
| **Manifest** (`copilot.layers.yml`, west-style) | **N-ready in shape, 3-biased in examples** | Already "lists the layer repos with a pin per layer." A list literally has no arity ceiling. Only the *example* shows 3 entries. Needs an explicit ordered-with-`rank` schema (§2) so order is a declared contract, not incidental YAML ordering. |
| **Lockfile** (`copilot.lock`, resolved SHA per layer) | **N-ready** | "Record resolved SHA per layer" is a per-entry map. 3 vs 4 vs N is just more rows. |
| **`resolve --explain`** (git `--show-origin` shadow report) | **N-ready** | "personal/qa shadows company/qa shadows public/qa" is a chain print of arbitrary length. 4 layers just prints a 4-deep chain (§4). |
| **Resolver walk** (§5.3) | **N-ready** | The walk is `for layer in layers_in_precedence_order`. Only the loop bound changes. No 3 anywhere. |
| **`cc` knowledge-list resolver** (`resolve_knowledge_repos`, `config.py:176-201`) | **N-ready TODAY** | `paths.knowledge_repo` is already an *ordered list of arbitrary length*. `add_to_list_config` (`config.py:362-390`) appends order-preserving with no cap. This is the running proof N works — it has never known about "3." |

**Where 3 (or 2) is genuinely hardcoded / assumed — the real work list:**

1. **`LIST_VALUED_KEYS` carries bare strings, not typed layer entries** (`config.py:59`). The list is *ordered paths*, with no per-entry `role`, `source`, `auth`, or `rank`. It can *order* N knowledge repos but cannot *distinguish* department-knowledge from org-knowledge. This is the one schema gap that matters (§5).
2. **`cc` config resolution itself is 2-tier + env** (`get_resolved_config`, `config.py:204-259`: env › project › machine › default). That is the *config-file cascade*, orthogonal to the *layer stack* — do NOT try to make department/org/foundation into `cc` config scopes. The layer stack is data the resolver reads; the 2-tier config cascade is where the *manifest pointer* lives. Keep them separate (§5).
3. **Prose/labels bake in "public/company/personal"** across §2–§10 and the extension-spec. Cosmetic but pervasive — the role vocabulary must become open (`personal|department|org|foundation|…`), not a closed 3-set.
4. **The `@machine` sentinel + private-companion assumption is 2-layer** (public tree defers to one untracked machine layer). With 4 layers, "the private layer" is now *three* private layers (personal, department, org) — the sentinel discipline must fan out (§6, secrets risk).

**Verdict: ~85% of §5 is already N-ready.** The resolver algorithm, lockfile, explain view, and precedence rule need *zero* structural change. The genuine deltas are (a) a typed, ranked manifest schema, (b) one `cc` config change to carry per-layer metadata, and (c) resolving *which* department a user belongs to (§3) — a new determination step that has no 3-layer analog.

---

## 2. Manifest schema for N ordered layers

Design goal: **order is an explicit, declared contract** (not YAML-incidental), each layer is self-describing (`id`/`role`/`source`/`auth`), and adding a 5th layer (squad, sub-department) is a data edit with **no schema change**.

```yaml
# copilot.layers.yml  — highest precedence FIRST; rank is the tiebreak of record
version: 1
layers:
  - id: personal-pablo          # stable, unique, machine-key
    role: personal              # open vocabulary — NOT an enum the parser closes
    rank: 10                    # lower = higher precedence (Nix-style); explicit
    source:
      repo: git@github.com:pablitoalejo/claude-copilot-private.git
      ref: main                 # branch | tag | semver-range; pinned in lock
    auth: ssh                   # ssh | token:<env> | anon-https
    activation: always          # always | includeIf:<glob>  (git includeIf model)

  - id: dept-engineering
    role: department
    unit: engineering           # names the DEPARTMENT this layer serves (see §3)
    rank: 20
    source:
      repo: git@github.com:acme/acme-copilot.git
      ref: v3.x
      path: departments/engineering   # subfolder-in-org-repo model (§3, recommended)
    auth: token:ACME_GH_TOKEN
    activation: always

  - id: org-acme
    role: org
    rank: 30
    source:
      repo: git@github.com:acme/acme-copilot.git
      ref: v3.x
      path: org                 # org-wide root inside the SAME repo
    auth: token:ACME_GH_TOKEN
    activation: always

  - id: foundation
    role: foundation
    rank: 40                    # highest number = lowest precedence = the base
    source:
      repo: https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git
      ref: ^5.13.0              # semver range against the public framework
    auth: anon-https
    activation: always
```

**Schema rules that keep it N-extensible:**

- **`rank` is the precedence of record; list order MUST agree with it** (resolver asserts `ranks == sorted(ranks)` at load — a same-rank pair is a hard error, mirroring Nix's error-on-equal-priority). Carrying *both* an explicit `rank` and requiring sorted order gives a self-checking manifest: a human reads top-to-bottom, the machine verifies via `rank`. Leave gaps (10/20/30/40) so a squad slots in at `rank: 15` with **no renumbering**.
- **`role` is an open string**, not a closed enum. `personal|department|org|foundation` are the *known* roles the UX and defaults understand; a `squad` or `region` role parses fine and simply has no special handling. This is what makes 5+ free.
- **`source.path`** lets one repo serve multiple layers (the org+department-in-one-repo model, §3) — the resolver treats `(repo, path)` as the layer root.
- **`unit`** disambiguates *which* department/squad a `department`-role layer is (the selection key in §3).
- **`activation`** carries git-`includeIf` conditional engagement so one machine holds many department layers and engages the right one per context.

No field is arity-bound. A 7-layer stack (personal › squad › department › division › org › partner-consortium › foundation) is the same document with more rows.

---

## 3. The DEPARTMENT-vs-ORG distinction (the hard modeling question)

Department and Org live under the **same enterprise** — same auth domain, same GitHub org, overlapping maintainers. This is the one genuinely new modeling problem 4-tier introduces (3-tier had exactly one private-org layer). Three options:

| Option | Shape | Pro | Con |
|---|---|---|---|
| **(a) Separate repos per layer** | `acme-copilot-org`, `acme-copilot-dept-engineering`, `acme-copilot-dept-finance` | Clean per-dept auth/CODEOWNERS; independent cadence | Repo sprawl (1 + D repos); org+dept version-skew across repo boundaries; cross-repo PR to change a shared convention |
| **(b) One org repo, per-department subfolders** ✅ | `acme-copilot` with `org/` + `departments/<unit>/`; department layer = `(repo, path=departments/<unit>)` | One clone, one auth, one release train for the whole enterprise; org+dept skew impossible (same SHA); trivial "promote dept→org" (move a file up a dir) | Coarser write-access (dir-level CODEOWNERS, not repo-level); all departments see each other's dirs |
| **(c) GitHub-teams-driven selection** | Membership API picks the department dir at resolve time | Zero user config; "org chart is the source of truth" | Non-deterministic offline; network + token dependency in the hot path; two-departments case is ambiguous; violates the framework's local-first/offline stance |

**RECOMMENDATION: (b) — one org repo with per-department subfolders, department selected by an explicit config value.** Rationale:

- **Determinism & offline-first.** The framework is explicitly local-first (`cc docs`, `cc memory` all work headless). Resolution must never depend on a live membership API (rules out (c) as the *mechanism*; it may *seed* the config value once, out-of-band).
- **Kills org↔dept version-skew by construction.** Because org and department layers are the *same repo at the same SHA* (§6), the transitive-pin chain collapses from 4 independent pins to 3. Only foundation and personal are separately versioned against the enterprise repo.
- **Matches the existing seam.** `source.path` already exists in the manifest; a subfolder layer is not new machinery.

**How a user's DEPARTMENT is determined — explicit config, deterministically:**

```bash
cc config set layers.department engineering    # the selection key
```

Resolution reads `layers.department`, substitutes it into any `department`-role layer whose `unit` is templated (`path: departments/${layers.department}`), and materializes. **Determination precedence (reuse the existing env›project›machine cascade):**

1. `CC_LAYERS_DEPARTMENT` env (per-shell / per-worktree override)
2. project `.claude/cc/config.json` (`layers.department`) — a repo can pin its department
3. machine `~/.claude/cc/config.json` — the user's default department

This is the *config-file cascade* (`config.py`) doing what it already does — no new resolution engine. Git identity (`user.email` domain) or a Teams lookup may **seed** this value during `/setup-project`, but the stored config is the contract, never a live lookup.

**A user in two departments** — deterministic by making it *explicit and ordered*, not magic:

- The manifest may carry **multiple `department`-role layers** with distinct `unit` and **distinct `rank`** (e.g. engineering `rank: 20`, platform `rank: 21`). Both materialize; precedence is the declared rank order — a `platform/qa` shadows an `engineering/qa` shadows `org/qa`. There is no ambiguity because rank total-orders them.
- If a user should carry two departments *situationally*, use `activation: includeIf:<glob>` so only the context-matching department engages per project. One machine, many department layers, deterministic per-repo engagement.
- **Never** infer "primary department" from a membership set — that reintroduces non-determinism. Two departments = two ranked, declared layers.

---

## 4. Resolver algorithm changes

**None structural.** The §5.3 walk is already the N-tier algorithm. Stated precisely for 4 tiers:

```
load manifest → layers sorted by rank (assert strictly increasing, else ERROR)
for dimension in {agents, skills, commands, knowledge, mcp}:
    winners = {}                      # name -> (layer, path)
    shadowed = defaultdict(list)
    for layer in layers_low_rank_first:   # personal → department → org → foundation
        for item in layer.items(dimension):
            if item.name in winners:
                shadowed[item.name].append(layer.id)   # already claimed by nearer layer
            else:
                winners[item.name] = (layer.id, item.path)
        assert_no_intra_layer_collision(layer, dimension)   # same-name WITHIN one layer → ERROR
    materialize(winners) into .claude/<dimension>/
    report(shadowed)                  # reported shadowing, never silent
```

- **Iterate in precedence order** (nearest first); **per-name winner** = first layer to claim the name.
- **Whole-unit override** — a nearer layer replaces the *entire* item; no field-merge (the tsconfig/Helm footgun, §prior-art).
- **Reported shadowing** — every shadowed name surfaces in `resolve --explain`; shadowing is a feature, not an error, *when intended* (optional `override: true` suppresses the warning).
- **Hard-error on same-layer collision** — two `qa.md` in one layer is genuine ambiguity → fail.
- **Confirmed unchanged 3→N except the loop bound.** The only new precondition is the `rank` strictly-increasing assertion (arity-independent).

**O(N) concerns: none meaningful.** Complexity is O(L × I) — L layers × I items per dimension. L is tiny (4, maybe 7); I is small (dozens of agents/skills). This is a filesystem scan, dominated by I/O, not by L. Doubling layers from 3→4→7 is imperceptible next to the `git pull` fan-out that precedes it.

**`resolve --explain` for 4 layers:**

```
agents/qa.md      personal-pablo   (shadows dept-engineering › org-acme › foundation)
agents/me.md      foundation       (no shadow)
skills/excel.md   org-acme         (shadows foundation)
agents/tax.md     personal-pablo   (no shadow — personal-only "accountant")
knowledge[]       ACCUMULATE       personal-pablo, dept-engineering, org-acme  (list-typed: no override)
```

Note the last row: **knowledge is list-typed → accumulates across all 4 layers** (git's "multi-valued keys accumulate" rule), while agents/skills/commands are single-valued → override. This override-vs-accumulate split is per-dimension, already present at 3, unchanged at N.

---

## 5. `cc` config changes to support N

**The problem with reusing `paths.knowledge_repo` as-is:** it is an *ordered list of bare path strings* (`LIST_VALUED_KEYS`, `config.py:59`). It already orders N repos correctly — but a bare string cannot say *"this one is the engineering-department knowledge, that one is org-wide."* Ordering ≠ typing. For KNOWLEDGE alone, order is sufficient (the list just accumulates, §4), so `paths.knowledge_repo` needs **no change** — it maps to 4 layers by holding 4 ordered paths.

**But the layer STACK needs per-layer metadata** (role, source-repo, auth, rank) that a flat path list cannot carry. Two candidate schemas:

| Option | Change | Verdict |
|---|---|---|
| **Extend `LIST_VALUED_KEYS` with parallel typed lists** (`paths.knowledge_repo` + `layers.roles` + `layers.auth`, index-aligned) | Minimal code, but positional coupling across 3 lists is fragile — a reorder desyncs role↔path | **Reject** — index-aligned parallel arrays are a known bug farm |
| **New `layers` config key — a list of typed objects** ✅ | One structured key; each element `{id, role, rank, source, auth}` | **Recommend** — self-describing, reorder-safe, is literally the manifest inline |

**RECOMMENDATION — the one schema change that matters: add a `layers` key (list-of-objects), NOT more parallel string lists.**

The manifest (`copilot.layers.yml`, §2) is the *authoring* surface; `cc`'s job is only to know **where the manifest is** and **which department is selected**. So the minimal `cc` config delta is tiny:

```jsonc
// ~/.claude/cc/config.json
{
  "layers": {
    "manifest": "~/.claude/copilot.layers.yml",  // pointer to the ordered stack
    "department": "engineering"                    // §3 selection key
  }
}
```

- `layers.manifest` and `layers.department` are **plain scalars** — they ride the *existing* env›project›machine cascade (`resolve_key`, `config.py:262`) with zero new resolution logic. `CC_LAYERS_DEPARTMENT` / `CC_LAYERS_MANIFEST` env overrides come free from the `CC_<UPPER_DOTTED>` convention.
- `paths.knowledge_repo` **stays** as the list-valued key for the accumulate-dimension; the resolver can *populate* it from the manifest's knowledge dirs, so `cc env` keeps emitting `CC_PATHS_KNOWLEDGE_REPO` unchanged (back-compat preserved).
- **Do NOT** turn department/org/foundation into new `cc` config *scopes*. The config file cascade (env/project/machine) is orthogonal to the layer stack. Conflating them would be the design mistake — keep the stack as *data the resolver reads*, and `cc` config as the *pointer + selection* only.

Net: **one new dotted key namespace (`layers.*`), two scalars, zero change to `LIST_VALUED_KEYS`.** Complexity: Low.

---

## 6. Version-skew across 4 tiers

The pin chain is transitive: **personal pins department, department pins org, org pins foundation.** A personal override written against foundation `^5.13` can break when foundation bumps to `6.x` beneath three layers of pins.

**Transitive-pin risk table:**

| Chain link | Pin example | Skew risk |
|---|---|---|
| org → foundation | `foundation: ^5.13.0` | An org agent extending a foundation agent breaks on foundation major bump |
| department → org | *(collapses — same repo/SHA under model (b))* | **Eliminated by §3(b)** — dept and org share one SHA |
| personal → department | `department: v3.x` | A personal override of a dept skill breaks if the dept restructures |
| personal → foundation (skip-level) | implicit | Personal item written against a foundation agent skips the middle layers — the riskiest link, invisible in a naive 2-deep view |

**How the lockfile handles a 4-deep chain** — `copilot.lock` records the **resolved SHA of every layer**, so the *effective set* is reproducible regardless of how deep the semver ranges nest:

```yaml
# copilot.lock — flat map, arity-independent
resolved:
  personal-pablo:  { repo: …private.git,  sha: a1b2c3d }
  dept-engineering:{ repo: …acme.git,      sha: e4f5a6b, path: departments/engineering }
  org-acme:        { repo: …acme.git,      sha: e4f5a6b, path: org }   # SAME sha as dept — model (b) payoff
  foundation:      { repo: …claude-copilot, sha: 9c8d7e6, ref: v5.13.2 }
```

- **The lock flattens the transitive chain into N independent pins.** There is no *nested* lock — every layer resolves against its own `source.ref` and the lock captures the final SHA. This is exactly Terraform's `.terraform.lock.hcl` / `package-lock.json` model, arity-free.
- **`copilot diff` before `update`** previews what a layer bump changes to the *effective* set ("foundation bumps 5.13→5.14; personal/qa still wins; 1 org skill now shadowed") — Terraform-plan ergonomics, the mitigation for skip-level skew.
- **Per-layer `minVersion`/compatibility field** (already present in `knowledge-manifest.json`) should be **enforced** at resolve: a layer declares `requires: { foundation: ">=5.13" }`; resolve hard-errors if the locked foundation SHA is below it. This is the deterministic guard against silent 4-deep breakage. Complexity: Med (P1).
- **Model (b) is the biggest skew win:** collapsing dept+org to one SHA removes an entire independent pin from the chain, reducing a 4-tier stack to a **3-deep** version graph (personal → enterprise → foundation) even though it presents as 4 layers.

---

## 7. Decision summary (ADR record)

| # | Decision | Complexity | Priority |
|---|---|---|---|
| 1 | Precedence = manifest list ORDER + explicit `rank`; N-tier resolver = 3-tier walk with a larger loop bound | Low | P0 |
| 2 | Manifest `copilot.layers.yml`: `id`/`role`(open)/`rank`/`source{repo,ref,path}`/`auth`/`activation`; 5+ layers = data edit, no schema change | Low | P0 |
| 3 | **Department-vs-org: ONE org repo, per-department subfolders (model b); department chosen by explicit `layers.department` config, seeded-not-looked-up** | Med | P0 |
| 4 | Resolver: iterate-by-rank, per-name winner, whole-unit override, reported shadowing, hard-error intra-layer collision + strictly-increasing-rank assert | Low | P0 |
| 5 | **`cc` config: add `layers.manifest` + `layers.department` scalars; keep `paths.knowledge_repo` list unchanged; do NOT parallel-array the metadata; do NOT make layers into config scopes** | Low | P0 |
| 6 | Lockfile = flat per-layer SHA map (arity-free); enforce per-layer `requires`/minVersion; model (b) collapses the 4-deep chain to 3 | Med | P1 |

**One-paragraph verdict:** N-tier is ~85% already built — the §5 resolver, lockfile, and `--explain` are arity-independent because precedence is list order, not a hardcoded 3. The four real deltas are a typed/ranked manifest, a department *selection* step (new — no 3-layer analog), one `cc` `layers.*` config namespace, and enforced transitive-version guards. Model the enterprise as one repo with org/ + departments/<unit>/ subfolders so org↔dept skew is structurally impossible, and the whole 4-tier stack costs less than the number 4 suggests.
