"""D1 — Claude Copilot framework install conformance.

`RUBRIC.md` §D1 / `HARNESS-DESIGN.md` §4 Layer 3 (`repo.d01.*`, applies to
classes A/B/C/D — not E):

  PRESENT — `.claude/agents/*.md` is exactly the 15 `frameworkAgents` named
  in `VERSION.json` plus `kc.md` (16 files), no retired agent remains, and
  any extra file carries `owner: project` frontmatter; `.claude/commands/*.md`
  is exactly the 7 `projectCommands`; `.claude/fitness-check.sh` exists and
  is executable; `CLAUDE.md` contains the literal heading
  `## Claude Copilot`; `.mcp.json` parses with an `mcpServers` object.
  PARTIAL — 2-command "never updated" installs, 17+ command "whole
  directory copied" over-installs, unowned roster drift, or a `CLAUDE.md`
  missing the heading.
  ABSENT — no `.claude/agents/` and no `.claude/commands/` (the
  `NEW_PROJECT` case both `/setup-project` and `/update-project` test).

Ground truth verified directly against `VERSION.json` on this machine
(2026-08-10), NOT trusted from the rubric prose per `WP1-INTERFACES.md`'s
"trace to the consumer, not the producer" rule:

  - `components.agents.frameworkAgents` has 15 entries; `+kc` (appended by
    the framework's own source resolver,
    `cc.core.ecosystem.project_integration._claude_source_files`) is the
    16-name reference roster this module's `_reference_agents()` computes
    live from the manifest, never a hardcoded list.
  - `components.commands.projectCommands` has exactly 7 entries (with
    `.md` suffixes already).
  - `components.commands.machineCommands` has **6** entries
    (`setup.md`, `setup-project.md`, `update-project.md`,
    `update-copilot.md`, `setup-copilot.md`, `knowledge-copilot.md`) — NOT
    9 as an earlier rubric draft claimed (`TEST-MATRIX.md`: "Rubric error
    #1"). `config.md`, `reflect.md`, `skills-approve.md` exist in
    `claude-copilot/.claude/commands/` but are in *neither* list — they are
    unmanifested, not merely uncounted, and a command file matching
    neither the 7 nor the 6 is reported here as an "unmanifested extra",
    distinct from a "leaked machine command".

This module never hardcodes the roster: every check that needs
`VERSION.json` resolves the framework root the same way
`project_integration._framework_root()` does (`paths.claude_copilot_root`,
overridable per call for the synthetic fleet) and reads the manifest fresh,
so a future framework roster change cannot make this module silently drift
from the contract it is supposed to enforce (`HARNESS-DESIGN.md` §3.2 rule
1: "a check never computes ecosystem state it can ask cc for" — here, "cc"
is the manifest itself, wrapped rather than re-typed).

Real repos are read-only: filesystem reads go through plain `pathlib` (no
write-shaped calls are ever made); `check_d01_fitness_check_passes` is the
one FULL-mode check that shells out, and it runs the repo's OWN
`.claude/fitness-check.sh` (a read-only verification script, per
`EXISTING-VERIFICATION.md` row 16) rather than mutating anything — the
suite's `machine_readonly` tripwire still guards the run end-to-end.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

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
from cc.core.ecosystem.project_integration import _framework_root

if TYPE_CHECKING:
    from cc.core.conformance.dimensions import RepoContext

VERSION_MANIFEST_RELATIVE_PATH = "VERSION.json"
AGENTS_RELATIVE_DIR = ".claude/agents"
COMMANDS_RELATIVE_DIR = ".claude/commands"
FITNESS_CHECK_RELATIVE_PATH = ".claude/fitness-check.sh"
CLAUDE_MD_RELATIVE_PATH = "CLAUDE.md"
MCP_JSON_RELATIVE_PATH = ".mcp.json"
CLAUDE_MD_HEADING = "## Claude Copilot"

_APPLIES_TO = ("A", "B", "C", "D")

_AGENT_COUNT_CLAIM = re.compile(r"(\d+)\s+specialists?", re.IGNORECASE)
_COMMAND_REFERENCE = re.compile(r"`/([a-z][a-z0-9_-]*)`")


# ---------------------------------------------------------------------------
# Manifest helpers — read VERSION.json fresh every call; never hardcode the
# roster this module is verifying against.
# ---------------------------------------------------------------------------


def _load_version_manifest(framework_root: Path) -> dict[str, Any] | None:
    """Read `VERSION.json` at the resolved framework root. Returns `None`
    (never a fabricated empty manifest — `inv.no_fabricated_healthy`) when
    the file is missing, unreadable, or not a JSON object."""

    path = framework_root / VERSION_MANIFEST_RELATIVE_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _reference_agents(manifest: dict[str, Any]) -> frozenset[str] | None:
    try:
        roster = manifest["components"]["agents"]["frameworkAgents"]
    except (KeyError, TypeError):
        return None
    if not isinstance(roster, list) or any(
        not isinstance(name, str) or not name for name in roster
    ):
        return None
    return frozenset({*roster, "kc"})


def _retired_agents(manifest: dict[str, Any]) -> frozenset[str] | None:
    try:
        retired = manifest["components"]["agents"].get("retired", [])
    except (KeyError, TypeError):
        return None
    if not isinstance(retired, list) or any(
        not isinstance(name, str) for name in retired
    ):
        return None
    return frozenset(retired)


def _reference_commands(manifest: dict[str, Any]) -> frozenset[str] | None:
    try:
        commands = manifest["components"]["commands"]["projectCommands"]
    except (KeyError, TypeError):
        return None
    if not isinstance(commands, list) or any(
        not isinstance(name, str) or not name for name in commands
    ):
        return None
    return frozenset(commands)


def _machine_commands(manifest: dict[str, Any]) -> frozenset[str] | None:
    try:
        commands = manifest["components"]["commands"].get("machineCommands", [])
    except (KeyError, TypeError):
        return None
    if not isinstance(commands, list) or any(
        not isinstance(name, str) for name in commands
    ):
        return None
    return frozenset(commands)


def _agent_files(repo: Path) -> dict[str, Path] | None:
    agents_dir = repo / AGENTS_RELATIVE_DIR
    if not agents_dir.is_dir():
        return None
    return {path.stem: path for path in sorted(agents_dir.glob("*.md"))}


def _command_files(repo: Path) -> dict[str, Path] | None:
    commands_dir = repo / COMMANDS_RELATIVE_DIR
    if not commands_dir.is_dir():
        return None
    return {path.name: path for path in sorted(commands_dir.glob("*.md"))}


def _frontmatter_owner(path: Path) -> str | None:
    """Best-effort, never-raising read of a YAML-frontmatter `owner:`
    value. A file with no frontmatter, a malformed block, or an unreadable
    file reports `None` — silence is NOT project ownership
    (`RUBRIC.md` D1 PARTIAL: extras need `owner: project` to be exempt)."""

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    for line in text[3:end].splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == "owner":
            return value.strip().strip('"').strip("'")
    return None


def _missing_framework_root_result(
    registration: Any, subject: str, expected_today: ExpectedToday | None
) -> CheckResult:
    return registration.result(
        subject=subject,
        verdict=Verdict.COULD_NOT_RUN,
        evidence=(
            Evidence(
                kind="framework-root-unresolved",
                path="paths.claude_copilot_root",
                expected="a resolvable claude-copilot checkout",
                actual="unresolved or not a directory",
                detail=(
                    "cannot determine the reference roster without a "
                    "readable framework source; a harness pre-condition "
                    "failure, not a project defect."
                ),
            ),
        ),
        detail="framework root unresolved",
        expected_today=expected_today,
    )


def _unreadable_manifest_result(
    registration: Any,
    subject: str,
    framework_root: Path,
    expected_today: ExpectedToday | None,
) -> CheckResult:
    return registration.result(
        subject=subject,
        verdict=Verdict.COULD_NOT_RUN,
        evidence=(
            Evidence(
                kind="manifest-unreadable",
                path=str(framework_root / VERSION_MANIFEST_RELATIVE_PATH),
                expected="a parseable JSON object with components.agents/.commands",
                actual="missing, unreadable, or malformed",
            ),
        ),
        detail="VERSION.json unreadable or unexpectedly shaped",
        expected_today=expected_today,
    )


# ---------------------------------------------------------------------------
# repo.d01.agent_roster_exact
# ---------------------------------------------------------------------------

_D01_AGENT_ROSTER_REGISTRATION = register_check(
    id="repo.d01.agent_roster_exact",
    layer=Layer.REPO,
    severity=Severity.S1,
    scope=Scope.PER_REPO,
    summary=(
        "TEST-MATRIX.md IC-D1-AGENTS: `.claude/agents/*.md` is exactly "
        "REFERENCE_AGENTS (VERSION.json frameworkAgents + kc, 16 named "
        "files), no retired agent remains, and any extra file carries "
        "`owner: project` frontmatter."
    ),
    remediation=(
        "Run `/update-project` to restore missing framework agents and "
        "remove any remaining retired agent; for a genuinely hand-authored "
        "extra, add `owner: project` to its frontmatter so `/update-project` "
        "preserves it instead of silently overwriting it."
    ),
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.FAIL,
)


def check_d01_agent_roster_exact(
    repo: Path,
    *,
    claude_root: Path | str | None = None,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)
    registration = _D01_AGENT_ROSTER_REGISTRATION

    framework_root = _framework_root("claude", claude_root)
    if framework_root is None:
        return _missing_framework_root_result(registration, subject_name, expected_today)

    manifest = _load_version_manifest(framework_root)
    if manifest is None:
        return _unreadable_manifest_result(
            registration, subject_name, framework_root, expected_today
        )

    reference = _reference_agents(manifest)
    retired = _retired_agents(manifest)
    if reference is None or retired is None:
        return _unreadable_manifest_result(
            registration, subject_name, framework_root, expected_today
        )

    present = _agent_files(repo)
    if present is None:
        return registration.result(
            subject=subject_name,
            verdict=Verdict.FAIL,
            evidence=(
                Evidence(
                    kind="agents-dir-missing",
                    path=AGENTS_RELATIVE_DIR,
                    expected=f"a directory with the {len(reference)} reference agents",
                    actual="missing (NEW_PROJECT / ABSENT)",
                ),
            ),
            detail="no .claude/agents directory",
            expected_today=expected_today,
        )

    present_names = frozenset(present)
    missing = sorted(reference - present_names)
    retired_present = sorted(retired & present_names)
    unowned_extra = sorted(
        name
        for name in present_names - reference - retired
        if _frontmatter_owner(present[name]) != "project"
    )

    evidence: list[Evidence] = []
    for name in missing:
        evidence.append(
            Evidence(
                kind="agent-missing",
                path=f"{AGENTS_RELATIVE_DIR}/{name}.md",
                expected="present",
                actual="missing",
            )
        )
    for name in retired_present:
        evidence.append(
            Evidence(
                kind="agent-retired-present",
                path=f"{AGENTS_RELATIVE_DIR}/{name}.md",
                expected="removed (retired in VERSION.json)",
                actual="present",
            )
        )
    for name in unowned_extra:
        evidence.append(
            Evidence(
                kind="agent-unowned-extra",
                path=f"{AGENTS_RELATIVE_DIR}/{name}.md",
                expected="`owner: project` frontmatter, or removed",
                actual=f"owner={_frontmatter_owner(present[name]) or 'unset'!r}",
            )
        )

    verdict = Verdict.FAIL if evidence else Verdict.PASS
    detail = (
        ""
        if verdict is Verdict.PASS
        else (
            f"{len(present_names & reference)}/{len(reference)} reference "
            f"agents present; missing={missing}; retired_present="
            f"{retired_present}; unowned_extra={unowned_extra}."
        )
    )
    return registration.result(
        subject=subject_name,
        verdict=verdict,
        evidence=tuple(evidence),
        detail=detail,
        expected_today=expected_today,
    )


# ---------------------------------------------------------------------------
# repo.d01.command_set_exact
# ---------------------------------------------------------------------------

_D01_COMMAND_SET_REGISTRATION = register_check(
    id="repo.d01.command_set_exact",
    layer=Layer.REPO,
    severity=Severity.S1,
    scope=Scope.PER_REPO,
    summary=(
        "TEST-MATRIX.md IC-D1-COMMANDS: `.claude/commands/*.md` is exactly "
        "the 7 `projectCommands`, no more, no less — detects both poles of "
        "the machine's bimodal distribution (2-command 'never updated' "
        "installs and 17+-command 'whole directory copied' over-installs "
        "that leak `machineCommands`)."
    ),
    remediation=(
        "Run `/update-project` to install the missing project commands; "
        "remove any `machineCommands` file "
        "(setup.md/setup-project.md/update-project.md/update-copilot.md/"
        "setup-copilot.md/knowledge-copilot.md) or unmanifested extra "
        "(e.g. config.md, reflect.md, skills-approve.md, "
        "setup-knowledge-sync.md) from the project's `.claude/commands/`."
    ),
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.FAIL,
)


def check_d01_command_set_exact(
    repo: Path,
    *,
    claude_root: Path | str | None = None,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)
    registration = _D01_COMMAND_SET_REGISTRATION

    framework_root = _framework_root("claude", claude_root)
    if framework_root is None:
        return _missing_framework_root_result(registration, subject_name, expected_today)

    manifest = _load_version_manifest(framework_root)
    if manifest is None:
        return _unreadable_manifest_result(
            registration, subject_name, framework_root, expected_today
        )

    reference = _reference_commands(manifest)
    machine = _machine_commands(manifest)
    if reference is None or machine is None:
        return _unreadable_manifest_result(
            registration, subject_name, framework_root, expected_today
        )

    present = _command_files(repo)
    if present is None:
        return registration.result(
            subject=subject_name,
            verdict=Verdict.FAIL,
            evidence=(
                Evidence(
                    kind="commands-dir-missing",
                    path=COMMANDS_RELATIVE_DIR,
                    expected=f"a directory with the {len(reference)} project commands",
                    actual="missing (NEW_PROJECT / ABSENT)",
                ),
            ),
            detail="no .claude/commands directory",
            expected_today=expected_today,
        )

    present_names = frozenset(present)
    missing = sorted(reference - present_names)
    leaked_machine = sorted(present_names & machine)
    unmanifested_extra = sorted(present_names - reference - machine)

    evidence: list[Evidence] = []
    for name in missing:
        evidence.append(
            Evidence(
                kind="command-missing",
                path=f"{COMMANDS_RELATIVE_DIR}/{name}",
                expected="present",
                actual="missing",
            )
        )
    for name in leaked_machine:
        evidence.append(
            Evidence(
                kind="command-leaked-machine",
                path=f"{COMMANDS_RELATIVE_DIR}/{name}",
                expected="absent (a machineCommand, not a projectCommand)",
                actual="present",
            )
        )
    for name in unmanifested_extra:
        evidence.append(
            Evidence(
                kind="command-unmanifested-extra",
                path=f"{COMMANDS_RELATIVE_DIR}/{name}",
                expected="absent (named in neither projectCommands nor machineCommands)",
                actual="present",
            )
        )

    verdict = Verdict.FAIL if evidence else Verdict.PASS
    detail = (
        ""
        if verdict is Verdict.PASS
        else (
            f"{len(present_names & reference)}/{len(reference)} project "
            f"commands present; missing={missing}; leaked_machine="
            f"{leaked_machine}; unmanifested_extra={unmanifested_extra}."
        )
    )
    return registration.result(
        subject=subject_name,
        verdict=verdict,
        evidence=tuple(evidence),
        detail=detail,
        expected_today=expected_today,
    )


# ---------------------------------------------------------------------------
# repo.d01.fitness_check_present_executable
# ---------------------------------------------------------------------------

_D01_FITNESS_PRESENT_REGISTRATION = register_check(
    id="repo.d01.fitness_check_present_executable",
    layer=Layer.REPO,
    severity=Severity.S1,
    scope=Scope.PER_REPO,
    summary="`.claude/fitness-check.sh` exists and carries the executable bit.",
    remediation="Run `/update-project` to restore `.claude/fitness-check.sh` (`chmod +x` it if the bit was dropped).",
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)


def check_d01_fitness_check_present_executable(
    repo: Path,
    *,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)
    path = repo / FITNESS_CHECK_RELATIVE_PATH
    exists = path.is_file()
    executable = exists and os.access(path, os.X_OK)

    if exists and executable:
        return _D01_FITNESS_PRESENT_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.PASS,
            detail="",
            expected_today=expected_today,
        )

    actual = "missing" if not exists else "present, not executable"
    return _D01_FITNESS_PRESENT_REGISTRATION.result(
        subject=subject_name,
        verdict=Verdict.FAIL,
        evidence=(
            Evidence(
                kind="fitness-check-missing"
                if not exists
                else "fitness-check-not-executable",
                path=FITNESS_CHECK_RELATIVE_PATH,
                expected="present, executable",
                actual=actual,
            ),
        ),
        detail=actual,
        expected_today=expected_today,
    )


# ---------------------------------------------------------------------------
# repo.d01.claude_md_entry_heading
# ---------------------------------------------------------------------------

_D01_CLAUDE_MD_HEADING_REGISTRATION = register_check(
    id="repo.d01.claude_md_entry_heading",
    layer=Layer.REPO,
    severity=Severity.S1,
    scope=Scope.PER_REPO,
    summary=(
        "TEST-MATRIX.md IC-D1-HEADING: `CLAUDE.md` contains the literal "
        "substring `## Claude Copilot` — the exact test "
        "`project_integration._verify_claude_entry` runs (plain "
        "containment, not a line-anchored heading)."
    ),
    remediation="Run `/update-project`, or add the literal `## Claude Copilot` heading to CLAUDE.md by hand.",
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)


def check_d01_claude_md_entry_heading(
    repo: Path,
    *,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)
    path = repo / CLAUDE_MD_RELATIVE_PATH
    try:
        text: str | None = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = None

    if text is not None and CLAUDE_MD_HEADING in text:
        return _D01_CLAUDE_MD_HEADING_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.PASS,
            detail="",
            expected_today=expected_today,
        )

    actual = "missing" if text is None else "heading not found"
    return _D01_CLAUDE_MD_HEADING_REGISTRATION.result(
        subject=subject_name,
        verdict=Verdict.FAIL,
        evidence=(
            Evidence(
                kind="claude-md-heading-missing",
                path=CLAUDE_MD_RELATIVE_PATH,
                expected=f"contains the literal heading {CLAUDE_MD_HEADING!r}",
                actual=actual,
            ),
        ),
        detail=actual,
        expected_today=expected_today,
    )


# ---------------------------------------------------------------------------
# repo.d01.claude_md_agent_count_accurate
# ---------------------------------------------------------------------------

_D01_AGENT_COUNT_REGISTRATION = register_check(
    id="repo.d01.claude_md_agent_count_accurate",
    layer=Layer.REPO,
    severity=Severity.S3,
    scope=Scope.PER_REPO,
    summary=(
        "Any `<N> specialist(s)` claim in CLAUDE.md matches the actual "
        "on-disk `.claude/agents/*.md` count. Named failures found on this "
        "machine: `admin-server` claims 21, five repos claim 11, "
        "`product-creation-copilot` claims 14 — all should be 16."
    ),
    remediation="Correct the specialist-count prose in CLAUDE.md to match `.claude/agents/*.md`'s actual count.",
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)


def check_d01_claude_md_agent_count_accurate(
    repo: Path,
    *,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)
    path = repo / CLAUDE_MD_RELATIVE_PATH
    try:
        text: str | None = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = None

    if text is None:
        return _D01_AGENT_COUNT_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.SKIP,
            detail="no CLAUDE.md to check",
            expected_today=expected_today,
        )

    claims = sorted({int(match.group(1)) for match in _AGENT_COUNT_CLAIM.finditer(text)})
    if not claims:
        return _D01_AGENT_COUNT_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.SKIP,
            detail="no '<N> specialist(s)' claim found in CLAUDE.md",
            expected_today=expected_today,
        )

    present = _agent_files(repo)
    actual_count = len(present) if present is not None else 0
    wrong = [claim for claim in claims if claim != actual_count]
    if not wrong:
        return _D01_AGENT_COUNT_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.PASS,
            detail=f"claimed count(s) {claims} match actual {actual_count}",
            expected_today=expected_today,
        )

    evidence = tuple(
        Evidence(
            kind="claude-md-count-mismatch",
            path=CLAUDE_MD_RELATIVE_PATH,
            expected=f"{actual_count} (actual .claude/agents/*.md count)",
            actual=str(claim),
        )
        for claim in wrong
    )
    return _D01_AGENT_COUNT_REGISTRATION.result(
        subject=subject_name,
        verdict=Verdict.FAIL,
        evidence=evidence,
        detail=f"CLAUDE.md claims {wrong}; actual on-disk roster is {actual_count}.",
        expected_today=expected_today,
    )


# ---------------------------------------------------------------------------
# repo.d01.documented_commands_exist
# ---------------------------------------------------------------------------

_D01_DOCUMENTED_COMMANDS_REGISTRATION = register_check(
    id="repo.d01.documented_commands_exist",
    layer=Layer.REPO,
    severity=Severity.S2,
    scope=Scope.PER_REPO,
    summary=(
        "Every `` `/command` `` reference in CLAUDE.md names a command "
        "that actually exists in `.claude/commands/`. Named failure: "
        "`research-copilot` documents 4 that do not exist."
    ),
    remediation="Remove or correct the stale command reference(s) in CLAUDE.md, or restore the missing command file(s) via `/update-project`.",
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)


def check_d01_documented_commands_exist(
    repo: Path,
    *,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)
    path = repo / CLAUDE_MD_RELATIVE_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = None

    if not text:
        return _D01_DOCUMENTED_COMMANDS_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.SKIP,
            detail="no CLAUDE.md to check",
            expected_today=expected_today,
        )

    named = sorted({match.group(1) for match in _COMMAND_REFERENCE.finditer(text)})
    if not named:
        return _D01_DOCUMENTED_COMMANDS_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.SKIP,
            detail="no `` `/command` `` references found in CLAUDE.md",
            expected_today=expected_today,
        )

    commands_dir = repo / COMMANDS_RELATIVE_DIR
    missing = [name for name in named if not (commands_dir / f"{name}.md").is_file()]
    if not missing:
        return _D01_DOCUMENTED_COMMANDS_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.PASS,
            detail=f"all {len(named)} documented command(s) exist on disk",
            expected_today=expected_today,
        )

    evidence = tuple(
        Evidence(
            kind="documented-command-missing",
            path=f"{COMMANDS_RELATIVE_DIR}/{name}.md",
            expected="present (referenced by CLAUDE.md)",
            actual="missing",
        )
        for name in missing
    )
    return _D01_DOCUMENTED_COMMANDS_REGISTRATION.result(
        subject=subject_name,
        verdict=Verdict.FAIL,
        evidence=evidence,
        detail=f"CLAUDE.md references {len(missing)} command(s) that do not exist: {missing}.",
        expected_today=expected_today,
    )


# ---------------------------------------------------------------------------
# repo.d01.mcp_json_is_object
#
# TEST-MATRIX.md IC-D1-MCP is the structural half of RUBRIC.md's D1 PRESENT
# criterion ("`.mcp.json` parses and contains an `mcpServers` object"); the
# content-level half (no retired MCP servers, `.gitignore` committability)
# is a distinct D10 concern owned by a sibling module
# (`dimensions/d10_mcp.py`) and registered under a distinct id
# (`repo.d10.*`) — the two never collide.
# ---------------------------------------------------------------------------

_D01_MCP_JSON_REGISTRATION = register_check(
    id="repo.d01.mcp_json_is_object",
    layer=Layer.REPO,
    severity=Severity.S2,
    scope=Scope.PER_REPO,
    summary="TEST-MATRIX.md IC-D1-MCP: `.mcp.json` parses and `mcpServers` is a JSON object (an empty object is correct since v5.0.0).",
    remediation="Restore `.mcp.json` with at least `{\"mcpServers\": {}}` (or run `/update-project`, which does not touch an existing valid `.mcp.json`).",
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)


def check_d01_mcp_json_is_object(
    repo: Path,
    *,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)
    path = repo / MCP_JSON_RELATIVE_PATH

    if not path.is_file():
        return _D01_MCP_JSON_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.FAIL,
            evidence=(
                Evidence(
                    kind="mcp-json-missing",
                    path=MCP_JSON_RELATIVE_PATH,
                    expected="present, mcpServers object",
                    actual="missing",
                ),
            ),
            detail="missing",
            expected_today=expected_today,
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _D01_MCP_JSON_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.FAIL,
            evidence=(
                Evidence(
                    kind="mcp-json-malformed",
                    path=MCP_JSON_RELATIVE_PATH,
                    expected="valid JSON",
                    actual=f"unreadable/malformed: {exc}",
                ),
            ),
            detail="unreadable or malformed JSON",
            expected_today=expected_today,
        )

    servers = raw.get("mcpServers") if isinstance(raw, dict) else None
    if isinstance(servers, dict):
        return _D01_MCP_JSON_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.PASS,
            detail=f"mcpServers object with {len(servers)} entrie(s)",
            expected_today=expected_today,
        )

    actual = f"mcpServers is {type(servers).__name__}" if servers is not None else "mcpServers is absent"
    return _D01_MCP_JSON_REGISTRATION.result(
        subject=subject_name,
        verdict=Verdict.FAIL,
        evidence=(
            Evidence(
                kind="mcp-json-not-object",
                path=MCP_JSON_RELATIVE_PATH,
                expected="mcpServers is a JSON object",
                actual=actual,
            ),
        ),
        detail=actual,
        expected_today=expected_today,
    )


# ---------------------------------------------------------------------------
# repo.d01.fitness_check_passes (FULL mode — wraps FF1-FF11, never
# reimplements them; EXISTING-VERIFICATION.md row 16, HARNESS-DESIGN.md §2.1)
# ---------------------------------------------------------------------------

_D01_FITNESS_PASSES_REGISTRATION = register_check(
    id="repo.d01.fitness_check_passes",
    layer=Layer.REPO,
    severity=Severity.S1,
    scope=Scope.PER_REPO,
    summary="`bash .claude/fitness-check.sh` exits 0 (FF1-FF11: roster/manifest parity, retired-agent absence, frontmatter conformance, no dead skill refs, etc.) — wrapped, never re-implemented.",
    remediation="Run the repo's own `.claude/fitness-check.sh` locally and follow its `FAIL ` lines; each FFn is documented in `claude-copilot/.claude/fitness-check.sh`.",
    mode=Mode.FULL,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)


def check_d01_fitness_check_passes(
    repo: Path,
    *,
    timeout: float = 60.0,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)
    path = repo / FITNESS_CHECK_RELATIVE_PATH

    if not path.is_file() or not os.access(path, os.X_OK):
        return _D01_FITNESS_PASSES_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.COULD_NOT_RUN,
            evidence=(
                Evidence(
                    kind="fitness-check-unavailable",
                    path=FITNESS_CHECK_RELATIVE_PATH,
                    expected="present, executable",
                    actual="missing or not executable",
                ),
            ),
            detail="cannot run FF1-FF11: script absent or not executable",
            expected_today=expected_today,
        )

    try:
        result = subprocess.run(
            ["bash", str(path)],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _D01_FITNESS_PASSES_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.COULD_NOT_RUN,
            evidence=(
                Evidence(
                    kind="fitness-check-execution-error",
                    path=FITNESS_CHECK_RELATIVE_PATH,
                    expected="exits 0/1 within the timeout",
                    actual=f"execution failed: {exc}",
                ),
            ),
            detail="subprocess failure",
            expected_today=expected_today,
        )

    if result.returncode == 0:
        return _D01_FITNESS_PASSES_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.PASS,
            detail="fitness-check.sh exited 0 (FF1-FF11)",
            expected_today=expected_today,
        )

    fail_lines = [line for line in result.stdout.splitlines() if line.startswith("FAIL ")]
    evidence = tuple(
        Evidence(
            kind="fitness-check-failure",
            path=FITNESS_CHECK_RELATIVE_PATH,
            expected="FF1-FF11 all PASS",
            actual=line,
        )
        for line in (fail_lines or [f"exit code {result.returncode}"])
    )
    tail = "\n".join(result.stdout.splitlines()[-15:])
    return _D01_FITNESS_PASSES_REGISTRATION.result(
        subject=subject_name,
        verdict=Verdict.FAIL,
        evidence=evidence,
        detail=f"fitness-check.sh exited {result.returncode}: {tail}",
        expected_today=expected_today,
    )


# Every registration this module owns, in the order `run()` evaluates them
# -- used only for the class-SKIP branch (`dimensions/__init__.py`'s
# contract: "a Verdict.SKIP result (never a silent omission) for any check
# whose applies_to_classes excludes context.rubric_class").
_D01_REGISTRATIONS: tuple[Any, ...] = (
    _D01_AGENT_ROSTER_REGISTRATION,
    _D01_COMMAND_SET_REGISTRATION,
    _D01_FITNESS_PRESENT_REGISTRATION,
    _D01_CLAUDE_MD_HEADING_REGISTRATION,
    _D01_AGENT_COUNT_REGISTRATION,
    _D01_DOCUMENTED_COMMANDS_REGISTRATION,
    _D01_MCP_JSON_REGISTRATION,
    _D01_FITNESS_PASSES_REGISTRATION,
)


def run(context: "RepoContext") -> Iterable[CheckResult]:
    """The `dimensions/__init__.py` module contract's required entry
    point: one `CheckResult` per check id this module registered, for
    every repo -- a `Verdict.SKIP` for class E (D1 applies to A/B/C/D
    only), and a `Verdict.SKIP` for `repo.d01.fitness_check_passes` in
    fast mode (FULL-mode only work sweep.py did not ask for)."""

    if context.rubric_class not in _APPLIES_TO:
        skip_detail = f"N/A for class {context.rubric_class} -- D1 applies to classes A/B/C/D, not E."
        return tuple(
            registration.result(
                subject=context.subject, verdict=Verdict.SKIP, detail=skip_detail
            )
            for registration in _D01_REGISTRATIONS
        )

    results: list[CheckResult] = [
        check_d01_agent_roster_exact(context.path, subject=context.subject),
        check_d01_command_set_exact(context.path, subject=context.subject),
        check_d01_fitness_check_present_executable(context.path, subject=context.subject),
        check_d01_claude_md_entry_heading(context.path, subject=context.subject),
        check_d01_claude_md_agent_count_accurate(context.path, subject=context.subject),
        check_d01_documented_commands_exist(context.path, subject=context.subject),
        check_d01_mcp_json_is_object(context.path, subject=context.subject),
    ]
    if context.mode is Mode.FULL:
        results.append(
            check_d01_fitness_check_passes(context.path, subject=context.subject)
        )
    else:
        results.append(
            _D01_FITNESS_PASSES_REGISTRATION.result(
                subject=context.subject,
                verdict=Verdict.SKIP,
                detail="FULL-mode only check skipped in fast mode",
            )
        )
    return tuple(results)


__all__ = [
    "AGENTS_RELATIVE_DIR",
    "CLAUDE_MD_HEADING",
    "CLAUDE_MD_RELATIVE_PATH",
    "COMMANDS_RELATIVE_DIR",
    "FITNESS_CHECK_RELATIVE_PATH",
    "MCP_JSON_RELATIVE_PATH",
    "VERSION_MANIFEST_RELATIVE_PATH",
    "check_d01_agent_roster_exact",
    "check_d01_claude_md_agent_count_accurate",
    "check_d01_claude_md_entry_heading",
    "check_d01_command_set_exact",
    "check_d01_documented_commands_exist",
    "check_d01_fitness_check_passes",
    "check_d01_fitness_check_present_executable",
    "check_d01_mcp_json_is_object",
    "run",
]
