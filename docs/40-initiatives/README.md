# Initiatives

> Mode: Reference  
> Audience: maintainers and agents documenting, planning, and validating multi-phase initiatives

## What Is An Initiative

An initiative is a multi-phase body of work with a defined goal, explicit decisions, and evidence-bound exit criteria. It is larger than a task or a single feature spec and is expected to survive multiple sessions.

Formal initiative documentation lives only in `docs/40-initiatives/NN-slug/`.

## Current Initiatives

| Folder | Initiative | Goal | Status | `tc` context |
| --- | --- | --- | --- | --- |

## Directory Contract

```text
docs/40-initiatives/
  README.md
  _template/
  NN-slug/
    README.md
    phases/
    decisions/
    retrospectives/
```

## Markdown And `tc` Ownership

Initiative Markdown records durable intent, rationale, phase design, decisions, validation evidence, and outcomes. `tc` remains authoritative for live task state, assignments, dependencies, work products, and QA status.

Do not maintain a second task board in an initiative README. Summarize current status and link to the corresponding PRD or tasks instead.

## How To Add An Initiative

1. Choose the next unused two-digit number; never renumber existing initiatives.
2. Copy `_template/` to `NN-slug/`.
3. Complete the initiative README before creating implementation tasks.
4. Create or link the matching `tc` PRD and tasks.
5. Add the initiative to the table in this file.
6. Record significant choices in `decisions/`.
7. Store phase validation in closure audits and in a `tc` test work product.

Do not create `docs/initiatives/`. Closed or superseded initiatives move to `docs/90-archive/initiatives/` with a redirect note at the original path.
