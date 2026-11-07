"""Where project init and migrate keep machine state, resolved the way `cc release` resolves it.

The copilot home is `$COPILOT_HOME` (else `~/.copilot`); its parent plays the user home, so an isolated
run keeps everything in one tree. The Codex home is `$CODEX_HOME`, else `<that home>/.codex`.
"""

from __future__ import annotations

import os
from pathlib import Path


def copilot_home() -> Path:
    from cc.core.release.engine import layout

    return layout.copilot_home()


def codex_home() -> Path:
    env = os.environ.get("CODEX_HOME")
    if env:
        return Path(env).expanduser()
    from cc.core.release.engine import layout

    return layout.home_root() / ".codex"
