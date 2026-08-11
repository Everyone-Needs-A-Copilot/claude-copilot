"""D5 — cc project config (`.claude/cc/config.json`).

`RUBRIC.md` §D5 / `HARNESS-DESIGN.md` §4 Layer 3 (`repo.d05.cc_config_machine_sentinel`,
S1, fast, applies to classes A/B/C/D — not E):

  PRESENT — file exists, `$schema == "cc-config-v1"`, `version == 1`, and
  every value under `paths` is either the literal sentinel `"@machine"` (or
  another `@`-prefixed sentinel form, `core.sentinels.is_sentinel`) or a
  project-relative path — never an absolute machine path.
  PARTIAL — an absolute machine path under `paths`, or malformed JSON.
  ABSENT — no `.claude/cc/config.json`.

`RUBRIC.md`'s own text claims this dimension is "healthy and should be
scored quickly" — verified true for *content* (every config on this machine
that exists uses `@machine` correctly), but the task brief's own tracing
found the rubric's claim of universal health is wrong on a dimension the
rubric text never checked at all: whether the file even SURVIVES a fresh
clone. `convoco-site/.gitignore:53` excludes `.claude/cc/config.json`
outright, so a project can score PRESENT by every RUBRIC.md byte-content
test while still never reaching a second machine or a fresh clone — which
is the exact portability failure D5 exists to catch, one layer up the
stack. This module therefore asserts a THIRD, git-level condition beyond
RUBRIC.md's own two: the config file must not be matched by any
`.gitignore` rule in the subject repo. `cli-copilot` has no cc config at
all (a plain ABSENT case, `TEST-MATRIX.md` §3 `IC-D5-CCCONFIG`) — that is
the rubric's own named failure; the convoco-site self-exclusion is this
module's own additional finding, not weakened to fit the rubric's original
"healthy" framing (`WP1-INTERFACES.md`: "do not weaken an assertion to go
green").

Real repos are read-only: filesystem reads go through plain `pathlib`
(no write-shaped calls are ever made), and the one git operation
(`check-ignore`) goes through `fsguard.run_git_readonly`, the only
sanctioned way a conformance check touches a real repository
(`WP1-INTERFACES.md`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Iterator

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

CC_CONFIG_RELATIVE_PATH = ".claude/cc/config.json"
EXPECTED_SCHEMA = "cc-config-v1"
EXPECTED_VERSION = 1

# RUBRIC.md D5: "Applies to: A, B, C, D." -- not E (not a git root, or an
# `_archive/` descendant, or scratch).
_APPLIES_TO = ("A", "B", "C", "D")

_D05_REGISTRATION = register_check(
    id="repo.d05.cc_config_machine_sentinel",
    layer=Layer.REPO,
    severity=Severity.S1,
    scope=Scope.PER_REPO,
    summary=(
        "`.claude/cc/config.json` exists, matches the `cc-config-v1` "
        "schema, every `paths.*` value is the `@machine` sentinel or a "
        "project-relative path, and the file is not excluded from the "
        "repo's own git history by a `.gitignore` rule."
    ),
    remediation=(
        "Run `cc config init --project`; ensure every `paths.*` value is "
        '`"@machine"` (never an absolute machine path); and remove any '
        "`.gitignore` rule that excludes `.claude/cc/config.json` so the "
        "file survives a fresh clone (see convoco-site's `.gitignore:53`)."
    ),
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)


def _iter_leaf_values(node: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Walk a (possibly nested) config value, yielding `(dotted_key, leaf)`
    pairs for every scalar leaf. Real `paths` blocks are flat, but this
    tolerates nesting rather than assuming the shape."""

    if isinstance(node, dict):
        for key, value in node.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            yield from _iter_leaf_values(value, child_prefix)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _iter_leaf_values(value, f"{prefix}[{index}]")
    else:
        yield (prefix, node)


def _is_absolute_machine_path(value: Any) -> bool:
    """True only for a plain string that is an absolute filesystem path
    (`/...` or `~/...`) — the one shape that breaks portability. Any
    `@`-prefixed sentinel (`@machine`, `@machine:other.key`, `@disabled`,
    `@env:VAR`) and any relative string both pass through unflagged."""

    return isinstance(value, str) and (value.startswith("/") or value.startswith("~"))


def check_d05_cc_config_machine_sentinel(
    repo: Path,
    *,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    """Pure function of `repo` (a repo working directory) to a
    `CheckResult` — no ecosystem state is computed beyond a JSON parse and
    one read-only git plumbing call (Rule 2, `HARNESS-DESIGN.md` §3.2)."""

    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)
    config_path = repo / CC_CONFIG_RELATIVE_PATH
    evidence: list[Evidence] = []

    if not config_path.is_file():
        evidence.append(
            Evidence(
                kind="cc-config-missing",
                path=str(config_path),
                expected=f"{CC_CONFIG_RELATIVE_PATH} present",
                actual="missing",
                detail="RUBRIC.md D5 ABSENT — run `cc config init --project`.",
            )
        )
        return _D05_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.FAIL,
            evidence=tuple(evidence),
            detail="cc project config is absent.",
            expected_today=expected_today,
        )

    try:
        raw_text = config_path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        evidence.append(
            Evidence(
                kind="cc-config-malformed",
                path=str(config_path),
                expected="valid JSON object",
                actual=f"unreadable or malformed: {exc}",
                detail="RUBRIC.md D5 PARTIAL — malformed JSON.",
            )
        )
        return _D05_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.FAIL,
            evidence=tuple(evidence),
            detail="cc project config is malformed.",
            expected_today=expected_today,
        )

    if not isinstance(data, dict):
        evidence.append(
            Evidence(
                kind="cc-config-malformed",
                path=str(config_path),
                expected="a JSON object at the top level",
                actual=f"{type(data).__name__}",
            )
        )
        data = {}

    schema = data.get("$schema")
    if schema != EXPECTED_SCHEMA:
        evidence.append(
            Evidence(
                kind="cc-config-schema",
                path=str(config_path),
                expected=f'$schema == "{EXPECTED_SCHEMA}"',
                actual=repr(schema),
            )
        )

    version = data.get("version")
    if version != EXPECTED_VERSION:
        evidence.append(
            Evidence(
                kind="cc-config-version",
                path=str(config_path),
                expected=f"version == {EXPECTED_VERSION}",
                actual=repr(version),
            )
        )

    paths = data.get("paths")
    if not isinstance(paths, dict):
        evidence.append(
            Evidence(
                kind="cc-config-paths",
                path=str(config_path),
                expected="a `paths` object",
                actual=repr(paths),
            )
        )
    else:
        for dotted_key, value in _iter_leaf_values(paths):
            if _is_absolute_machine_path(value):
                evidence.append(
                    Evidence(
                        kind="cc-config-absolute-path",
                        path=str(config_path),
                        expected='"@machine" or a project-relative path',
                        actual=f"paths.{dotted_key} = {value!r}",
                        detail=(
                            "an absolute machine path breaks portability for "
                            "any second machine or any other user."
                        ),
                    )
                )

    if (repo / ".git").exists():
        ignore_result = run_git_readonly(
            ("check-ignore", "-q", CC_CONFIG_RELATIVE_PATH), cwd=repo
        )
        if ignore_result.returncode == 0:
            verbose = run_git_readonly(
                ("check-ignore", "-v", CC_CONFIG_RELATIVE_PATH), cwd=repo
            )
            evidence.append(
                Evidence(
                    kind="cc-config-gitignore-self-exclusion",
                    path=str(config_path),
                    expected=(
                        f"{CC_CONFIG_RELATIVE_PATH} tracked, matched by no "
                        "`.gitignore` rule"
                    ),
                    actual="matched by a `.gitignore` rule — never reaches a fresh clone",
                    detail=(
                        "e.g. convoco-site's `.gitignore:53` excludes "
                        "`.claude/cc/config.json` entirely, so this file can "
                        "score PRESENT on disk while being invisible to "
                        "`git clone`."
                    ),
                    command=f"git check-ignore -v {CC_CONFIG_RELATIVE_PATH}",
                    output=verbose.stdout.strip(),
                )
            )

    verdict = Verdict.FAIL if evidence else Verdict.PASS
    detail = (
        ""
        if verdict is Verdict.PASS
        else f"{len(evidence)} violation(s) of the cc-config-v1 contract."
    )
    return _D05_REGISTRATION.result(
        subject=subject_name,
        verdict=verdict,
        evidence=tuple(evidence),
        detail=detail,
        expected_today=expected_today,
    )


def run(context: "RepoContext") -> Iterable[CheckResult]:
    """The `dimensions/__init__.py` module contract's required entry
    point: exactly one `CheckResult` for `repo.d05.cc_config_machine_
    sentinel`, for every repo (a `Verdict.SKIP` for class E, never a
    silent omission -- module contract, `dimensions/__init__.py`)."""

    if context.rubric_class not in _APPLIES_TO:
        return (
            _D05_REGISTRATION.result(
                subject=context.subject,
                verdict=Verdict.SKIP,
                detail=(
                    f"N/A for class {context.rubric_class} -- D5 applies to "
                    "classes A/B/C/D, not E."
                ),
            ),
        )
    return (
        check_d05_cc_config_machine_sentinel(context.path, subject=context.subject),
    )


__all__ = [
    "CC_CONFIG_RELATIVE_PATH",
    "EXPECTED_SCHEMA",
    "EXPECTED_VERSION",
    "check_d05_cc_config_machine_sentinel",
    "run",
]
