# Foundation Governance — ENAC Owns The Foundation

| | |
|---|---|
| **Status** | Research / Proposed |
| **Branch** | `ecosystem-extensions` |
| **Question** | How does ENAC (the foundation owner) author and publish foundation-level changes while ALSO being an enterprise with its own org/department/personal layers? |
| **Parent** | `docs/40-initiatives/01-ecosystem-extensions/00-findings-and-recommendations.md` (§9 #7 #9, §7) |
| **Framing under test** | "The FOUNDATION is simply ENAC's ORG layer, published publicly." |

---

## 0. TL;DR

**Do not add a 5th layer type.** The 4-tier model (PERSONAL > DEPARTMENT > ORG > FOUNDATION) is complete as a *resolution* model. ENAC's authoring need is a **repo-topology + release-pipeline** concern, not a new resolution tier. Concretely: ENAC keeps a **private ORG layer that sits ABOVE the public FOUNDATION** (stack for ENAC staff = `personal > department > enac-org-private > FOUNDATION(public)`), and runs a **one-directional promotion pipeline** that pushes *vetted, generic* content DOWN from the private ENAC org layer into the public foundation repo. The "5th layer" the user senses is real but it is not a new *kind* of layer — it is ENAC's ordinary ORG layer, which every enterprise has. What is special about ENAC is only that its FOUNDATION output is world-readable and that it owns the promotion valve. This is the **open-core / upstream-first pattern applied to config**, and it is well-precedented.

---

## 1. The authoring model for ENAC-owns-foundation

### 1.1 The framing holds — with one inversion

"Foundation = ENAC's published org layer" is *directionally* right but geometrically inverted if taken literally. The foundation is not ENAC's org layer; it is the **published floor** that ENAC's private org layer sits **on top of**. The distinction matters because it dictates promotion direction:

- If foundation *were* ENAC's org layer, ENAC would have nowhere private to stage — everything ENAC's org authors would be public by construction. That breaks the "ENAC-internal content that must NEVER go public" requirement.
- Instead, ENAC has a **private ENAC-org repo above the public foundation**, exactly like any enterprise. The difference: ENAC's org repo has a **downhill valve** into foundation that no other enterprise's org repo has.

So ENAC's resolution stack at runtime is a normal 4-layer stack — `personal > department > enac-org-private > FOUNDATION`. ENAC content lives in `enac-org-private` and is one of three fates:

| Fate | Lives in | Ever public? |
|---|---|---|
| **Never-public** (client names, internal ops agents, ENAC business knowledge) | `enac-org-private` permanently | No |
| **Not-yet-public** (staging a foundation change before it is vetted/generic) | `enac-org-private` temporarily | After promotion |
| **Generic/vetted** (the industrial-designer protocol step; a broadly-useful skill) | Promoted DOWN to `FOUNDATION` | Yes |

### 1.2 Where the framing breaks — and why that is fine

The framing breaks precisely at the never-public bucket, and that break is the *feature*. Because `enac-org-private` sits ABOVE foundation in precedence, ENAC can shadow or extend its own public foundation for internal use (e.g. an ENAC-flavored `qa` agent) without that ever touching the public tree — identical to how any enterprise shadows the foundation. The resolver already gives this for free (personal > company > public whole-unit override, per parent doc §5.3). **No new mechanism is needed for ENAC to be an enterprise-on-top-of-its-own-foundation.** The only net-new machinery is the promotion valve (§2).

### 1.3 Recommendation

**Model = promotion pipeline, NOT a 5th staging layer.** Reject a distinct "staging tier" in the resolution model:

1. It would pollute the clean 4-tier precedence semantics every consumer relies on.
2. Staging is a *repo state* (a branch / a not-yet-promoted directory), not a *resolution rank*. Encoding it as a rank means every other enterprise would carry a dead tier.
3. The `@machine` sentinel discipline (parent §3.2) already keeps the public tree clean while a private layer overlays it — ENAC uses the identical mechanism, just with an extra egress step.

ENAC-org-private **is** the staging area. Promotion is a pipeline event, not a layer.

---

## 2. The promotion / release pipeline (private ENAC-org → public FOUNDATION)

### 2.1 Prior art surveyed

- **GitHub Private Mirrors App** (`github-community-projects/private-mirrors`): develop contributions in a *private mirror* of a public repo, preserving commit history, authorship, signing, and metadata, then push vetted commits public. This is the closest turnkey precedent for "private ahead of public, promote when ready."
- **Salesforce internal-copies model**: maintain an internal copy carrying a *minimal patch set* over upstream; contribute patches upstream, accept lag before they land in a public release.
- **Upstream-first policy** (LWN): a change must land upstream (public) *before* it ships downstream (private) — the disciplined inverse that prevents permanent private divergence.
- **Open-core anti-pattern** (Wikipedia / Linux Journal): the perverse incentive where the private edition races ahead and the public core starves. **ENAC must explicitly guard against this** — the promotion pipeline needs a policy that generic improvements default to promotion, not hoarding.
- **GitLab push/pull mirroring** and **git subtree vs. cherry-pick**: subtree is for whole-repo incorporation; cherry-pick is for selective commit promotion — the right primitive here since only *some* commits are generic.

### 2.2 The recommended flow: PR-promotion via a `copilot promote` verb over cherry-pick

Respecting this repo's hard constraints (PR-only, signed commits, CodeQL, branch protection — CLAUDE.md), a raw mirror-push is disallowed: it would bypass the PR gate on `main`. Therefore promotion must **land as a normal PR** into the public foundation. Recommended pipeline:

1. **Author in `enac-org-private`** on a normal branch, signed commits. Content is exercised by ENAC's own daily use (§5).
2. **Mark for promotion.** A commit/PR trailer `Promote-To: foundation` (or a `promote/` path convention) flags generic, world-safe content. Absence = stays private forever (never-public default is safe).
3. **`copilot promote` command** — thin wrapper that:
   - Cherry-picks the flagged commits (author + signature preserved, private-mirrors-style) onto a fresh branch in a *checkout of the public foundation repo*.
   - Runs a **leak scan** (deny-list: client names, `.env`, tokens, `mcp.json` secrets, internal knowledge globs) and **hard-fails** if any never-public marker or secret pattern is present. This is the single most important safety in the valve.
   - Opens a **PR into public `foundation:main`** — which then runs the *existing* CodeQL + required-review + signed-commit branch protection. No special path around governance.
4. **Public review + merge** under foundation CODEOWNERS. The promoted change is now world-readable; ENAC pulls it back as the foundation floor on next `copilot update`, and the temporary copy in `enac-org-private` is retired (or left to be shadowed harmlessly by the now-identical foundation item).

**Why cherry-pick-into-PR, not mirror/subtree/direct-push:**

- **Selective** — only flagged commits cross the boundary; never-public content is structurally excluded, not merely filtered.
- **Governance-preserving** — it lands as a PR, so CodeQL, required reviews, and signed-commit enforcement apply unchanged. A subtree/mirror push would either bypass branch protection or fight it.
- **Provenance-preserving** — private-mirrors demonstrates author/signature/metadata survive the cherry-pick, so the public history stays honest.
- **Reversible** — a bad promotion is a revert PR, not a history rewrite.

**Egress direction is strictly one-way (private → public).** Ingress (public foundation updates → ENAC) is just the normal `copilot update` pull every enterprise runs. Never wire an automatic public→private→public loop; that reintroduces the open-core starvation risk.

---

## 3. Governance & trust boundaries across all 4 tiers

The threat: `copilot update` **auto-pulls and MATERIALIZES executable-adjacent content** (agents, skills, MCP server declarations, commands) from ORG and DEPARTMENT private repos into a user's `.claude/`. A malicious or compromised department push becomes code the user's agent runs. Governance must make each layer's push path as trustworthy as the blast radius demands. Map of GitHub primitives to layer:

| Layer | Who may push | Review requirement | Signing / provenance | GitHub primitives |
|---|---|---|---|---|
| **FOUNDATION (public)** | ENAC maintainers only (via promotion PR) | Required review by foundation CODEOWNERS; CodeQL required check | **Signed commits enforced** (already true); tagged releases signed | Public repo, branch protection on `main`, ruleset "required reviewer" for `agents/**` `skills/**`, CodeQL |
| **ENAC-ORG-PRIVATE / any ORG** | Org platform team | Required review (≥1, ≥2 for agent/skill/mcp paths) | Signed commits enforced; org SSO/SAML gate | Private org repo, org SSO enforcement, branch protection, **CODEOWNERS per dimension** |
| **DEPARTMENT** | Department leads + members | Required review by department CODEOWNERS; **cannot self-approve executable dimensions** | Signed commits; provenance attestation on skills/agents | Private repo (or org repo subtree with path-scoped CODEOWNERS + required-reviewer ruleset) |
| **PERSONAL** | The single user | None (self-owned) | Optional signing | Private personal repo; trust = "you are trusting yourself" |

### 3.1 Per-layer specifics

- **CODEOWNERS per dimension, not per repo.** GitHub's **required-reviewer ruleset** (GA Feb 2026) lets a repo require that changes to `skills/**` get a security-team review and `agents/sec.md` get two reviews. Apply this at org and department layers so the *executable-adjacent* paths carry heavier review than knowledge/docs paths in the same repo.
- **Signed commits as the trust anchor at every non-personal layer.** The foundation already enforces this; extend the same enforcement to org and department repos so the resolver can, in principle, verify that every materialized item traces to a signed commit by an authorized identity.
- **Org SSO/SAML** gates *who can even be* a pusher to org/department repos — the identity floor beneath CODEOWNERS.
- **"You trust a department layer" answer:** trust is transitive through (a) org SSO membership proving the pusher is a real employee, (b) required review by a department CODEOWNER (no solo malicious push), (c) signed commits proving authorship, and (d) the resolver's allow/deny policy (§4) capping what a department is *permitted* to contribute regardless of what it pushes. No single compromised account can ship an executable to users.
- **GitHub Environments** gate the promotion pipeline (§2): the `copilot promote`→public PR job runs in a protected Environment requiring a manual approver, so promotion to the world is a deliberate, logged, human-gated event.

---

## 4. Supply-chain integrity of the materialized set

Because the resolver **copies executable-adjacent content across 4 layers into `.claude/`**, treat the resolved set as a build artifact and apply SLSA-style controls (Sigstore: cosign signing, Fulcio keyless OIDC identity, Rekor transparency log; verify-before-materialize).

Concrete controls, in priority order:

1. **SHA-pinned lockfile per layer** (`copilot.lock`, already proposed parent §5.2). Records the exact resolved commit SHA of each of the 4 layers. Reproducible, and the anchor everything else verifies against.
2. **Signature verification before materialize.** `copilot update` verifies each pulled layer's tip commit/tag is **signed by an allowed key** (foundation = ENAC release key; org/dept = keys in an org-managed allow-list) before copying anything into `.claude/`. Unsigned or unknown-signer layer → refuse to materialize, don't silently proceed. This is the SLSA "reject artifacts that fail provenance policy" pattern applied to config.
3. **Per-layer capability allow/deny policy** — the highest-leverage new control. A machine/org policy file declares **which layers may contribute which dimension**, e.g.:
   ```yaml
   layers:
     department:
       may_add: [skills, knowledge, commands]
       may_override: []          # dept may ADD skills but NOT override any agent
       may_never: [agents/sec.md, mcp]   # security agent + MCP decls are off-limits
   ```
   This directly answers "department may add skills but NOT override the security agent." The resolver enforces it at materialize time: a department item targeting a denied dimension/name is dropped and reported, not applied. Prevents a lower-trust layer from silently shadowing a security-critical unit.
4. **`resolve --explain` / audit trail** (parent §5.3, git `--show-origin` model). Per materialized item: winning layer, shadowed layers, source SHA, signer identity, and any policy denials applied. Persist a `copilot.audit.json` alongside the lockfile so "what executable content is in my `.claude/` and where did each piece come from" is answerable offline. Pair with `resolve --check` (drift detection, mirroring `cc memory check`) so a hand-edited materialized file is flagged.
5. **Secret-egress guard on the promotion valve** (§2.3 leak scan) — the inverse control: nothing secret leaves private layers into the public foundation. Deny-list + hard-fail in `copilot promote`.

Net: **lockfile (integrity) + signature verify (authenticity) + capability policy (authorization) + audit (transparency)** are the four controls. If only one ships first, ship the **capability allow/deny policy** — it is the control that bounds blast radius even when a layer is compromised.

---

## 5. The dogfooding validation loop

ENAC runs the exact 4-tier system it ships, so **ENAC's own daily usage is the integration test** for the resolver, the promotion pipeline, and the governance controls:

- Every ENAC engineer resolves `personal > department > enac-org-private > FOUNDATION` every day. A resolver regression, a bad shadow, a broken lockfile, or a mis-scoped capability policy surfaces in ENAC's own sessions **before** any external enterprise hits it. ENAC is structurally its own canary.
- The **`enac-org-private → FOUNDATION` promotion is exercised continuously** — every generic improvement ENAC makes travels the full valve (flag → cherry-pick → leak-scan → public PR → CodeQL → merge → pull-back). That path is the *reference implementation* other enterprises copy for their own internal promotions (dept→org), so ENAC cannot ship a promotion pipeline it hasn't itself run end-to-end.
- **Never-public content is the negative test.** ENAC necessarily has content that must never promote (client work, internal agents). If the leak-scan/deny-list ever lets an ENAC-internal item into the public foundation, that is caught by ENAC first and hardest — aligning incentive with correctness.
- **Guard the open-core starvation trap** (§2.1): because ENAC eats its own dogfood, an under-fed public foundation degrades ENAC's *own* floor, not just outsiders' — a structural incentive to keep promotion flowing rather than hoard improvements privately. Make "generic → promote" the reviewed default, and treat a growing never-promoted delta in `enac-org-private` as a governance smell to review, not a moat to defend.

**Consequence for the roadmap:** the promotion pipeline and the 4-tier resolver should be built and validated *inside ENAC's own repos first* (`claude-copilot` public = FOUNDATION, a new private ENAC-org repo above it, reusing the existing `claude-copilot-private` as the personal-layer fixture from parent §3.3). Ship externally only after ENAC has round-tripped real promotions through it.

---

## 6. Decisions to ratify

1. **No 5th resolution tier.** ENAC-org-private is a normal ORG layer with a promotion valve; staging is repo-state, not a rank.
2. **Promotion = `copilot promote` → cherry-pick → leak-scan → PR into public foundation.** One-way egress; ingress is ordinary `copilot update`. No mirror/subtree/direct-push (would bypass branch protection).
3. **Signed commits + CODEOWNERS-per-dimension + required-reviewer rulesets** at every non-personal layer; executable-adjacent paths (`agents/**`, `skills/**`, `mcp`) carry heavier review than knowledge/docs.
4. **Four supply-chain controls:** SHA lockfile, signature-verify-before-materialize, per-layer capability allow/deny policy, `resolve --explain` audit. If sequencing, capability policy first.
5. **GitHub Environments gate the public promotion job** — human-approved, logged egress.
6. **Dogfood-first:** validate the whole loop inside ENAC's own repos before external release.

---

## Sources

- [GitHub Private Mirrors App](https://github.com/github-community-projects/private-mirrors) — private mirror of public repo, promote preserving history/signing/metadata
- [Salesforce: No Forking Way](https://engineering.salesforce.com/no-forking-way-dc5fa842649b/) — internal copies with minimal patch set
- [Upstream first policy (LWN)](https://lwn.net/Articles/390706/) — land public before shipping private
- [Open-core model (Wikipedia)](https://en.wikipedia.org/wiki/Open-core_model) · [Some Thoughts on Open Core (Linux Journal)](https://www.linuxjournal.com/content/some-thoughts-open-core) — the starvation anti-pattern to avoid
- [GitLab repository mirroring](https://docs.gitlab.com/user/project/repository/mirror/) · [Git cherry-pick (Atlassian)](https://www.atlassian.com/git/tutorials/cherry-pick) — promotion primitives
- [GitHub required reviewer rule GA (Feb 2026)](https://github.blog/changelog/2026-02-17-required-reviewer-rule-is-now-generally-available/) · [About code owners](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners) — per-path required reviews
- [Managing permissions in a monorepo (Graphite)](https://graphite.com/guides/managing-permissions-access-control-monorepo) — coarse write access, CODEOWNERS as the control
- [SLSA framework (JFrog)](https://jfrog.com/learn/grc/slsa-framework/) · [Sigstore/SLSA build provenance (AquilaX)](https://aquilax.ai/blog/supply-chain-artifact-signing-slsa) — verify-before-deploy, cosign/Fulcio/Rekor keyless provenance
