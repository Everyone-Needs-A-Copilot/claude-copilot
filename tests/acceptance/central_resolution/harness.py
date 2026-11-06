"""Shared helpers: command runner, symlink-aware snapshots, real-state sentinel, runtime drivers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import replica as rp

SNAP_SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", ".pytest_cache", ".ruff_cache",
             ".mypy_cache", ".worktrees"}
HASH_CAP = 64 * 1024 * 1024


# ----------------------------------------------------------------------------- commands
@dataclass
class Run:
    rc: int
    out: str
    err: str
    secs: float
    cmd: list

    @property
    def text(self) -> str:
        return self.out + "\n" + self.err


def run(cmd, *, env=None, cwd=None, timeout=300, stdin: str | None = "") -> Run:
    t = time.monotonic()
    try:
        p = subprocess.run([str(c) for c in cmd], env=env, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, input=stdin, errors="replace")
        return Run(p.returncode, p.stdout, p.stderr, time.monotonic() - t, list(cmd))
    except subprocess.TimeoutExpired as exc:
        return Run(124, (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
                   f"TIMEOUT after {timeout}s", time.monotonic() - t, list(cmd))


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        n = 0
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
            n += len(b)
            if n > HASH_CAP:
                h.update(b"[capped]")
                break
    return h.hexdigest()


# ----------------------------------------------------------------------------- snapshots
def snapshot(root: Path, skip=SNAP_SKIP) -> dict:
    """Symlink-aware tree snapshot: type, mode, link target (never dereferenced), content hash."""
    out: dict[str, tuple] = {}
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        rel_dir = os.path.relpath(dirpath, root)
        for name in sorted(dirnames) + sorted(filenames):
            p = os.path.join(dirpath, name)
            rel = os.path.normpath(os.path.join(rel_dir, name))
            st = os.lstat(p)
            mode = stat.S_IMODE(st.st_mode)
            if stat.S_ISLNK(st.st_mode):
                out[rel] = ("link", os.readlink(p))
            elif stat.S_ISDIR(st.st_mode):
                out[rel] = ("dir", mode)
            elif stat.S_ISREG(st.st_mode):
                out[rel] = ("file", mode, st.st_size, sha256_file(Path(p)))
            else:
                out[rel] = ("other", mode)
    return out


def diff_snapshots(a: dict, b: dict) -> dict:
    return {
        "removed": sorted(set(a) - set(b)),
        "added": sorted(set(b) - set(a)),
        "changed": sorted(k for k in set(a) & set(b) if a[k] != b[k]),
    }


def tree_digest(root: Path, names: list[str]) -> str:
    """Cheap digest (names, sizes, mtimes, link targets) of selected top-level entries; for the real-state sentinel."""
    h = hashlib.sha256()
    for n in names:
        base = Path(root, n)
        if not (base.exists() or base.is_symlink()):
            h.update(f"missing:{n}\n".encode())
            continue
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            # skills/synced is Claude Code's own cloud-skill sync cache, rewritten by the app itself
            dirnames[:] = sorted(d for d in dirnames if not (d == "synced" and os.path.basename(dirpath) == "skills"))
            for name in sorted(dirnames + filenames):
                p = os.path.join(dirpath, name)
                try:
                    st = os.lstat(p)
                except OSError:
                    continue
                tgt = os.readlink(p) if stat.S_ISLNK(st.st_mode) else ""
                h.update(f"{p}|{st.st_mode}|{st.st_size}|{st.st_mtime_ns}|{tgt}\n".encode())
        if base.is_symlink() or base.is_file():
            st = os.lstat(base)
            h.update(f"{base}|{st.st_mode}|{st.st_size}|{st.st_mtime_ns}|{os.readlink(base) if base.is_symlink() else ''}\n".encode())
    return h.hexdigest()


# ----------------------------------------------------------------------------- sentinel
FRAMEWORK_TOP = [".claude", ".codex", ".agents", ".claude-plugin", ".mcp.json", ".codex-copilot.json",
                 "copilot.lock.json", "copilot.project.json", "CLAUDE.md", "AGENTS.md", "SOUL.md",
                 "settings.local.json", "mcp.json", "plugins"]


def _git_env() -> dict:
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"  # a read of a real repo must never refresh its index
    return env


def sentinel_snapshot(extra_repos: list[str]) -> dict:
    real = rp.REAL_HOME
    s: dict = {}

    def file_hash(p: Path) -> str:
        return sha256_file(p) if p.is_file() else "missing"

    cur = real / ".copilot" / "current"
    s["~/.copilot/current -> "] = os.readlink(cur) if cur.is_symlink() else "not-a-link"
    s["~/.copilot/release-history.jsonl"] = file_hash(real / ".copilot" / "release-history.jsonl")
    s["~/.copilot/links-receipt.json"] = file_hash(real / ".copilot" / "links-receipt.json")
    s["~/.claude/settings.json"] = file_hash(real / ".claude" / "settings.json")
    s["~/.codex/config.toml"] = file_hash(real / ".codex" / "config.toml")
    s["~/.codex/AGENTS.md"] = file_hash(real / ".codex" / "AGENTS.md")
    s["~/.claude/{agents,commands,skills,hooks}"] = tree_digest(real / ".claude", ["agents", "commands", "skills", "hooks"])
    s["~/.codex/{skills,hooks,hooks.json}"] = tree_digest(real / ".codex", ["skills", "hooks", "hooks.json"])
    s["~/.copilot/releases (listing)"] = ",".join(sorted(os.listdir(real / ".copilot" / "releases")))
    for r, name, _ in rp.PROJECTS:
        path = rp.SITES / r / name
        env = _git_env()
        st = run(["git", "-C", path, "status", "--porcelain", "-z", "--untracked-files=all"], env=env).out
        head = run(["git", "-C", path, "rev-parse", "HEAD"], env=env).out.strip()
        s[f"project {name}: git status+HEAD"] = hashlib.sha256((head + "\0" + st).encode()).hexdigest()
        s[f"project {name}: framework files"] = tree_digest(path, FRAMEWORK_TOP)
    for repo in extra_repos:
        path = rp.SITES / repo
        env = _git_env()
        st = run(["git", "-C", path, "status", "--porcelain", "-z", "--untracked-files=all"], env=env).out
        head = run(["git", "-C", path, "rev-parse", "HEAD"], env=env).out.strip()
        s[f"support {repo}: git status+HEAD"] = hashlib.sha256((head + "\0" + st).encode()).hexdigest()
    return s


# ----------------------------------------------------------------------------- runtime drivers
# The codex the owner's shell resolves (WP-319 used it: 0.167.0). /opt/homebrew/bin/codex is a stale 0.153.0 that does not
# know the configured model, so every turn fails before a command is attempted.
CODEX_BIN = os.environ.get("CR_CODEX_BIN") or shutil.which("codex") or "/opt/homebrew/bin/codex"
CLAUDE_BIN = os.environ.get("CR_CLAUDE_BIN", str(rp.REAL_HOME / ".local" / "bin" / "claude"))
# Empty = the replica config's own model, exactly like the manual WP-319 probe. Forcing a model (-m) that the ChatGPT
# account does not support fails the turn before any command is attempted ("model is not supported ... ChatGPT account").
CODEX_MODEL = os.environ.get("CR_CODEX_MODEL", "")


def codex_model_args() -> list:
    return ["-m", CODEX_MODEL] if CODEX_MODEL else []
RUNTIME_TIMEOUT = int(os.environ.get("CR_RUNTIME_TIMEOUT", "240"))


def claude_run(rep, cwd: Path, prompt: str, *, obs: Path | None = None, extra: list | None = None,
               allowed: list | None = None) -> dict:
    """Headless `claude -p` in the replica. Returns parsed stream-json."""
    env = rep.env({"CRACC_OBS": str(obs)} if obs else {})
    cmd = [CLAUDE_BIN, "-p", prompt, "--output-format", "stream-json", "--verbose", "--include-hook-events"]
    if allowed:
        cmd += ["--allowedTools", *allowed]
    cmd += extra or []
    r = run(cmd, env=env, cwd=cwd, timeout=RUNTIME_TIMEOUT)
    events = []
    for line in r.out.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    return {"run": r, "events": events, "result": result.get("result", "") or "", "is_error": result.get("is_error", True),
            "text": r.out + "\n" + r.err, "prompt": prompt}


def claude_tool_calls(events: list) -> list[dict]:
    """[{name, input, output, is_error}] pairing tool_use with tool_result."""
    uses, calls = {}, []
    for e in events:
        msg = e.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if c.get("type") == "tool_use":
                uses[c["id"]] = {"name": c["name"], "input": c.get("input", {})}
            elif c.get("type") == "tool_result":
                u = uses.get(c.get("tool_use_id"), {})
                body = c.get("content")
                if isinstance(body, list):
                    body = " ".join(str(x.get("text", x)) for x in body)
                calls.append({**u, "output": str(body), "is_error": bool(c.get("is_error"))})
    return calls


def codex_run(rep, cwd: Path, prompt: str, *, obs: Path | None = None, without_agents_md: bool = False) -> dict:
    """Headless `codex exec` in the replica: default approval/sandbox from config, never the bypass flag.
    without_agents_md: hide the replica CODEX_HOME/AGENTS.md for this one run only (restored in finally), so the model
    does not obey the coordinator rule and decline to attempt the command the hook is being probed with."""
    env = rep.env({"CRACC_OBS": str(obs)} if obs else {})
    cmd = [CODEX_BIN, "exec", *codex_model_args(), "--json", "--skip-git-repo-check", prompt]
    ag = rep.codex_home / "AGENTS.md"
    hidden = ag.with_name("AGENTS.md.cracc-hidden")
    moved = False
    if without_agents_md and ag.exists():
        ag.rename(hidden)
        moved = True
    try:
        r = run(cmd, env=env, cwd=cwd, timeout=RUNTIME_TIMEOUT)
    finally:
        if moved:
            hidden.rename(ag)
    items = []
    for line in r.out.splitlines():
        try:
            items.append(json.loads(line))
        except ValueError:
            pass
    final = ""
    for it in items:
        i = it.get("item") or {}
        if it.get("type") == "item.completed" and i.get("type") == "agent_message":
            final = i.get("text", "")
    # the human stream (hook lines) is on stderr only when not --json; capture hook trace separately
    return {"run": r, "items": items, "result": final, "text": r.out + "\n" + r.err}


def codex_hook_trace(rep, cwd: Path, obs: Path | None = None, prompt: str = "Reply with the single word OK") -> dict:
    """One non-JSON `codex exec` pass whose stdout shows `hook: <Event>` / `Completed` lines."""
    env = rep.env({"CRACC_OBS": str(obs)} if obs else {})
    r = run([CODEX_BIN, "exec", *codex_model_args(), "--skip-git-repo-check", prompt],
            env=env, cwd=cwd, timeout=RUNTIME_TIMEOUT)
    return {"run": r, "text": r.out + "\n" + r.err}


class RealEnv:
    """Stand-in for a Replica so codex_hooks_list can inventory a byte copy of the REAL Codex home (never the live one)."""
    def __init__(self, codex_home: Path | None = None):
        self.codex_home = codex_home

    def env(self, extra: dict | None = None) -> dict:
        e = dict(os.environ)
        if self.codex_home:
            e["CODEX_HOME"] = str(self.codex_home)
        return e


def codex_hooks_list(rep, cwd: Path, timeout: int = 60) -> dict:
    """Deterministic Codex hook inventory via the app-server `hooks/list` method (no model involved).
    Returns {hook key: {"trust": trustStatus, "hash": currentHash, "event": eventName, "command": command}}."""
    import subprocess as sp
    p = sp.Popen([CODEX_BIN, "app-server"], stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.DEVNULL, text=True,
                 cwd=cwd, env=rep.env())

    def send(o):
        p.stdin.write(json.dumps(o) + "\n")
        p.stdin.flush()

    def recv(i):
        while True:
            line = p.stdout.readline()
            if not line:
                return {}
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if m.get("id") == i:
                return m
    out: dict = {}
    try:
        send({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "cracc", "version": "1"}, "capabilities": {}}})
        recv(1)
        send({"method": "initialized"})
        send({"id": 2, "method": "hooks/list", "params": {"cwds": [str(cwd)]}})
        for e in (recv(2).get("result") or {}).get("data", []):
            for hk in e.get("hooks", []):
                out[hk["key"]] = {"trust": hk.get("trustStatus"), "hash": hk.get("currentHash"),
                                  "event": hk.get("eventName"), "command": hk.get("command", "")}
    finally:
        p.kill()
    return out


def claude_transcript_text(events: list) -> str:
    """Everything the model was GIVEN (user messages, slash-command expansions, tool results, hook output) - never its own
    assistant text - so an assertion on it cannot be satisfied by the model echoing or ignoring a probe."""
    parts = []
    for e in events:
        if e.get("type") == "assistant":
            continue
        msg = e.get("message") or {}
        c = msg.get("content")
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            for x in c:
                if x.get("type") == "tool_result":
                    b = x.get("content")
                    parts.append(b if isinstance(b, str) else " ".join(str(y.get("text", y)) for y in b or []))
                elif x.get("type") == "text":
                    parts.append(x.get("text", ""))
        if e.get("type") == "system":
            parts.append(json.dumps(e)[:4000])
    return "\n".join(parts)


def claude_session_given_text(rep, events: list) -> str:
    """Text the runtime gave the model, from the session's own on-disk transcript (<HOME>/.claude/projects/*/<session>.jsonl):
    user turns (including slash-command expansions) and tool results.  Assistant turns are excluded."""
    sid = next((e.get("session_id") for e in events if e.get("session_id")), None)
    if not sid:
        return ""
    parts = []
    for f in (rep.home / ".claude" / "projects").glob(f"*/{sid}.jsonl"):
        for line in f.read_text(errors="replace").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") != "user":
                continue
            c = (e.get("message") or {}).get("content")
            parts.append(c if isinstance(c, str) else json.dumps(c))
    return "\n".join(parts)
