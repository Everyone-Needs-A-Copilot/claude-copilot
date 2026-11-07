"""Idempotent .gitignore block for derived links."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Sequence

BEGIN = "# copilot:derived-links:begin"
END = "# copilot:derived-links:end"


def ensure_ignored(project: Path, entries: Sequence[str]) -> bool:
    if not entries:
        return False
    path = project / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    block = "\n".join([BEGIN, *sorted(f"/{e}" for e in entries), END]) + "\n"
    if BEGIN in text and END in text:
        head, rest = text.split(BEGIN, 1)
        _old, tail = rest.split(END, 1)
        new = head + block + tail.lstrip("\n") if tail.strip() else head + block
    else:
        sep = "" if not text else ("\n" if text.endswith("\n") else "\n\n")
        new = text + sep + block
    if new == text:
        return False
    fd, tmp = tempfile.mkstemp(dir=project, prefix=".gitignore.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(new)
    os.replace(tmp, path)
    return True
