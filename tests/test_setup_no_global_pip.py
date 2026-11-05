"""Setup must never run a plain `pip install` into the machine Python.

Homebrew Python is externally managed (PEP 668), so `pip install -e tools/tc`
fails on a fresh Mac. tc installs through tools/tc/install.sh, which uses its own venv.
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPERATIVE = [
    ".claude/commands/setup.md",
    ".claude/commands/update-copilot.md",
    "SETUP.md",
    "CONTRIBUTING.md",
    "scripts/check-versions.sh",
    "scripts/install/validate-installation.sh",
    "tools/tc/README.md",
]
PLAIN_PIP = re.compile(r"(?<![\w.-])pip3? install\b(?! --quiet)")


def test_setup_paths_do_not_use_plain_pip():
    offenders = [
        f"{rel}:{n}"
        for rel in OPERATIVE
        for n, line in enumerate((ROOT / rel).read_text().splitlines(), 1)
        if PLAIN_PIP.search(line)
    ]
    assert offenders == []


def test_tc_installer_uses_its_own_venv():
    script = (ROOT / "tools/tc/install.sh").read_text()
    assert '-m venv "$TC_VENV_DIR"' in script
    assert '"$TC_VENV_DIR/bin/python" -m pip install' in script
    assert subprocess.run(["bash", "-n", str(ROOT / "tools/tc/install.sh")]).returncode == 0
