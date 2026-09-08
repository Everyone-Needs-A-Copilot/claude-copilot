# ADR-001 — Local, bounded execution; one QA authority

Status: Accepted for user-authorized foundation implementation; pilot adoption
remains gated. Context: PRD-5 / TASK-58 and TASK-60–63.

## Decision

Keep pytest, shell contracts and Playwright. Add a thin local `cc` plan/run/status
surface with explicit scope, real process control, observable progress and durable
artifacts. Let agents diagnose and author checks; deterministic execution does not
require inference. `tc` remains the sole task-completion authority.

Select tests from behavior and affected consumers, fall back broadly for unknown
impact, and run a complete portable batch once at the batch/release boundary.
Keep machine, platform, performance and model-effectiveness lanes explicit.

## Alternatives rejected

- Full-suite execution after each small repair: repeated evidence at high feedback
  cost, without isolating the shared failure mechanism.
- Replacing meaningful tests with text assertions: misses persistence, rollback,
  concurrency, registration and runtime behavior.
- Mandatory multi-agent/healer chain: extra inference and handoffs for ordinary
  execution; risk of adjusting or skipping the test instead of fixing the product.
- Immediate hosted QA migration: no evidence yet that hosting is the bottleneck;
  adds cost and data-handling obligations without fixing Python suite duplication.
- Automatic pass reuse by task ID or Git commit alone: ignores dirty source,
  fixtures, dependencies, environment and different acceptance contracts.

## Consequences

One additional small runner/selection contract requires maintenance and adversarial
verification. Selection errors can hide defects, so conservative fallback and full
discovery-based release coverage are mandatory. Saved media/logs need privacy,
retention and size limits. Runtime caps stop expenditure, not uncertainty: a timeout
is incomplete. Faster feedback and fewer escapes remain hypotheses until measured.

The design satisfies the repository's local CLI, inspectability and honesty
boundaries; no service, telemetry-by-default or model provider is introduced.
