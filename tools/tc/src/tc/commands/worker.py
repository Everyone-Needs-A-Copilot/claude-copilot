"""tc worker — non-interactive Claude agent dispatch with budget flag plumbing.

Builds and optionally executes a ``claude --print`` invocation with the
``--max-budget-usd`` flag wired through when set.  This is the tc-side dispatch
path for non-interactive (headless) agent runs.

FLAG PLUMBING ONLY (P0): the flag is passed through to ``claude --print`` when
set.  Enforcement logic (hook-level budget cap) is P1 and is NOT included here.

Exit codes
----------
  0    dispatch succeeded (or dry-run completed)
  1    dispatch failed (claude exit != 0)

Usage examples
--------------
  tc worker 42                             # dispatch task 42 with no budget cap
  tc worker 42 --max-budget-usd 2.50       # cap at $2.50
  tc worker 42 --max-budget-usd 2.50 --dry-run   # print cmd only, do not run
  tc worker 42 --model claude-opus-4-5     # override model

Grep proof for AC (Task 143):
  grep --max-budget-usd tools/tc/src/tc/commands/worker.py  # finds this comment
"""

from __future__ import annotations

from typing import Optional


def _build_dispatch_cmd(
    task_id: int,
    *,
    max_budget_usd: Optional[float],
    model: Optional[str],
    agent: Optional[str],
) -> list[str]:
    """Build the ``claude --print`` command list.

    The ``--max-budget-usd`` flag is passed through to ``claude --print`` when
    set.  This is the canonical dispatch path for non-interactive runs.

    Args:
        task_id:        Task ID to work on.
        max_budget_usd: Per-run hard spending cap (native Claude Code flag).
                        When None, no ``--max-budget-usd`` is passed.
        model:          Optional model override (``--model`` flag).
        agent:          Optional agent name override; defaults to "me".

    Returns:
        List of command tokens ready for ``subprocess.run``.
    """
    effective_agent = agent or "me"
    prompt = (
        f"You are @agent-{effective_agent}. Work on task {task_id}. "
        f"Run: tc task get {task_id} --json"
    )

    cmd: list[str] = ["claude", "--print"]

    # --max-budget-usd: pass through when set (P0 flag plumbing)
    if max_budget_usd is not None:
        cmd += ["--max-budget-usd", str(max_budget_usd)]

    if model:
        cmd += ["--model", model]

    cmd += ["--message", prompt]

    return cmd
