# External Prior-Art: Layered "Public Base → Company Overlay → Personal Overlay" Config/Extension Models

Research to inform an architecture for the Claude Copilot ecosystem, where a user experiences ONE unified tool while content (agents, skills, commands/workflows, knowledge, integrations) resolves across three git-repo layers: a **PUBLIC** open-source foundation, a **COMPANY** private shared repo, and **PERSONAL** private per-user repos. Layers extend/merge; users add at the right layer; updating = pull latest from each layer.

The recurring question across every prior art below: **do you MERGE layers deterministically at read-time, or MATERIALIZE (copy/symlink) into a single discovery path?** That axis, plus how each system handles precedence, versioning, and conflicts, is what transfers.

---

## Category 1 — Config Cascade / "extends" (closest analog to layered precedence)

### VS Code settings layers — the cleanest mental model for this problem
- **Mechanism:** Ordered scopes, each a plain JSON file: **Default → User → Remote → Workspace → Workspace Folder**. VS Code reads all of them and computes an *effective* value per setting key at runtime.
- **Precedence/merge:** More specific scope wins **per-key** (last-writer-wins on scalar keys). Most settings are scalar-overriding; a few (e.g. `files.associations`) merge as objects. Arrays generally **replace**, not concat.
- **Updates:** Each layer is edited independently; there is no "pull," but the model of "N independent files, one computed effective view" is exactly the read-time-merge pattern.
- **Fit:** ★★★★★ conceptually. Maps directly: public=Default, company=User/Workspace-shared, personal=Folder. The lesson: **keep each layer a standalone valid config, compute the effective set at read time, resolve per-item not per-file.**
- **Con:** Scalar last-writer-wins is only clean when items are atomic. Agents/skills are whole files, so "per-key merge" degenerates to "per-item (whole-file) override" — which is actually simpler and what you want.

### Git config levels — proof that N-layer scalar cascade scales
- **Mechanism:** `system → global → local → worktree`, each a flat INI file. `git config --show-origin` tells you which layer won.
- **Precedence:** Nearest scope wins for single-valued keys; **multi-valued keys accumulate across layers** (e.g. multiple `remote.*` / `include.path`). This is the one mainstream system that does BOTH override AND additive-accumulate depending on key cardinality — a useful precedent: **"same-named thing = override; list-typed thing = accumulate."**
- **Killer feature for you:** `include` / `includeIf` — a config can pull in another file conditionally (e.g. `includeIf "gitdir:~/work/"`). This is a first-class **layer-composition primitive** and a model for "activate the company overlay only in company repos."
- **Fit:** ★★★★★. The `--show-origin` provenance and `includeIf` conditional layering are both directly worth copying.

### ESLint flat config `extends` (2025) — explicit array composition, no directory inheritance
- **Mechanism:** Config is a flat **array** of config objects. `defineConfig()` + a re-introduced `extends` (2025) let a config object pull in named plugin configs / other arrays, which are **spread inline** during a normalization pass. ESLint matches all objects whose `files` glob matches the target and merges them **top→bottom, last wins**. `extends` does NOT trigger file-system inheritance — composition is explicit and in-array. (eslint.org flat-config-extends blog, Mar 2025)
- **Precedence:** Pure array order; later objects override earlier. Author controls precedence by ordering.
- **Fit:** ★★★★. Transferable lesson: **make layer order explicit and linear** (public first, company, personal last) and **normalize/flatten to a single ordered list before resolving.** ESLint deliberately abandoned implicit directory cascade because it was unpredictable — a warning against "magic" merge.

### tsconfig `extends`
- **Mechanism:** `extends` a base file (or an array of them, TS 5.0+); child **shallow-overrides** parent keys. Relative paths in the base re-resolve relative to the base. Arrays replace.
- **Precedence:** Single inheritance chain, child wins. Array form (5.0+) = later entries win, like a mini layer stack.
- **Fit:** ★★★. Simple, well-understood override; but shallow-merge gotchas (child replacing whole objects) are a known footgun — argues for **whole-item override rather than deep field merge.**

### EditorConfig root/override
- **Mechanism:** Walk from file up the directory tree, collecting `.editorconfig` files until `root=true`. Nearer file wins per-property; sections matched by glob.
- **Fit:** ★★. The `root=true` "stop climbing" boundary is a nice primitive (a layer can declare "I am the base, look no further"), but directory-walk discovery doesn't map to separate repos.

**Category 1 takeaway:** The dominant, battle-tested pattern is **read-time cascade with per-item last-writer-wins over an explicitly ordered layer list, plus provenance reporting** (`--show-origin`). Git's `includeIf` (conditional layer activation) and ESLint's "flatten to one ordered array, no directory magic" are the two ideas most worth stealing.

---

## Category 2 — Overlay/Composition Systems

### Kustomize (bases + overlays) — the strongest structural analog
- **Mechanism:** A **base** = complete set of resources; an **overlay** = a kustomization that references one or more bases and applies **patches** (strategic-merge or JSON6902), `namePrefix`, `commonLabels`, `images`, etc. `kustomize build overlay/` **renders** a final flat manifest. Bases can be **remote** (git URL with `?ref=v1.2.3`).
- **Precedence/merge:** Overlay patches deep-merge onto base by resource identity (group/kind/name/namespace). Explicit patch targeting; strategic-merge understands list-merge keys.
- **Updates:** Base pinned by git ref in the `resources:` URL; bump the ref to update. Layers are independently versioned repos, composed at build.
- **Versioning:** Git ref pinning per base — **exactly the multi-repo-per-layer model you want.**
- **Fit:** ★★★★★. Kustomize is arguably the closest existing system to your spec: *pure, declarative, git-ref-pinned base + overlays, rendered (materialized) to a final artifact, no templating.* The "render to a concrete output you can inspect/diff" philosophy is a strong recommendation for materialization.
- **Con:** Patch semantics are heavyweight for whole-file assets like agents/skills. For your case you rarely need *field-level* patching of an agent — you need whole-item override + additive new items, which is simpler than Kustomize patches.

### Helm (charts + values layering)
- **Mechanism:** A chart ships default `values.yaml`; users layer `-f company-values.yaml -f personal-values.yaml` (last wins, deep-merged for maps, **replace for arrays**) plus `--set`. Subchart dependencies pinned by version range in `Chart.yaml`, pulled from repos. `helm template` renders.
- **Precedence:** Right-most `-f` / `--set` wins; documented deterministic order. Arrays replace (a famous footgun).
- **Versioning:** SemVer version ranges on dependencies, pulled from chart repos (OCI or HTTP).
- **Fit:** ★★★★ for the **values-layering** idea (ordered override files) and SemVer-ranged dependencies. The array-replace footgun is the recurring warning: **decide array = replace vs append explicitly and document it.**

### Terraform modules + private module registry
- **Mechanism:** Root module `source = "app.terraform.io/org/vpc/aws"` + `version = "~> 3.0"`. Private registry serves versioned modules; `terraform init` resolves + locks in `.terraform.lock.hcl`.
- **Precedence:** No cascade — composition by explicit reference + variable passing. Child module variables set by caller (override via input vars).
- **Versioning:** SemVer constraints + a **lock file** pinning exact resolved versions (reproducibility). Private registry = your "company layer as a published, versioned artifact" model.
- **Fit:** ★★★★ specifically for **(a) private registry as the company-layer distribution channel and (b) a lock file for reproducible multi-layer pins.** A lock file (`copilot.lock`) capturing the resolved commit/version of each of the 3 layers is a strong recommendation.

### Nix overlays / Home-Manager — the most principled precedence model
- **Mechanism:** Overlays are `final: prev: { ... }` functions that transform a package set; they **compose in order**, each seeing the accumulated result (`prev`) and the fully-resolved fixpoint (`final`). NixOS/Home-Manager modules define options that the module system **merges across all layers**.
- **Precedence:** Explicit **numeric priority**: `mkOptionDefault` (1500) < `mkDefault` (1000) < normal (100) < `mkForce` (50) < `mkOverride n` (arbitrary). **Lower number wins.** Conflicting same-priority definitions = evaluation error (forces you to disambiguate). (NixOS Wiki Overlays; option-def priorities)
- **Fit:** ★★★★ for the **explicit priority-number** idea and the **"conflict at equal priority is an ERROR, not silent last-wins"** stance — the most rigorous conflict-handling precedent found. A layer could declare `override: force` on an agent to intentionally win, vs. accidental collisions surfacing as warnings.
- **Con:** Full Nix semantics (fixpoint, lazy eval) are far too heavy; borrow only the priority-tag + explicit-conflict concepts.

**Category 2 takeaway:** **Kustomize** (git-ref-pinned base+overlay rendered to a concrete artifact) is the best structural fit; **Terraform's lock file + private registry** is the best versioning/distribution fit; **Nix's explicit priority + error-on-ambiguous-conflict** is the best conflict-semantics fit.

---

## Category 3 — Multi-Repo Composition Mechanics (pulling 3 repos into one working tree)

| Approach | How | Update UX | Pros | Cons | Fit |
|---|---|---|---|---|---|
| **git submodule** | Base/overlays as nested repos pinned to a commit SHA in the parent's `.gitmodules` | `git submodule update --remote` per module | True independent history; exact SHA pin; each layer stays its own repo/PR flow | Notorious UX friction; detached HEAD; easy to forget to init/update; two-step commits | ★★★ |
| **git subtree** | Merge external repo's contents into a subdir of the parent | `git subtree pull --prefix=…` | Single clone, no extra tooling for consumers; contents are just files | Squashes/mingles history; parent repo bloats; contributing upstream is awkward | ★★ |
| **vendoring** (git-vendor / git-subrepo) | Copy upstream files in + track the upstream ref in metadata | tool-specific `pull` | Files are plain, present, greppable; metadata records provenance; cleaner than subtree for upstreaming (subrepo) | Manual-ish; drift if not disciplined | ★★★ |
| **"meta" repo tool** (`meta`, `myrepos`/`mr`, `gita`, `vcsh`, Google `repo`, `west`) | A thin orchestrator repo lists N child repos + runs git commands across all of them | one command → `git pull` across all repos | **Each layer stays a fully independent repo/clone with its own history & auth**; one command fans out; no nesting/detached-HEAD pain | Working tree is N sibling clones, not one merged tree — a resolver must overlay them | ★★★★ |

- **`myrepos` (mr)** and **`meta`** are the canonical "run this git command across a registered set of repos" tools; Android's **`repo`** and Zephyr's **`west`** are the industrial-scale versions (a manifest repo lists child repos + pinned revisions). **`west`'s manifest** (`west.yml` listing projects + revisions, `west update` pulls all) is a very clean precedent for "one manifest pins 3 layers; one command updates all."
- **Recommendation for your model:** **Do NOT nest via submodule/subtree.** Keep the 3 layers as **independent clones** managed by a lightweight manifest+fan-out (west/`mr`-style), then have the tool **resolve/overlay** them at read time (or materialize into a discovery dir). This preserves independent versioning, per-repo auth (public vs private), and clean per-layer PR flows, which submodules/subtrees compromise.

**Category 3 takeaway:** A **manifest-driven multi-repo tool (west/`mr` model)** beats submodule/subtree for "public base + private overlays," because the layers have *different visibility and auth* and *different release cadences* — they should not share one history graph.

---

## Category 4 — Package-Distribution-as-Layers (a layer = a versioned published package)

- **npm scoped packages + private registry:** `@company/*` scope routed to a private registry via `.npmrc` (`@company:registry=…`), while unscoped/`@public` resolve to the public registry. Consumers get **one `node_modules`** merged from multiple registries; versions pinned in `package-lock.json`. **The scope acts as the layer namespace and the routing key.** ★★★★★ — this is a very direct precedent: *public agents = unscoped/`@copilot`, company = `@acme`, personal = `@pablo`, all installed into one flat resolution space with a lock file.*
- **Python + uv/pip private index:** `uv`'s `[[tool.uv.index]]` with `explicit = true` pins specific packages to a private index; `--index-url`/`--extra-index-url` layer indexes. `uv.lock` pins resolved versions/hashes. ★★★★ — same shape as npm scopes; uv's *explicit index pinning per-package* avoids the "dependency confusion" attack (a real security note: **namespace/scope must be authoritatively routed, or a public package can shadow a private one**).
- **Ansible collections/roles + Galaxy:** Content is packaged as **collections** (`namespace.collection`, SemVer) pulled from public Galaxy or a private Automation Hub; `requirements.yml` lists sources + versions; `ansible-galaxy install` materializes into a collections path. Precedence by the **collections search path order**. ★★★★ — closest domain analog (agents/roles/playbooks ≈ your agents/skills/commands); the `requirements.yml` + ordered search path is nearly your exact model.

**Category 4 takeaway:** **Namespacing + private registry + lock file** is the mature industry answer to "a layer is a versioned published package." If you ever want stronger reproducibility and decoupling from raw git, publish each layer as a **scoped, SemVer'd package** (npm-scope / Ansible-collection style) with a lock file. Security caveat: **route namespaces authoritatively** (dependency-confusion class of bug).

---

## Category 5 — Plugin/Extension Ecosystems (base + additive plugins)

- **oh-my-zsh + custom/plugins:** Core framework ships default plugins; `$ZSH_CUSTOM` (default `~/.oh-my-zsh/custom`) holds **user overrides that take precedence** — a file in `custom/` shadows the same-named core file. Plugins are additive; enabled via an ordered `plugins=(…)` array (later can override earlier). ★★★★ — clean **"base dir + custom dir that shadows by filename"** precedent = exactly your public-vs-personal override by same-named item.
- **VS Code / Obsidian extensions:** Additive plugin model; each plugin is a versioned package from a marketplace; no merge — plugins register capabilities into a shared registry, conflicts (e.g. two plugins binding a command) resolved by load order / last-registered or explicit user keybinding. ★★★ — mostly additive, weak on override semantics, but the **marketplace + per-plugin version pin** is relevant.
- **Backstage plugins:** Additive plugins wired into an app; **dynamic plugins** (Red Hat/Janus) can be layered in without rebuild. ★★★ (more below under golden paths).
- **chezmoi vs yadm (dotfiles) — best "machine/personal layering" precedent:**
  - **chezmoi:** Single source repo; **filename prefixes encode behavior** and **stack** (`private_`, `readonly_`, `dot_`, `.tmpl`). Go `text/template` renders per-machine differences from one source; `.chezmoiignore` includes/excludes per machine (templated). `chezmoi apply` **materializes** into `$HOME`. Data comes from `.chezmoidata` + per-machine config. ★★★★ — the **template-once-render-per-context + materialize** model, and per-machine include/exclude, transfer well.
  - **yadm:** Git wrapper with **alternate files** (`##os.Linux`, `##hostname`) — the most specific matching suffix wins; template support via plugins. ★★★ — simpler "most-specific-variant-wins" selection, another form of per-item override.
  - Both **materialize to a target dir** rather than read-time-merge — a data point that **file-copy materialization into a discovery path is the norm for tools that must feed an unaware consumer** (the shell, in their case; Claude Code's agent/skill discovery, in yours).

**Category 5 takeaway:** oh-my-zsh's **"custom dir shadows base by filename"** and chezmoi's **"one source, render per context, then materialize"** are the two most directly reusable mechanisms. Both confirm: when the *consumer can't do the merge itself*, you **materialize** the resolved set into the discovery path.

---

## Category 6 — Direct Precedent for "OSS Base + Org Overlay + Individual Overlay"

- **Backstage golden paths / IDP:** The canonical org pattern. Public Backstage core → **company software templates** (`template.yaml` scaffolder recipes encoding the org's "paved road") → per-team/per-user parameters at scaffold time. The **golden-path** concept = an opinionated org overlay on a generic base, with guardrails. ★★★★ — strategically this IS your model at the org layer: *a company encodes its standards as an overlay on an open base, individuals instantiate with personal params.* Borrow the vocabulary ("golden path" = the company overlay's opinionated defaults) and the **template-parameters-as-personal-layer** idea.
- **How large orgs overlay OSS tools generally:** The mature pattern is **fork-and-overlay with an upstream remote** (org maintains a thin overlay repo + tracks upstream, periodically `git pull upstream` / rebases the overlay) OR **config-over-fork** (consume upstream unmodified, layer all org opinions in a separate config/overlay repo so upstream updates stay clean). The strong industry lesson: **never fork-and-diverge; overlay so the base stays independently updatable.** Your 3-repo model is the "config-over-fork" pattern done properly.
- **ESLint shareable configs / Airbnb-style `eslint-config-*`:** A public base config (`eslint-config-airbnb`) → a company `eslint-config-acme` that `extends` it and overrides → a project `.eslintrc`/flat config that extends the company one and overrides further. **This is a real, widespread 3-tier public→org→individual config cascade in production today.** ★★★★★ — a living proof-of-concept of exactly your layering, via published packages + `extends`.
- **Renovate/EAS/Prettier shared configs:** Same three-tier `extends` pattern (`extends: ["config:base", "@acme/renovate-config", "local"]`), each layer a published package, later overrides earlier. ★★★★.

**Category 6 takeaway:** The **shareable-config + `extends` chain** (Airbnb→company→project ESLint/Prettier/Renovate configs) is the closest *production* precedent for public→org→individual, and it's distributed as **versioned packages composed by an ordered extends list** — reinforcing Categories 1 & 4.

---

## SYNTHESIS — Recommendations for the Claude Copilot 3-Layer Model

**Best-fit pattern set (composite, not a single tool):**
1. **Kustomize's philosophy** — declarative base+overlay, git-ref-pinned, rendered to a concrete artifact you can inspect/diff (structural spine).
2. **Git config's cascade + `--show-origin` + `includeIf`** — per-item last-writer-wins over an explicitly ordered layer list, with provenance and conditional activation (resolution semantics).
3. **The shareable-config `extends` chain (ESLint/Prettier/Ansible-collections)** — public→company→personal as an ordered, versioned composition; the proven production precedent for your exact three tiers.
4. **west/`mr` manifest + Terraform lock file** — manifest lists the 3 layer repos + pinned refs; one command fans out `git pull`; a lock file records resolved commits (multi-repo update UX + reproducibility).

### (a) Deterministic MERGE vs file-copy/symlink materialization
**Recommendation: MATERIALIZE the resolved set into the discovery path — do not rely on read-time merge.** Rationale: Claude Code's agent/skill/command **discovery is filesystem-based and layer-unaware** (it scans `.claude/agents/`, `.claude/skills/`, etc.); it cannot itself perform a 3-layer cascade. Every prior-art system whose *consumer is unaware of layers* materializes (chezmoi `apply`, yadm, Kustomize `build`, Helm `template`, Ansible `install`, oh-my-zsh's custom dir on the fpath). Read-time merge (VS Code, git config) only works because those consumers are *themselves* the merge engine.
- Implement a **`copilot sync`/resolve step**: walk layers public→company→personal, compute the winning item per name, and write the resolved set into `.claude/` (the discovery path). Prefer **copy over symlink** for the resolved output (portable, greppable, survives the repos being on different volumes; symlinks break on Windows/containers) — but keep the layer repos as the editable source of truth.
- **Keep it inspectable/diffable** (Kustomize lesson): `copilot resolve --explain` should print, per item, which layer won and which were shadowed (git `--show-origin` model).
- **Whole-item override, not deep field-merge** (tsconfig/Helm footgun lesson): an agent/skill is an atomic unit; a higher layer *replaces* the whole file rather than deep-merging YAML fields. Simpler, predictable, no array-merge surprises. (Offer opt-in field-level extension only where a real need exists, e.g. appending to a knowledge list — mirror git's "list-typed keys accumulate.")

### (b) Keep 3 layers independently versioned yet pullable together
- **Manifest + lock file.** A top-level manifest (`copilot.layers.yml`, west-style) lists the three repos with a pin per layer (branch, tag, or SemVer range). A generated **`copilot.lock`** (Terraform/npm-lock model) records the exact resolved commit SHA of each layer so a machine can reproduce the same resolved set.
- **Do NOT use submodules/subtree** (Category 3): the layers have *different visibility/auth* (public OSS vs private company vs private personal) and *different release cadences*; nesting them into one history graph fights all three. Keep independent clones; orchestrate with a fan-out.
- **Independent SemVer per layer** (you already do this per-component in `VERSION.json`): public layer publishes releases; company pins "public ^5.x"; personal pins "company ^2.x". Optional future: publish each layer as a **scoped package** (npm-scope / Ansible-collection style) for stronger reproducibility than raw git refs.

### (c) Conflict handling when two layers define the same-named agent/skill
- **Default: higher layer wins silently by precedence** (personal > company > public), matching every cascade system — BUT **surface it** (git `--show-origin`): the resolve step reports "personal/agents/qa.md shadows company/agents/qa.md shadows public/agents/qa.md." Shadowing is a feature, not an error, *when intended*.
- **Borrow Nix's explicit-priority + error-on-ambiguity for the dangerous case:** if two items collide at the **same layer** (or a manifest flags an item `pin: exact`), that's a genuine ambiguity → **error, don't silently pick.** Optionally let an item declare intent: `override: true` (I mean to shadow the base — no warning) vs. an accidental same-name collision (warn). This gives you Nix's rigor without Nix's machinery.
- **Namespace to avoid accidental collisions** (npm-scope / dependency-confusion lesson): consider optional layer prefixes/scopes (`acme/qa`, `pablo/qa`) so authors *can* run a company `qa` alongside the public `qa` when they don't intend to override — and so routing is authoritative (prevents a public item silently shadowing a private one, the dependency-confusion class of bug).

### (d) Pull/update UX ("pull latest from public + company + personal")
- **One command, fan-out, then re-resolve** (west/`mr` + chezmoi model):
  - `copilot update` → for each layer in the manifest: `git pull` (respecting the pin), then **automatically re-run resolve/materialize** into `.claude/`, then print a **provenance diff** ("company/qa.md updated; personal override still wins; 2 new public skills added").
  - `copilot update --layer public` to pull one layer; `copilot resolve --explain` to see the effective set + shadowing; `copilot lock` to freeze current SHAs; `copilot diff` to preview what an update would change before applying (Kustomize/Terraform-plan ergonomics).
  - Handle the **auth split** transparently (public = anon HTTPS; company/personal = SSH/token) — a manifest per-layer `auth` hint, since this is the practical friction submodules famously mishandle.
- **Conditional activation** (git `includeIf`): allow a layer/item to activate only in matching contexts (e.g. company overlay auto-activates inside company repos), so a personal machine can carry company + personal layers and have the right one engage per project.

### One-paragraph architecture recommendation
Model it as **git-config-style precedence resolved by a Kustomize-style build step, distributed via a west-style manifest+lock, with an ESLint-shareable-config extends chain as the proven production precedent.** Concretely: a manifest pins three independently-versioned, independently-authed layer repos; `copilot update` fans out `git pull` and regenerates a lock; a `resolve` step materializes (copies) the per-item winner (personal > company > public, whole-file override) into Claude Code's filesystem discovery paths; conflicts are silent-but-reported when intended and hard-errors when ambiguous; `--explain`/`diff` give Kustomize/Terraform-plan-grade inspectability. Avoid submodules/subtree and avoid read-time merge — the discovery consumer is layer-unaware, so materialize.

---

## Sources
- ESLint flat-config `extends` (Mar 2025): https://eslint.org/blog/2025/03/flat-config-extends-define-config-global-ignores/ ; flat config intro: https://eslint.org/blog/2022/08/new-config-system-part-2/ ; config files ref: https://eslint.org/docs/latest/use/configure/configuration-files
- Git multi-repo tradeoffs: https://www.atlassian.com/git/tutorials/git-subtree ; https://www.geeksforgeeks.org/git/git-subtree-vs-git-submodule/ ; git-vendor: https://github.com/thejoshwolfe/git-vendor
- Backstage golden paths / software templates: https://medium.com/@rameshavutu/how-to-build-golden-paths-in-backstage-idp-with-software-templates-170adce436fe ; https://www.redhat.com/en/blog/designing-golden-paths ; https://backstage.spotify.com/learn/onboarding-software-to-backstage/setting-up-software-templates/11-spotify-templates/
- chezmoi vs yadm: https://www.chezmoi.io/comparison-table/ ; https://www.chezmoi.io/why-use-chezmoi/
- Nix overlays + module priority (mkDefault/mkForce/mkOverride): https://nixos.wiki/wiki/Overlays ; https://nixos-and-flakes.thiscute.world/nixpkgs/overlays ; option priorities: https://nlewo.github.io/nixos-manual-sphinx/development/option-def.xml.html
- (From domain knowledge) Kustomize bases/overlays; Helm values layering; Terraform private module registry + lock file; npm scoped packages + private registry; uv index pinning; Ansible collections/requirements.yml + Galaxy; VS Code settings scopes; git config levels + includeIf; oh-my-zsh $ZSH_CUSTOM; west manifest; myrepos/mr.
