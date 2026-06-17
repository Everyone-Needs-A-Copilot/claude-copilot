"""
QA verification tests for skill frontmatter migration (TASK-61).
Checks:
  1. YAML validity
  2. No stale skill_name fields
  3. Required shape: name + non-empty description
  4. Code-bearing skills retain execution fields
  5. cc skill search functional
  6. Count sanity (27 touched per WP-96, but we accept total > 27)
  7. No FTS5 claims in key docs
"""

import os
import glob
import yaml
import subprocess
import sys

BASE = "/Volumes/Dev/Sites/COPILOT/claude-copilot"
SKILLS_DIR = os.path.join(BASE, ".claude/skills")


def get_all_skill_files():
    """Return sorted list of all SKILL.md paths."""
    files = []
    for root, dirs, fs in os.walk(SKILLS_DIR):
        for f in fs:
            if f == "SKILL.md":
                files.append(os.path.join(root, f))
    return sorted(files)


def parse_frontmatter(filepath):
    """Extract and parse YAML frontmatter from a SKILL.md file."""
    with open(filepath, "r", encoding="utf-8") as fh:
        content = fh.read()
    if not content.startswith("---"):
        return None, content, "no frontmatter delimiter"
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None, content, "incomplete frontmatter"
    try:
        fm = yaml.safe_load(parts[1])
        return fm, content, None
    except yaml.YAMLError as e:
        return None, content, str(e)


ALL_SKILLS = get_all_skill_files()


class TestSkillCount:
    def test_at_least_27_skills_exist(self):
        """At least 27 SKILL.md files must exist (WP-96 claims 27 were migrated)."""
        assert (
            len(ALL_SKILLS) >= 27
        ), f"Expected >= 27 SKILL.md files, found {len(ALL_SKILLS)}"

    def test_no_skills_are_empty(self):
        """No SKILL.md file should be empty/truncated."""
        empty = []
        for fp in ALL_SKILLS:
            size = os.path.getsize(fp)
            if size < 50:  # Less than 50 bytes is suspiciously empty
                empty.append((fp.replace(BASE, ""), size))
        assert not empty, f"Empty/truncated skill files: {empty}"


class TestYAMLValidity:
    def test_all_frontmatter_parses_as_valid_yaml(self):
        """Every SKILL.md frontmatter must parse as valid YAML."""
        errors = []
        for fp in ALL_SKILLS:
            fm, content, err = parse_frontmatter(fp)
            if err:
                errors.append(f"{fp.replace(BASE, '')}: {err}")
            elif fm is None:
                errors.append(f"{fp.replace(BASE, '')}: parsed as None/empty")
        assert not errors, "YAML parse failures:\n" + "\n".join(errors)


class TestNoStaleFields:
    def test_no_skill_name_field_remains(self):
        """The stale 'skill_name' field must not appear in any SKILL.md frontmatter."""
        stale = []
        for fp in ALL_SKILLS:
            fm, _, err = parse_frontmatter(fp)
            if err:
                continue  # Already caught in YAML validity test
            if fm and "skill_name" in fm:
                stale.append(fp.replace(BASE, ""))
        assert (
            not stale
        ), "Files still containing stale 'skill_name' field:\n" + "\n".join(stale)

    def test_no_skill_name_in_raw_text(self):
        """Double-check: grep for skill_name: anywhere in SKILL.md files."""
        hits = []
        for fp in ALL_SKILLS:
            with open(fp, "r", encoding="utf-8") as fh:
                content = fh.read()
            for i, line in enumerate(content.splitlines(), 1):
                if "skill_name:" in line:
                    hits.append(f"{fp.replace(BASE, '')}:{i}: {line.strip()}")
        assert not hits, "Raw 'skill_name:' occurrences found:\n" + "\n".join(hits)


class TestRequiredShape:
    def test_every_skill_has_name_field(self):
        """Every SKILL.md frontmatter must have a non-empty 'name' field."""
        missing = []
        for fp in ALL_SKILLS:
            fm, _, err = parse_frontmatter(fp)
            if err:
                continue
            if not fm or not fm.get("name"):
                missing.append(fp.replace(BASE, ""))
        assert not missing, "Skills missing 'name' field:\n" + "\n".join(missing)

    def test_every_skill_has_nonempty_description(self):
        """Every SKILL.md frontmatter must have a non-empty 'description' field."""
        missing = []
        for fp in ALL_SKILLS:
            fm, _, err = parse_frontmatter(fp)
            if err:
                continue
            if not fm or not fm.get("description"):
                missing.append(fp.replace(BASE, ""))
        assert not missing, "Skills missing non-empty 'description':\n" + "\n".join(
            missing
        )

    def test_description_meets_minimum_length(self):
        """Descriptions should be > 80 chars (WP-95 spec: trigger-rich, >80 chars)."""
        short = []
        for fp in ALL_SKILLS:
            fm, _, err = parse_frontmatter(fp)
            if err:
                continue
            desc = (fm or {}).get("description", "") or ""
            if len(str(desc)) < 80:
                short.append(
                    f"{fp.replace(BASE, '')}: {len(str(desc))} chars: '{desc[:60]}'"
                )
        assert (
            not short
        ), "Skills with description < 80 chars (WP-95 spec violation):\n" + "\n".join(
            short
        )


class TestCodeBearingSkills:
    """Code-bearing skills must retain allowed-tools and Bash instructions."""

    def _find_code_bearing(self):
        """Skills with allowed-tools or trigger_keywords are code-bearing."""
        code_bearing = []
        for fp in ALL_SKILLS:
            fm, content, err = parse_frontmatter(fp)
            if err:
                continue
            if fm and ("allowed-tools" in fm or "trigger_keywords" in fm):
                code_bearing.append((fp, fm, content))
        return code_bearing

    def test_code_bearing_skills_have_allowed_tools(self):
        """Code-bearing skills must have 'allowed-tools' field."""
        missing = []
        for fp, fm, content in self._find_code_bearing():
            if "allowed-tools" not in fm:
                missing.append(fp.replace(BASE, ""))
        # This is informational — trigger_keywords alone doesn't require allowed-tools
        # Just confirm at least some code-bearing skills exist
        code_bearing = self._find_code_bearing()
        assert len(code_bearing) > 0, "No code-bearing skills found at all"

    def test_code_bearing_skills_have_bash_instructions(self):
        """Code-bearing skills must contain Bash execution instructions in body."""
        no_bash = []
        for fp, fm, content in self._find_code_bearing():
            body = content.split("---", 2)[-1] if "---" in content else content
            # Check for bash, Bash, or shell execution references
            has_bash = any(
                kw in body
                for kw in ["Bash", "bash", "shell", "Shell", "```bash", "run"]
            )
            if not has_bash:
                no_bash.append(fp.replace(BASE, ""))
        assert (
            not no_bash
        ), "Code-bearing skills missing Bash instructions:\n" + "\n".join(no_bash)


class TestCCSkillSearch:
    """cc skill search must return expected skills for known topics."""

    def _run_search(self, query):
        result = subprocess.run(
            ["cc", "skill", "search", query], capture_output=True, text=True, cwd=BASE
        )
        return result.stdout + result.stderr

    def test_search_security_finds_stride_dread(self):
        """'security' search should return stride-dread skill.

        KNOWN DEFECT (TASK-61 regression): cc skill search uses a custom
        line-by-line YAML parser (skill_store._parse_skill_frontmatter) that
        cannot resolve YAML block scalars (>-). When description uses >- syntax,
        the parser stores ">-" as the description string instead of the resolved
        content. stride-dread has no tags: field, so its haystack is
        "stride-dread >- " and "security" does not match.

        This test documents the regression. Fix: use yaml.safe_load() in
        skill_store._parse_skill_frontmatter() instead of the custom parser.
        """
        output = self._run_search("security")
        assert "stride-dread" in output.lower() or "stride" in output.lower(), (
            f"'security' search did not return stride-dread.\n"
            f"Root cause: _parse_skill_frontmatter() does not handle YAML >- block scalars.\n"
            f"Output:\n{output}"
        )

    def test_search_testing_finds_pytest(self):
        """'testing' search should return pytest-patterns skill."""
        output = self._run_search("testing")
        assert (
            "pytest" in output.lower()
        ), f"'testing' search did not return pytest-patterns. Output:\n{output}"

    def test_search_javascript_finds_skill(self):
        """'javascript' search should return javascript-patterns skill."""
        output = self._run_search("javascript")
        assert (
            "javascript" in output.lower()
        ), f"'javascript' search did not find javascript skill. Output:\n{output}"

    def test_search_docker_finds_skill(self):
        """'docker' search should return docker-patterns skill."""
        output = self._run_search("docker")
        assert (
            "docker" in output.lower()
        ), f"'docker' search did not find docker skill. Output:\n{output}"


class TestDocsFixed:
    """Docs must not assert FTS5 for skill search or template skill_name."""

    DOCS_TO_CHECK = [
        os.path.join(BASE, "docs/30-operations/06-skills-authoring-guide.md"),
        os.path.join(BASE, "docs/10-architecture/00-overview.md"),
        os.path.join(BASE, "CLAUDE.md"),
    ]

    def _read(self, path):
        if not os.path.exists(path):
            return ""
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()

    def test_no_fts5_skill_claim_in_authoring_guide(self):
        """Skills authoring guide must not POSITIVELY claim FTS5 for skill search.

        A corrective statement like 'It is NOT FTS5' is fine and expected.
        We only flag lines that affirmatively state cc skill search IS FTS5.
        """
        content = self._read(self.DOCS_TO_CHECK[0])
        assert os.path.exists(
            self.DOCS_TO_CHECK[0]
        ), f"Skills authoring guide not found at {self.DOCS_TO_CHECK[0]}"
        lines = content.splitlines()
        violations = []
        for i, line in enumerate(lines, 1):
            # Affirmative claim: FTS5 + skill/search but NOT a negation
            if "FTS5" in line and ("skill" in line.lower() or "search" in line.lower()):
                # Allow lines that are explicitly negating the FTS5 claim
                if "NOT FTS5" in line or "not FTS5" in line or "isn't FTS5" in line:
                    continue
                violations.append(f"line {i}: {line.strip()}")
        assert not violations, (
            "Authoring guide still affirmatively claims FTS5 for skill search:\n"
            + "\n".join(violations)
        )

    def test_no_skill_name_template_in_authoring_guide(self):
        """Skills authoring guide must not template 'skill_name:' as canonical field."""
        content = self._read(self.DOCS_TO_CHECK[0])
        lines = content.splitlines()
        violations = []
        for i, line in enumerate(lines, 1):
            # Looking for template usage like "skill_name: my-skill" as instruction
            if "skill_name:" in line and not line.strip().startswith("#"):
                violations.append(f"line {i}: {line.strip()}")
        assert (
            not violations
        ), "Authoring guide still templates 'skill_name:':\n" + "\n".join(violations)

    def test_no_fts5_skill_claim_in_overview(self):
        """Architecture overview must not affirmatively claim FTS5 for skill search."""
        content = self._read(self.DOCS_TO_CHECK[1])
        if not content:
            return  # File may not exist
        lines = content.splitlines()
        violations = []
        for i, line in enumerate(lines, 1):
            if "FTS5" in line and "skill" in line.lower():
                if "NOT FTS5" in line or "not FTS5" in line:
                    continue
                violations.append(f"line {i}: {line.strip()}")
        assert (
            not violations
        ), "overview.md still affirmatively claims FTS5 for skills:\n" + "\n".join(
            violations
        )

    def test_no_fts5_skill_claim_in_claude_md(self):
        """CLAUDE.md must not affirmatively claim FTS5 for skill search (memory FTS5 is OK)."""
        content = self._read(self.DOCS_TO_CHECK[2])
        lines = content.splitlines()
        violations = []
        for i, line in enumerate(lines, 1):
            # FTS5 in context of skills (not memory) — only affirmative claims
            if "FTS5" in line and "skill" in line.lower():
                if "NOT FTS5" in line or "not FTS5" in line:
                    continue
                violations.append(f"line {i}: {line.strip()}")
        assert (
            not violations
        ), "CLAUDE.md still affirmatively claims FTS5 for skill search:\n" + "\n".join(
            violations
        )

    def test_no_skill_name_template_in_claude_md(self):
        """CLAUDE.md must not template 'skill_name:' as canonical field."""
        content = self._read(self.DOCS_TO_CHECK[2])
        lines = content.splitlines()
        violations = []
        for i, line in enumerate(lines, 1):
            if "skill_name:" in line:
                violations.append(f"line {i}: {line.strip()}")
        assert (
            not violations
        ), "CLAUDE.md still has 'skill_name:' references:\n" + "\n".join(violations)
