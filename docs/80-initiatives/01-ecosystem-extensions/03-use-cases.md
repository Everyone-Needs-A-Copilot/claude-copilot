# Four-Tier Model — Common Use Cases

| | |
|---|---|
| **Status** | Research / Illustrative (extends [`02-four-tier-and-github-topology.md`](02-four-tier-and-github-topology.md)) |
| **Branch** | `ecosystem-extensions` |
| **Date** | 2026-07-06 |
| **Purpose** | Show how real people use the **PERSONAL › DEPARTMENT › ORG › FOUNDATION** model day to day — who authors where, what commands they run, and what resolves. |

> **Note on commands.** The `copilot update` / `copilot resolve --explain` / `copilot promote` / `cc config set layers.*` verbs below are the **proposed** UX from the architecture docs, not all shipped yet. Today only knowledge layering resolves deterministically (via `cc`'s `paths.knowledge_repo`). These scenarios describe the target experience the roadmap builds toward.

---

## Cast (a running example)

- **Jane** — a developer in the **Engineering** department at **acme-corp** (an enterprise). She has all four tiers.
- **Raj** — acme-corp's **platform lead**; he authors the **org** layer everyone inherits.
- **Mira** — a **Finance** department lead at acme-corp; she authors the **Finance department** layer.
- **Pablo** — an **ENAC maintainer**; he authors the **foundation** and runs promotions.
- **Sam** — an **independent** solo user with no company; just **personal + foundation**.

Jane's resolved stack (nearest wins): `personal-jane › dept-engineering › org-acme › foundation`.

---

## Where does X go? (the 5-second decision)

| I want a … | that should reach … | Author at layer | Everyone below inherits by |
|---|---|---|---|
| personal "accountant" agent | only me | **PERSONAL** | (nobody else — personal is top) |
| tax-calc skill | only Finance | **DEPARTMENT** (Finance) | Finance members pulling |
| "Excel-to-JSON" skill | the whole company | **ORG** | every acme-corp dev pulling |
| an industrial-designer protocol step | every Copilot user on earth | **FOUNDATION** | anyone running `copilot update` |

**Rule of thumb:** author at the *narrowest* layer that covers your audience. Promote upward later if it proves broadly useful (§ Use Case 8).

---

## A. Consuming — the everyday majority

### Use Case 1 — New employee onboarding (wire three tiers in one command)

**Persona:** Jane, day one at acme-corp.
**Goal:** get the company's agents, skills, commands, and knowledge without hand-assembling anything.

```bash
# IT provides one bootstrap; Jane runs it once.
./acme-onboard.sh
#   → verifies her enterprise SSH key (Host github-work)
#   → asks/confirms her department: "engineering" → cc config set layers.department engineering
#   → clones org + dept-engineering + foundation into ~/.copilot/layers/
#   → writes copilot.layers.yml (foundation < org < dept)
#   → runs `copilot update` to materialize into .claude/

# Optional: add her PERSONAL layer (highest precedence)
git clone git@github-personal:jane/claude-copilot-private.git ~/.copilot/layers/personal
cc config add paths.layer "$HOME/.copilot/layers/personal:ssh-personal"
copilot update
```

**Result:** Jane's `.claude/` now contains the merged set — foundation agents, org-wide skills, Engineering-specific skills, and (if added) her personal overrides — all from one command. She never manually copied a file.

---

### Use Case 2 — Daily "pull latest everywhere" (`copilot update`)

**Persona:** Jane, any morning.
**Goal:** stay current as the foundation, org, and her department evolve independently.

```bash
copilot update
```

```
Pulling 4 layers…
  personal-jane      ✓ up to date
  dept-engineering   ✓ 2 commits   (+1 skill: k8s-debug)
  org-acme           ✓ 5 commits   (~ excel-to-json updated)
  foundation         ✓ 1 tag       (v5.13.2 → v5.14.0: +industrial-designer protocol step)

Re-materializing .claude/ …
  agents/qa.md       personal-jane   (still shadows org-acme › foundation)
  skills/excel.md    org-acme        (updated; shadows foundation)
  skills/k8s-debug   dept-engineering (NEW)
  protocol chain     foundation       (NEW stage: industrial-designer)

3 new, 1 updated, 0 conflicts. Lockfile updated.
```

**Result:** one fan-out pulls every layer with the correct credential per URL (personal key, work key, anon), re-materializes `.claude/`, and prints a **provenance diff** so Jane sees exactly what changed and which layer won. Her personal `qa` override survives the org/foundation updates.

---

### Use Case 3 — "Why is this agent behaving this way?" (`resolve --explain`)

**Persona:** Jane, debugging surprising behavior from the `qa` agent.
**Goal:** see which layer's version is active and what it shadows.

```bash
copilot resolve --explain agents/qa.md
```

```
agents/qa.md
  WINNER   personal-jane   (~/.copilot/layers/personal/agents/qa.md @ a1b2c3d, signed ✓)
  shadows  dept-engineering   (had no qa.md)
  shadows  org-acme           (agents/qa.md @ e4f5a6b)
  shadows  foundation         (agents/qa.md @ 9c8d7e6)
```

**Result:** the git-`--show-origin`-style trace answers "what's active and why" offline. Jane realizes *she* overrode `qa` months ago; she deletes her personal copy and re-runs `copilot update` to fall back to the org version.

---

## B. Authoring at each layer

### Use Case 4 — Personal-only agent (the "accountant") — PERSONAL layer

**Persona:** Sam, an independent user (personal + foundation only).
**Goal:** a personal accounting agent nobody else should ever get.

```bash
cd ~/.copilot/layers/personal
mkdir -p agents
$EDITOR agents/accountant.md      # name: accountant, owner: personal
git commit -am "add personal accountant agent" && git push
copilot update                     # materializes accountant into .claude/agents/
```

**Result:** `@agent-accountant` is available in Sam's sessions. Because it lives in his private personal repo at the top of the stack, it is invisible to everyone else and overrides nothing (no lower layer has an `accountant`).

---

### Use Case 5 — Department-only skill (Finance tax-calc) — DEPARTMENT layer

**Persona:** Mira, Finance lead.
**Goal:** a `tax-calc` skill every Finance analyst gets, but Engineering does not.

```bash
cd ~/.copilot/layers/dept-finance        # acme-corp/copilot-dept-finance — a separate, team-scoped repo (default; confidential dept content)
$EDITOR skills/tax-calc/SKILL.md
git commit -am "add tax-calc skill" && git push
```

Any Finance member (`layers.department = finance`) runs `copilot update` and inherits `tax-calc`. Jane in Engineering does **not** — her manifest resolves `dept-engineering`, which has no `tax-calc`, and the org/foundation layers don't either.

**Result:** department scoping is automatic — audience is defined by *which department layer a user resolves*, set once via `cc config set layers.department`.

---

### Use Case 6 — Company-wide skill (Excel-to-JSON) — ORG layer

**Persona:** Raj, platform lead.
**Goal:** the owner's canonical example — an `excel-to-json` skill *everyone* at acme-corp inherits.

```bash
cd ~/.copilot/layers/org-acme            # acme-corp/copilot-org
$EDITOR skills/excel-to-json/SKILL.md
git commit -am "add excel-to-json skill, company-wide" && git push
```

**Result:** on their next `copilot update`, **every** acme-corp dev — every department — inherits `excel-to-json`, because the org layer sits below all departments and above only the foundation. Raj published once; the whole company pulled it. A department may still *shadow* it with its own version (Use Case 7); a personal layer may shadow it further.

---

### Use Case 7 — Foundation change (industrial-designer protocol step) — FOUNDATION layer

**Persona:** Pablo, ENAC maintainer.
**Goal:** the owner's third example — add an industrial-designer stage to the protocol chain so *every Copilot user on earth* gets it.

Because the foundation is public and PR-gated, Pablo doesn't push directly — he authors in ENAC's private staging layer and **promotes** (Use Case 9). The end state: the public `foundation` ships a new protocol stage; on the next `copilot update`, Jane, Sam, and every other user worldwide see the industrial-designer step appear in their protocol chain (as in Use Case 2's diff).

**Result:** a single foundation change fans out globally through the one mechanism everyone already runs — `copilot update`.

---

## C. Overrides, promotion & governance

### Use Case 8 — Overriding a lower layer (reported shadowing)

**Persona:** Jane wants a stricter `qa` than the org ships.
**Goal:** replace the org `qa` agent for herself only, without forking anything.

```bash
cd ~/.copilot/layers/personal
cp ~/.copilot/layers/org-acme/agents/qa.md agents/qa.md
$EDITOR agents/qa.md               # tighten it; optionally add `override: true`
git commit -am "personal stricter qa" && git push
copilot update
```

```
agents/qa.md   personal-jane   (shadows org-acme › foundation)   [override: true — no warning]
```

**Result:** whole-unit override — Jane's `qa` wins for her; everyone else still gets the org's. The shadow is **reported, not silent**. Adding `override: true` marks it intentional (suppresses the "you're shadowing" warning); omitting it still works but warns, so *accidental* same-name collisions get flagged.

---

### Use Case 9 — Promotion: content graduates upward

Two flavors of the same idea — a capability proves useful to a wider audience and moves up a layer.

**9a — Department → Org (internal promotion).** Mira's Finance `tax-calc` skill turns out useful company-wide. Because department repos are separate by default, promotion is a **cross-repo `copilot promote --to org`**: Raj reviews it, and the tool cherry-picks the flagged commit from `copilot-dept-finance` into `copilot-org`, preserving author and signature. Now every department inherits it; Finance deletes its now-redundant copy (or lets the identical org version shadow-match harmlessly). *(Narrow exception: under an explicit `subfolder`-topology opt-in for non-confidential departmental content, promotion collapses to a plain `git mv departments/finance/skills/tax-calc org/skills/` within the one repo — but this is the exception, not the headline path.)*

**9b — ENAC Org → Foundation (public promotion, `copilot promote`).** Pablo's industrial-designer step (authored in ENAC's private staging) is generic and world-safe:

```bash
copilot promote --to foundation           # flagged commits carry `Promote-To: foundation`
#   → cherry-picks flagged commits (author + signature preserved)
#   → HARD-FAIL leak scan (client names, .env, tokens, mcp secrets) — nothing private leaks
#   → opens a PR into public foundation:main
#   → runs existing CodeQL + required review + signed-commit checks
#   → GitHub Environment approval gates the merge
```

**Result:** promotion is a deliberate, one-way, governed egress. Never-public content stays private (default); only flagged, scanned, reviewed content reaches the world. Ingress back to ENAC is just the ordinary `copilot update`.

---

### Use Case 10 — A user in two departments

**Persona:** Priya, who works across **Engineering** and **Platform**.
**Goal:** get both departments' content, deterministically.

Her manifest declares **two** department-role layers with distinct rank:

```yaml
  - id: dept-platform     { role: department, unit: platform,    rank: 20 }
  - id: dept-engineering  { role: department, unit: engineering, rank: 21 }
```

**Result:** both materialize; `platform/*` shadows `engineering/*` shadows `org/*` — total-ordered by rank, no ambiguity. If Platform content should engage *only* inside platform repos, she adds `activation: includeIf:~/work/platform/**` so it engages per project context. There is no "guess the primary department" magic — two departments = two declared, ranked layers.

---

### Use Case 11 — Governance blocks a risky override (capability policy)

**Persona:** acme-corp security team.
**Goal:** ensure no department can silently replace the security agent or inject MCP servers.

The org ships a capability policy:

```yaml
layers:
  department:
    may_add:      [skills, knowledge, commands]
    may_override: []                    # departments may ADD, not override agents
    may_never:    [agents/sec.md, mcp]  # the security agent + MCP decls are off-limits
```

If the Finance department repo ships an `agents/sec.md` or an `mcp` entry, `copilot update` **drops it and reports it** at materialize time:

```
POLICY  dept-finance/agents/sec.md  DENIED (department.may_never) — not materialized
```

**Result:** blast radius is bounded even if a department repo is compromised — the resolver enforces *what a layer is permitted to contribute*, independent of what it pushes. This is the single highest-leverage governance control.

---

### Use Case 12 — Pin, preview, and roll back (version safety)

**Persona:** Jane, cautious before a big foundation bump.
**Goal:** see what an update would change before applying it, and freeze if needed.

```bash
copilot diff                       # preview: "foundation v5.14→6.0; personal/qa still wins; 2 org skills now shadowed"
copilot lock                       # freeze current resolved SHAs across all 4 layers
# … later, if a bump broke something …
copilot update --layer foundation --to v5.14.0   # pin one layer back; re-materialize
```

**Result:** the flat per-layer lockfile (`copilot.lock`) makes the effective set reproducible on any machine; `copilot diff` gives Terraform-plan-style foresight; a bad layer bump is a one-line pin-and-rematerialize, not a crisis. Per-layer `requires:` (minVersion) hard-errors if a personal override needs a newer foundation than is pinned.

---

## Summary — the shape of daily use

| Frequency | Who | Action | Command |
|---|---|---|---|
| **Daily** | everyone | pull all layers, re-materialize | `copilot update` |
| **Often** | anyone debugging | see what's active & why | `copilot resolve --explain <item>` |
| **Weekly** | authors | create/edit at their layer, push | git + `copilot update` |
| **Occasional** | power users | override a lower layer for themselves | edit personal layer + `override: true` |
| **Occasional** | leads/maintainers | promote content upward | `git mv` (dept→org) / `copilot promote` (org→foundation) |
| **Rare** | cautious users | preview / pin / roll back | `copilot diff` / `copilot lock` / `--to <ref>` |

**The whole model reduces to one everyday verb (`copilot update`) plus author-at-the-right-layer.** Consumers run one command; authors push to the narrowest layer that covers their audience; promotion moves proven content upward through governed, one-way valves. The four tiers are invisible in daily use — they only surface when someone asks "why?" (`resolve --explain`) or crosses a governance boundary (capability policy).
