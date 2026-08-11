"""Tests for cc.core.ecosystem.substance — the "is this real content or an
inert scaffold" heuristic shared by project-install ladder resolution.
"""

from __future__ import annotations

from cc.core.ecosystem.substance import frontmatter_status, is_substantive


def test_frontmatter_status_extracts_status_value():
    text = "---\nstatus: draft\nother: x\n---\n\nbody"
    assert frontmatter_status(text) == "draft"


def test_frontmatter_status_none_when_no_frontmatter():
    assert frontmatter_status("just a body, no frontmatter") is None


def test_frontmatter_status_none_when_no_status_key():
    text = "---\nother: x\n---\n\nbody"
    assert frontmatter_status(text) is None


def test_is_substantive_true_for_ordinary_real_content():
    assert is_substantive("# Real protocol\n\nActual instructions here.") is True


def test_is_substantive_false_for_draft_frontmatter():
    text = "---\nstatus: draft\n---\n\nsome prose"
    assert is_substantive(text) is False


def test_is_substantive_false_for_todo_marker_even_with_lots_of_prose():
    """The live incident shape: a TODO( marker atop an otherwise large
    byte-for-byte reproduction of real content is still non-substantive --
    size alone must never override the marker."""
    text = "TODO(pablo): this section is a placeholder.\n\n" + ("real words. " * 500)
    assert is_substantive(text) is False


def test_is_substantive_false_when_disproportionately_smaller_than_shadow():
    assert is_substantive("tiny", shadow_size=10_000) is False


def test_is_substantive_true_when_no_shadow_size_given():
    """No chain to compare against -- the size-ratio check cannot fire, so
    a marker-free, non-draft file is substantive even if genuinely small."""
    assert is_substantive("short but real") is True


def test_is_substantive_respects_custom_minimum_size_ratio():
    text = "x" * 40  # 40 bytes
    assert is_substantive(text, shadow_size=100, minimum_size_ratio=0.5) is False
    assert is_substantive(text, shadow_size=100, minimum_size_ratio=0.3) is True
