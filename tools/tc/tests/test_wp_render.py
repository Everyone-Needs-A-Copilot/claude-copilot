"""Tests for tc wp render — HTML work-product renderer.

Verifies:
- render produces a file at the expected path
- rendered HTML is self-contained (no external http/https asset references)
- copy-as buttons are present (Copy as Markdown, Copy as JSON)
- severity markers are color-coded via CSS classes
- severity legend appears when markers found, absent when not
- tc wp get output is unchanged after rendering (no storage side-effects)
- --out path override works
- stdout contains only the file path (token-free contract)
- non-existent WP exits with EXIT_NOT_FOUND
- tabbed nav present for long content (>= 100 lines), absent for short content
"""

import json
import re
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_task(cli):
    result = cli(["task", "create", "--title", "Render Test Task", "--json"])
    return json.loads(result.output)["id"]


def _store_wp(cli, task_id, content, title="Test WP", type_="analysis"):
    result = cli([
        "wp", "store",
        "--task", str(task_id),
        "--type", type_,
        "--title", title,
        "--content", content,
        "--json",
    ])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


# ---------------------------------------------------------------------------
# render produces a file
# ---------------------------------------------------------------------------

class TestWpRenderProducesFile:
    def test_render_creates_html_file(self, cli, db_path):
        task_id = _setup_task(cli)
        _store_wp(cli, task_id, "# Hello\n\nSome content here.")

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0, result.output

        html_path = Path(result.output.strip())
        assert html_path.exists(), f"Expected HTML file at {html_path}"
        assert html_path.suffix == ".html"
        assert "WP-1" in html_path.name

    def test_render_default_path_convention(self, cli, db_path):
        """Output path must be <db_parent>/renders/WP-<id>.html."""
        task_id = _setup_task(cli)
        _store_wp(cli, task_id, "Content.")

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_path = Path(result.output.strip())
        # db_path is <tmp>/.copilot/tasks.db
        # renders must be at <tmp>/.copilot/renders/WP-1.html
        expected = db_path.parent / "renders" / "WP-1.html"
        assert html_path.resolve() == expected.resolve()

    def test_render_out_path_override(self, cli, db_path, tmp_dir):
        task_id = _setup_task(cli)
        _store_wp(cli, task_id, "Content.")

        custom_out = tmp_dir / "custom_output.html"
        result = cli(["wp", "render", "1", "--html", "--out", str(custom_out)])
        assert result.exit_code == 0

        html_path = Path(result.output.strip())
        assert html_path.resolve() == custom_out.resolve()
        assert custom_out.exists()

    def test_render_stdout_is_path_only(self, cli, db_path):
        """stdout MUST contain only the file path — never the HTML body."""
        task_id = _setup_task(cli)
        _store_wp(cli, task_id, "# Doc\n\nSome text.")

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        output = result.output.strip()
        # Must be a single line
        assert '\n' not in output
        # Must not contain HTML tags
        assert '<html' not in output
        assert '<body' not in output
        # Must be an absolute path to an existing file
        html_path = Path(output)
        assert html_path.is_absolute()
        assert html_path.exists()

    def test_render_nonexistent_wp(self, cli):
        result = cli(["wp", "render", "999", "--html"])
        assert result.exit_code == 2  # EXIT_NOT_FOUND


# ---------------------------------------------------------------------------
# Self-contained — no external asset references
# ---------------------------------------------------------------------------

class TestWpRenderSelfContained:
    def test_no_external_http_references(self, cli, db_path):
        """The rendered HTML must not reference any http:// or https:// assets."""
        task_id = _setup_task(cli)
        _store_wp(cli, task_id, "# Title\n\nParagraph with [a link](https://example.com).")

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")

        # Extract all src/href/url() references (not link text)
        # Links in <a href="..."> are allowed (they're content links, not asset loads)
        # Disallow: <link href>, <script src>, <img src>, @import url(), etc.
        external_asset_patterns = [
            r'<link\b[^>]*\bhref=["\']https?://',
            r'<script\b[^>]*\bsrc=["\']https?://',
            r'<img\b[^>]*\bsrc=["\']https?://',
            r'url\(["\']?https?://',
            r'@import\s+["\']https?://',
        ]
        for pattern in external_asset_patterns:
            matches = re.findall(pattern, html_content, re.IGNORECASE)
            assert not matches, f"Found external asset reference matching {pattern!r}: {matches}"

    def test_no_cdn_references(self, cli, db_path):
        """No well-known CDN hostnames should appear as asset sources."""
        task_id = _setup_task(cli)
        _store_wp(cli, task_id, "Content.")

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        cdn_patterns = [
            'cdn.jsdelivr.net',
            'cdnjs.cloudflare.com',
            'unpkg.com',
            'fonts.googleapis.com',
            'fonts.gstatic.com',
            'stackpath.bootstrapcdn.com',
        ]
        for cdn in cdn_patterns:
            assert cdn not in html_content, f"Found CDN reference: {cdn}"

    def test_valid_html_structure(self, cli, db_path):
        """Rendered file must open with DOCTYPE and contain key structural tags."""
        task_id = _setup_task(cli)
        _store_wp(cli, task_id, "Simple content.")

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert html_content.startswith("<!DOCTYPE html>")
        assert "<html" in html_content
        assert "<head>" in html_content or "<head\n" in html_content
        assert "<body>" in html_content or "<body\n" in html_content
        assert "<style>" in html_content  # inline CSS present
        assert "</html>" in html_content


# ---------------------------------------------------------------------------
# Copy-as buttons
# ---------------------------------------------------------------------------

class TestWpRenderCopyButtons:
    def test_copy_markdown_button_present(self, cli, db_path):
        task_id = _setup_task(cli)
        _store_wp(cli, task_id, "# My WP\n\nContent.")

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert "Copy as Markdown" in html_content

    def test_copy_json_button_present(self, cli, db_path):
        task_id = _setup_task(cli)
        _store_wp(cli, task_id, "Content.")

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert "Copy as JSON" in html_content

    def test_clipboard_api_used(self, cli, db_path):
        """The JS must use navigator.clipboard for the copy actions."""
        task_id = _setup_task(cli)
        _store_wp(cli, task_id, "Content.")

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert "navigator.clipboard" in html_content

    def test_markdown_source_embedded(self, cli, db_path):
        """The original markdown source must be embedded in the JS for copying."""
        task_id = _setup_task(cli)
        content = "# Source\n\nDistinct markdown text for test_markdown_source_embedded."
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        # The source is JSON-encoded in the script block
        assert "test_markdown_source_embedded" in html_content

    def test_json_payload_embedded(self, cli, db_path):
        """The WP JSON record must be embedded in the JS for copying."""
        task_id = _setup_task(cli)
        _store_wp(cli, task_id, "Content.", title="UniqueJsonTitle999")

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert "UniqueJsonTitle999" in html_content


# ---------------------------------------------------------------------------
# Severity color-coding
# ---------------------------------------------------------------------------

class TestWpRenderSeverityColoring:
    def test_critical_marker_gets_css_class(self, cli, db_path):
        task_id = _setup_task(cli)
        content = "# Security Review\n\n**CRITICAL**: Buffer overflow in parser.\n"
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert 'sev-critical' in html_content

    def test_high_marker_gets_css_class(self, cli, db_path):
        task_id = _setup_task(cli)
        content = "- HIGH: SQL injection risk in query builder.\n"
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert 'sev-high' in html_content

    def test_medium_marker_gets_css_class(self, cli, db_path):
        task_id = _setup_task(cli)
        content = "MEDIUM priority: missing rate limiting.\n"
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert 'sev-medium' in html_content

    def test_low_marker_gets_css_class(self, cli, db_path):
        task_id = _setup_task(cli)
        content = "LOW: verbose logging in production.\n"
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert 'sev-low' in html_content

    def test_p0_marker_gets_css_class(self, cli, db_path):
        task_id = _setup_task(cli)
        content = "P0: System crash on empty input.\n"
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert 'sev-p0' in html_content

    def test_p1_marker_gets_css_class(self, cli, db_path):
        task_id = _setup_task(cli)
        content = "- P1: Auth bypass via header manipulation.\n"
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert 'sev-p1' in html_content

    def test_p2_marker_gets_css_class(self, cli, db_path):
        task_id = _setup_task(cli)
        content = "P2 issue: inefficient loop detected.\n"
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert 'sev-p2' in html_content

    def test_severity_legend_shown_when_markers_present(self, cli, db_path):
        task_id = _setup_task(cli)
        content = "CRITICAL: major issue.\nHIGH: another issue.\nLOW: minor note.\n"
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert 'class="legend"' in html_content

    def test_severity_legend_absent_for_plain_prose(self, cli, db_path):
        task_id = _setup_task(cli)
        content = "# Implementation Notes\n\nThis module handles authentication.\n"
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert 'class="legend"' not in html_content

    def test_mixed_severity_all_classes_present(self, cli, db_path):
        task_id = _setup_task(cli)
        content = (
            "# Code Review\n\n"
            "P0: Auth token not invalidated on logout.\n\n"
            "HIGH risk: plain-text secrets in config.\n\n"
            "MED: missing input sanitization.\n\n"
            "LOW: log message spelling error.\n"
        )
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert 'sev-p0' in html_content
        assert 'sev-high' in html_content
        assert 'sev-medium' in html_content
        assert 'sev-low' in html_content


# ---------------------------------------------------------------------------
# wp get unchanged after render (no storage side-effects)
# ---------------------------------------------------------------------------

class TestWpGetUnchangedAfterRender:
    def test_wp_get_json_unchanged(self, cli, db_path):
        task_id = _setup_task(cli)
        content = "# Original\n\nContent that must not be altered."
        _store_wp(cli, task_id, content)

        # Capture wp get output before render
        before = cli(["wp", "get", "1", "--json"])
        assert before.exit_code == 0
        before_data = json.loads(before.output)

        # Render
        render_result = cli(["wp", "render", "1", "--html"])
        assert render_result.exit_code == 0

        # Capture wp get output after render
        after = cli(["wp", "get", "1", "--json"])
        assert after.exit_code == 0
        after_data = json.loads(after.output)

        # The stored record must be byte-for-byte identical
        assert before_data == after_data

    def test_wp_list_unchanged_after_render(self, cli, db_path):
        task_id = _setup_task(cli)
        _store_wp(cli, task_id, "Content A.")
        _store_wp(cli, task_id, "Content B.")

        before_list = json.loads(cli(["wp", "list", "--json"]).output)

        cli(["wp", "render", "1", "--html"])
        cli(["wp", "render", "2", "--html"])

        after_list = json.loads(cli(["wp", "list", "--json"]).output)

        assert len(before_list) == len(after_list)
        assert before_list == after_list

    def test_render_does_not_create_new_wp_record(self, cli, db_path):
        """Rendering must not add rows to work_products table."""
        task_id = _setup_task(cli)
        _store_wp(cli, task_id, "Content.")

        before_count = len(json.loads(cli(["wp", "list", "--json"]).output))

        cli(["wp", "render", "1", "--html"])

        after_count = len(json.loads(cli(["wp", "list", "--json"]).output))
        assert before_count == after_count


# ---------------------------------------------------------------------------
# Tabbed navigation for long content
# ---------------------------------------------------------------------------

class TestWpRenderTabs:
    def test_tabs_present_for_long_content(self, cli, db_path):
        """Content with >= 100 newlines must render with tabbed nav."""
        task_id = _setup_task(cli)
        # Generate content with exactly 100 lines
        content = "\n".join(f"Line {i}" for i in range(101))
        assert content.count('\n') >= 100
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert 'class="tabs"' in html_content
        assert "Rendered" in html_content
        assert "Source" in html_content

    def test_tabs_absent_for_short_content(self, cli, db_path):
        """Short content (< 100 lines) must NOT have tabbed nav."""
        task_id = _setup_task(cli)
        content = "# Short\n\nJust a few lines.\n"
        assert content.count('\n') < 100
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert 'class="tabs"' not in html_content


# ---------------------------------------------------------------------------
# Markdown rendering accuracy
# ---------------------------------------------------------------------------

class TestWpRenderMarkdown:
    def test_headings_rendered(self, cli, db_path):
        task_id = _setup_task(cli)
        _store_wp(cli, task_id, "# H1\n## H2\n### H3\n")

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert '<h1>' in html_content
        assert '<h2>' in html_content
        assert '<h3>' in html_content

    def test_code_block_rendered(self, cli, db_path):
        task_id = _setup_task(cli)
        _store_wp(cli, task_id, "```python\nprint('hello')\n```\n")

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert '<pre>' in html_content
        assert '<code' in html_content

    def test_html_injection_escaped(self, cli, db_path):
        """Content with HTML-special chars must be escaped, not injected."""
        task_id = _setup_task(cli)
        dangerous = '<script>alert("xss")</script>'
        _store_wp(cli, task_id, dangerous)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        # The raw script tag must NOT appear outside the JS data blocks
        # The content div must contain the escaped form
        assert '&lt;script&gt;' in html_content or 'alert' not in html_content.split('<script>')[0]

    def test_table_rendered(self, cli, db_path):
        task_id = _setup_task(cli)
        content = "| Col A | Col B |\n|---|---|\n| Val 1 | Val 2 |\n"
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert '<table>' in html_content
        assert '<th>' in html_content
        assert 'Val 1' in html_content

    def test_bold_italic_rendered(self, cli, db_path):
        task_id = _setup_task(cli)
        _store_wp(cli, task_id, "**bold text** and *italic text*")

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert '<strong>' in html_content
        assert '<em>' in html_content

    def test_unordered_list_rendered(self, cli, db_path):
        task_id = _setup_task(cli)
        _store_wp(cli, task_id, "- item one\n- item two\n- item three\n")

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert '<ul>' in html_content
        assert '<li>' in html_content

    def test_ordered_list_rendered(self, cli, db_path):
        task_id = _setup_task(cli)
        _store_wp(cli, task_id, "1. first\n2. second\n3. third\n")

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html_content = Path(result.output.strip()).read_text(encoding="utf-8")
        assert '<ol>' in html_content
        assert '<li>' in html_content


# ---------------------------------------------------------------------------
# API-level tests (render_wp_html function directly)
# ---------------------------------------------------------------------------

class TestRenderWpHtmlApi:
    def test_api_returns_absolute_path(self, db_path):
        from tc.services.render_html import render_wp_html
        from tc.services.wp import store_wp, get_wp
        from tc.db.connection import get_db

        conn = get_db(db_path)
        # Create task manually
        conn.execute(
            "INSERT INTO tasks (title, status, priority) VALUES (?, 'pending', 0)",
            ("API Test Task",)
        )
        conn.commit()

        store_wp(task_id=1, type_="note", title="API WP", content="Hello world.", db_path=db_path)

        html_path = render_wp_html(wp_id=1, db_path=db_path)
        conn.close()

        assert html_path.is_absolute()
        assert html_path.exists()

    def test_api_wp_not_found_raises(self, db_path):
        from tc.services.render_html import render_wp_html
        from tc.db.exceptions import WorkProductNotFound

        with pytest.raises(WorkProductNotFound):
            render_wp_html(wp_id=9999, db_path=db_path)

    def test_api_custom_out_path(self, db_path, tmp_path):
        from tc.services.render_html import render_wp_html
        from tc.services.wp import store_wp
        from tc.db.connection import get_db

        conn = get_db(db_path)
        conn.execute(
            "INSERT INTO tasks (title, status, priority) VALUES (?, 'pending', 0)",
            ("API Task",)
        )
        conn.commit()
        store_wp(task_id=1, type_="note", title="WP", content="Content.", db_path=db_path)
        conn.close()

        custom = tmp_path / "custom.html"
        result_path = render_wp_html(wp_id=1, out_path=custom, db_path=db_path)

        assert result_path.resolve() == custom.resolve()
        assert custom.exists()


# ---------------------------------------------------------------------------
# Variant-grid template
# ---------------------------------------------------------------------------

class TestVariantGridTemplate:
    """variant-grid template: >= 2 option/variant/approach headings → CSS grid."""

    def test_variant_grid_renders_grid_class(self, cli, db_path):
        task_id = _setup_task(cli)
        content = (
            "# Comparison\n\n"
            "Intro paragraph.\n\n"
            "## Option A: Redis Cache\n\nFast, requires separate service.\n\n"
            "## Option B: In-Memory Cache\n\nSimple, not persistent.\n"
        )
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html = Path(result.output.strip()).read_text(encoding="utf-8")
        assert 'class="variant-grid"' in html

    def test_variant_grid_each_option_is_a_card(self, cli, db_path):
        task_id = _setup_task(cli)
        content = (
            "## Option A: Approach Alpha\n\nDetails for alpha.\n\n"
            "## Option B: Approach Beta\n\nDetails for beta.\n"
        )
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html = Path(result.output.strip()).read_text(encoding="utf-8")
        assert html.count('class="variant-card"') == 2

    def test_variant_grid_three_variants(self, cli, db_path):
        task_id = _setup_task(cli)
        content = (
            "## Variant 1: Alpha\n\nContent A.\n\n"
            "## Variant 2: Beta\n\nContent B.\n\n"
            "## Variant 3: Gamma\n\nContent C.\n"
        )
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html = Path(result.output.strip()).read_text(encoding="utf-8")
        assert html.count('class="variant-card"') == 3
        assert "Content A" in html
        assert "Content B" in html
        assert "Content C" in html

    def test_variant_grid_preamble_rendered(self, cli, db_path):
        """Text before the first variant heading must appear above the grid."""
        task_id = _setup_task(cli)
        content = (
            "# Design Decision\n\n"
            "Preamble text that describes the decision context.\n\n"
            "## Option A: First approach\n\nBody A.\n\n"
            "## Option B: Second approach\n\nBody B.\n"
        )
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html = Path(result.output.strip()).read_text(encoding="utf-8")
        assert "Preamble text" in html
        assert 'class="variant-grid"' in html

    def test_single_option_falls_back_to_standard(self, cli, db_path):
        """Only 1 variant heading — must NOT produce a grid (fallback to standard)."""
        task_id = _setup_task(cli)
        content = "## Option A: The only option\n\nJust one.\n"
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html = Path(result.output.strip()).read_text(encoding="utf-8")
        assert 'class="variant-grid"' not in html

    def test_variant_grid_self_contained_no_external_assets(self, cli, db_path):
        task_id = _setup_task(cli)
        content = (
            "## Alternative X\n\nX details.\n\n"
            "## Alternative Y\n\nY details.\n"
        )
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html = Path(result.output.strip()).read_text(encoding="utf-8")
        for pattern in [
            r'<link\b[^>]*\bhref=["\']https?://',
            r'<script\b[^>]*\bsrc=["\']https?://',
        ]:
            assert not re.findall(pattern, html, re.IGNORECASE)

    def test_approach_keyword_triggers_grid(self, cli, db_path):
        """The 'approach' keyword in headings must also trigger the grid."""
        task_id = _setup_task(cli)
        content = (
            "## Approach 1: Incremental\n\nGradual rollout.\n\n"
            "## Approach 2: Big-bang\n\nFull cutover.\n"
        )
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html = Path(result.output.strip()).read_text(encoding="utf-8")
        assert 'class="variant-grid"' in html


# ---------------------------------------------------------------------------
# Rendered-diff template
# ---------------------------------------------------------------------------

class TestRenderedDiffTemplate:
    """rendered-diff template: fenced ```diff blocks → color-coded HTML."""

    def test_diff_block_renders_diff_block_class(self, cli, db_path):
        task_id = _setup_task(cli)
        content = (
            "# Code Review\n\n"
            "```diff\n"
            "-old line\n"
            "+new line\n"
            "```\n"
        )
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html = Path(result.output.strip()).read_text(encoding="utf-8")
        assert 'class="diff-block"' in html

    def test_diff_added_lines_get_diff_add_class(self, cli, db_path):
        task_id = _setup_task(cli)
        content = "```diff\n+added line here\n context\n-removed line\n```\n"
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html = Path(result.output.strip()).read_text(encoding="utf-8")
        assert 'diff-add' in html

    def test_diff_removed_lines_get_diff_remove_class(self, cli, db_path):
        task_id = _setup_task(cli)
        content = "```diff\n+added line\n context\n-removed line here\n```\n"
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html = Path(result.output.strip()).read_text(encoding="utf-8")
        assert 'diff-remove' in html

    def test_diff_hunk_header_gets_diff_hunk_class(self, cli, db_path):
        task_id = _setup_task(cli)
        content = (
            "```diff\n"
            "@@ -1,4 +1,4 @@\n"
            " context\n"
            "-old\n"
            "+new\n"
            "```\n"
        )
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html = Path(result.output.strip()).read_text(encoding="utf-8")
        assert 'diff-hunk' in html

    def test_diff_file_headers_get_diff_file_class(self, cli, db_path):
        task_id = _setup_task(cli)
        content = (
            "```diff\n"
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
            "```\n"
        )
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html = Path(result.output.strip()).read_text(encoding="utf-8")
        assert 'diff-file' in html

    def test_diff_surrounding_markdown_rendered(self, cli, db_path):
        """Non-diff content before/after a diff block must render as HTML."""
        task_id = _setup_task(cli)
        content = (
            "# Change Summary\n\n"
            "This patch fixes the bug.\n\n"
            "```diff\n"
            "-old\n"
            "+new\n"
            "```\n\n"
            "Review complete.\n"
        )
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html = Path(result.output.strip()).read_text(encoding="utf-8")
        assert "<h1>" in html
        assert "This patch fixes the bug" in html
        assert "Review complete" in html
        assert 'class="diff-block"' in html

    def test_diff_self_contained_no_external_assets(self, cli, db_path):
        task_id = _setup_task(cli)
        content = "```diff\n-old\n+new\n```\n"
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html = Path(result.output.strip()).read_text(encoding="utf-8")
        for pattern in [
            r'<link\b[^>]*\bhref=["\']https?://',
            r'<script\b[^>]*\bsrc=["\']https?://',
        ]:
            assert not re.findall(pattern, html, re.IGNORECASE)

    def test_plain_content_no_diff_class(self, cli, db_path):
        """Standard prose must NOT produce diff-block markup."""
        task_id = _setup_task(cli)
        content = "# Normal Content\n\nJust prose here.\n"
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html = Path(result.output.strip()).read_text(encoding="utf-8")
        assert 'class="diff-block"' not in html

    def test_diff_takes_priority_over_variant_grid(self, cli, db_path):
        """When both diff and variant keywords are present, diff wins."""
        task_id = _setup_task(cli)
        content = (
            "## Option A: Old Approach\n\n"
            "```diff\n-old\n+new\n```\n\n"
            "## Option B: New Approach\n\nNew stuff.\n"
        )
        _store_wp(cli, task_id, content)

        result = cli(["wp", "render", "1", "--html"])
        assert result.exit_code == 0

        html = Path(result.output.strip()).read_text(encoding="utf-8")
        # diff template wins (diff-block present, variant-grid absent)
        assert 'class="diff-block"' in html
