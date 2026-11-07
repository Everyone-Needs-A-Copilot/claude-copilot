# Developer review: central resolution framework update

Review snapshot: 7 November 2026. Owner: Pablo Alejo. Initiative: PRD-16.

**Review the candidate for security, efficiency and performance before release. Latest targeted records report 15 passing checks (six recorded failures and nine specific controls), with the search-evidence limits below; release #12 has not been built and activated.** This document requests an independent developer assessment, not authorization to publish or a claim that the complete handoff is finished.

## 1. Outcome and scope

The update replaces framework copies and checksum locks in each project with one machine-level release pointer. Claude Code and Codex consume a common release; projects retain their own instructions, memory, tasks, owned capabilities and a thin marker. A machine install becomes a prerequisite: clone-and-go behavior on a machine without the CSE is intentionally given up.

Read [ADR-001](decisions/ADR-001-central-release-pointer.md), the [machine install guide](../../01-getting-started/03-machine-install.md), and [architecture principles](../../01-architecture/12-architecture-guiding-principles.md) first. The ADR is accepted. Older initiative frontmatter and original handoff statuses may describe an earlier checkpoint; the source identities below define this review.

Major changes to assess:

- Immutable signed company-tier releases under ~/.copilot/releases, with atomic selection through ~/.copilot/current; personal tiers remain live links by accepted design.
- Receipt-owned per-item links, one Codex marketplace and a frozen plugin core whose stable dispatchers reach release-selected hook logic.
- Marker-gated framework hooks, with global coordinator guards kept separate from marker gating.
- Thin, explicit project initialization and read-only status. Control Tower uses the same status contract and calls project init as the single writer.
- One-time migration: identify distributed framework capabilities, preserve project-owned or modified content, and retire the old project reconciliation/lock model.
- Authenticated Knowledge reads from a frozen active release, retaining signed source authority, protected caching and entitlement revocation.
- Signed/notarized publishing paths that authorize source before candidate execution or credentials.

The Claude range alone is 426 changed files, 19,030 insertions and 117,001 deletions as measured below. Representative retirement groups include conformance implementation (30 files / 16,117 deletions), conformance tests/baselines (28 / 32,283, including 20,057 lines in one JSON baseline), and embedded Codex assets (106 / 8,222). Other ecosystem and cc-test groups mix additions with removals. No Claude renames were detected in this comparison. Much of the total is therefore old implementations, tests and data rather than new executable behavior. That is a review-scope observation, not evidence that every removal is safe. Review retirement-to-replacement coverage and recovery explicitly.

## 2. Exact source identities and comparison ranges

These are local candidate commits. Do not assume they are available from origin or final release tags. Obtain the candidate branches or a Git bundle from the author if necessary; this review document does not push them. Comparison bases are the observed merge bases with each local origin/main, not assertions about the current remote server.

| Repository / candidate branch | Comparison base | Candidate commit |
|---|---|---|
| claude-copilot / integration/central-resolution | e4578de8f1269d5968356008b0db535cf7ada1f2 | ee616244469678596c9f896b30fe517ed28abeb9 |
| codex-copilot / feat/central-resolution | 2c1b67e26de5d3e33cb433ccc98f70f13e0b5108 | c6e2992db227b63c0df7e1b4f05f52a2ba2b7675 |
| cli-copilot / feat/central-resolution | d927d6c5925850897c7bbe3e1decc2c40fce9f1a | 39085c8fbd6eac5b4d5f8ac59d7522017a73817a |
| copilot-control-tower / feat/central-resolution | f45b3253e184909bc7ee99d4a147202ed1ff2ad9 | 2573497788ecdc34f81c6c4b6999baeb41693c35 |
| claude-copilot-internal / docs/blast-radius-qa | 84f4bcef8aec11a72766e5dc4a342520a02355e8 | 6a176b889043a2342ee907a31b5bb21073a71153 |
| knowledge-copilot-internal / docs/blast-radius-qa | c2f043f7d5bfbf813c70305240f7ddc104e8005f | cb6c9c3e54a7dfcb648b9f57ea002e8425c2a9de |

Origins are repositories with those names under https://github.com/Everyone-Needs-A-Copilot/. The organization Claude checkout currently uses the equivalent github-work SSH host alias. Verify repository identity before applying a range; use the configured authorized SSH identity for private organization repositories.

Useful review-only commands, substituting local checkout paths:

~~~sh
CLAUDE_REPO=/path/to/claude-copilot
git -C "$CLAUDE_REPO" show --show-signature --stat ee616244469678596c9f896b30fe517ed28abeb9
git -C "$CLAUDE_REPO" diff --find-renames --stat e4578de8f1269d5968356008b0db535cf7ada1f2...ee616244469678596c9f896b30fe517ed28abeb9
git -C "$CLAUDE_REPO" diff --find-renames --name-status e4578de8f1269d5968356008b0db535cf7ada1f2...ee616244469678596c9f896b30fe517ed28abeb9
~~~

Use each row's own base/head for the other repositories. Do not compare the feature tree only with the deployed release: that would hide the earlier central-resolution implementation. The narrower Claude post-release-11 range is e1a975e57fbb1a05a1ec466ddb0fb50458274513..ee616244469678596c9f896b30fe517ed28abeb9.

### Deployed baseline is different

The active local pointer was read as release #11, 20261107T111725Z-e1a975e57fbb. Its main components remain Claude v5.35.0-rc11 at e1a975e5, Codex v0.17.0-rc4 at 89694771, CLI v0.3.14-rc3 at 32488d4d, product-creation v0.0.0-rc1 at 67ecf855, and a Control Tower v0.6.11 version record. Candidate Control Tower is 0.7.0/build 39; its candidate code is not established as the installed app.

Signed tier pins observed in that active manifest:

| Tier component | Ref | Commit |
|---|---|---|
| knowledge/foundation | v0.1.8 | e200afb17a86c8bb45c76ca590f1dd41349116db |
| knowledge/organization | v1.10.3-rc3 | cb6c9c3e54a7dfcb648b9f57ea002e8425c2a9de |
| knowledge/department-accounting | v1.0.6 | 2309b57187c916601a98fab919d3e22527e4fd08 |
| claude/organization | v1.11.11-rc3 | 6a176b889043a2342ee907a31b5bb21073a71153 |
| claude/department-accounting | v1.0.8 | d7d8284befe31f173511bbc7484ae2e91aa58981 |
| codex/organization | v1.8.3 | f8922b2a033897757cdc6f8a3cc9901c2c668a2e |
| codex/department-accounting | v1.0.5 | 8377a4d38abd2f668897b34ebc41ad2de2d4e8bb |
| cli/organization | v0.1.18 | b2d3b4987d567aa1b772f68d8bd6be16ff93fdb6 |
| cli/department-accounting | v1.0.5 | 8f64cdeb5a20dd8c7f7a353b7f57545ad7dd7fc2 |

Personal Knowledge/Claude/Codex/CLI entries are live-link main entries, not immutable signed pins. The raw machine layer file was previously found behind intended RC pins; reconcile the final release input with the intended component table rather than silently downgrading. No release #12 tag, manifest or artifact should be inferred from this table.

## 3. Architecture and source reading map

~~~mermaid
flowchart LR
    A[Configured repository identity] --> B[Allowed signer and signed Git object]
    C[Active release receipt] --> D[Canonical managed snapshot]
    B --> E[Exact frozen skill-tree comparison]
    D --> E
    E --> F[Existing private/public cache pipeline]
    F --> G[Entitlement lease on protected reads]
    G --> H[Skill content]
    I[Protected workflow revision] --> J[Trusted verifier and signing roots]
    J --> K[Authorize exact tag, commit and main ancestry]
    K --> L[Candidate execution and credential stage]
~~~

The receipt selects a version; it is not a trust root. The existing Git authoring verifier remains the fallback when no matching central release applies. A matching but invalid central component must fail closed rather than fall back to permissive authoring content.

Paths below are relative to the named repository. Start with these entry points and follow their dependencies; this is a reading map, not an assertion that unlisted paths are irrelevant.

| Area | Entry points |
|---|---|
| Claude release engine | tools/cc/src/cc/core/release/engine/{build,pointer,schema,layout,doctor}.py; core/release/publish.py |
| Link ownership and precedence | tools/cc/src/cc/core/release/links/{plan,adopt,apply}.py |
| Codex cache and frozen trust | tools/cc/src/cc/core/release/codex/{marketplace,step,trust_gate,config}.py; Codex templates/central-hooks and frozen plugin hooks |
| Project API / state preservation | tools/cc/src/cc/commands/project.py; core/project_init/{init,status,registry,codex_trust,sections,packs}.py |
| Migration / source ownership | tools/cc/src/cc/core/project_migrate/{framework_index,source_guard,planner,apply,rollback,scan}.py |
| Knowledge trust / leases | tools/cc/src/cc/core/ecosystem/knowledge_release_source.py; knowledge_skill_source.py; policy.py; entitlement.py |
| Hook dispatch | .claude/hooks/copilot-hook.sh and coordinator-guard.sh; Codex templates/central-hooks and hooks/hooks.json |
| Claude publishing | .github/workflows/cc-macos-release.yml; scripts/package-cc-macos-release.sh; scripts/verify-foundation-release.sh |
| Control Tower runtime | native/cli-client.swift (projectStatus / initializeProject); cli-dtos.swift (CentralProjectStatusReport / renderer); tray and wizard CentralProjectsView callers |
| Control Tower publishing | .github/workflows/release.yml; .github/scripts/verify-release-source.sh; scripts/release-local.sh; ADR-012 publishing documentation |
| CLI launch / version declarations | cli-copilot copilot_cli/launcher_install.py and installer; VERSION.json and generated Claude CLI reference |

## 4. Security review: release-blocking questions

The two verifier issues below were demonstrated with private fixtures, corrected, then passed their exact targeted retests. Other rows are review questions, not newly observed vulnerabilities.

| Priority | Boundary / question | What evidence should support approval? |
|---|---|---|
| Blocker until independently reviewed | Candidate code must not select its verifier or signing roots. CT previously accepted a no-op verifier from an unsigned candidate; the standalone cc packager independently did the same. | Trace workflow checkout to GitHub's workflow revision, executable protected-main guards, exact ref/SHA/ancestry/signature verification and credential ordering. For the standalone path, verify caller-owned verifier, no-checkout clone and disabled hooks before authorization. Candidate-supplied signer files or environment overrides must not become authority. |
| Blocker before CI enablement | Workflow code guards are not environment secret-access policy. | Inspect actual release-environment deployment rules, protected-main/ruleset settings, secret scope and required approvals after GitHub access is restored. Local tests cannot attest to remote settings. |
| High | Active Knowledge receipt, source identity, signed object and content must agree. | Review canonical release-parent containment, no-follow file reads, owner/mode/link-count checks, receipt consistency, repository-origin binding, commit/signer agreement, exact file/directory sets and detection of pointer/receipt changes during resolution. Examine remaining race windows; do not assume mode bits make user-owned files unchangeable. |
| High | Authentication and entitlement are separate decisions. | Follow the verified snapshot into the existing cache and protected read lease. Public foundation reads need no organization entitlement; organization/department reads must reject revoked authority even with a warm cache. Check that signed-source selection never drops a binding or turns a matching failure into unsigned compatibility. |
| High | Initialization and migration must preserve owner decisions and recovery. | Corrupt registry or explicit Codex distrust must block before project writes. Inspect partial-write/race handling, symlink/path boundaries, dirty-copy holds, source-repository exemptions, exact originals and rollback fidelity. Migration history matching must identify deployed capabilities, not any product file that once shared a basename/blob. |
| High | One pointer changes every consumer at once. | Inspect flip/rollback locking and failure ordering across links, marketplace refresh and doctor; confirm that receipt-owned links cannot discard owner items. Verify cache invalidation, frozen plugin trust and required-project failure behavior. |
| Medium | Retired implementations and tests must have a contract disposition. | Map removed APIs/tests/assets to replacement behavior or accepted retirement. Inspect preserved CT test/source archives and fleet migration receipts. Confirm who authorized destructive changes and what restores each changed project; do not treat a large deletion count as proof of wrongdoing or safety. |

Standalone signer configuration also needs an explicit decision: scripts/verify-foundation-release.sh:70–83 permits FOUNDATION_RELEASE_PRINCIPAL and FOUNDATION_RELEASE_PUBLIC_KEY to replace the default list, while CI clears them. Review the trusted local-caller override contract and the comment that calls this a narrowing operation; do not assume candidate substitution remains possible after the fix. This is observed configurability, not a new demonstrated exploit.

Review personal-tier mutability as an explicit trust exception. Also inspect source-repository hooks versus consumer hooks: coordinator guards are global, while framework execution is marker-gated. A missing marker, a duplicate legacy registration, a disabled-hook marker and a required-project marker must have distinct intended behavior.

## 5. Efficiency review

Assess whether removing per-project propagation reduces the actual maintenance and execution cost, without moving that cost to every read:

- Trace scoped project status: it should inspect one requested folder, not perform a hidden home/fleet census. The --all path combines registered projects with approved roots, depth three, excluding linked roots. Check repeated registry/trust parsing and repeated status calls after an explicit initialization.
- Inspect release build/materialization, link-plan calculation, Codex refresh and migration history indexing for redundant Git subprocesses, duplicate full-tree reads or unnecessary copies. Verify any cache key includes the authority/ref/tree/entitlement inputs it depends on.
- Review the lifecycle of cached signed snapshots, release history, preservation archives and generated artifacts. Space reclamation must remain receipt-scoped and separately authorized; logical retirement does not establish deletion permission.
- Review Control Tower refresh fan-out, initialization re-entry guards, subprocess lifetime/cancellation and background cadence. A successful init is followed by fresh scoped status; UI readiness must not be fabricated from an earlier response.
- Check parser/reference reproducibility. The first generation used installed Typer 0.28 and produced a large formatting diff; the corrected shipping lock pins Typer 0.26.8, Rich 15.0.0 and Click 8.4.2. The local-package lock version was corrected from 2.18.0 to 2.19.0 without third-party upgrades. Verify generated reference against that lock, not global packages.

## 6. Performance review and measurement limits

**Observed:** three individually selected search pytest processes took 146.026 s (testing/pytest), 155.331 s (JavaScript) and 136.257 s (Docker). Security search passed in an earlier four-node batch; the batch's 60 s cap interrupted the remaining work. Subsequent per-case runs passed with a 180 s cap. These are whole test-process elapsed times in the real machine's live configuration, not isolated cc-command timings or a controlled benchmark. The active pointer alone does not establish the child implementation; runtime.json separately records the expected private-environment ccBinary and candidate PYTHONPATH, without a child-process identity attestation. Artifact timestamps and adjacent PIDs show the three single-test processes started concurrently with a common HOME and live configuration. Cache/lock contention is possible but was not measured; cold/warm state and subprocess cost were not profiled. Do not label the measurements an established per-query latency regression or normal expected latency.

The original release-11 handoff reports project init at approximately 0.35 s and an under-10-second requirement (ADR target 1–2 s). That older observation does not establish current-candidate latency across project shapes.

Suggested focused performance questions for the reviewer, with no benchmark run implied by this document:

| Path | Measurement needed | Suspected cost to investigate, not a confirmed cause |
|---|---|---|
| Knowledge resolution / search | Single-process and concurrent cold/warm runs on one fixed release, fixed entitlement and identical skill set; wall/CPU time, Git process count, bytes read, lock waits, RSS | policy.py:189–242 starts one Git blob subprocess per regular file; skill_store.py:432–460 can reach per-read full cached-tree verification in knowledge_skill_source.py:201–220/672–717. Confirm call counts and baseline behavior before blaming or optimizing these paths. |
| Project init / status | Fresh, repeat, foreign/non-Git, corrupt and denied fixtures; direct command time separately from interpreter startup | Registry size, trust-file locking, pack links and repeated status inspection |
| All-project discovery / migration scan | Fixed approved-root set, project count, tree/history size; explicit single-project comparison | Depth-bound traversal and history/blob index rebuild versus reuse |
| Release flip / rollback | Break down pointer change, links, Codex refresh and doctor; failure/rollback case | Atomic symlink replacement is only one part of end-to-end completion |
| Control Tower | Refresh process count, latency and UI responsiveness under overlapping refresh/init/failure | Tray refresh currently starts six CLI operations concurrently, including fleet scan and all-project status; inspect coalescing, duplicate work and stale replies |

Agree budgets before approving an optimization. Retain signature, exact-byte, entitlement and race checks; an optimization must not replace authorization with a stale cache hit. The review should identify which measurements are required to decide release readiness, rather than mandate a new product-wide regression.

## 7. Verification evidence and precise reproduction scope

The prior release-11 sweep is historical evidence for that source. It is not a full-regression pass for this final candidate. The owner's subsequent direction was explicit: test only the six recorded failures and their specific defect controls, not the full section. The final targeted result is **six previously failed executable checks passing, plus nine passing specific controls**, with source/runtime metadata recorded, subject to the search-attribution limitation below. No full section or new full regression was run for this final verification.

| Selected group | Decisive outcome / limitation |
|---|---|
| Four Knowledge searches | All four existing assertions pass. They are substring smoke checks over combined stdout/stderr, not verified successful structured search results; see the coverage limitation below. No CLI was installed by this test round. |
| Five Knowledge controls | Valid signed snapshot with divergent authoring content; altered bytes rejected; wrong signer rejected; pointer outside managed releases rejected; revoked protected entitlement rejected. The last control originally used public foundation content. Commit ee616244 changes only its fixture to an internally consistent protected organization component; successful read then revoked-read rejection assertions remain unchanged. |
| Three CT authority tests | Candidate verifier/signer substitution rejected, authorized exact signed source accepted, protected workflow/checkout controls pass. Entire selected run: 1.003 s, private fixtures only. |
| Three cc packager parameter cases | Unsigned/no-op candidate rejected; signed integrated source accepted; signed off-main source rejected. Selected run: 2.433 s, no actual download or Apple calls. |

**Search coverage limitation:** tests/test_skill_frontmatter.py:198–244 invokes PATH-selected cc, combines stdout and stderr, ignores the child return code and checks topic/skill substrings. Passing these four assertions does not prove exit-zero search correctness, structured results or absence of diagnostic text. runtime.json records the expected ccBinary in the private locked environment and candidate PYTHONPATH. That is useful discovered routing metadata, but it is not a captured child-process realpath/hash/module attestation. Confirm the executed route before attributing successful implementation behavior to a candidate or deployed release. Ask for an appropriate successful-result oracle and separate error-stream validation; no false-positive exploit has been demonstrated, and no tests were changed for this document.

The synthetic security cases use temporary repositories, keys and stubbed external operations. They prove the local guard behavior exercised, not remote GitHub policy, hosted-runner availability, genuine Apple credentials, notarization or final artifact provenance. Original failures, the runner timeout and fixture correction are retained.

The test runtime was Python 3.14.7, pytest 9.1.1, Typer 0.26.8, Rich 15.0.0 and PyYAML 6.0.3. Shipping lock SHA-256: 6854a21ace6935457a330daa7b4a299f391738e399609fd9b6daf5cd00c157e9. Use a private environment derived from tools/cc/uv.lock; preserve installed developer environments. The CT unittest run used a separate runtime with the same Python/PyYAML versions.

Exact selectors for another developer, if separately authorized to reproduce. These commands are documentation; none were run while authoring this review. Set PYTHON to the private locked interpreter. Before the four live searches, capture command -v cc, resolve its symlinks/launcher, hash the selected artifact and identify its actual runtime/source commit. For a Python launcher, locate cc.__file__ using that launcher’s interpreter; for a frozen binary, use its artifact provenance. Merely importing cc in the pytest interpreter does not identify the child executable. Record the direct search exit code, stdout and stderr separately, plus the supported structured/parsed result and cache context; preserve PATH and relevant PYTHONPATH in the evidence. The four live searches require a CSE machine with the signed layer configuration, source repositories, active release and cache/entitlement context; they are not portable unit fixtures. Unit controls require Git and ssh-keygen but use synthetic authority. Use a unique pytest temporary directory per run.

From the Claude repository root, with PYTHONPATH=tools/cc/src:

~~~sh
PYTHONPATH="$PWD/tools/cc/src" "$PYTHON" -m pytest -o addopts= -p no:cacheprovider \
  tests/test_skill_frontmatter.py::TestCCSkillSearch::test_search_security_finds_stride_dread \
  tests/test_skill_frontmatter.py::TestCCSkillSearch::test_search_testing_finds_pytest \
  tests/test_skill_frontmatter.py::TestCCSkillSearch::test_search_javascript_finds_skill \
  tests/test_skill_frontmatter.py::TestCCSkillSearch::test_search_docker_finds_skill
~~~

From tools/cc, with PYTHONPATH=src:

~~~sh
PYTHONPATH="$PWD/src" "$PYTHON" -m pytest -o addopts= -p no:cacheprovider \
  tests/test_knowledge_release_source.py::test_active_release_authenticates_without_trusting_authoring_bytes \
  'tests/test_knowledge_release_source.py::test_snapshot_tampering_fails_closed[bytes]' \
  tests/test_knowledge_release_source.py::test_wrong_policy_signer_is_not_receipt_authority \
  tests/test_knowledge_release_source.py::test_current_pointer_cannot_escape_managed_releases \
  tests/test_knowledge_release_source.py::test_release_read_still_requires_current_entitlement \
  'tests/test_cc_release_packaging.py::test_packager_verifies_real_tag_main_ancestry_before_building[True-True]' \
  'tests/test_cc_release_packaging.py::test_packager_verifies_real_tag_main_ancestry_before_building[True-False]' \
  'tests/test_cc_release_packaging.py::test_packager_verifies_real_tag_main_ancestry_before_building[False-False]'
~~~

From the Control Tower repository, set PYTHONPATH=.github/tests:

~~~sh
PYTHONPATH="$PWD/.github/tests" "$PYTHON" -m unittest -v \
  test_release_ci.ReleaseAuthority.test_candidate_cannot_replace_verifier_and_signer_authority \
  test_release_ci.ReleaseAuthority.test_signed_integrated_exact_source_passes_without_credentials \
  test_release_ci.ReleaseAuthority.test_workflow_dispatch_and_checkout_keep_authority_outside_candidate
~~~

### Evidence locations and portability

Inline outcomes above remain readable without this machine. The raw artifacts below are local and ephemeral; /private/tmp and macOS temporary directories can disappear. Preserve/export the relevant summaries, raw logs, source identities, runtime receipt and original/corrected fixture diff into the developer's review packet before relying on them elsewhere. Do not publish synthetic private keys, real credentials, personal configuration or unredacted machine data.

- Knowledge: /private/tmp/cr-targeted-knowledge-0k8uwfpj/targeted-results.json; original failures and fixture-fix.json/diff beside it.
- Independent revocation: /private/tmp/cr-targeted-revocation-retest-vb36eg0s/summary.json.
- CT: /private/var/folders/h_/6c6hkvfn5hs2wx4yjw4pyknr0000gn/T/cr-targeted-ct-verifier-43y7wq6m/summary.json.
- cc packager: /private/tmp/cr-targeted-packager-t7s63jzi/summary.json and pytest.log.
- Original full sweep: canonical TASK-210 work products WP-404 through WP-410, as identified in the handoff; machine-local task records need an export for another developer. Their evidence is scoped to release #11, not this final candidate.

Task references for navigation are PRD-16, release/fleet TASK-209/210, status/interface TASK-229/230/232, packaging TASK-231/233/236, documentation TASK-234 and Knowledge adapter TASK-235. IDs are locators, not independent proof; confirm task-to-artifact links and tested identity. Some older API writes returned IDs from transactions that were not committed, so do not assume an ID printed in an earlier narrative establishes a durable record.

## 8. Release gates, recovery and requested review result

Still unfinished at this snapshot:

- Build and activate release #12; verify the live plan/receipt accounts for all 793 planned items, including three preserved owner items with reasons. Sandbox accounting does not establish the live result.
- Verify final intended source pins and coherent versions across every layer; retain the frozen Codex plugin core/trust contract and cc minimum 2.19 declaration.
- Complete the normal signed PR/branch-protection/CodeQL/CI path. GitHub CLI access was returning authentication failure; the owner deferred addressing it. No bypass is authorized.
- Verify remote release-environment protections/secrets, run actual hosted packaging, obtain notarized cc, update and verify CT's vendored helper, and produce genuine signed/notarized app artifacts. An older CT helper (2.12.7) is incompatible with the 2.19 central contract.
- Reconcile remaining tasks/streams and PRD state from actual source-bound evidence; the full handoff is not complete.

Recovery review must cover both layers: pointer rollback to a retained immutable release, and restoration of project migration changes from their exact manifests/archives/Git history. Confirm Codex cache refresh and doctor after rollback. A pointer rollback does not undo every machine trust/configuration or fleet migration change. Preserve owner-authored files, pending local commits, dirty worktrees and archives; fleet commits stay local. The prior Voice Copilot auto-push was explicitly retained by the owner and its hook preserved but disabled; that exception is not permission for new fleet pushes. Do not prune releases, delete archives/worktrees or rewrite history as part of this review.

Return a review with exact repository/commit/file references, severity, observed evidence or reproducible hypothesis, impact, and the smallest required change or follow-up measurement. Separate:

1. Release blockers, including unresolved trust or correctness defects.
2. Security/efficiency/performance concerns needing targeted evidence.
3. Non-blocking maintainability/documentation observations.
4. Explicitly unreviewed areas and any evidence the reviewer could not obtain.

A useful approval states the reviewed commit set and its limits. It must not turn targeted defect passes into whole-product approval or treat a source-only workflow review as proof of deployed CI or notarized artifacts.
