"""Small public seam for the canonical Claude + Codex project transaction.

The transaction itself is the existing reconciliation pipeline:
``build_plan_report`` issues an identity-bound reviewed plan,
``build_apply_report`` executes it through ``reconciliation_transaction``,
and ``build_verify_report`` independently re-reads disk truth.  This module
does not implement another installer.  It only constructs the closed request
for one project so human-facing setup/update adapters cannot each reinvent
root selection, component ordering, or request serialization.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from cc.core.config import resolve_key
from cc.core.ecosystem.project_locking import inspect_project_identity
from cc.core.ecosystem.reconciliation_types import (
    SUPPORTED_COMPONENTS,
    ReconciliationRequest,
    RequestValidationError,
    parse_reconciliation_request,
)

LEGACY_PROJECT_COMMANDS = ("protocol.md", "continue.md")
SETUP_ONLY_AGENTS = ("kc",)


def claude_reference_roster(
    source: Path | str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the reviewed project command and agent roster from VERSION.json.

    Older framework fixtures and installations predate ``projectCommands``;
    their established two-command contract remains readable for migration.
    Current releases declare the complete roster and are required to provide
    every declared file. ``kc`` remains an intentional setup-only project
    agent and is therefore appended outside ``frameworkAgents``.
    """

    version_path = Path(source) / "VERSION.json"
    try:
        payload = json.loads(version_path.read_text(encoding="utf-8"))
        components = payload["components"]
        commands_value = components.get("commands", {}).get("projectCommands")
        agents_value = components["agents"]["frameworkAgents"]
    except (
        FileNotFoundError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
    ) as exc:
        raise RequestValidationError(
            "The authoritative Claude reference manifest is unavailable."
        ) from exc

    commands = (
        tuple(commands_value) if commands_value is not None else LEGACY_PROJECT_COMMANDS
    )
    agents = (*tuple(agents_value), *SETUP_ONLY_AGENTS)
    if (
        not commands
        or len(commands) != len(set(commands))
        or any(
            not isinstance(name, str)
            or not name.endswith(".md")
            or Path(name).name != name
            for name in commands
        )
        or not agents
        or len(agents) != len(set(agents))
        or any(
            not isinstance(name, str)
            or not name
            or Path(name).name != name
            or "/" in name
            for name in agents
        )
    ):
        raise RequestValidationError(
            "The authoritative Claude reference manifest is invalid."
        )
    return commands, agents


def inspect_canonical_prerequisites(
    *,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    home: Path | None = None,
) -> dict[str, Any]:
    """Report actor-correct CLI prerequisites without changing the machine.

    The banner check prevents macOS' C compiler from being accepted as the
    Copilot ``cc`` CLI. ``tc`` remains required because the reference project
    contract includes durable task and QA evidence even though the file
    transaction itself never shells out to it.
    """

    preferred = (home or Path.home()) / ".local/bin/cc"
    candidates = [which("cc"), str(preferred) if preferred.is_file() else None]
    cc_path: str | None = None
    for candidate in dict.fromkeys(value for value in candidates if value):
        try:
            result = run(
                (str(candidate), "--version"),
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0 and result.stdout.startswith("cc version"):
            cc_path = str(candidate)
            break

    tc_path = which("tc")
    ready = cc_path is not None and tc_path is not None
    return {
        "ready": ready,
        "cc": {
            "state": "ready" if cc_path else "missing-or-wrong-program",
            "path": cc_path,
        },
        "tc": {"state": "ready" if tc_path else "missing", "path": tc_path},
        "responsible_actor": "none" if ready else "person",
        "next_action": (
            "Continue with the canonical project transaction."
            if ready
            else "Complete Claude Copilot machine setup in ~/.claude/copilot with /setup, open a fresh shell, then retry the project transaction."
        ),
    }


def canonical_prerequisites_json() -> str:
    """Return the prerequisite fact as stable machine-readable JSON."""

    return json.dumps(
        inspect_canonical_prerequisites(), sort_keys=True, separators=(",", ":")
    )


def _canonical(path: Path | str) -> Path:
    try:
        return Path(path).expanduser().resolve(strict=True)
    except OSError as exc:
        raise RequestValidationError(
            "The project or approved project folder could not be resolved."
        ) from exc


def _configured_roots() -> tuple[Path, ...]:
    raw: Any = resolve_key("projects.roots")
    values: Iterable[Any]
    if isinstance(raw, list):
        values = raw
    elif isinstance(raw, str) and raw:
        values = (raw,)
    else:
        values = ()
    roots: list[Path] = []
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        try:
            root = _canonical(value)
        except RequestValidationError:
            continue
        if root not in roots:
            roots.append(root)
    return tuple(roots)


def _containing_root(project: Path, roots: Sequence[Path]) -> Path:
    candidates: list[Path] = []
    for root in roots:
        try:
            project.relative_to(root)
        except ValueError:
            continue
        candidates.append(root)
    if not candidates:
        raise RequestValidationError(
            "The project is not inside an approved project folder."
        )
    # The nearest approved boundary is the least authority needed for this
    # transaction and avoids silently widening a one-project request.
    return max(candidates, key=lambda item: len(item.parts))


def build_canonical_project_request(
    project: Path | str,
    *,
    components: Sequence[str] = SUPPORTED_COMPONENTS,
    approved_roots: Sequence[Path | str] | None = None,
) -> ReconciliationRequest:
    """Build the one-project request consumed by plan/apply/verify.

    This is read-only.  It accepts only a real Git worktree root, preserves the
    canonical component order, and selects the nearest configured folder that
    already grants project authority.  Dirty/degraded/customized decisions are
    intentionally left to the reconciliation census, the single source of
    truth that can hold rather than mutate.
    """

    root = _canonical(project)
    identity = inspect_project_identity(root)
    if Path(identity.path) != root:
        raise RequestValidationError("The selected path is not the project root.")

    selected = tuple(
        component for component in SUPPORTED_COMPONENTS if component in components
    )
    if (
        not selected
        or len(components) != len(set(components))
        or any(component not in SUPPORTED_COMPONENTS for component in components)
    ):
        raise RequestValidationError(
            "Select one or both supported components: claude and codex."
        )

    roots = (
        tuple(_canonical(value) for value in approved_roots)
        if approved_roots is not None
        else _configured_roots()
    )
    authority_root = _containing_root(root, roots)
    return parse_reconciliation_request(
        {
            "schema_version": "1.0",
            "roots": [str(authority_root)],
            "projects": [{"path": str(root), "components": list(selected)}],
        }
    )


def canonical_project_request_json(
    project: Path | str,
    *,
    components: Sequence[str] = SUPPORTED_COMPONENTS,
    approved_roots: Sequence[Path | str] | None = None,
) -> str:
    """Canonical JSON adapter payload; no plan, lock, or project is written."""

    request = build_canonical_project_request(
        project,
        components=components,
        approved_roots=approved_roots,
    )
    return json.dumps(request.as_dict(), sort_keys=True, separators=(",", ":"))


__all__ = [
    "build_canonical_project_request",
    "canonical_prerequisites_json",
    "canonical_project_request_json",
    "claude_reference_roster",
    "inspect_canonical_prerequisites",
]
