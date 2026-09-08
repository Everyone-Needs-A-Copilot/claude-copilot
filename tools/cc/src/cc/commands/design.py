"""cc design — task-scoped guidance and evidence for both native frameworks."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import typer

from cc.core.design import contracts, feedback, review, tools
from cc.core.locking import LockContentionError

design_app = typer.Typer(help="Design guidance, pinned audits and review evidence; tc retains QA authority.", no_args_is_help=True)
tool_app = typer.Typer(help="Explicitly manage the machine-pinned external detector.", no_args_is_help=True)
design_app.add_typer(tool_app, name="tool")


def _run(fn, *, output_json: bool = True):
    try:
        result = fn()
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError, LockContentionError) as exc:
        typer.echo(json.dumps({"error": str(exc)}) if output_json else str(exc), err=True)
        raise typer.Exit(2)
    if result is not None:
        if not output_json and isinstance(result, dict) and "content" in result:
            typer.echo(result["content"])
        else:
            typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
    return result


@design_app.command("guide")
def guide_cmd(action: Optional[str] = typer.Argument(None), output_json: bool = typer.Option(False, "--json")):
    """List focused actions or load one source-hashed playbook."""
    _run(lambda: contracts.guide(action), output_json=output_json)


@design_app.command("template")
def template_cmd(output: Optional[str] = typer.Option(None, "--output"), output_json: bool = typer.Option(False, "--json")):
    """Print a draft surface contract; --output creates a new file exclusively."""
    def execute():
        value = contracts.template()
        if output:
            contracts.create_file(Path.cwd(), output, json.dumps(value, indent=2) + "\n")
        return value
    _run(execute, output_json=output_json)


@design_app.command("context")
def context_cmd(contract: str = typer.Option(..., "--contract"), action: str = typer.Option("shape", "--action"),
                max_chars: int = typer.Option(12000, "--max-chars", min=0, max=100000),
                output_json: bool = typer.Option(False, "--json")):
    """Load a surface contract and bounded explicit authority, with selection receipts."""
    _run(lambda: contracts.context(Path.cwd(), contract, action=action, max_chars=max_chars), output_json=output_json)


@design_app.command("review")
def review_cmd(contract: str = typer.Option(..., "--contract"), assessment: str = typer.Option(..., "--assessment"),
               output: str = typer.Option(..., "--output"), output_json: bool = typer.Option(False, "--json")):
    """Record initial design judgment before running the detector."""
    _run(lambda: review.start_review(Path.cwd(), contract, assessment, output), output_json=output_json)


@design_app.command("audit")
def audit_cmd(targets: Optional[List[str]] = typer.Argument(None), review_path: Optional[str] = typer.Option(None, "--review"),
              output: Optional[str] = typer.Option(None, "--output"), timeout: int = typer.Option(20, "--timeout", min=1, max=60),
              output_json: bool = typer.Option(False, "--json")):
    """Run a pinned local static scan; exit 1 when scan evidence is unavailable."""
    def execute():
        if review_path:
            if targets or not output:
                raise ValueError("--review uses its own targets and requires --output")
            return review.audit_review(Path.cwd(), review_path, output, timeout=timeout)
        result = tools.audit(Path.cwd(), targets or [], timeout=timeout)
        return contracts.save_receipt(Path.cwd(), output, result) if output else result
    result = _run(execute, output_json=output_json)
    if result["status"] != "completed":
        raise typer.Exit(1)


@design_app.command("report")
def report_cmd(review_path: str = typer.Option(..., "--review"), audit_path: str = typer.Option(..., "--audit"),
               verification: str = typer.Option(..., "--verification"), output: str = typer.Option(..., "--output"),
               output_json: bool = typer.Option(False, "--json")):
    """Check criterion coverage and evidence identity; never issue a QA verdict."""
    result = _run(lambda: review.report(Path.cwd(), review_path, audit_path, verification, output), output_json=output_json)
    if not result["ready_for_qa"]:
        raise typer.Exit(1)


@design_app.command("compare")
def compare_cmd(manifest: str = typer.Argument(...), output: str = typer.Option(..., "--output"),
                output_json: bool = typer.Option(False, "--json")):
    """Create a self-contained baseline/candidate screenshot comparison."""
    _run(lambda: review.compare(Path.cwd(), manifest, output), output_json=output_json)


@tool_app.command("status")
def status_cmd(output_json: bool = typer.Option(False, "--json")):
    """Verify the registered executable's current content hash."""
    _run(tools.tool_status, output_json=output_json)


@tool_app.command("install")
def install_cmd(replace: bool = typer.Option(False, "--replace"), output_json: bool = typer.Option(False, "--json")):
    """Download the reviewed release asset and verify its packaged SHA256."""
    _run(lambda: tools.install_tool(replace=replace), output_json=output_json)


@tool_app.command("register")
def register_cmd(binary: Path = typer.Argument(...), sha256: str = typer.Option(..., "--sha256"),
                 version: str = typer.Option(..., "--version"), source: str = typer.Option(..., "--source"),
                 replace: bool = typer.Option(False, "--replace"), output_json: bool = typer.Option(False, "--json")):
    """Pin a separately verified local Impeccable engine; never trust project-selected executables."""
    _run(lambda: tools.register_tool(binary, sha256, version, source, replace=replace), output_json=output_json)


@design_app.command("feedback-config")
def feedback_config_cmd(runtime: str = typer.Option(..., "--runtime"), enabled: bool = typer.Option(True, "--enable/--disable"),
                        output_json: bool = typer.Option(False, "--json")):
    """Enable/disable project feedback and preserve unrelated native hooks."""
    _run(lambda: feedback.configure(Path.cwd(), runtime, enabled=enabled), output_json=output_json)


@design_app.command("feedback")
def feedback_cmd(runtime: str = typer.Option(..., "--runtime")):
    """Native PostToolUse adapter; bounded input/output and no task-state mutation."""
    try:
        raw = sys.stdin.buffer.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise ValueError("Native event exceeds input limit")
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError("Native event must be an object")
        result = feedback.feedback(Path.cwd(), event, runtime)
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        result = feedback.envelope(f"Design feedback unavailable: {exc}. Complete explicit QA checks; no task approval granted.")
    if result is not None:
        typer.echo(json.dumps(result))
