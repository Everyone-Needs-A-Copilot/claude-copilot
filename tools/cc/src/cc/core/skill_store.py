"""Skill store: discovery, parsing, and retrieval of SKILL.md files.

Skills are markdown files with YAML frontmatter. The canonical frontmatter
fields are: name, description, tags, version. Additional fields (e.g.
skill_name, skill_category) are tolerated and stored under 'extra'.

Resolution order (first match wins): project → machine → framework.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any


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


def default_skill_paths() -> list[tuple[Path, str]]:
    """Return the default skill search paths with their source labels.

    Resolution order: project → machine → framework.
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

    return paths


def _parse_skill_frontmatter(text: str) -> dict[str, Any]:
    """Parse YAML frontmatter from a SKILL.md file.

    Returns a dict of frontmatter fields. If no frontmatter block is present,
    returns an empty dict.
    """
    if not text.startswith("---"):
        return {}

    end = text.find("\n---", 3)
    if end == -1:
        return {}

    raw_yaml = text[3:end].strip()
    fm: dict[str, Any] = {}

    for line in raw_yaml.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1]
            fm[key] = [v.strip() for v in inner.split(",") if v.strip()] if inner.strip() else []
        else:
            fm[key] = val

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


def discover_skills(
    paths: list[Path],
    source_label: str = "",
) -> list[SkillMeta]:
    """Scan each path for ``*/SKILL.md`` files and parse frontmatter.

    Args:
        paths: Directories to scan. Each directory is walked one level deep
               for ``<name>/SKILL.md`` files.
        source_label: Optional label to set on all discovered skills.

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
        skill_files = []
        for root, _dirs, files in os.walk(base, followlinks=True):
            if "SKILL.md" in files:
                skill_files.append(Path(root) / "SKILL.md")

        for skill_file in sorted(skill_files):
            try:
                text = skill_file.read_text(encoding="utf-8")
            except OSError:
                continue

            fm = _parse_skill_frontmatter(text)
            # Derive a fallback name from the parent directory
            fallback_name = skill_file.parent.name
            name = _skill_name_from_fm(fm, fallback_name)
            description = fm.get("description", "")
            tags = _skill_tags_from_fm(fm)
            version = str(fm.get("version", ""))

            # Collect remaining fields as 'extra'
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
                )
            )

    return skills


def discover_skills_with_sources(
    path_source_pairs: list[tuple[Path, str]],
) -> list[SkillMeta]:
    """Discover skills from multiple paths, each with its own source label.

    Deduplicates by skill name (first match wins, reflecting resolution order).
    """
    seen_names: set[str] = set()
    results: list[SkillMeta] = []

    for base_path, source_label in path_source_pairs:
        for skill in discover_skills([base_path], source_label=source_label):
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
    return skill_meta.path.read_text(encoding="utf-8")


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
