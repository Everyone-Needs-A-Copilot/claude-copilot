"""Replica builder: copy (never modify) the real machine state into a sandbox.

The sandbox is a complete fake HOME plus fake workspace roots:

    <sandbox>/home/{.claude,.codex,.copilot,.config/...,.local/bin,.gitconfig,.claude.json}
    <sandbox>/Sites/{CSE,COPILOT}/<project>        (git clone --local + dirty/untracked/ignored-config files)

Every absolute path or link that points at real *state* (the home state dirs and the cloned project
roots) is rewritten to the sandbox twin.  Paths to read-only tools (python, node, homebrew, the
claude/codex binaries) are left alone.  Nothing is ever written to a real path.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

REAL_HOME = Path(os.path.realpath(os.path.expanduser("~")))
SITES = Path("/Volumes/Dev/Sites")

# Home entries that are STATE and therefore replicated (everything else under the real home is a tool).
HOME_STATE = [".copilot", ".claude", ".codex", ".local/bin", ".config/copilot", ".config/dev-environment",
              ".claude.json", ".gitconfig"]

# ~/.claude: copy configuration, not history / caches / sessions.
CLAUDE_COPY = ["settings.json", "CLAUDE.md", "agents", "commands", "skills", "hooks", "plugins", "cc",
               "knowledge", "ecosystem.yml", "statusline-command.sh", "keybindings.json", "themes", "state",
               "copilot", ".claude.json"]
# ~/.codex: copy configuration, trust, skills, plugin cache, hooks, auth.
CODEX_COPY = ["config.toml", "AGENTS.md", "skills", "plugins", "hooks", "hooks.json", ".hook-trust",
              "auth.json", "installation_id", "version.json", "keybindings.json",
              "models_cache.json"]  # account-specific model list: without it Codex refetches an anonymous one and rejects the config model
# ~/.copilot: everything except bulky history mirrors.
COPILOT_SKIP = {"framework-snapshots", "legacy-mirrors", "mirrors", "materialized", "recovery", "triage",
                "organization-snapshots", "rollback", "migrations", "registered-projects.json",
                "framework-install.lock"}

PROJECTS = [  # (root, name, role)
    ("COPILOT", "pipeline-copilot", "pipeline-copilot"),
    ("COPILOT", "convoco", "convoco"),
    ("COPILOT", "the-herd", "the-herd"),
    ("CSE", "claude-copilot-private", "claude-copilot-private"),
    ("CSE", "knowledge-copilot-internal", "knowledge-copilot-internal"),
    # Codex-heavy: project-local .codex/config.toml with its own agent roster and Codex hooks.
    ("COPILOT", "convoco-creative-studio", "codex-heavy"),
]
# Ignored-but-meaningful files copied into each clone (framework/runtime configuration, never build output).
CONFIG_PATHS = [".claude", ".codex", ".agents", ".claude-plugin", ".mcp.json", ".codex-copilot.json",
                "copilot.lock.json", "copilot.project.json", "CLAUDE.md", "AGENTS.md", "SOUL.md",
                "settings.local.json", "mcp.json", "plugins"]
CONFIG_SKIP_PARTS = {"worktrees", "node_modules", ".venv", "__pycache__", ".git"}
MAX_COPY_BYTES = 200 * 1024 * 1024


@dataclass
class Replica:
    root: Path
    home: Path = field(init=False)
    path_map: list = field(default_factory=list)  # (real_prefix, sandbox_prefix), longest first
    projects: dict = field(default_factory=dict)  # role -> sandbox path
    support_repos: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    unmapped_links: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self.home = self.root / "home"

    @property
    def copilot_home(self) -> Path:
        return self.home / ".copilot"

    @property
    def codex_home(self) -> Path:
        return self.home / ".codex"

    @property
    def tool_dirs(self) -> str:
        """Directory of the codex binary (and its node), so a node-script codex runs under the sanitized PATH."""
        b = os.environ.get("CR_CODEX_BIN") or shutil.which("codex")
        return f"{os.path.dirname(b)}:" if b else ""

    def env(self, extra: dict | None = None) -> dict:
        """Environment for every command run against the replica."""
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("CLAUDE_", "CODEX_", "COPILOT_", "CC_", "CMUX")) and k not in ("PWD", "OLDPWD")}
        env.update({
            "HOME": str(self.home),
            "CODEX_HOME": str(self.codex_home),
            "COPILOT_HOME": str(self.copilot_home),
            "PATH": f"{self.home}/.local/bin:{self.tool_dirs}/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "GIT_CONFIG_GLOBAL": str(self.home / ".gitconfig"),
            "NO_COLOR": "1",
        })
        env.update(extra or {})
        return env

    def rewrite(self, text: str) -> str:
        for real, sandbox in self.path_map:
            if real in text:
                text = text.replace(real, sandbox)
        return text


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def rmtree_force(path: Path) -> None:
    """Remove a sandbox tree, including read-only release trees.  Refuses anything that is not a sandbox."""
    path = Path(path)
    if not (path / ".cr-sandbox").exists() and path.exists() and any(path.iterdir()):
        raise RuntimeError(f"{path} is not a harness sandbox (no .cr-sandbox marker); refusing to delete")
    if not path.exists():
        return
    for dirpath, dirnames, _ in os.walk(path):
        os.chmod(dirpath, 0o700)
    shutil.rmtree(path)


def _cp(src: Path, dst: Path) -> None:
    """Copy preserving symlinks, modes and times; clone-on-write when the filesystem allows."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = _run(["cp", "-cRp", str(src), str(dst)])
    if r.returncode != 0:
        r = _run(["cp", "-Rp", str(src), str(dst)])
    if r.returncode != 0:
        raise RuntimeError(f"copy failed {src} -> {dst}: {r.stderr.strip()[:300]}")


def _writable_tree(root: Path):
    """Make a tree writable; return a restorer that puts back the original directory modes."""
    modes = []
    for dirpath, dirnames, _ in os.walk(root):
        st = os.lstat(dirpath)
        modes.append((dirpath, stat.S_IMODE(st.st_mode)))
        os.chmod(dirpath, stat.S_IMODE(st.st_mode) | 0o700)

    def restore() -> None:
        for dirpath, mode in reversed(modes):
            os.chmod(dirpath, mode)
    return restore


def _is_text(data: bytes) -> bool:
    return b"\0" not in data[:4096]


def _rewrite_tree(rep: Replica, root: Path) -> int:
    """Rewrite mapped absolute paths inside text files and symlink targets under root."""
    restore = _writable_tree(root)
    changed = 0
    needles = tuple(r.encode() for r, _ in rep.path_map)
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            if ".git" in dirnames:
                dirnames.remove(".git")
            for name in filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
                p = Path(dirpath, name)
                if p.is_symlink():
                    target = os.readlink(p)
                    new = rep.rewrite(target)
                    if new != target:
                        p.unlink()
                        os.symlink(new, p)
                        changed += 1
                    continue
                try:
                    if p.stat().st_size > 8 * 1024 * 1024:
                        continue
                    data = p.read_bytes()
                except OSError:
                    continue
                if not any(n in data for n in needles) or not _is_text(data):
                    continue
                mode = stat.S_IMODE(p.stat().st_mode)
                os.chmod(p, mode | 0o600)
                p.write_text(rep.rewrite(data.decode("utf-8", "surrogateescape")),
                             encoding="utf-8", errors="surrogateescape")
                os.chmod(p, mode)
                changed += 1
    finally:
        restore()
    return changed


def _discover_support_repos(src_roots: list[Path], known: set[str]) -> set[tuple[str, str]]:
    """Absolute symlink targets into /Volumes/Dev/Sites/<root>/<repo> found in copied home state."""
    found = set()
    for base in src_roots:
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            for name in list(dirnames) + filenames:
                p = Path(dirpath, name)
                if p.is_symlink():
                    t = os.readlink(p)
                    if t.startswith(str(SITES) + "/"):
                        parts = Path(t).relative_to(SITES).parts
                        if len(parts) >= 2 and parts[1] not in known:
                            found.add((parts[0], parts[1]))
            dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", ".venv")]
    return found


def clone_project(root: str, name: str, dest: Path, notes: list) -> None:
    """git clone --local, then reproduce dirty tracked files, deletions, untracked files and config symlinks."""
    src = SITES / root / name
    r = _run(["git", "clone", "--local", "--no-checkout", "-q", str(src), str(dest)])
    if r.returncode:
        raise RuntimeError(f"clone {src}: {r.stderr[:300]}")
    head = _run(["git", "-C", str(src), "rev-parse", "HEAD"]).stdout.strip()
    branch = _run(["git", "-C", str(src), "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    r = _run(["git", "-C", str(dest), "checkout", "-q", "--detach", head] if branch == "HEAD"
             else ["git", "-C", str(dest), "checkout", "-q", "-B", branch, head])
    if r.returncode:
        raise RuntimeError(f"checkout {name}: {r.stderr[:300]}")
    # the clone's origin is the real repo; cut it so nothing can ever fetch from or push to real state
    _run(["git", "-C", str(dest), "remote", "remove", "origin"])

    def lines(*args):
        out = subprocess.run(["git", "-C", str(src), *args], capture_output=True).stdout
        return [x.decode("utf-8", "surrogateescape") for x in out.split(b"\0") if x]

    modified = lines("ls-files", "-z", "-m")
    deleted = set(lines("ls-files", "-z", "-d"))
    untracked = lines("ls-files", "-z", "-o", "--exclude-standard")
    ignored_cfg = []
    for spec in CONFIG_PATHS:
        ignored_cfg += lines("ls-files", "-z", "-o", "-i", "--exclude-standard", "--", spec)
    todo = {}
    for rel in modified + untracked + ignored_cfg:
        if rel in deleted:
            continue
        todo[rel] = True
    for rel in deleted:
        t = dest / rel
        if t.exists() or t.is_symlink():
            t.unlink()
    skipped = []
    for rel in sorted(todo):
        parts = set(Path(rel.rstrip("/")).parts)
        if parts & CONFIG_SKIP_PARTS:
            skipped.append(rel)
            continue
        s = src / rel.rstrip("/")
        t = dest / rel.rstrip("/")
        try:
            if s.is_symlink():
                t.parent.mkdir(parents=True, exist_ok=True)
                if t.exists() or t.is_symlink():
                    t.unlink()
                os.symlink(os.readlink(s), t)
            elif s.is_dir():
                if _run(["du", "-sk", str(s)]).stdout.split()[0:1] and int(_run(["du", "-sk", str(s)]).stdout.split()[0]) * 1024 > MAX_COPY_BYTES:
                    skipped.append(rel)
                    continue
                if t.exists():
                    shutil.rmtree(t)
                _cp(s, t)
            elif s.is_file():
                if s.stat().st_size > MAX_COPY_BYTES:
                    skipped.append(rel)
                    continue
                t.parent.mkdir(parents=True, exist_ok=True)
                if t.is_symlink():
                    t.unlink()
                shutil.copy2(s, t)
        except OSError as exc:
            notes.append(f"{name}: could not copy {rel}: {exc}")
    if skipped:
        notes.append(f"{name}: {len(skipped)} oversized/runtime-state path(s) not copied (e.g. {skipped[0]})")
    # project .git/info/exclude and hooks stay as cloned; copy the real exclude so ignore rules match
    ex = src / ".git" / "info" / "exclude"
    if ex.is_file():
        (dest / ".git" / "info").mkdir(parents=True, exist_ok=True)
        shutil.copy2(ex, dest / ".git" / "info" / "exclude")


def porcelain(path: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(path), "status", "--porcelain", "-z", "--untracked-files=all"],
                         capture_output=True).stdout
    return sorted(x.decode("utf-8", "surrogateescape")[3:] for x in out.split(b"\0") if x)


def build(root: Path) -> Replica:
    rep = Replica(root=root)
    rmtree_force(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / ".cr-sandbox").write_text("acceptance harness sandbox\n")
    home = rep.home
    home.mkdir(parents=True, exist_ok=True)

    # ---- decide the cloned repo set (roles + support repos found through links) ----------------------
    wanted = {name for _, name, _ in PROJECTS}
    plan = [(r, n) for r, n, _ in PROJECTS]

    # ---- copy home state ------------------------------------------------------------------------
    for rel in CLAUDE_COPY:
        s = REAL_HOME / ".claude" / rel
        if s.exists() or s.is_symlink():
            _cp(s, home / ".claude" / rel)
    for rel in CODEX_COPY:
        s = REAL_HOME / ".codex" / rel
        if s.exists() or s.is_symlink():
            _cp(s, home / ".codex" / rel)
    (home / ".copilot").mkdir(parents=True, exist_ok=True)
    for child in sorted((REAL_HOME / ".copilot").iterdir()):
        if child.name in COPILOT_SKIP or child.name.endswith(".lock"):
            continue
        _cp(child, home / ".copilot" / child.name)
    # the registry of real project folders must never lead a tool to real folders
    (home / ".copilot" / "registered-projects.json").write_text(
        json.dumps({"schema_version": "1.0", "projects": []}), encoding="utf-8")
    for rel in (".config/copilot", ".config/dev-environment", ".gitconfig", ".claude.json"):
        s = REAL_HOME / rel
        if s.exists() or s.is_symlink():
            _cp(s, home / rel)
    (home / ".local" / "bin").mkdir(parents=True, exist_ok=True)
    for shim in ("cc", "tc", "tc-limits", "copilot"):
        s = REAL_HOME / ".local" / "bin" / shim
        if s.exists() or s.is_symlink():
            _cp(s, home / ".local" / "bin" / shim)
    (home / ".gnupg").mkdir(exist_ok=True)
    os.chmod(home / ".gnupg", 0o700)

    # ---- support repos: live-link / personal-tier checkouts referenced by copied links -----------
    support = _discover_support_repos([home / ".claude" / "skills", home / ".codex" / "skills"], wanted)
    rel_dir = home / ".copilot" / "releases"
    if rel_dir.is_dir():
        support |= _discover_support_repos([d for d in rel_dir.iterdir() if d.is_dir()], wanted)
    # layers file names the checkouts of the tiers
    layers = home / ".config" / "copilot" / "copilot.layers.yml"
    if layers.is_file():
        import re
        for m in re.finditer(r"/Volumes/Dev/Sites/(CSE|COPILOT)/([A-Za-z0-9._-]+)", layers.read_text()):
            if m.group(2) not in wanted:
                support.add((m.group(1), m.group(2)))
    support |= {("CSE", "claude-copilot")}
    for root_name, name in sorted(support):
        if (SITES / root_name / name / ".git").exists():
            plan.append((root_name, name))
            rep.support_repos.append(f"{root_name}/{name}")
    # ---- path map ---------------------------------------------------------------------------------
    pairs = []
    for rel in HOME_STATE:
        pairs.append((str(REAL_HOME / rel), str(home / rel)))
    for root_name, name in plan:
        pairs.append((f"{SITES}/{root_name}/{name}", str(root / "Sites" / root_name / name)))
    pairs.sort(key=lambda p: -len(p[0]))
    rep.path_map = pairs

    # ---- clone projects and support repos --------------------------------------------------------
    for root_name, name in plan:
        dest = root / "Sites" / root_name / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        clone_project(root_name, name, dest, rep.notes)
    for r, n, role in PROJECTS:
        rep.projects[role] = root / "Sites" / r / n

    # ---- rewrite absolute references -------------------------------------------------------------
    n = 0
    for tree in (home / ".copilot", home / ".claude", home / ".codex", home / ".config", home / ".local" / "bin"):
        if tree.exists():
            n += _rewrite_tree(rep, tree)
    for f in (home / ".gitconfig", home / ".claude.json"):
        if f.is_file():
            f.write_text(rep.rewrite(f.read_text()), encoding="utf-8")
    rep.notes.append(f"rewrote {n} home-state file(s)/link(s)")
    rep.notes.append("registered-projects.json emptied; sessions/history/caches not copied")
    return rep


def real_state_references(rep: Replica) -> list[str]:
    """Links or settings inside the sandbox that still resolve into real state. Empty means isolated."""
    bad: list[str] = []
    real_roots = [str(REAL_HOME / rel) for rel in HOME_STATE] + [
        f"{SITES}/{r}/{n}" for r, n, _ in PROJECTS]
    for base in (rep.home / ".copilot", rep.home / ".claude", rep.home / ".codex", rep.home / ".local"):
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", ".venv", "cache", "__pycache__")]
            for name in list(dirnames) + filenames:
                p = Path(dirpath, name)
                if p.is_symlink():
                    t = os.path.normpath(os.path.join(dirpath, os.readlink(p)))
                    if any(t == r or t.startswith(r + "/") for r in real_roots) and not t.startswith(str(rep.root)):
                        bad.append(f"{p} -> {os.readlink(p)}")
    for f in [rep.home / ".claude" / "settings.json", rep.codex_home / "config.toml",
              rep.copilot_home / "current" / "links.json"]:
        if f.is_file():
            txt = f.read_text(errors="replace")
            for r in real_roots:
                if r in txt:
                    bad.append(f"{f} mentions {r}")
    return bad[:50]
