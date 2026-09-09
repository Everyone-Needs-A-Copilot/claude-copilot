# Opt-in pilot handoff

These are deliberately separate from foundation acceptance. Do not start them
automatically when the foundation batch finishes. Each pilot needs its named
inputs and a new bounded execution decision; no paid or hosted service is assumed.

## One visible UI defect — existing TASK-65

Required inputs: application checkout, known defect, local test command and URL,
safe seeded data/reset, supported browser, and the expected semantic result.

1. Register a source-bound acceptance criterion for the real user behavior.
2. Reproduce on the original source. Capture the first divergent state, not only
   a screenshot of the symptom. Save a persistent Playwright regression with a
   semantic assertion (for example exact returned IDs, not only item count).
3. Use the same seed, viewport, authentication state and assertion before/after.
   For this one reproduction use trace/video on both runs and disable retries.
   Use the application's installed Playwright API and existing reset authority.
4. Fix the responsible behavior and rerun the affected scenario. In a disposable
   copy, reintroduce the original defect and require the same assertion to fail.
5. Record source/data/runtime identities and local trace/video paths in `tc`.
   Review actual behavior; a playable recording does not grant approval. Close
   when the criterion passes and the negative control fails as expected, then stop.

No default upload or public recording. Redact synthetic accounts and keep media
in an ignored, owner-controlled local folder; follow the application's retention
policy. Do not install a cloud recorder without an explicit destination decision.

## Source-backed visual alternatives — existing `cc design`

Name one application surface and its actual product/design authority. Use
`cc design template` and `cc design context` to bind criteria and source targets.
Prepare two defensible alternatives under the same content/state constraints;
record which authority supports the differences. Use `cc design compare` with
real comparable captures, not invented screenshots or scores. The owner chooses
the trade-off. Implement that choice and record initial critique with
`cc design review` before optional detector output from `cc design audit`.
`cc design report` checks evidence readiness; the existing `tc` QA gate approves.
Stop after the selected surface meets its criteria, not after a perfect score.

See [design quality operation](../../../30-operations/10-design-quality.md) if
available in the consumer's adopted documentation; otherwise use `cc design guide`
and the native design-quality guide shipped with Codex Copilot.

## One inspectable personal rule — existing private taste owner

Use only an owner-selected real feedback source. Do not mine history or make up a
candidate. Keep minimized source, exact quote, line range, hash and session identity
in the private knowledge repository; foundation repositories receive no private
quotes or inferred preferences.

Use that repository's `scripts/taste propose --receipt ...` and `scripts/taste list`
to inspect the candidate. Record the owner's approve or reject decision explicitly.
Rejection leaves the candidate inactive, with the decision recorded; do not invent
a `reject` command. Promotion uses existing `promote --approved-by ... --approval
...` after receipt, independent-observation and conflict checks. A verified explicit
standing instruction can use the existing approved `--force` path; silence is not
approval. Use `retire --why ...` when a real rule should no longer apply.

Check applicability from the generated private `08-taste/INDEX.md`; project
requirements outrank personal rules. Evaluate benefit on held-out work not used
to learn the rule. Stop after the one candidate's reviewed disposition and one
bounded trial; do not automatically collect or promote further candidates.

## Matched adoption measurement — existing TASK-66

Freeze one instruction change, one shared-code defect and one UI defect before
running baseline/candidate pairs. Keep model, effort, source inputs, runtime,
tools, acceptance and seed constant; vary one intervention. Include failed,
incomplete and reopened cases. Freeze replicate count and thresholds up front.

Reuse `cc eval adoption-freeze <plan.json> --output <frozen.json>` and
`cc eval adoption-check <frozen.json> <observations.json>` for supported held-out
identity/quality gates. These commands do not dispatch models or collect timing,
and their current schema is not a performance dashboard. Retain linked timing
observations separately: median/tail verification cycle, test execution, agent
work, repeated checks, actual owner interventions, defects/false positives and
rework. Record available real token snapshots; missing values remain unknown.
Do not sum overlapping parallel durations or equate an API estimate with billing.

The prior 30% median reduction is a target, not a measured outcome. Review the
frozen sample once; adopt, reject or report inconclusive, then stop. A small pilot
cannot establish an ecosystem-wide defect-rate improvement.
