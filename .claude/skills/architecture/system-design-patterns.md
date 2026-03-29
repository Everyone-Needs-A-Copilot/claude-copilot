---
skill_name: system-design-patterns
skill_category: architecture
description: Architecture patterns, ADR methodology, and trade-off analysis frameworks
allowed_tools: [Read, Grep, Glob, Edit, Write]
token_estimate: 2000
version: 1.0
last_updated: 2026-03-29
owner: Claude Copilot
status: active
tags: [architecture, system-design, adr, patterns, trade-offs]
trigger_files: ["**/architecture/**", "**/infra/**", "docker-compose*", "*.tf", "**/api/**"]
trigger_keywords: [architecture, microservices, monolith, cqrs, event-driven, api-gateway, scalability, trade-off]
quality_keywords: [anti-pattern, pattern, trade-off, decision, fitness-function]
---

# System Design Patterns

Architecture patterns, ADR methodology, and trade-off analysis frameworks for making and documenting sound design decisions.

## Purpose

- Document architectural decisions with full context and rationale
- Select the right architectural pattern for the problem at hand
- Validate architecture with automated fitness functions
- Analyse trade-offs explicitly before committing to a direction

---

## ADR Template

Architecture Decision Records capture the context and consequences of significant design choices.

```markdown
# ADR-[number]: [Title]

**Date:** YYYY-MM-DD
**Status:** Proposed | Accepted | Deprecated | Superseded by ADR-[n]

## Context

What is the situation forcing a decision? What constraints exist?
What forces are at play (technical, political, organizational)?

## Decision

What was decided? State it as an active voice sentence:
"We will use [X] because [Y]."

## Consequences

**Positive:**
- [Benefit 1]
- [Benefit 2]

**Negative:**
- [Trade-off 1]
- [Trade-off 2]

**Neutral:**
- [Side effect that is neither good nor bad]

## Alternatives Rejected

| Alternative | Reason Rejected |
|-------------|----------------|
| [Option A]  | [Why not chosen] |
| [Option B]  | [Why not chosen] |

## References

- [Link to relevant documentation, RFC, or prior art]
```

---

## Architecture Pattern Decision Matrix

| Pattern | Best When | Avoid When | Key Trade-offs |
|---------|-----------|------------|----------------|
| **Layered (Monolith)** | Small team, simple domain, fast iteration needed | Independent deployment required, team > 10, polyglot stack | Fast to build; harder to scale independently |
| **Microservices** | Independent deployment needed, team autonomy, polyglot stack | Domain is unclear, team is small, ops maturity is low | High autonomy; high operational complexity |
| **Event-Driven** | Async workflows, eventual consistency acceptable, audit trail needed | Strong consistency required, debugging must be simple | Decoupled producers; complex event ordering |
| **CQRS** | Read/write asymmetry, complex queries, event sourcing in use | Simple CRUD, small team, low query complexity | Optimised reads/writes; two models to maintain |
| **API Gateway** | Multiple clients, rate limiting needed, auth aggregation | Single client, low traffic, gateway becomes bottleneck | Centralised cross-cutting concerns; single point of failure risk |

---

## Fitness Function Examples

Automated architecture tests that verify the system conforms to its intended structure.

### Dependency Rules

```typescript
// No circular dependencies between modules
import { checkCycles } from 'madge';

test('no circular dependencies', async () => {
  const result = await madge('./src', { fileExtensions: ['ts'] });
  expect(result.circular()).toHaveLength(0);
});
```

### Anti-Corruption Layer

```typescript
// All external calls go through anti-corruption layer
test('external integrations isolated', () => {
  const externalCalls = findFilesWithPattern('src/**/*.ts', /fetch|axios|http\.request/);
  const allowedPaths = ['src/infrastructure/', 'src/adapters/'];

  externalCalls.forEach(file => {
    expect(allowedPaths.some(p => file.startsWith(p))).toBe(true);
  });
});
```

### Performance Threshold

```typescript
// Response time p99 < defined threshold
test('p99 latency within SLA', async () => {
  const metrics = await loadTestEndpoint('/api/search', { rps: 100, duration: 60 });
  expect(metrics.p99).toBeLessThan(500); // 500ms SLA
});
```

### Layering Enforcement

```typescript
// No direct database access from presentation layer
test('presentation layer does not access database', () => {
  const violations = findImports('src/controllers/**/*.ts', /typeorm|prisma|knex|sequelize/);
  expect(violations).toHaveLength(0);
});
```

---

## Trade-Off Analysis Checklist

For every significant architectural decision, answer these questions before committing:

- [ ] **Quality attribute optimised:** What does this choice improve? (performance, scalability, reliability, maintainability, security, cost)
- [ ] **Quality attribute sacrificed:** What does this choice make worse?
- [ ] **Reversibility:** Can we undo this decision in < 1 sprint? If not, treat as high-stakes.
- [ ] **Evidence-based:** Is the decision driven by observed data or assumed need? (avoid premature optimisation)
- [ ] **Team readiness:** Does the team have the skills to operate this pattern in production?
- [ ] **Failure mode understood:** What happens when this component fails? Is it graceful?
- [ ] **Migration path:** If we need to move away from this, what is the path?
- [ ] **Documentation:** Is the decision recorded in an ADR?

---

## Anti-Patterns

| Anti-Pattern | Description | Consequence |
|-------------|-------------|-------------|
| **God Service** | One service owns too much domain logic and data | Becomes the monolith everyone feared; all teams blocked on it |
| **Distributed Monolith** | Microservices that must deploy together or share a database | Operational complexity of microservices with zero autonomy benefit |
| **Shared Database Between Services** | Multiple services read/write the same database schema | Schema changes require coordinating all services; no true encapsulation |
| **Synchronous Chain > 3 Hops** | Request triggers 4+ synchronous downstream calls | Latency multiplies; one slow service degrades everything |
| **Premature Decomposition** | Splitting into microservices before domain boundaries are understood | Wrong boundaries require expensive re-merging or re-splitting later |

---

## Related Resources

- [C4 Model](https://c4model.com/) — architecture diagramming
- [Architectural Decision Records](https://adr.github.io/) — ADR tooling and examples
- [Building Evolutionary Architectures](https://evolutionaryarchitecture.com/) — fitness functions
- Related skills: `skill_get("docker-patterns")`, `skill_get("threat-modeling")`
