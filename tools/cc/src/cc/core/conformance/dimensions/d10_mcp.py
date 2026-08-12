"""D10 -- MCP wiring (`RUBRIC.md` D10, `TEST-MATRIX.md` IC-D10-MCPOBJ).

Two independent checks, matching the two distinct MCP-wiring failure modes
found on this machine:

  - `repo.d10.mcp_object_no_retired_servers` -- `.mcp.json` parses with an
    `mcpServers` OBJECT (an empty object is the correct, modern state --
    Claude Copilot has shipped no MCP servers of its own since v5.0.0) that
    names no retired Copilot-owned server (`copilot-memory`,
    `skills-copilot`, `task-copilot`, or `research-copilot`).
    `cc workspace verify`'s own `_verify_claude_entry` treats ANY
    `mcpServers` object -- including one still declaring a dead server -- as
    PRESENT (`EXISTING-VERIFICATION.md` section 2: "An empty dict passes.").
    That is exactly the hollow pass this harness exists to catch, so this
    check asserts substance (no retired config left behind), not merely
    object shape. Legitimate third-party servers (`nocodb-mcp`,
    `postgresql-mcp`, `delphi-assistant`) are preserved and
    never flagged -- `/update-project` explicitly does not touch
    `.mcp.json`, and neither does this check.

  - `repo.d10.mcp_json_is_committable` -- no `.gitignore` rule excludes
    `.mcp.json` (RC-6: `claude-copilot`'s own `.gitignore` is inherited into
    every scaffold cloned from it, so a fresh clone never even receives the
    marker file to begin with -- a defect one level upstream of the object
    itself, and the reason `IC-D1-MCP`'s "file missing" cases and this
    check's "file present but ignored" cases are worth keeping distinct).

Both checks are per-repo (`Scope.PER_REPO`), fast mode, and read-only: the
first never shells out at all (a plain JSON parse); the second's only
filesystem action is `git check-ignore`, run exclusively through
`fsguard.run_git_readonly` (on the read-only allowlist), never a write.

`run(context)` below implements the `dimensions/__init__.py` module
contract (`DimensionModule`/`RepoContext`, owned by WP-4), which has since
landed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from cc.core.conformance.fsguard import run_git_readonly
from cc.core.conformance.registry import register_check
from cc.core.conformance.types import (
    CheckResult,
    Evidence,
    ExpectedToday,
    Layer,
    Mode,
    Scope,
    Severity,
    Verdict,
)

if TYPE_CHECKING:
    from cc.core.conformance.dimensions import RepoContext

# Retired framework MCP servers (`RUBRIC.md` D10 PARTIAL): replaced by the
# `cc`/`tc` CLIs in v5.0.0. Any project still declaring one is running dead
# config. Kept as a plain data table on purpose -- a future third retirement
# is one line here, never a change to the check logic below.
RETIRED_MCP_SERVERS: frozenset[str] = frozenset(
    {"copilot-memory", "skills-copilot", "task-copilot", "research-copilot"}
)

# Machine-verified today (`RUBRIC.md` D10 / `TEST-MATRIX.md` IC-D10-MCPOBJ):
# these 4 PERSONAL/TSM repos still declare a retired server. Verified live,
# 2026-08-10, by parsing `.mcp.json` in each of `PERSONAL/spanish-copilot`,
# `TSM/clio`, `TSM/Delphi`, `TSM/h3` -- all 4 declare `copilot-memory` and
# `skills-copilot`; `TSM/Delphi` additionally carries 3 legitimate
# third-party servers (`delphi-assistant`, `memory`, `sequential-thinking`)
# that must be preserved, not removed.
KNOWN_RETIRED_SERVER_REPOS: frozenset[str] = frozenset(
    {"spanish-copilot", "clio", "Delphi", "h3"}
)

# Machine-verified today (RC-6 / `HARNESS-DESIGN.md` repo.d10.mcp_json_is_
# committable): every COMPONENT repo whose `.mcp.json` is excluded by an
# inherited `.gitignore` rule. Verified live, 2026-08-10, via
# `git check-ignore -q .mcp.json` against all 16
# `{claude,codex,cli,knowledge}-copilot{,-internal,-accounting,-private}`
# repos -- exactly 12 of the 13 that carry the file are ignored (only
# `knowledge-copilot-internal` tracks it). `codex-copilot`, `cli-copilot`,
# and `cli-copilot-internal` don't carry the file at all today -- that is
# `IC-D1-MCP`'s ABSENT case in `TEST-MATRIX.md`, not this check's business.
KNOWN_MCP_GITIGNORED_REPOS: frozenset[str] = frozenset(
    {
        "claude-copilot",
        "claude-copilot-internal",
        "claude-copilot-accounting",
        "claude-copilot-private",
        "codex-copilot-internal",
        "codex-copilot-accounting",
        "codex-copilot-private",
        "cli-copilot-accounting",
        "cli-copilot-private",
        "knowledge-copilot",
        "knowledge-copilot-accounting",
        "knowledge-copilot-private",
    }
)

_APPLIES_TO = ("A", "B", "C", "D")  # RUBRIC.md D10: "Applies to: A, B, C, D."

_MCP_OBJECT_CHECK = register_check(
    id="repo.d10.mcp_object_no_retired_servers",
    layer=Layer.REPO,
    severity=Severity.S2,
    scope=Scope.PER_REPO,
    summary=(
        ".mcp.json parses with an mcpServers object (empty is correct) and "
        "names no retired Copilot-owned server (copilot-memory, "
        "skills-copilot, task-copilot, research-copilot); third-party "
        "servers are preserved."
    ),
    remediation=(
        "Remove the retired server entry/entries from mcpServers -- the "
        "cc/tc CLIs replace them since v5.0.0. Never touch a legitimate "
        "third-party server (nocodb-mcp, postgresql-mcp, delphi-assistant)."
    ),
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)

_MCP_COMMITTABLE_CHECK = register_check(
    id="repo.d10.mcp_json_is_committable",
    layer=Layer.REPO,
    severity=Severity.S1,
    scope=Scope.PER_REPO,
    summary="No .gitignore rule excludes .mcp.json from version control.",
    remediation=(
        "Remove the .mcp.json exclusion from .gitignore (RC-6) -- a fresh "
        "clone must start with the marker file present, per "
        "claude-copilot's own v5.0.0-era contract that ships an empty "
        "mcpServers object."
    ),
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)


def _expected_today(repo: Path, known_bad: frozenset[str]) -> ExpectedToday:
    return ExpectedToday.FAIL if repo.name in known_bad else ExpectedToday.PASS


def check_mcp_object_no_retired_servers(
    repo: Path,
    *,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    """`repo.d10.mcp_object_no_retired_servers` against one repo."""

    name = subject or str(repo)
    expected = (
        expected_today
        if expected_today is not None
        else _expected_today(repo, KNOWN_RETIRED_SERVER_REPOS)
    )
    mcp_path = repo / ".mcp.json"

    if not mcp_path.is_file():
        return _MCP_OBJECT_CHECK.result(
            subject=name,
            verdict=Verdict.FAIL,
            expected_today=expected,
            evidence=(
                Evidence(
                    kind="mcp-config",
                    path=str(mcp_path),
                    expected="a .mcp.json file with an mcpServers object",
                    actual="file does not exist",
                ),
            ),
        )

    try:
        data = json.loads(mcp_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _MCP_OBJECT_CHECK.result(
            subject=name,
            verdict=Verdict.FAIL,
            expected_today=expected,
            evidence=(
                Evidence(
                    kind="mcp-config",
                    path=str(mcp_path),
                    expected="valid JSON with an mcpServers object",
                    actual=f"failed to parse: {exc}",
                ),
            ),
        )

    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return _MCP_OBJECT_CHECK.result(
            subject=name,
            verdict=Verdict.FAIL,
            expected_today=expected,
            evidence=(
                Evidence(
                    kind="mcp-config",
                    path=str(mcp_path),
                    expected="mcpServers is a JSON object",
                    actual=(
                        f"mcpServers is {type(servers).__name__}"
                        if servers is not None
                        else "mcpServers key is missing"
                    ),
                ),
            ),
        )

    retired_present = sorted(RETIRED_MCP_SERVERS & servers.keys())
    if retired_present:
        return _MCP_OBJECT_CHECK.result(
            subject=name,
            verdict=Verdict.FAIL,
            expected_today=expected,
            evidence=(
                Evidence(
                    kind="mcp-config",
                    path=str(mcp_path),
                    expected="no retired framework server names in mcpServers",
                    actual=f"declares retired server(s): {', '.join(retired_present)}",
                    detail=(
                        "cc workspace verify treats any mcpServers object as "
                        "PRESENT regardless of content -- this is the "
                        "hollow-pass condition RUBRIC.md D10 PARTIAL exists "
                        "to catch"
                    ),
                ),
            ),
        )

    return _MCP_OBJECT_CHECK.result(
        subject=name,
        verdict=Verdict.PASS,
        expected_today=expected,
        detail=(
            f"mcpServers has {len(servers)} legitimate server(s)"
            if servers
            else "mcpServers is the correct empty object"
        ),
    )


def check_mcp_json_is_committable(
    repo: Path,
    *,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    """`repo.d10.mcp_json_is_committable` against one repo (RC-6)."""

    name = subject or str(repo)
    expected = (
        expected_today
        if expected_today is not None
        else _expected_today(repo, KNOWN_MCP_GITIGNORED_REPOS)
    )

    result = run_git_readonly(("check-ignore", "-v", "--", ".mcp.json"), cwd=repo)

    if result.returncode == 1:
        # Not ignored -- the correct state, whether or not the file exists
        # yet (a gitignore rule can pre-emptively block a future commit,
        # which is exactly what RC-6 is -- so this is checked regardless of
        # IC-D1-MCP's separate "does the file exist" question).
        return _MCP_COMMITTABLE_CHECK.result(
            subject=name, verdict=Verdict.PASS, expected_today=expected
        )

    if result.returncode == 0:
        matched = result.stdout.strip()
        return _MCP_COMMITTABLE_CHECK.result(
            subject=name,
            verdict=Verdict.FAIL,
            expected_today=expected,
            evidence=(
                Evidence(
                    kind="gitignore-rule",
                    path=str(repo / ".gitignore"),
                    expected=".mcp.json is not excluded by any .gitignore rule",
                    actual=matched or "matched (no rule detail returned)",
                    detail="RC-6: inherited from claude-copilot's own .gitignore",
                    command="git check-ignore -v -- .mcp.json",
                    output=result.stdout,
                ),
            ),
            root_cause="rc.rc6",
        )

    # Any other exit code (128 = not a git repository, etc.): the harness
    # cannot determine an answer. Never coerced to PASS or FAIL
    # (inv.no_fabricated_healthy).
    return CheckResult(
        id=_MCP_COMMITTABLE_CHECK.id,
        layer=_MCP_COMMITTABLE_CHECK.layer,
        severity=_MCP_COMMITTABLE_CHECK.severity,
        scope=_MCP_COMMITTABLE_CHECK.scope,
        subject=name,
        assertion=_MCP_COMMITTABLE_CHECK.summary,
        verdict=Verdict.COULD_NOT_RUN,
        expected_today=expected,
        detail=f"git check-ignore exited {result.returncode}: {result.stderr.strip()}",
        remediation=_MCP_COMMITTABLE_CHECK.remediation,
    )


def run(context: "RepoContext") -> Iterable[CheckResult]:
    """The `dimensions/__init__.py` module contract's required entry
    point: one `CheckResult` per registered D10 check id, for every repo
    (`Verdict.SKIP` for a class D10 does not apply to)."""

    if context.rubric_class not in _APPLIES_TO:
        detail = (
            f"N/A for class {context.rubric_class} -- D10 applies to classes A/B/C/D."
        )
        return (
            _MCP_OBJECT_CHECK.result(
                subject=context.subject, verdict=Verdict.SKIP, detail=detail
            ),
            _MCP_COMMITTABLE_CHECK.result(
                subject=context.subject, verdict=Verdict.SKIP, detail=detail
            ),
        )
    return (
        check_mcp_object_no_retired_servers(context.path, subject=context.subject),
        check_mcp_json_is_committable(context.path, subject=context.subject),
    )


__all__ = [
    "KNOWN_MCP_GITIGNORED_REPOS",
    "KNOWN_RETIRED_SERVER_REPOS",
    "RETIRED_MCP_SERVERS",
    "check_mcp_json_is_committable",
    "check_mcp_object_no_retired_servers",
    "run",
]
