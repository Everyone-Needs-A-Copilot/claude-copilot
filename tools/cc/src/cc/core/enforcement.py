"""Harness-independent evaluation of the shared safety rule file.

No commands are executed. This is pattern detection, not shell confinement.
Evaluation errors are explicit and must be denied by mandatory host adapters.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


def evaluate(request: dict, rules_path: Path, *, destructive_action: str = "block") -> dict:
    if not isinstance(request, dict) or request.get("schema_version") != 1:
        raise ValueError("Unsupported enforcement request schema")
    if request.get("operation") != "shell":
        raise ValueError("Unsupported enforcement operation")
    command = request.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("A nonempty shell command is required")
    if len(command) > 1_000_000:
        raise ValueError("Shell command exceeds enforcement input limit")
    if destructive_action not in {"block", "warn"}:
        raise ValueError("Invalid destructive action")
    raw = rules_path.read_bytes()
    policy = json.loads(raw)
    if not isinstance(policy, dict) or not isinstance(policy.get("rules"), list) or not policy["rules"]:
        raise ValueError("Invalid or empty safety policy")
    matches = []
    for rule in policy["rules"]:
        if not isinstance(rule, dict) or not isinstance(rule.get("enabled"), bool):
            raise ValueError("Invalid safety rule")
        if not rule["enabled"]:
            continue
        if rule.get("action") not in {"warn", "block"} or not isinstance(rule.get("id"), str):
            raise ValueError("Invalid safety rule action or id")
        patterns = rule.get("patterns")
        if not isinstance(patterns, list) or not patterns or not all(isinstance(p, str) and p for p in patterns):
            raise ValueError("Invalid safety rule patterns")
        # Compile every pattern, including rules that do not match this command.
        compiled = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
        if any(pattern.search(command) for pattern in compiled):
            action = destructive_action if rule["id"] == "destructive-command" else rule["action"]
            matches.append({"id": rule["id"], "action": action})
    decision = "deny" if any(m["action"] == "block" for m in matches) else "warn" if matches else "allow"
    return {"schema_version": 1, "decision": decision,
            "reason": "Safety policy: " + ", ".join(m["id"] for m in matches) if matches else "No safety pattern matched",
            "matches": matches, "policy_path": str(rules_path.resolve()),
            "policy_sha256": hashlib.sha256(raw).hexdigest()}
