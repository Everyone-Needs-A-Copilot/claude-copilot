# Initiative: Ecosystem Extensions (layered public → org → personal resolution)

Feasibility + recommendations for a **multi-tier** extension/resolution model where a user experiences one unified system while agents, skills, commands, knowledge, and integrations resolve across git-repo layers. The initiative started as a 3-layer model (public → company → personal) and was extended to a **4-tier / N-tier** model — **PERSONAL › DEPARTMENT › ORG › FOUNDATION** — with a GitHub multi-account topology and a foundation-owner promotion pipeline.

- **[00-findings-and-recommendations.md](00-findings-and-recommendations.md)** — the original deliverable (3-layer): BLUF, current state, per-dimension feasibility, proposed architecture (materialize-into-discovery-paths + manifest/lockfile resolver), phased roadmap, risks, next steps.
- **[02-four-tier-and-github-topology.md](02-four-tier-and-github-topology.md)** — the 4-tier / N-tier extension: how the resolver generalizes (~85% free), the typed/ranked manifest, department selection, the GitHub account topology (SSH host aliases for multi-account auth; separate per-department repos — the default, for confidentiality), and ENAC-owns-the-foundation authoring via a one-way `copilot promote` valve.
- **[03-use-cases.md](03-use-cases.md)** — the most common workflows in the 4-tier model as concrete scenarios: onboarding, daily `copilot update`, `resolve --explain`, authoring at each layer (personal accountant / dept tax-calc / org excel-to-json / foundation protocol step), overrides, promotion, multi-department users, capability-policy governance, and version pin/rollback.
- **[04-ecosystem-architecture.md](04-ecosystem-architecture.md)** — **the final architecture.** The full 3-product × 4-tier ecosystem (Claude/Codex + Knowledge + CLI Copilot), the computable GitHub naming + self-describing `ecosystem.yml`, the zero-friction "Bob the accountant" installer, and — per §9 — a validation section mapping the **13 Critical + 17 High** failures two adversarial red-teams found to exactly how the design addresses each. Design + validation appendices live under `research/` (`design-*.md`, `redteam-*.md`).
- **[assets/ecosystem-diagram.html](assets/ecosystem-diagram.html)** — the layered diagram (Artifact): the 3×4 matrix, resolution flow, Bob's three-ring install, "focus not corpus," and the validated governance guards.
- **[assets/ecosystem-walkthrough.html](assets/ecosystem-walkthrough.html)** — the operator's walkthrough (Artifact): how each use case exploits the ecosystem, how the hardening pass improved them (before→after), the from-nothing install journey, the one-time IT setup, the sync-automation stack, and an honest "what's still missing."
- **[05-control-tower.md](05-control-tower.md)** — **Copilot Control Tower**: the always-on macOS menu-bar client + open-source IT setup/deploy tool (Tauri, single-process, host-aware Claude/Codex, MDM-deployable). Validated against two adversarial red-teams (§10 maps the 25 Critical+High findings to their fixes). Design + red-team appendices under `research/` (`design-control-tower-*.md`, `redteam-control-tower-*.md`).
- **[06-control-tower-prd.md](06-control-tower-prd.md)** — the parallel, multi-phase **PRD** for Control Tower: one prerequisite CLI-contract workstream gating eight concurrent app-side workstreams (shell, wizard, distribution, MDM/security, Bob-agency escalation, observability, Admin-mode/docs, Windows), with per-task acceptance criteria and phase gates. Ready for `/orchestrate`.
- **[research/](research/)** — source appendices:
  - `research-internal.md` — current-state trace of the two resolution engines.
  - `research-ecosystem.md` — project/repo inventory.
  - `research-priorart.md` — external layering precedents (Kustomize, git config, ESLint, west, chezmoi).
  - `research-ntier-arch.md` — N-tier generalization ADR.
  - `research-github-topology.md` — GitHub topology + multi-account credential architecture.
  - `research-foundation-governance.md` — foundation-owner authoring, promotion pipeline, supply-chain governance.

Status: Research / Proposed · Branch: `ecosystem-extensions` · Dates: 3-layer 2026-07-04, 4-tier 2026-07-06
