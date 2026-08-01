"""cc usage — query Claude session quota state.

Producer: ``cc usage`` writes/refreshes ~/.claude/session-usage.json.
Consumer: statusline and /memory dashboard read that file without re-probing.

ADR-003: probe only when a transcript changed in last ~12 min.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from cc.usage.probe import CACHE_PATH, read_cache, run_probe

usage_app = typer.Typer(
    name="usage",
    help="Show Claude session quota / rate-limit state.",
    no_args_is_help=False,
    invoke_without_command=True,
)

console = Console()
err_console = Console(stderr=True)


def _fmt_epoch(epoch: Optional[int]) -> str:
    if epoch is None:
        return "unknown"
    try:
        dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (OSError, ValueError, OverflowError):
        return str(epoch)


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "unknown"
    return f"{v * 100:.1f}%"


def _fmt_source(source: str, idle_gated: bool) -> str:
    if idle_gated:
        return f"{source} (idle-gated, returned cached)"
    return source


def _print_human(cache, path: Path) -> None:
    age_s = time.time() - cache.probed_at
    age_str = f"{int(age_s)}s ago" if age_s < 3600 else f"{age_s/3600:.1f}h ago"
    source = _fmt_source(cache.source, cache.idle_gated)

    console.print()
    console.print(f"[bold]Claude Session Quota[/bold]  source=[cyan]{source}[/cyan]  updated={age_str}")
    console.print(f"Cache: {path}")
    if cache.probe_error:
        console.print(f"[yellow]Probe error:[/yellow] {cache.probe_error}")
    console.print()

    if cache.source == "probe":
        # 5-hour window
        status5 = cache.five_h_status or "unknown"
        color5 = "green" if status5 == "allowed" else "red"
        console.print(f"  [bold]5-hour window[/bold]")
        console.print(f"    Status:      [{color5}]{status5}[/{color5}]")
        console.print(f"    Utilization: {_fmt_pct(cache.five_h_utilization)}")
        console.print(f"    Resets:      {_fmt_epoch(cache.five_h_reset_epoch)}")
        console.print()

        # 7-day window
        status7 = cache.seven_d_status or "unknown"
        color7 = "green" if status7 == "allowed" else "red"
        console.print(f"  [bold]7-day window[/bold]")
        console.print(f"    Status:      [{color7}]{status7}[/{color7}]")
        console.print(f"    Utilization: {_fmt_pct(cache.seven_d_utilization)}")
        console.print(f"    Resets:      {_fmt_epoch(cache.seven_d_reset_epoch)}")

        if cache.overage_status is not None:
            console.print()
            console.print(f"  [bold]Overage[/bold]")
            console.print(f"    Status:      {cache.overage_status}")
            console.print(f"    Utilization: {_fmt_pct(cache.overage_utilization)}")

        if cache.representative_claim:
            console.print()
            console.print(f"  Representative claim: {cache.representative_claim}")
        if cache.fallback_percentage is not None:
            console.print(f"  Fallback %: {_fmt_pct(cache.fallback_percentage)}")

    else:
        # Fallback (transcript reconstruction)
        console.print(f"  [dim]Offline reconstruction — counts are messages, not tokens[/dim]")
        console.print(f"  5-hour messages: {cache.five_h_tokens_reconstructed or 0}")
        console.print(f"  7-day  messages: {cache.seven_d_tokens_reconstructed or 0}")
        console.print(f"  5h resets: {_fmt_epoch(cache.five_h_reset_epoch)}")

    console.print()


@usage_app.callback(invoke_without_command=True)
def usage_cmd(
    ctx: typer.Context,
    output_json: bool = typer.Option(False, "--json", help="Output raw JSON cache."),
    refresh: bool = typer.Option(
        False,
        "--refresh",
        help="Force a new probe even if idle (bypasses the 12-min gate).",
    ),
    no_probe: bool = typer.Option(
        False,
        "--no-probe",
        help="Never probe; return cached data or transcript fallback only.",
    ),
    cache_path: Optional[str] = typer.Option(
        None,
        "--cache",
        help="Override cache file path (default: ~/.claude/session-usage.json).",
        hidden=True,
    ),
) -> None:
    """Show Claude session quota / rate-limit state.

    On macOS, attempts a 1-token probe against the Anthropic API using the
    Claude Code OAuth token from Keychain — but only when Claude Code is
    actively in use (transcript changed within 12 min).

    On non-macOS or when idle, reads transcript files to estimate activity.

    \b
    Examples:
        cc usage
        cc usage --json
        cc usage --refresh        # force probe even when idle
        cc usage --no-probe       # read cache only, never probe
    """
    if ctx.invoked_subcommand is not None:
        return

    resolved_path = Path(cache_path) if cache_path else CACHE_PATH

    if no_probe:
        cache = read_cache(resolved_path)
        if cache is None:
            from cc.usage.reconstruct import reconstruct_usage
            cache = reconstruct_usage()
            cache.idle_gated = True
    else:
        cache = run_probe(force=refresh, cache_path=resolved_path)

    if output_json:
        typer.echo(json.dumps(cache.to_dict(), indent=2))
        return

    _print_human(cache, resolved_path)
