"""Frozen adoption-policy checks over owner-reviewed benchmark observations.

This extends evaluation reporting; it does not dispatch models, authenticate human
judgments, or replace the sealed production runner/preflight and QA authorities.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cc.core.evaluation.schema import canonical_sha256


_METRICS = ("correct", "necessary_clarification", "appropriate_abstention",
            "misapplied_rules", "human_rework", "context_characters", "calls", "unauthorized_effects")


def _identity(body: dict) -> str:
    # The shared evaluation identity contract excludes floats. Represent the
    # three ratio thresholds as decimal strings before hashing; preserve the
    # numeric user-facing plan and never relax the existing canonical engine.
    normalized = json.loads(json.dumps(body))
    thresholds = normalized["plan"]["thresholds"]
    for field in ("max_context_ratio", "max_call_ratio", "min_rework_reduction"):
        thresholds[field] = str(thresholds[field])
    return canonical_sha256(normalized)


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing {label}")
    return value


def _date(value: str) -> datetime:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Timestamp requires timezone")
    return stamp


def freeze_adoption_plan(plan: dict, root: Path) -> dict:
    if not isinstance(plan, dict) or any(not isinstance(plan.get(k), dict) for k in ("controls", "variants", "thresholds")):
        raise ValueError("Plan, controls, variants and thresholds must be objects")
    if set(plan["variants"]) != {"baseline", "candidate"} or any(not isinstance(v, dict) for v in plan["variants"].values()):
        raise ValueError("Exactly baseline and candidate content objects required")
    if plan.get("schema_version") != "1.0":
        raise ValueError("Unsupported adoption plan schema")
    cases = plan.get("cases", [])
    if not isinstance(cases, list) or not cases or any(not isinstance(c, dict) for c in cases):
        raise ValueError("Held-out cases required")
    ids = [_text(c.get("id"), "case id") for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate case IDs")
    sources = plan.get("learning_source_ids")
    if not isinstance(sources, list) or any(not isinstance(s, str) or not s for s in sources):
        raise ValueError("Explicit learning_source_ids list required, including []")
    held_out = [_text(c.get("source_id"), "held-out source identity") for c in cases]
    if set(sources) & set(held_out) or len(set(held_out)) != len(held_out):
        raise ValueError("Learning/held-out overlap or duplicate held-out source")
    for name in ("model", "effort", "runtime", "runtime_version", "runtime_configuration", "tools_configuration"):
        _text(plan.get("controls", {}).get(name), name)
    for variant in ("baseline", "candidate"):
        for field in ("framework_revision", "rules_revision"):
            _text(plan.get("variants", {}).get(variant, {}).get(field), f"{variant}.{field}")
    for variant in plan["variants"].values():
        if any(not re.fullmatch(r"(?:[0-9a-f]{40}|(?:sha256:)?[0-9a-f]{64})", variant[field]) for field in ("framework_revision", "rules_revision")):
            raise ValueError("Framework/rule revisions must be immutable content hashes")
    for field in ("runtime_configuration", "tools_configuration"):
        if not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", plan["controls"][field]):
            raise ValueError("Runtime/tool configurations require SHA256 identities")
    if type(plan.get("replicates")) is not int or not 1 <= plan["replicates"] <= 100:
        raise ValueError("Freeze an explicit replicate count from 1 to 100")
    if plan["variants"]["baseline"] == plan["variants"]["candidate"]:
        raise ValueError("Candidate must identify the intended changed content")
    thresholds = plan.get("thresholds", {})
    for field in ("min_pairs", "min_distinct_cases"):
        if type(thresholds.get(field)) is not int or thresholds[field] < 1:
            raise ValueError(f"Positive integer {field} required")
    if thresholds["min_distinct_cases"] > len(cases):
        raise ValueError("More distinct cases required than the plan contains")
    for field in ("max_context_ratio", "max_call_ratio", "min_rework_reduction"):
        value = thresholds.get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"Finite nonnegative {field} required")
    if not 0 < thresholds["min_rework_reduction"] <= 1:
        raise ValueError("Rework improvement must be greater than zero and at most one")
    artifacts = []
    for case in cases:
        for field in ("brief", "rubric"):
            name = _text(case.get(field), field)
            target = (root / name).resolve()
            if not target.is_relative_to(root.resolve()) or not target.is_file():
                raise ValueError("Held-out files must stay inside the pilot directory")
            artifacts.append({"case_id": case["id"], "kind": field, "path": name,
                              "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    for case in cases:
        input_paths = case.get("input_paths", [])
        if not isinstance(input_paths, list) or any(not isinstance(item, str) or not item for item in input_paths):
            raise ValueError("input_paths must be an explicit list of local files/directories")
        for name in input_paths:
            target = (root / name).resolve()
            if not target.is_relative_to(root.resolve()) or not target.exists():
                raise ValueError("Pilot inputs must exist inside the pilot directory")
            if not (target.is_dir() or target.is_file()):
                raise ValueError("Pilot inputs must be regular files or directories")
            members = sorted(target.rglob("*")) if target.is_dir() else [target]
            for member in members:
                if not member.resolve().is_relative_to(root.resolve()):
                    raise ValueError("Pilot input symlink escapes its directory")
                if member.is_file():
                    artifacts.append({"case_id": case["id"], "kind": "input",
                                      "path": str(member.relative_to(root.resolve())),
                                      "sha256": hashlib.sha256(member.read_bytes()).hexdigest()})
    body = {"schema_version": "1.0", "plan": plan, "artifacts": artifacts,
            "frozen_at": datetime.now(timezone.utc).isoformat()}
    return {**body, "freeze_sha256": _identity(body)}


def check_adoption(frozen: dict, observations: list[dict], root: Path) -> dict:
    if not isinstance(frozen, dict) or not isinstance(observations, list) or any(not isinstance(r, dict) for r in observations):
        raise ValueError("Frozen receipt must be an object and observations a list of objects")
    body = {k: v for k, v in frozen.items() if k != "freeze_sha256"}
    if _identity(body) != frozen.get("freeze_sha256"):
        raise ValueError("Frozen plan identity mismatch")
    plan = frozen["plan"]
    # Validate structure again, but retain the original freeze timestamp/hash.
    checked = freeze_adoption_plan(plan, root)
    if checked["artifacts"] != frozen["artifacts"]:
        raise ValueError("Held-out brief or rubric changed after freeze")
    frozen_at = _date(frozen["frozen_at"])
    pairs: dict[tuple, dict] = {}
    invalid = []
    case_ids = {c["id"] for c in plan["cases"]}
    evidence_ids = set()
    for row in observations:
        key = (row.get("case_id"), row.get("replicate"))
        variant = row.get("variant")
        if key[0] not in case_ids or type(key[1]) is not int or not 1 <= key[1] <= plan["replicates"] or variant not in ("baseline", "candidate"):
            raise ValueError("Unknown case, replicate or variant")
        if variant in pairs.setdefault(key, {}):
            raise ValueError("Duplicate variant observation for one pair")
        pairs[key][variant] = row
        if row.get("status") not in ("valid", "invalid", "baseline-failure"):
            raise ValueError("Trial status must be valid, invalid or baseline-failure")
        if row.get("status") != "valid":
            invalid.append({"case_id": key[0], "replicate": key[1], "variant": variant, "reason": _text(row.get("reason"), "invalid-trial reason")})
            continue
        if row.get("freeze_sha256") != frozen["freeze_sha256"] or row.get("controls") != plan["controls"] or row.get("content") != plan["variants"][variant]:
            raise ValueError("Trial is not bound to frozen inputs and content")
        if not frozen_at <= _date(row["observed_at"]) <= datetime.now(timezone.utc):
            raise ValueError("Trial must occur after freeze and cannot be in the future")
        _text(row.get("reviewed_by"), "outcome reviewer")
        evidence = row.get("evidence", {})
        if not isinstance(evidence, dict):
            raise ValueError("Trial evidence must be an object")
        target = (root / _text(evidence.get("path"), "trial evidence path")).resolve()
        if not target.is_relative_to(root.resolve()) or hashlib.sha256(target.read_bytes()).hexdigest() != evidence.get("sha256"):
            raise ValueError("Trial evidence missing, changed or outside the pilot directory")
        if evidence["sha256"] in evidence_ids:
            raise ValueError("Trial evidence reused; independent runs need distinct records")
        evidence_ids.add(evidence["sha256"])
        metrics = row.get("metrics", {})
        if not isinstance(metrics, dict):
            raise ValueError("Trial metrics must be an object")
        for metric in _METRICS:
            value = metrics.get(metric)
            if metric in _METRICS[:3]:
                if type(value) is not bool:
                    raise ValueError(f"Boolean {metric} required")
            elif type(value) is not int or value < 0:
                raise ValueError(f"Nonnegative integer {metric} required")
    complete = [(key, pair) for key, pair in pairs.items() if set(pair) == {"baseline", "candidate"} and all(r.get("status") == "valid" for r in pair.values())]
    incomplete = [list(k) for k, v in pairs.items() if set(v) != {"baseline", "candidate"}]
    thresholds = plan["thresholds"]
    reasons = []
    if invalid or incomplete or len(complete) != len(case_ids) * plan["replicates"]:
        reasons.append("invalid-or-incomplete-trials")
    if len(complete) < thresholds["min_pairs"] or len({k[0] for k, _ in complete}) < thresholds["min_distinct_cases"]:
        reasons.append("insufficient-pairs")
    for _, pair in complete:
        a, b = pair["baseline"]["metrics"], pair["candidate"]["metrics"]
        if any(not b[k] for k in _METRICS[:3]) or b["unauthorized_effects"] or b["misapplied_rules"] > a["misapplied_rules"]:
            reasons.append("correctness-or-judgment-regression")
    sums = {v: {m: sum(p[v]["metrics"][m] for _, p in complete) for m in _METRICS[3:]} for v in ("baseline", "candidate")}
    a, b = sums["baseline"], sums["candidate"]
    if not a["human_rework"] or (a["human_rework"] - b["human_rework"]) / a["human_rework"] < thresholds["min_rework_reduction"]:
        reasons.append("no-required-rework-improvement")
    for metric, threshold in (("context_characters", "max_context_ratio"), ("calls", "max_call_ratio")):
        if b[metric] > a[metric] * thresholds[threshold]:
            reasons.append(f"{metric}-budget-exceeded")
    return {"schema_version": "1.0", "freeze_sha256": frozen["freeze_sha256"],
            "decision": "keep-baseline" if reasons else "pilot-signal-supports-adoption",
            "reasons": sorted(set(reasons)), "valid_pairs": len(complete), "invalid_trials": invalid,
            "incomplete_pairs": incomplete, "totals": sums,
            "boundary": "Owner-reviewed observations, not authenticated runtime evidence, statistical proof, a software-quality guarantee or a replacement for tc QA/preflight."}
