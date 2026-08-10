"""tc worker — non-interactive Claude agent dispatch with budget plumbing,
spend measurement, and breach handling.

Builds and executes a ``claude --print --output-format json`` invocation, with
the ``--max-budget-usd`` flag wired through when set.  This is the tc-side
dispatch path for non-interactive (headless) agent runs.

What "budget enforcement" means here: the spending cap itself is enforced by
the Claude Code harness at the API boundary — ``--max-budget-usd`` is a native,
hard-enforced flag (see ``claude --help``), and passing it through *is*
enforcement.  There is no separate hook-level cap layered on top, and none is
needed: a PreToolUse hook cannot observe API spend, so it could not enforce
this cap correctly anyway.

What tc adds on top of the harness's cap:
  - Measurement: every dispatch's ``total_cost_usd`` / ``num_turns`` /
    ``stop_reason`` / ``terminal_reason`` is recorded to ``agent_log``.
  - Breach handling: when the harness kills a run for exceeding its cap
    (``terminal_reason == "budget_exhausted"``), the task is released back to
    ``pending`` with its claim cleared, instead of being left silently stuck
    ``in_progress``, and a ``budget_exhausted`` log entry records why.

Verified against ``claude --help`` (no ``--message`` flag exists; the prompt
is a positional argument). ``--agent`` selects the framework persona defined
in ``.claude/agents/<agent>.md`` for the dispatched session.

Exit codes
----------
  0    dispatch succeeded (or dry-run completed)
  1    dispatch failed (claude exit != 0), including a budget breach

Usage examples
--------------
  tc worker 42                             # dispatch task 42 with no budget cap
  tc worker 42 --max-budget-usd 2.50       # cap at $2.50
  tc worker 42 --max-budget-usd 2.50 --dry-run   # print cmd only, do not run
  tc worker 42 --model claude-opus-4-5     # override model
"""

from __future__ import annotations

import json as _json
import subprocess as _subprocess
from pathlib import Path
from typing import Any, Optional

# terminal_reason value the harness emits when --max-budget-usd is exceeded
# (verified by live invocation: `claude --print --max-budget-usd 0.001 ...`
# returns terminal_reason="budget_exhausted", subtype="error_max_budget_usd").
BUDGET_EXHAUSTED_REASON = "budget_exhausted"

# Fields worth persisting from the `claude --print --output-format json`
# result wrapper -- narrow allow-list, mirrors the one already used by
# cc.core.ecosystem.reconciliation_assistant for the same wrapper shape.
_SPEND_KEYS = (
    "total_cost_usd",
    "num_turns",
    "stop_reason",
    "terminal_reason",
    "is_error",
    "subtype",
)


def _build_dispatch_cmd(
    task_id: int,
    *,
    max_budget_usd: Optional[float],
    model: Optional[str],
    agent: Optional[str],
) -> list[str]:
    """Build the ``claude --print`` command list.

    The ``--max-budget-usd`` flag is passed through when set. The prompt is a
    positional argument (``claude`` has no ``--message`` flag) and the target
    persona is selected via the native ``--agent`` flag rather than by asking
    the model to role-play one in the prompt text.

    Args:
        task_id:        Task ID to work on.
        max_budget_usd: Per-run hard spending cap (native Claude Code flag,
                        enforced by the harness at the API boundary). When
                        None, no ``--max-budget-usd`` is passed.
        model:          Optional model override (``--model`` flag).
        agent:          Optional agent name override; defaults to "me". Passed
                        through to the native ``--agent`` flag.

    Returns:
        List of command tokens ready for ``subprocess.run``.
    """
    effective_agent = agent or "me"
    prompt = f"Work on task {task_id}. Run: tc task get {task_id} --json"

    cmd: list[str] = ["claude", "--print", "--output-format", "json"]

    if max_budget_usd is not None:
        cmd += ["--max-budget-usd", str(max_budget_usd)]

    if model:
        cmd += ["--model", model]

    cmd += ["--agent", effective_agent]

    # Prompt must be positional -- there is no --message flag.
    cmd.append(prompt)

    return cmd


def _parse_spend(stdout: str) -> dict[str, Any]:
    """Extract the allow-listed spend fields from a result wrapper.

    Never raises: a run that dies before printing a parseable JSON wrapper
    (crash, signal, empty stdout) must not take down dispatch. Returns an
    empty dict in that case.
    """
    try:
        data = _json.loads(stdout)
    except (_json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: data[k] for k in _SPEND_KEYS if k in data}


def is_budget_breach(spend: dict[str, Any]) -> bool:
    """True when the harness killed the run for exceeding --max-budget-usd."""
    return spend.get("terminal_reason") == BUDGET_EXHAUSTED_REASON


def dispatch(
    task_id: int,
    *,
    cmd: list[str],
    agent: Optional[str],
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Execute the dispatch command, record spend, and handle budget breach.

    Args:
        task_id: Task ID being dispatched (for logging/release).
        cmd:     Command list built by ``_build_dispatch_cmd``.
        agent:   Agent name used for the dispatch (defaults to "me" for
                 logging purposes if not given).
        db_path: Explicit DB path; if None, service calls walk up from cwd.

    Returns:
        ``{"returncode": int, "spend": dict, "breached": bool}``.
    """
    effective_agent = agent or "me"
    result = _subprocess.run(cmd, capture_output=True, text=True)
    spend = _parse_spend(result.stdout)
    breached = is_budget_breach(spend)

    from tc.services.log import record_log

    record_log(
        agent=effective_agent,
        task=task_id,
        action="worker_dispatch",
        details=_json.dumps({"returncode": result.returncode, **spend}),
        db_path=db_path,
    )

    if breached:
        from tc.services.tasks import update_task

        update_task(
            task_id=task_id,
            status="pending",
            clear_claim=True,
            db_path=db_path,
        )
        record_log(
            agent=effective_agent,
            task=task_id,
            action="budget_exhausted",
            details=_json.dumps(spend),
            db_path=db_path,
        )

    return {"returncode": result.returncode, "spend": spend, "breached": breached}
