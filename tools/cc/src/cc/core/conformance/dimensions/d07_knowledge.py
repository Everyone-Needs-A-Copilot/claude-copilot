"""D7 — Knowledge repo wiring.

`RUBRIC.md` §D7 / `HARNESS-DESIGN.md` §4 Layer 3 (`repo.d07.knowledge_wiring_resolves`,
S1, fast, applies to classes A/B/C/D — not E):

  PRESENT — `.claude/cc/config.json` resolves `paths.knowledge_repo` via
  `@machine` to the machine ladder.
  PARTIAL — config present but `CLAUDE.md` references knowledge tooling by
  a hardcoded machine path instead of `$CC_KNOWLEDGE_REPO`/`$CC_SHARED_DOCS`.
  ABSENT — no `paths.knowledge_repo`.

Traced to the CONSUMER, not the producer (per the engineering brief): the
ladder itself (`cc env`'s `CC_KNOWLEDGE_REPOS` vs. the truncated singular
`CC_KNOWLEDGE_REPO` alias, `commands/env.py:116-121`) and the 5 sub-paths
`cw`/`sd`/`ta` dereference are MACHINE-global, per-tier facts —
`TEST-MATRIX.md` H-4/H-5/H-7, `HARNESS-DESIGN.md` Layer 1
(`tier.knowledge.*`, owned by WP-2's `tier.py`, not this module. This
module does not re-derive that ladder-level fact; it stays inside the
per-repo D7 contract RUBRIC.md actually defines, and additionally
implements the ONE per-repo sub-claim the brief calls out that IS a static,
self-contained property of a single repo: "validate knowledge-manifest.json
extensions[] and that requiredSkills resolve." When the SUBJECT repo is
itself a knowledge-tier contributor (i.e. it has its own
`knowledge-manifest.json` — `knowledge-copilot-internal`,
`knowledge-copilot-private`, `knowledge-copilot`, and any future tier
variant), this module verifies, purely from that repo's own files on disk:
every `extensions[].file` exists, every `skills.local[].path` exists, and
every `extensions[].requiredSkills` entry names a skill present in
`skills.local[]`. Verified live on this machine, 2026-08-10: the org
manifest (`knowledge-copilot-internal`) declares 5 extensions with 24 total
`requiredSkills` references across 222 `skills.local` entries, 24/24
resolve, 0 broken paths — the healthy baseline this check exists to keep
green. `knowledge-copilot-accounting` has no manifest at all (a hollow
rung) — that is `TEST-MATRIX.md` H-6/H-7, Layer 1's territory (a
ladder-completeness fact, not a per-repo D7 fact), so this module
correctly does not evaluate it: a repo with no `knowledge-manifest.json`
simply has nothing for the self-validation sub-check to assert about.

Real repos are read-only: no git access is needed for this dimension (pure
filesystem reads of `.claude/cc/config.json`, `CLAUDE.md`, and
`knowledge-manifest.json`).
"""

from __future__ import annotations

import json
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

CC_CONFIG_RELATIVE_PATH = ".claude/cc/config.json"
CLAUDE_MD_RELATIVE_PATH = "CLAUDE.md"
KNOWLEDGE_MANIFEST_RELATIVE_PATH = "knowledge-manifest.json"

# RUBRIC.md D7: "Applies to: A, B, C, D." -- not E.
_APPLIES_TO = ("A", "B", "C", "D")

# Both mount conventions this machine's repos are cited under
# (`TEST-MATRIX.md` IC-D7-HARDCODE: "grep -n '/Volumes/Dev/Sites\\|/Users/pabs/Sites'").
_HARDCODED_PATH_MARKERS: tuple[str, ...] = ("/Volumes/Dev/Sites", "/Users/pabs/Sites")

_D07_REGISTRATION = register_check(
    id="repo.d07.knowledge_wiring_resolves",
    layer=Layer.REPO,
    severity=Severity.S1,
    scope=Scope.PER_REPO,
    summary=(
        "`.claude/cc/config.json` declares `paths.knowledge_repo` (via "
        "`@machine` or a project-relative override); `CLAUDE.md` never "
        "hardcodes an absolute knowledge/shared-docs path; and, when this "
        "repo carries its own `knowledge-manifest.json`, every declared "
        "`extensions[].file` and `skills.local[].path` exists and every "
        "`requiredSkills` entry resolves against `skills.local[]`."
    ),
    remediation=(
        "Run `cc config init --project` (or set `paths.knowledge_repo`); "
        "replace any hardcoded `/Volumes/Dev/Sites`/`/Users/pabs/Sites` "
        "reference in `CLAUDE.md` with `$CC_KNOWLEDGE_REPO`/"
        "`$CC_SHARED_DOCS`; and fix any broken `extensions[].file` or "
        "`skills.local[].path` entry (or unresolved `requiredSkills` name) "
        "in `knowledge-manifest.json`."
    ),
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)


def _read_cc_config_paths(repo: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Read `.claude/cc/config.json`'s `paths` block. Returns
    `(paths_dict_or_None, error_or_None)` — mirrors d05's tolerant
    read-and-report shape without importing d05 (each dimension module
    stays independently self-contained, per the file-ownership boundary
    `HARNESS-DESIGN.md` §9.1 draws between WP-4a/4b/4c)."""

    config_path = repo / CC_CONFIG_RELATIVE_PATH
    if not config_path.is_file():
        return None, "missing"
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"malformed: {exc}"
    if not isinstance(data, dict):
        return None, f"not an object: {type(data).__name__}"
    paths = data.get("paths")
    if not isinstance(paths, dict):
        return None, "no `paths` object"
    return paths, None


def _find_hardcoded_paths(claude_md: Path) -> list[tuple[int, str, str]]:
    """`(line_number, marker, line_text)` for every `CLAUDE.md` line that
    hardcodes an absolute knowledge/shared-docs machine path."""

    hits: list[tuple[int, str, str]] = []
    try:
        lines = claude_md.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return hits
    for line_number, line in enumerate(lines, start=1):
        for marker in _HARDCODED_PATH_MARKERS:
            if marker in line:
                hits.append((line_number, marker, line.strip()))
                break
    return hits


def _validate_knowledge_manifest(repo: Path) -> list[Evidence]:
    """Self-validation of `<repo>/knowledge-manifest.json` (only runs when
    that file exists — i.e. this repo is itself a knowledge-tier
    contributor). Every fact checked is a plain, per-repo, on-disk
    property; no machine-global ladder resolution is involved."""

    evidence: list[Evidence] = []
    manifest_path = repo / KNOWLEDGE_MANIFEST_RELATIVE_PATH
    if not manifest_path.is_file():
        return evidence

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        evidence.append(
            Evidence(
                kind="knowledge-manifest-malformed",
                path=str(manifest_path),
                expected="valid JSON object",
                actual=f"unreadable or malformed: {exc}",
            )
        )
        return evidence

    if not isinstance(manifest, dict):
        evidence.append(
            Evidence(
                kind="knowledge-manifest-malformed",
                path=str(manifest_path),
                expected="a JSON object at the top level",
                actual=type(manifest).__name__,
            )
        )
        return evidence

    skills_block = manifest.get("skills")
    local_skills = skills_block.get("local") if isinstance(skills_block, dict) else None
    local_skills = local_skills if isinstance(local_skills, list) else []
    skills_by_name: dict[str, dict[str, Any]] = {
        entry["name"]: entry
        for entry in local_skills
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }

    for entry in local_skills:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name", "<unnamed>")
        rel_path = entry.get("path")
        if not isinstance(rel_path, str) or not (repo / rel_path).exists():
            evidence.append(
                Evidence(
                    kind="knowledge-manifest-broken-skill-path",
                    path=str(manifest_path),
                    expected=f"skills.local[name={name!r}].path exists on disk",
                    actual=repr(rel_path),
                )
            )

    extensions = manifest.get("extensions")
    extensions = extensions if isinstance(extensions, list) else []
    for entry in extensions:
        if not isinstance(entry, dict):
            continue
        agent = entry.get("agent", "<unknown agent>")
        file_rel = entry.get("file")
        if not isinstance(file_rel, str) or not (repo / file_rel).is_file():
            evidence.append(
                Evidence(
                    kind="knowledge-manifest-broken-extension-file",
                    path=str(manifest_path),
                    expected=f"extensions[agent={agent!r}].file exists on disk",
                    actual=repr(file_rel),
                )
            )
        required_skills = entry.get("requiredSkills") or []
        if not isinstance(required_skills, list):
            continue
        for skill_name in required_skills:
            if not isinstance(skill_name, str):
                continue
            if skill_name not in skills_by_name:
                evidence.append(
                    Evidence(
                        kind="knowledge-manifest-unresolved-required-skill",
                        path=str(manifest_path),
                        expected=(
                            f"requiredSkills entry {skill_name!r} (agent "
                            f"{agent!r}) present in skills.local[]"
                        ),
                        actual="not declared in skills.local[]",
                    )
                )

    return evidence


def check_d07_knowledge_wiring_resolves(
    repo: Path,
    *,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    """Pure function of `repo` to a `CheckResult` — three independent,
    purely-local sub-assertions bundled into one compound verdict, matching
    the compound shape RUBRIC.md's own PRESENT/PARTIAL/ABSENT criteria
    already have for this dimension."""

    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)
    evidence: list[Evidence] = []

    paths, error = _read_cc_config_paths(repo)
    if error is not None:
        evidence.append(
            Evidence(
                kind="knowledge-repo-config",
                path=str(repo / CC_CONFIG_RELATIVE_PATH),
                expected="paths.knowledge_repo resolvable via `.claude/cc/config.json`",
                actual=error,
                detail="RUBRIC.md D7 ABSENT — follows from D5's config being absent/malformed.",
            )
        )
    elif not paths.get("knowledge_repo"):
        evidence.append(
            Evidence(
                kind="knowledge-repo-config",
                path=str(repo / CC_CONFIG_RELATIVE_PATH),
                expected="paths.knowledge_repo set (to `@machine` or a literal override)",
                actual=repr(paths.get("knowledge_repo")),
                detail="RUBRIC.md D7 ABSENT.",
            )
        )

    claude_md = repo / CLAUDE_MD_RELATIVE_PATH
    if claude_md.is_file():
        for line_number, marker, line_text in _find_hardcoded_paths(claude_md):
            evidence.append(
                Evidence(
                    kind="knowledge-claude-md-hardcoded-path",
                    path=f"{claude_md}:{line_number}",
                    expected="$CC_KNOWLEDGE_REPO / $CC_SHARED_DOCS reference",
                    actual=line_text,
                    detail=f"hardcoded absolute machine path via {marker!r}.",
                )
            )

    evidence.extend(_validate_knowledge_manifest(repo))

    verdict = Verdict.FAIL if evidence else Verdict.PASS
    detail = (
        ""
        if verdict is Verdict.PASS
        else f"{len(evidence)} violation(s) of the knowledge-wiring contract."
    )
    return _D07_REGISTRATION.result(
        subject=subject_name,
        verdict=verdict,
        evidence=tuple(evidence),
        detail=detail,
        expected_today=expected_today,
    )


def run(context: "RepoContext") -> Iterable[CheckResult]:
    """The `dimensions/__init__.py` module contract's required entry
    point: exactly one `CheckResult` for `repo.d07.knowledge_wiring_
    resolves`, for every repo (`Verdict.SKIP` for class E)."""

    if context.rubric_class not in _APPLIES_TO:
        return (
            _D07_REGISTRATION.result(
                subject=context.subject,
                verdict=Verdict.SKIP,
                detail=(
                    f"N/A for class {context.rubric_class} -- D7 applies to "
                    "classes A/B/C/D, not E."
                ),
            ),
        )
    return (
        check_d07_knowledge_wiring_resolves(context.path, subject=context.subject),
    )


__all__ = [
    "CC_CONFIG_RELATIVE_PATH",
    "CLAUDE_MD_RELATIVE_PATH",
    "KNOWLEDGE_MANIFEST_RELATIVE_PATH",
    "check_d07_knowledge_wiring_resolves",
    "run",
]
