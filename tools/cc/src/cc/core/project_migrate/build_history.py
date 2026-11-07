"""Developer tool: regenerate `framework_section_history.json` from the framework repos' git history.

    python -m cc.core.project_migrate.build_history CLAUDE_COPILOT_REPO CODEX_COPILOT_REPO

The JSON maps an instruction-file section key to the whitespace-normalised SHA-256 of every released version of that
framework-owned section (templates only; hashes, not text). Projects synced by older framework
versions carry those older texts, so the migrator can tell "unedited, older release" (remove)
from "edited by the project" (hold).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from cc.core.project_migrate import instructions

TEMPLATES = {
    "claude": ("templates/CLAUDE.template.md",),
    "codex": ("templates/AGENTS.project.template.md", "templates/codex-AGENTS.framework.md"),
}
OUT = Path(__file__).with_name("framework_section_history.json")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False).stdout


def collect(repos: dict[str, Path]) -> dict[str, list[str]]:
    out: dict[str, set[str]] = {}
    for name, repo in repos.items():
        seen: set[str] = set()
        for rel in TEMPLATES[name]:
            for commit in _git(repo, "log", "--all", "--format=%H", "--", rel).split():
                blob = _git(repo, "rev-parse", f"{commit}:{rel}").strip()
                if not blob or blob in seen:
                    continue
                seen.add(blob)
                for key, texts in instructions.known_sections_from_text(_git(repo, "show", f"{commit}:{rel}")).items():
                    for t in texts:
                        out.setdefault(key, set()).add(instructions.history_digest(t))
    return {k: sorted(v) for k, v in sorted(out.items())}


if __name__ == "__main__":
    claude, codex = (Path(a) for a in sys.argv[1:3])
    OUT.write_text(json.dumps(collect({"claude": claude, "codex": codex}), indent=1) + "\n")
    print(f"wrote {OUT}")
