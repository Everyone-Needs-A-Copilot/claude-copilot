# ADR-004: HTML as a Work-Product Output Format

**Diátaxis mode:** Explanation (architectural decision record)

**Status:** Accepted
**Date:** 2026-06-25
**Deciders:** Pablo Alejo
**Component:** Task Copilot (`tc`) — work-product rendering

---

## Context

Work products stored in Task Copilot carry their content as Markdown text (inline in SQLite for small payloads; file-referenced in `.copilot/wp/` above 8 KB). `tc wp get` returns this text to the context window.

Two usage patterns create friction with text-only output:

1. **Review mode.** QA agents and human reviewers scan adversarial reports, implementation notes, and design comparisons that contain tables, severity ladders, code diffs, and side-by-side option grids. Plain Markdown in a terminal is hard to parse visually; every call to `tc wp get` floods the context window with the full payload.

2. **Attribution and handoff.** When sharing a work product outside the agent chain (peer review, async stakeholder review), Markdown requires a separate renderer. Embedding rendered output into the context window is the wrong delivery channel.

### Prior art that informed this decision

- **gstack by Garry Tan** (`github.com/garrytan/gstack`, MIT): introduced the `/design-html` command pattern — producing a fully self-contained HTML file as the output of a design pass rather than returning raw text. The key insight: a side-artifact file is zero-cost to generate and zero-cost to the context window.
- **"The Unreasonable Effectiveness of HTML" by Thariq Shihipar** (Anthropic Engineering Blog): demonstrated that HTML-as-output with "Copy as Markdown/JSON" buttons and variant-comparison grids gives reviewers a richer, more navigable surface than plain text — and that this pattern fits naturally into AI-assisted workflows. Specific influences: copy-as-Markdown buttons, copy-as-JSON buttons, and variant/option grid layouts.

We reimplemented both ideas natively in Python; no code was copied.

---

## Decision

Add `tc wp render <id> --html` as a **token-free side artifact** command that:

1. Reads the work product via `get_wp()` (no storage side-effects).
2. Renders it to a fully self-contained HTML file at `.copilot/renders/WP-<id>.html` (inline CSS, vanilla JS, no CDN, no external assets).
3. Returns only the absolute file path to stdout — the HTML body never enters the context window.
4. Does NOT change what `tc wp get`, `list_wps`, or any storage function returns to callers.

**Auto-detected templates** keep the renderer zero-configuration:

| Template | Detection rule | Added capability |
|----------|---------------|-----------------|
| Severity | P0/P1/P2 or CRITICAL/HIGH/MEDIUM/LOW markers in content | Color-coded severity rows, legend |
| Variant grid | ≥ 2 headings containing option/variant/alternative/approach/solution | Tabbed side-by-side comparison |
| Rendered diff | ` ```diff ` block or ≥ 3 standalone `+`/`-` diff lines | Syntax-highlighted diff viewer |

All renders include "Copy as Markdown" and "Copy as JSON" buttons (`navigator.clipboard.writeText`). Content with ≥ 100 newlines gets a Rendered / Source tab switcher.

Implementation: `tools/tc/src/tc/services/render_html.py` (zero new PyPI dependencies — pure-Python line-by-line Markdown converter with `html.escape()` safety and `<script>` JSON-encoding).

---

## Alternatives Rejected

| Alternative | Reason rejected |
|-------------|----------------|
| **Return rendered HTML in stdout** | Defeats the purpose — would flood the context window with 10–100 KB of markup. The value is the side-artifact pattern, not the HTML per se. |
| **Use a third-party Markdown-to-HTML library (mistune, markdown2, etc.)** | Adds a PyPI dependency to `tc`, which is intentionally minimal. The line-by-line converter covers the subset actually used in work products (headings, tables, fenced code, bold/italic, links, lists). |
| **Render to PDF** | Requires headless browser or WeasyPrint; heavyweight for an agent-side tool. HTML achieves the same review goal without binary dependencies. |
| **Extend `tc wp get --html`** | Would change the contract of `tc wp get`, which callers depend on for text. A separate `render` subcommand keeps the contracts separate and makes the side-artifact nature explicit. |

---

## Consequences

**Positive:**
- Context window impact of rendering is zero (only a path string enters context).
- Renders are reusable across sessions — `.copilot/renders/` persists with the project.
- No new runtime dependencies.
- Token-free contract is explicit: `render_wp_html` never writes to the `work_products` table.
- The pattern extends naturally to future templates (e.g., test-results, threat-model grids) without changing the CLI surface.

**Negative / risks:**
- Renders can go stale if the work product is updated after rendering. The render path is deterministic (`WP-<id>.html`) so callers can always re-run to refresh.
- `navigator.clipboard` requires HTTPS or localhost in modern browsers. A graceful fallback message is displayed when the API is unavailable (e.g., `file://` protocol).

---

## References

- **gstack** by Garry Tan — `github.com/garrytan/gstack` (MIT) — inspiration for the `/design-html` side-artifact pattern, `/careful`+`/freeze` safety primitives, cross-model adversarial review, and the Confusion Protocol. We adopted the core concepts natively; no code was copied.
- **"The Unreasonable Effectiveness of HTML"** by Thariq Shihipar (Anthropic Engineering Blog) — inspiration for HTML-as-output-format with copy-as-Markdown/JSON buttons and variant-grid layouts.
- Implementation WPs: WP-152 (HTML renderer), WP-158 (variant-grid + rendered-diff templates)
- CHANGELOG: 5.11.0
