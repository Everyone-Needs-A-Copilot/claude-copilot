"""Skill store: discovery, parsing, and retrieval of SKILL.md files.

Skills are markdown files with YAML frontmatter. The canonical frontmatter
fields are: name, description, tags, version. Additional fields (e.g.
skill_name, skill_category, and WP-372 P2.2's `triggers` routing block)
are tolerated and stored under 'extra' -- this module never curates which
frontmatter fields are "useful"; it surfaces everything declared and lets
the caller (an agent, via `cc skill list --json`) decide (parse, never
compute).

Resolution order (first match wins): project → machine → knowledge
(WP-372 P2.2 added the third tier -- every configured `paths.knowledge_repo`
entry's `03-ai-enabling/01-skills/` tree, the canonical sub-path
knowledge-copilot's own consumption contract names) → framework.
"""

from __future__ import annotations

import datetime as _datetime
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    import yaml as _yaml  # type: ignore[import]

    _YAML_AVAILABLE = True
except ImportError:  # pragma: no cover
    _YAML_AVAILABLE = False

_log = logging.getLogger(__name__)

# WP-372 P2.2: the canonical sub-path knowledge-copilot's own consumption
# contract names for skills (knowledge-copilot/docs/00-knowledge-copilot/
# 02-consumption-contract.md: "AI skills & profiles | 03-ai-enabling/ |
# 01-skills/, 02-profiles/") -- verified live against the real
# ~280-file skill tree under `03-ai-enabling/01-skills/` in this
# machine's configured knowledge repo(s).
_KNOWLEDGE_SKILLS_SUBPATH = "03-ai-enabling/01-skills"


@dataclass
class SkillMeta:
    """Parsed metadata for a single SKILL.md file."""

    name: str
    description: str
    path: Path
    tags: list[str] = field(default_factory=list)
    version: str = ""
    source: str = ""  # "project" | "machine" | "framework"
    extra: dict[str, Any] = field(default_factory=dict)
    _knowledge_source: Any = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class SkillContent:
    content: str
    receipt: Any = None

    @property
    def is_authenticated(self) -> bool:
        return self.receipt is not None and bool(self.receipt.is_authenticated)


def _git_root() -> Path | None:
    """Return the git repository root, or None if not inside a repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def knowledge_skill_paths() -> list[Path]:
    """
    Every configured `paths.knowledge_repo` entry's skill tree (WP-372
    P2.2) -- `03-ai-enabling/01-skills/`, the canonical sub-path the
    knowledge repo's own consumption contract names.

    Uses `resolve_knowledge_repos()` (core/config.py) -- the FULL ordered
    list, not the single-entry `CC_KNOWLEDGE_REPO` env alias WP-372's case
    3 found silently truncated to one entry -- so a configured PERSONAL
    knowledge repo's skill tree is just as discoverable as the org's.

    Entries with no `01-skills/` subtree on disk (or no
    `paths.knowledge_repo` configured at all) contribute nothing -- same
    "absent is a valid machine state" fail-open posture every other
    config-driven path in this codebase uses; never raises.
    """
    from cc.core.ecosystem.knowledge_skill_source import (
        resolve_knowledge_skill_sources,
    )

    return [path for path, _source in resolve_knowledge_skill_sources()]


def default_skill_paths() -> list[tuple[Path, str]]:
    """Return the default skill search paths with their source labels.

    Resolution order: project → machine → knowledge.
    Returns a list of (path, source_label) tuples.
    """
    paths: list[tuple[Path, str]] = []

    # Project skills: <git root>/.claude/skills/
    repo = _git_root()
    if repo is not None:
        project_skills = repo / ".claude" / "skills"
        if project_skills.exists():
            paths.append((project_skills, "project"))

    # Machine skills: ~/.claude/skills/
    machine_skills = Path.home() / ".claude" / "skills"
    if machine_skills.exists():
        paths.append((machine_skills, "machine"))

    # Knowledge skills: every configured paths.knowledge_repo entry's
    # 03-ai-enabling/01-skills/ tree (WP-372 P2.2).
    for skills_dir in knowledge_skill_paths():
        paths.append((skills_dir, "knowledge"))

    return paths


def _resolve_block_scalar(
    lines: list[str], start: int, indicator: str = ">-"
) -> tuple[str, int]:
    """Resolve a YAML block scalar starting at *start* (the line containing >- or |).

    *indicator* is the block scalar indicator string (">-", ">", "|-", or "|").

    Returns (resolved_string, next_line_index). The resolved string has leading/
    trailing whitespace stripped. Continuation lines are joined with a space
    (folded, >-) or newlines (literal, |).
    """
    # Determine fold vs literal and chomp style
    # We treat >- / > as folded (join with space, strip trailing newlines)
    # and | / |- as literal (preserve newlines)
    folded = indicator.startswith(">")

    # Detect the indentation of the next non-empty continuation line
    i = start + 1
    # Skip blank lines immediately after the indicator to find indent level
    while i < len(lines) and lines[i].strip() == "":
        i += 1

    if i >= len(lines):
        return "", i

    indent = len(lines[i]) - len(lines[i].lstrip())
    parts: list[str] = []

    while i < len(lines):
        line = lines[i]
        if line.strip() == "":
            parts.append("")
            i += 1
            continue
        current_indent = len(line) - len(line.lstrip())
        if current_indent < indent:
            # De-dented back to parent — end of block scalar
            break
        parts.append(line[indent:].rstrip())
        i += 1

    # Remove trailing empty strings (strip chomp for >- and |-)
    while parts and parts[-1] == "":
        parts.pop()

    if folded:
        resolved = " ".join(p for p in parts if p)
    else:
        resolved = "\n".join(parts)

    return resolved, i


def _json_safe(value: Any) -> Any:
    """
    Recursively coerce YAML-native scalar types `yaml.safe_load()` produces
    but `json.dumps()` cannot serialize -- `datetime.date`/`datetime.
    datetime` (an UNQUOTED `last_updated: 2026-02-25`-style frontmatter
    value parses as a real `date` object, not a string) -- into their ISO
    string form.

    WP-372 P2.2, found live: the knowledge repo's real SKILL.md corpus
    frontmatter includes `last_updated: <unquoted date>` on nearly every
    file, and this module's `extra` dict (surfaced verbatim in `cc skill
    list --json`) previously passed that raw `date` object straight
    through, crashing `json.dumps()` the first time a knowledge-repo skill
    was listed. Mirrors the existing defensive-cast precedent this module
    already applies to `version` (`str(fm.get("version", ""))`, guarding
    against YAML auto-typing `version: 1.0` as a float) -- generalized
    here to the whole frontmatter dict rather than one named field, since
    `extra` intentionally passes through fields this module does not know
    the names of in advance.
    """
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, (_datetime.date, _datetime.datetime)):
        return value.isoformat()
    return value


def _parse_skill_frontmatter(text: str) -> dict[str, Any]:
    """Parse YAML frontmatter from a SKILL.md file.

    Prefers yaml.safe_load() when PyYAML is available (handles all valid YAML).
    Falls back to a block-scalar-aware line-by-line parser when PyYAML is not
    installed. The fallback correctly resolves >- and | block scalar indicators
    so that skills using those syntaxes in their description field index the
    resolved prose rather than the literal ">-" string.

    Returns a dict of frontmatter fields. If no frontmatter block is present
    or parsing fails, returns an empty dict. Every value is JSON-safe
    (`_json_safe()`) -- callers (notably `cc skill list --json`) never need
    their own type-coercion pass.
    """
    if not text.startswith("---"):
        return {}

    end = text.find("\n---", 3)
    if end == -1:
        return {}

    raw_yaml = text[3:end].strip()

    # --- Fast path: PyYAML handles all valid YAML including block scalars ---
    if _YAML_AVAILABLE:
        try:
            parsed = _yaml.safe_load(raw_yaml)
            if isinstance(parsed, dict):
                return _json_safe(parsed)
        except Exception:  # noqa: BLE001
            pass
        return {}

    # --- Fallback: block-scalar-aware line-by-line parser ---
    fm: dict[str, Any] = {}
    lines = raw_yaml.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if ":" not in line:
            i += 1
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        if not key or key.startswith(" "):
            # Indented line — continuation of previous value, skip
            i += 1
            continue
        val = val.strip()
        if val in (">-", ">", "|-", "|"):
            # Block scalar: consume subsequent indented lines
            resolved, i = _resolve_block_scalar(lines, i, indicator=val)
            fm[key] = resolved
        elif val.startswith("[") and val.endswith("]"):
            inner = val[1:-1]
            fm[key] = (
                [v.strip() for v in inner.split(",") if v.strip()]
                if inner.strip()
                else []
            )
            i += 1
        else:
            fm[key] = val
            i += 1

    return fm


def _skill_name_from_fm(fm: dict[str, Any], fallback: str) -> str:
    """Extract skill name from frontmatter, tolerating multiple field names."""
    return fm.get("name") or fm.get("skill_name") or fallback


def _skill_tags_from_fm(fm: dict[str, Any]) -> list[str]:
    """Extract tags list from frontmatter."""
    raw = fm.get("tags")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [t.strip() for t in raw if t.strip()]
    # Comma-separated string
    return [t.strip() for t in raw.split(",") if t.strip()]


# WP-372 P2.2 perf: read frontmatter-sized chunks, never the whole file --
# see _read_frontmatter_prefix()'s own docstring.
_FRONTMATTER_READ_CHUNK = 4096
_FRONTMATTER_MAX_BYTES = 65536  # 64 KiB ceiling -- generous for any real frontmatter block


def _read_frontmatter_prefix(path: Path) -> str:
    """
    Read only as much of `path` as is needed to capture its YAML
    frontmatter block (`---\\n...\\n---`), never the full SKILL.md body.

    WP-372 P2.2: the knowledge repo's skill tree alone is ~280 files;
    `.read_text()`-ing every file in full on every `cc skill list`/
    `search` just to discard the body immediately after parsing
    frontmatter was needless I/O.

    Reads in `_FRONTMATTER_READ_CHUNK`-character increments and stops as
    soon as `buf.find("\\n---", 3)` succeeds -- the EXACT same delimiter
    search `_parse_skill_frontmatter()` performs on a full read, so the
    parse result is identical to a full read whenever the frontmatter
    block fits within `_FRONTMATTER_MAX_BYTES` (true for every real
    SKILL.md on this machine and every existing fixture) -- or once
    `_FRONTMATTER_MAX_BYTES` is reached (a pathological file with no
    closing delimiter within that ceiling reads no further;
    `_parse_skill_frontmatter()` degrades to `{}` for it, the same
    "no frontmatter" outcome a full read of a genuinely malformed file
    would have produced).

    A file with no frontmatter at all (doesn't start with `---`) returns
    after the FIRST chunk -- `_parse_skill_frontmatter()` never looks past
    that check either.

    Raises `OSError` on any read failure -- callers already handle that
    identically to the prior `.read_text()` call this replaces.
    """
    with path.open("r", encoding="utf-8") as fh:
        buf = fh.read(_FRONTMATTER_READ_CHUNK)
        if not buf.startswith("---"):
            return buf
        while buf.find("\n---", 3) == -1 and len(buf) < _FRONTMATTER_MAX_BYTES:
            chunk = fh.read(_FRONTMATTER_READ_CHUNK)
            if not chunk:
                break
            buf += chunk
        return buf


def discover_skills(
    paths: list[Path],
    source_label: str = "",
    *,
    cache_dir: Optional[Path] = None,
    _knowledge_source: Any = None,
) -> list[SkillMeta]:
    """Scan each path for ``*/SKILL.md`` files and parse frontmatter.

    Args:
        paths: Directories to scan. Each directory is walked one level deep
               for ``<name>/SKILL.md`` files.
        source_label: Optional label to set on all discovered skills.
        cache_dir: WP-372 P2.2 -- when given, a parsed-frontmatter cache
            directory (`core/skill_cache.py`) is consulted before reading
            each file and updated after a miss, keyed by the file's
            `(path, mtime, size)`. `None` (the default) disables caching
            entirely -- every direct caller of this function that does not
            explicitly opt in (including every existing test) is
            byte-for-byte unaffected; only `commands/skill.py`'s real CLI
            entry point passes a real cache directory.

    Returns a list of :class:`SkillMeta` objects, one per discovered file.
    """
    skills: list[SkillMeta] = []

    for base in paths:
        base = Path(base)
        if not base.exists() or not base.is_dir():
            continue

        # Walk one level: base/<name>/SKILL.md
        # Also supports nested: base/<category>/<name>/SKILL.md.
        # Follow symlinked directories so shared framework skills can be bridged
        # into project-local .claude/skills without copying the framework.
        if _knowledge_source is not None:
            skill_files = list(_knowledge_source.skill_files())
        else:
            skill_files = []
            for root, _dirs, files in os.walk(base, followlinks=True):
                if "SKILL.md" in files:
                    skill_files.append(Path(root) / "SKILL.md")

        for skill_file in sorted(skill_files):
            fm: Optional[dict[str, Any]] = None
            stat_result = None
            if cache_dir is not None:
                try:
                    stat_result = skill_file.stat()
                except OSError:
                    continue
                from cc.core.skill_cache import cache_get_frontmatter

                fm = cache_get_frontmatter(
                    skill_file,
                    mtime=stat_result.st_mtime,
                    size=stat_result.st_size,
                    cache_dir=cache_dir,
                )

            if fm is None:
                try:
                    text = (
                        _knowledge_source.read_text(skill_file)
                        if _knowledge_source is not None
                        else _read_frontmatter_prefix(skill_file)
                    )
                except OSError:
                    continue

                fm = _parse_skill_frontmatter(text)

                if cache_dir is not None:
                    if stat_result is None:
                        try:
                            stat_result = skill_file.stat()
                        except OSError:
                            stat_result = None
                    if stat_result is not None:
                        from cc.core.skill_cache import cache_put_frontmatter

                        cache_put_frontmatter(
                            skill_file,
                            mtime=stat_result.st_mtime,
                            size=stat_result.st_size,
                            frontmatter=fm,
                            cache_dir=cache_dir,
                        )

            # Derive a fallback name from the parent directory
            fallback_name = skill_file.parent.name
            name = _skill_name_from_fm(fm, fallback_name)
            description = fm.get("description", "")
            tags = _skill_tags_from_fm(fm)
            version = str(fm.get("version", ""))

            # Collect remaining fields as 'extra' -- e.g. WP-372 P2.2's
            # `triggers` routing block, `allowed-tools`, `status`, ... this
            # module never decides which of these are "useful"; every
            # declared field not already promoted to a named SkillMeta
            # field flows through unchanged (parse, never compute).
            known_keys = {"name", "skill_name", "description", "tags", "version"}
            extra = {k: v for k, v in fm.items() if k not in known_keys}

            skills.append(
                SkillMeta(
                    name=name,
                    description=description,
                    path=skill_file.resolve(),
                    tags=tags,
                    version=version,
                    source=source_label,
                    extra=extra,
                    _knowledge_source=_knowledge_source,
                )
            )

    return skills


def discover_skills_with_sources(
    path_source_pairs: list[tuple[Path, str]],
    *,
    cache_dir: Optional[Path] = None,
) -> list[SkillMeta]:
    """Discover skills from multiple paths, each with its own source label.

    Deduplicates by skill name (first match wins, reflecting resolution
    order -- project → machine → knowledge, WP-372 P2.2).

    `cache_dir`: forwarded to `discover_skills()` unchanged -- `None` (the
    default) disables caching for every existing/direct caller.
    """
    seen_names: set[str] = set()
    results: list[SkillMeta] = []

    for base_path, source_label in path_source_pairs:
        knowledge_source = None
        effective_cache_dir = cache_dir
        if source_label == "knowledge":
            from cc.core.ecosystem.knowledge_skill_source import (
                resolve_knowledge_skill_sources,
            )

            nominal = Path(os.path.abspath(Path(base_path).expanduser()))
            knowledge_source = next(
                (
                    source
                    for root, source in resolve_knowledge_skill_sources()
                    if root == nominal
                ),
                None,
            )
            # A mutable mtime/size cache is not an authority for signed bytes.
            effective_cache_dir = None
        for skill in discover_skills(
            [base_path],
            source_label=source_label,
            cache_dir=effective_cache_dir,
            _knowledge_source=knowledge_source,
        ):
            if skill.name not in seen_names:
                seen_names.add(skill.name)
                results.append(skill)

    return results


def search_skills(query: str, skills: list[SkillMeta]) -> list[SkillMeta]:
    """Keyword search against name, description, and tags.

    Case-insensitive substring match. Returns skills that match any token.
    """
    if not query.strip():
        return list(skills)

    tokens = [t.lower() for t in query.split()]
    results: list[SkillMeta] = []

    for skill in skills:
        haystack = " ".join(
            [
                skill.name.lower(),
                skill.description.lower(),
                " ".join(t.lower() for t in skill.tags),
            ]
        )
        if any(token in haystack for token in tokens):
            results.append(skill)

    return results


def get_skill_content(skill_meta: SkillMeta) -> str:
    """Read and return the full SKILL.md content for a given skill."""
    return get_skill_content_with_receipt(skill_meta).content


def get_skill_content_with_receipt(
    skill_meta: SkillMeta, *, runtime: str = "cc"
) -> SkillContent:
    """Read a skill and retain signed Knowledge provenance when available.

    Project, machine, and legacy unsigned Knowledge paths remain compatible,
    but deliberately return no authenticated receipt.
    """
    if skill_meta._knowledge_source is not None:
        source = skill_meta._knowledge_source
        relative = skill_meta.path.relative_to(source.skills_root)
        contribution = (
            Path(source.relative_path) / relative
        ).as_posix()
        receipt = source.authenticated_contribution(contribution, runtime=runtime)
        return SkillContent(content=receipt.content, receipt=receipt)
    return SkillContent(content=skill_meta.path.read_text(encoding="utf-8"))


def revalidate_skill_path(skill_meta: SkillMeta) -> None:
    """Revalidate signed Knowledge authority before disclosing a live path."""
    if skill_meta._knowledge_source is None:
        return
    from cc.core.ecosystem.knowledge_skill_source import (
        revalidate_knowledge_skill_source,
    )

    revalidate_knowledge_skill_source(skill_meta._knowledge_source)


def find_skill_by_name(
    name: str,
    skills: list[SkillMeta],
) -> SkillMeta | None:
    """Return the first skill whose name matches (case-insensitive)."""
    name_lower = name.lower()
    for skill in skills:
        if skill.name.lower() == name_lower:
            return skill
    return None
