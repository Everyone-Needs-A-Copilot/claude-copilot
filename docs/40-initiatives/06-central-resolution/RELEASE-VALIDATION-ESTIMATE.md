# Release-validation estimate evidence — 7 November 2026

**The available evidence supports seconds-scale observations for selected local controls, but no reliable total duration for end-to-end release validation yet.** The missing time is concentrated in identifiable stages: genuine release materialization and installation, four ordered Apple submissions, protected CI readiness and queues, final artifact preparation, and live activation/recovery. Neither the 120-minute CI timeouts nor the prior 136–155-second search processes are usable completion estimates.

This is an evidence-gathering result, not release acceptance. No tests, builds, fixes, installation, activation, authenticated service calls, publication, paid calls or task closure ran during this investigation. Existing unaffected passes are preserved. Source inspection and recovery of existing raw measurements were parallelized across three workers; this document has one convergence owner and an independent dependency reviewer.

## What can actually be timed from existing evidence

| Selected activity | Observed wall time | What it establishes |
|---|---:|---|
| cc packager source-authority defect plus two direct controls | 2.433 seconds total | Three private source-preflight cases; excludes download, binary build, signing and Apple |
| CT hosted source-authority defect plus two direct controls | 1.003 seconds total | Three private source/workflow guards; excludes actual hosted policy and packaging |
| Protected Knowledge revoked-entitlement control | 0.521 seconds | One corrected private organization fixture; excludes real entitlement service |
| Trust probe silent stub / responsive stub | 0.990 / 0.104 seconds | Demonstrates F4 timeout overrun with requested .05-second deadline; not real app-server latency |
| Historical CT User Swift compilation | 8.936–9.328 seconds | Two distinct-source local compilations; not final signed/notarized app |
| Historical CT Admin Swift compilation | 12.172–12.480 seconds | Same limitations; not a release build range |
| Historical compiled Swift → actual cc seam | 3.387 seconds | Local compile/driver and private project; not installed UI |
| Historical provider-free Codex hook probe | .928-second process, 28-millisecond hook | Release11 runtime; not final candidate activation |

These are observations, not percentiles or guaranteed upper bounds. They do not measure test authoring, fixture preparation, evidence review or fixes. The original five Knowledge-control run took 1.477 seconds but included one faulty-fixture failure; it is not five successful current controls. The corrected revocation result is separately recorded above. An earlier incorrectly configured hook probe ran 55.198 seconds before its deadline; preserve it as setup failure, not successful-runtime latency.

Raw measurement locations, identities and hashes: [timing evidence](/var/folders/h_/6c6hkvfn5hs2wx4yjw4pyknr0000gn/T/cr-release-estimate-timings-5an0l8p2/TIMING-EVIDENCE.md), with `source-hashes.json` beside it. Prior concurrent searches used shared HOME/configuration and uncontrolled caches, and weak assertions did not establish child exit-zero; all three search times are excluded from this estimate. No unaffected check was rerun merely to collect another duration.

## Actual critical path

The candidate has two related paths, with the same artifact identities required at their join:

1. **Release eligibility:** correct F1/F2/F4, and align F3's standalone publisher or explicitly exclude that entrypoint; identify changed code and exact affected retests. Fix effort remains outside this validation assignment.
2. **Artifact production:** final signed integrated cc source → protected CI/source authorization → universal cc build/download/sign/notarize → verified CT helper vendoring → final signed CT source → CT User app, Admin app and DMG packaging/notarization → artifact validation/promotion.
3. **Runtime consumption:** coherent final framework/tier pins and approved artifacts → release materialization and locked cc/tc environment → preflip real Codex trust → private pointer flip and links → real Codex cache refresh → doctor → launcher/hooks/Knowledge/CT consumers → upgrade/rollback and receipt reconciliation.
4. **Live proof:** independently checked remote policy and genuine Apple artifacts, authorized live activation and consumer/service checks, and actual 793-item receipt accounting including the three preserved owner items. Synthetic staging cannot attest to these machine/account-specific facts.

Direct source: Claude `tools/cc/src/cc/core/release/publish.py:185–247` orders build, trust preflight, pointer, links, Codex and doctor; `_restore` handles failure. `engine/build.py:248–269` builds the real environment with a 600-second subprocess ceiling. CT `scripts/release-local.sh:336–370` performs User app → Admin app → DMG Apple waits serially; prior cc helper notarization creates a fourth ordered wait. The three worker slots do not parallelize this entire spine.

The CT candidate's **tracked historical helper record**, `packaging/cc/NOTARIZATION.json`, records 2.12.7, while `controltower.compat.json` requires >=2.19.0,<3.0.0. This is an unsatisfied recorded artifact dependency, not a measurement of the installed app/helper. Helper replacement and provenance verification must precede final CT source/tag selection; the current candidate must not simply be assumed ready for unchanged packaging.

Source-backed external dependency details and line references: [dependency evidence](/private/tmp/cr-release-estimate-dependencies-20261107/EVIDENCE.md). GitHub access previously failed according to the brief; its present state was not probed and is therefore **unknown**, not proved broken. Credential provisioning is documented, but current validity was intentionally not checked. `RELEASE_CI_ENABLED`, actual protected-main/environment rules, runner availability and secret scope remain unverified.

## Minimum remaining measurements, in useful execution order

Each future check must state its precise question, selected command or reproducer, expected result and tested identity before execution. This table is a concrete measurement plan, not a claim these commands ran or authorization for blanket tests.

| Stage/question | Exact next measurement | Required output and boundary |
|---|---|---|
| Did a correction close F1/F2/F4 and the selected F3 route? | Retain the audit's `repro_rollback.py`, `repro_history.py`, `repro_timeout.py` and source-only CT `repro_ct.py`; select only failed cases and direct controls sharing changed code. | Per-case wall/CPU, exit/stdout/stderr and corrected commit. Requires separately assigned fixes and final affected-code scope; do not edit acceptance assertions. |
| How much genuine private materialization costs | A dedicated preserving harness calls candidate `build.build_release(sources, private_home, post_build=publisher.make_post_build(private_home, venv=True))` with exact verified local source pins and a private package cache. Record archive/materialization and locked-environment construction separately. | One isolated cold run then one explicitly warm run only if cold/warm distinction affects the estimate. No final candidate pins are invented; stubbed verifier/extractor or `venv=False` cannot count as genuine timing. Inspect installers for downloads, external calls and cleanup before execution. |
| Can the complete candidate activation path operate privately? | A dedicated harness calls `publisher.publish(..., home=private_home, codex_home=private_codex_home, control_tower_app=private_candidate_app, venv=True)` with real signer/extractor/Codex and an external watchdog; then exercise a selected rollback path and inspect pointer, cache, links and receipt. | Per-step timings and actual child executable/module identities. Private HOME alone is insufficient: CLI publish defaults CT to `/Applications/Copilot Control Tower.app` and exposes no CT override. Private app identity and frozen pins are prerequisites. F4 requires a watchdog even during measurement. No live config/cache/credentials or trust changes. |
| Which consumers resolve the candidate? | Capture private generated launcher `copilot --launcher-info`; one provider-free candidate hook event; one private project status/init seam; one successful structured Knowledge result plus selected protected-denial control. | Child realpaths/hashes, successful exit and parsed result, not import-only or substring proof. Exact checks selected by the affected consumer; do not rerun every consumer suite. Real entitlement service needs separately controlled identity. |
| What do hosted jobs really take? | After permitted authenticated read access, `gh run list --repo OWNER/REPO --workflow WORKFLOW --all --limit 10 --json databaseId,headSha,status,conclusion,createdAt,startedAt,updatedAt`; for relevant runs `gh api repos/OWNER/REPO/actions/runs/RUN_ID/jobs` and inspect step timestamps. | Separate queue, runner preparation, build and service waits; compare same workflow/toolchain/artifact shape. Inspect actual branch/environment rules separately. These are read-only remote operations but involve credentials excluded from this pass. No workflow dispatch or mutation needed to inspect history. |
| What is Apple's actual wait distribution? | Authorized read-only publisher history: `xcrun notarytool history --keychain-profile ct-notary --output-format json`, followed by `info SUBMISSION_ID` for relevant jobs and correlated local build logs. | Matched submission/start/completion timestamps for cc, CT User/Admin/DMG from correlated timestamped CI/build logs. Apple history/info may expose only createdDate/status; do not assume those responses contain completion timing. Accepted IDs without timestamps cannot establish duration. Credential access and Apple contact were excluded here; no new submission for estimation alone. |
| What remains when staging succeeds? | Prepare exact live activation, receipt reconciliation and rollback commands against the frozen artifacts, then obtain scoped live-operation authority before running. | Start/end timing, actual 793-item accounting with owner preserves, runtime identity and bounded recovery result. Cannot extrapolate a synthetic receipt into a live pass. |

The genuine materialization/activation pilot is the most useful missing **local** measurement. Another source-guard unit-test rerun would add seconds-scale data without addressing the dominant unknowns. A synthetic-key/private-app pilot can estimate local mechanics sooner if the real candidate artifacts are unavailable, but its result must stay labeled synthetic and cannot time real signing/notarization or approve release identity.

Existing `release_codex/test_publish.py:44–60` replaces the verifier, extractor, hook lister, app and Codex and sets `venv=False`; its speed does not measure the preceding genuine path. `release_pointer/conftest.py:25–35` removes temporary fixture trees automatically. Use a dedicated evidence-preserving harness before timing those boundaries under this assignment's no-deletion constraint; do not silently rewrite tests or weaken their assertions.

## How the estimate will be calculated

Keep four separate quantities:

- **Measured check execution:** current evidence supports only the observations above. Reuse unaffected accepted results; selected retests belong only to changed paths.
- **Preparation and analysis:** private harness construction, artifact/source binding, result interpretation and independent challenge have no measured distribution here. Do not disguise them as a multiplier on test seconds.
- **Fix work:** independently scoped after implementation ownership/route is decided; excluded from validation-only timing.
- **External waits:** protected-branch approvals, CI queue, Apple response, artifact availability and owner-authorized live windows are not presently bounded.

Once representative stage timings exist, use:

`elapsed = serial setup + critical path of ready validation lanes within 3 worker slots + serialized artifact/activation work + convergence + external waits`

Do not divide total work by three, add all timeout caps, or extrapolate the slow concurrent search record. The 120-minute job caps, 600-second environment-build cap and 300-second Codex-command caps are failure limits, not expected durations; the nominal trust timeout is additionally defective. A reliable local-validation range needs the private genuine pilot and a frozen check inventory. A reliable full completion range additionally needs source/fix readiness and historical or observed external service timings; until those exist the upper bound remains unknown.

## Source, operating framework and preservation

Re-read candidate protocol/QA/verification guidance in `/Volumes/Dev/Sites/CSE/.worktrees/cr-codex-central/skills/`, organization `parallel-execution` and `blast-radius-qa` in `/Volumes/Dev/Sites/CSE/.worktrees/internal-blast-radius-qa/skills/`, applicable AGENTS and lifecycle guidance. The owner's selected-check scope overrides generic full-regression defaults; the explicit request for an estimate overrides generic advice to omit time estimates. Native parallel delegation was active; no new candidate runtime, cycle enforcement, plugin activation or service capability is claimed from reading instructions.

`/usr/bin/git` and `/opt/homebrew/bin/rg` were used for read-only inspection. Installed `gh run list --help` was read locally to verify the proposed fields/flags; no authenticated GitHub command ran. The dependency reviewer independently challenged this report; corrections distinguish observations from estimates and require timestamped logs for Apple completion timing. All six candidate HEADs were freshly rechecked and still match the audit: Claude `ee616244469678596c9f896b30fe517ed28abeb9`; Codex `c6e2992db227b63c0df7e1b4f05f52a2ba2b7675`; CLI `39085c8fbd6eac5b4d5f8ac59d7522017a73817a`; CT `2573497788ecdc34f81c6c4b6999baeb41693c35`; organization `6a176b889043a2342ee907a31b5bb21073a71153`; Knowledge `cb6c9c3e54a7dfcb648b9f57ea002e8425c2a9de`. Full comparison bases and runtime provenance remain in the adjacent audit. Existing modified README, untracked brief and audit were preserved. Other five candidate trees were clean when rechecked. Worktrees and temporary evidence are held for the owner; no cleanup or task closure is implied.

**Recommendation:** continue with the isolated genuine-path measurement once its exact private inputs and preservation harness are ready, while obtaining only the permitted external-history reads needed to estimate service waits. Keep release readiness held on the audit findings and unproven live boundaries. This report closes estimation discovery, not validation, repair or release.
