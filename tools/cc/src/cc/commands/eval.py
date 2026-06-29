"""cc eval — regression eval command for agent contracts.

Usage
-----
  cc eval --agent qa              # run the qa golden set
  cc eval --agent qa --json       # JSON output
  cc eval --agent qa --threshold 0.9
  cc eval --list-agents           # list agents with eval cases

Exit codes
----------
  0   all cases pass and pass-rate >= threshold
  1   pass-rate < threshold OR a P0 case regressed

Architecture
------------
Loads case YAML files from ``.claude/evals/<agent>/*.yaml``, runs them through
the pluggable runner (default: LocalPythonRunner — pure Python, no LLM, no Node),
persists scores to cc memory, and returns structured JSON.

Pluggable runner: the --runner flag is reserved for future adapters (e.g.
promptfoo), but wiring is not required for P0. The default local Python runner
handles all deterministic assertions.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

eval_app = typer.Typer(
    name="eval",
    help="Run regression evals against agent contracts.",
    no_args_is_help=True,
)

console = Console()
err_console = Console(stderr=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXIT_OK = 0
_EXIT_FAIL = 1


def _resolve_repo_root() -> Path:
    """Walk up from cwd to find the git root (or fall back to cwd)."""
    cwd = Path.cwd()
    candidate = cwd
    for _ in range(10):
        if (candidate / ".git").exists():
            return candidate
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return cwd


def _evals_dir(repo_root: Path) -> Path:
    return repo_root / ".claude" / "evals"


def _load_threshold(repo_root: Path) -> float:
    """Read pass-rate threshold from quality-gates.json. Defaults to 0.8."""
    gates_file = repo_root / ".claude" / "quality-gates.json"
    if not gates_file.exists():
        return 0.8
    try:
        data = json.loads(gates_file.read_text(encoding="utf-8"))
        eval_gate = data.get("eval", {})
        return float(eval_gate.get("pass_rate_threshold", 0.8))
    except Exception:
        return 0.8


def _persist_scores(result_dict: dict) -> None:
    """Store eval scores to cc memory (best-effort, never raises)."""
    try:
        from cc.core.entry_store import store_entry, default_scope
        import datetime

        agent = result_dict.get("agent", "unknown")
        pass_rate = result_dict.get("pass_rate", 0.0)
        total = result_dict.get("total", 0)
        passed = result_dict.get("passed", 0)
        p0_regression = result_dict.get("p0_regression", False)

        # Try to get git SHA for keying
        sha = "unknown"
        try:
            import subprocess
            out = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5,
            )
            if out.returncode == 0:
                sha = out.stdout.strip()
        except Exception:
            pass

        content = (
            f"eval {agent} pass_rate={pass_rate:.4f} "
            f"passed={passed}/{total} p0_regression={p0_regression} "
            f"sha={sha} date={datetime.date.today().isoformat()}"
        )
        store_entry(
            entry_type="reference",
            content=content,
            tags=["eval", agent, sha],
            scope=default_scope(),
        )
    except Exception:
        pass  # score persistence is best-effort


def _run_eval_impl(
    agent: str,
    threshold: Optional[float] = None,
    output_json: bool = False,
    evals_dir_override: Optional[str] = None,
    repo_root_override: Optional[str] = None,
) -> None:
    """Shared implementation called from both eval_run and eval_default.

    Raises typer.Exit with the appropriate exit code.
    """
    from cc.core.eval_runner import run_eval, LocalPythonRunner

    repo_root = (
        Path(repo_root_override)
        if (repo_root_override and isinstance(repo_root_override, str))
        else _resolve_repo_root()
    )
    evals_path = (
        Path(evals_dir_override)
        if (evals_dir_override and isinstance(evals_dir_override, str))
        else _evals_dir(repo_root)
    )
    effective_threshold = threshold if threshold is not None else _load_threshold(repo_root)

    try:
        result = run_eval(
            agent,
            evals_dir=evals_path,
            repo_root=repo_root,
            runner=LocalPythonRunner(),
        )
    except FileNotFoundError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(_EXIT_FAIL)
    except Exception as exc:
        err_console.print(f"[red]Unexpected error:[/red] {exc}")
        raise typer.Exit(_EXIT_FAIL)

    result_dict = result.as_dict()

    # Persist scores (best-effort)
    _persist_scores(result_dict)

    # Output
    if output_json:
        result_dict["threshold"] = effective_threshold
        result_dict["overall_pass"] = (
            result.pass_rate >= effective_threshold and not result.p0_regression
        )
        typer.echo(json.dumps(result_dict, indent=2))
    else:
        _format_human(result_dict, effective_threshold)

    # Exit code
    if result.pass_rate < effective_threshold or result.p0_regression:
        raise typer.Exit(_EXIT_FAIL)
    raise typer.Exit(_EXIT_OK)


def _format_human(result_dict: dict, threshold: float) -> None:
    """Print a human-readable eval summary."""
    agent = result_dict["agent"]
    total = result_dict["total"]
    passed = result_dict["passed"]
    failed = result_dict["failed"]
    pass_rate = result_dict["pass_rate"]
    p0_regression = result_dict["p0_regression"]

    # Summary line
    status_color = "green" if pass_rate >= threshold and not p0_regression else "red"
    status_label = "PASS" if pass_rate >= threshold and not p0_regression else "FAIL"
    console.print(
        f"\n[bold]cc eval[/bold]  agent=[cyan]{agent}[/cyan]  "
        f"[{status_color}]{status_label}[/{status_color}]  "
        f"{passed}/{total} passed  ({pass_rate * 100:.1f}%)"
    )

    if p0_regression:
        console.print("[red]  P0 regression detected — a priority-0 case failed.[/red]")

    # Per-case table
    table = Table(show_header=True, header_style="bold", show_edge=False)
    table.add_column("ID", style="dim", min_width=18)
    table.add_column("Priority", min_width=6, justify="center")
    table.add_column("Result", min_width=6, justify="center")
    table.add_column("Name")

    for c in result_dict.get("cases", []):
        c_passed = c["passed"]
        result_str = "[green]PASS[/green]" if c_passed else "[red]FAIL[/red]"
        p_color = "bold red" if c["priority"] == "P0" else "dim"
        table.add_row(
            c["id"],
            f"[{p_color}]{c['priority']}[/{p_color}]",
            result_str,
            c["name"],
        )

        if not c_passed:
            for a in c.get("assertions", []):
                if not a["passed"]:
                    console.print(
                        f"    [red]  FAIL[/red]  [{a['assertion_type']}] "
                        f"{a['description']}"
                    )
                    if a.get("error"):
                        console.print(f"         {a['error']}")

    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@eval_app.command("run")
def eval_run(
    agent: str = typer.Option(..., "--agent", help="Agent name to evaluate (e.g. qa)."),
    threshold: Optional[float] = typer.Option(
        None,
        "--threshold",
        help="Pass-rate threshold [0.0–1.0]. Default from quality-gates.json (0.8).",
    ),
    output_json: bool = typer.Option(False, "--json", help="Emit JSON to stdout."),
    evals_dir_override: Optional[str] = typer.Option(
        None,
        "--evals-dir",
        help="Override path to the evals directory (default: <repo-root>/.claude/evals).",
        hidden=True,
    ),
    repo_root_override: Optional[str] = typer.Option(
        None,
        "--repo-root",
        help="Override repo root (default: auto-detected git root).",
        hidden=True,
    ),
) -> None:
    """Run the golden eval set for an agent and exit non-zero on regression.

    Exit codes:
      0 — pass-rate >= threshold AND no P0 case regressed
      1 — pass-rate < threshold OR any P0 case regressed
    """
    _run_eval_impl(
        agent=agent,
        threshold=threshold,
        output_json=output_json,
        evals_dir_override=evals_dir_override,
        repo_root_override=repo_root_override,
    )


@eval_app.callback(invoke_without_command=True)
def eval_default(
    ctx: typer.Context,
    agent: Optional[str] = typer.Option(
        None, "--agent", help="Agent name to evaluate (e.g. qa)."
    ),
    threshold: Optional[float] = typer.Option(
        None, "--threshold", help="Pass-rate threshold [0.0–1.0]."
    ),
    output_json: bool = typer.Option(False, "--json", help="Emit JSON to stdout."),
    list_agents: bool = typer.Option(
        False, "--list-agents", help="List agents that have eval cases."
    ),
) -> None:
    """Run regression evals against agent contracts.

    Examples:
      cc eval --agent qa
      cc eval --agent qa --json
      cc eval --list-agents
    """
    if ctx.invoked_subcommand is not None:
        return

    if list_agents:
        repo_root = _resolve_repo_root()
        evals_path = _evals_dir(repo_root)
        if not evals_path.exists():
            console.print("[dim]No eval cases found.[/dim]")
            return
        agents = sorted(
            d.name for d in evals_path.iterdir()
            if d.is_dir() and list(d.glob("*.yaml"))
        )
        if agents:
            console.print("Agents with eval cases:")
            for a in agents:
                count = len(list((evals_path / a).glob("*.yaml")))
                console.print(f"  [cyan]{a}[/cyan]  ({count} cases)")
        else:
            console.print("[dim]No eval cases found.[/dim]")
        return

    if agent:
        # Call the shared implementation directly (avoids ctx.invoke param-default issues)
        _run_eval_impl(
            agent=agent,
            threshold=threshold,
            output_json=output_json,
        )
        return

    # No agent and no subcommand — show help
    typer.echo(ctx.get_help())
