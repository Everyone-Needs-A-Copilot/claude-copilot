# claude-copilot Architecture Guiding Principles

Use this file to decide how accepted product direction should be built.

## System Context

- Project: `claude-copilot`
- Stack: Unknown
- Description: Project using Copilot Control Tower

## Principles

1. Preserve product intent in the implementation.
2. Prefer simple, observable flows over clever hidden behavior.
3. Keep boundaries explicit between UI, domain logic, persistence, integrations, and infrastructure.
4. Make failure states recoverable and visible to the right actor.
5. Treat security, privacy, accessibility, and performance as design constraints.
6. Add abstractions only when they reduce real complexity or match an established local pattern.

## Design-Led Implementation Rules

- Start with the workflow and state model before choosing the code shape.
- Keep UI components aligned with the visual and interaction direction.
- Make product copy, validation, permissions, empty states, loading states, errors, and recovery paths part of the implementation scope.
- Prefer instrumentation that reveals whether the designed experience is actually working.

## Review Questions

Before durable technical work, answer:

1. Which product decision is this architecture serving?
2. What boundary or contract must stay stable?
3. What failure mode needs first-class handling?
4. What future change should this make easier?
5. What complexity are we intentionally rejecting?
