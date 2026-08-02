# Workflows

## Standard Sequences

Read `../../protocol/references/generated-workflows.md`. It is generated from
`agent-catalog.json`, the single workflow source of truth.

## Spawn Guidance

- use `explorer` when the output is analysis, diagnosis, decomposition, or review
- use `worker` when the output is code
- use `default` when the work is cross-functional or design-heavy

## Prompt Skeleton

For a spawned specialist:

```text
You are acting as codex-copilot specialist <id>.
Use the <skill-name> playbook.
Own only this scope: <scope>.
Return: <expected output>.
Do not touch files outside: <paths>.
```
