"""`cc connect <service-id> --json` -- write locally-supplied secret VALUES
into the per-user OS keychain for one service's missing credential NAMES
(WP-395's D-6 "manual keychain floor", Task Copilot task 222).

WP-395 traced the "Bob in accounting" connect path end to end and found no
verb anywhere writes the credential the ladder reads (gap G-4): the only
keychain WRITER in the ecosystem was `core/keychain.py`'s `set_secret()`,
used exclusively by `cc auth` for the GitHub device-flow token under a
*different* keychain service. WP-396/398 designed the pragmatic (option-a)
in-app connect experience around a value the user types once, that never
touches disk except the OS keychain. This module is the CLI floor under
that experience -- the owner ratified in-app secret input (never `.env`,
never a device-flow/OIDC replacement, which remains a future North Star
model, WP-396 Walkthrough 1).

**What this verb computes, and what it reuses (invariant #1 still holds).**
The SET of a service's required credential NAMES, and which of them are
currently missing, is entirely `cc connections`' own job (`commands/
connections.py`'s `build_connections_report()` -- the single source of
truth WP-388/389/390 already built for exactly this question). This module
adds exactly one new capability on top of that: accepting secret VALUES for
those missing names and writing them to the local OS keychain, then asking
`connections.py` to re-evaluate so the caller gets a fresh, honest row back.
It never re-implements presence-checking, store probing, or the `from`
routing-hint logic -- see `_find_row()`, which only reads
`build_connections_report()`'s own output.

**Why re-run the full connections report instead of a cheaper targeted
re-check.** `connections.py`'s own docstring already flags per-invocation
cost as a design concern ("cheap and offline-tolerant like doctor/
freshness, not a network round-trip on every invocation"), and this verb's
write path calls it twice (before, to know what's missing; after, to
report what changed). A narrower re-check would need this module to import
`connections.py`'s private per-row/per-store helpers or duplicate their
routing logic -- exactly the kind of premature abstraction/duplication this
codebase's design discipline forbids for a verb that runs on a deliberate,
occasional user action (typing a credential), never a hot path. Simplicity
and the single-source-of-truth guarantee win over the extra `copilot`
invocation.

**Values travel on stdin ONLY -- never argv, an environment variable, or a
file.** This is the entire reason this verb exists as a separate write path
rather than, say, a `--value` flag:

  - **argv** is world-readable for the lifetime of the call via `ps`/`/proc`/
    any process-listing tool, and is exactly the leak class WP-395 called
    out in the manual `security add-generic-password ... -w '<value>'`
    command it found nobody was ever given.
  - **An environment variable** is inherited by every child process the `cc`
    invocation spawns, is visible via `/proc/<pid>/environ` (or `ps -Ewwww`
    on this same OS) for the process's whole lifetime rather than one
    subprocess call, and is a common accidental-logging surface (shells,
    supervisors, and crash reporters all dump environments more readily
    than argv or stdin).
  - **A file** would put the value at rest on disk under a name/path this
    verb would then have to remember to delete, with no guarantee of that
    cleanup surviving a crash -- precisely the "at rest anywhere but the
    keychain" outcome this verb's entire job is to avoid.

  Reading a JSON object off stdin, acting on it in-process, and never
  persisting the raw request anywhere is the only one of the four
  candidate channels with no leak window after the call returns. See
  `_read_stdin_credentials()` and `core/keychain.py`'s `set_secret_stdin()`
  (the non-leaking `security` invocation this module writes through).

**Never echoes a value.** Every credential outcome this module reports is
`{name, outcome, detail}` -- `detail` is always a plain-language, non-value
string this module authors itself (never a copy of stdin, never a copy of
an underlying command's stdout/stderr). An empty value, a non-string value,
or a value containing a line break (a mechanism limit of the stdin-batch
protocol `set_secret_stdin()` uses -- see that function's docstring) is
rejected BEFORE ever reaching the keychain writer, with a structured
`failed` outcome that names the reason, never the value.

**Honest for every combination the trace called out.** An unknown
`service-id` and a service with zero missing credentials are both
ordinary, fully-structured outcomes (WP-395's honesty rule: no state whose
only visible effect is a crash or a blank screen) -- see
`build_connect_report()`'s `unknown-service` result and its "every
`requires_secret` name not in `missing` reads `already-present`, and
`--check`/no-missing-credentials never reads stdin at all" behavior.

Schema: copilot-control-tower/docs/01-architecture/schemas/connect.schema.json
(vendored copy: tools/cc/tests/fixtures/schemas/connect.schema.json).
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, Optional

from cc.commands.connections import KEYCHAIN_SERVICE, build_connections_report
from cc.core import keychain

SCHEMA_VERSION = "1.0"

ReadStdin = Callable[[], str]
WriteKeychain = Callable[[str, str], bool]

# A generous cap on how much stdin this verb will ever read -- a handful of
# short credential values, never a bulk payload. Guards against a caller
# piping something unbounded (e.g. `/dev/zero`) into a non-interactive `cc`
# invocation; the read is aborted (treated as invalid input) past this size
# rather than blocking indefinitely or exhausting memory.
_MAX_STDIN_BYTES = 65_536


def _default_stdin_reader() -> str:
    """Default `ReadStdin`: read stdin to EOF, bounded by `_MAX_STDIN_BYTES`.
    Tests inject a fake so nothing here ever blocks on a real terminal."""
    return sys.stdin.read(_MAX_STDIN_BYTES + 1)


def _default_write_keychain(name: str, value: str) -> bool:
    """Default `WriteKeychain`: `core/keychain.py`'s non-leaking stdin
    writer, under the same `copilot-cli` keychain service the credential
    ladder's rung 2 reads (`connections.KEYCHAIN_SERVICE`, mirroring
    cli-copilot's `secrets_ladder.KEYCHAIN_SERVICE`)."""
    return keychain.set_secret_stdin(name, value, service=KEYCHAIN_SERVICE)


def _find_row(connections: list[dict[str, Any]], service_id: str) -> Optional[dict[str, Any]]:
    """Match *service_id* against a connections row. Tries `id` first (the
    schema's "stable slug"), then `name` (the schema's own documented
    "this row's identity for a Connect action to reference") -- accepting
    either keeps this verb usable against `cc connections --json` output
    from before `id` existed (where it defaults to `name`) without forcing
    a caller to know which field a given `copilot` version populates."""
    for row in connections:
        if row.get("id") == service_id:
            return row
    for row in connections:
        if row.get("name") == service_id:
            return row
    return None


def _parse_credentials_payload(raw: str) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Parse *raw* stdin text as a JSON object of `{"NAME": "value", ...}`.

    Returns `(payload, None)` on success or `(None, detail)` on any
    failure. `detail` is always a plain-language description this function
    authors itself -- NEVER a copy of *raw* (which, on a malformed-JSON
    call, may still contain a credential value the caller intended to
    send)."""
    if len(raw.encode("utf-8", errors="ignore")) > _MAX_STDIN_BYTES:
        return None, "stdin was larger than this verb accepts."
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None, "stdin was not valid JSON."
    if not isinstance(payload, dict):
        return None, 'stdin must be a JSON object of {"NAME": "value"}.'
    return payload, None


def _validate_value(value: Any) -> Optional[str]:
    """Returns a plain-language rejection reason for *value*, or `None` if
    it is acceptable to write. NEVER includes the value itself in the
    reason."""
    if not isinstance(value, str):
        return "value must be a string."
    if not value:
        return "value must not be empty."
    if "\n" in value or "\r" in value:
        return "value must not contain a line break."
    return None


def _envelope(
    *,
    result: str,
    detail: Optional[str],
    mode: str,
    service: Optional[dict[str, Any]],
    credentials: Optional[list[dict[str, Any]]],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result": result,
        "detail": detail,
        "mode": mode,
        "service": service,
        "credentials": credentials,
    }


def build_connect_report(
    service_id: str,
    *,
    check_only: bool = False,
    stdin_reader: Optional[ReadStdin] = None,
    run: Optional[Any] = None,
    ecosystem_cfg: Optional[dict[str, Any]] = None,
    check_keychain: Optional[Any] = None,
    write_keychain: Optional[WriteKeychain] = None,
) -> dict[str, Any]:
    """Build the `cc connect <service-id> --json` contract object.

    `run`/`ecosystem_cfg`/`check_keychain` are threaded straight through to
    `connections.build_connections_report()` -- same collaborators, same
    defaults, so a test (or a future caller) configures this module's
    dependency on the connections machinery exactly the way it would
    configure `connections.py` directly. `stdin_reader` defaults to a
    bounded real stdin read; `write_keychain` defaults to the non-leaking
    `core/keychain.py` writer. See the module docstring for the full
    design and the stdin-only rationale.
    """
    if stdin_reader is None:
        stdin_reader = _default_stdin_reader
    if write_keychain is None:
        write_keychain = _default_write_keychain

    mode = "check" if check_only else "connect"

    connections_report = build_connections_report(
        run=run, ecosystem_cfg=ecosystem_cfg, check_keychain=check_keychain
    )
    underlying_result = connections_report.get("result")
    connections = [
        row for row in connections_report.get("connections", []) if isinstance(row, dict)
    ]

    if underlying_result == "copilot-unavailable":
        return _envelope(
            result="copilot-unavailable",
            detail=connections_report.get("detail"),
            mode=mode,
            service=None,
            credentials=None,
        )

    row = _find_row(connections, service_id)
    if row is None:
        return _envelope(
            result="unknown-service",
            detail=f"No service named '{service_id}' is in this Mac's roster.",
            mode=mode,
            service=None,
            credentials=None,
        )

    if check_only:
        return _envelope(
            result=underlying_result,
            detail=connections_report.get("detail"),
            mode="check",
            service=row,
            credentials=None,
        )

    missing = [name for name in row.get("missing") or [] if isinstance(name, str)]
    missing_set = set(missing)
    requires = row.get("requires_secret") or []

    payload: dict[str, Any] = {}
    parse_detail: Optional[str] = None
    if missing:
        raw = stdin_reader()
        parsed, parse_detail = _parse_credentials_payload(raw)
        if parsed is not None:
            payload = parsed

    credentials: list[dict[str, Any]] = []
    for item in requires:
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name:
            continue

        if name not in missing_set:
            credentials.append({"name": name, "outcome": "already-present", "detail": None})
            continue

        if parse_detail is not None:
            credentials.append({"name": name, "outcome": "failed", "detail": parse_detail})
            continue

        if name not in payload:
            credentials.append(
                {
                    "name": name,
                    "outcome": "failed",
                    "detail": "no value was provided for this credential.",
                }
            )
            continue

        value = payload[name]
        rejection = _validate_value(value)
        if rejection is not None:
            credentials.append({"name": name, "outcome": "failed", "detail": rejection})
            continue

        try:
            stored = write_keychain(name, value)
        except (keychain.KeychainUnavailable, ValueError) as exc:
            credentials.append({"name": name, "outcome": "failed", "detail": str(exc)})
            continue

        if stored:
            credentials.append({"name": name, "outcome": "stored", "detail": None})
        else:
            credentials.append(
                {"name": name, "outcome": "failed", "detail": "the keychain write failed."}
            )

    # Re-run the presence check so `service` reflects reality after any
    # writes -- see the module docstring for why this is a full re-run
    # rather than a narrower targeted re-check.
    refreshed_report = build_connections_report(
        run=run, ecosystem_cfg=ecosystem_cfg, check_keychain=check_keychain
    )
    refreshed_connections = [
        r for r in refreshed_report.get("connections", []) if isinstance(r, dict)
    ]
    refreshed_row = _find_row(refreshed_connections, service_id) or row

    result = "invalid-input" if parse_detail is not None else underlying_result
    detail = parse_detail if parse_detail is not None else connections_report.get("detail")

    return _envelope(
        result=result,
        detail=detail,
        mode="connect",
        service=refreshed_row,
        credentials=credentials,
    )


def _connect_exit_code(report: dict[str, Any]) -> int:
    """Exit `0` only when the envelope-level result is `ok` AND (in connect
    mode) no individual credential outcome is `failed` -- a partial write
    failure is a real failure for scripting purposes even though the
    report itself is a complete, honest success-shaped payload."""
    if report.get("result") != "ok":
        return 1
    credentials = report.get("credentials")
    if credentials and any(c.get("outcome") == "failed" for c in credentials):
        return 1
    return 0


def render_connect_report_rich(report: dict[str, Any], *, console: Any = None) -> None:
    """Human-readable (Rich) rendering of a `build_connect_report()`
    payload. NEVER renders a credential value -- there is none in the
    report to render (see the module docstring)."""
    from rich.console import Console

    con = console or Console()
    result = report.get("result", "unknown")
    if result not in ("ok",):
        con.print(f"[bold red]{result}[/bold red]: {report.get('detail') or 'unknown error'}")
        if report.get("service") is None:
            return

    service = report.get("service") or {}
    con.print(
        f"[bold]{service.get('name', report.get('service_id', '?'))}[/bold]: "
        f"{service.get('secret_state', 'unknown')}"
    )

    credentials = report.get("credentials")
    if not credentials:
        return
    for cred in credentials:
        outcome = cred.get("outcome")
        color = {"stored": "green", "already-present": "cyan", "failed": "red"}.get(
            outcome, "yellow"
        )
        line = f"  [{color}]{outcome}[/{color}] {cred.get('name')}"
        if cred.get("detail"):
            line += f" -- {cred['detail']}"
        con.print(line)
