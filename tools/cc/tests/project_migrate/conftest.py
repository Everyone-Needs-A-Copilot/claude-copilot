"""Fixture builders: temp projects shaped like real synced projects (never real ones)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from cc.core.project_migrate import Known

FW_SECTION = "## Output Contract\n\n- Lead with the answer.\n"
FW_SECTION_2 = "## Work Lifecycle\n\n- Apply the lifecycle.\n"
EVIDENCE = "<!-- cse-evidence-v2:start -->\n## Task Acceptance and Tested Identity\n\nRegister contracts.\n<!-- cse-evidence-v2:end -->\n"
CLAUDE_BLOCK = (
    "<!-- cc:project-integration:claude:v1:start -->\n## Claude Copilot\n\nThis project uses the framework.\n"
    "<!-- cc:project-integration:claude:v1:end -->\n"
)
HOOK_CMD = 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/copilot-hook.sh" session-start'
SHIM = b"#!/bin/bash\necho shim\n"
GATE = b"#!/bin/bash\necho gate\n"
FITNESS = b"#!/bin/bash\necho fitness\n"


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def tree_state(root: Path) -> dict[str, object]:
    """path -> bytes hash / link target, for byte-identity comparisons (skips .git)."""
    out: dict[str, object] = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d != ".git"]
        for n in dns + fns:
            p = Path(dp) / n
            rel = p.relative_to(root).as_posix()
            if p.is_symlink():
                out[rel] = ("link", os.readlink(p))
            elif p.is_file():
                out[rel] = ("file", sha(p.read_bytes()), p.stat().st_mode & 0o777)
    return out


@dataclass
class Fx:
    root: Path
    known: Known
    codex_config: Path
    registry: Path
    packs_root: Path
    backup_root: Path

    def kw(self, **extra):
        return dict(known=self.known, codex_config=self.codex_config, registry=self.registry,
                    packs_root=self.packs_root, backup_root=self.backup_root, **extra)


def _w(root: Path, rel: str, data: bytes | str, mode: int | None = None) -> bytes:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    b = data.encode() if isinstance(data, str) else data
    p.write_bytes(b)
    if mode is not None:
        p.chmod(mode)
    return b


def make_known() -> Known:
    return Known(
        file_hashes={".claude/fitness-check.sh": {sha(FITNESS)}, "scripts/copilot-gate.sh": {sha(GATE)},
                     ".claude/hooks/copilot-hook.sh": {sha(SHIM)}},
        tree_hashes={},
        sections={"## Output Contract": {FW_SECTION.rstrip()}, "## Work Lifecycle": {FW_SECTION_2.rstrip()},
                  "<!-- cse-evidence-v2 -->": {EVIDENCE.rstrip()}},
    )


def build_project(tmp: Path, name: str = "app", *, shape: str = "plain", git: bool = True) -> Path:
    root = tmp / name
    root.mkdir(parents=True)
    files: list[dict] = []

    def fw(rel: str, data: bytes, **kw) -> None:
        _w(root, rel, data, 0o555 if rel.endswith(".sh") else None)
        files.append({"checksum": sha(data), "ownership": "framework", "path": rel})

    for n in ("protocol", "continue", "pause"):
        fw(f".claude/commands/{n}.md", f"# {n} framework\n".encode())
    for n in ("ta", "me", "qa"):
        fw(f".claude/agents/{n}.md", f"---\nname: {n}\n---\nframework {n}\n".encode())
    fw(".claude/agents/_shared/work-lifecycle.md", b"lifecycle\n")
    fw(".claude/hooks/copilot-hook.sh", SHIM)
    fw(".claude/fitness-check.sh", FITNESS)
    fw(".claude/skills/cleanup/SKILL.md", b"cleanup\n")
    claude = {"component": "claude", "files": list(files), "ownership_mode": "full", "version": "5.34.8",
              "managed_outputs": [{"kind": "merged-json", "path": ".claude/settings.json", "fingerprint": "x"}]}
    files.clear()
    for n in ("plugin.json", "skills/protocol/SKILL.md"):
        fw(f"plugins/codex-copilot/{n}", f"codex {n}\n".encode())
    fw("scripts/copilot-gate.sh", GATE)
    codex = {"component": "codex", "files": list(files), "ownership_mode": "full", "version": "0.16.7",
             "managed_outputs": [{"kind": "internal-symlink", "path": ".claude/skills/codex-copilot", "fingerprint": "x"}]}
    (root / ".claude/skills/codex-copilot").symlink_to("../../plugins/codex-copilot/skills")
    mut = {"kind": "settings-hook", "target": ".claude/settings.json", "target_existed_before": False,
           "entries": [{"command": HOOK_CMD, "event": "SessionStart"}]}
    _w(root, "copilot.lock.json", json.dumps({"schema_version": "1.0", "components": [claude, codex], "mutations": [mut]}))
    _w(root, ".codex-copilot.json", json.dumps({"frameworkVersion": "0.16.7", "activePacks": []}))
    _w(root, ".mcp.json", '{"mcpServers":{}}')
    _w(root, ".agents/plugins/marketplace.json", json.dumps(
        {"name": "codex-copilot-project", "plugins": [{"name": "codex-copilot", "source": {"source": "local", "path": "./plugins/codex-copilot"}}]}))
    settings = {
        "permissions": {"allow": ["Bash(ls)"]},
        "hooks": {
            "SessionStart": [{"matcher": "startup", "hooks": [
                {"type": "command", "command": HOOK_CMD, "_copilot_source": "claude-copilot"},
                {"type": "command", "command": "echo project-hook"}]}],
            "PreCompact": [{"hooks": [{"type": "command", "command": "bash x copilot-hook.sh pre", "_copilot_source": "claude-copilot"}]}],
        },
    }
    _w(root, ".claude/settings.json", json.dumps(settings, indent=2))
    _w(root, "copilot.project.json", json.dumps({"components": ["claude", "codex"], "schema_version": "1.0", "tier": "x"}))
    # class (a)
    _w(root, ".claude/memory/entries/m1.md", "memory one\n")
    _w(root, ".claude/memory/.gitignore", "memory.db\n")
    _w(root, ".copilot/tasks.db", b"SQLITE")
    _w(root, ".copilot/wp/1.md", "wp\n")
    _w(root, ".claude/cc/config.json", "{}")
    _w(root, ".claude/skills/launch/SKILL.md", "project skill\n")
    _w(root, ".claude/agents/mine.md", "---\nname: mine\n---\nproject agent\n")
    _w(root, "SOUL.md", "soul\n")
    _w(root, "CLAUDE.md", f"# {name}\n\n## Project Rules\n\n- Be kind.\n\n{CLAUDE_BLOCK}\n{EVIDENCE}\n## Standing Notes\n\nOurs.\n")
    _w(root, "AGENTS.md", f"# {name}\n\n## Project Overview\n\nWhat we do.\n\n{FW_SECTION}\n{FW_SECTION_2}")
    if shape == "gtm":
        _w(root, "docs/plugins/codex-copilot/plugin.json", "docs copy\n")
        _w(root, "plugins/gtm-copilot/.codex-plugin/plugin.json", "{}")
        _w(root, "plugins/gtm-copilot/skills/gtm/SKILL.md", "gtm\n")
    if shape == "convoco":
        (root / "scripts/copilot-gate.sh").unlink()
        _w(root, "scripts/copilot-gate.sh", b"#!/bin/bash\necho project-owned gate\n")  # lock-listed, differs
        (root / ".claude/agents/ta.md").write_text("---\nname: ta\nowner: project\n---\nmy ta\n")
    if shape == "pipeline":
        for s in ("legal-nda", "cw"):
            (root / "plugins/pipeline-copilot/skills").mkdir(parents=True, exist_ok=True)
            (root / f"plugins/pipeline-copilot/skills/{s}").symlink_to(f"../../../../codex-copilot/packs/writing-legal/skills/{s}")
        _w(root, "plugins/pipeline-copilot/.codex-plugin/plugin.json", "{}")
    if shape == "creative":
        # customized-preserve: project owns the agent tree; modified framework command
        (root / ".claude/commands/protocol.md").write_text("# protocol edited by project\n")
    if git:
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "synced"]):
            subprocess.run(["git", "-C", str(root), *args], check=True, env=env, capture_output=True)
    return root


@pytest.fixture
def fx(tmp_path: Path, monkeypatch) -> Fx:
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"), ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@t")):
        monkeypatch.setenv(k, v)
    base = tmp_path / "sandbox"
    base.mkdir()
    return Fx(root=build_project(base), known=make_known(), codex_config=tmp_path / "codex" / "config.toml",
              registry=tmp_path / "registry.json", packs_root=tmp_path / "packs", backup_root=tmp_path / "backups")
