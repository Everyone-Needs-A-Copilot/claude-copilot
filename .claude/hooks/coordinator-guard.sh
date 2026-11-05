#!/usr/bin/env bash
# coordinator-guard.sh — user-level PreToolUse hook: the main session is a coordinator.
#
# Rule (2026-11-05): the main session never reads project content, edits files or runs
# work commands itself; it dispatches agents. Canonical text: the `parallel-execution`
# skill (cc skill get parallel-execution --scope machine) and .claude/commands/protocol.md.
#
# Installed copy: ~/.claude/hooks/coordinator-guard.sh, wired in ~/.claude/settings.json
# (PreToolUse, matcher Bash|Read|Grep|Glob|Edit|Write|NotebookEdit|MultiEdit).
#
# Main vs subagent: Claude Code 2.1.x adds `agent_id` (and `agent_type`) to the hook stdin
# JSON only for tool calls made inside a subagent (verified empirically). Main-session
# calls have neither. Only `agent_id` is used here, so a main session started with
# `--agent` is still treated as main. Subagent calls always pass.
#
# Emergency off switch: COPILOT_COORDINATOR=off (logged to
# ${COPILOT_COORDINATOR_LOG:-~/.local/state/copilot/coordinator-off.log}).
#
# Layering with pretool-check.sh rule_force_delegate: this guard supersedes the 10-file /
# 200KB budget for the main session. When this guard is installed and not off,
# force-delegate defers (returns allow) so the main session is never double-blocked.
#
# Exit 0 = allow; exit 2 + stderr message = block.
_SRC=$(cat <<'PY'
import json, os, re, shlex, sys, time

def main():
    try:
        d = json.load(sys.stdin)
    except Exception:
        return 0  # malformed payload: never block
    tool = d.get("tool_name", "")
    if tool not in ("Bash", "Read", "Grep", "Glob", "Edit", "Write", "NotebookEdit", "MultiEdit"):
        return 0
    if d.get("agent_id"):
        return 0  # subagent call
    if os.environ.get("COPILOT_COORDINATOR", "") == "off":
        log = os.environ.get("COPILOT_COORDINATOR_LOG") or os.path.expanduser("~/.local/state/copilot/coordinator-off.log")
        try:
            os.makedirs(os.path.dirname(log), exist_ok=True)
            with open(log, "a") as f:
                f.write("%s COPILOT_COORDINATOR=off bypass session=%s tool=%s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S%z"), d.get("session_id", ""), tool))
        except Exception:
            pass
        sys.stderr.write("[coordinator-guard] COPILOT_COORDINATOR=off: coordinator rule bypassed (logged)\n")
        return 0

    ti = d.get("tool_input") or {}
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    cfg = os.path.realpath(cfg)

    def allowed_path(p, plans_ok):
        if not p:
            return False
        p = os.path.realpath(os.path.expanduser(p))
        if re.match(re.escape(cfg) + r"/projects/[^/]+/memory(/|$)", p):
            return True
        if plans_ok and (p == cfg + "/plans" or p.startswith(cfg + "/plans/")):
            return True
        if re.match(r"/private/tmp/claude-[^/]+/.*/scratchpad(/|$)", p):
            return True
        return False

    def block(what):
        sys.stderr.write(
            "BLOCKED by the Coordinator rule (2026-11-05): the main session is a coordinator and never reads project "
            "content, edits files or runs work commands itself (%s). Dispatch an agent with the Agent tool instead "
            "(read-only work needs no approval wait; split by question, source or owned files). Allowed here: tc, "
            "cc status/list/progress/skill, git status/log/branch/worktree list/rev-parse, pwd/date/readlink, "
            "memory and scratchpad paths. Rule text: `cc skill get parallel-execution --scope machine`. "
            "Emergency off: COPILOT_COORDINATOR=off.\n" % what)
        return 2

    if tool in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
        p = ti.get("file_path") or ti.get("notebook_path") or ""
        return 0 if allowed_path(p, True) else block("%s %s" % (tool, p or "?"))
    if tool in ("Read", "Grep", "Glob"):
        p = ti.get("file_path") or ti.get("path") or ""
        if tool == "Glob" and not p:
            p = ""
        return 0 if allowed_path(p, True) else block("%s %s" % (tool, p or "(cwd)"))

    cmd = ti.get("command", "")
    return 0 if bash_ok(cmd) else block("Bash: %s" % cmd[:80])

GIT_READ = {"status", "log", "rev-parse"}
# Options that can write files, run programs, redirect the repo, or dump project content.
# Long options match by unique-prefix in git, so any prefix of these is rejected too.
GIT_DANGER_LONG = ("output", "ext-diff", "textconv", "exec-path", "git-dir", "work-tree", "patch",
                   "open-files-in-pager", "show-signature", "no-index", "diff-merges", "cc",
                   "config-env", "super-prefix", "namespace", "paginate", "pager", "exec")
GIT_DANGER_SHORT = set("pucCO")
WORKTREE_OK = {"--porcelain", "-v", "--verbose", "-z"}

def git_args_safe(args):
    for x in args:
        if x == "--":
            return True  # the rest are pathspecs
        if x.startswith("--"):
            name = x[2:].split("=", 1)[0]
            if not name or any(d.startswith(name) or name.startswith(d) for d in GIT_DANGER_LONG):
                return False
        elif x.startswith("-") and len(x) > 1:
            if GIT_DANGER_SHORT & set(x[1:]):
                return False
    return True

CC_OK = {"status", "list", "progress", "skill"}

def segment_ok(argv):
    if not argv:
        return False
    a0 = argv[0]
    if a0 in ("pwd", "date", "readlink"):
        return True
    if a0 == "tc":
        return True
    if a0 == "cc":
        return len(argv) > 1 and (argv[1] in CC_OK or argv[1] in ("--help", "--version"))
    if a0 == "git":
        rest = argv[1:]
        while len(rest) >= 2 and rest[0] == "-C":
            rest = rest[2:]
        if not rest:
            return False
        sub, args = rest[0], rest[1:]
        if sub in GIT_READ:
            return git_args_safe(args)
        if sub == "branch":
            return all(x in ("--list", "-l", "-a", "-r", "-v", "-vv", "--show-current", "--all", "--remotes") for x in args)
        if sub == "worktree":
            return args[:1] == ["list"] and all(x in WORKTREE_OK for x in args[1:])
    return False

def bash_ok(cmd):
    if not cmd.strip() or "\n" in cmd or "`" in cmd or "$(" in cmd or "<(" in cmd or ">(" in cmd:
        return False
    # redirections: only 2>&1 and >/dev/null variants are tolerated
    scrub = re.sub(r"\d?>>?\s*/dev/null|2>&1|&>\s*/dev/null", "", cmd)
    if re.search(r"[<>]", scrub):
        return False
    try:
        lex = shlex.shlex(scrub, posix=True, punctuation_chars=";&|")
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        return False
    segs, cur = [], []
    for t in toks:
        if t and set(t) <= set(";&|"):
            segs.append(cur); cur = []
        else:
            cur.append(t)
    segs.append(cur)
    segs = [s for s in segs if s] if len(segs) > 1 else segs
    # strip trailing 2>&1 / /dev/null leftovers already scrubbed from check, but tokens remain
    clean = []
    for s in segs:
        s = [t for t in s if not re.fullmatch(r"\d?>>?(/dev/null)?|2>&1|&>|/dev/null", t)]
        clean.append(s)
    return all(segment_ok(s) for s in clean)

sys.exit(main())
PY
)
exec python3 -I -c "$_SRC"
