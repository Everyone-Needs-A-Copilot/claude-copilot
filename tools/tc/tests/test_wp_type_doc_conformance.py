"""Static check: every `tc wp store --type <value>` literal this repo's own
documentation and agent definitions instruct an agent to use must be in
WP_VALID_TYPES.

This is the regression test for the `other` gap (commit `dedf5d4` followed
by this fix): `docs/50-features/04-goal-driven-agents.md:315` instructs
every agent's BLOCKED recovery workflow to run `tc wp store --type other
...`. The allowlist audit that introduced WP_VALID_TYPES drew from
`tasks.db` contents and `.claude/agents/*.md` but never grepped this repo's
own feature docs (`docs/50-features/**`) or skills (`SKILL.md`), so a
literal value instructed only in a feature doc was invisible to it and every
agent following its documented recovery step failed with EXIT_VALIDATION.

This test closes that class of gap (not just the one instance): it parses
every doc this repo ships (docs/**, .claude/agents/**, .claude/commands/**,
.claude/skills/**, README.md, CLAUDE.md) for literal `tc wp store ...
--type <value>` occurrences and asserts each one is accepted by store_wp.

It is deliberately scoped to this repo's own tree, not sibling repos under
/Volumes/Dev/Sites/COPILOT/ — a hermetic, CI-portable check can only see
what ships with the framework itself. Values sourced from other repos
(e.g. a downstream project's custom agent) are added by hand, with their
evidence recorded in docs/70-reference/06-wp-type-allowlist.md, the same way
this fix added `artifact-review`, `validation-review`, and `discovery`.

Placeholders (`<type>`, `<t>`, `TYPE`, etc.) are excluded — they document
where an agent supplies its own value, they are not themselves an
instructed value.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path("/Volumes/Dev/Sites/COPILOT/claude-copilot")

# Directories (repo-relative) that ship instructions to agents, and
# therefore gate what this test checks. `.claude/agents/_archive` and
# `.claude/worktrees` are deliberately excluded: the former holds
# superseded agent versions, the latter holds ephemeral per-agent working
# copies — neither is a canonical, currently-shipped instruction.
_SCAN_ROOTS = ["docs", ".claude/agents", ".claude/commands", ".claude/skills"]
_SCAN_FILES = ["README.md", "CLAUDE.md", "CLAUDE_REFERENCE.md"]
_EXCLUDED_PATH_FRAGMENTS = ("/worktrees/", "/_archive/")

# Matches `tc wp store ... --type <token>` on a single line. The value
# character class (alnum/underscore/hyphen/angle-brackets) stops the match
# cleanly at trailing markdown punctuation (backticks, colons, parens)
# without a separate strip pass.
_WP_STORE_TYPE_RE = re.compile(r"tc wp store\b.*?--type[= ]+([A-Za-z0-9_<>-]+)")

# A literal instructed value never contains a placeholder marker, and is
# never the bare words `type`/`TYPE`/`t` used as a placeholder name.
_PLACEHOLDER_RE = re.compile(r"[<>]|^(?:TYPE|type|t)$")


def _iter_doc_files():
    for root in _SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*.md"):
            rel = str(path.relative_to(REPO_ROOT))
            if any(frag in f"/{rel}" for frag in _EXCLUDED_PATH_FRAGMENTS):
                continue
            yield path
    for name in _SCAN_FILES:
        path = REPO_ROOT / name
        if path.exists():
            yield path


def _instructed_types() -> dict[str, list[str]]:
    """Map literal --type value -> ['file:line', ...] locations it appears at."""
    found: dict[str, list[str]] = {}
    for path in _iter_doc_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in _WP_STORE_TYPE_RE.finditer(line):
                value = match.group(1)
                if _PLACEHOLDER_RE.search(value):
                    continue
                found.setdefault(value, []).append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno}"
                )
    return found


class TestWpTypeDocConformance:
    def test_every_documented_wp_store_type_is_in_allowlist(self):
        """Every literal --type value this repo's own docs and agent
        definitions instruct an agent to use must be accepted by store_wp —
        not just the values the allowlist happened to already contain."""
        from tc.services.wp import WP_VALID_TYPES

        found = _instructed_types()
        assert found, (
            "expected at least one literal `tc wp store --type <value>` "
            "instruction in this repo's docs — if this is empty the scan "
            "itself is broken, not the allowlist"
        )
        missing = {
            value: locations
            for value, locations in found.items()
            if value not in WP_VALID_TYPES
        }
        assert not missing, (
            "documented `tc wp store --type` value(s) not in WP_VALID_TYPES "
            f"(add them, with evidence, to WP_VALID_TYPES and "
            f"docs/70-reference/06-wp-type-allowlist.md): {missing}"
        )

    def test_other_is_documented_and_accepted(self):
        """The exact defect this check exists for: docs/50-features/
        04-goal-driven-agents.md's BLOCKED recovery workflow instructs
        `tc wp store --type other ...`. This is the assertion that would
        have failed against the pre-fix allowlist at authoring time."""
        from tc.services.wp import WP_VALID_TYPES

        found = _instructed_types()
        assert "other" in found, (
            "expected docs/50-features/04-goal-driven-agents.md's BLOCKED "
            "workflow to still instruct --type other"
        )
        assert "other" in WP_VALID_TYPES
