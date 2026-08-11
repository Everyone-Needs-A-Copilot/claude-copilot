"""Layer 5 — round-trip / end-to-end (`HARNESS-DESIGN.md` §4 Layer 5).

Proves the real installer produces the reference install, and the real
updater is idempotent and destroys nothing project-owned.

**Why this module runs bash, not just Python.** `/setup-project` and
`/update-project` are not Python functions anywhere in this codebase — they
are ```bash fenced code blocks embedded in `.claude/commands/setup-project.md`
/ `update-project.md` that a coding agent reads and executes step by step.
There is no `cc` verb and no library function that performs the mutating
install (`cc.core.ecosystem.project_integration` is exhaustively read-only —
see its own module docstring: "Inspection is read-only"). So "run the real
installer, not a reimplementation" means exactly one thing here: extract the
identical fenced blocks the command file ships and execute them verbatim via
`bash -c`, the same way a coding agent would, with no LLM in the loop. This
is how the design's own root-cause findings were made — "`setup-project.md`
Step 5 copies only 2 files (`setup-project.md` Step 5 is two literal `cp`
lines)" is a fact about the file's *literal bash text*, not an inference —
and it is why `extract_bash_steps`/`run_setup_project`/`run_update_project`
below are marker-based *extraction*, never a rewrite of the steps' logic.
`InstallerScriptError` fires loudly if a heading marker goes missing, exactly
so a future edit to the command files cannot silently stop this module from
testing the real thing.

**What IS new code here** (deliberately — `HARNESS-DESIGN.md` §2.4 lists
"Round-trip (L5)" among the six things nothing verifies today: "nothing
proves `/setup-project` produces the reference install"): the comparison
between what the literal bash produced and the reference install shape, the
degraded-install seeding, and the idempotence/preservation diffing. None of
that is "ecosystem state" `cc` already computes — it is the harness's own
job, per §2.4 point 6.

**Ground truth used throughout** (verified against `VERSION.json` directly,
per `TEST-MATRIX.md`'s own "Ground truth constants" section — not assumed
from `RUBRIC.md`, which has two confirmed errors: `machineCommands` is 6 on
this machine, not the 9 `RUBRIC.md` §D1 states, and the codex plugin tree is
61 files under `plugins/codex-copilot/` + 1 (`scripts/copilot-gate.sh`
outside it) = 62 locked paths total, not "62 files per project").
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from cc.core.conformance.registry import register_check
from cc.core.conformance.types import (
    CheckResult,
    Evidence,
    ExpectedToday,
    Layer,
    Mode,
    Scope,
    Severity,
)

# ---------------------------------------------------------------------------
# Ground truth constants (TEST-MATRIX.md section 5 / "Ground truth constants
# used throughout this matrix", re-verified against VERSION.json in this
# module's own tests rather than hardcoded blindly — these are the FALLBACK
# expectations a check uses when it has no live VERSION.json to read).
# ---------------------------------------------------------------------------

REFERENCE_COMMANDS: tuple[str, ...] = (
    "protocol",
    "continue",
    "pause",
    "map",
    "memory",
    "extensions",
    "orchestrate",
)
SETUP_STAGE_COMMANDS: tuple[str, ...] = ("protocol", "continue")
CLAUDE_MD_HEADING = "## Claude Copilot"
MCP_JSON_REFERENCE: dict[str, Any] = {"mcpServers": {}}
CC_CONFIG_SCHEMA = "cc-config-v1"
CC_CONFIG_SENTINEL_KEYS: tuple[str, ...] = ("shared_docs", "knowledge_repo")
CC_CONFIG_SENTINEL_VALUE = "@machine"

# Verified 2026-08-10: `find plugins/codex-copilot -type f | wc -l` = 61 in
# the real codex-copilot repo; `scripts/copilot-gate.sh` sits outside
# `plugins/` and is the 62nd locked path (TEST-MATRIX.md "Rubric error #2").
CODEX_PLUGIN_FILE_COUNT = 61
CODEX_LOCKED_PATH_COUNT = 62
CODEX_SKILL_BRIDGE_RELATIVE = ".claude/skills/codex-copilot"
CODEX_SKILL_BRIDGE_TARGET = "../../plugins/codex-copilot/skills"

# TEST-MATRIX.md: "MACHINE_COMMANDS (6, not 9 as RUBRIC.md section D1
# states)". Recorded here so a check can assert the rubric error stays
# caught rather than silently re-trusting RUBRIC.md's number.
MACHINE_COMMANDS_GROUND_TRUTH_COUNT = 6
RUBRIC_CLAIMED_MACHINE_COMMANDS_COUNT = 9

OWNER_PROJECT_FRONTMATTER = re.compile(r"^owner:\s*project\s*$", re.MULTILINE)


class InstallerScriptError(RuntimeError):
    """A documented bash step in `setup-project.md` / `update-project.md`
    could not be located or executed. Raised loudly rather than silently
    skipped: the design's own root-cause findings were made by reading these
    exact fenced blocks (see module docstring), so if the command file's
    structure changes, this module must fail — not quietly stop testing the
    real installer and report a false pass."""


class CcBinaryNotFoundError(RuntimeError):
    """No working `cc` executable could be resolved for the round-trip's
    `cc config init --project` / `cc config doctor` steps. This is a
    harness-cannot-run condition (`HARNESS-DESIGN.md` §6.4 exit code 2), not
    a conformance failure — never coerced into a FAIL verdict."""


# ---------------------------------------------------------------------------
# Discovery — never a hardcoded machine path (`inv.no_bare_cli_name` /
# `no-hardcoded-paths.yml` both apply to this module too).
# ---------------------------------------------------------------------------


def discover_framework_repo_root(start: Path | None = None) -> Path:
    """The `claude-copilot` repo root that ships `setup-project.md` /
    `update-project.md` / `VERSION.json` — resolved dynamically via `git
    rev-parse --show-toplevel`, exactly like `test_project_integration.py`'s
    own `project_root()` helper, never a hardcoded absolute path."""

    cwd = start or Path(__file__).resolve().parent
    result = subprocess.run(
        ("git", "rev-parse", "--show-toplevel"),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=10.0,
    )
    if result.returncode != 0:
        raise InstallerScriptError(
            f"git rev-parse --show-toplevel failed from {cwd}: {result.stderr}"
        )
    return Path(result.stdout.strip())


def discover_cc_bin(framework_repo_root: Path) -> Path:
    """The real `cc` executable this round-trip invokes for `cc config
    init --project` / `cc config doctor` (the literal commands
    `setup-project.md` Step 7B and `update-project.md` Step 9B/9C/9D
    document). Prefers the framework repo's own `tools/cc/.venv/bin/cc` (the
    exact code this test suite itself runs under) over a bare `PATH` lookup,
    for the same reason `test_project_integration.py`'s `CC_BIN` seam
    exists: determinism over ambient environment."""

    venv_cc = framework_repo_root / "tools" / "cc" / ".venv" / "bin" / "cc"
    if venv_cc.is_file():
        return venv_cc
    found = shutil.which("cc")
    if found:
        return Path(found)
    raise CcBinaryNotFoundError(
        "no working `cc` executable found -- neither "
        f"{venv_cc} nor a PATH lookup resolved one. The round-trip cannot "
        "run `cc config init --project` without it."
    )


# ---------------------------------------------------------------------------
# Extracting and running the literal installer steps
# ---------------------------------------------------------------------------

_BASH_FENCE = re.compile(r"```bash\n(.*?)```", re.DOTALL)


def _section(markdown: str, start_marker: str, end_marker: str) -> str:
    try:
        start = markdown.index(start_marker)
    except ValueError as exc:
        raise InstallerScriptError(
            f"heading marker {start_marker!r} not found. "
            "setup-project.md/update-project.md's structure has changed -- "
            "update roundtrip.py's extraction markers to match (this error "
            "exists so a drifted marker fails loudly rather than silently "
            "skipping a step)."
        ) from exc
    try:
        end = markdown.index(end_marker, start + len(start_marker))
    except ValueError as exc:
        raise InstallerScriptError(
            f"heading marker {end_marker!r} (end of section starting at "
            f"{start_marker!r}) not found."
        ) from exc
    return markdown[start:end]


def extract_bash_steps(
    markdown: str, sections: Sequence[tuple[str, str]]
) -> tuple[str, ...]:
    """Extract every ```bash fenced block from each `(start_marker,
    end_marker)` section of `markdown`, in document order. This is the
    entirety of this module's "parsing" of the command files — it locates
    the literal text, it does not interpret or rewrite it."""

    blocks: list[str] = []
    for start_marker, end_marker in sections:
        section_text = _section(markdown, start_marker, end_marker)
        blocks.extend(match.group(1) for match in _BASH_FENCE.finditer(section_text))
    return tuple(blocks)


@dataclass(frozen=True)
class StepRun:
    """One executed bash block and its outcome. `command` is kept verbatim
    (whitespace and all) so a failing round-trip's evidence can show a human
    the exact literal script that ran, byte for byte."""

    command: str
    returncode: int
    stdout: str
    stderr: str


def run_bash_steps(
    blocks: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float = 60.0,
) -> tuple[StepRun, ...]:
    """Run each extracted block via `bash -c`, in order, against `cwd`. Does
    NOT abort on a non-zero exit (some documented steps are intentionally
    best-effort, e.g. `cc config doctor`'s warnings) — callers inspect
    `StepRun.returncode` themselves, exactly like `fsguard.run_git_readonly`
    inspects `.returncode` rather than raising on a non-zero exit."""

    runs: list[StepRun] = []
    for block in blocks:
        result = subprocess.run(
            ("bash", "-c", block),
            cwd=cwd,
            env=dict(env),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        runs.append(
            StepRun(
                command=block,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        )
    return tuple(runs)


# `setup-project.md` section markers for the steps that have a filesystem
# effect on the PROJECT directory. Steps 1/1B/2/3 are pure environment
# checks (no project-directory writes); Step 8/9 are interactive
# (AskUserQuestion) with no bash execution; Step 10 (CLAUDE.md creation) is
# prose template substitution, handled separately by `render_claude_md`
# below, not a bash block.
SETUP_PROJECT_SECTIONS: tuple[tuple[str, str], ...] = (
    ("## Step 4: Create Directory Structure", "## Step 5: Copy Project Commands"),
    ("## Step 5: Copy Project Commands", "## Step 6: Copy Agents"),
    ("## Step 6: Copy Agents", "## Step 7: Create .mcp.json"),
    ("## Step 7: Create .mcp.json", "## Step 7B: Initialize cc Project Config"),
    ("## Step 7B: Initialize cc Project Config", "## Step 8: Detect Knowledge"),
)
SETUP_PROJECT_FITNESS_SECTION: tuple[tuple[str, str], ...] = (
    ("## Step 11B: Run Fitness Check", "## Step 12: Report Success"),
)

# `update-project.md` section markers, same rule: Steps 1-5 and 10/10B-11 are
# either read-only or interactive; only 6/7/8/9B/9C have filesystem effects
# on the project. Step 9A (installing `cc` itself if missing) and 9D (`cc
# config doctor`, purely diagnostic) are deliberately excluded — the
# round-trip supplies a working `cc` directly (`discover_cc_bin`) rather than
# exercising 9A's install-from-scratch path, and 9D's warnings are read-only
# by the command file's own design ("continue -- do not stop").
UPDATE_PROJECT_SECTIONS: tuple[tuple[str, str], ...] = (
    ("## Step 6: Update Commands", "## Step 7: Update Agents (Roster-Aware Sync)"),
    (
        "## Step 7: Update Agents (Roster-Aware Sync)",
        "## Step 8: Remove Retired Orchestrator Files (if present)",
    ),
    (
        "## Step 8: Remove Retired Orchestrator Files (if present)",
        "## Step 9: Update cc CLI and Project Config",
    ),
    ("### 9B: Check cc Project Config", "### 9D: Run cc config doctor"),
)
UPDATE_PROJECT_FITNESS_SECTION: tuple[tuple[str, str], ...] = (
    ("## Step 10B: Run Fitness Check", "## Step 11: Report Success"),
)


# ---------------------------------------------------------------------------
# Scratch environment construction
# ---------------------------------------------------------------------------


def materialize_framework_source(dest: Path, framework_repo_root: Path) -> None:
    """Build the `~/.claude/copilot` the documented bash steps expect to
    find, inside `dest` (a `tmp_path` fixture directory) — a SELECTIVE,
    read-only copy of exactly the files `setup-project.md`/
    `update-project.md` reference (never the whole 2GB+ working tree, and
    never a write against `framework_repo_root` itself). This mirrors what a
    real machine's `~/.claude/copilot` checkout provides for these scripts'
    purposes without paying the cost — or carrying the write risk — of a
    full `git clone` of this repo for every test.

    Deliberately includes `.claude/hooks/copilot-hook.sh` even though no
    documented bash step ever copies it anywhere — that omission is exactly
    RC-1's mechanism, and the source having the file while the installer
    never reaches for it is the fact `roundtrip.setup.installs_enforcement_hook`
    exists to catch.
    """

    dest.mkdir(parents=True, exist_ok=True)

    def _copy_file(relative: str) -> None:
        source = framework_repo_root / relative
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    _copy_file("VERSION.json")
    _copy_file("templates/CLAUDE.template.md")
    _copy_file(".claude/fitness-check.sh")
    _copy_file(".claude/hooks/copilot-hook.sh")

    for relative_dir in (".claude/commands", ".claude/agents"):
        source_dir = framework_repo_root / relative_dir
        target_dir = dest / relative_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        for source_file in sorted(source_dir.glob("*.md")):
            shutil.copy2(source_file, target_dir / source_file.name)


def build_scratch_env(
    *,
    home: Path,
    cc_bin: Path,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """The environment every subprocess in this module runs under: `HOME`
    pointed at a `tmp_path` fixture directory (so `~/.claude/copilot`
    expansion in the documented bash resolves inside the sandbox, never the
    real machine), `CC_MACHINE_ROOT`/`XDG_CONFIG_HOME` isolated the same way
    `FleetHandle.env` isolates World-A tests, `PATH` including the resolved
    `cc` binary's directory plus the minimal system tools the documented
    bash needs (`python3`, `git`, coreutils), and `TMPDIR` redirected inside
    `home`'s parent so a stray temp write also lands in the sandbox
    (`HARNESS-DESIGN.md` §5.3 point 2)."""

    scratch_root = home.parent
    return {
        "HOME": str(home),
        "CC_MACHINE_ROOT": str(home / ".claude" / "cc"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "TMPDIR": str(scratch_root),
        "PATH": f"{cc_bin.parent}:/usr/bin:/bin:/usr/local/bin",
        "LANG": "en_US.UTF-8",
        **dict(extra or {}),
    }


def render_claude_md(
    template_path: Path,
    *,
    project_name: str,
    project_description: str = "A scratch conformance-harness project.",
    tech_stack: str = "Other (describe)",
    knowledge_status: str = "Not configured",
    knowledge_name: str = "",
    output_verbosity: str = "concise",
    output_audience: str = "plain",
) -> str:
    """`setup-project.md` Step 10's CLAUDE.md creation is prose ("Read the
    template ... and create CLAUDE.md with: ...."), not a bash block — it is
    still a deterministic, literally-specified substitution (the 7 named
    values Step 10 lists), so replaying it mechanically is running the real
    step, not reimplementing logic. `OUTPUT_VERBOSITY`/`OUTPUT_AUDIENCE`
    default to Step 10's own documented fallbacks (`cc config get
    output.verbosity --raw`, falling back to `concise`/`plain`) — callers
    that actually queried `cc config get` pass the real value through."""

    text = template_path.read_text(encoding="utf-8")
    substitutions = {
        "{{PROJECT_NAME}}": project_name,
        "{{PROJECT_DESCRIPTION}}": project_description,
        "{{TECH_STACK}}": tech_stack,
        "{{KNOWLEDGE_STATUS}}": knowledge_status,
        "{{KNOWLEDGE_NAME}}": knowledge_name,
        "{{OUTPUT_VERBOSITY}}": output_verbosity,
        "{{OUTPUT_AUDIENCE}}": output_audience,
    }
    for token, value in substitutions.items():
        text = text.replace(token, value)
    return text


# ---------------------------------------------------------------------------
# Running the real installer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InstallRun:
    """Everything one `run_setup_project`/`run_update_project` call did, for
    evidence purposes: the literal step runs (in order) and the project
    path they ran against."""

    project: Path
    steps: tuple[StepRun, ...]

    def failed_steps(self) -> tuple[StepRun, ...]:
        return tuple(step for step in self.steps if step.returncode != 0)


def run_setup_project(
    project: Path,
    *,
    framework_repo_root: Path,
    home: Path,
    cc_bin: Path,
    run_fitness_check: bool = True,
) -> InstallRun:
    """Run the literal, filesystem-effecting bash steps of
    `setup-project.md` against `project` (a fresh, empty git repo), plus
    Step 10's CLAUDE.md template substitution. Returns every step's outcome
    so a caller can build FAIL evidence with the exact command that ran."""

    markdown = (
        framework_repo_root / ".claude" / "commands" / "setup-project.md"
    ).read_text(encoding="utf-8")
    env = build_scratch_env(home=home, cc_bin=cc_bin)

    blocks = list(extract_bash_steps(markdown, SETUP_PROJECT_SECTIONS))
    if run_fitness_check:
        blocks.extend(extract_bash_steps(markdown, SETUP_PROJECT_FITNESS_SECTION))
    steps = list(run_bash_steps(blocks, cwd=project, env=env))

    template_path = home / ".claude" / "copilot" / "templates" / "CLAUDE.template.md"
    claude_md = render_claude_md(template_path, project_name=project.name)
    (project / "CLAUDE.md").write_text(claude_md, encoding="utf-8")

    return InstallRun(project=project, steps=tuple(steps))


def run_update_project(
    project: Path,
    *,
    framework_repo_root: Path,
    home: Path,
    cc_bin: Path,
    run_fitness_check: bool = True,
) -> InstallRun:
    """Run the literal, filesystem-effecting bash steps of
    `update-project.md` against an already-set-up `project`."""

    markdown = (
        framework_repo_root / ".claude" / "commands" / "update-project.md"
    ).read_text(encoding="utf-8")
    env = build_scratch_env(home=home, cc_bin=cc_bin)

    blocks = list(extract_bash_steps(markdown, UPDATE_PROJECT_SECTIONS))
    if run_fitness_check:
        blocks.extend(extract_bash_steps(markdown, UPDATE_PROJECT_FITNESS_SECTION))
    steps = run_bash_steps(blocks, cwd=project, env=env)
    return InstallRun(project=project, steps=steps)


def seed_project_owned_agent(
    project: Path,
    *,
    name: str = "my-custom",
    body: str = "Project-specific agent seeded by the conformance harness.",
) -> Path:
    """Write a project-owned agent (`owner: project` frontmatter) — the
    exact shape `update-project.md` Step 7's own preservation guard checks
    for (`grep -q '^owner: project'`), and the shape the owner's ratified
    Q21/Q22 answers protect in 4 real repos (`preflight-copilot`,
    `voice-copilot`, `spanish-copilot`, `small-business-copilot`).
    Returns the written path."""

    target = project / ".claude" / "agents" / f"{name}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"---\nowner: project\nname: {name}\n---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )
    return target


def seed_third_party_mcp_server(
    project: Path, *, name: str = "third-party-example"
) -> None:
    """Write a `.mcp.json` carrying one third-party server — the shape
    `update-project.md`'s own "Unchanged: .mcp.json (any third-party MCP
    servers you added manually are left untouched)" promise makes."""

    payload = {"mcpServers": {name: {"command": "third-party-binary", "args": []}}}
    (project / ".mcp.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Observing a project tree and comparing it to the reference
# ---------------------------------------------------------------------------


def has_owner_project_frontmatter(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return bool(OWNER_PROJECT_FRONTMATTER.search(text))


def observe_install(project: Path) -> dict[str, Any]:
    """Measure exactly what is on disk after a round-trip step, independent
    of any lock or any prior expectation — the harness's own "capability
    census" for Layer 5, analogous to `project_integration._project_capabilities`
    (`EXISTING-VERIFICATION.md` §2: "computed from disk ... independently of
    the lock. It is honest.") but built fresh here per `HARNESS-DESIGN.md`
    §2.4 point 6, since nothing in `cc` observes a round-trip's own scratch
    tree today."""

    def _names(directory: Path) -> tuple[str, ...]:
        if not directory.is_dir():
            return ()
        return tuple(sorted(path.stem for path in directory.glob("*.md")))

    def _is_executable(path: Path) -> bool:
        return path.is_file() and (path.stat().st_mode & 0o111) != 0

    commands_dir = project / ".claude" / "commands"
    agents_dir = project / ".claude" / "agents"
    hook_path = project / ".claude" / "hooks" / "copilot-hook.sh"
    fitness_path = project / ".claude" / "fitness-check.sh"
    mcp_path = project / ".mcp.json"
    cc_config_path = project / ".claude" / "cc" / "config.json"
    claude_md_path = project / "CLAUDE.md"
    memory_gitkeep_path = project / ".claude" / "memory" / "entries" / ".gitkeep"
    lock_path = project / "copilot.lock.json"
    declaration_path = project / "copilot.project.json"
    codex_plugin_dir = project / "plugins" / "codex-copilot"
    skill_bridge_path = project / CODEX_SKILL_BRIDGE_RELATIVE

    mcp_json: dict[str, Any] | None = None
    if mcp_path.is_file():
        try:
            mcp_json = json.loads(mcp_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            mcp_json = None

    cc_config: dict[str, Any] | None = None
    if cc_config_path.is_file():
        try:
            cc_config = json.loads(cc_config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cc_config = None

    claude_md_text = ""
    if claude_md_path.is_file():
        try:
            claude_md_text = claude_md_path.read_text(encoding="utf-8")
        except OSError:
            claude_md_text = ""

    return {
        "command_names": _names(commands_dir),
        "agent_names": _names(agents_dir),
        "hook_present": hook_path.is_file(),
        "hook_executable": _is_executable(hook_path),
        "fitness_check_present": fitness_path.is_file(),
        "fitness_check_executable": _is_executable(fitness_path),
        "mcp_json": mcp_json,
        "cc_config": cc_config,
        "claude_md_has_heading": CLAUDE_MD_HEADING in claude_md_text,
        "memory_gitkeep_present": memory_gitkeep_path.is_file(),
        "lock_present": lock_path.is_file(),
        "declaration_present": declaration_path.is_file(),
        "codex_plugin_file_count": (
            sum(1 for path in codex_plugin_dir.rglob("*") if path.is_file())
            if codex_plugin_dir.is_dir()
            else 0
        ),
        "codex_skill_bridge_present": skill_bridge_path.is_symlink(),
        "codex_skill_bridge_target": (
            str(Path(skill_bridge_path.readlink()))
            if skill_bridge_path.is_symlink()
            else None
        ),
    }


def load_reference_manifest(path: Path) -> dict[str, Any]:
    """Load the checked-in reference-install fixture
    (`tests/conformance/fixtures/reference-install/manifest.json`). Kept as
    a thin, path-agnostic loader — this module never hardcodes the fixture's
    location; the test module (which owns `tests/conformance/fixtures/`)
    supplies the path."""

    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Check registrations — Layer 5
# ---------------------------------------------------------------------------

_PRODUCES_REFERENCE = register_check(
    id="roundtrip.setup.produces_reference_install",
    layer=Layer.ROUNDTRIP,
    severity=Severity.S0,
    scope=Scope.PER_REPO,
    summary=(
        "A fresh `/setup-project` run against an empty scratch repo "
        "produces the reference install exactly: 16 agent files (15 "
        "framework + kc), fitness-check.sh, .claude/hooks/copilot-hook.sh, "
        ".mcp.json, .claude/cc/config.json with the @machine sentinel, "
        "CLAUDE.md with the '## Claude Copilot' heading, "
        ".claude/memory/entries/.gitkeep, a generated copilot.lock.json, and "
        "a portable copilot.project.json declaration "
        "(TEST-MATRIX.md RT-1, RT-4)."
    ),
    remediation=(
        "Each failing facet names its own fix. Commonly: setup-project.md "
        "Step 6's ROSTER loop must append every id "
        "_claude_source_files() (project_integration.py:279) appends -- "
        "'kc' is present only in the loop's dead python3-absent fallback "
        "string, never in the primary VERSION.json-driven path, so a fresh "
        "install ships 15 agent files, not 16. Step 6 never references "
        ".claude/hooks/copilot-hook.sh at all (RC-1). No step anywhere "
        "calls projects.write_project_lock (RC-4)."
    ),
    mode=Mode.FULL,
    expected_today=ExpectedToday.FAIL,
)

_REPORTS_ACCURATELY = register_check(
    id="roundtrip.setup.reports_only_what_it_did",
    layer=Layer.ROUNDTRIP,
    severity=Severity.S1,
    scope=Scope.PER_REPO,
    summary=(
        "The installer's own success-message text must not hardcode a "
        "count that the measured tree can contradict -- e.g. claiming '16 "
        "agent files' unconditionally when the documented roster loop can "
        "produce 15."
    ),
    remediation=(
        "Compute the reported count from the measured roster/command set "
        "at report time instead of a literal string baked into the "
        "success-message template."
    ),
    mode=Mode.FULL,
    # RC-1 fix, re-verified live 2026-08-10: the roster loop now actually
    # produces 16 agent files, so the unconditional "16 agent files" claim
    # in both installers' success text is honest, not a disagreement with
    # the measured roster. `check_reports_only_what_it_did`'s two results
    # never pass an explicit expected_today override, so this registration
    # default is what they both get.
    expected_today=ExpectedToday.PASS,
)

_INSTALLS_HOOK = register_check(
    id="roundtrip.setup.installs_enforcement_hook",
    layer=Layer.ROUNDTRIP,
    severity=Severity.S0,
    scope=Scope.PER_REPO,
    summary=(
        "After `/setup-project` and `/update-project`, "
        ".claude/hooks/copilot-hook.sh exists and is executable "
        "(TEST-MATRIX.md RT-4)."
    ),
    remediation=(
        "RC-1: add a step to setup-project.md/update-project.md that copies "
        "and chmods .claude/hooks/copilot-hook.sh from the framework "
        "source, matching the pattern already used for fitness-check.sh."
    ),
    mode=Mode.FULL,
    expected_today=ExpectedToday.FAIL,
)

_CLOSES_COMMAND_GAP = register_check(
    id="roundtrip.update.closes_command_gap",
    layer=Layer.ROUNDTRIP,
    severity=Severity.S1,
    scope=Scope.PER_REPO,
    summary=(
        "Running `/update-project` immediately after `/setup-project` "
        "closes the command-set gap: exactly the 7 REFERENCE_COMMANDS are "
        "present afterward (TEST-MATRIX.md RT-2)."
    ),
    remediation=(
        "No fix needed while this passes -- update-project.md Step 6 "
        "already copies all 7 project commands. This check exists to catch "
        "a future regression."
    ),
    mode=Mode.FULL,
    expected_today=ExpectedToday.PASS,
)

_UPDATE_IDEMPOTENT = register_check(
    id="roundtrip.update.is_idempotent",
    layer=Layer.ROUNDTRIP,
    severity=Severity.S0,
    scope=Scope.PER_REPO,
    summary=(
        "Running `/update-project` twice in a row produces a byte-identical "
        "tree the second time (excluding volatile machine-local files): "
        "zero files change on the second run (TEST-MATRIX.md RT-3)."
    ),
    remediation=(
        "If this fails: find the step that is not idempotent (a missing "
        "existence guard around an append, e.g. to .gitignore, or a "
        "resource created unconditionally on every run) and add the guard."
    ),
    mode=Mode.FULL,
    # TEST-MATRIX.md RT-3: "UNVERIFIED -- no audit evidence either way ...
    # Treat the first live run as the baseline, not as confirmation of
    # either outcome." expected_today is therefore supplied per-call by the
    # test that performs that first live run, never defaulted here.
)

_PRESERVES_PROJECT_OWNED = register_check(
    id="roundtrip.update.preserves_project_owned",
    layer=Layer.ROUNDTRIP,
    severity=Severity.S0,
    scope=Scope.PER_REPO,
    summary=(
        "A project-owned agent (`owner: project` frontmatter) seeded before "
        "`/update-project` survives the update byte-identical -- the "
        "never-destroy invariant as an executable test, protecting the "
        "owner's ratified Q21/Q22 answers (TEST-MATRIX.md RT-6)."
    ),
    remediation=(
        "update-project.md Step 7's `grep -q '^owner: project'` guard must "
        "run before every agent-roster copy/remove decision, never after."
    ),
    mode=Mode.FULL,
    expected_today=ExpectedToday.PASS,
)

_DOES_NOT_TOUCH_MCP = register_check(
    id="roundtrip.update.does_not_touch_mcp_json",
    layer=Layer.ROUNDTRIP,
    severity=Severity.S1,
    scope=Scope.PER_REPO,
    summary=(
        "A third-party `.mcp.json` server, present before `/update-project` "
        "runs, survives byte-identical (`update-project.md`'s own "
        "'Unchanged: .mcp.json' promise)."
    ),
    remediation=(
        "No step in update-project.md writes .mcp.json today -- if this "
        "ever fails, a future edit added one and must exclude .mcp.json "
        "from its write set."
    ),
    mode=Mode.FULL,
    expected_today=ExpectedToday.PASS,
)

_DEGRADED_DETECTED = register_check(
    id="roundtrip.degraded.detected_not_papered_over",
    layer=Layer.ROUNDTRIP,
    severity=Severity.S0,
    scope=Scope.PER_REPO,
    summary=(
        "Given a reference install degraded exactly as the real fleet is "
        "degraded (missing commands, missing hook, dropped agents, a "
        "foreign lock), the harness's own reference comparison reports "
        "every degradation as a concrete FAIL -- proving detection works, "
        "not just that a clean install can pass."
    ),
    remediation=(
        "N/A -- this check asserts the HARNESS's own detection code path, "
        "not the ecosystem's health. A failure here is a harness bug: fix "
        "observe_install()/the reference comparison in roundtrip.py."
    ),
    mode=Mode.FULL,
    expected_today=ExpectedToday.PASS,
)


# ---------------------------------------------------------------------------
# Check bodies — build CheckResults from measured facts
# ---------------------------------------------------------------------------


def _facet_result(
    registration,
    *,
    subject: str,
    passed: bool,
    kind: str,
    path: str,
    expected: str,
    actual: str,
    detail: str = "",
    expected_today: ExpectedToday | None = None,
    root_cause: str | None = None,
) -> CheckResult:
    from cc.core.conformance.types import Verdict  # local import avoids cycle noise

    if passed:
        return registration.result(
            subject=subject,
            verdict=Verdict.PASS,
            expected_today=expected_today,
            root_cause=root_cause,
        )
    return registration.result(
        subject=subject,
        verdict=Verdict.FAIL,
        evidence=[
            Evidence(
                kind=kind,
                path=path,
                expected=expected,
                actual=actual,
                detail=detail,
            )
        ],
        detail=detail,
        expected_today=expected_today,
        root_cause=root_cause,
    )


def check_produces_reference_install(
    *, project: Path, reference: Mapping[str, Any], subject_prefix: str
) -> tuple[CheckResult, ...]:
    """Compare `observe_install(project)` against the reference manifest,
    facet by facet, per `roundtrip.setup.produces_reference_install`. Every
    disagreement becomes its own FAIL `CheckResult` with concrete evidence —
    "where the installer and the reference disagree, that disagreement IS a
    finding" is implemented literally as one result per facet, never
    collapsed into a single pass/fail bit."""

    observed = observe_install(project)
    claude_ref = reference["claude"]
    codex_ref = reference["codex"]
    results: list[CheckResult] = []

    expected_agents = tuple(sorted(claude_ref["agents"]["names"]))
    results.append(
        _facet_result(
            _PRODUCES_REFERENCE,
            subject=f"{subject_prefix}::agents",
            passed=observed["agent_names"] == expected_agents,
            kind="agent-roster",
            path=".claude/agents/",
            expected=f"{len(expected_agents)} files: {', '.join(expected_agents)}",
            actual=(
                f"{len(observed['agent_names'])} files: "
                f"{', '.join(observed['agent_names']) or '(none)'}"
            ),
            detail=(
                "setup-project.md Step 6's ROSTER loop takes VERSION.json's "
                "frameworkAgents (15 entries, no 'kc') on the primary "
                "python3 code path; 'kc' exists only in the loop's "
                "python3-failed fallback string, which never executes when "
                "python3 is present."
            ),
            # RC-1 fix, re-verified live 2026-08-10: a fresh /setup-project
            # now produces exactly the 16-agent reference roster (including
            # 'kc'). `detail=` above documents the historical defect this
            # facet used to catch; it is only attached to a FAIL result.
            expected_today=ExpectedToday.PASS,
        )
    )

    # Compared against the FULL 7-command reference here (not the 2-command
    # setup-stage subset) because that IS the reference install's shape --
    # setup-project.md's own inability to reach it in one step is exactly
    # HARNESS-DESIGN.md's "Fails today on >=3 counts: setup copies 2
    # commands not 7". The 2-vs-7 gap closing via /update-project is
    # asserted separately by roundtrip.update.closes_command_gap (RT-2).
    expected_commands = tuple(sorted(claude_ref["commands"]["names"]))
    results.append(
        _facet_result(
            _PRODUCES_REFERENCE,
            subject=f"{subject_prefix}::commands",
            passed=observed["command_names"] == expected_commands,
            kind="command-set",
            path=".claude/commands/",
            expected=f"{len(expected_commands)} files: {', '.join(expected_commands)}",
            actual=(
                f"{len(observed['command_names'])} files: "
                f"{', '.join(observed['command_names']) or '(none)'}"
            ),
            detail=(
                "setup-project.md Step 5 copies only protocol.md and "
                "continue.md by design -- the remaining 5 project commands "
                "arrive only via /update-project (see "
                "roundtrip.update.closes_command_gap)."
            ),
            # RC-1 fix, re-verified live 2026-08-10: setup-project.md's
            # Step 5 now copies all 7 project commands directly -- the
            # /update-project-only path `detail=` above describes is
            # historical (only attached to a FAIL result).
            expected_today=ExpectedToday.PASS,
        )
    )

    results.append(
        _facet_result(
            _PRODUCES_REFERENCE,
            subject=f"{subject_prefix}::mcp_json",
            passed=observed["mcp_json"] == claude_ref["mcp_json"],
            kind="project-file",
            path=".mcp.json",
            expected=json.dumps(claude_ref["mcp_json"]),
            actual=json.dumps(observed["mcp_json"]),
            expected_today=ExpectedToday.PASS,
        )
    )

    cc_config_ok = bool(
        observed["cc_config"]
        and observed["cc_config"].get("$schema") == claude_ref["cc_config"]["schema"]
        and all(
            observed["cc_config"].get("paths", {}).get(key) == CC_CONFIG_SENTINEL_VALUE
            for key in CC_CONFIG_SENTINEL_KEYS
        )
    )
    results.append(
        _facet_result(
            _PRODUCES_REFERENCE,
            subject=f"{subject_prefix}::cc_config",
            passed=cc_config_ok,
            kind="project-file",
            path=".claude/cc/config.json",
            expected=f"$schema={claude_ref['cc_config']['schema']}, "
            f"paths.{{{','.join(CC_CONFIG_SENTINEL_KEYS)}}}={CC_CONFIG_SENTINEL_VALUE}",
            actual=json.dumps(observed["cc_config"]),
            expected_today=ExpectedToday.PASS,
        )
    )

    results.append(
        _facet_result(
            _PRODUCES_REFERENCE,
            subject=f"{subject_prefix}::claude_md_heading",
            passed=observed["claude_md_has_heading"],
            kind="project-file",
            path="CLAUDE.md",
            expected=f"contains {CLAUDE_MD_HEADING!r}",
            actual="present" if observed["claude_md_has_heading"] else "missing",
            expected_today=ExpectedToday.PASS,
        )
    )

    results.append(
        _facet_result(
            _PRODUCES_REFERENCE,
            subject=f"{subject_prefix}::fitness_check",
            passed=observed["fitness_check_present"]
            and observed["fitness_check_executable"],
            kind="project-file",
            path=".claude/fitness-check.sh",
            expected="present, executable",
            actual=(
                f"present={observed['fitness_check_present']}, "
                f"executable={observed['fitness_check_executable']}"
            ),
            expected_today=ExpectedToday.PASS,
        )
    )

    results.append(
        _facet_result(
            _PRODUCES_REFERENCE,
            subject=f"{subject_prefix}::hook",
            passed=observed["hook_present"] and observed["hook_executable"],
            kind="project-file",
            path=".claude/hooks/copilot-hook.sh",
            expected="present, executable",
            actual=(
                f"present={observed['hook_present']}, "
                f"executable={observed['hook_executable']}"
            ),
            detail=(
                "RC-1: neither setup-project.md nor update-project.md ever "
                "references .claude/hooks/copilot-hook.sh (see the "
                "dedicated roundtrip.setup.installs_enforcement_hook check "
                "for the same fact as its own registered check, per "
                "HARNESS-DESIGN.md's Layer 5 table listing both)."
            ),
            # RC-1 fix, re-verified live 2026-08-10: setup-project.md now
            # cp's + chmod's the hook and registers it via `cc settings-hook
            # add`. `detail=` above is historical (only attached on FAIL).
            expected_today=ExpectedToday.PASS,
            root_cause="rc.rc1.enforcement_hook_is_installed_by_something",
        )
    )

    results.append(
        _facet_result(
            _PRODUCES_REFERENCE,
            subject=f"{subject_prefix}::memory_gitkeep",
            passed=observed["memory_gitkeep_present"],
            kind="project-file",
            path=".claude/memory/entries/.gitkeep",
            expected="present",
            actual="present" if observed["memory_gitkeep_present"] else "missing",
            expected_today=ExpectedToday.PASS,
        )
    )

    results.append(
        _facet_result(
            _PRODUCES_REFERENCE,
            subject=f"{subject_prefix}::lock",
            passed=observed["lock_present"],
            kind="project-file",
            path="copilot.lock.json",
            expected="present (generated by the installer)",
            actual="present" if observed["lock_present"] else "missing",
            detail=(
                "RC-4: no step in setup-project.md/update-project.md calls "
                "projects.write_project_lock or any other lock generator."
            ),
            # RC-1/RC-4, re-verified live 2026-08-10: setup-project.md's
            # Step 6 `cc settings-hook add` call (added for RC-1) itself
            # writes a genuinely generated copilot.lock.json via the real
            # settings-hook mutation ledger (core/ecosystem/mutations.py) --
            # unique fingerprints/mutation id per project, not a copied
            # template. `detail=` above is historical (only attached on
            # FAIL); the text of setup-project.md/update-project.md still
            # never literally mentions a lock generator (see rc.rc4's own
            # text-grep-based regression pin), but the RUNTIME EFFECT of a
            # step it already runs now produces one.
            expected_today=ExpectedToday.PASS,
        )
    )

    results.append(
        _facet_result(
            _PRODUCES_REFERENCE,
            subject=f"{subject_prefix}::declaration",
            passed=observed["declaration_present"],
            kind="project-file",
            path="copilot.project.json",
            expected="present (generated by the installer)",
            actual="present" if observed["declaration_present"] else "missing",
            detail=(
                "repo.d09.portable_declaration: no step in setup-project.md/"
                "update-project.md ever wrote copilot.project.json, so "
                "every repo the installer touched lacked the declaration "
                "(same shape as RC-1/RC-4 -- a required artifact no "
                "installer installs)."
            ),
            # Fixed alongside repo.d01.documented_commands_exist's own
            # false-failure fix: setup-project.md's Step 6D and
            # update-project.md's Step 7D now write/merge
            # copilot.project.json from what is genuinely installed.
            # `detail=` above is historical (only attached on FAIL).
            expected_today=ExpectedToday.PASS,
        )
    )

    codex_ok = (
        observed["codex_plugin_file_count"] == codex_ref["plugin_file_count"]
        and observed["codex_skill_bridge_present"]
        and observed["codex_skill_bridge_target"] == codex_ref["skill_bridge_target"]
    )
    results.append(
        _facet_result(
            _PRODUCES_REFERENCE,
            subject=f"{subject_prefix}::codex",
            passed=codex_ok,
            kind="codex-plugin-tree",
            path="plugins/codex-copilot/",
            expected=(
                f"{codex_ref['plugin_file_count']} files + skill-bridge "
                f"symlink -> {codex_ref['skill_bridge_target']}"
            ),
            actual=f"{observed['codex_plugin_file_count']} files, "
            f"skill_bridge_present={observed['codex_skill_bridge_present']}",
            detail=(
                "setup-project.md never references plugins/codex-copilot at "
                "all -- the codex half of the reference install is supplied "
                "entirely by codex-copilot/scripts/setup-project.sh, a "
                "separate installer in a separate repo. /setup-project "
                "alone can never reproduce the reference install's codex "
                "component; this is a structural gap distinct from RC-1/"
                "RC-2/RC-4 and is not currently named by any registered "
                "root-cause check."
            ),
            expected_today=ExpectedToday.FAIL,
        )
    )

    return tuple(results)


def check_installs_enforcement_hook(*, project: Path, subject: str) -> CheckResult:
    observed = observe_install(project)
    return _facet_result(
        _INSTALLS_HOOK,
        subject=subject,
        passed=observed["hook_present"] and observed["hook_executable"],
        kind="project-file",
        path=".claude/hooks/copilot-hook.sh",
        expected="present, executable",
        actual=(
            f"present={observed['hook_present']}, "
            f"executable={observed['hook_executable']}"
        ),
        detail=(
            "grep -c copilot-hook setup-project.md update-project.md == 0 "
            "(RC-1) -- confirmed by this round-trip actually running both "
            "documented scripts and finding the file absent."
        ),
        # RC-1 fix, re-verified live 2026-08-10: setup-project.md now
        # installs the hook; `detail=` above is historical (FAIL-only).
        expected_today=ExpectedToday.PASS,
        root_cause="rc.rc1.enforcement_hook_is_installed_by_something",
    )


def check_closes_command_gap(*, project: Path, subject: str) -> CheckResult:
    observed = observe_install(project)
    expected = tuple(sorted(REFERENCE_COMMANDS))
    return _facet_result(
        _CLOSES_COMMAND_GAP,
        subject=subject,
        passed=observed["command_names"] == expected,
        kind="command-set",
        path=".claude/commands/",
        expected=f"{len(expected)} files: {', '.join(expected)}",
        actual=f"{len(observed['command_names'])} files: "
        f"{', '.join(observed['command_names']) or '(none)'}",
    )


def check_reports_only_what_it_did(
    *, framework_repo_root: Path, project: Path, subject: str
) -> tuple[CheckResult, ...]:
    """Static-text scan of the two command files' success-message sections
    for hardcoded count claims, cross-referenced against the measured tree
    this round-trip actually produced (not the audit's paraphrase of an
    earlier reading — the literal current text, re-verified now)."""

    setup_text = (
        framework_repo_root / ".claude" / "commands" / "setup-project.md"
    ).read_text(encoding="utf-8")
    update_text = (
        framework_repo_root / ".claude" / "commands" / "update-project.md"
    ).read_text(encoding="utf-8")
    observed = observe_install(project)
    actual_agent_count = len(observed["agent_names"])

    results: list[CheckResult] = []

    setup_claims_16 = "16 agent files" in setup_text
    results.append(
        _facet_result(
            _REPORTS_ACCURATELY,
            subject=f"{subject}::setup_agent_count_claim",
            passed=not setup_claims_16 or actual_agent_count == 16,
            kind="installer-text",
            path=".claude/commands/setup-project.md",
            expected="claimed agent count matches what Step 6 actually produces",
            actual=f"claims '16 agent files' unconditionally; Step 6 produced "
            f"{actual_agent_count}",
            detail=(
                "setup-project.md lines matching '16 agent files' are a "
                "literal string in the Step 11B verify comment and the "
                "Step 12 success report, not computed from the roster loop's "
                "actual output."
            ),
        )
    )

    update_claims_16 = "16 agent files" in update_text
    results.append(
        _facet_result(
            _REPORTS_ACCURATELY,
            subject=f"{subject}::update_agent_count_claim",
            passed=not update_claims_16 or actual_agent_count == 16,
            kind="installer-text",
            path=".claude/commands/update-project.md",
            expected="claimed agent count matches what Step 7 actually produces",
            actual=f"claims '16 agent files' unconditionally; roster-aware "
            f"sync produced {actual_agent_count} framework-owned agent(s) "
            "(project-owned agents are additional and correctly not "
            "counted in this claim)",
        )
    )

    return tuple(results)


def check_preserves_project_owned(
    *, before: str, after_path: Path, subject: str
) -> CheckResult:
    after_text = (
        after_path.read_text(encoding="utf-8") if after_path.is_file() else None
    )
    survived_unmodified = after_text == before
    return _facet_result(
        _PRESERVES_PROJECT_OWNED,
        subject=subject,
        passed=after_path.is_file() and survived_unmodified,
        kind="project-owned-file",
        path=str(after_path),
        expected="byte-identical to its content before /update-project ran",
        actual=(
            "missing"
            if not after_path.is_file()
            else ("unmodified" if survived_unmodified else "modified")
        ),
    )


def check_does_not_touch_mcp_json(
    *, before: Mapping[str, Any], project: Path, subject: str
) -> CheckResult:
    mcp_path = project / ".mcp.json"
    after: dict[str, Any] | None = None
    if mcp_path.is_file():
        try:
            after = json.loads(mcp_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            after = None
    return _facet_result(
        _DOES_NOT_TOUCH_MCP,
        subject=subject,
        passed=after == dict(before),
        kind="project-file",
        path=".mcp.json",
        expected=json.dumps(dict(before)),
        actual=json.dumps(after),
    )


def check_update_idempotent(
    *, diff_paths: Sequence[str], subject: str, expected_today: ExpectedToday
) -> CheckResult:
    """`diff_paths` is the set of relative paths that differ between the
    first and second `/update-project` run (excluding volatile,
    machine-local files the caller has already filtered out, e.g. any path
    under `.claude/memory/` — pure local cache/index state, not part of the
    installed tree's identity). Empty means byte-identical -- idempotent."""

    return _facet_result(
        _UPDATE_IDEMPOTENT,
        subject=subject,
        passed=not diff_paths,
        kind="tree-diff",
        path=str(sorted(diff_paths)[0]) if diff_paths else "(no diff)",
        expected="0 paths differ between the first and second /update-project run",
        actual=f"{len(diff_paths)} path(s) differ: {', '.join(sorted(diff_paths))}"
        if diff_paths
        else "0 paths differ",
        expected_today=expected_today,
    )


# ---------------------------------------------------------------------------
# Degraded-install fixture support
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DegradationShape:
    """One named, real-world-observed way a fleet install goes bad
    (`HARNESS-DESIGN.md` §5.2: "Named degradations, not ad-hoc edits. Each
    degraded project reproduces a shape actually observed in the audit and
    carries the citing repo in a docstring, so a fixture cannot drift into
    testing an imaginary failure.")."""

    name: str
    description: str
    citing_evidence: str
    remove: tuple[str, ...] = field(default_factory=tuple)
    write: Mapping[str, str] = field(default_factory=dict)


def load_degradation_shapes(path: Path) -> tuple[DegradationShape, ...]:
    """Load named degradation shapes from the checked-in fixture
    (`tests/conformance/fixtures/degraded/known-bad-shapes.json`), owned and
    supplied by the test module — this loader is path-agnostic, matching
    `load_reference_manifest`."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        DegradationShape(
            name=entry["name"],
            description=entry["description"],
            citing_evidence=entry["citing_evidence"],
            remove=tuple(entry.get("remove", ())),
            write=dict(entry.get("write", {})),
        )
        for entry in raw["shapes"]
    )


def apply_degradation(project: Path, shape: DegradationShape) -> tuple[str, ...]:
    """Apply one `DegradationShape` to an already-set-up `project` tree.
    Returns the list of actions actually taken (for evidence)."""

    actions: list[str] = []
    for relative in shape.remove:
        target = project / relative
        if target.is_file() or target.is_symlink():
            target.unlink()
            actions.append(f"removed {relative}")
        elif target.is_dir():
            shutil.rmtree(target)
            actions.append(f"removed directory {relative}")
    for relative, content in shape.write.items():
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        actions.append(f"wrote {relative}")
    return tuple(actions)


def check_degraded_install_detected(
    *,
    project: Path,
    reference: Mapping[str, Any],
    shape: DegradationShape,
    subject_prefix: str,
) -> CheckResult:
    """Assert the harness's own reference comparison reports at least one
    concrete FAIL against a deliberately degraded install — proving
    detection works, not merely that a clean install can pass
    (HARNESS-DESIGN.md §5.2's rationale for real degraded fixtures, applied
    here to the round-trip's own comparison logic rather than to `cc`)."""

    facet_results = check_produces_reference_install(
        project=project,
        reference=reference,
        subject_prefix=f"{subject_prefix}(degraded)",
    )
    from cc.core.conformance.types import Verdict  # local import avoids cycle noise

    failing = [result for result in facet_results if result.verdict is Verdict.FAIL]
    subject = f"{subject_prefix}::{shape.name}"
    if failing:
        return _DEGRADED_DETECTED.result(
            subject=subject,
            verdict=Verdict.PASS,
            detail=(
                f"{shape.description} ({shape.citing_evidence}) -- detected "
                f"as {len(failing)} facet FAIL(s): "
                f"{', '.join(result.subject for result in failing)}"
            ),
        )
    return _DEGRADED_DETECTED.result(
        subject=subject,
        verdict=Verdict.FAIL,
        evidence=[
            Evidence(
                kind="harness-detection-gap",
                path=str(project),
                expected="at least one facet FAIL against the degraded shape",
                actual="0 facet FAILs -- the degradation went undetected",
                detail=f"{shape.description} ({shape.citing_evidence})",
            )
        ],
        detail=(
            "The harness's own reference comparison did not notice this "
            "degradation -- this is a harness bug, not an ecosystem finding."
        ),
    )


__all__ = [
    "CC_CONFIG_SCHEMA",
    "CC_CONFIG_SENTINEL_KEYS",
    "CC_CONFIG_SENTINEL_VALUE",
    "CLAUDE_MD_HEADING",
    "CODEX_LOCKED_PATH_COUNT",
    "CODEX_PLUGIN_FILE_COUNT",
    "CODEX_SKILL_BRIDGE_RELATIVE",
    "CODEX_SKILL_BRIDGE_TARGET",
    "CcBinaryNotFoundError",
    "DegradationShape",
    "InstallRun",
    "InstallerScriptError",
    "MACHINE_COMMANDS_GROUND_TRUTH_COUNT",
    "MCP_JSON_REFERENCE",
    "REFERENCE_COMMANDS",
    "RUBRIC_CLAIMED_MACHINE_COMMANDS_COUNT",
    "SETUP_PROJECT_FITNESS_SECTION",
    "SETUP_PROJECT_SECTIONS",
    "SETUP_STAGE_COMMANDS",
    "StepRun",
    "UPDATE_PROJECT_FITNESS_SECTION",
    "UPDATE_PROJECT_SECTIONS",
    "apply_degradation",
    "build_scratch_env",
    "check_closes_command_gap",
    "check_degraded_install_detected",
    "check_does_not_touch_mcp_json",
    "check_installs_enforcement_hook",
    "check_preserves_project_owned",
    "check_produces_reference_install",
    "check_reports_only_what_it_did",
    "check_update_idempotent",
    "discover_cc_bin",
    "discover_framework_repo_root",
    "extract_bash_steps",
    "has_owner_project_frontmatter",
    "load_degradation_shapes",
    "load_reference_manifest",
    "materialize_framework_source",
    "observe_install",
    "render_claude_md",
    "run_bash_steps",
    "run_setup_project",
    "run_update_project",
    "seed_project_owned_agent",
    "seed_third_party_mcp_server",
]
