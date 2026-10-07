#!/usr/bin/env bash
# fitness-check.sh — Claude Copilot Framework Fitness Functions
#
# Validates that a project's agents and commands are healthy after setup or update.
# Runs 11 fitness functions (FF1–FF11) and reports pass/fail per check.
#
# Usage:
#   bash .claude/fitness-check.sh [--agents-dir DIR] [--commands-dir DIR] [--copilot-path PATH]
#
# Arguments:
#   --agents-dir DIR      Path to agents directory (default: .claude/agents)
#   --commands-dir DIR    Path to commands directory (default: .claude/commands)
#   --copilot-path PATH   Path to copilot source (overrides CC_COPILOT_PATH env var and
#                         project-relative resolution; default: ~/.claude/copilot)
#
# Environment:
#   CC_COPILOT_PATH       Explicit override for copilot source path (lower priority than
#                         --copilot-path flag, higher than project-relative resolution)
#
# Exit codes:
#   0 = all checks passed
#   1 = one or more checks failed

set -uo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
AGENTS_DIR=".claude/agents"
COMMANDS_DIR=".claude/commands"
COPILOT_PATH_FLAG=""   # set only when --copilot-path is passed explicitly

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --agents-dir)   AGENTS_DIR="$2";        shift 2 ;;
    --commands-dir) COMMANDS_DIR="$2";      shift 2 ;;
    --copilot-path) COPILOT_PATH_FLAG="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
PASS_COUNT=0
FAIL_COUNT=0
FAILURES=()

pass() { echo "  [PASS] $1"; PASS_COUNT=$((PASS_COUNT + 1)); }
fail() { echo "  [FAIL] $1"; FAIL_COUNT=$((FAIL_COUNT + 1)); FAILURES+=("$1"); }
section() { echo; echo "=== $1 ==="; }

# ---------------------------------------------------------------------------
# Resolve VERSION.json — hermetic precedence:
#   1. --copilot-path flag (explicit CLI override)
#   2. CC_COPILOT_PATH env var (explicit env override)
#   3. Project's own VERSION.json (repo root, resolved relative to this script)
#   4. Machine install ~/.claude/copilot/VERSION.json
#   5. Hardcoded fallback (emits WARNING — stale-prone)
# ---------------------------------------------------------------------------
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
_PROJECT_VERSION="${_SCRIPT_DIR}/VERSION.json"
_MACHINE_VERSION="${HOME}/.claude/copilot/VERSION.json"

if [ -n "$COPILOT_PATH_FLAG" ]; then
  VERSION_FILE="${COPILOT_PATH_FLAG}/VERSION.json"
  VERSION_SOURCE="--copilot-path flag"
elif [ -n "${CC_COPILOT_PATH:-}" ]; then
  VERSION_FILE="${CC_COPILOT_PATH}/VERSION.json"
  VERSION_SOURCE="CC_COPILOT_PATH env var"
elif [ -f "$_PROJECT_VERSION" ]; then
  VERSION_FILE="$_PROJECT_VERSION"
  VERSION_SOURCE="project root (${_PROJECT_VERSION})"
elif [ -f "$_MACHINE_VERSION" ]; then
  VERSION_FILE="$_MACHINE_VERSION"
  VERSION_SOURCE="machine install (${_MACHINE_VERSION})"
else
  VERSION_FILE=""
  VERSION_SOURCE=""
fi

# Keep COPILOT_PATH for the restore-guidance footer (best-effort)
COPILOT_PATH="${COPILOT_PATH_FLAG:-${CC_COPILOT_PATH:-${HOME}/.claude/copilot}}"

# ---------------------------------------------------------------------------
# Framework repo vs consumer project. The same script ships into every
# installed project, and several checks below are only meaningful in one of
# the two: the context-budget baseline (FF9) and the agent git history (FF12)
# live in the framework repo, never in a consumer. The framework repo is the
# directory whose VERSION.json declares `framework` and that carries tools/cc;
# an installed project has neither. CC_FITNESS_MODE=framework|consumer
# overrides detection (tests, unusual layouts).
# ---------------------------------------------------------------------------
if [ -n "${CC_FITNESS_MODE:-}" ]; then
  FITNESS_MODE="$CC_FITNESS_MODE"
elif [ -f "${_SCRIPT_DIR}/tools/cc/pyproject.toml" ] && \
     python3 -c "import json,sys; sys.exit(0 if 'framework' in json.load(open(sys.argv[1])) else 1)" \
       "${_SCRIPT_DIR}/VERSION.json" 2>/dev/null; then
  FITNESS_MODE="framework"
else
  FITNESS_MODE="consumer"
fi
case "$FITNESS_MODE" in
  framework|consumer) echo "Fitness mode: $FITNESS_MODE" >&2 ;;
  *) echo "Unknown CC_FITNESS_MODE: $FITNESS_MODE (expected framework|consumer)" >&2; exit 1 ;;
esac

# ---------------------------------------------------------------------------
# Customized-preserve installs. A project that keeps its own agent tree is
# installed in `customized-preserve` ownership mode (copilot.lock.json): the
# framework adds only its commands, hook shim and this script, and the
# framework agents (cco ... uxd, _shared/) are deployed once at user level
# (~/.claude/agents), which Claude Code loads in every project. Requiring those
# files inside the project would demand exactly the copies the preservation
# install is built not to make, so in this mode the framework roster resolves
# against the project first and the user-level deployment second. Project-owned
# agents are the project's: they are not held to the framework's agent contract
# (model key, Runtime Precedence / Output Contract blocks). Every other
# install keeps the strict project-only behaviour.
# ---------------------------------------------------------------------------
PRESERVE_MODE=0
USER_AGENTS_DIR=""
if [ "$FITNESS_MODE" = "consumer" ] && [ -f "${_SCRIPT_DIR}/copilot.lock.json" ] && \
   python3 -c "
import json, sys
lock = json.load(open(sys.argv[1]))
claude = [c for c in lock.get('components', []) if c.get('component') == 'claude']
sys.exit(0 if claude and claude[0].get('ownership_mode') == 'customized-preserve' else 1)
" "${_SCRIPT_DIR}/copilot.lock.json" 2>/dev/null; then
  PRESERVE_MODE=1
  USER_AGENTS_DIR="${CC_USER_AGENTS_DIR:-${CLAUDE_CONFIG_DIR:-${HOME}/.claude}/agents}"
  echo "Install ownership: customized-preserve (framework agents load from ${USER_AGENTS_DIR})" >&2
fi

# agent_path NAME -- the file a session loads for agent NAME.
agent_path() {
  if [ -f "${AGENTS_DIR}/$1.md" ] || [ "$PRESERVE_MODE" -ne 1 ]; then
    echo "${AGENTS_DIR}/$1.md"
  elif [ -f "${USER_AGENTS_DIR}/$1.md" ]; then
    echo "${USER_AGENTS_DIR}/$1.md"
  else
    echo "${AGENTS_DIR}/$1.md"
  fi
}

# shared_path NAME -- the canonical _shared/NAME block source.
shared_path() {
  if [ -f "${AGENTS_DIR}/_shared/$1" ] || [ "$PRESERVE_MODE" -ne 1 ]; then
    echo "${AGENTS_DIR}/_shared/$1"
  elif [ -f "${USER_AGENTS_DIR}/_shared/$1" ]; then
    echo "${USER_AGENTS_DIR}/_shared/$1"
  else
    echo "${AGENTS_DIR}/_shared/$1"
  fi
}

# block_agent_files -- the agent files that must carry the canonical blocks
# (FF8, FF10): every agent in the framework repo or a standard install. A
# customized-preserve project carries none of the framework agents and its own
# agents are the project's, so only a roster agent the project itself carries
# is held to the blocks; the deployed framework agents are the machine's, and
# their drift from the framework is reconciled and reported by FF12.
block_agent_files() {
  if [ "$PRESERVE_MODE" -eq 1 ]; then
    for agent in $ROSTER; do
      [ -f "${AGENTS_DIR}/${agent}.md" ] && ! is_project_agent "$agent" && echo "${AGENTS_DIR}/${agent}.md"
    done
  else
    for f in "${AGENTS_DIR}"/*.md; do
      [ -f "$f" ] && ! is_project_agent "$(basename "$f" .md)" && echo "$f"
    done
  fi
  return 0
}

# ---------------------------------------------------------------------------
# Read roster from VERSION.json
# ---------------------------------------------------------------------------
if [ -n "$VERSION_FILE" ] && [ -f "$VERSION_FILE" ]; then
  ROSTER=$(python3 -c "
import json, sys
with open('$VERSION_FILE') as f:
    v = json.load(f)
agents = v['components']['agents']['frameworkAgents']
print(' '.join(agents))
" 2>/dev/null) || ROSTER=""
  RETIRED=$(python3 -c "
import json, sys
with open('$VERSION_FILE') as f:
    v = json.load(f)
retired = v['components']['agents'].get('retired', [])
print(' '.join(retired))
" 2>/dev/null) || RETIRED=""
  echo "Using manifest: $VERSION_SOURCE" >&2
else
  echo "WARNING: VERSION.json not found via any resolution path — using hardcoded defaults (stale-prone)" >&2
  echo "  Checked: --copilot-path flag, CC_COPILOT_PATH env, ${_PROJECT_VERSION}, ${_MACHINE_VERSION}" >&2
  ROSTER="cco cpa cs cw do doc ind kc me qa sd sec ta uid uids uxd"
  RETIRED="design"
fi

# Project-owned agents. In an installed project, an agent that declares
# `owner: project` (the documented way to keep a project's own agent, even
# under a framework name) or that is not in the framework roster at all is the
# project's own. It is not held to the framework's agent contract: the
# frontmatter schema (FF7), the specialist sections (FF4), and the Runtime
# Precedence / Output Contract blocks (FF8, FF10). Those exist so framework
# agents stay byte-aligned with the framework; a project's tutor or studio agent
# has no framework counterpart to align with. FF11 (dead skill references) still
# applies to every agent, because a dead reference fails at runtime whoever
# owns the file. The framework repo itself has no project agents.
PROJECT_AGENTS=""
if [ "$FITNESS_MODE" = "consumer" ]; then
  # Agents the lock records as framework files (e.g. the setup-only kc, which
  # is not in the build roster) are framework agents whatever their name.
  LOCKED_AGENTS=$(python3 -c "
import json, sys
try:
    lock = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
for c in lock.get('components', []):
    if c.get('component') == 'claude':
        for f in c.get('files', []):
            p = str(f.get('path', ''))
            if p.startswith('.claude/agents/') and p.count('/') == 2 and p.endswith('.md'):
                print(p.rsplit('/', 1)[1][:-3])
" "${_SCRIPT_DIR}/copilot.lock.json" 2>/dev/null | tr '\n' ' ')
  for f in "${AGENTS_DIR}"/*.md; do
    [ -f "$f" ] || continue
    n=$(basename "$f" .md)
    if grep -q '^owner: project' "$f" 2>/dev/null || \
       { [[ " $ROSTER " != *" $n "* ]] && [[ " $LOCKED_AGENTS " != *" $n "* ]]; }; then
      PROJECT_AGENTS="$PROJECT_AGENTS $n"
    fi
  done
fi
is_project_agent() { [[ " $PROJECT_AGENTS " == *" $1 "* ]]; }

# ---------------------------------------------------------------------------
# FF1: No orphan routes — every @agent-X referenced in agents/ and commands/
#      resolves to a real agent file in agents/
# ---------------------------------------------------------------------------
section "FF1: No Orphan Routes"

# Scan agents/ (excluding _archive/) and commands/ for @agent-X references
REFERENCED_AGENTS=$(grep -rh '@agent-[a-z][a-z-]*' \
  --exclude-dir=_archive \
  "${AGENTS_DIR}/" "${COMMANDS_DIR}/" 2>/dev/null \
  | grep -oE '@agent-[a-z][a-z-]*' \
  | sed 's/@agent-//' \
  | sed 's/-$//' \
  | sort -u)

# sec is allowlisted — it routes externally but is a valid agent
# kc is a setup agent, not routed to during normal work
ALLOWLIST="sec kc"

for ref in $REFERENCED_AGENTS; do
  # Skip allowlisted agents
  is_allowed=0
  for allowed in $ALLOWLIST; do
    [ "$ref" = "$allowed" ] && is_allowed=1 && break
  done

  ref_file=$(agent_path "$ref")
  if [ -f "$ref_file" ]; then
    pass "@agent-${ref} resolves to ${ref_file}"
  elif [ $is_allowed -eq 1 ]; then
    pass "@agent-${ref} (allowlisted — external or setup agent)"
  else
    fail "@agent-${ref} referenced but ${AGENTS_DIR}/${ref}.md does not exist"
  fi
done

# ---------------------------------------------------------------------------
# FF2: Roster invocation parity — every agent in the manifest has a .md file
# ---------------------------------------------------------------------------
section "FF2: Roster Parity (all manifest agents present)"

for agent in $ROSTER; do
  if [ -f "$(agent_path "$agent")" ]; then
    pass "${agent}.md present"
  else
    fail "${agent}.md MISSING (in VERSION.json roster but not in ${AGENTS_DIR}/$([ "$PRESERVE_MODE" -eq 1 ] && echo " or ${USER_AGENTS_DIR}/"))"
  fi
done

# ---------------------------------------------------------------------------
# FF3: No retired agents remain — retired agents must not exist in agents/
# ---------------------------------------------------------------------------
section "FF3: No Retired Agents Present"

if [ -z "$RETIRED" ]; then
  pass "No retired agents defined in VERSION.json"
else
  for agent in $RETIRED; do
    if [ -f "${AGENTS_DIR}/${agent}.md" ]; then
      # Exception: a project-owned override (owner: project) is intentionally kept
      if grep -q '^owner: project' "${AGENTS_DIR}/${agent}.md" 2>/dev/null; then
        pass "Retired agent ${agent}.md kept as project-owned override (owner: project)"
      else
        fail "${agent}.md still present but is listed as retired in VERSION.json — remove it"
      fi
    else
      pass "Retired agent ${agent}.md correctly absent"
    fi
  done
fi

# ---------------------------------------------------------------------------
# FF4: Specialist distinctness — each specialist has required sections
# ---------------------------------------------------------------------------
section "FF4: Specialist Distinctness (required sections)"

REQUIRED_SECTIONS=("Core Behaviors" "Route To Other Agent")
SPECIALIST_AGENTS="uxd uids uid ind cco cw sec cs cpa"

for agent in $SPECIALIST_AGENTS; do
  agent_file=$(agent_path "$agent")
  if is_project_agent "$agent"; then
    pass "${agent}.md is project-owned (owner: project) -- framework specialist sections not required"
    continue
  fi
  if [ ! -f "$agent_file" ]; then
    fail "${agent}.md missing — skipping section check"
    continue
  fi
  for section_name in "${REQUIRED_SECTIONS[@]}"; do
    if grep -q "## ${section_name}" "$agent_file" 2>/dev/null; then
      pass "${agent}.md has '${section_name}' section"
    else
      fail "${agent}.md missing '${section_name}' section"
    fi
  done
done

# ---------------------------------------------------------------------------
# FF5: No orphan agent routes in agent files (agents only route to known agents)
# ---------------------------------------------------------------------------
section "FF5: No Orphan Agent-to-Agent Routes"

# Include on-disk agent basenames so project-owned custom agents (e.g. critic,
# structural-editor, line-editor) are treated as known without needing to be in
# the framework roster or allowlist.
ON_DISK_AGENTS=$(for f in "${AGENTS_DIR}"/*.md $([ "$PRESERVE_MODE" -eq 1 ] && echo "${USER_AGENTS_DIR}"/*.md); do [ -f "$f" ] && basename "$f" .md; done 2>/dev/null | tr '\n' ' ')
KNOWN_AGENTS="$ROSTER $ON_DISK_AGENTS $ALLOWLIST"

for agent_file in "${AGENTS_DIR}"/*.md; do
  agent_name=$(basename "$agent_file" .md)
  # Find all @agent-X references in this file (allow hyphens in agent names)
  refs=$(grep -oE '@agent-[a-z][a-z-]*' "$agent_file" 2>/dev/null | sed 's/@agent-//' | sed 's/-$//' | sort -u)
  for ref in $refs; do
    # Check if ref is in known agents (roster + allowlist)
    is_known=0
    for known in $KNOWN_AGENTS; do
      [ "$ref" = "$known" ] && is_known=1 && break
    done
    if [ $is_known -eq 1 ]; then
      pass "${agent_name}.md → @agent-${ref} (known)"
    else
      fail "${agent_name}.md → @agent-${ref} (UNKNOWN — not in roster or allowlist)"
    fi
  done
done

# ---------------------------------------------------------------------------
# FF6: No stale design agent refs in CLAUDE.md
#      Catches @agent-design and routing-stage usage of bare "design" (e.g.
#      "sd → design →" or "design →") while ignoring legitimate prose such as
#      "Atomic Design", "Design chain", "design tokens", "service design", etc.
# ---------------------------------------------------------------------------
section "FF6: No Stale Design Agent Refs in CLAUDE.md"

CLAUDE_MD="CLAUDE.md"
if [ ! -f "$CLAUDE_MD" ]; then
  pass "CLAUDE.md not found at repo root — skipping"
else
  # Check for @agent-design literal reference
  if grep -q '@agent-design' "$CLAUDE_MD" 2>/dev/null; then
    fail "CLAUDE.md contains '@agent-design' — retired agent reference must be removed"
  else
    pass "CLAUDE.md: no @agent-design reference"
  fi

  # Check for routing-stage pattern: "design" used as a pipeline stage
  # Matches "→ design →", "→ design" at line end, or "design →" at start of routing
  # Does NOT match "Design chain", "Atomic Design", "design tokens", "service design", etc.
  if grep -E '(→\s*design\s*→|→\s*design\s*$|\bdesign\s*→)' "$CLAUDE_MD" 2>/dev/null | grep -qv 'Design chain\|Atomic Design\|design tokens\|service design\|visual design\|design chain'; then
    fail "CLAUDE.md contains 'design' used as a routing stage — replace with specialist agent(s)"
  else
    pass "CLAUDE.md: no 'design' routing-stage references"
  fi
fi

# ---------------------------------------------------------------------------
# FF7: Agent frontmatter conformance — every agent .md's YAML frontmatter has
#      only recognized top-level keys (catches keys hoisted out of a nested
#      block, e.g. `validationRules:` sitting as a sibling of `iteration:`
#      instead of nested under it), a valid `model`, and — for every
#      role=framework agent (the ROSTER from VERSION.json) — a well-formed
#      `iteration:` contract: enabled/maxIterations/completionPromises/
#      validationRules, matching manifest.schema.json's
#      definitions.AgentDescriptor.properties.iteration subschema so the two
#      representations cannot drift apart. role=setup-only agents (e.g. kc,
#      not in ROSTER) are exempt from requiring the block, but if present it
#      is still validated.
# ---------------------------------------------------------------------------
section "FF7: Agent Frontmatter Conformance (iteration contract)"

while IFS= read -r ff7_line; do
  [ -z "$ff7_line" ] && continue
  case "$ff7_line" in
    "PASS "*) pass "${ff7_line#PASS }" ;;
    "FAIL "*) fail "${ff7_line#FAIL }" ;;
    *) fail "FF7 checker produced unparseable output: $ff7_line" ;;
  esac
done < <(python3 - "$AGENTS_DIR" "$ROSTER" "$PRESERVE_MODE" "$USER_AGENTS_DIR" "$PROJECT_AGENTS" <<'PYEOF'
import re
import sys
from pathlib import Path

agents_dir = Path(sys.argv[1])
roster = set(sys.argv[2].split()) if len(sys.argv) > 2 else set()
preserve = len(sys.argv) > 3 and sys.argv[3] == "1"
user_dir = Path(sys.argv[4]) if preserve and len(sys.argv) > 4 and sys.argv[4] else None
project_agents = set(sys.argv[5].split()) if len(sys.argv) > 5 else set()

KNOWN_TOP = {"name", "description", "tools", "model", "iteration"}
REQUIRED_TOP = ("name", "description", "tools", "model")
KNOWN_ITER = {"enabled", "maxIterations", "completionPromises", "validationRules"}
PROMISE_RE = re.compile(r"^<promise>[A-Z]+</promise>$")
RULE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")


def fail(msg):
    print(f"FAIL {msg}")


def ok(msg):
    print(f"PASS {msg}")


def collect_list_items(lines, key, key_line):
    if key not in key_line:
        return None
    start = key_line[key]
    inline = lines[start].split(":", 1)[1].strip()
    if inline.startswith("[") and inline.endswith("]"):
        body = inline[1:-1].strip()
        if not body:
            return []
        return [x.strip().strip('"').strip("'") for x in body.split(",")]
    items = []
    j = start + 1
    while j < len(lines):
        line = lines[j]
        if line.strip() == "":
            j += 1
            continue
        if not line.strip().startswith("-"):
            break
        items.append(line.strip()[1:].strip().strip('"').strip("'"))
        j += 1
    return items


if not agents_dir.is_dir():
    fail(f"agents directory not found: {agents_dir}")
    sys.exit(0)

agent_files = {md.name: md for md in agents_dir.glob("*.md")}
if user_dir is not None and user_dir.is_dir():
    # A customized-preserve install loads the framework roster from the
    # user-level deployment; a project file of the same name shadows it.
    for md in user_dir.glob("*.md"):
        if md.stem in roster:
            agent_files.setdefault(md.name, md)

for _, md in sorted(agent_files.items()):
    name = md.stem
    if name in project_agents and md.parent == agents_dir:
        # The project's own agent: no framework schema or iteration contract,
        # but a `model` it declares must still be one Claude Code accepts.
        own = md.read_text(encoding="utf-8")
        own_end = own.find("\n---", 3) if own.startswith("---") else -1
        own_model = None
        for line in (own[3:own_end].splitlines() if own_end != -1 else []):
            if line.startswith("model:"):
                own_model = line.split(":", 1)[1].strip()
        if own_model is not None and own_model not in ("sonnet", "opus"):
            fail(f"{md.name}: model '{own_model}' not one of sonnet|opus")
        else:
            ok(f"{md.name}: project-owned agent -- framework frontmatter contract not applied")
        continue
    text = md.read_text(encoding="utf-8")

    if not text.startswith("---"):
        fail(f"{md.name}: no frontmatter block (must start with '---')")
        continue
    end = text.find("\n---", 3)
    if end == -1:
        fail(f"{md.name}: frontmatter block never closes with '---'")
        continue
    fm_lines = text[3:end].splitlines()

    top_keys = []
    key_line = {}
    iter_block_lines = []
    current_top = None
    for i, line in enumerate(fm_lines):
        if line.strip() == "":
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            m = KEY_RE.match(line)
            if not m:
                continue
            key = m.group(1)
            top_keys.append(key)
            key_line[key] = i
            current_top = key
            if key == "iteration":
                iter_block_lines = []
        else:
            if current_top == "iteration":
                iter_block_lines.append(line)

    unexpected = [k for k in top_keys if k not in KNOWN_TOP]
    for k in unexpected:
        fail(
            f"{md.name}: unexpected top-level frontmatter key '{k}' "
            f"(check indentation -- likely belongs nested under 'iteration:')"
        )
    # A customized-preserve project's own agents are not held to the framework
    # roster's `model` requirement (Claude Code treats it as optional); a
    # `model` they do declare is still validated below.
    required_top = [
        k for k in REQUIRED_TOP
        if not (preserve and k == "model" and name not in roster)
    ]
    missing_required = [k for k in required_top if k not in top_keys]
    for k in missing_required:
        fail(f"{md.name}: missing required frontmatter key '{k}'")
    if not unexpected and not missing_required:
        ok(f"{md.name}: frontmatter top-level keys well-formed")

    if "model" in key_line:
        mval = fm_lines[key_line["model"]].split(":", 1)[1].strip()
        if mval not in ("sonnet", "opus"):
            fail(f"{md.name}: model '{mval}' not one of sonnet|opus")
        else:
            ok(f"{md.name}: model '{mval}' valid")

    is_framework = name in roster
    if "iteration" not in top_keys:
        if is_framework:
            fail(f"{md.name}: missing required 'iteration:' block (role: framework)")
        else:
            ok(f"{md.name}: no iteration block (exempt -- not in frameworkAgents roster)")
        continue

    sub_keys = []
    sub_key_line = {}
    for j, line in enumerate(iter_block_lines):
        if line.strip() == "":
            continue
        indent = len(line) - len(line.lstrip(" "))
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if m and indent <= 2:
            sub_keys.append(m.group(1))
            sub_key_line[m.group(1)] = j

    unexpected_sub = [k for k in sub_keys if k not in KNOWN_ITER]
    for k in unexpected_sub:
        fail(f"{md.name}: unexpected key '{k}' inside iteration block")
    missing_sub = [k for k in KNOWN_ITER if k not in sub_keys]
    for k in missing_sub:
        fail(f"{md.name}: iteration block missing required key '{k}'")
    if not unexpected_sub and not missing_sub:
        ok(f"{md.name}: iteration block keys well-formed")

    if "enabled" in sub_key_line:
        val = iter_block_lines[sub_key_line["enabled"]].split(":", 1)[1].strip()
        if val not in ("true", "false"):
            fail(f"{md.name}: iteration.enabled '{val}' is not true|false")
        else:
            ok(f"{md.name}: iteration.enabled valid")

    if "maxIterations" in sub_key_line:
        val = iter_block_lines[sub_key_line["maxIterations"]].split(":", 1)[1].strip()
        try:
            n = int(val)
            if not (1 <= n <= 20):
                fail(f"{md.name}: iteration.maxIterations {n} out of range 1-20")
            else:
                ok(f"{md.name}: iteration.maxIterations {n} valid")
        except ValueError:
            fail(f"{md.name}: iteration.maxIterations '{val}' is not an integer")

    promises = collect_list_items(iter_block_lines, "completionPromises", sub_key_line)
    if promises is not None:
        if len(promises) < 1:
            fail(f"{md.name}: completionPromises must have at least 1 entry")
        else:
            bad = [p for p in promises if not PROMISE_RE.match(p)]
            if bad:
                fail(f"{md.name}: completionPromises has malformed entries: {bad}")
            else:
                ok(f"{md.name}: completionPromises well-formed ({len(promises)})")

    rules = collect_list_items(iter_block_lines, "validationRules", sub_key_line)
    if rules is not None:
        if len(rules) < 1:
            fail(f"{md.name}: validationRules must have at least 1 entry")
        else:
            bad = [r for r in rules if not RULE_RE.match(r)]
            if bad:
                fail(f"{md.name}: validationRules has malformed entries: {bad}")
            else:
                ok(f"{md.name}: validationRules well-formed ({len(rules)})")
PYEOF
)

# ---------------------------------------------------------------------------
# FF8: Runtime Precedence block — present exactly once, byte-identical to the
#      canonical `_shared/precedence.md`, and anchored immediately before
#      `## Output Format` in every agent file. Free, deterministic, always-on;
#      the anti-drift mechanism for the block until agent generation lands.
# ---------------------------------------------------------------------------
section "FF8: Runtime Precedence Block (present, unique, byte-identical, anchored)"
if [ "$PRESERVE_MODE" -eq 1 ]; then
  echo "  [REPORT] customized-preserve install: only framework agents carried by the project are checked here; deployed framework agents are reconciled by FF12"
fi

PRECEDENCE_SRC=$(shared_path precedence.md)
if [ ! -f "$PRECEDENCE_SRC" ]; then
  fail "canonical precedence block missing at ${PRECEDENCE_SRC}"
else
  PRECEDENCE_CONTENT=$(cat "$PRECEDENCE_SRC")
  while IFS= read -r agent_file; do
    [ -f "$agent_file" ] || continue
    agent_name=$(basename "$agent_file" .md)

    occ=$(grep -c '^## Runtime Precedence$' "$agent_file" 2>/dev/null || true)
    occ=${occ:-0}
    if [ "$occ" -ne 1 ]; then
      fail "${agent_name}.md: '## Runtime Precedence' heading appears ${occ} time(s) (expected exactly 1)"
      continue
    fi

    block=$(awk '/^## Runtime Precedence$/{flag=1; print; next} /^## /{if (flag) exit} flag' "$agent_file")
    if [ "$block" != "$PRECEDENCE_CONTENT" ]; then
      fail "${agent_name}.md: Runtime Precedence block differs from canonical ${PRECEDENCE_SRC}"
    else
      pass "${agent_name}.md: Runtime Precedence block byte-identical to canonical source"
    fi

    fmt_line=$(grep -n '^## Output Format$' "$agent_file" | head -1 | cut -d: -f1)
    prec_line=$(grep -n '^## Runtime Precedence$' "$agent_file" | head -1 | cut -d: -f1)
    if [ -z "$fmt_line" ]; then
      fail "${agent_name}.md: no '## Output Format' section to anchor Runtime Precedence against"
    else
      between=$(sed -n "$((prec_line + 1)),$((fmt_line - 1))p" "$agent_file" | grep -c '^## ' || true)
      between=${between:-0}
      if [ "$between" -ne 0 ]; then
        fail "${agent_name}.md: another '##' section sits between Runtime Precedence and Output Format"
      else
        pass "${agent_name}.md: Runtime Precedence anchored immediately before Output Format"
      fi
    fi
  done < <(block_agent_files)
fi

# ---------------------------------------------------------------------------
# FF9: Context budget -- converts the anti-context-bloat *rules* in CLAUDE.md
#      and protocol-injection.md into an enforced *budget*, modeled on
#      gstack's skill-size-budget.test.ts (per-skill growth ratio, corpus
#      ceiling, shrink floor, always-loaded ceiling, audited overrides).
#      Four invariants against the committed baseline
#      (.claude/context-budget-baseline-v*.json, highest version wins):
#        1. Per-artifact growth ratio  -- no agent .md or command .md may
#           grow past `growth_ratio` x its baseline in one change.
#        2. Corpus ceiling             -- sum of all agent .md bytes may not
#           exceed `corpus_ceiling_ratio` x the baseline sum.
#        3. Per-artifact shrink floor  -- no tracked artifact may fall below
#           `shrink_floor_ratio` x its baseline (catches an accidental body
#           strip a growth-only budget can't see).
#        4. Always-loaded ceiling      -- CLAUDE.md + the SessionStart hook's
#           injected file + the agent frontmatter description catalog (what
#           Claude Code actually loads into EVERY session, unconditionally)
#           may not exceed `always_loaded_growth_ratio` x its baseline. This
#           is the strictest ratio in the file because it is the one number
#           that taxes every session regardless of what the session does.
#      `.claude/commands/protocol.md` is tracked under invariants 1 and 3
#      (it is the largest single command) but deliberately excluded from
#      invariant 4: it loads on an explicit `/protocol` invocation, not
#      unconditionally at session start. See the baseline file's
#      `excluded_from_always_loaded` block for the full reasoning, including
#      why AGENTS.md (a Codex-layer file, not read by Claude Code) is also
#      excluded.
#
#      Overrides: a failing check is allowed to pass only if
#      .claude/context-budget-overrides.jsonl (committed, reviewable) has an
#      entry whose id is sha256("<artifact>|<kind>|<baseline>|<actual>")[:12]
#      and carries a non-empty `reason`. CC_BUDGET_OVERRIDE="<artifact>:
#      <reason>" appends such an entry locally (for the developer to commit);
#      CI never honors the env var directly, only a committed, exactly-
#      matching entry -- so an unaudited override cannot pass CI.
# ---------------------------------------------------------------------------
section "FF9: Context Budget (bytes + token estimate vs committed baseline)"

if [ "$FITNESS_MODE" = "consumer" ]; then
  # The baseline is a framework-development budget: it pins the byte size of
  # the framework's own corpus so a framework change cannot silently grow
  # what every session loads. A consumer project receives that corpus already
  # budgeted (the framework's own FF9 ran before release) and has no baseline
  # of its own to compare against -- so absence here is expected, not a defect.
  echo "  [SKIP] consumer project -- the context budget is enforced against the framework's committed baseline before release, not per install"
else
FF9_BUDGET_DIR="$(dirname "$AGENTS_DIR")"
FF9_CLAUDE_MD="CLAUDE.md"
FF9_SESSION_INJECTION="${FF9_BUDGET_DIR}/hooks/protocol-injection.md"
FF9_ACTOR="$(git config user.name 2>/dev/null || echo "${USER:-unknown}")"

while IFS= read -r ff9_line; do
  [ -z "$ff9_line" ] && continue
  case "$ff9_line" in
    "PASS "*) pass "${ff9_line#PASS }" ;;
    "FAIL "*) fail "${ff9_line#FAIL }" ;;
    *) fail "FF9 checker produced unparseable output: $ff9_line" ;;
  esac
done < <(python3 - "$AGENTS_DIR" "$COMMANDS_DIR" "$FF9_CLAUDE_MD" "$FF9_SESSION_INJECTION" "$FF9_BUDGET_DIR" "${CC_BUDGET_OVERRIDE:-}" "$FF9_ACTOR" <<'PYEOF'
import hashlib
import json
import re
import sys
import time
from pathlib import Path

agents_dir = Path(sys.argv[1])
commands_dir = Path(sys.argv[2])
claude_md_path = Path(sys.argv[3])
session_injection_path = Path(sys.argv[4])
budget_dir = Path(sys.argv[5])
override_env = sys.argv[6] if len(sys.argv) > 6 else ""
actor = sys.argv[7] if len(sys.argv) > 7 else "unknown"


def fail(msg):
    print(f"FAIL {msg}")


def ok(msg):
    print(f"PASS {msg}")


def info(msg):
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# Resolve the baseline: highest-version context-budget-baseline-v*.json in
# budget_dir. A deliberate re-baseline is a NEW file with a higher version,
# so drift in the numbers this check enforces is itself a reviewable diff.
# ---------------------------------------------------------------------------
def _version_key(p):
    m = re.search(r"-v(\d+)\.(\d+)\.(\d+)\.json$", p.name)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


candidates = sorted(budget_dir.glob("context-budget-baseline-v*.json"), key=_version_key)
if not candidates:
    fail(
        f"no context-budget baseline found under {budget_dir} "
        "(expected context-budget-baseline-v*.json) -- skipping FF9"
    )
    sys.exit(0)
baseline_file = candidates[-1]
info(f"FF9: using baseline {baseline_file}")

try:
    baseline = json.loads(baseline_file.read_text(encoding="utf-8"))
except Exception as exc:
    fail(f"{baseline_file.name} is not valid JSON: {exc}")
    sys.exit(0)

# ---------------------------------------------------------------------------
# Staleness. A baseline older than the artifacts it measures produces a scatter of
# per-file failures that read like content bloat and are nothing of the kind. On
# 2026-08-15 exactly that happened: five files failed (three over growth, two under
# the shrink floor) purely because two feature commits post-dated the baseline. The
# diagnosis cost far more than the fix. Say it once, plainly, up front.
# ---------------------------------------------------------------------------
captured = baseline.get("captured_at")
if captured:
    import subprocess as _sp
    def _last_commit_iso(path):
        try:
            out = _sp.run(["git", "log", "-1", "--format=%cI", "--", path],
                          capture_output=True, text=True, timeout=15)
            return (out.stdout or "").strip()
        except Exception:
            return ""
    _newer = []
    for _p in ("CLAUDE.md", str(agents_dir), str(commands_dir)):
        _iso = _last_commit_iso(_p)
        if _iso and _iso > captured:
            _newer.append((_p, _iso[:10]))
    if _newer:
        info(
            "FF9: baseline captured " + captured[:10] + " but tracked artifacts changed "
            "since: " + ", ".join(f"{a} ({d})" for a, d in _newer) + ". Per-file "
            "results below are measured against a stale reference -- re-baseline to a "
            "new version file before treating any of them as content bloat."
        )

th = baseline["thresholds"]
GROWTH_RATIO = th["growth_ratio"]
SHRINK_FLOOR = th["shrink_floor_ratio"]
CORPUS_RATIO = th["corpus_ceiling_ratio"]
ALWAYS_RATIO = th["always_loaded_growth_ratio"]
# Absolute ceilings. Ratios alone can only ratchet upward; these give the budget a
# direction it can refuse. Absent from older baselines, so default to no ceiling.
ALWAYS_CEILING = th.get("always_loaded_ceiling_bytes")
CORPUS_CEILING = th.get("agent_corpus_ceiling_bytes")
BYTES_PER_TOKEN = baseline["byte_to_token_ratio"]

# ---------------------------------------------------------------------------
# Overrides ledger
# ---------------------------------------------------------------------------
overrides_path = budget_dir / "context-budget-overrides.jsonl"
overrides = []
if overrides_path.exists():
    for i, line in enumerate(overrides_path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            overrides.append(json.loads(line))
        except Exception:
            fail(f"{overrides_path.name}: line {i} is not valid JSON -- corrupt override log")


def fingerprint(artifact, kind, baseline_bytes, actual_bytes):
    raw = f"{artifact}|{kind}|{baseline_bytes}|{actual_bytes}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def record_override(artifact, kind, baseline_bytes, actual_bytes, ratio, reason, actor):
    entry = {
        "id": fingerprint(artifact, kind, baseline_bytes, actual_bytes),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "artifact": artifact,
        "kind": kind,
        "baseline_bytes": baseline_bytes,
        "actual_bytes": actual_bytes,
        "ratio": round(ratio, 4) if ratio != float("inf") else None,
        "reason": reason,
        "actor": actor,
    }
    with overrides_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    overrides.append(entry)
    return entry


def check_override(artifact, kind, baseline_bytes, actual_bytes, ratio):
    """Returns (covered: bool, note: str|None). Only ever consults the
    COMMITTED overrides file for a match -- CC_BUDGET_OVERRIDE can append a
    new entry (for the developer to commit), but never bypasses the check by
    itself in the same run unless that append also produces a matching
    entry, so a bare env var with nothing committed still fails on a clean
    checkout / in CI."""
    fp = fingerprint(artifact, kind, baseline_bytes, actual_bytes)
    for entry in overrides:
        if entry.get("id") == fp and str(entry.get("reason", "")).strip():
            return True, f"{entry['reason']} (recorded {entry.get('ts', '?')} by {entry.get('actor', '?')})"
    if override_env:
        env_artifact, sep, env_reason = override_env.partition(":")
        if sep and env_artifact == artifact:
            env_reason = env_reason.strip()
            if not env_reason:
                return False, None  # refused below with a specific message
            record_override(artifact, kind, baseline_bytes, actual_bytes, ratio, env_reason, actor)
            return True, f"{env_reason} (just recorded to {overrides_path.name} -- commit it for review)"
    return False, None


def override_refused_for_empty_reason(artifact):
    if not override_env:
        return False
    env_artifact, sep, env_reason = override_env.partition(":")
    return bool(sep) and env_artifact == artifact and not env_reason.strip()


# ---------------------------------------------------------------------------
# Byte collection
# ---------------------------------------------------------------------------
def frontmatter_description_bytes(md_path):
    try:
        text = md_path.read_text(encoding="utf-8")
    except Exception:
        return 0
    if not text.startswith("---"):
        return 0
    end = text.find("\n---", 3)
    if end == -1:
        return 0
    for line in text[3:end].splitlines():
        if line.startswith("description:"):
            return len(line.split(":", 1)[1].strip().encode("utf-8"))
    return 0


current_agents = {}
catalog_bytes = 0
if agents_dir.is_dir():
    for md in sorted(agents_dir.glob("*.md")):
        current_agents[md.name] = len(md.read_bytes())
        catalog_bytes += frontmatter_description_bytes(md)

current_commands = {}
if commands_dir.is_dir():
    for md in sorted(commands_dir.glob("*.md")):
        current_commands[md.name] = len(md.read_bytes())

current_claude_md = len(claude_md_path.read_bytes()) if claude_md_path.is_file() else 0
current_session_injection = (
    len(session_injection_path.read_bytes()) if session_injection_path.is_file() else 0
)

# ---------------------------------------------------------------------------
# Per-artifact growth ratio + shrink floor (invariants 1 and 3)
# ---------------------------------------------------------------------------
def evaluate_artifact(key, label, baseline_bytes, actual_bytes):
    if baseline_bytes is None:
        ok(f"{label}: new artifact, not yet in baseline (capture on next re-baseline)")
        return
    tok_actual = actual_bytes / BYTES_PER_TOKEN
    tok_baseline = baseline_bytes / BYTES_PER_TOKEN
    ratio = (actual_bytes / baseline_bytes) if baseline_bytes else (float("inf") if actual_bytes else 1.0)

    if ratio > GROWTH_RATIO:
        kind = "growth"
    elif ratio < SHRINK_FLOOR:
        kind = "shrink"
    else:
        ok(
            f"{label}: {actual_bytes}B (~{tok_actual:.0f} tok), {ratio:.3f}x baseline "
            f"{baseline_bytes}B (~{tok_baseline:.0f} tok) -- within budget"
        )
        return

    if override_refused_for_empty_reason(key):
        fail(f"{label}: CC_BUDGET_OVERRIDE for '{key}' given with no reason text -- override refused")
        return

    covered, note = check_override(key, kind, baseline_bytes, actual_bytes, ratio)
    budget = GROWTH_RATIO if kind == "growth" else SHRINK_FLOOR
    verb = "exceeds growth budget" if kind == "growth" else "is below shrink floor"
    msg = (
        f"{label}: {actual_bytes}B (~{tok_actual:.0f} tok) is {ratio:.3f}x baseline "
        f"{baseline_bytes}B (~{tok_baseline:.0f} tok) -- {verb} {budget}x"
    )
    if covered:
        ok(msg + f" [OVERRIDDEN: {note}]")
    else:
        fail(msg + f" -- override: CC_BUDGET_OVERRIDE='{key}:<reason>' bash .claude/fitness-check.sh")


baseline_agents = baseline.get("agents", {})
for name in sorted(set(current_agents) | set(baseline_agents)):
    evaluate_artifact(
        f"agents/{name}",
        f"{agents_dir}/{name}",
        baseline_agents.get(name),
        current_agents.get(name, 0),
    )

baseline_commands = baseline.get("commands", {})
for name in sorted(set(current_commands) | set(baseline_commands)):
    evaluate_artifact(
        f"commands/{name}",
        f"{commands_dir}/{name}",
        baseline_commands.get(name),
        current_commands.get(name, 0),
    )

always = baseline.get("always_loaded", {})
evaluate_artifact("CLAUDE.md", str(claude_md_path), always.get("claude_md_bytes"), current_claude_md)
evaluate_artifact(
    ".claude/hooks/protocol-injection.md",
    str(session_injection_path),
    always.get("session_start_injection_bytes"),
    current_session_injection,
)
evaluate_artifact(
    "__frontmatter_catalog__",
    "agent frontmatter description catalog (sum across all agent .md files)",
    always.get("frontmatter_catalog_bytes"),
    catalog_bytes,
)

# ---------------------------------------------------------------------------
# Corpus ceiling (invariant 2) and always-loaded ceiling (invariant 4)
# ---------------------------------------------------------------------------
def evaluate_ceiling(key, label, baseline_bytes, actual_bytes, ratio_budget):
    ceiling = baseline_bytes * ratio_budget
    tok_actual = actual_bytes / BYTES_PER_TOKEN
    tok_ceiling = ceiling / BYTES_PER_TOKEN
    tok_baseline = baseline_bytes / BYTES_PER_TOKEN
    if actual_bytes <= ceiling:
        ok(
            f"{label}: {actual_bytes}B (~{tok_actual:.0f} tok) within ceiling "
            f"{ceiling:.0f}B (~{tok_ceiling:.0f} tok) = baseline {baseline_bytes}B "
            f"(~{tok_baseline:.0f} tok) x {ratio_budget}"
        )
        return
    if override_refused_for_empty_reason(key):
        fail(f"{label}: CC_BUDGET_OVERRIDE for '{key}' given with no reason text -- override refused")
        return
    ratio = actual_bytes / baseline_bytes if baseline_bytes else float("inf")
    covered, note = check_override(key, "ceiling", baseline_bytes, actual_bytes, ratio)
    msg = (
        f"{label}: {actual_bytes}B (~{tok_actual:.0f} tok) EXCEEDS ceiling "
        f"{ceiling:.0f}B (~{tok_ceiling:.0f} tok) = baseline {baseline_bytes}B x {ratio_budget}"
    )
    if covered:
        ok(msg + f" [OVERRIDDEN: {note}]")
    else:
        fail(msg + f" -- override: CC_BUDGET_OVERRIDE='{key}:<reason>' bash .claude/fitness-check.sh")


corpus_total = sum(current_agents.values())
evaluate_ceiling(
    "__corpus__",
    "Agent corpus total",
    baseline.get("agent_corpus_total_bytes", 0),
    corpus_total,
    CORPUS_RATIO,
)

always_loaded_total = current_claude_md + current_session_injection + catalog_bytes
evaluate_ceiling(
    "__always_loaded__",
    "Always-loaded total (CLAUDE.md + SessionStart injection + frontmatter catalog)",
    always.get("total_bytes", 0),
    always_loaded_total,
    ALWAYS_RATIO,
)


def evaluate_absolute(label, actual_bytes, ceiling_bytes):
    """Enforce a hard byte ceiling.

    The ratio checks above answer "did this edit grow too fast". This answers "is it
    too big", which no ratio can. Benchmarking on 2026-08-15 measured a real cost for
    always-loaded context that FF9 could not see, because a compliant 8% step is
    compliant however many times it is taken.
    """
    if not ceiling_bytes:
        return
    tokens = actual_bytes / BYTES_PER_TOKEN
    limit_tokens = ceiling_bytes / BYTES_PER_TOKEN
    if actual_bytes > ceiling_bytes:
        over = actual_bytes - ceiling_bytes
        fail(
            f"{label} is {actual_bytes:,} B (~{tokens:,.0f} tok), over the absolute "
            f"ceiling of {ceiling_bytes:,} B (~{limit_tokens:,.0f} tok) by {over:,} B. "
            "Reduce it, or raise the ceiling deliberately in the baseline with a reason."
        )
    else:
        head = ceiling_bytes - actual_bytes
        ok(
            f"{label} {actual_bytes:,} B (~{tokens:,.0f} tok) within absolute ceiling "
            f"{ceiling_bytes:,} B ({head:,} B headroom)"
        )


evaluate_absolute("Always-loaded total", always_loaded_total, ALWAYS_CEILING)
evaluate_absolute("Agent corpus total", corpus_total, CORPUS_CEILING)
PYEOF
)
fi

# ---------------------------------------------------------------------------
# FF10: Output Contract block -- present exactly once, byte-identical to the
#      canonical `_shared/output-contract.md`, and anchored immediately
#      before `## Runtime Precedence` in every agent file (same anti-drift
#      mechanism as FF8, one link earlier in the chain: Output Contract ->
#      Runtime Precedence -> Output Format). Also required, byte-identical,
#      in `.claude/commands/protocol.md` -- the one command file explicitly
#      carrying the full block, since it is the primary session entry point;
#      the other command files inherit the contract via CLAUDE.md instead of
#      duplicating it (see CLAUDE.md's Output Contract note), so they are not
#      checked here.
# ---------------------------------------------------------------------------
section "FF10: Output Contract Block (present, unique, byte-identical, anchored)"
if [ "$PRESERVE_MODE" -eq 1 ]; then
  echo "  [REPORT] customized-preserve install: only framework agents carried by the project are checked here; deployed framework agents are reconciled by FF12"
fi

CONTRACT_SRC=$(shared_path output-contract.md)
if [ ! -f "$CONTRACT_SRC" ]; then
  fail "canonical output-contract block missing at ${CONTRACT_SRC}"
else
  CONTRACT_CONTENT=$(cat "$CONTRACT_SRC")

  while IFS= read -r agent_file; do
    [ -f "$agent_file" ] || continue
    agent_name=$(basename "$agent_file" .md)

    occ=$(grep -c '^## Output Contract$' "$agent_file" 2>/dev/null || true)
    occ=${occ:-0}
    if [ "$occ" -ne 1 ]; then
      fail "${agent_name}.md: '## Output Contract' heading appears ${occ} time(s) (expected exactly 1)"
      continue
    fi

    block=$(awk '/^## Output Contract$/{flag=1; print; next} /^## /{if (flag) exit} flag' "$agent_file")
    if [ "$block" != "$CONTRACT_CONTENT" ]; then
      fail "${agent_name}.md: Output Contract block differs from canonical ${CONTRACT_SRC}"
    else
      pass "${agent_name}.md: Output Contract block byte-identical to canonical source"
    fi

    contract_line=$(grep -n '^## Output Contract$' "$agent_file" | head -1 | cut -d: -f1)
    prec_line=$(grep -n '^## Runtime Precedence$' "$agent_file" | head -1 | cut -d: -f1)
    if [ -z "$prec_line" ]; then
      fail "${agent_name}.md: no '## Runtime Precedence' section to anchor Output Contract against"
    else
      between=$(sed -n "$((contract_line + 1)),$((prec_line - 1))p" "$agent_file" | grep -c '^## ' || true)
      between=${between:-0}
      if [ "$between" -ne 0 ]; then
        fail "${agent_name}.md: another '##' section sits between Output Contract and Runtime Precedence"
      else
        pass "${agent_name}.md: Output Contract anchored immediately before Runtime Precedence"
      fi
    fi
  done < <(block_agent_files)

  PROTOCOL_MD="${COMMANDS_DIR}/protocol.md"
  if [ ! -f "$PROTOCOL_MD" ]; then
    fail "protocol.md not found at ${PROTOCOL_MD} -- cannot verify Output Contract block"
  else
    occ=$(grep -c '^## Output Contract$' "$PROTOCOL_MD" 2>/dev/null || true)
    occ=${occ:-0}
    if [ "$occ" -ne 1 ]; then
      fail "protocol.md: '## Output Contract' heading appears ${occ} time(s) (expected exactly 1)"
    else
      block=$(awk '/^## Output Contract$/{flag=1; print; next} /^## /{if (flag) exit} flag' "$PROTOCOL_MD")
      if [ "$block" != "$CONTRACT_CONTENT" ]; then
        fail "protocol.md: Output Contract block differs from canonical ${CONTRACT_SRC}"
      else
        pass "protocol.md: Output Contract block byte-identical to canonical source"
      fi
    fi
  fi
fi

# ---------------------------------------------------------------------------
# FF11: No dead skill references -- every skill an agent definition points
#      at must resolve the way the agent resolves it at runtime: BY NAME,
#      through the multi-scope lookup (`cc skill get <name>`: project ->
#      machine -> shared knowledge, with the installed framework's own
#      catalog as part of machine scope).
#
#      Agents reference skills two ways, and both are checked by name:
#        1. `cc skill get <name>` anywhere in the agent body.
#        2. Backtick-quoted names in an '## Available Skills' table row
#           (e.g. `` `terraform-patterns` ``).
#
#      Repo-relative `.claude/skills/<category>/<name>/SKILL.md` paths are
#      themselves a failure, in every project. They only ever resolved in
#      the framework checkout: the installer ships agents into consumer
#      projects but never the framework's .claude/skills tree, so the same
#      line was a dead reference in every installed project (38 consumer
#      fitness failures, 2026-10-06, 22 of them this class).
#
#      Resolution uses ONE `cc skill list --scope all --json` call, not one
#      `cc skill get` per name (~20 names across the roster measured ~75s as
#      subprocesses; one listing is ~6s). When `cc` is unavailable (not on
#      PATH, or the macOS C compiler answering to `cc`), the same scopes are
#      scanned on disk instead: <project>/.claude/skills, ~/.claude/skills,
#      and the framework catalog at $COPILOT_PATH/.claude/skills -- so CI and
#      a machine without cc still get a real verdict rather than a skip.
#
#      Exists to catch the class of drift found 2026-08-09 in do.md (a
#      renamed skill, `terraform-patterns` for `terraform-best-practices`,
#      pointing at nothing) and the 2026-10-06 consumer-path class above.
# ---------------------------------------------------------------------------
section "FF11: No Dead Skill References"

while IFS= read -r ff11_line; do
  [ -z "$ff11_line" ] && continue
  case "$ff11_line" in
    "PASS "*) pass "${ff11_line#PASS }" ;;
    "FAIL "*) fail "${ff11_line#FAIL }" ;;
    *) fail "FF11 checker produced unparseable output: $ff11_line" ;;
  esac
done < <(python3 - "$AGENTS_DIR" "$COPILOT_PATH" <<'PYEOF'
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

agents_dir = Path(sys.argv[1])
copilot_path = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 and sys.argv[2] else None


def fail(msg):
    print(f"FAIL {msg}")


def ok(msg):
    print(f"PASS {msg}")


def info(msg):
    print(msg, file=sys.stderr)


PATH_REF_RE = re.compile(r"\.claude/skills/[A-Za-z0-9_\-./]+/SKILL\.md")
GET_RE = re.compile(r"cc skill get ([A-Za-z0-9_\-]+)")
TABLE_ROW_RE = re.compile(r"^\|\s*`([A-Za-z0-9_\-]+)`\s*\|")
NAME_RE = re.compile(r"^name:\s*['\"]?([A-Za-z0-9_\-]+)", re.MULTILINE)

project_root = agents_dir.resolve().parents[1]
agent_files = sorted(p for p in agents_dir.glob("*.md") if p.is_file())

if not agent_files:
    fail(f"no agent .md files found under {agents_dir}")
    sys.exit(0)

# Collect every reference, keyed by agent.
refs = {}  # agent -> {name: how}
for agent_file in agent_files:
    agent = agent_file.stem
    text = agent_file.read_text(encoding="utf-8")
    for path_ref in sorted(set(PATH_REF_RE.findall(text))):
        name = Path(path_ref).parent.name
        fail(
            f"{agent}.md: repo-relative skill path {path_ref} -- consumer projects never "
            f"receive the framework's .claude/skills tree; reference it as `cc skill get {name}`"
        )
    names = refs.setdefault(agent, {})
    for name in GET_RE.findall(text):
        names.setdefault(name, "cc skill get")
    in_table = False
    for line in text.splitlines():
        if line.strip() == "## Available Skills":
            in_table = True
            continue
        if in_table and line.startswith("## "):
            in_table = False
            continue
        if in_table:
            m = TABLE_ROW_RE.match(line)
            if m:
                names.setdefault(m.group(1), "Available Skills table")

if not any(refs.values()):
    info("FF11: no skill name references found")
    sys.exit(0)


def cc_listing():
    cc_bin = shutil.which("cc")
    if cc_bin is None:
        return None, "`cc` not on PATH"
    try:
        listing = subprocess.run(
            [cc_bin, "skill", "list", "--scope", "all", "--json"],
            capture_output=True, text=True, timeout=60,
        )
    except Exception as exc:  # noqa: BLE001 -- any failure falls back to disk
        return None, f"`cc skill list` errored ({exc})"
    if listing.returncode != 0 or not listing.stdout.strip():
        return None, "`cc skill list` unavailable"
    try:
        return {e["name"] for e in json.loads(listing.stdout) if "name" in e}, None
    except (ValueError, TypeError, KeyError):
        return None, "`cc skill list` returned unparseable output"


def disk_listing():
    roots = [project_root / ".claude" / "skills", Path.home() / ".claude" / "skills"]
    if copilot_path is not None:
        roots.append(copilot_path / ".claude" / "skills")
    found = set()
    for root in roots:
        if not root.is_dir():
            continue
        for skill_md in root.rglob("SKILL.md"):
            found.add(skill_md.parent.name)
            try:
                head = skill_md.read_text(encoding="utf-8", errors="replace")[:2000]
            except OSError:
                continue
            m = NAME_RE.search(head)
            if m:
                found.add(m.group(1))
    return found


known, why_not_cc = cc_listing()
via = "`cc skill list`"
if known is None:
    info(f"FF11: {why_not_cc} -- resolving skill names from the on-disk scopes instead")
    known = disk_listing()
    via = "on-disk skill scopes"

for agent in sorted(refs):
    for name, how in sorted(refs[agent].items()):
        if name in known:
            ok(f"{agent}.md: skill `{name}` ({how}) resolves via {via}")
        else:
            fail(f"{agent}.md: skill `{name}` ({how}) not found by {via} (project, machine, knowledge)")
PYEOF
)

# ---------------------------------------------------------------------------
# FF12: Deployment reconciliation -- does the corpus a session actually loads
#       match the corpus this repo just validated?
#
# WHY THIS EXISTS. Every check above this one measures $AGENTS_DIR, which
# defaults to this repo's own .claude/agents. A session does not read this repo.
# It reads the DEPLOYED agent directory (~/.claude/agents by default), and on a
# real machine those two are not the same thing: at the time this check was
# written, all 16 filenames matched while 8 files differed in bytes, including
# cpa.md by 1,672 B and cco.md by 494 B -- content present in the deployed copy
# and absent from the repo. FF9 passed, truthfully, about a number no session
# pays. An archived-agents directory (_archive, 8 files, ~59 KB) was also sitting
# in the deployed tree.
#
# That is the same shape as every other silence this framework has been bitten
# by: a check that answers "is the repo in order?" while nothing answers "is the
# thing that runs in order?"
#
# WHAT FAILS AND WHAT ONLY REPORTS, AND WHY THE SPLIT.
#   FAIL   the deployed corpus breaches the absolute ceiling. That is the number
#          sessions actually pay, so it is the number the ceiling is about.
#   FAIL   a file the repo defines is missing from the deployment, or the
#          deployment carries an agent the repo does not define. Either way the
#          roster a session sees is not the roster that was validated.
#   REPORT per-file byte drift, itemised with the delta and direction. Deliberately
#          not a failure: a repo edit legitimately precedes its install, and a
#          check that fails on every uncommitted edit is one that gets disabled --
#          which would restore the exact silence it exists to end. It is itemised
#          rather than summarised so it cannot be skimmed as "roughly the same".
#   SKIP   no deployed directory (CI, a fresh clone). Stated, never assumed clean.
# ---------------------------------------------------------------------------
section "FF12: Deployment Reconciliation (repo vs the corpus sessions load)"

# WHICH TWO DIRECTORIES, BY MODE.
#   framework  repo = this checkout's agents ($AGENTS_DIR); deployed = the machine
#              corpus (~/.claude/agents); history = this checkout's git.
#   consumer   repo = the framework source ($COPILOT_PATH/.claude/agents); deployed =
#              THIS project's agents ($AGENTS_DIR), because project-scope agents
#              shadow ~/.claude/agents for every session opened here; history = the
#              framework's git, not the project's. Running the framework-mode
#              comparison from a consumer compared the project against a stale
#              machine corpus and searched the PROJECT's git for agent history,
#              so every installed agent "matched no committed version" (16 false
#              failures in a clean install, 2026-10-06). A consumer may also
#              define its own agents; those are reported, not failed. And the
#              lock's release_tag must name a tag the framework actually has.
if [ "$FITNESS_MODE" = "consumer" ]; then
  FF12_REPO_AGENTS="${COPILOT_PATH}/.claude/agents"
  DEPLOYED_AGENTS_DIR="${CC_DEPLOYED_AGENTS_DIR:-$AGENTS_DIR}"
  FF12_OVERLAY_DIR=""
  if [ "$PRESERVE_MODE" -eq 1 ]; then
    # Framework agents load from the user-level deployment; the project's own
    # agents (overlay) shadow it and are reported as project-defined.
    DEPLOYED_AGENTS_DIR="${CC_DEPLOYED_AGENTS_DIR:-$USER_AGENTS_DIR}"
    FF12_OVERLAY_DIR="$AGENTS_DIR"
  fi
  FF12_HISTORY_ROOT="$COPILOT_PATH"
else
  FF12_REPO_AGENTS="$AGENTS_DIR"
  DEPLOYED_AGENTS_DIR="${CC_DEPLOYED_AGENTS_DIR:-${HOME}/.claude/agents}"
  FF12_OVERLAY_DIR=""
  FF12_HISTORY_ROOT="."
fi

if [ "$FITNESS_MODE" = "consumer" ]; then
  FF12_LOCK="${_SCRIPT_DIR}/copilot.lock.json"
  FF12_TAG="$(python3 -c "
import json, sys
try:
    lock = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
for c in lock.get('components', []):
    if c.get('component') == 'claude':
        print(c.get('release_tag') or '')
" "$FF12_LOCK" 2>/dev/null)"
  if [ ! -f "$FF12_LOCK" ]; then
    echo "  [SKIP] no copilot.lock.json at ${FF12_LOCK} -- no recorded release to verify"
  elif [ -z "$FF12_TAG" ]; then
    fail "copilot.lock.json records no Claude Copilot release_tag -- the install cannot be traced to a release"
  elif ! git -C "$COPILOT_PATH" rev-parse --git-dir >/dev/null 2>&1; then
    echo "  [SKIP] ${COPILOT_PATH} is not a git checkout -- cannot verify release tag ${FF12_TAG}"
  elif git -C "$COPILOT_PATH" rev-parse -q --verify "refs/tags/${FF12_TAG}^{commit}" >/dev/null 2>&1; then
    pass "copilot.lock.json release_tag ${FF12_TAG} is a tag in the framework repo"
  else
    fail "copilot.lock.json is locked to ${FF12_TAG}, which the framework repo at ${COPILOT_PATH} has not tagged (fetch tags, or the release was never tagged)"
  fi
fi

if [ ! -d "$FF12_REPO_AGENTS" ]; then
  echo "  [SKIP] no framework agent source at ${FF12_REPO_AGENTS} -- nothing to reconcile against."
elif [ ! -d "$DEPLOYED_AGENTS_DIR" ]; then
  echo "  [SKIP] no deployed agent directory at ${DEPLOYED_AGENTS_DIR} -- nothing to reconcile."
  echo "         Every result above describes this repo, not a running session."
elif [ "$(cd "$DEPLOYED_AGENTS_DIR" 2>/dev/null && pwd -P)" = "$(cd "$FF12_REPO_AGENTS" 2>/dev/null && pwd -P)" ]; then
  pass "deployed agents resolve to the same directory as the repo (${DEPLOYED_AGENTS_DIR}) -- no drift is possible"
else
  FF12_OUT=$(AGENTS_DIR="$FF12_REPO_AGENTS" DEPLOYED="$DEPLOYED_AGENTS_DIR" OVERLAY="$FF12_OVERLAY_DIR" \
    HISTORY_ROOT="$FF12_HISTORY_ROOT" MODE="$FITNESS_MODE" PROJECT_AGENTS="$PROJECT_AGENTS" \
    CEILING="$(python3 -c "
import json,sys
from pathlib import Path
try:
    for p in sorted((Path(sys.argv[1]) / '.claude').glob('context-budget-baseline-*.json')):
        pass
    print(json.loads(p.read_text())['thresholds']['agent_corpus_ceiling_bytes'])
except Exception:
    print(0)
" "$FF12_HISTORY_ROOT" 2>/dev/null || echo 0)" python3 - <<'FF12EOF'
import os
import re
import subprocess
from pathlib import Path

repo = Path(os.environ["AGENTS_DIR"])
dep = Path(os.environ["DEPLOYED"])
ceiling = int(os.environ.get("CEILING") or 0)
history_root = os.environ.get("HISTORY_ROOT") or "."
consumer = os.environ.get("MODE") == "consumer"
project_agents = set(os.environ.get("PROJECT_AGENTS", "").split())

repo_files = {p.name: p for p in repo.glob("*.md")}
dep_files = {p.name: p for p in dep.glob("*.md")}
overlay = os.environ.get("OVERLAY")
if overlay:
    dep_files.update({p.name: p for p in Path(overlay).glob("*.md")})
lines = []


def read(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# ---------------------------------------------------------------------------
# HOW THIS TELLS COMPOSITION FROM STALENESS FROM REAL DRIFT, AND WHY IT NEEDS TO.
#
# Two earlier versions of this check got it wrong, in instructive ways.
#
# v1 flagged any byte difference. On a real machine that fired on 8 of 16 files
# and read as 8 problems. It was 1. Six files were merely behind an uninstalled
# repo edit, and cpa.md was 1,672 B LARGER because the signed accounting tier
# appends its method to the base agent at install time -- the tier system working
# as designed. A check that cries wolf gets disabled, restoring the silence it
# exists to end.
#
# v2 classified by prefix: deployed-starts-with-repo meant composition,
# repo-starts-with-deployed meant stale. That broke the moment an edit landed in
# the MIDDLE of a file (the `Unknowns:` line goes inside the Output Format block,
# not at the end), so six stale files were reported as divergent. Prefix order is
# not the structure being tested.
#
# So the two questions get separated and each is answered with real evidence:
#
#   COMPOSITION is declared. A tier block announces itself -- a trailing `## ...
#   method` section whose body says it preserves the complete foundation contract
#   above. Strip those and what remains is the base the repo is responsible for.
#
#   STALENESS is checkable against git. If the deployed base matches ANY committed
#   version of that file, the deployment is simply behind; that is a report, not a
#   failure. If it matches nothing this repo has ever committed, the deployed base
#   is content of unknown origin -- every check above validated a file the session
#   does not load, and that is a failure.
#
# The distinction matters because only the third case invalidates the run.
# ---------------------------------------------------------------------------
TIER_BLOCK = re.compile(
    r"\n#{2,3} [^\n]*\n+This signed [^\n]*tier preserves the complete foundation[^\n]*\n"
)


def split_tier(text):
    """Return (base, tier_bytes) by removing declared trailing tier blocks."""
    match = None
    for m in TIER_BLOCK.finditer(text):
        match = m
    if match is None:
        return text, 0
    return text[: match.start()], len(text) - match.start()


def committed_versions(name, limit=200):
    """Every committed body of this agent file, across ALL branches, newest first.

    `--all` is load-bearing, and its absence produced a false alarm on the first real
    run. `git log -- <path>` walks only the CURRENT branch's history, so a file whose
    deployed copy came from a NEWER commit on another branch matched nothing and was
    reported as content of unknown origin. That is exactly what happened to cco.md: the
    deployed base was main's own newer, shortened wording, and the check was run from a
    feature branch that predated it. The check accused the deployment of drift when the
    deployment was simply ahead of the branch doing the checking.

    The limit is per-file and generous for the same reason -- a truncated history is
    indistinguishable from no match, and both read as a failure.
    """
    rel = f".claude/agents/{name}"
    try:
        revs = subprocess.run(
            ["git", "-C", history_root, "log", "--all", f"-{limit}", "--format=%H", "--", rel],
            capture_output=True, text=True, timeout=30, check=False,
        ).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    bodies = []
    for rev in revs:
        try:
            out = subprocess.run(
                ["git", "-C", history_root, "show", f"{rev}:{rel}"],
                capture_output=True, text=True, timeout=30, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if out.returncode == 0:
            bodies.append(out.stdout)
    return bodies


composed, behind, divergent = {}, {}, []
identical = 0
base_total = 0

for name in sorted(set(repo_files) & set(dep_files)):
    if name[:-3] in project_agents:
        # The project's own agent under a framework name (owner: project):
        # not a deployment of the framework file, so nothing to reconcile.
        lines.append(f"REPORT|{name} is project-owned (owner: project); the framework's {name} is not deployed here by design")
        continue
    r, d = read(repo_files[name]), read(dep_files[name])
    if r is None or d is None:
        divergent.append((name, "could not be read"))
        continue
    d_base, tier_bytes = split_tier(d)
    base_total += len(d_base)
    if tier_bytes:
        composed[name] = tier_bytes
    if d_base == r:
        identical += 1
        continue
    history = committed_versions(name)
    if history is None:
        divergent.append((name, "differs, and git history is unavailable to date it"))
    elif d_base in history:
        behind[name] = len(r) - len(d_base)
    else:
        divergent.append((name, "matches no version this repo has committed"))

missing = sorted(set(repo_files) - set(dep_files))
extra = sorted(set(dep_files) - set(repo_files))
for name in missing:
    lines.append(f"FAIL|{name} is defined in the repo and absent from the deployment -- "
                 f"a session cannot route to it")
for name in extra:
    if consumer:
        # A consumer project may define its own agents; the framework does not
        # own them, so their presence is stated, not failed, and their bytes
        # are outside the ceiling that governs the framework's base corpus.
        lines.append(f"REPORT|{name} is a project-defined agent (not in the framework roster)")
    else:
        base_total += dep_files[name].stat().st_size
        lines.append(f"FAIL|{name} is deployed and not defined in this repo -- sessions load an "
                     f"agent nothing here validates")
for name, why in divergent:
    lines.append(
        f"FAIL|{name}: the deployed base {why}. Every budget and contract check above "
        f"validated this repo's copy; the session loads that one. Reconcile before trusting "
        f"any result above."
    )

dep_total = sum(p.stat().st_size for p in dep_files.values())

if ceiling:
    if base_total > ceiling:
        lines.append(
            f"FAIL|deployed base agent corpus is {base_total:,} B against an absolute "
            f"ceiling of {ceiling:,} B (over by {base_total - ceiling:,} B)"
        )
    else:
        lines.append(
            f"PASS|deployed base agent corpus is {base_total:,} B, within the absolute "
            f"ceiling of {ceiling:,} B"
        )

if composed:
    total = sum(composed.values())
    lines.append(
        f"REPORT|signed tier extensions add {total:,} B across {len(composed)} agent(s), so "
        f"a session on this machine loads {dep_total:,} B, not the {base_total:,} B the "
        f"ceiling governs. Working as designed -- but it is the number actually paid, and "
        f"no other check states it."
    )
    for name, delta in sorted(composed.items()):
        lines.append(f"REPORT|  {name}: +{delta:,} B of tier content")

if behind:
    lines.append(
        f"REPORT|{len(behind)} agent file(s) are newer in this repo than in the deployment. "
        f"Sessions run the committed older content until the next `cc reconcile apply` or "
        f"reinstall -- so any change made here is not yet in effect."
    )
    for name, delta in sorted(behind.items()):
        # `delta` is repo minus deployed and can be negative when the newer repo
        # version is SHORTER. "repo is -329 B ahead" is nonsense, and nonsense in a
        # report is how a reader learns to stop reading it.
        direction = "larger" if delta > 0 else "smaller"
        lines.append(f"REPORT|  {name}: repo version is {abs(delta):,} B {direction}, "
                     f"and not yet deployed")

if identical and not divergent and not missing and (consumer or not extra):
    lines.append(f"PASS|{identical} agent base(s) byte-identical between repo and deployment")

archive = dep / "_archive"
if archive.is_dir():
    arch = list(archive.rglob("*.md"))
    if arch:
        lines.append(
            f"REPORT|the deployment carries {len(arch)} archived agent file(s) "
            f"({sum(p.stat().st_size for p in arch):,} B) under _archive/, outside every "
            f"budget measured above"
        )

print("\n".join(lines))
FF12EOF
)

  while IFS='|' read -r verdict message; do
    [ -z "$verdict" ] && continue
    case "$verdict" in
      PASS)   pass "$message" ;;
      FAIL)   fail "$message" ;;
      REPORT) echo "  [REPORT] $message" ;;
      *)      echo "  $verdict$message" ;;
    esac
  done <<< "$FF12_OUT"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo
echo "========================================"
echo "Fitness Check Results"
echo "========================================"
echo "  Passed: $PASS_COUNT"
echo "  Failed: $FAIL_COUNT"
echo

if [ $FAIL_COUNT -gt 0 ]; then
  echo "FAILURES:"
  for f in "${FAILURES[@]}"; do
    echo "  - $f"
  done
  echo
  echo "FITNESS CHECK FAILED ($FAIL_COUNT failures)"
  echo
  echo "Restore guidance:"
  echo "  - Missing agents: Copy from ${COPILOT_PATH}/.claude/agents/"
  echo "  - Orphan routes: Update Route To Other Agent table in offending agent file"
  echo "  - Retired agents: rm ${AGENTS_DIR}/<retired>.md"
  echo
  exit 1
else
  echo "FITNESS CHECK PASSED"
  exit 0
fi
