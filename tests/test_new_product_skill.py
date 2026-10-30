"""Contract tests for the /new-product foundation skill.

Fitness functions from the approved design (knowledge-copilot-internal WP-22):
F2 path integrity, F3 runtime neutrality, F5 frontmatter, plus the machine
install roster and an empty-folder setup walkthrough that runs the documented
setup commands against a scratch directory.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".claude" / "skills" / "new-product"
TEMPLATES = SKILL / "assets" / "templates"
SKILL_VERSION = re.search(r"^Skill version: (\S+)$", (SKILL / "SKILL.md").read_text(), re.M).group(1)
MARKDOWN = sorted(SKILL.rglob("*.md"))

# The facilitated documents of the original product-creation-copilot sequence.
EXPECTED_DOCUMENTS = [
    "00-overview/00-vision.md",
    "00-overview/10-scope-and-non-goals.md",
    "00-overview/20-success-metrics.md",
    "01-research/10-interviews/00-interview-template.md",
    "01-research/10-interviews/01-interview-self.md",
    "02-service-design/10-service-blueprint.md",
    "02-service-design/20-journey-maps.md",
    "02-service-design/30-jtbd.md",
    "02-service-design/40-moments-that-matter.md",
    "03-requirements/10-user-stories.md",
    "03-requirements/20-use-cases-and-scenarios.md",
    "03-requirements/30-acceptance-criteria.md",
    "04-experience-design/50-ux-design.md",
    "04-experience-design/60-ui-design.md",
    "04-experience-design/70-copy-voice.md",
    "05-design-challenge/00-brief.md",
    "06-prototype/00-figma-design.md",
    "06-prototype/10-design-spec.md",
    "06-prototype/20-storybook.md",
    "06-prototype/30-nextjs-prototype.md",
    "06-prototype/README.md",
    "README.md",
    "TODO-DESIGN-PACKAGE.md",
]


def _frontmatter(path: Path) -> dict:
    parts = path.read_text(encoding="utf-8").split("---", 2)
    assert len(parts) == 3, f"{path} has no frontmatter"
    return yaml.safe_load(parts[1])


def test_frontmatter_names_the_folder_and_triggers():
    meta = _frontmatter(SKILL / "SKILL.md")
    assert meta["name"] == SKILL.name == "new-product"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", meta["name"])
    description = meta["description"]
    assert 80 <= len(description) <= 1024
    assert "/new-product" in description and "$new-product" in description
    # Shared with Codex: only the Agent Skills keys, no runtime-specific ones.
    assert set(meta) <= {"name", "description"}


def test_skill_is_top_level_and_rostered_for_machine_install():
    version = json.loads((ROOT / "VERSION.json").read_text())
    roster = version["components"]["skills"]["machineSkills"]
    assert "new-product" in roster
    for name in roster:
        assert (ROOT / ".claude" / "skills" / name / "SKILL.md").is_file()
        assert _frontmatter(ROOT / ".claude" / "skills" / name / "SKILL.md")["name"] == name


def test_template_tree_matches_the_original_document_sequence():
    shipped = sorted(
        path.relative_to(TEMPLATES).as_posix() for path in TEMPLATES.rglob("*") if path.is_file()
    )
    assert shipped == sorted(EXPECTED_DOCUMENTS + ["SOUL.md"])


PATH_PATTERN = re.compile(
    r"`([^`\s]+\.md)`|\]\(([^)#\s]+\.md)\)|\b(\d\d-[a-z-]+/[A-Za-z0-9_./-]+\.md)"
)
# Paths that are deliberately not files shipped by the skill.
NOT_SHIPPED = {
    "AGENTS.md",
    "CLAUDE.md",
    "06-prototype/[chosen-output].md",
    "00-vision.md",
    "02-interview-user-01.md",
    "03-interview-user-02.md",
}


def _resolves(owner: Path, raw: str) -> bool:
    candidate = raw.removeprefix("docs/")
    if candidate.startswith("<skill-dir>/"):
        return (SKILL / candidate.removeprefix("<skill-dir>/")).exists()
    return any(
        base.exists()
        for base in (
            TEMPLATES / candidate,
            owner.parent / candidate,
            SKILL / candidate,
            SKILL / "references" / candidate,
        )
    )


@pytest.mark.parametrize("document", MARKDOWN, ids=lambda p: p.relative_to(SKILL).as_posix())
def test_every_referenced_path_exists(document: Path):
    broken = []
    for match in PATH_PATTERN.finditer(document.read_text(encoding="utf-8")):
        raw = next(group for group in match.groups() if group)
        if raw in NOT_SHIPPED:
            continue
        if not _resolves(document, raw):
            broken.append(raw)
    assert not broken, f"{document.relative_to(SKILL)} references missing files: {sorted(set(broken))}"


def test_soul_requires_the_walk_away_test():
    """Every soul file asks what would make its user stop using the product (2026-10-30)."""
    template = (TEMPLATES / "SOUL.md").read_text(encoding="utf-8")
    guide = (SKILL / "references" / "soul-file.md").read_text(encoding="utf-8")
    retrofit = (SKILL / "references" / "soul-retrofit.md").read_text(encoding="utf-8")
    essence = template.split("## 2. The Essence", 1)[1].split("## 3.", 1)[0]
    gates = template.split("## 5. Feature Filter", 1)[1].split("### Case Law", 1)[0]
    assert "**The walk-away test.**" in essence
    assert gates.rfind("### Gate") == gates.find("### Gate 5: Walk-away Test")
    assert "What would make you stop using this every day?" in guide
    assert "A soul file is not ratified without this answer." in guide
    assert "always a gap" in retrofit and "### First — The walk-away test" in retrofit


def test_known_original_defects_are_gone():
    text = "\n".join(path.read_text(encoding="utf-8") for path in MARKDOWN)
    for stale in ("01-discovery", "02-research/", "04-experience/", "templates/design-package", "REF-", "SKILL-soul"):
        assert stale not in text, stale


def test_instructions_name_only_runtime_neutral_mechanics_outside_runtime_reference():
    forbidden = ("@agent-", ".claude/", "AskUserQuestion", "allowed-tools", "subagent_type")
    offenders = []
    for document in MARKDOWN:
        if document.name == "runtime.md":
            continue
        text = document.read_text(encoding="utf-8")
        offenders += [f"{document.relative_to(SKILL)}: {token}" for token in forbidden if token in text]
    assert not offenders


def test_skill_md_links_every_reference_file():
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    for reference in sorted((SKILL / "references").glob("*.md")):
        assert f"references/{reference.name}" in skill_text, reference.name


def _run(command: str, cwd: Path, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-ec", command],
        cwd=cwd,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=True,
    )


def _setup_commands(section: str) -> list[str]:
    """Fenced bash blocks of setup-and-resume.md in document order."""
    text = (SKILL / "references" / "setup-and-resume.md").read_text(encoding="utf-8")
    return re.findall(r"```bash\n(.*?)```", text, re.S)


def test_empty_folder_walkthrough_builds_the_original_artifact_structure(tmp_path: Path):
    blocks = _setup_commands("")
    copy_command = next(b for b in blocks if b.startswith("mkdir -p docs\ntar "))
    replace_command = next(b for b in blocks if "PRODUCT_NAME=" in b)

    project = tmp_path / "my-new-product"
    project.mkdir()
    skill_dir = str(SKILL)
    _run(copy_command.replace("<skill-dir>", skill_dir), project)
    _run(
        replace_command.replace('"<name>"', '"A/B & Co \\"Atlas\\""')
        .replace('"<description>"', '"One-line description"')
        .replace('"1.0.0"', f'"{SKILL_VERSION}"'),
        project,
    )

    produced = sorted(
        path.relative_to(project / "docs").as_posix()
        for path in (project / "docs").rglob("*")
        if path.is_file()
    )
    assert produced == sorted(EXPECTED_DOCUMENTS)
    assert not (project / "docs" / "SOUL.md").exists()
    leftovers = [
        path.relative_to(project).as_posix()
        for path in (project / "docs").rglob("*.md")
        if re.search(r"\{\{(PRODUCT_NAME|PRODUCT_DESCRIPTION|SKILL_VERSION)\}\}", path.read_text())
    ]
    assert leftovers == []
    tracker = (project / "docs" / "TODO-DESIGN-PACKAGE.md").read_text()
    assert tracker.startswith('# A/B & Co "Atlas" — Design Package Status')
    assert f"new-product skill v{SKILL_VERSION}" in tracker
    # Every document the tracker sends the user to exists in the project.
    for relative in re.findall(r"`(\d\d-[a-z-]+/[^`\[\]]+\.md)`", tracker):
        assert (project / "docs" / relative).is_file(), relative


def test_existing_docs_are_archived_before_the_overlay(tmp_path: Path):
    blocks = _setup_commands("")
    archive_command = next(b for b in blocks if "ARCHIVE=" in b)
    copy_command = next(b for b in blocks if b.startswith("mkdir -p docs\ntar "))
    project = tmp_path / "existing"
    (project / "docs" / "_archive" / "older").mkdir(parents=True)
    (project / "docs" / "_archive" / "older" / "keep.md").write_text("older archive\n")
    (project / "docs" / "00-overview").mkdir()
    (project / "docs" / "00-overview" / "00-vision.md").write_text("my own vision\n")
    (project / "docs" / "notes.md").write_text("loose note\n")

    _run(archive_command, project)
    archive = next((project / "docs" / "_archive").glob("*-pre-template"))
    assert (archive / "00-overview" / "00-vision.md").read_text() == "my own vision\n"
    assert (archive / "notes.md").read_text() == "loose note\n"
    assert not (archive / "_archive").exists()

    _run(copy_command.replace("<skill-dir>", str(SKILL)), project)
    assert "my own vision" not in (project / "docs" / "00-overview" / "00-vision.md").read_text()
    assert (project / "docs" / "_archive" / "older" / "keep.md").exists()
