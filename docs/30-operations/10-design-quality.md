# Design quality in Claude Copilot and Codex Copilot

Use `cc design` for task-scoped design guidance and review evidence. The existing
specialist chain and `tc` QA gate remain authoritative. Implementation tasks require
`metadata.requiresQa=true`; **tc 1.4.0** supplies the completion predicate. Requires shared **cc
2.12.16**; use `$HOME/.local/bin/cc` if `cc` resolves to the system C compiler.

## Start from the surface

Choose the job of the surface: persuade, operate, read or experience. Preserve
existing product facts and design authority. Name the material states and observable
acceptance criteria before implementation; keep the existing UX/UI walkthroughs.

```bash
tc task get 42 --json
cc design guide --json
cc design template --output design/contract.json --json
```

Edit the draft before using it. A minimal complete contract looks like this:

```json
{
  "schema_version": "1.0",
  "task_id": 42,
  "surface": {
    "name": "Draft editor", "target": "/drafts/new", "mode": "operate",
    "job": "Save a draft and recover from a failed save", "change": "refine"
  },
  "authority": {"product": ["SOUL.md"], "design": ["DESIGN.md"]},
  "targets": ["src/DraftEditor.tsx"],
  "states": ["default", "saving", "saved", "save-error"],
  "criteria": [{
    "id": "C1", "expected": "A keyboard user can retry a failed save without losing entered content",
    "checks": ["behavior", "keyboard", "visual", "responsive"]
  }]
}
```

Files must remain inside the project and cannot use symlink aliases. Product and
design authority must exist. Context can name planned target files; review/audit
requires actual files. Task IDs are local to a project database: verify membership
with `tc task get` in the same project. Review and report bind the design criteria
to that database task’s registered acceptance contract and require its source scope
to cover every target and authority file. `detector_required: true` explicitly disallows replacing
an unavailable scan with manual evidence. Its default is false.

```bash
cc design context --contract design/contract.json --action shape --max-chars 12000 --json
cc design guide typeset --json
```

Context output records loaded/excluded authority, source hashes and character
counts. The contract is preserved even when it exceeds the budget. Read omitted
authority before editing; a selection receipt does not prove model consumption.
Guidance actions return a focused playbook for the specialist to apply, not an
unreviewed automatic source rewrite.

## Review before the detector

Inspect the implemented surface and record an initial `assessment.json`:

```json
{
  "judgment": "The save path is clear; recovery needs verification.",
  "method": "sequential", "reviewed_by": "Named reviewer or main-session role",
  "detector_seen": false,
  "issues": [{"id": "I1", "severity": "blocking", "observation": "Verify retry preserves content"}]
}
```

Use `issues: []` only when the initial review found none. Severities are blocking,
minor or question. An independent method additionally requires
`independence_evidence`; this remains reviewer attestation, not authentication.

```bash
cc design review --contract design/contract.json --assessment design/assessment.json --output design/review-1.json --json
cc design tool install --json
cc design tool status --json
cc design audit --review design/review-1.json --output design/audit-1.json --json
```

Install is an explicit network operation to a packaged, pinned release. It never
runs from a hook or audit. A separately verified executable can be registered with
`cc design tool register <binary> --sha256 <digest> --version <engine-version>
--source <provenance> --json`. A different existing pin requires explicit
`--replace`; the prior registry is backed up. A downloading launcher is not a pin.

The scan is local/static, with project and inline suppressions and automatic
DESIGN.md loading disabled; CSE applies the contract's design authority in review.
HTML scans include linked local stylesheet identities. Remote styles and executed
JavaScript are not inspected; root-relative stylesheet resolution is not guessed.
Native SwiftUI requires actual native inspection. Operational failure or unsupported
targets remain unavailable/incomplete evidence. Raw upstream exit 2 means findings;
`cc design audit` exits 0 for a completed scan, 1 for unavailable/incomplete/failed
evidence and 2 for invalid command input. Completion never means design approval.

## Verify and hand off to QA

Capture real rendered states and exercise behavior, keyboard use, responsive
layout, contrast and motion as required by the contract. Supported check names
are visual, behavior, keyboard, responsive, contrast, motion, content and localization.
Verification requires one record for every criterion:

```json
{
  "reviewed_by": "Named QA reviewer",
  "baseline": "Previous source/runtime identity, or a precise unavailable reason",
  "criteria": [{
    "id": "C1", "observed": "Retry retained the entered draft after the injected failure",
    "passed": true,
    "checks": {"behavior": true, "keyboard": true, "visual": true, "responsive": true},
    "artifacts": [{"path": "design/browser-run.json", "sha256": "REPLACE_WITH_ACTUAL_SHA256"}]
  }],
  "issues": {"I1": {"status": "verified", "reason": "Recorded retry check retained content"}},
  "findings": {}
}
```

Hash actual local artifacts; do not copy the placeholder. Record every detector
finding by its returned ID as `false-positive` with reason, or
`accepted-exception` with reason and authority. Required defects must be fixed and
rescanned. Only minor initial issues may be `accepted-minor`. Missing verification,
unresolved issues and stale artifacts prevent structural readiness.

When an optional detector is unavailable, add `scan_alternative` containing a
specific `reason` and local hashed `artifacts` for the alternate inspection. The
report retains the unavailable status. Native inspection is valid alternate
evidence; pretending a Swift file passed a web detector is not.

```bash
cc design report --review design/review-1.json --audit design/audit-1.json --verification design/verification.json --output design/report-1.json --json
```

The output says `ready_for_qa`, never `qa_approved: true`. QA must inspect artifact
relevance and behavioral truth, store its own task-bound `test` WP with an
`ARTIFACT:` and supported `VERDICT:`, and run the existing QA gate. Changes to
sources, linked stylesheets, authority or review inputs require a fresh review,
scan and affected checks. Output artifacts are created exclusively: choose a new
filename instead of overwriting earlier evidence.

## Compare actual captures

```bash
cc design guide compare --json
cc design compare design/captures.json --output design/comparison.html --json
```

The manifest names `surface`, `state`, `theme`, and `viewport: [width,height]`.
Both `baseline` and `candidate` contain actual local PNG `path`, `sha256`, a
source/runtime `identity`, and matching state/theme/viewport. Pixel dimensions
must match. Output is a self-contained offline side-by-side reviewer, with no
quality score or automatic acceptance. Use `cc design guide live` for optional
external live-tool setup, source ownership, bounded iteration and cleanup. No
server, provider, browser security exception or production injection starts implicitly.

## Enable native edit feedback

```bash
cc design feedback-config --runtime claude --enable --json
cc design feedback-config --runtime codex --enable --json
```

This requires an already pinned detector, preserves existing hook settings and
enables `.copilot/design-feedback.json` separately per runtime. Claude registration
uses `.claude/settings.local.json`; Codex uses `.codex/hooks.json`, with an optional
plugin wrapper also shipped. Equivalent repeated events deduplicate by session,
source/dependency content and binary pin. Edit/Write/MultiEdit and Codex apply_patch
are covered; shell-written files still need the explicit QA scan. No hook changes
task state. Reload the native session and verify real event dispatch; a manifest
entry or successful event replay alone does not prove runtime activation.

```bash
cc design feedback-config --runtime codex --disable --json
```

Disable is scoped to that runtime and preserves unrelated hooks. Set
`CC_DESIGN_FEEDBACK=off` for a session-wide emergency bypass. The explicit review
and QA path remains available. When cc is available, missing detectors or malformed/oversized events emit a
bounded reminder rather than approval; an unavailable cc cannot run the adapter.
Feedback never downloads a replacement.

## Programmatic use

`cc.api.design_guide(action)`, `cc.api.design_context(project=Path(...),
contract="...", action="shape", max_chars=12000)` and
`cc.api.design_audit(project=Path(...), targets=[...], timeout=20)` return the same
core data as the CLI. Keep `cc.api` and `tc.api` batches in separate processes.
Guides and release pin manifests ship as package resources in the cc wheel.


## Acceptance binding for current reviews

Before `cc design review`, register the named task's tc v2 acceptance contract
with `tc task contract ID --file acceptance.json`. Its criterion IDs and expected
behaviors must match the design contract; its source scopes must include every
target and product/design authority. A positive task number alone is insufficient.

Capture `tc task evidence-identity ID` before verification, preserve that exact
line, and compare a second capture afterwards. Store generated artifacts outside
the registered source scopes. The tc completion authority checks current content
again; the design report still only indicates readiness for QA.

Old saved design reviews lack database/acceptance binding and must be recreated
for current work. Historical QA records remain readable with their original scope.
