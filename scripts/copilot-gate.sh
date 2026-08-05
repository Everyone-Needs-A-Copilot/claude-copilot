#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/copilot-gate.sh [--task TASK_ID]

Checks Codex Copilot QA-gate state in tc. A task that declares
metadata.requiresQa=true must have a test work product attached to that task
whose content includes a passing VERDICT plus an ARTIFACT marker. Metadata may
index the QA result, but it is never accepted as evidence by itself.

Accepted artifact markers:
  ARTIFACT: test-run|...
  ARTIFACT: file-check|...
  ARTIFACT: diff-check|...
  ARTIFACT: screenshot-check|...
  ARTIFACT: a11y-check|...
  ARTIFACT: design-fidelity-check|...

Accepted passing verdicts:
  VERDICT: APPROVED
  VERDICT: APPROVED-WITH-MINOR-FIXES
EOF
}

TASK_ID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task)
      TASK_ID="${2:-}"
      shift 2
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! command -v tc >/dev/null 2>&1; then
  echo "copilot-gate: tc is not installed or not on PATH" >&2
  exit 2
fi

python3 - "$TASK_ID" <<'PY'
import json
import re
import subprocess
import sys


task_id = sys.argv[1]


def run_json(cmd):
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    text = result.stdout.strip()
    return json.loads(text) if text else None


def metadata(task):
    raw = task.get("metadata")
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def task_wps(tid):
    try:
        return run_json(["tc", "wp", "list", "--task", str(tid), "--json"]) or []
    except subprocess.CalledProcessError:
        return []


def wp_content(wp):
    wid = wp.get("id")
    if not wid:
        return ""
    try:
        full = run_json(["tc", "wp", "get", str(wid), "--json"]) or {}
    except subprocess.CalledProcessError:
        return {}, ""
    return full, str(full.get("content") or "")


PASSING_VERDICT_RE = re.compile(
    r"VERDICT:\s*(APPROVED-WITH-MINOR-FIXES|APPROVED)\b",
    re.IGNORECASE,
)
ARTIFACT_RE = re.compile(
    r"^\s*ARTIFACT:\s*"
    r"(test-run|file-check|diff-check|screenshot-check|a11y-check|design-fidelity-check)"
    r"\|.+$",
    re.IGNORECASE | re.MULTILINE,
)


def approved_with_artifact(content):
    return bool(PASSING_VERDICT_RE.search(content) and ARTIFACT_RE.search(content))


if task_id:
    tasks = [run_json(["tc", "task", "get", task_id, "--json"])]
else:
    tasks = run_json(["tc", "task", "list", "--json"]) or []

blocked = []
checked = 0

for task in tasks:
    if not task:
        continue
    meta = metadata(task)
    requires_qa = bool(meta.get("requiresQa"))
    if not requires_qa:
        continue
    checked += 1
    verdict_ok = False
    for wp in task_wps(task["id"]):
        if wp.get("type") != "test":
            continue
        full_wp, content = wp_content(wp)
        wp_task_id = full_wp.get("task_id", full_wp.get("task"))
        if wp_task_id is not None and str(wp_task_id) != str(task["id"]):
            continue
        if approved_with_artifact(content):
            verdict_ok = True
            break
    if not verdict_ok:
        blocked.append(f"TASK-{task['id']}: {task.get('title', '').strip()}")

if blocked:
    print("QA gate failed:")
    for item in blocked:
        print(f"- {item}")
    sys.exit(1)

print(f"QA gate passed ({checked} QA-required task(s) checked)")
PY
