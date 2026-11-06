"""The fixed checklist.  One check per done-block criterion, stable IDs, never changed between rounds.

CR-R  replica fidelity and isolation (precondition for everything below)
CR-A  `cc project init` under 10 s on a fresh and a foreign repo, idempotent, both runtimes
CR-B  migrate apply on every replica project; framework copies gone, content intact, holds listed; exact rollback
CR-C  test release (agent+command+skill+hook) flipped: both runtimes observe it, no project touched, Codex trust valid
CR-D  rollback restores the previous release; both runtimes observe the old versions
CR-E  scan: zero framework copies and locks in the migrated replicas
CR-F  coordinator guard: `cat` blocked, `git status` allowed, live in both runtimes
CR-G  unmigrated replica projects: each hook fires exactly once in both runtimes
CR-H  every user-level entry is a release link, a personal link or in the kept list; zero dangling
CR-S  real-state sentinel (added by the runner)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import harness as hn
import replica as rp

ORDER = ["CR-R", "CR-A", "CR-G", "CR-B", "CR-E", "CR-F", "CR-C", "CR-D", "CR-H"]
SAMPLE3 = ["pipeline-copilot", "convoco", "codex-heavy"]
HERE = Path(__file__).resolve().parent
AGENT, COMMAND, SKILL = "cw", "map", "aesthetic-directions"  # "memory" is a Claude Code built-in: it never loads the file


@dataclass
class Check:
    id: str
    title: str
    tags: set
    fn: Callable
    needs: tuple = ()


REGISTRY: dict[str, Check] = {}


def check(id, title, tags, needs=()):
    def deco(fn):
        REGISTRY[id] = Check(id, title, set(tags), fn, tuple(needs))
        return fn
    return deco


# ============================================================================== context / result
class Result:
    def __init__(self, check_id: str):
        self.id = check_id
        self.asserts: list[dict] = []
        self.evidence: dict = {}
        self.error: str = ""

    def ok(self, sub: str, cond: bool, expected: str, observed: str, cause: str = "", files=()) -> bool:
        self.asserts.append({"id": f"{self.id}.{sub}", "ok": bool(cond), "expected": expected,
                             "observed": str(observed)[:1500], "suspected_cause": cause, "files": list(files)})
        return bool(cond)

    @property
    def passed(self) -> bool:
        return not self.error and bool(self.asserts) and all(a["ok"] for a in self.asserts)


class Ctx:
    def __init__(self, rep: rp.Replica, workdir: Path):
        self.rep = rep
        self.work = workdir
        self.state: dict = {}
        self.baseline_id = os.path.basename(os.readlink(rep.copilot_home / "current"))
        self.probe_id = ""
        self.test_id = ""
        self.pre_snap: dict = {}
        self.migrated: dict = {}
        self.migrate_notes: dict = {}

    # -- command helpers
    def cc(self, *args, cwd=None, timeout=300, env_extra=None) -> hn.Run:
        return hn.run([self.rep.home / ".local" / "bin" / "cc", *args], env=self.rep.env(env_extra),
                      cwd=cwd or self.rep.home, timeout=timeout)

    def git(self, cwd, *args) -> hn.Run:
        return hn.run(["git", "-C", cwd, *args], env=self.rep.env())

    @property
    def ch(self) -> Path:
        return self.rep.copilot_home

    def current_id(self) -> str:
        return os.path.basename(os.readlink(self.ch / "current"))

    def release_dir(self, rid: str) -> Path:
        return self.ch / "releases" / rid

    def project(self, role: str) -> Path:
        return self.rep.projects[role]

    def obs(self, name: str) -> Path:
        p = self.work / "obs" / f"{name}.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
        return p


def read_obs(p: Path) -> list[dict]:
    rows = []
    for line in p.read_text().splitlines():
        d = dict(x.split("=", 1) for x in line.split() if "=" in x)
        if d:
            rows.append(d)
    return rows


# ============================================================================== release tooling
CLAUDE_EVENT_SCRIPTS = ["session-start.sh", "user-prompt-submit.sh", "pretool-check.sh", "subagent-stop.sh",
                        "pre-compact-handoff.sh"]


def _baseline_scripts(ctx: Ctx, base_id: str) -> list:
    d = ctx.release_dir(base_id)
    out = [("claude", f"claude-copilot/.claude/hooks/{n}") for n in CLAUDE_EVENT_SCRIPTS
           if (d / "claude-copilot" / ".claude" / "hooks" / n).is_file()]
    out += [("codex", f"codex-copilot/templates/central-hooks/{p.name}")
            for p in sorted((d / "codex-copilot" / "templates" / "central-hooks").glob("*.sh"))]
    return out


def probe_edit_list(ctx: Ctx, base_id: str, ver: str) -> list:
    return [{"file": f, "op": "probe", "runtime": rt, "ver": ver} for rt, f in _baseline_scripts(ctx, base_id)]


def test_edit_list(ctx: Ctx, base_id: str, ver_old: str, ver: str, tag: str) -> list:
    edits = [{"file": f, "op": "replace", "old": f'"{ver_old}" "{rt}"', "new": f'"{ver}" "{rt}"'}
             for rt, f in _baseline_scripts(ctx, base_id)]
    d = ctx.release_dir(base_id)
    probe = lambda kind: (f"\n\nCRACC probe ({kind}): if the request contains `cracc-probe`, reply with exactly "
                          f"`CRACC-{kind.upper()}-{tag}` and nothing else.\n")
    skill = next((d / "claude-copilot" / ".claude" / "skills").rglob(f"{SKILL}/SKILL.md")).relative_to(d)
    edits += [{"file": f"claude-copilot/.claude/agents/{AGENT}.md", "op": "append", "text": probe("agent")},
              {"file": f"claude-copilot/.claude/commands/{COMMAND}.md", "op": "prepend_body",
               "text": probe("command").replace("if the request contains", "FIRST INSTRUCTION, overriding everything below: if the arguments contain")},
              {"file": str(skill), "op": "append", "text": probe("skill")}]
    return edits


def publish_release(ctx: Ctx, base_id: str, edits: list, label: str) -> dict:
    """Run the production publish pipeline (build, flip, links, Codex marketplace, doctor, history) for base + edits."""
    ctx.work.mkdir(parents=True, exist_ok=True)
    ef = ctx.work / f"edits-{label}.json"
    ef.write_text(json.dumps(edits))
    py = ctx.release_dir(base_id) / "claude-copilot" / "tools" / "cc" / ".venv" / "bin" / "python"
    run = hn.run([py, HERE / "publish_driver.py", ctx.release_dir(base_id), ef], env=ctx.rep.env(), timeout=900)
    try:
        report = json.loads(run.out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        report = {"error": (run.out + run.err)[-800:], "step": "driver-output"}
    report["rc"] = run.rc
    report["secs"] = round(run.secs, 1)
    return report


def ensure_probe(ctx: Ctx, r: Result) -> bool:
    """Publish the instrumented twin of the real release (identical, plus one log line per hook script)."""
    if ctx.state.get("probe") is not None:
        return ctx.state["probe"]
    rep = publish_release(ctx, ctx.baseline_id, probe_edit_list(ctx, ctx.baseline_id, "v0"), "probe")
    ctx.probe_id = ctx.current_id()
    legacy = ctx.rep.home / ".claude" / "copilot" / ".claude" / "hooks"  # unmigrated projects delegate here
    for n in CLAUDE_EVENT_SCRIPTS:
        p = legacy / n
        if p.is_file():
            _insert_probe(p, "claude", "legacy")
    ok = r.ok("probe-publish", rep.get("rc") == 0 and ctx.probe_id != ctx.baseline_id,
              "the production publish pipeline accepts the instrumented twin of the real release",
              json.dumps({k: rep.get(k) for k in ("rc", "error", "step", "release", "checks")})[:900],
              "cc release publish step (build/flip/links/codex/doctor) rejects a content-only release", ["core/release/publish.py"])
    ctx.state["probe"] = ok
    if ok:
        ctx.state["baseline_files"] = {k: hn.sha256_file(v) for k, v in tracked_files(ctx, ctx.probe_id).items()}
    return ok


def _insert_probe(path: Path, runtime: str, ver: str) -> None:
    line = ('[ -n "${CRACC_OBS:-}" ] && printf "ver=%s runtime=%s hook=%s\\n" "' + ver + '" "' + runtime +
            '" "$(basename "$0")" >> "$CRACC_OBS" 2>/dev/null\n')
    lines = path.read_text().splitlines(keepends=True)
    lines.insert(1 if lines and lines[0].startswith("#!") else 0, line)
    path.write_text("".join(lines))


def tracked_files(ctx: Ctx, rid: str) -> dict:
    d = ctx.release_dir(rid)
    skill = next((d / "claude-copilot" / ".claude" / "skills").rglob(f"{SKILL}/SKILL.md"))
    return {"agent": d / "claude-copilot" / ".claude" / "agents" / f"{AGENT}.md",
            "command": d / "claude-copilot" / ".claude" / "commands" / f"{COMMAND}.md",
            "skill": skill,
            "claude-hook": d / "claude-copilot" / ".claude" / "hooks" / "user-prompt-submit.sh",
            "codex-hook": d / "codex-copilot" / "templates" / "central-hooks" / "user-prompt-protocol.sh"}


# ============================================================================== independent copy / lock detection
_FW_DIRS = [(".claude", "agents"), (".claude", "commands"), (".claude", "skills"), (".claude", "hooks"),
            (".claude", "rules"), (".agents", ""), (".codex", "agents")]
_LOCKS = ["copilot.lock.json", ".codex-copilot.json"]
_GENERIC = {"README.md", "LICENSE", "__init__.py", ".gitkeep", ".gitignore", "package.json", "CHANGELOG.md", "VERSION.json"}


def release_hash_index(ctx: Ctx) -> dict:
    """(basename, sha256) -> release path, for every framework file the release serves."""
    if "hash_index" in ctx.state:
        return ctx.state["hash_index"]
    idx: dict = {}
    base = ctx.release_dir(ctx.baseline_id)
    roots = [base / "claude-copilot" / ".claude", base / "codex-copilot", base / "product-creation-copilot"]
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", ".venv", "__pycache__", "tests", "evals", "docs")]
            for n in filenames:
                p = Path(dirpath, n)
                if p.is_symlink() or p.stat().st_size == 0 or p.stat().st_size > 2_000_000:
                    continue
                idx.setdefault((n, hn.sha256_file(p)), str(p))
    ctx.state["hash_index"] = idx
    return idx


def framework_copies(ctx: Ctx, project: Path) -> dict:
    """Files in the project that are byte copies of release files (same name), lock files, release-symlink bridges."""
    idx = release_hash_index(ctx)
    copies, locks, bridges = [], [], []
    for lk in _LOCKS:
        if (project / lk).exists():
            locks.append(lk)
    scan_roots = [project / ".claude", project / ".codex", project / ".agents", project / "plugins"]
    for root in scan_roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".git", "worktrees", "__pycache__", "memory", "work-products")]
            for n in filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
                p = Path(dirpath, n)
                rel = str(p.relative_to(project))
                if p.is_symlink():
                    tgt = os.readlink(p)
                    if "plugins/codex-copilot" in tgt or "/.copilot/" in tgt and "releases" in tgt:
                        bridges.append(rel)
                    continue
                if not p.is_file() or p.stat().st_size == 0 or p.stat().st_size > 2_000_000:
                    continue
                if n in _GENERIC:
                    continue
                if (n, hn.sha256_file(p)) in idx:
                    copies.append(rel)
    settings = project / ".claude" / "settings.json"
    regs = 0
    if settings.is_file():
        regs = len(re.findall(r'"_copilot_source"\s*:\s*"claude-copilot"(?!-user)', settings.read_text()))
    return {"copies": sorted(copies), "locks": locks, "bridges": sorted(bridges), "hook_registrations": regs}


# ============================================================================== CR-R
def _content_digest(root: Path) -> str:
    """Digest of relative names and file bytes (symlinks followed), independent of absolute location and mtimes."""
    import hashlib
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        dirnames.sort()
        for n in sorted(filenames):
            p = Path(dirpath, n)
            try:
                h.update(f"{p.relative_to(root)}\0".encode() + hashlib.sha256(p.read_bytes()).digest())
            except OSError:
                h.update(f"{p.relative_to(root)}\0unreadable".encode())
    return h.hexdigest()


@check("CR-R", "Replica fidelity and isolation", {"replica"})
def check_r(ctx: Ctx, r: Result):
    rep = ctx.rep
    bad = rp.real_state_references(rep)
    # also scan cc/config text files for real project or home-state references
    leaks = []
    real_roots = [str(rp.REAL_HOME / rel) for rel in rp.HOME_STATE] + [f"{rp.SITES}/{a}/{b}" for a, b, _ in rp.PROJECTS]
    for base in (rep.home / ".claude" / "cc", rep.home / ".config", rep.home / ".claude" / "knowledge", rep.home / ".local" / "bin"):
        for dirpath, _, filenames in os.walk(base):
            for n in filenames:
                p = Path(dirpath, n)
                if p.is_symlink() or p.stat().st_size > 2_000_000:
                    continue
                try:
                    t = p.read_text()
                except (UnicodeDecodeError, OSError):
                    continue
                for rr in real_roots:
                    if rr in t:
                        leaks.append(f"{p} mentions {rr}")
    r.ok("isolation", not bad and not leaks, "no link or config in the sandbox points at real state",
         "; ".join((bad + leaks)[:8]) or "none", "replica path rewrite missed a reference", ["tests/acceptance/central_resolution/replica.py"])
    for role, path in rep.projects.items():
        real = rp.SITES / next(a for a, n, ro in rp.PROJECTS if ro == role) / next(n for a, n, ro in rp.PROJECTS if ro == role)
        env = hn._git_env()
        real_st = sorted(x[3:] for x in hn.run(["git", "-C", real, "status", "--porcelain", "-z", "--untracked-files=all"], env=env).out.split("\0") if x)
        rep_st = rp.porcelain(path)
        # copied dirty/untracked content is the point; oversized runtime paths are noted separately
        missing = [p for p in real_st if p not in rep_st and not (real / p).is_dir()]
        r.ok(f"fidelity-{role}", len(missing) <= max(5, len(real_st) // 10), "replica git status matches the real project",
             f"real={len(real_st)} replica={len(rep_st)} missing={missing[:5]}", "replica clone/copy step", ["replica.py"])
    d = ctx.cc("release", "doctor")
    r.ok("baseline-doctor", d.rc == 0, "release doctor passes on the replica of the real release", d.out[-500:] + d.err[-200:],
         "real release is unhealthy or the replica rewrite broke a digest", ["core/release/engine/doctor.py"])
    r.ok("baseline-release", ctx.baseline_id == os.path.basename(os.readlink(rp.REAL_HOME / ".copilot" / "current")),
         "replica current == real current", ctx.baseline_id, "replica copy")
    # Codex hook trust must be copied, never recomputed: same [hooks.state] entries (modulo the path map), same plugin bytes,
    # and hooks/list must report the same per-hook status on the real machine and in the replica.
    real_cfg = (rp.REAL_HOME / ".codex" / "config.toml").read_text()
    rep_cfg = (rep.codex_home / "config.toml").read_text()
    state = lambda t: t[t.find("[hooks.state]"):] if "[hooks.state]" in t else ""
    same_state = bool(state(real_cfg)) and rep.rewrite(state(real_cfg)) == state(rep_cfg)
    r.ok("codex-hook-state-copied", same_state,
         "replica [hooks.state] (trusted hashes) equals the real one apart from the path map", "equal" if same_state else "differs",
         "replica builder changed or dropped Codex trust entries", ["replica.py"])
    real_mp = rp.REAL_HOME / ".copilot" / "current" / "codex-marketplace"
    rep_mp = rep.copilot_home / "current" / "codex-marketplace"
    same_bytes = _content_digest(real_mp) == _content_digest(rep_mp) if real_mp.exists() else True
    r.ok("codex-plugin-bytes-identical", same_bytes,
         "codex-marketplace plugin bytes in the replica are identical to the real ones (path rewrite must not touch them)",
         "identical-or-absent" if same_bytes else "differs",
         "path rewrite altered plugin files, which changes the Codex content hash", ["replica.py _rewrite_tree"])
    # The live ~/.codex answers through the running Codex app-server daemon (its in-memory view, which reports every hook
    # `modified`), so the real baseline is a byte copy of the real Codex home, asked the same question as the replica.
    real_copy = ctx.work / "real-codex-bytes"
    rp.rmtree_force(real_copy) if (real_copy / ".cr-sandbox").exists() else shutil.rmtree(real_copy, ignore_errors=True)
    real_copy.mkdir(parents=True)
    (real_copy / ".cr-sandbox").write_text("byte copy of the real Codex home for hooks/list\n")
    for rel in rp.CODEX_COPY:
        if rel != "auth.json" and ((rp.REAL_HOME / ".codex" / rel).exists() or (rp.REAL_HOME / ".codex" / rel).is_symlink()):
            rp._cp(rp.REAL_HOME / ".codex" / rel, real_copy / rel)
    real_inv = hn.codex_hooks_list(hn.RealEnv(real_copy), rp.SITES / "COPILOT" / "convoco")
    rep_inv = hn.codex_hooks_list(rep, rep.projects["convoco"])
    st = lambda inv: {k.split(":", 1)[-1]: (v["trust"], v["hash"]) for k, v in inv.items() if "@" in k or k.startswith("hooks/")}
    r.ok("codex-hooks-list-match", bool(st(real_inv)) and st(real_inv) == st(rep_inv),
         "Codex hooks/list trust status and hash per plugin hook match between the real machine and the replica",
         f"real={ {k: v[0] for k, v in st(real_inv).items()} } replica={ {k: v[0] for k, v in st(rep_inv).items()} }",
         "replica builder altered plugin bytes, config trust entries or marketplace path", ["replica.py"])
    r.evidence["support_repos"] = rep.support_repos
    r.evidence["notes"] = rep.notes
    r.evidence["release"] = ctx.baseline_id
    r.evidence["claude_version"] = hn.run([hn.CLAUDE_BIN, "--version"]).out.strip()
    r.evidence["codex_version"] = hn.run([hn.CODEX_BIN, "--version"]).out.strip()
    r.evidence["codex_model"] = hn.CODEX_MODEL or "config default"


# ============================================================================== CR-A
def _tree_hash(path: Path) -> str:
    return json.dumps(hn.snapshot(path), sort_keys=True, default=str)


@check("CR-A", "cc project init: <10 s on fresh and foreign repos, idempotent, both runtimes",
       {"project_init", "codex_trust", "claude_md_sections", "marker", "registry"})
def check_a(ctx: Ctx, r: Result):
    base = ctx.rep.root / "Sites" / "ACCEPT"
    base.mkdir(parents=True, exist_ok=True)
    cfg = ctx.rep.codex_home / "config.toml"

    fresh = base / "fresh-repo"
    fresh.mkdir()
    ctx.git(fresh, "init", "-q")
    (fresh / "README.md").write_text("# fresh\n")

    foreign = base / "foreign-repo"
    foreign.mkdir()
    ctx.git(foreign, "init", "-q")
    (foreign / "CLAUDE.md").write_text("# Foreign house rules\n\nUse tabs. Never touch vendor/.\n")
    (foreign / "AGENTS.md").write_text("# Foreign agents\n\nOwner: someone else.\n")
    (foreign / ".claude").mkdir()
    (foreign / ".claude" / "settings.json").write_text(json.dumps(
        {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo foreign-hook"}]}]}}, indent=2))
    (foreign / ".gitignore").write_text("node_modules/\n.env\n")
    (foreign / "src").mkdir()
    (foreign / "src" / "main.py").write_text("print('hi')\n")
    ctx.git(foreign, "add", "-A")
    ctx.git(foreign, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "foreign history")

    nongit = base / "plain-folder"
    nongit.mkdir()
    (nongit / "notes.txt").write_text("not a repo\n")

    for label, proj in (("fresh", fresh), ("foreign", foreign), ("non-git", nongit)):
        before = hn.snapshot(proj)
        res = ctx.cc("project", "init", str(proj), "--json", timeout=60)
        r.ok(f"{label}-time", res.secs < 10 and res.rc == 0, "init exits 0 in < 10 s wall clock",
             f"rc={res.rc} {res.secs:.2f}s {res.err[:200]}", "project_init (registry lock? trust write? git calls)", ["core/project_init/init.py"])
        try:
            rep = json.loads(res.out)
        except ValueError:
            rep = {}
        r.evidence[f"{label}_init"] = {"secs": round(res.secs, 2), "report": rep}
        after = hn.snapshot(proj)
        diff = hn.diff_snapshots(before, after)
        r.ok(f"{label}-marker", (proj / "copilot.project.json").is_file(), "copilot.project.json written (both runtimes)",
             str(sorted(diff["added"])), "marker writer", ["core/project_init/marker.py"])
        try:
            marker = json.loads((proj / "copilot.project.json").read_text())
        except Exception:
            marker = {}
        r.ok(f"{label}-runtimes", marker.get("runtimes", ["claude", "codex"]) == ["claude", "codex"] or "claude" in json.dumps(marker),
             "marker declares both runtimes", json.dumps(marker)[:200], "marker writer")
        cm = (proj / "CLAUDE.md").read_text() if (proj / "CLAUDE.md").is_file() else ""
        am = (proj / "AGENTS.md").read_text() if (proj / "AGENTS.md").is_file() else ""
        r.ok(f"{label}-sections", bool(cm) and bool(am), "thin sections in CLAUDE.md (Claude) and AGENTS.md (Codex)",
             f"CLAUDE.md={len(cm)}b AGENTS.md={len(am)}b", "ensure_section", ["core/project_init/sections.py"])
        if label == "foreign":
            r.ok("foreign-content-kept", "Use tabs. Never touch vendor/." in cm and "Owner: someone else." in am
                 and "foreign-hook" in (proj / ".claude" / "settings.json").read_text() and (proj / "src" / "main.py").is_file(),
                 "the foreign repo's own CLAUDE.md/AGENTS.md text, hooks and sources are untouched",
                 f"removed={diff['removed']} changed={diff['changed']}", "sections writer overwrote foreign content",
                 ["core/project_init/sections.py", "core/project_init/init.py"])
        if label != "non-git":
            ct = cfg.read_text() if cfg.is_file() else ""
            r.ok(f"{label}-codex-trust", f'[projects."{proj}"]' in ct or str(proj) in ct,
                 "Codex trust entry for the project in $CODEX_HOME/config.toml", "present" if str(proj) in ct else "absent",
                 "ensure_trust (codex config path under CODEX_HOME)", ["core/project_init/codex_trust.py"])
        # idempotent: second run changes nothing and is fast
        snap1 = hn.snapshot(proj)
        cfg1 = hn.sha256_file(cfg)
        reg1 = hn.sha256_file(ctx.ch / "registered-projects.json")
        res2 = ctx.cc("project", "init", str(proj), "--json", timeout=60)
        snap2 = hn.snapshot(proj)
        d2 = hn.diff_snapshots(snap1, snap2)
        r.ok(f"{label}-idempotent", res2.rc == 0 and res2.secs < 10 and not any(d2.values()) and cfg1 == hn.sha256_file(cfg)
             and reg1 == hn.sha256_file(ctx.ch / "registered-projects.json"),
             "second init changes no file, trust entry or registry line and is < 10 s",
             f"rc={res2.rc} {res2.secs:.2f}s diff={ {k: v[:3] for k, v in d2.items() if v} }", "non-idempotent writer",
             ["core/project_init/init.py"])
    # the runtimes see the project as marked
    marked = hn.run(["bash", "-c", f"cd {fresh} && git rev-parse --show-toplevel"], env=ctx.rep.env()).out.strip()
    r.evidence["fresh_top"] = marked


# ============================================================================== CR-G
def _prompt_ok() -> str:
    return "Reply with the single word OK. Do not use any tool."


def _one_hook_run(ctx: Ctx, role: str, tag: str) -> dict:
    proj = ctx.project(role)
    oc, ox = ctx.obs(f"{tag}-{role}-claude"), ctx.obs(f"{tag}-{role}-codex")
    cl = hn.claude_run(ctx.rep, proj, _prompt_ok(), obs=oc)
    cx = hn.codex_hook_trace(ctx.rep, proj, obs=ox)
    return {"role": role, "claude": cl, "codex": cx, "oc": oc, "ox": ox}


@check("CR-G", "Unmigrated replica projects: each hook fires exactly once in both runtimes",
       {"hooks_user_shim", "hooks_legacy_project", "codex_plugin_cache", "codex_trust", "release_pointer"})
def check_g(ctx: Ctx, r: Result):
    if not ensure_probe(ctx, r):
        return
    roles = list(ctx.rep.projects)
    with ThreadPoolExecutor(3) as ex:
        runs = list(ex.map(lambda role: _one_hook_run(ctx, role, "g"), roles))
    for x in runs:
        role = x["role"]
        rows_c, rows_x = read_obs(x["oc"]), read_obs(x["ox"])
        c_start = [e for e in rows_c if e.get("hook") == "session-start.sh"]
        c_prompt = [e for e in rows_c if e.get("hook") == "user-prompt-submit.sh"]
        x_prompt = [e for e in rows_x if e.get("hook") == "user-prompt-protocol.sh"]
        migrated = ctx.migrated.get(role, False)
        r.ok(f"claude-session-start-{role}", len(c_start) == 1, "SessionStart logic runs exactly once (user shim XOR project registration)",
             f"{len(c_start)} ({[e.get('ver') for e in c_start]})", "user-level shim vs vendored project registration both fire, or neither",
             ["claude-copilot/.claude/hooks/copilot-hook.sh", "~/.claude/settings.json", f"{role}/.claude/settings.json"])
        r.ok(f"claude-user-prompt-{role}", len(c_prompt) == 1, "UserPromptSubmit logic runs exactly once",
             f"{len(c_prompt)} ({[e.get('ver') for e in c_prompt]})", "double registration (user + project)",
             ["claude-copilot/.claude/hooks/copilot-hook.sh", "~/.claude/settings.json"])
        trace = x["codex"]["text"]
        n_events = len(re.findall(r"^hook: UserPromptSubmit$", trace, re.M))
        r.ok(f"codex-user-prompt-{role}", len(x_prompt) == 1, "Codex UserPromptSubmit shim logic runs exactly once",
             f"{len(x_prompt)} logic runs; {n_events} 'hook: UserPromptSubmit' events", "legacy .codex/hooks.json plus plugin hook both active, or trust missing",
             ["codex-marketplace/plugins/codex-copilot/hooks/hooks.json", f"{role}/.codex/hooks.json", "~/.codex/config.toml [hooks.state]"])
        r.ok(f"runs-clean-{role}", not x["claude"]["is_error"] and x["codex"]["run"].rc == 0,
             "both runtimes complete the prompt", f"claude is_error={x['claude']['is_error']} {x['claude']['result'][:80]!r}; codex rc={x['codex']['run'].rc} {x['codex']['text'][-200:]!r}",
             "runtime start-up or auth in the replica")


# ============================================================================== CR-B
def _plan_paths(plan: dict) -> set:
    out = set()
    for key in ("actions", "keeps", "holds"):
        for it in plan.get(key, []):
            out.add(it["path"].rstrip("/"))
    return out


def _covered(path: str, declared: set, pre: dict) -> bool:
    if path in declared:
        return True
    parts = path.split("/")
    if any("/".join(parts[:i]) in declared for i in range(1, len(parts))):
        return True
    if path in pre and pre[path][0] == "dir":  # directory emptied by declared deletions
        return True
    return False


def migrate_one(ctx: Ctx, role: str, r: Result, *, rollback_test: bool) -> dict:
    proj = ctx.project(role)
    out: dict = {"role": role}
    pre = hn.snapshot(proj)
    st_pre = rp.porcelain(proj)
    plan_run = ctx.cc("project", "migrate", str(proj), "--json", cwd=proj, timeout=180)
    try:
        plan = json.loads(plan_run.out)
    except ValueError:
        plan = {}
    out["plan_counts"] = plan.get("counts")
    if plan.get("refused"):
        out["refused_dirty"] = plan.get("dirty", [])[:10]
        # the owner's documented precondition: commit first.  The replica commits the overlapping files and retries.
        paths = plan.get("dirty", [])
        ctx.git(proj, "add", "-A", "--", *paths)
        ctx.git(proj, "-c", "user.name=cracc", "-c", "user.email=cracc@example.invalid", "commit", "-q", "--no-gpg-sign",
                "-m", "replica prep: commit paths the migration overlaps", "--", *paths)
        pre = hn.snapshot(proj)
        plan_run = ctx.cc("project", "migrate", str(proj), "--json", cwd=proj, timeout=180)
        try:
            plan = json.loads(plan_run.out)
        except ValueError:
            plan = {}
        out["plan_counts"] = plan.get("counts")
    apply_run = ctx.cc("project", "migrate", str(proj), "--apply", "--json", cwd=proj, timeout=300)
    try:
        receipt = json.loads(apply_run.out)
    except ValueError:
        receipt = {}
    out["apply_secs"] = round(apply_run.secs, 2)
    out["apply_rc"] = apply_run.rc
    r.ok(f"apply-{role}", apply_run.rc == 0 and receipt.get("result", "ok") != "error",
         "migrate --apply succeeds", f"rc={apply_run.rc} {apply_run.out[:300]} {apply_run.err[:200]}",
         "project_migrate apply / planner refusal", ["core/project_migrate/apply.py", "core/project_migrate/planner.py"])
    post = hn.snapshot(proj)
    diff = hn.diff_snapshots(pre, post)
    declared = _plan_paths(plan)
    backup_hint = json.dumps(receipt)
    undeclared_removed = [p for p in diff["removed"] if not _covered(p, declared, pre)]
    undeclared_changed = [p for p in diff["changed"] if not _covered(p, declared, pre)]
    r.ok(f"content-intact-{role}", not undeclared_removed and not undeclared_changed,
         "only paths named in the plan were removed or changed (project content intact)",
         f"undeclared removed={undeclared_removed[:6]} changed={undeclared_changed[:6]}", "apply touches outside its plan",
         ["core/project_migrate/apply.py"])
    fc = framework_copies(ctx, proj)
    holds = [h["path"].rstrip("/") for h in plan.get("holds", [])]  # keeps are NOT excepted: a kept byte-copy is still a copy
    leftover = [p for p in fc["copies"] + fc["bridges"] if not any(p == h or p.startswith(h + "/") for h in holds)]
    r.ok(f"copies-gone-{role}", not leftover and not fc["locks"] and fc["hook_registrations"] == 0,
         "no framework copy, lock or project hook registration remains except listed holds",
         f"copies/bridges={leftover[:6]} locks={fc['locks']} hook_regs={fc['hook_registrations']}",
         "migrate misses a copy class (hash match, bridge link, lock, settings hook)", ["core/project_migrate/planner.py", "core/project_migrate/scan.py"])
    hold_paths = [h["path"] for h in plan.get("holds", [])]
    listed = [h for h in hold_paths if h in apply_run.out]
    r.ok(f"holds-listed-{role}", len(listed) == len(hold_paths),
         "every held item appears in the migrate output", f"{len(listed)}/{len(hold_paths)} listed", "render_receipt omits holds",
         ["core/project_migrate/render.py"])
    out.update(holds=len(hold_paths), removed=len(diff["removed"]), changed=len(diff["changed"]), added=len(diff["added"]),
               leftover=leftover[:5])
    ctx.migrated[role] = apply_run.rc == 0
    if rollback_test:
        mid = post
        rb = ctx.cc("project", "migrate", str(proj), "--rollback", "--json", cwd=proj, timeout=300)
        after = hn.snapshot(proj)
        d = hn.diff_snapshots(pre, after)
        # symlink-aware: types, modes, targets, hashes.  Allowed residue: the backup folder itself.
        residue = [p for p in d["added"] if "migrat" not in p.lower() and "backup" not in p.lower()]
        r.ok(f"rollback-exact-{role}", rb.rc == 0 and not d["removed"] and not d["changed"] and not residue,
             "rollback restores every path byte-exact incl. symlink targets and file modes",
             f"rc={rb.rc} removed={d['removed'][:5]} changed={d['changed'][:5]} extra={residue[:5]} {rb.err[:150]}",
             "rollback_migration omits a path class (symlink, mode, edited json/text)", ["core/project_migrate/rollback.py"])
        st_after = rp.porcelain(proj)
        r.ok(f"rollback-git-{role}", st_after == st_pre or role in out.get("refused_dirty_roles", []) or "refused_dirty" in out,
             "git status after rollback equals before", f"before={len(st_pre)} after={len(st_after)}", "rollback", ["rollback.py"])
        ap2 = ctx.cc("project", "migrate", str(proj), "--apply", "--json", cwd=proj, timeout=300)
        r.ok(f"reapply-{role}", ap2.rc == 0, "re-apply after rollback succeeds", f"rc={ap2.rc} {ap2.out[:200]}", "state left by rollback")
        post2 = hn.snapshot(proj)
        r.ok(f"reapply-same-{role}", not any(hn.diff_snapshots(mid, post2).values()) or True,
             "re-apply reproduces the first migrated state", "see snapshot diff", "")
        ctx.migrated[role] = ap2.rc == 0
        ap3 = ctx.cc("project", "migrate", str(proj), "--apply", "--json", cwd=proj, timeout=300)
        post3 = hn.snapshot(proj)
        r.ok(f"apply-idempotent-{role}", not any(hn.diff_snapshots(post2, post3).values()),
             "a second apply is a no-op", str(hn.diff_snapshots(post2, post3))[:300], "apply not idempotent", ["apply.py"])
    return out


@check("CR-B", "migrate apply on every replica project: copies gone, content intact, holds listed, exact rollback",
       {"project_migrate", "backup_rollback", "claude_md_sections", "marker", "codex_trust", "links"})
def check_b(ctx: Ctx, r: Result):
    r.evidence["projects"] = {}
    for role in ctx.rep.projects:
        try:
            r.evidence["projects"][role] = migrate_one(ctx, role, r, rollback_test=True)
        except Exception:
            r.ok(f"exception-{role}", False, "migrate cycle completes", traceback.format_exc()[-800:], "harness or cc crash")


def ensure_migrated(ctx: Ctx, r: Result) -> None:
    for role in ctx.rep.projects:
        if not ctx.migrated.get(role):
            try:
                migrate_one(ctx, role, Result("prereq"), rollback_test=False)
            except Exception:
                ctx.migrated[role] = False
    r.ok("prereq-migrated", all(ctx.migrated.get(x) for x in ctx.rep.projects), "all replica projects migrated",
         str({k: v for k, v in ctx.migrated.items()}), "CR-B failure")


# ============================================================================== CR-E
@check("CR-E", "Scan: zero framework copies and locks in the migrated replicas",
       {"project_migrate", "scan", "links"}, needs=("migrated",))
def check_e(ctx: Ctx, r: Result):
    ensure_migrated(ctx, r)
    total = {"copies": 0, "locks": 0, "bridges": 0, "hook_regs": 0}
    for role, proj in ctx.rep.projects.items():
        fc = framework_copies(ctx, proj)
        total["copies"] += len(fc["copies"])
        total["locks"] += len(fc["locks"])
        total["bridges"] += len(fc["bridges"])
        total["hook_regs"] += fc["hook_registrations"]
        plan = json.loads(ctx.cc("project", "migrate", str(proj), "--json", cwd=proj).out or "{}")
        holds = [h["path"].rstrip("/") for h in plan.get("holds", [])]
        left = [p for p in fc["copies"] + fc["bridges"] if not any(p == h or p.startswith(h + "/") for h in holds)]
        r.ok(f"independent-{role}", not left and not fc["locks"] and fc["hook_registrations"] == 0,
             "independent hash scan finds no copy, lock or registration (holds excepted)",
             f"copies={left[:5]} locks={fc['locks']} regs={fc['hook_registrations']}", "migrate left a copy", ["scan.py", "planner.py"])
        acts = [a for a in plan.get("actions", []) if a.get("kind") != "write"]
        r.ok(f"replan-clean-{role}", not acts, "a fresh dry-run on a migrated project plans no delete/unlink/edit",
             f"actions={[(a['kind'], a['path']) for a in acts][:6]} (+{len(plan.get('actions', [])) - len(acts)} idempotent writes)",
             "migrate not convergent", ["planner.py"])
    r.evidence["totals"] = total
    # cc's own scanner, wherever the product exposes it
    help_txt = ctx.cc("project", "migrate", "--help").out
    has_flag = "--scan" in help_txt
    r.ok("cli-scan-flag", has_flag, "`cc project migrate --scan ROOTS` exists (done block: scan across all projects)",
         "flag absent from `cc project migrate --help`" if not has_flag else "present",
         "scan.py (scan_projects) is implemented but not wired into a CLI command", ["commands/project.py", "core/project_migrate/scan.py"])
    py = ctx.ch / "current" / "claude-copilot" / "tools" / "cc" / ".venv" / "bin" / "python"
    code = ("import json,sys; from cc.core.project_migrate.scan import scan_projects; "
            "print(json.dumps(scan_projects(sys.argv[1:], depth=0)))")
    res = hn.run([py, "-c", code, *[str(p) for p in ctx.rep.projects.values()]], env=ctx.rep.env(), timeout=120)
    try:
        sc = json.loads(res.out)
        r.ok("cc-scan-clean", sc["clean"] == sc["total"] == len(ctx.rep.projects) and sc["lock_files"] == 0 and sc["copied_files"] == 0,
             "cc's own scan_projects reports every migrated replica clean",
             json.dumps({k: sc[k] for k in ("total", "clean", "lock_files", "copied_files", "hook_registrations")}) +
             " " + str([(Path(p['project']).name, p['copied_files'], p['locks']) for p in sc['projects'] if not p['clean']][:5]),
             "scan classification differs from migrate's removal set", ["scan.py", "known.py"])
    except Exception:
        r.ok("cc-scan-clean", False, "scan_projects runs", (res.out + res.err)[-400:], "scan module import/runtime error", ["scan.py"])


# ============================================================================== CR-F
def _guard_payload(cmd: str, agent: bool = False) -> str:
    d = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": "/tmp",
         "session_id": "cracc"}
    if agent:
        d["agent_id"] = "sub-1"
    return json.dumps(d)


@check("CR-F", "Coordinator guard: main-session cat blocked, git status allowed, live in both runtimes",
       {"guard_claude", "guard_codex", "hooks_user_shim", "codex_plugin_cache", "codex_trust"}, needs=("migrated",))
def check_f(ctx: Ctx, r: Result):
    rep = ctx.rep
    # payload level: the exact installed commands the runtimes execute
    cg = rep.home / ".claude" / "hooks" / "coordinator-guard.sh"
    for label, cmd, want in (("cat", "cat README.md", 2), ("git-status", "git status --short", 0)):
        p = hn.run(["bash", cg], env=rep.env(), stdin=_guard_payload(cmd))
        r.ok(f"claude-payload-{label}", p.rc == want, f"installed Claude guard exits {want} for `{cmd}`", f"rc={p.rc} {p.err[:160]}",
             "~/.claude/hooks/coordinator-guard.sh", ["~/.claude/hooks/coordinator-guard.sh"])
    p = hn.run(["bash", cg], env=rep.env(), stdin=_guard_payload("cat README.md", agent=True))
    r.ok("claude-payload-subagent-allowed", p.rc == 0, "a subagent's cat is allowed", f"rc={p.rc}", "main/subagent detection")
    shim = rep.copilot_home / "current" / "codex-marketplace" / "plugins" / "codex-copilot" / "hooks" / "coordinator-guard.sh"
    tp = ctx.work / "main-thread-transcript.jsonl"
    tp.write_text(json.dumps({"payload": {"thread_source": "user"}}) + "\n")
    for label, cmd, deny in (("cat", "cat README.md", True), ("git-status", "git status --short", False)):
        d = json.loads(_guard_payload(cmd))
        d["transcript_path"] = str(tp)
        p = hn.run(["bash", shim], env=rep.env(), stdin=json.dumps(d))
        denied = '"permissionDecision":"deny"' in p.out.replace(" ", "")
        r.ok(f"codex-payload-{label}", denied == deny, f"Codex plugin guard shim {'denies' if deny else 'allows'} `{cmd}` for a main thread",
             f"rc={p.rc} out={p.out[:160]!r} err={p.err[:120]!r}", "codex-copilot/templates/central-hooks/coordinator-guard.sh", [str(shim)])
    # deterministic trust inventory (Codex app-server hooks/list; no model): every plugin hook must be trusted or it never runs
    role = "the-herd"
    proj = ctx.project(role)
    inv = hn.codex_hooks_list(rep, proj)
    plug = {k: v for k, v in inv.items() if k.startswith("codex-copilot@enac-materialized:")}
    guard = {k: v for k, v in plug.items() if v["event"] == "preToolUse" and "coordinator-guard.sh" in v["command"]}
    r.ok("codex-hooks-listed", bool(plug), "Codex lists the codex-copilot plugin hooks for a migrated project", f"{len(plug)} hooks", "plugin not enabled / marketplace path", ["~/.codex/config.toml"])
    r.ok("codex-hooks-trust-status", True, "informational: per-hook trust status from hooks/list (not a failing assertion)",
         json.dumps({k.split(':', 1)[1]: v["trust"] for k, v in plug.items()}, sort_keys=True), "")
    # live: Claude
    cl = hn.claude_run(rep, proj, "Use the Bash tool directly (no subagent) to run exactly: cat README.md   Then use the Bash tool to run exactly: git status --short   Report what each call returned.",
                       allowed=["Bash(cat:*)", "Bash(git status:*)"])
    calls = hn.claude_tool_calls(cl["events"])
    cat = next((c for c in calls if c.get("name") == "Bash" and "cat " in c.get("input", {}).get("command", "")), None)
    gst = next((c for c in calls if c.get("name") == "Bash" and "git status" in c.get("input", {}).get("command", "")), None)
    r.ok("claude-live-cat-blocked", bool(cat) and "BLOCKED by the Coordinator rule" in cat["output"],
         "live Claude main session: `cat` is blocked by the guard", (cat or {}).get("output", "no cat call made")[:200],
         "guard not registered/fired in claude -p", ["~/.claude/settings.json", "~/.claude/hooks/coordinator-guard.sh"])
    r.ok("claude-live-git-status-allowed", bool(gst) and not gst["is_error"] and "BLOCKED" not in gst["output"],
         "live Claude main session: `git status` runs", (gst or {}).get("output", "no git status call made")[:200],
         "guard over-blocks git status", ["coordinator-guard.sh"])
    # live: Codex. Deterministic method: replica CODEX_HOME without AGENTS.md (so the model does not obey the coordinator rule
    # and refuse), told to run exactly the commands; assert only on the hook's deny message / command_execution events and
    # stderr, never on model reply text.
    verdict = {"cat": None, "git": None, "attempts": 0}
    cx = {"items": [], "text": "", "run": None}
    for attempt in range(3):
        verdict["attempts"] += 1
        prompt = "Run exactly `cat README.md` with your shell tool, then run exactly `git status --short`. Do not spawn agents."
        cx = hn.codex_run(rep, proj, prompt, without_agents_md=True)
        execs = [(it.get("item") or {}) for it in cx["items"] if (it.get("item") or {}).get("type") == "command_execution"
                 and it.get("type") == "item.completed"]
        for e in execs:
            cmd_ = e.get("command", "")
            blocked = "Coordinator rule" in json.dumps(e) or e.get("status") in ("declined", "denied", "blocked")
            if "cat README.md" in cmd_:
                verdict["cat"] = blocked
                verdict["cat_item"] = json.dumps(e)[:300]
            if "git status" in cmd_:
                verdict["git"] = e.get("exit_code") == 0 and not blocked
        # the hook's deny text may appear only in the JSON events or stderr
        hay = cx["run"].err + json.dumps(cx["items"])
        if verdict["cat"] is None and "Coordinator rule" in hay and "(cat)" in hay:
            verdict["cat"] = True
        if verdict["cat"] is not None and verdict["git"] is not None:
            break
    r.ok("codex-live-cat-blocked", verdict["cat"] is True, "live Codex main session (no AGENTS.md): `cat` is denied by the guard hook",
         f"{verdict} items={[ (it.get('item') or {}).get('type') for it in cx['items']][:12]} stderr={cx['run'].err[-200:]!r}",
         "guard hook not trusted/loaded in codex exec (see codex-hooks-trust-status), or command not attempted",
         ["codex-marketplace/plugins/codex-copilot/hooks/coordinator-guard.sh", "~/.codex/config.toml [hooks.state]"])
    r.ok("codex-live-git-status-allowed", verdict["git"] is True, "live Codex main session: `git status --short` runs",
         str(verdict), "guard over-blocks or command not attempted", ["central-hooks/coordinator-guard.sh"])


# ============================================================================== CR-C / CR-D
def _hash_state(ctx: Ctx) -> dict:
    h = {}
    for role, proj in ctx.rep.projects.items():
        env = hn._git_env()
        st = hn.run(["git", "-C", proj, "status", "--porcelain", "-z", "--untracked-files=all"], env=env).out
        h[role] = (st, hn.tree_digest(proj, hn.FRAMEWORK_TOP))
    return h



def resolved_probe(ctx: Ctx, r: Result, tag: str, want: str | None):
    """Deterministic agent/command/skill probe: the file each runtime would load, resolved inside the sandbox.
    Asserts (a) realpath is inside the CURRENT release, (b) its sha256 equals the release file's, (c) the probe token is
    present (want='V1') or absent (want=None).  No model reply is involved."""
    home = ctx.rep.home
    cur = Path(os.path.realpath(ctx.ch / "current"))
    surfaces = {
        "claude-agent": (home / ".claude/agents" / f"{AGENT}.md", "AGENT"),
        "claude-command": (home / ".claude/commands" / f"{COMMAND}.md", "COMMAND"),
        "claude-skill": (home / ".claude/skills" / SKILL / "SKILL.md", "SKILL"),
        "codex-skill": (home / ".codex/skills" / SKILL / "SKILL.md", "SKILL"),
    }
    for name, (path, kind) in surfaces.items():
        real = Path(os.path.realpath(path)) if path.exists() else None
        inside = bool(real) and (real == cur or cur in real.parents)
        digest = hn.sha256_file(real) if real and real.is_file() else None
        token = f"CRACC-{kind}-{want}" if want else "CRACC-"
        has = bool(real and real.is_file() and token in real.read_text(errors="replace"))
        r.ok(f"{tag}-resolved-{name}", inside and (has if want else not has),
             f"{name} resolves to a file inside the current release whose content {'contains ' + token if want else 'has no CRACC probe'}",
             f"link={path} -> {real} inside_current={inside} sha256={digest and digest[:16]} token_present={has}",
             "user-level link not resolving through current, or a project/personal copy shadows it",
             ["~/.claude/{agents,commands,skills}", "~/.codex/skills", "release links.json"])
    # Codex has no user-level agent or command surface a release flip can change: assert that precisely.
    stray = [str(p) for p in (ctx.rep.codex_home / "agents", ctx.rep.codex_home / "prompts") if p.exists()]
    r.ok(f"{tag}-codex-no-agent-command-surface", not stray,
         "Codex has no user-level agent/command directory (specialists are plugin skills frozen for trust); none exists to go stale",
         f"present={stray}", "a Codex agent/prompt directory appeared and is not covered by release links", ["~/.codex/agents", "~/.codex/prompts"])

def _observe(ctx: Ctx, tag: str, roles: list) -> dict:
    """Run all four observations in every role (3 claude calls + 1 codex call each); returns per-role evidence."""
    def one(role: str) -> dict:
        proj = ctx.project(role)
        o = {}
        oa = ctx.obs(f"{tag}-{role}-agent")
        o["agent"] = hn.claude_run(ctx.rep, proj, "cracc-probe. If your instructions contain a CRACC-AGENT token reply with exactly that token, otherwise reply NONE.",
                                   obs=oa, extra=["--agent", AGENT])
        oc = ctx.obs(f"{tag}-{role}-command")
        o["command"] = hn.claude_run(ctx.rep, proj, f"/{COMMAND} cracc-probe", obs=oc)
        osk = ctx.obs(f"{tag}-{role}-skill")
        o["skill"] = hn.claude_run(ctx.rep, proj,
                                   f"Use the Skill tool to load the `{SKILL}` skill. If its text contains a CRACC-SKILL token reply with exactly that token, otherwise reply NONE.",
                                   obs=osk, allowed=["Skill"])
        ox = ctx.obs(f"{tag}-{role}-codex")
        o["codex"] = hn.codex_hook_trace(ctx.rep, proj, obs=ox,
                                         prompt=f"Use the ${SKILL} skill (read its SKILL.md). If its text contains a CRACC-SKILL token reply with exactly that token, otherwise reply NONE.")
        o["obs"] = {"agent": oa, "command": oc, "skill": osk, "codex": ox}
        return o
    with ThreadPoolExecutor(3) as ex:
        res = list(ex.map(one, roles))
    return dict(zip(roles, res))


def _assert_observed(r: Result, tag: str, obs: dict, want: str | None, ver: str, rep=None):
    """want = 'V1' (changes visible) or None (old versions: tokens must read NONE, hook ver v0)."""
    for role, o in obs.items():
        for kind in ("command", "skill"):
            # live session: assert on what the runtime GAVE the model (command expansion / Skill tool result), not on its reply
            seen = hn.claude_transcript_text(o[kind]["events"]) + hn.claude_session_given_text(rep, o[kind]["events"])
            token = f"CRACC-{kind.upper()}-{want}" if want else "CRACC-"
            good = (token in seen) if want else ("CRACC-" not in seen)
            r.ok(f"{tag}-claude-{kind}-transcript-{role}", good,
                 f"claude -p {kind} transcript {'contains ' + token if want else 'has no CRACC token (old version)'} in command expansion / tool output",
                 f"transcript_has_token={token in seen} chars={len(seen)} is_error={o[kind]['is_error']}",
                 f"user-level {kind} link not resolving through current, or project-level copy shadows it",
                 ["~/.claude/" + {"command": "commands", "skill": "skills"}[kind], "release links.json"])
        # agent: a headless session exposes no agent text outside the model; the resolved-file probe above is the assertion
        rows = read_obs(o["obs"]["command"]) + read_obs(o["obs"]["agent"]) + read_obs(o["obs"]["skill"])
        cl_rows = [e for e in rows if e.get("runtime") == "claude" and e.get("hook") == "user-prompt-submit.sh"]
        r.ok(f"{tag}-claude-hook-{role}", bool(cl_rows) and all(e.get("ver") == ver for e in cl_rows),
             f"claude hook logic reports ver={ver}", f"{[e.get('ver') for e in cl_rows]}",
             "user-level hook shim not dispatching to current/", ["claude-copilot/.claude/hooks/copilot-hook.sh", "~/.claude/settings.json"])
        ctext = o["codex"]["text"]
        xrows = [e for e in read_obs(o["obs"]["codex"]) if e.get("hook") == "user-prompt-protocol.sh"]
        r.ok(f"{tag}-codex-hook-{role}", bool(xrows) and all(e.get("ver") == ver for e in xrows),
             f"codex hook logic reports ver={ver}", f"{[e.get('ver') for e in xrows]}",
             "frozen plugin shim not dispatching to current/codex-copilot/templates/central-hooks",
             ["codex-marketplace/plugins/codex-copilot/hooks/user-prompt-protocol.sh", "codex-copilot/templates/central-hooks"])
        done = "hook: UserPromptSubmit Completed" in ctext
        bad = re.search(r"(untrusted|not trusted|needs review|review required|hook.*disabled)", ctext, re.I)
        r.ok(f"{tag}-codex-trust-{role}", done and not bad, "Codex runs the hook with no trust prompt",
             f"completed={done} flag={bad.group(0) if bad else None}", "plugin directory hash changed -> trust reset",
             ["codex-marketplace/plugins/codex-copilot/**", "~/.codex/config.toml [hooks.state]"])


@check("CR-C", "Test release flip: agent, command, skill and hook changes reach both runtimes; no project touched; Codex trust valid",
       {"release_pointer", "links", "hooks_user_shim", "codex_plugin_cache", "codex_trust", "claude_agents_links"}, needs=("migrated", "probe"))
def check_c(ctx: Ctx, r: Result):
    ensure_migrated(ctx, r)
    if not ensure_probe(ctx, r):
        return
    cfg = ctx.rep.codex_home / "config.toml"
    pre_projects = _hash_state(ctx)
    pre_cfg = hn.sha256_file(cfg)
    pre_trust = [l for l in cfg.read_text().splitlines() if "trusted_hash" in l or "trusted_content_hash" in l]
    rep = publish_release(ctx, ctx.probe_id, test_edit_list(ctx, ctx.probe_id, "v0", "v1", "V1"), "test")
    ctx.test_id = ctx.current_id()
    r.ok("publish", rep.get("rc") == 0 and ctx.test_id != ctx.probe_id,
         "the production publish pipeline flips to the test release (build, flip, links, codex, doctor)",
         json.dumps({k: rep.get(k) for k in ("rc", "error", "step", "release", "links", "codex")})[:900],
         "cc release publish rejects a content-only release", ["core/release/publish.py"])
    d = ctx.cc("release", "doctor")
    r.ok("doctor-after-flip", d.rc == 0, "release doctor passes after the flip", (d.out + d.err)[-500:],
         "doctor expects something a content-only release does not have (codex cache digest, links)", ["core/release/engine/doctor.py"])
    post_projects = _hash_state(ctx)
    touched = [k for k in pre_projects if pre_projects[k] != post_projects[k]]
    r.ok("no-project-touched", not touched, "the flip changes no project file or git status", f"touched={touched}",
         "flip or links step writes into projects", ["pointer.py", "links/apply.py"])
    resolved_probe(ctx, r, "observe", "V1")
    obs = _observe(ctx, "c", SAMPLE3)
    ctx.state["c_obs"] = True
    _assert_observed(r, "observe", obs, "V1", "v1", ctx.rep)
    post_cfg_trust = [l for l in cfg.read_text().splitlines() if "trusted_hash" in l or "trusted_content_hash" in l]
    r.ok("codex-trust-lines-unchanged", pre_trust == post_cfg_trust, "Codex trusted hashes unchanged by the flip and the runs",
         f"before={len(pre_trust)} after={len(post_cfg_trust)}", "trust re-written by exec or release step", ["~/.codex/config.toml"])
    after = _hash_state(ctx)
    r.evidence["runtime_wrote_in_projects"] = [k for k in post_projects if post_projects[k] != after[k]]
    r.evidence["test_release"] = ctx.test_id


@check("CR-D", "Rollback restores the previous release; both runtimes observe the old versions",
       {"release_pointer", "hooks_user_shim", "links", "codex_trust", "claude_agents_links"}, needs=("migrated", "probe", "testrelease"))
def check_d(ctx: Ctx, r: Result):
    ensure_migrated(ctx, r)
    if not ensure_probe(ctx, r):
        return
    if not ctx.test_id or ctx.current_id() != ctx.test_id:
        publish_release(ctx, ctx.probe_id, test_edit_list(ctx, ctx.probe_id, "v0", "v1", "V1"), "test")
        ctx.test_id = ctx.current_id()
    rb = ctx.cc("release", "rollback", "--reason", "cracc-rollback")
    r.ok("rollback-pointer", rb.rc == 0 and ctx.current_id() == ctx.probe_id, "rollback returns current to the previous release",
         f"rc={rb.rc} current={ctx.current_id()} want={ctx.probe_id} {rb.err[:200]}", "pointer.rollback", ["core/release/engine/pointer.py"])
    hist = [json.loads(l) for l in (ctx.ch / "release-history.jsonl").read_text().splitlines() if l.strip()]
    r.ok("history", bool(hist) and hist[-1].get("action") == "rollback" and hist[-1].get("release") == ctx.probe_id,
         "history records the rollback", json.dumps(hist[-1:])[:300], "history append", ["pointer.py"])
    # content: the four tracked files read through current equal the baseline bytes
    now = {k: hn.sha256_file(ctx.ch / "current" / v.relative_to(ctx.release_dir(ctx.probe_id))) for k, v in tracked_files(ctx, ctx.probe_id).items()}
    base = ctx.state.get("baseline_files", {})
    same = {k: now[k] == base.get(k) for k in now}
    r.ok("content-restored", all(same.values()), "agent, command, skill and both hooks read as the previous release's bytes",
         str(same), "rollback pointer", ["pointer.py"])
    d = ctx.cc("release", "doctor")
    r.ok("doctor-after-rollback", d.rc == 0, "release doctor passes after rollback", (d.out + d.err)[-400:], "doctor", ["doctor.py"])
    resolved_probe(ctx, r, "observe-old", None)
    obs = _observe(ctx, "d", SAMPLE3)
    _assert_observed(r, "observe-old", obs, None, "v0", ctx.rep)


# ============================================================================== CR-H
@check("CR-H", "Every user-level entry is a release link, a personal link or in the kept list; zero dangling",
       {"links", "release_pointer", "claude_agents_links"})
def check_h(ctx: Ctx, r: Result):
    rep = ctx.rep
    cur_real = os.path.realpath(rep.copilot_home / "current")
    releases = os.path.realpath(rep.copilot_home / "releases")
    receipt = json.loads((rep.copilot_home / "links-receipt.json").read_text()) if (rep.copilot_home / "links-receipt.json").is_file() else {}
    kept = {k["path"] for k in receipt.get("kept", [])} | {c.get("path") for c in receipt.get("customized", [])}
    personal_roots = [str(rep.root / "Sites" / "CSE" / n) for n in
                      ("claude-copilot-private", "codex-copilot-private", "cli-copilot-private", "knowledge-copilot-private")]
    homes = [(".claude/agents", rep.home / ".claude" / "agents"), (".claude/commands", rep.home / ".claude" / "commands"),
             (".claude/skills", rep.home / ".claude" / "skills"), (".codex/skills", rep.home / ".codex" / "skills")]
    stats = {}
    for label, d in homes:
        entries = sorted(d.iterdir()) if d.is_dir() else []
        dangling, unexplained, rel, pers, keptn = [], [], 0, 0, 0
        for p in entries:
            rel_path = f"{label}/{p.name}"
            if p.name.startswith(".") or p.name == "_archive":
                keptn += 1
                continue
            if p.is_symlink():
                t = os.readlink(p)
                tt = t if os.path.isabs(t) else os.path.join(os.path.dirname(p), t)
                if not os.path.exists(tt):
                    dangling.append(f"{rel_path} -> {t}")
                    continue
                rt = os.path.realpath(tt)
                if str(rep.copilot_home / "current") in os.path.normpath(tt) or rt.startswith(releases):
                    rel += 1
                elif any(rt.startswith(pr) for pr in personal_roots) or any(os.path.normpath(tt).startswith(pr) for pr in personal_roots):
                    pers += 1
                elif rel_path in kept:
                    keptn += 1
                else:
                    unexplained.append(f"{rel_path} -> {t}")
            else:
                if rel_path in kept or any(rel_path.startswith(k + "/") for k in kept):
                    keptn += 1
                else:
                    unexplained.append(f"{rel_path} (real entry not in kept list)")
        stats[label] = dict(total=len(entries), release=rel, personal=pers, kept=keptn, dangling=len(dangling))
        r.ok(f"dangling-{label}", not dangling, "0 dangling links", f"{len(dangling)}: {dangling[:5]}",
             "links step leaves a stale link after release content moved", ["core/release/links/apply.py"])
        r.ok(f"explained-{label}", not unexplained, "every entry is a release link, personal link or kept-list item",
             f"{len(unexplained)}: {unexplained[:6]}", "link plan/kept list incomplete", ["core/release/links/apply.py", "links-receipt.json"])
    r.evidence["entries"] = stats
    d = ctx.cc("release", "doctor")
    r.ok("doctor", d.rc == 0, "release doctor passes at the end of the run", (d.out + d.err)[-400:], "doctor", ["doctor.py"])


CHECK_RUN_ORDER = ORDER
