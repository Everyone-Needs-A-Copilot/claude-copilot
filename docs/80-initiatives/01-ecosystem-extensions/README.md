# Initiative: Ecosystem Extensions (layered public → org → personal resolution)

Feasibility + recommendations for a **multi-tier** extension/resolution model where a user experiences one unified system while agents, skills, commands, knowledge, and integrations resolve across git-repo layers. The initiative started as a 3-layer model (public → company → personal) and was extended to a **4-tier / N-tier** model — **PERSONAL › DEPARTMENT › ORG › FOUNDATION** — with a GitHub multi-account topology and a foundation-owner promotion pipeline.

- **[00-findings-and-recommendations.md](00-findings-and-recommendations.md)** — the original deliverable (3-layer): BLUF, current state, per-dimension feasibility, proposed architecture (materialize-into-discovery-paths + manifest/lockfile resolver), phased roadmap, risks, next steps.
- **[02-four-tier-and-github-topology.md](02-four-tier-and-github-topology.md)** — the 4-tier / N-tier extension: how the resolver generalizes (~85% free), the typed/ranked manifest, department selection, the GitHub account topology (SSH host aliases for multi-account auth; separate-vs-subfolder dept repos), and ENAC-owns-the-foundation authoring via a one-way `copilot promote` valve.
- **[03-use-cases.md](03-use-cases.md)** — the most common workflows in the 4-tier model as concrete scenarios: onboarding, daily `copilot update`, `resolve --explain`, authoring at each layer (personal accountant / dept tax-calc / org excel-to-json / foundation protocol step), overrides, promotion, multi-department users, capability-policy governance, and version pin/rollback.
- **[research/](research/)** — source appendices:
  - `research-internal.md` — current-state trace of the two resolution engines.
  - `research-ecosystem.md` — project/repo inventory.
  - `research-priorart.md` — external layering precedents (Kustomize, git config, ESLint, west, chezmoi).
  - `research-ntier-arch.md` — N-tier generalization ADR.
  - `research-github-topology.md` — GitHub topology + multi-account credential architecture.
  - `research-foundation-governance.md` — foundation-owner authoring, promotion pipeline, supply-chain governance.

Status: Research / Proposed · Branch: `ecosystem-extensions` · Dates: 3-layer 2026-07-04, 4-tier 2026-07-06
