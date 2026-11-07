"""Historical managed instruction blocks, kept ONLY so `cc project migrate` can recognise them.

The reconcile recipe engine that lived here (per-file framework copies, lock entries,
plan/apply transactions) is retired with the copy model. Old projects still carry the
marker-delimited CLAUDE.md / AGENTS.md blocks it wrote; `project_migrate.known` reads these
two constants to classify those blocks as framework text rather than project text. Nothing
here writes anything.
"""

from __future__ import annotations

_CLAUDE_BLOCK = (
    "<!-- cc:project-integration:claude:v1:start -->\n"
    "## Claude Copilot\n\n"
    "This project uses the shared Claude Copilot framework. Preserve the "
    "project-specific instructions in this file and the installed `.claude/` "
    "capabilities. Read `.claude/agents/_shared/work-lifecycle.md` when installed "
    "for proportional learning, handoff and verified retirement checkpoints; "
    "use `/cleanup` for accumulated clutter.\n"
    "<!-- cc:project-integration:claude:v1:end -->\n"
)

_CODEX_BLOCK = (
    "<!-- cc:project-integration:codex:v1:start -->\n"
    "## Codex Copilot\n\n"
    "This project uses the project-local Codex Copilot plugin at "
    "`./plugins/codex-copilot`. Preserve project-specific instructions and "
    "capabilities.\n"
    "<!-- cc:project-integration:codex:v1:end -->\n"
)
