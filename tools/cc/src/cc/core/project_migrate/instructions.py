"""Thin CLAUDE.md / AGENTS.md: remove the managed block and byte-matched template sections.

A file is split into segments: `## ` heading sections (code fences respected),
`<!-- name:start -->` ... `<!-- name:end -->` blocks, and anonymous text between
them. A segment is removed only when

* it is a `cc:project-integration:*` managed block (delimited by the framework's own
  markers), or
* its text equals, after trailing-whitespace trimming, a section of a known framework
  template with the same key.

Anything else, including a framework heading whose body was edited, is kept; the
edited framework-headed ones are reported as holds.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from cc.core.project_init.sections import SECTION_BEGIN, SECTION_END

_START = re.compile(r"^<!--\s*(\S+?):start(?:\s[^>]*)?\s*-->\s*$")
_END = re.compile(r"^<!--\s*(\S+?):end(?:\s[^>]*)?\s*-->\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
MANAGED_PREFIX = "cc:project-integration:"
# Headings that are project-owned in the templates, never framework text.
_PROJECT_HEADING = re.compile(r"^##\s+Project\b", re.IGNORECASE)


@dataclass
class Segment:
    key: Optional[str]   # "## Heading", "<!-- name -->", or None for anonymous text
    text: str            # exact original text, newlines included

    @property
    def managed(self) -> bool:
        return bool(self.key and self.key.startswith("<!-- " + MANAGED_PREFIX))


def _key_for_heading(line: str) -> str:
    return line.strip()


def split_segments(text: str) -> list[Segment]:
    lines = text.splitlines(keepends=True)
    segments: list[Segment] = []
    cur_key: Optional[str] = None
    cur: list[str] = []
    in_fence = False
    block_name: Optional[str] = None

    def flush() -> None:
        nonlocal cur, cur_key
        if cur:
            segments.append(Segment(cur_key, "".join(cur)))
        cur, cur_key = [], None

    for line in lines:
        if block_name is not None:
            cur.append(line)
            m = _END.match(line.rstrip("\n"))
            if m and m.group(1) == block_name:
                flush()
                block_name = None
            continue
        stripped = line.rstrip("\n")
        if _FENCE.match(stripped):
            in_fence = not in_fence
        if not in_fence:
            m = _START.match(stripped)
            if m:
                flush()
                block_name = m.group(1)
                cur_key = f"<!-- {block_name} -->"
                cur.append(line)
                continue
            if stripped.startswith("## "):
                flush()
                cur_key = _key_for_heading(stripped)
                cur.append(line)
                continue
            if stripped == SECTION_BEGIN:
                flush()
                block_name = "__thin__"
                cur_key = "<!-- copilot:thin -->"
                cur.append(line)
                continue
        cur.append(line)
    flush()
    # An unterminated block is not a block: demote to anonymous so nothing is removed.
    if block_name is not None and segments:
        last = segments[-1]
        segments[-1] = Segment(None, last.text)
    return segments


def _norm(text: str) -> str:
    return text.rstrip()


def history_digest(text: str) -> str:
    """Hash of a section ignoring line wrapping and spacing (older releases wrapped differently)."""
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()


def known_sections_from_text(text: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for seg in split_segments(text):
        if not seg.key or _PROJECT_HEADING.match(seg.key) or seg.key == "<!-- copilot:thin -->":
            continue
        if seg.key.startswith("<!-- ") and not seg.managed and not seg.key.startswith("<!-- cse-"):
            continue
        out.setdefault(seg.key, set()).add(_norm(seg.text))
    return out


def known_sections_from_files(paths: Iterable[Path]) -> dict[str, set[str]]:
    merged: dict[str, set[str]] = {}
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for k, v in known_sections_from_text(text).items():
            merged.setdefault(k, set()).update(v)
    return merged


@dataclass
class ThinResult:
    new_text: str
    removed: list[str]        # keys removed
    held: list[tuple[str, str]]  # (key, reason)
    changed: bool


def thin_text(text: str, known: dict[str, set[str]],
              known_hashes: Optional[dict[str, set[str]]] = None) -> ThinResult:
    segments = split_segments(text)
    kept: list[Segment] = []
    removed: list[str] = []
    held: list[tuple[str, str]] = []
    hashes = known_hashes or {}
    for seg in segments:
        key = seg.key
        if key is None or key == "<!-- copilot:thin -->":
            kept.append(seg)
            continue
        if seg.managed:
            removed.append(key)
            continue
        body = _norm(seg.text)
        if key in known and body in known[key]:
            removed.append(key)
            continue
        if key in hashes and history_digest(body) in hashes[key]:
            removed.append(key)  # an older released version, unedited
            continue
        if key in known or key in hashes:
            held.append((key, "framework section that was edited in this project: it matches no released "
                              "version, so it was kept. Delete it by hand if the edits are not needed "
                              "(framework text now lives only in the central instructions)"))
        kept.append(seg)
    if not removed:
        return ThinResult(text, [], held, False)
    out = "".join(s.text for s in kept)
    if not out.strip():
        out = ""
    elif segments and not any(s is segments[-1] for s in kept):
        out = out.rstrip("\n") + "\n"
    return ThinResult(out, removed, held, out != text)
