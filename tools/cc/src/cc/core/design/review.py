"""Design judgment, later detector evidence, and explicit human verification."""
from __future__ import annotations

import base64
import hashlib
import html
import json
import struct
from pathlib import Path

from .contracts import (create_file, file_record, identity, local_path, now, read_bytes,
                        read_json, save_receipt, source_records, text, validate_contract, verify_receipt, task_binding)
from .tools import audit


def start_review(root: Path, contract_path: str, assessment_path: str, output: str) -> dict:
    contract = validate_contract(read_json(local_path(root, contract_path)), root)
    binding = task_binding(contract, root)
    assessment = read_json(local_path(root, assessment_path))
    text(assessment.get("judgment"), "Initial design judgment", 12000)
    if assessment.get("method") not in ("sequential", "independent"):
        raise ValueError("Assessment method must explicitly be sequential or independent")
    text(assessment.get("reviewed_by"), "reviewed_by")
    if assessment["method"] == "independent":
        text(assessment.get("independence_evidence"), "independence_evidence")
    if type(assessment.get("detector_seen")) is not bool:
        raise ValueError("Record detector_seen as an explicit boolean")
    issues = assessment.get("issues")
    if not isinstance(issues, list) or len(issues) > 100:
        raise ValueError("Record issues explicitly, including []")
    issue_ids = set()
    for issue in issues:
        if not isinstance(issue, dict) or issue.get("severity") not in ("blocking", "minor", "question"):
            raise ValueError("Issue severity must be blocking, minor, or question")
        iid = text(issue.get("id"), "issue.id", 80)
        if iid in issue_ids:
            raise ValueError("Duplicate design issue ID")
        issue_ids.add(iid)
        text(issue.get("observation"), "issue.observation")
    body = {"schema_version": "1.0", "kind": "design-review", "created_at": now(),
            "contract": contract, "task_binding": binding, "identity": identity(contract, root), "assessment": assessment,
            "contract_source": file_record(root, contract_path),
            "assessment_source": file_record(root, assessment_path),
            "unanchored_attested": not assessment["detector_seen"],
            "boundary": "Recorded reviewer attestation; ordering of these receipts does not authenticate independence or prove the model obeyed instructions."}
    if contract != read_json(local_path(root, contract_path)) or assessment != read_json(local_path(root, assessment_path)):
        raise ValueError("Design review input changed while recording the review")
    return save_receipt(root, output, body)


def current_review(root: Path, path: str) -> dict:
    review = verify_receipt(local_path(root, path), "design-review")
    if review.get("task_binding") != task_binding(review["contract"], root):
        raise ValueError("Design task acceptance contract changed; record a new review")
    for key in ("contract_source", "assessment_source"):
        if review[key] != file_record(root, review[key]["path"]):
            raise ValueError("Design review input changed; record a new review")
    if review["contract"] != read_json(local_path(root, review["contract_source"]["path"])) or review["assessment"] != read_json(local_path(root, review["assessment_source"]["path"])):
        raise ValueError("Review body differs from its recorded input files")
    if review["identity"] != identity(review["contract"], root):
        raise ValueError("Design review is stale: contract authority or target content changed; record a new review")
    return review


def audit_review(root: Path, review_path: str, output: str, *, timeout: int = 20) -> dict:
    review = current_review(root, review_path)
    result = audit(root, review["contract"]["targets"], timeout=timeout, review_sha256=review["receipt_sha256"])
    if result.get("identity_stable") is True:
        current_review(root, review_path)
    return save_receipt(root, output, result)


def report(root: Path, review_path: str, audit_path: str, verification_path: str, output: str) -> dict:
    review = current_review(root, review_path)
    scan = verify_receipt(local_path(root, audit_path), "design-audit")
    if scan.get("review_sha256") != review["receipt_sha256"] or scan.get("project") != str(root.resolve()):
        raise ValueError("Audit belongs to a different review or project")
    expected_sources = source_records(root, review["contract"]["targets"])
    if scan.get("sources") != expected_sources or scan["created_at"] < review["created_at"]:
        raise ValueError("Audit source or ordering mismatch")
    verification = read_json(local_path(root, verification_path))
    text(verification.get("reviewed_by"), "verification.reviewed_by")
    text(verification.get("baseline"), "baseline or explicit unavailable reason")
    records = verification.get("criteria")
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        raise ValueError("Verification criteria must be explicit records")
    by_id = {r.get("id"): r for r in records}
    expected_ids = {c["id"] for c in review["contract"]["criteria"]}
    if len(by_id) != len(records) or set(by_id) != expected_ids:
        raise ValueError("Verification must cover exactly the contract's criterion IDs")
    gaps, artifacts = [], []
    for criterion in review["contract"]["criteria"]:
        record = by_id[criterion["id"]]
        text(record.get("observed"), "observed outcome")
        if record.get("passed") is not True:
            gaps.append(f"{criterion['id']}: behavior not verified passing")
        checks = record.get("checks")
        if not isinstance(checks, dict) or any(checks.get(c) is not True for c in criterion["checks"]):
            gaps.append(f"{criterion['id']}: missing required check")
        evidence = record.get("artifacts")
        if not isinstance(evidence, list) or not evidence:
            gaps.append(f"{criterion['id']}: no local evidence")
            continue
        for item in evidence:
            if not isinstance(item, dict):
                raise ValueError("Artifact requires path and sha256")
            actual = file_record(root, item.get("path"))
            if item.get("sha256") != actual["sha256"]:
                raise ValueError("Verification artifact changed or was not content-pinned")
            artifacts.append(actual)
    # A scanner's success never closes an unresolved design or usability issue.
    resolutions = verification.get("issues", {})
    if not isinstance(resolutions, dict):
        raise ValueError("Issue dispositions must be an object")
    issue_ids = {item["id"] for item in review["assessment"]["issues"]}
    if set(resolutions) - issue_ids:
        raise ValueError("Unknown design issue disposition")
    for issue in review["assessment"]["issues"]:
        disposition = resolutions.get(issue["id"], {})
        if not isinstance(disposition, dict):
            raise ValueError("Issue disposition must be an object")
        status = disposition.get("status")
        if status not in ("verified", "accepted-minor") or not disposition.get("reason"):
            gaps.append(f"{issue['id']}: unresolved design issue")
        elif status == "accepted-minor" and issue["severity"] != "minor":
            gaps.append(f"{issue['id']}: required issue cannot be waived as minor")
    dispositions = verification.get("findings", {})
    if not isinstance(dispositions, dict):
        raise ValueError("Detector dispositions must be an object")
    finding_ids = {f["id"] for f in scan.get("findings", [])}
    if set(dispositions) - finding_ids:
        raise ValueError("Unknown detector finding disposition")
    for fid in finding_ids:
        item = dispositions.get(fid, {})
        if not isinstance(item, dict) or item.get("status") not in ("false-positive", "accepted-exception") or not item.get("reason"):
            gaps.append(f"{fid[:12]}: detector finding needs contextual review")
        elif item["status"] == "accepted-exception" and not item.get("authority"):
            gaps.append(f"{fid[:12]}: exception authority missing")
    if scan.get("status") != "completed":
        fallback = verification.get("scan_alternative", {})
        if review["contract"].get("detector_required") is True or not isinstance(fallback, dict) or not isinstance(fallback.get("reason"), str) or not fallback["reason"].strip() or not isinstance(fallback.get("artifacts"), list) or not fallback["artifacts"]:
            gaps.append(f"detector {scan.get('status', 'unknown')}; explicit alternate evidence required")
        else:
            for item in fallback["artifacts"]:
                if not isinstance(item, dict):
                    raise ValueError("Alternate scan evidence requires path and sha256")
                actual = file_record(root, item.get("path"))
                if item.get("sha256") != actual["sha256"]:
                    raise ValueError("Alternate scan evidence digest mismatch")
                artifacts.append(actual)
    # The report is a candidate for QA, never a tc verdict or completion command.
    body = {"schema_version": "1.0", "kind": "design-report", "created_at": now(),
            "task_id": review["contract"]["task_id"], "identity": review["identity"],
            "review_sha256": review["receipt_sha256"], "audit_sha256": scan["receipt_sha256"],
            "verification": verification, "verification_source": file_record(root, verification_path),
            "artifacts": artifacts, "ready_for_qa": not gaps, "gaps": gaps, "qa_approved": False,
            "detector_status": scan.get("status"),
            "boundary": "Structural readiness and reviewer attestations only. QA must verify artifact relevance and behavior and store its own task-bound verdict in tc."}
    current_review(root, review_path)
    return save_receipt(root, output, body)


def compare(root: Path, manifest_path: str, output: str) -> dict:
    """Package actual captures into a standalone reviewer; never grade pixel similarity."""
    manifest = read_json(local_path(root, manifest_path))
    for key in ("surface", "state", "theme"):
        text(manifest.get(key), key)
    viewport = manifest.get("viewport")
    if not isinstance(viewport, list) or len(viewport) != 2 or any(type(n) is not int or n < 1 or n > 16000 for n in viewport):
        raise ValueError("viewport must be [width, height]")
    captures = []
    for variant in ("baseline", "candidate"):
        item = manifest.get(variant)
        if not isinstance(item, dict):
            raise ValueError(f"{variant} capture metadata required")
        text(item.get("identity"), f"{variant}.identity")
        for key in ("viewport", "state", "theme"):
            if item.get(key) != manifest[key]:
                raise ValueError(f"{variant} {key} differs from comparison conditions")
        record = file_record(root, item.get("path"))
        if item.get("sha256") != record["sha256"]:
            raise ValueError(f"{variant} capture digest changed")
        body = read_bytes(local_path(root, item["path"]))
        if body[:8] != b"\x89PNG\r\n\x1a\n" or body[12:16] != b"IHDR" or len(body) < 33:
            raise ValueError("Comparison currently accepts PNG screenshots only")
        dimensions = list(struct.unpack(">II", body[16:24]))
        captures.append({"variant": variant, "record": record, "dimensions": dimensions, "identity": item["identity"],
                         "data": base64.b64encode(body).decode()})
    if captures[0]["dimensions"] != captures[1]["dimensions"]:
        raise ValueError("Capture pixel dimensions differ; recapture comparable states")
    title = html.escape(manifest["surface"])
    sections = "".join(f'<figure><figcaption><strong>{c["variant"].title()}</strong><br>{html.escape(c["identity"])}</figcaption><img alt="{c["variant"]} capture" src="data:image/png;base64,{c["data"]}"></figure>' for c in captures)
    page = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
<title>{title} — design comparison</title><style>body{{font:16px/1.5 system-ui;margin:2rem;color:#20242a;background:#fafaf8}}main{{display:grid;grid-template-columns:1fr 1fr;gap:1rem}}figure{{margin:0;min-width:0}}img{{width:100%;height:auto;border:1px solid #b9bdc4}}figcaption{{padding:1rem 0;overflow-wrap:anywhere}}@media(max-width:700px){{main{{grid-template-columns:1fr}}}}@media(prefers-color-scheme:dark){{body{{color:#f2f2ef;background:#181b20}}}}</style>
<h1>{title}</h1><p>{html.escape(manifest['state'])} · {html.escape(manifest['theme'])} · {viewport[0]} × {viewport[1]}</p>
<p>Inspect the task, hierarchy, content, and interaction evidence; this comparison does not grant QA approval.</p><main>{sections}</main></html>'''
    path = create_file(root, output, page)
    return {"kind": "design-comparison", "path": str(path), "sha256": hashlib.sha256(page.encode()).hexdigest(),
            "captures": [{k: v for k, v in c.items() if k != "data"} for c in captures], "qa_approved": False}
