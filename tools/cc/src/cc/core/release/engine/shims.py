"""Stable ~/.local/bin shims (cc, tc, tc-limits) that resolve through `current`."""

from __future__ import annotations

import os
from pathlib import Path

from . import layout

_MISSING = (
    'if [ ! -e "$CUR" ]; then echo "copilot: no current release ($CUR); run: cc release status" >&2; exit 0; fi\n'
)


def _script(name: str, home: Path | str | None) -> str:
    current = layout.current_path(home)
    head = f'#!/bin/sh\nCUR="{current}"\n{_MISSING}'
    py = f'"$CUR/{layout.CC_VENV_PYTHON_RELATIVE.as_posix()}"'
    if name == "tc-limits":
        return head + f'exec "$CUR/{layout.TC_LIMITS_RELATIVE.as_posix()}" "$@"\n'
    module = "cc" if name == "cc" else "tc"
    code = f"import sys; from {module}.main import app; sys.argv[0]='{name}'; sys.exit(app())"
    return head + f"exec {py} -c \"{code}\" \"$@\"\n"


def install(home: Path | str | None = None) -> list[str]:
    """Write the shims atomically; returns the paths written."""
    directory = layout.bin_dir(home)
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name in layout.SHIM_NAMES:
        target = directory / name
        temp = directory / f".{name}.{os.getpid()}.tmp"
        temp.write_text(_script(name, home), encoding="utf-8")
        os.chmod(temp, 0o755)
        os.replace(temp, target)
        written.append(str(target))
    return written
