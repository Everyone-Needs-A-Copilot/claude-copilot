# Evidence and adoption

Implementation authority: codex-copilot PRD-9 / TASK-11–15. This guide covers shared
`cc` commands consumed by both frameworks. Native `qa` instructions define the
delivery evidence packet; the task-bound `ARTIFACT:` and `VERDICT:` gate remains.

## Frozen pilot contract

Keep `plan.json`, `frozen.json`, task inputs and observation artifacts in one pilot
directory. Paths below are relative to that directory; outside paths are refused.
Before freezing, replace every placeholder with the actual controlled identity.
Use SHA256 digests for runtime/tool configuration and immutable framework/rule
content hashes. Do not use `current`, `latest` or a mutable branch name as a pin.

```json
{
  "schema_version": "1.0",
  "learning_source_ids": [],
  "replicates": 2,
  "cases": [{"id": "case-1", "source_id": "held-out-1", "brief": "brief.md", "rubric": "rubric.md"}],
  "controls": {
    "model": "<exact model>", "effort": "<same effort>",
    "runtime": "codex", "runtime_version": "<installed version>",
    "runtime_configuration": "<64 hex characters>",
    "tools_configuration": "<64 hex characters>"
  },
  "variants": {
    "baseline": {"framework_revision": "<content hash>", "rules_revision": "<content hash>"},
    "candidate": {"framework_revision": "<content hash>", "rules_revision": "<content hash>"}
  },
  "thresholds": {
    "min_pairs": 2, "min_distinct_cases": 1,
    "max_context_ratio": 1.1, "max_call_ratio": 1.1,
    "min_rework_reduction": 0.1
  }
}
```

That minimal shape illustrates the API; the CSE outcome pilot uses six distinct
cases, two repetitions and twelve complete pairs. Freeze a rubric that records
correctness, required clarification and abstention as separate booleans; if a
behavior is inapplicable, its rubric must explain what counts as satisfied.
Measure `human_rework` as reviewed corrective edits and `misapplied_rules` as
observed rule corrections; never substitute untouched-file percentages.

The observation file is a JSON array. Each trial supplies:

```json
{
  "case_id": "case-1", "replicate": 1, "variant": "baseline", "status": "valid",
  "freeze_sha256": "<from frozen receipt>",
  "controls": {"<all fields>": "<exact frozen controls object>"},
  "content": {"framework_revision": "<hash>", "rules_revision": "<hash>"},
  "observed_at": "<ISO timestamp after freeze>", "reviewed_by": "<owner/reviewer>",
  "evidence": {"path": "runs/case-1-baseline-1.json", "sha256": "<file digest>"},
  "metrics": {
    "correct": true, "necessary_clarification": true, "appropriate_abstention": true,
    "misapplied_rules": 0, "human_rework": 2, "context_characters": 1000,
    "calls": 4, "unauthorized_effects": 0
  }
}
```

Invalid trials and baseline failures use a non-valid `status` and explicit `reason`;
they are reported separately and cannot create a supportive pilot signal. Every
planned pair/replicate must be present. Changed task/rubric, controls, evidence,
duplicate rows, reused artifacts, overlap with learning sources, insufficient data,
regressions or missing rework improvement retain the baseline or reject the input.
A supportive signal is an initial owner-reviewed observation, not a release verdict.

## Runtime and context limits

Use `cc skill select --json` for optional loading; preserve mandatory constraints
outside the skill catalog. Use `cc doctor --runtime-details --json` for local
source/config identity and `--exercise-runtime` only when direct diagnostic execution
is intended. A passing direct probe leaves runtime trust and dispatch unknown.
An actual runtime-origin event or existing verifier-issued evaluation record is
needed to claim enforcement. Keep these reports in the task work product once.
