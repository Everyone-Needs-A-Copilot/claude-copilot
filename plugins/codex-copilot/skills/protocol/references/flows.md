# Protocol Flows

## Repository decision instruments

Before selecting a specialist flow for substantial work:

- read root `SOUL.md` when the work changes product behavior, UX, UI, copy, coaching, AI behavior, documents, onboarding, or other user-facing workflows
- read `docs/01-architecture/12-architecture-guiding-principles.md` when the work changes durable technical architecture, schemas, migrations, APIs, security, performance, data pipelines, AI orchestration, or productized implementation

Use `SOUL.md` to decide whether the product direction belongs in the product. Use architecture principles to decide how accepted direction should be built.

## Default workflows

The authoritative sequences are generated from `agent-catalog.json` into
`generated-workflows.md`. Read that file before routing; do not duplicate the
sequences here.

## Routing notes

- prefer `experience` when the work changes how users experience the product
- include `uid` for experience work that changes screens, components, responsive behavior, or interface states
- prefer `technical` when the change is mostly internal or architectural
- prefer `defect` when the task is about broken behavior or verification
- use `security-sensitive` when trust boundaries or privilege decisions are central
- use `infrastructure` when the work changes CI, deployment, environment setup, observability, worktrees, release automation, or operational safety

## Ambiguous requests

If the user says something like:

- improve the dashboard
- make onboarding better
- clean this up

and the correct flow is not obvious, stop and ask a short clarifying question before continuing.
