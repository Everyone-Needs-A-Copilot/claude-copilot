"""D9 — Portable declaration (`copilot.project.json`).

`RUBRIC.md` §D9 / `HARNESS-DESIGN.md` §4 Layer 3 (`repo.d09.portable_declaration`,
S2, fast, applies to classes A/B/C/D — not E):

  PRESENT — file exists, `schema_version == "1.0"`, `components` lists the
  host frameworks the project expects (e.g. `["claude","codex"]`), and
  contains NO repo URLs, org topology, credentials, ranks, or machine
  paths (`workspaces.py`'s module docstring: `copilot.project.json` is
  portable and committed; it declares intent, never machine-local or
  organizational fact).
  PARTIAL — declares a component that is not, in fact, installed
  (`workspaces.py` module docstring: "declaration is explicitly not proof
  of installation" — verified here as a per-repo filesystem proxy, not a
  full `cc workspace verify` cross-check: `claude` implies
  `.claude/agents/` exists; `codex` implies `plugins/codex-copilot/`
  exists), or carries a forbidden field.
  ABSENT — file missing. `TEST-MATRIX.md` §3 `IC-D9-DECLARATION`: present
  in only 9 of 63 repos today — this is the majority-fail dimension in the
  D5-D9 set, unlike D5/D6/D7 which are majority-pass.

Real repos are read-only: pure filesystem reads (JSON parse + two
directory-existence probes), no git access needed for this dimension.
"""

from __future__ import annotations

import json
import re
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

if TYPE_CHECKING:
    from cc.core.conformance.dimensions import RepoContext

# RUBRIC.md D9: "Applies to: A, B, C, D." -- not E.
_APPLIES_TO = ("A", "B", "C", "D")

DECLARATION_RELATIVE_PATH = "copilot.project.json"
EXPECTED_SCHEMA_VERSION = "1.0"

# `workspaces.py`'s docstring forbids repo URLs, org topology, credentials,
# ranks, and machine paths -- a portable declaration is deliberately thin.
_FORBIDDEN_KEY_MARKERS: tuple[str, ...] = (
    "rank",
    "credential",
    "secret",
    "token",
    "password",
    "org",
    "repo_url",
    "repository",
    "url",
    "ssh",
)
_URL_OR_ABSOLUTE_PATH_PATTERN = re.compile(
    r"^(https?://|git@|ssh://|/|~/|/Volumes/|/Users/)"
)

# The filesystem proxy this module uses for "declares what is actually
# installed" (a lightweight, self-contained stand-in for a full `cc
# workspace verify` cross-check -- D1/D2's own install-conformance detail
# is WP-4a's territory, `dimensions/d01_claude.py`/`d02_codex.py`).
_COMPONENT_INSTALL_MARKERS: dict[str, str] = {
    "claude": ".claude/agents",
    "codex": "plugins/codex-copilot",
}

_D09_REGISTRATION = register_check(
    id="repo.d09.portable_declaration",
    layer=Layer.REPO,
    severity=Severity.S2,
    scope=Scope.PER_REPO,
    summary=(
        "`copilot.project.json` exists, `schema_version == \"1.0\"`, "
        "`components` names what is actually installed, and it carries no "
        "repo URLs, org topology, credentials, ranks, or machine paths."
    ),
    remediation=(
        'Add a `copilot.project.json` with `{"schema_version": "1.0", '
        '"components": [...]}` listing exactly the host frameworks '
        "actually installed; never include a repo URL, org name, "
        "credential, rank, or machine path."
    ),
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.FAIL,
)


def _iter_forbidden_field_hits(
    node: Any, prefix: str = ""
) -> list[tuple[str, str]]:
    """`(dotted_key, reason)` for every field that looks like a repo URL,
    org topology, credential, rank, or machine path — `workspaces.py`'s
    forbidden-content list, checked structurally rather than by a single
    hardcoded key name so a differently-spelled violation is still caught."""

    hits: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            dotted_key = f"{prefix}.{key}" if prefix else str(key)
            lowered_key = str(key).lower()
            if any(marker in lowered_key for marker in _FORBIDDEN_KEY_MARKERS):
                hits.append((dotted_key, f"forbidden key name {key!r}"))
            hits.extend(_iter_forbidden_field_hits(value, dotted_key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            hits.extend(_iter_forbidden_field_hits(value, f"{prefix}[{index}]"))
    elif isinstance(node, str):
        if _URL_OR_ABSOLUTE_PATH_PATTERN.match(node):
            hits.append((prefix, f"repo URL or machine path value {node!r}"))
    return hits


def check_d09_portable_declaration(
    repo: Path,
    *,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    """Pure function of `repo` to a `CheckResult`."""

    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)
    declaration_path = repo / DECLARATION_RELATIVE_PATH
    evidence: list[Evidence] = []

    if not declaration_path.is_file():
        evidence.append(
            Evidence(
                kind="declaration-missing",
                path=str(declaration_path),
                expected=f"{DECLARATION_RELATIVE_PATH} present",
                actual="missing",
                detail="RUBRIC.md D9 ABSENT — present in only 9 of 63 repos today.",
            )
        )
        return _D09_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.FAIL,
            evidence=tuple(evidence),
            detail="copilot.project.json is absent.",
            expected_today=expected_today,
        )

    try:
        data = json.loads(declaration_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        evidence.append(
            Evidence(
                kind="declaration-malformed",
                path=str(declaration_path),
                expected="valid JSON object",
                actual=f"unreadable or malformed: {exc}",
            )
        )
        return _D09_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.FAIL,
            evidence=tuple(evidence),
            detail="copilot.project.json is malformed.",
            expected_today=expected_today,
        )

    if not isinstance(data, dict):
        evidence.append(
            Evidence(
                kind="declaration-malformed",
                path=str(declaration_path),
                expected="a JSON object at the top level",
                actual=type(data).__name__,
            )
        )
        data = {}

    schema_version = data.get("schema_version")
    if schema_version != EXPECTED_SCHEMA_VERSION:
        evidence.append(
            Evidence(
                kind="declaration-schema-version",
                path=str(declaration_path),
                expected=f'schema_version == "{EXPECTED_SCHEMA_VERSION}"',
                actual=repr(schema_version),
            )
        )

    components = data.get("components")
    if not isinstance(components, list) or not all(
        isinstance(item, str) for item in components
    ):
        evidence.append(
            Evidence(
                kind="declaration-components",
                path=str(declaration_path),
                expected="components: a list of framework name strings",
                actual=repr(components),
            )
        )
        components = []

    for component in components:
        marker = _COMPONENT_INSTALL_MARKERS.get(component)
        if marker is not None and not (repo / marker).exists():
            evidence.append(
                Evidence(
                    kind="declaration-not-installed",
                    path=str(declaration_path),
                    expected=f"components declares {component!r} only if installed",
                    actual=f"{marker} does not exist",
                    detail=(
                        "workspaces.py: declaration is explicitly not proof "
                        "of installation."
                    ),
                )
            )

    for dotted_key, reason in _iter_forbidden_field_hits(data):
        evidence.append(
            Evidence(
                kind="declaration-forbidden-field",
                path=str(declaration_path),
                expected="no repo URLs, org topology, credentials, ranks, or machine paths",
                actual=f"{dotted_key}: {reason}",
            )
        )

    verdict = Verdict.FAIL if evidence else Verdict.PASS
    detail = (
        ""
        if verdict is Verdict.PASS
        else f"{len(evidence)} violation(s) of the portable-declaration contract."
    )
    return _D09_REGISTRATION.result(
        subject=subject_name,
        verdict=verdict,
        evidence=tuple(evidence),
        detail=detail,
        expected_today=expected_today,
    )


def run(context: "RepoContext") -> Iterable[CheckResult]:
    """The `dimensions/__init__.py` module contract's required entry
    point: exactly one `CheckResult` for `repo.d09.portable_declaration`,
    for every repo (`Verdict.SKIP` for class E)."""

    if context.rubric_class not in _APPLIES_TO:
        return (
            _D09_REGISTRATION.result(
                subject=context.subject,
                verdict=Verdict.SKIP,
                detail=(
                    f"N/A for class {context.rubric_class} -- D9 applies to "
                    "classes A/B/C/D, not E."
                ),
            ),
        )
    return (check_d09_portable_declaration(context.path, subject=context.subject),)


__all__ = [
    "DECLARATION_RELATIVE_PATH",
    "EXPECTED_SCHEMA_VERSION",
    "check_d09_portable_declaration",
    "run",
]
