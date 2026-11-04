#!/usr/bin/env python3
"""Provider-free protocol packaging and pending-QA dispatch boundary checks.

The verifier shims test the hook boundary, not tc persistence or native models.
Fixtures and original failures remain under --evidence-root; nothing is deleted.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, default=ROOT / ".copilot/parallel-protocol-check")
    parser.add_argument("--policy", type=Path)
    args = parser.parse_args()
    args.evidence_root.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix="run-", dir=args.evidence_root))
    checks = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})
        (evidence / "results.json").write_text(json.dumps(checks, indent=2))
        if not passed:
            raise AssertionError(f"{name}: {detail}; evidence={evidence}")

    command = (ROOT / ".claude/commands/orchestrate.md").read_text()
    check("legacy redirect matches template", command == (ROOT / "templates/commands/orchestrate.md").read_text())
    check("legacy command is deprecated", "deprecated" in command.lower())
    check("legacy redirect cannot directly delete", "git worktree remove" not in command and "git branch -d" not in command)
    protocol = (ROOT / ".claude/commands/protocol.md").read_text()
    check("protocol owns real native dispatch", "tc cycle claim" in protocol and "actually invoke" not in protocol and "invoke the native Agent tool concurrently" in protocol)
    check("no obsolete arbitrary cap", "at most three concurrent subagents" not in protocol)
    architect = (ROOT / ".claude/agents/ta.md").read_text()
    check("no minimum task threshold", "(5+ tasks)" not in architect)
    lifecycle = (ROOT / ".claude/agents/_shared/work-lifecycle.md").read_text()
    check("lifecycle stays bounded", len(lifecycle.split()) < 1000)
    check("cleanup holds unique and active work", "stopped-worker evidence" in lifecycle and "Hold uncertain resources" in lifecycle)
    if args.policy:
        policy = args.policy.read_text()
        check("canonical policy covers both runtimes", "Claude Copilot and Codex Copilot" in policy)
        check("cheap smoke makes no native-model claim", "does not prove" in policy and "provider-free" in policy)
        check("automatic cleanup retains branches", "Preserve their branches by default" in policy)

    hook = ROOT / ".claude/hooks/pretool-check.sh"
    cases = [
        ("untracked-builder", "none", "valid", "allow", 2),
        ("bare-marker", "bare", "valid", "allow", 2),
        ("forged-claim", "valid", "deny", "allow", 2),
        ("wrong-role", "valid", "wrong-role", "allow", 2),
        ("wrong-cwd", "valid", "wrong-cwd", "allow", 2),
        ("pending-same-task", "valid", "same-task", "allow", 2),
        ("malformed-receipt", "valid", "malformed", "allow", 2),
        ("knowledge-denied", "valid", "valid", "deny", 2),
        ("independent-claimed-builder", "valid", "valid", "allow", 0),
        ("independent-claimed-designer", "valid", "valid", "allow", 0),
    ]
    for name, framing, tc_mode, journey_mode, expected in cases:
        case = evidence / name
        (case / "state").mkdir(parents=True)
        (case / "worker").mkdir()
        session = "cycle-hook-test"
        (case / "state/qa-gate.json").write_text(json.dumps({session: {"pending_tasks": ["TASK-11"]}}))
        cc = case / "cc-shim"
        cc.write_text("#!/bin/sh\nif [ \"$JOURNEY_MODE\" = deny ]; then printf '%s\\n' '{\"schema_version\":\"2.1\",\"state\":\"denied\",\"reason\":\"fixture-knowledge-rejected\"}'; exit 2; fi\nprintf '%s\\n' '{\"schema_version\":\"2.1\",\"state\":\"no_active\"}'\n")
        cc.chmod(0o700)
        tc = case / "tc-shim"
        tc.write_text("""#!/bin/sh
if [ "$1 $2" = 'task check-qa' ]; then printf '%s\\n' '{"approved":false,"reason":"pending"}'; exit 0; fi
if [ "$1 $2" != 'cycle verify-dispatch' ]; then exit 2; fi
printf '%s\\n' "$*" >> "$CALL_LOG"
if [ "$TC_MODE" = deny ]; then exit 2; fi
role="$6"; cwd="$8"; task=12
if [ "$TC_MODE" = wrong-role ]; then role=doc; fi
if [ "$TC_MODE" = wrong-cwd ]; then cwd=/different; fi
if [ "$TC_MODE" = same-task ]; then task=11; fi
if [ "$TC_MODE" = malformed ]; then printf '%s\\n' '{"allowed":true}'; exit 0; fi
printf '{"allowed":true,"cycle":"cycle-a","stream":"stream-b","role":"%s","task":%s,"cwd":"%s","leaseToken":"fixture-lease"}\\n' "$role" "$task" "$cwd"
""")
        tc.chmod(0o700)
        role = "uids" if name.endswith("designer") else "me"
        prompt = "Perform the bounded task."
        if framing != "none":
            prompt += "\nCYCLE: cycle-a STREAM: stream-b"
        if framing == "valid":
            prompt += f"\nCYCLE-CWD: {case / 'worker'}"
        payload = {"session_id": session, "tool_name": "Agent", "tool_input": {"subagent_type": role, "prompt": prompt}}
        env = dict(os.environ, COPILOT_FORCE_DELEGATE="off", COPILOT_QA_GATE="on", COPILOT_EXTENSIONS_GATE="off", COPILOT_SAFETY="off", COPILOT_HOOK_STATE_DIR=str(case / "state"), COPILOT_CC_BIN=str(cc), COPILOT_TC_BIN=str(tc), CLAUDE_PROJECT_DIR=str(case), JOURNEY_MODE=journey_mode, TC_MODE=tc_mode, CALL_LOG=str(case / "cycle-verifier-calls.txt"))
        result = subprocess.run(["bash", str(hook)], input=json.dumps(payload), text=True, capture_output=True, env=env, cwd=case, timeout=10)
        (case / "result.json").write_text(json.dumps({"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}, indent=2))
        check(name, result.returncode == expected, f"expected={expected}, observed={result.returncode}, output={result.stdout[:300]}")
        if journey_mode == "deny":
            check("knowledge refusal precedes claim consumption", not (case / "cycle-verifier-calls.txt").exists())
    print(json.dumps({"status": "passed", "checks": len(checks), "providers": 0, "evidence": str(evidence)}))


if __name__ == "__main__":
    main()
