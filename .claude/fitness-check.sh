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

  if [ -f "${AGENTS_DIR}/${ref}.md" ]; then
    pass "@agent-${ref} resolves to ${AGENTS_DIR}/${ref}.md"
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
  if [ -f "${AGENTS_DIR}/${agent}.md" ]; then
    pass "${agent}.md present"
  else
    fail "${agent}.md MISSING (in VERSION.json roster but not in ${AGENTS_DIR}/)"
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
  agent_file="${AGENTS_DIR}/${agent}.md"
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
ON_DISK_AGENTS=$(for f in "${AGENTS_DIR}"/*.md; do [ -f "$f" ] && basename "$f" .md; done 2>/dev/null | tr '\n' ' ')
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
done < <(python3 - "$AGENTS_DIR" "$ROSTER" <<'PYEOF'
import re
import sys
from pathlib import Path

agents_dir = Path(sys.argv[1])
roster = set(sys.argv[2].split()) if len(sys.argv) > 2 else set()

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

for md in sorted(agents_dir.glob("*.md")):
    name = md.stem
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
    missing_required = [k for k in REQUIRED_TOP if k not in top_keys]
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

PRECEDENCE_SRC="${AGENTS_DIR}/_shared/precedence.md"
if [ ! -f "$PRECEDENCE_SRC" ]; then
  fail "canonical precedence block missing at ${PRECEDENCE_SRC}"
else
  PRECEDENCE_CONTENT=$(cat "$PRECEDENCE_SRC")
  for agent_file in "${AGENTS_DIR}"/*.md; do
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
  done
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

CONTRACT_SRC="${AGENTS_DIR}/_shared/output-contract.md"
if [ ! -f "$CONTRACT_SRC" ]; then
  fail "canonical output-contract block missing at ${CONTRACT_SRC}"
else
  CONTRACT_CONTENT=$(cat "$CONTRACT_SRC")

  for agent_file in "${AGENTS_DIR}"/*.md; do
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
  done

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
#      at must actually resolve, checked two ways since agents reference
#      skills two ways:
#        1. Explicit `@include .claude/skills/<path>/SKILL.md` paths --
#           checked directly against the filesystem (repo-relative, no
#           external dependency, always runs).
#        2. Backtick-quoted skill NAMES in an '## Available Skills' table
#           row (e.g. `` `terraform-patterns` ``) -- checked against a
#           SINGLE `cc skill list --scope all --json` call (multi-scope:
#           project / machine / shared knowledge, the same lookup agents
#           perform at runtime), not one `cc skill get` subprocess per
#           name -- with ~20 table rows across the roster, per-name
#           subprocesses measured ~75s for one fitness-check.sh run (each
#           `cc` invocation pays its own interpreter + CLI startup cost),
#           which multiplies out badly in test files that run
#           fitness-check.sh repeatedly (e.g. tests/test_ff6_negative.py).
#           One `cc skill list` call is ~6s regardless of table size. A
#           skill that only lives in the shared knowledge repo is still
#           correctly recognized as real, not flagged for not sitting
#           under .claude/skills/ locally. If `cc` is not on PATH, or the
#           list call fails, this half is skipped (PASS, noted) rather
#           than failed -- an environment limitation, not a project
#           defect.
#      Exists to catch exactly the class of drift found 2026-08-09 in
#      do.md: a renamed/typo'd skill name (`terraform-patterns` instead of
#      `terraform-best-practices`) sitting in an agent's Available Skills
#      table, unenforced, pointing at nothing.
# ---------------------------------------------------------------------------
section "FF11: No Dead Skill References"

while IFS= read -r ff11_line; do
  [ -z "$ff11_line" ] && continue
  case "$ff11_line" in
    "PASS "*) pass "${ff11_line#PASS }" ;;
    "FAIL "*) fail "${ff11_line#FAIL }" ;;
    *) fail "FF11 checker produced unparseable output: $ff11_line" ;;
  esac
done < <(python3 - "$AGENTS_DIR" <<'PYEOF'
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

agents_dir = Path(sys.argv[1])


def fail(msg):
    print(f"FAIL {msg}")


def ok(msg):
    print(f"PASS {msg}")


def info(msg):
    print(msg, file=sys.stderr)


INCLUDE_RE = re.compile(r"\.claude/skills/[A-Za-z0-9_\-./]+/SKILL\.md")
TABLE_ROW_RE = re.compile(r"^\|\s*`([A-Za-z0-9_\-]+)`\s*\|")

repo_root = agents_dir.resolve().parents[1]
agent_files = sorted(p for p in agents_dir.glob("*.md") if p.is_file())

if not agent_files:
    fail(f"no agent .md files found under {agents_dir}")
    sys.exit(0)

# 1. Explicit @include .claude/skills/.../SKILL.md paths.
found_any_path_ref = False
for agent_file in agent_files:
    agent_name = agent_file.stem
    text = agent_file.read_text(encoding="utf-8")
    for match in sorted(set(INCLUDE_RE.findall(text))):
        found_any_path_ref = True
        target = repo_root / match
        if target.is_file():
            ok(f"{agent_name}.md: referenced skill file exists ({match})")
        else:
            fail(f"{agent_name}.md: references nonexistent skill file {match}")
if not found_any_path_ref:
    info("FF11: no @include .claude/skills/*/SKILL.md path references found")

# 2. Backtick skill names in '## Available Skills' tables -- resolved
#    against ONE `cc skill list` call (see comment above on why not one
#    subprocess per name).
cc_bin = shutil.which("cc")
known_skill_names = None
if cc_bin is not None:
    try:
        listing = subprocess.run(
            [cc_bin, "skill", "list", "--scope", "all", "--json"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if listing.returncode == 0 and listing.stdout.strip():
            known_skill_names = {
                entry["name"] for entry in json.loads(listing.stdout) if "name" in entry
            }
    except Exception as exc:
        info(f"FF11: `cc skill list` errored, skipping name-based lookup: {exc}")

if cc_bin is None:
    ok("Available Skills table entries: `cc` not on PATH -- skipping name-based lookup")
elif known_skill_names is None:
    ok("Available Skills table entries: `cc skill list` unavailable -- skipping name-based lookup")
else:
    found_any_name_ref = False
    for agent_file in agent_files:
        agent_name = agent_file.stem
        in_table = False
        for line in agent_file.read_text(encoding="utf-8").splitlines():
            if line.strip() == "## Available Skills":
                in_table = True
                continue
            if in_table and line.startswith("## "):
                in_table = False
                continue
            if not in_table:
                continue
            m = TABLE_ROW_RE.match(line)
            if not m:
                continue
            name = m.group(1)
            found_any_name_ref = True
            if name in known_skill_names:
                ok(f"{agent_name}.md: skill `{name}` resolves via `cc skill list`")
            else:
                fail(
                    f"{agent_name}.md: skill `{name}` listed in Available Skills "
                    f"but not found by `cc skill list --scope all`"
                )
    if not found_any_name_ref:
        info("FF11: no '## Available Skills' table rows found")
PYEOF
)

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
