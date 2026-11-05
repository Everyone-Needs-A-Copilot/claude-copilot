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

REV_RE = re.compile(r"^[A-Za-z0-9._/@^~:-]+$")
POS_INT = re.compile(r"^[0-9]+$")

def is_rev(a):
    return not a.startswith("-") and bool(REV_RE.match(a))

# Allowlist (shared semantics with the Codex guard): every git argument, after per-token quote
# removal, must be an explicitly listed form; anything unlisted is denied.
def git_args_ok(sub, args):
    if sub == "status":
        return all(a in ("-s", "--short", "-b", "--branch", "--porcelain", "--porcelain=v1", "--porcelain=v2") for a in args)
    if sub == "log":
        dashdash = False
        i = 0
        while i < len(args):
            a = args[i]; i += 1
            if dashdash:
                continue
            if a == "--":
                dashdash = True
            elif a in ("--oneline", "--graph", "--decorate", "--all", "--stat", "--name-only", "--name-status",
                       "--first-parent", "--no-merges"):
                pass
            elif a == "-n":
                if i >= len(args) or not POS_INT.match(args[i]):
                    return False
                i += 1
            elif re.match(r"^-[0-9]", a):
                if not re.match(r"^-[0-9]+$", a):
                    return False
            elif a.startswith("--max-count="):
                if not POS_INT.match(a.split("=", 1)[1]):
                    return False
            elif a.startswith(("--format=", "--pretty=", "--since=", "--until=", "--author=")):
                pass
            elif a.startswith("-"):
                return False
            elif ".." in a:
                if not REV_RE.match(a):
                    return False
            elif not is_rev(a):
                return False
        return True
    if sub == "branch":
        listing = "--list" in args
        for a in args:
            if a in ("-a", "-r", "-v", "-vv", "--list", "--show-current"):
                continue
            if a.startswith("-") or not listing:
                return False
        return True
    if sub == "worktree":
        if args[:1] != ["list"] or len(args) > 2:
            return False
        return len(args) < 2 or args[1] == "--porcelain"
    if sub == "rev-parse":
        for a in args:
            if a in ("--abbrev-ref", "--short", "--show-toplevel", "--git-dir", "--is-inside-work-tree") or re.match(r"^--short=[0-9]", a):
                continue
            if not is_rev(a):
                return False
        return True
    return False

CC_OK = {"status", "list", "progress", "skill"}

def segment_ok(argv, raw_unsafe=False):
    if not argv:
        return False
    a0 = argv[0]
    if a0 == "tc":
        return True
    if a0 == "cc":
        return len(argv) > 1 and (argv[1] in CC_OK or argv[1] in ("--help", "--version"))
    # Remaining commands are allowlisted strictly: no backslashes, `$`, or quotes left in any token.
    if raw_unsafe or any("\\" in t or "$" in t or "'" in t or '"' in t for t in argv):
        return False
    if a0 == "pwd":
        return all(x in ("-P", "-L") for x in argv[1:])
    if a0 == "date":
        return all(x == "-u" or x.startswith("+") for x in argv[1:])
    if a0 == "readlink":
        return len(argv) == 2 and not argv[1].startswith("-")
    if a0 == "git":
        rest = argv[1:]
        while len(rest) >= 2 and rest[0] == "-C":
            rest = rest[2:]
        if not rest:
            return False
        return git_args_ok(rest[0], rest[1:])
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
    raw_unsafe = "\\" in cmd or "$" in cmd
    return all(segment_ok(s, raw_unsafe) for s in clean)

sys.exit(main())
PY
)
exec python3 -I -c "$_SRC"
