"""tc.services.render_html — render a work product to a standalone HTML file.

Output path convention:
    <project-root>/.copilot/renders/WP-<id>.html

Where ``.copilot/`` is the directory that holds ``tasks.db``.  The HTML file
is completely self-contained: inline CSS only, vanilla JS only, no external
assets, no CDN references.  The caller receives only the absolute file path
so the rendered HTML never flows back into the main-session context window
(TOKEN-FREE SIDE ARTIFACT).

This module does NOT alter the work-product storage format and does NOT change
what ``get_wp`` / ``list_wps`` return to callers.
"""

from __future__ import annotations

import html as _html
import json as _json
import re
import sqlite3
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Template auto-detection
# ---------------------------------------------------------------------------

# Variant-grid: heading containing an "option/variant/alternative/approach/solution" keyword
_VARIANT_HEADING_RE = re.compile(
    r'^#{1,4}\s+.*\b(option|variant|alternative|approach|solution)\b',
    re.IGNORECASE | re.MULTILINE,
)

# Rendered-diff: a fenced ```diff block, OR 3+ standalone diff lines (+x / -x, not +++ / ---)
_DIFF_FENCE_RE = re.compile(r'```diff\s*\n(.*?)```', re.DOTALL | re.IGNORECASE)
_DIFF_LINE_RE = re.compile(r'^[+-](?![+-])', re.MULTILINE)


def _has_variant_grid(text: str) -> bool:
    """True when the content has >= 2 variant/option headings."""
    return len(_VARIANT_HEADING_RE.findall(text)) >= 2


def _has_diff(text: str) -> bool:
    """True when the content contains a ```diff block or >= 3 diff-formatted lines."""
    if _DIFF_FENCE_RE.search(text):
        return True
    return len(_DIFF_LINE_RE.findall(text)) >= 3


# ---------------------------------------------------------------------------
# Severity detection
# ---------------------------------------------------------------------------

_SEV_RE = re.compile(r'\b(CRITICAL|HIGH|MEDIUM|MED|LOW|P0|P1|P2)\b')

_SEV_CLASS: dict[str, str] = {
    'CRITICAL': 'sev-critical',
    'HIGH': 'sev-high',
    'MEDIUM': 'sev-medium',
    'MED': 'sev-medium',
    'LOW': 'sev-low',
    'P0': 'sev-p0',
    'P1': 'sev-p1',
    'P2': 'sev-p2',
}


def _sev_class(text: str) -> Optional[str]:
    """Return the CSS severity class for the first marker in *text*, or None."""
    m = _SEV_RE.search(text.upper())
    return _SEV_CLASS.get(m.group(1)) if m else None


def _has_severity(text: str) -> bool:
    return bool(_SEV_RE.search(text.upper()))


# ---------------------------------------------------------------------------
# Inline markdown → HTML
# ---------------------------------------------------------------------------

_CODE_SPAN_RE = re.compile(r'`([^`]+)`')
_BOLD_RE = re.compile(r'\*\*([^*\n]+)\*\*')
_ITALIC_RE = re.compile(r'\*([^*\n]+)\*')
_LINK_RE = re.compile(r'\[([^\]]*)\]\(([^)]*)\)')


def _inline(raw: str) -> str:
    """Convert raw inline markdown text to safe HTML.

    Processing order:
    1. Split on backtick code spans — code content is HTML-escaped only.
    2. For each non-code segment: HTML-escape, then apply bold / italic / links.

    This ordering ensures code span contents are never processed as markdown,
    and HTML-special characters in regular text are escaped before the markdown
    substitution patterns (which use only ``*`` and ``[]()`` — all safe after
    ``html.escape``).
    """
    segments = _CODE_SPAN_RE.split(raw)
    parts: list[str] = []
    for i, seg in enumerate(segments):
        if i % 2 == 1:
            # Odd segments are the captured code span contents.
            parts.append(f'<code>{_html.escape(seg)}</code>')
        else:
            s = _html.escape(seg)
            s = _BOLD_RE.sub(r'<strong>\1</strong>', s)
            s = _ITALIC_RE.sub(r'<em>\1</em>', s)
            s = _LINK_RE.sub(r'<a href="\2">\1</a>', s)
            parts.append(s)
    return ''.join(parts)


# ---------------------------------------------------------------------------
# Block-level markdown → HTML
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r'^(#{1,6})\s+(.*)')
_UL_RE = re.compile(r'^[-*+]\s')
_OL_RE = re.compile(r'^\d+\.\s')
_TABLE_RE = re.compile(r'^\|')
_SEP_ROW_RE = re.compile(r'^[-:|]+$')


def _is_block_start(line: str) -> bool:
    """True when *line* opens a new structural block."""
    s = line.lstrip()
    return bool(
        s.startswith('#')
        or s.startswith('```')
        or _TABLE_RE.match(s)
        or _UL_RE.match(s)
        or _OL_RE.match(s)
    )


def _render_table(rows: list[str]) -> str:
    """Convert markdown table lines to an HTML ``<table>``."""
    if not rows:
        return ''
    cells = [
        [c.strip() for c in r.strip().strip('|').split('|')]
        for r in rows
    ]
    header = cells[0]
    body_start = 1
    # Skip the separator row (e.g., ``|---|---|``)
    if len(cells) > 1 and all(_SEP_ROW_RE.match(c.strip()) for c in cells[1] if c.strip()):
        body_start = 2

    thead = '<tr>' + ''.join(f'<th>{_inline(c)}</th>' for c in header) + '</tr>'
    tbody_rows = [
        '<tr>' + ''.join(f'<td>{_inline(c)}</td>' for c in row) + '</tr>'
        for row in cells[body_start:]
    ]
    return (
        '<table><thead>' + thead + '</thead>'
        '<tbody>' + ''.join(tbody_rows) + '</tbody></table>'
    )


def _md_to_html(text: str) -> str:  # noqa: C901
    """Convert a markdown string to an HTML fragment.

    Handles: ATX headings, fenced code blocks, unordered/ordered lists,
    tables, paragraphs, inline code, bold, italic, and links.
    Severity markers (CRITICAL/HIGH/MED/LOW/P0/P1/P2) found in paragraphs
    and list items are wrapped with the matching ``sev-*`` CSS class.
    """
    lines = text.split('\n')
    out: list[str] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # ── fenced code block ────────────────────────────────────────────────
        if stripped.startswith('```'):
            lang = stripped[3:].strip()
            code_lines: list[str] = []
            i += 1
            while i < n and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            i += 1  # consume closing ```
            code_text = '\n'.join(code_lines)
            lang_attr = (
                f' class="language-{_html.escape(lang)}"' if lang else ''
            )
            out.append(
                f'<pre><code{lang_attr}>{_html.escape(code_text)}</code></pre>'
            )
            continue

        # ── ATX heading ──────────────────────────────────────────────────────
        m = _HEADING_RE.match(line)
        if m:
            lvl = len(m.group(1))
            out.append(f'<h{lvl}>{_inline(m.group(2))}</h{lvl}>')
            i += 1
            continue

        # ── table ────────────────────────────────────────────────────────────
        if '|' in stripped and _TABLE_RE.match(stripped):
            tbl: list[str] = []
            while i < n and '|' in lines[i] and _TABLE_RE.match(lines[i].strip()):
                tbl.append(lines[i])
                i += 1
            out.append(_render_table(tbl))
            continue

        # ── unordered list ───────────────────────────────────────────────────
        if _UL_RE.match(stripped):
            items: list[str] = []
            while i < n and _UL_RE.match(lines[i].strip()):
                item_text = re.sub(r'^[-*+]\s+', '', lines[i].strip())
                sev = _sev_class(item_text)
                cls = f' class="{sev}"' if sev else ''
                items.append(f'<li{cls}>{_inline(item_text)}</li>')
                i += 1
            out.append('<ul>' + ''.join(items) + '</ul>')
            continue

        # ── ordered list ─────────────────────────────────────────────────────
        if _OL_RE.match(stripped):
            items = []
            while i < n and _OL_RE.match(lines[i].strip()):
                item_text = re.sub(r'^\d+\.\s+', '', lines[i].strip())
                sev = _sev_class(item_text)
                cls = f' class="{sev}"' if sev else ''
                items.append(f'<li{cls}>{_inline(item_text)}</li>')
                i += 1
            out.append('<ol>' + ''.join(items) + '</ol>')
            continue

        # ── blank line ───────────────────────────────────────────────────────
        if not stripped:
            i += 1
            continue

        # ── paragraph ────────────────────────────────────────────────────────
        para_lines: list[str] = []
        while i < n and lines[i].strip() and not _is_block_start(lines[i]):
            para_lines.append(lines[i].strip())
            i += 1
        if para_lines:
            para_text = ' '.join(para_lines)
            sev = _sev_class(para_text)
            p_html = f'<p>{_inline(para_text)}</p>'
            if sev:
                p_html = f'<div class="{sev}">{p_html}</div>'
            out.append(p_html)
        else:
            i += 1  # safety skip to prevent infinite loop

    return '\n'.join(out)


# ---------------------------------------------------------------------------
# Variant-grid rendering
# ---------------------------------------------------------------------------


def _render_variant_grid(text: str) -> str:
    """Split content at variant headings and render each section as a grid card.

    Lines before the first variant heading are rendered as a preamble above
    the grid.  If fewer than 2 variant headings are found, falls back to
    standard markdown rendering.
    """
    lines = text.split('\n')
    preamble: list[str] = []
    sections: list[tuple[str, list[str]]] = []  # (heading_line, body_lines)
    current_heading: str | None = None
    current_body: list[str] = []

    for line in lines:
        if _VARIANT_HEADING_RE.match(line):
            if current_heading is not None:
                sections.append((current_heading, current_body))
            elif current_body:
                preamble = current_body[:]
            current_heading = line
            current_body = []
        else:
            current_body.append(line)

    if current_heading is not None:
        sections.append((current_heading, current_body))
    elif not sections:
        preamble = current_body

    if len(sections) < 2:
        return _md_to_html(text)

    preamble_html = _md_to_html('\n'.join(preamble).strip()) if any(l.strip() for l in preamble) else ''

    cards: list[str] = []
    for heading, body_lines in sections:
        heading_html = _md_to_html(heading)
        body_html = _md_to_html('\n'.join(body_lines).strip()) if any(l.strip() for l in body_lines) else ''
        cards.append(f'<div class="variant-card">{heading_html}{body_html}</div>')

    grid_html = '<div class="variant-grid">' + '\n'.join(cards) + '</div>'
    return (preamble_html + '\n' + grid_html) if preamble_html else grid_html


# ---------------------------------------------------------------------------
# Rendered-diff rendering
# ---------------------------------------------------------------------------


def _render_diff_line(line: str) -> str:
    """Wrap a single raw diff line with the appropriate CSS class span."""
    escaped = _html.escape(line)
    if line.startswith('@@'):
        return f'<span class="diff-line diff-hunk">{escaped}</span>'
    if line.startswith('+++') or line.startswith('---'):
        return f'<span class="diff-line diff-file">{escaped}</span>'
    if line.startswith('+'):
        return f'<span class="diff-line diff-add">{escaped}</span>'
    if line.startswith('-'):
        return f'<span class="diff-line diff-remove">{escaped}</span>'
    return f'<span class="diff-line">{escaped}</span>'


def _render_diff_block(diff_text: str) -> str:
    """Render a raw diff string as a color-coded HTML block."""
    rendered = ''.join(_render_diff_line(l) for l in diff_text.split('\n'))
    return f'<div class="diff-block">{rendered}</div>'


def _render_diff_content(text: str) -> str:
    """Replace fenced ```diff blocks with color-coded HTML; render remainder as markdown."""
    parts: list[str] = []
    last_end = 0
    for m in _DIFF_FENCE_RE.finditer(text):
        before = text[last_end:m.start()]
        if before.strip():
            parts.append(_md_to_html(before))
        parts.append(_render_diff_block(m.group(1)))
        last_end = m.end()
    after = text[last_end:]
    if after.strip():
        parts.append(_md_to_html(after))
    return '\n'.join(parts)


# ---------------------------------------------------------------------------
# HTML page template
# ---------------------------------------------------------------------------

_CSS = """\
:root{--bg:#fff;--sf:#f8f9fa;--bd:#dee2e6;--tx:#212529;--mu:#6c757d;\
--co:#f1f3f4;--lk:#0d6efd;--rc:#dc3545;--rh:#fd7e14;--rm:#ffc107;--rl:#198754}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;\
font-size:15px;line-height:1.6;color:var(--tx);background:var(--bg);\
padding:2rem;max-width:920px;margin:0 auto}
header{margin-bottom:1.5rem;padding-bottom:1rem;border-bottom:2px solid var(--bd)}
header h1{font-size:1.4rem;margin-bottom:.5rem}
.meta{display:flex;flex-wrap:wrap;gap:1rem;font-size:.83rem;color:var(--mu);margin-bottom:.75rem}
.actions{display:flex;gap:.5rem;flex-wrap:wrap}
.btn{display:inline-flex;align-items:center;padding:.35rem .75rem;\
font-size:.82rem;border:1px solid var(--bd);border-radius:6px;\
background:var(--sf);color:var(--tx);cursor:pointer;transition:background .15s;\
font-family:inherit}
.btn:hover{background:var(--bd)}
.tabs{display:flex;margin-bottom:1rem;border-bottom:1px solid var(--bd)}
.tab-btn{padding:.5rem 1rem;font-size:.9rem;border:none;\
border-bottom:2px solid transparent;background:none;color:var(--mu);\
cursor:pointer;margin-bottom:-1px;font-family:inherit}
.tab-btn.active{color:var(--tx);border-bottom-color:var(--lk);font-weight:500}
.tab-pane{display:none}.tab-pane.active{display:block}
.content h1,.content h2,.content h3,.content h4,.content h5,.content h6\
{margin:1.2rem 0 .45rem;line-height:1.3}
.content h1{font-size:1.6rem}
.content h2{font-size:1.3rem;border-bottom:1px solid var(--bd);padding-bottom:.2rem}
.content h3{font-size:1.1rem}
.content p{margin:.6rem 0}
.content ul,.content ol{margin:.6rem 0 .6rem 1.5rem}
.content li{margin:.2rem 0}
.content code{background:var(--co);padding:.1rem .35rem;border-radius:3px;\
font-family:"SFMono-Regular",Consolas,monospace;font-size:.875em}
.content pre{background:var(--sf);border:1px solid var(--bd);border-radius:6px;\
padding:.85rem 1rem;overflow-x:auto;margin:.6rem 0}
.content pre code{background:none;padding:0;font-size:.875rem}
.content a{color:var(--lk);text-decoration:underline}
.content strong{font-weight:600}
.content table{width:100%;border-collapse:collapse;margin:.6rem 0;font-size:.9rem}
.content th{background:var(--sf);font-weight:600;text-align:left}
.content th,.content td{padding:.45rem .7rem;border:1px solid var(--bd)}
.content tr:nth-child(even) td{background:var(--sf)}
.sev-critical,.sev-p0{background:#fff5f5;border-left:4px solid var(--rc);\
padding:.4rem .7rem;margin:.35rem 0;border-radius:0 4px 4px 0}
.sev-high,.sev-p1{background:#fff8f0;border-left:4px solid var(--rh);\
padding:.4rem .7rem;margin:.35rem 0;border-radius:0 4px 4px 0}
.sev-medium,.sev-p2{background:#fffdf0;border-left:4px solid var(--rm);\
padding:.4rem .7rem;margin:.35rem 0;border-radius:0 4px 4px 0}
.sev-low{background:#f0fff4;border-left:4px solid var(--rl);\
padding:.4rem .7rem;margin:.35rem 0;border-radius:0 4px 4px 0}
.legend{display:flex;flex-wrap:wrap;align-items:center;gap:.75rem;\
margin-bottom:1rem;padding:.55rem .75rem;background:var(--sf);\
border-radius:6px;font-size:.8rem}
.leg-item{display:flex;align-items:center;gap:.3rem}
.leg-dot{width:9px;height:9px;border-radius:50%;display:inline-block}
.dot-c{background:var(--rc)}.dot-h{background:var(--rh)}
.dot-m{background:var(--rm)}.dot-l{background:var(--rl)}
.src{font-family:"SFMono-Regular",Consolas,monospace;font-size:.875rem;\
line-height:1.5;white-space:pre-wrap;word-break:break-word;padding:1rem;\
background:var(--sf);border:1px solid var(--bd);border-radius:6px}
.toast{position:fixed;bottom:1.5rem;right:1.5rem;background:#333;color:#fff;\
padding:.55rem 1rem;border-radius:6px;font-size:.875rem;opacity:0;\
transition:opacity .2s;pointer-events:none;z-index:9999}
.toast.show{opacity:1}
.variant-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));\
gap:1.25rem;margin:1rem 0}
.variant-card{border:1px solid var(--bd);border-radius:8px;padding:1rem;\
background:var(--sf)}
.variant-card h1,.variant-card h2,.variant-card h3,.variant-card h4\
{margin-top:0;padding-bottom:.35rem;border-bottom:2px solid var(--lk);\
color:var(--lk);font-size:1rem}
.diff-block{font-family:"SFMono-Regular",Consolas,monospace;font-size:.875rem;\
border:1px solid var(--bd);border-radius:6px;overflow-x:auto;margin:.6rem 0;\
background:#fafafa;line-height:1.4}
.diff-line{padding:.05rem .5rem;display:block;white-space:pre}
.diff-add{background:#e6ffed;color:#22863a}
.diff-remove{background:#ffeef0;color:#b31d28}
.diff-hunk{background:#dbedff;color:#005cc5;font-weight:600}
.diff-file{color:var(--mu);font-weight:600}\
"""


def _js_str(value: str) -> str:
    """JSON-encode *value* for safe embedding inside a ``<script>`` block."""
    # Replace '</' to prevent premature ``</script>`` tag closure.
    return _json.dumps(value, ensure_ascii=False).replace('</', '<\\/')


def _build_html_page(wp: dict[str, Any], content: str) -> str:
    """Assemble the complete standalone HTML document for *wp*."""
    wp_id = wp.get('id', '?')
    title = wp.get('title') or 'Untitled'
    wp_type = wp.get('type') or ''
    task_id = wp.get('task_id', '')
    agent = wp.get('agent') or ''
    created_at = str(wp.get('created_at') or '')

    title_e = _html.escape(title)
    type_e = _html.escape(wp_type)
    agent_span = (
        f'<span><strong>Agent:</strong> {_html.escape(agent)}</span>'
        if agent else ''
    )

    use_tabs = content.count('\n') >= 100
    show_legend = _has_severity(content)

    # Auto-select template: diff > variant-grid > standard
    if _has_diff(content):
        rendered_body = _render_diff_content(content)
    elif _has_variant_grid(content):
        rendered_body = _render_variant_grid(content)
    else:
        rendered_body = _md_to_html(content)

    legend_html = ''
    if show_legend:
        legend_html = (
            '<div class="legend"><strong>Severity:</strong>'
            '<span class="leg-item"><span class="leg-dot dot-c"></span>CRITICAL / P0</span>'
            '<span class="leg-item"><span class="leg-dot dot-h"></span>HIGH / P1</span>'
            '<span class="leg-item"><span class="leg-dot dot-m"></span>MEDIUM / P2</span>'
            '<span class="leg-item"><span class="leg-dot dot-l"></span>LOW</span>'
            '</div>'
        )

    if use_tabs:
        tabs_nav = (
            '<nav class="tabs">'
            '<button class="tab-btn active" data-tab="rendered" '
            'onclick="showTab(\'rendered\')">Rendered</button>'
            '<button class="tab-btn" data-tab="source" '
            'onclick="showTab(\'source\')">Source</button>'
            '</nav>'
        )
        main_html = (
            tabs_nav
            + f'<div id="tab-rendered" class="tab-pane active">'
            + legend_html
            + f'<div class="content">{rendered_body}</div></div>'
            + f'<div id="tab-source" class="tab-pane">'
            + f'<pre class="src">{_html.escape(content)}</pre></div>'
        )
        tab_js = (
            'function showTab(n){'
            'document.querySelectorAll(".tab-btn")'
            '.forEach(b=>b.classList.toggle("active",b.dataset.tab===n));'
            'document.querySelectorAll(".tab-pane")'
            '.forEach(p=>p.classList.toggle("active",p.id==="tab-"+n));'
            '}'
        )
    else:
        main_html = (
            legend_html
            + f'<div class="content">{rendered_body}</div>'
        )
        tab_js = ''

    # Build JSON payload for "Copy as JSON" button (include resolved content).
    wp_copy = dict(wp)
    wp_copy['content'] = content
    wp_json_str = _json.dumps(wp_copy, indent=2, default=str)

    md_js = _js_str(content)
    json_js = _js_str(wp_json_str)

    script = f"""\
const MD={md_js};
const WPJSON={json_js};
function toast(m){{const t=document.getElementById('toast');t.textContent=m;\
t.classList.add('show');setTimeout(()=>t.classList.remove('show'),1800);}}
function copyMd(){{if(!navigator.clipboard){{toast('Clipboard unavailable');return;}}\
navigator.clipboard.writeText(MD).then(()=>toast('Copied as Markdown ✓'))\
.catch(()=>toast('Copy failed — check permissions'));}}
function copyJson(){{if(!navigator.clipboard){{toast('Clipboard unavailable');return;}}\
navigator.clipboard.writeText(WPJSON).then(()=>toast('Copied as JSON ✓'))\
.catch(()=>toast('Copy failed — check permissions'));}}
{tab_js}"""

    return (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n'
        '<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f'<title>WP-{wp_id}: {title_e}</title>\n'
        f'<style>{_CSS}</style>\n'
        '</head>\n'
        '<body>\n'
        '<header>\n'
        f'<h1>WP-{wp_id}: {title_e}</h1>\n'
        '<div class="meta">'
        f'<span><strong>Type:</strong> {type_e}</span>'
        f'<span><strong>Task:</strong> #{task_id}</span>'
        f'{agent_span}'
        f'<span><strong>Created:</strong> {_html.escape(created_at)}</span>'
        '</div>\n'
        '<div class="actions">'
        '<button class="btn" onclick="copyMd()">Copy as Markdown</button>'
        '<button class="btn" onclick="copyJson()">Copy as JSON</button>'
        '</div>\n'
        '</header>\n'
        + main_html + '\n'
        '<div class="toast" id="toast"></div>\n'
        f'<script>{script}</script>\n'
        '</body>\n'
        '</html>'
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_wp_html(
    *,
    wp_id: int,
    out_path: Optional[Path] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> Path:
    """Render work product *wp_id* to a self-contained HTML file on disk.

    This is a TOKEN-FREE SIDE ARTIFACT: the HTML is written to disk and the
    caller receives only the absolute ``Path``.  It does NOT alter stored
    work products or change what ``get_wp`` / ``list_wps`` return.

    Output path convention (when *out_path* is omitted):
        ``<db_parent>/renders/WP-<id>.html``
    where ``<db_parent>`` is the ``.copilot/`` directory that holds
    ``tasks.db``.  Example: ``.copilot/renders/WP-42.html``.

    Args:
        wp_id:    Work product ID to render.
        out_path: Override the output file path.
        conn:     Existing DB connection (not opened/closed by this function).
        db_path:  Explicit DB path; walked up from ``cwd`` if ``None``.

    Returns:
        Absolute ``Path`` to the written HTML file.

    Raises:
        WorkProductNotFound: if *wp_id* does not exist.
        FileNotFoundError:   if no DB is found and *db_path* is None.
    """
    from tc.services.wp import get_wp

    # Resolve DB path (needed for the renders directory and for get_wp).
    resolved_db: Optional[Path]
    if db_path is not None:
        resolved_db = db_path
    else:
        from tc.db.connection import find_db_path
        resolved_db = find_db_path()

    # Fetch the work product (raises WorkProductNotFound if missing).
    wp = get_wp(wp_id=wp_id, db_path=resolved_db)
    content: str = wp.get('content') or ''

    # Determine the output file path.
    if out_path is not None:
        html_path = Path(out_path)
    elif resolved_db is not None:
        renders_dir = resolved_db.parent / 'renders'
        renders_dir.mkdir(parents=True, exist_ok=True)
        html_path = renders_dir / f'WP-{wp_id}.html'
    else:
        html_path = Path.cwd() / f'WP-{wp_id}.html'

    html_path.parent.mkdir(parents=True, exist_ok=True)

    page = _build_html_page(wp, content)
    html_path.write_text(page, encoding='utf-8')

    return html_path.resolve()
