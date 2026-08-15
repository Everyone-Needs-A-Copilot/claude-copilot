# Layered effectiveness evaluation

This evaluation framework defines the live EVAL-01 through EVAL-07 comparison required by WP-718. It plans exactly 28 cells: seven cases, two declared layer variants per case, and both Claude Code and Codex. The matrix is criterion-based and intentionally has no aggregate score, ranking, winner, or automatic claim that the ecosystem is effective.

## What the matrix tests

EVAL-01, EVAL-02, EVAL-03, EVAL-04, and EVAL-06 compare Foundation with Foundation plus Organization. EVAL-05 compares Foundation with Foundation plus Organization plus Department. EVAL-07 compares Foundation plus Organization plus Department with the same ladder plus Personal. Every control and layered run uses the same fixture revision, declared evidence, runtime identity, attempt policy, and tool policy; the content variant is the intended difference.

Each runtime receives only the synthetic problem statement and declared evidence packet as user input. The private oracle, criterion list, hard-rejection rules, layer names, and expected answer never enter user input. Specialist and Knowledge context must be produced by TASK-296's production protocol and resolver path, and the exact system context, invocation marker, composed-content digest, source receipts, runtime configuration, tool configuration, and final output are bound into evidence identities.

## Commands

`cc eval effectiveness matrix --json` prints the exact 28-cell preregistered plan from the immutable fixture bundle installed inside `cc` and starts no model calls. `--fixtures-root` remains available for verifier development, but it is not accepted by the live operator path.

`cc eval effectiveness readiness --json` performs a value-suppressing candidate inspection from the installed fixture bundle and starts no model calls. Candidate checks can identify missing layer materialization, runtime authentication, and runtime isolation, but they cannot mint canonical readiness. The command therefore remains blocked with `canonical-readiness-verifier-unavailable` even if every candidate check is satisfied.

`cc eval effectiveness run --artifact-root <private-root> --claude-model <exact-model> --codex-model <exact-model> --json` is the operator entrypoint. It accepts only the installed preregistered fixture root, an explicit private artifact root, and exact model references. The CLI does not create evaluation cells, receipts, passing gates, readiness, artifact directories, runtime callbacks, or fallback execution. It can invoke only the public synchronous production boundary `cc.core.evaluation.execution.issue_matrix_execution`, which is responsible for verifying canonical readiness, claiming attempts, executing, adjudicating, and preserving the portfolio. Until that boundary exists, the command exits blocked with `canonical-execution-issuer-unavailable`, reports zero initial cells and zero attempts started, creates no artifacts, and starts no model calls.

The production boundary returns one exact JSON-safe report with a bound execution identity, the installed matrix identity, initial cell and total attempt counts, sorted blockers, and a portfolio artifact identity only on completion. CLI validation rejects missing or extra fields, a substituted matrix, Boolean or invalid counts, unordered or duplicate blockers, an unbound execution identity, or a completion without a portfolio identity.

## Installed fixture bundle

The EVAL-01–07 case packets, evidence, and private oracles ship inside the wheel at `cc/evaluation_fixtures/cases`. The installed root contains exactly the reviewed 23-directory/31-file tree and is bound to raw bundle SHA-256 `a2f20f40690ff1ca09312b72575bda5d1600539be06663afa689501c8d418698`; its case, evidence, oracle, route, variant, and runtime preregistration is separately bound to matrix SHA-256 `0c844795668aa2dc40596975ba5e20d3ee2fe345583149d20c9c8a07ef6688f6`. The package loader rejects missing, extra, symlinked, non-directory, mutated, or non-preregistered content before returning the default root.

## Runtime completion proof

The Claude adapter uses non-interactive JSON output, no session persistence, plan permission mode, no built-in tools, denied MCP tools, strict MCP configuration, safe mode, and an explicit system-context file containing the exact protocol-prepared projection. Native Keychain authentication is checked with `claude auth status --json` in the same value-suppressing environment used by the adapter. Claude's custom-agent flag is not used because safe mode disables custom agents; instead, exact signed specialist bytes are included in the explicit system projection and disclosed as a source receipt.

The Codex adapter uses the exact native binary behind the JavaScript launcher, ephemeral execution, strict configuration, isolated authentication projection, read-only sandboxing, JSONL events, a private pre-created final-message file, and a closed feature-disable set. The final-message inode is retained across launch and read, JSONL ordering and item identity are verified, tool events are rejected, stderr is digest-bound, output is safety-scanned before storage, and the process group is terminated on every exit. Codex production execution remains fail-closed with `codex-no-tool-isolation-unavailable` because read-only sandboxing and disabled feature flags do not yet prove that model-requested process execution and unintended reads are preventively impossible.

The subprocess path bounds stdout and stderr while streaming, kills the entire retained process group on timeout and normal exit, and stages the verified executable bytes into the private invocation workspace before production execution. Completion is accepted only when the concrete adapter authenticates one native successful terminal turn and binds the exact invocation envelope, runtime configuration, tool configuration, full prompt, output, artifact path, terminal event, command policy, and stderr digest.

Completed output is quarantined as a content-addressed, mode-0600 private evaluation artifact. It is not a shared deliverable. A durable COMPLETED run record is accepted only with the same in-process sealed output and a fresh retained-file-descriptor verification of the exact private bytes. Generic caller-provided stdout can produce no completion authority. Attempt claims are created atomically before a runtime call, so a duplicate first attempt for the same exact cell is rejected before model execution and the original claim remains preserved. Each claimed execution also writes one immutable slot-keyed terminal result that binds the full RunRecord to the exact start claim. A host or process crash after the start claim but before that terminal result permanently consumes the attempt; recovery requires a verifier-approved new matrix revision, never deletion, reset, or silent reuse of the abandoned slot.

## Source attribution

A content receipt may contain multiple products for one tier, such as an authenticated Knowledge contribution and a Claude agent or Codex specialist contribution. Products are ordered canonically within the exact tier ladder. Every TASK-296 prepared source must match exactly one content-receipt product by repository, immutable ref, tree, signer, contribution path, and content digest; missing, duplicate, extra, wrong-repository, wrong-tier, and substituted-content sources fail closed.

The shared-tier releases supplied by TASK-297 identify Claude Organization `cco`, Claude Accounting `cpa`, Codex Organization `cco` and `uids`, and Codex Accounting `cpa` contributions. Those releases and their lock/materialization receipts are prerequisites, but the evaluation cannot treat a release tag alone as consumption proof. The Codex path must still compose the applicable signed Knowledge contributions with the exact additive signed specialist plugins for each variant and must prove every required tier in the resulting content receipt.

Personal content has a different publication policy. It must not be forced into a shared signed repository, but an F+O+D+P evaluation still requires a frozen, value-suppressing local content-object identity for exact Personal Knowledge and runtime-specialist bytes. Until that snapshot contract is implemented, personal matrix cells remain blocked rather than silently consuming mutable `main` content.

## Judgment and safety

Only a completed, evidence-bound run can receive criterion judgments. A judgment must cover every required criterion and hard-rejection rule in fixture order, cite digest-bound spans from the exact output, and identify an owner review or independent QA review. Model self-assessment and aggregate score fields are rejected. Any hard rejection blocks comparison, any new VIOLATED criterion blocks comparison, and any protected criterion regression blocks comparison.

Pre-storage scanning rejects credential shapes, personal contact details, and private paths. Every runtime result, including EVAL-07 exact values and semantic paraphrases, is stored only in the private `runtime-quarantine` class. No shared-output write exists in the runtime adapters. Promotion to a shared deliverable remains unsupported until a durable owner or independent-QA authorization can apply the private oracle and value-suppressing semantic review to the exact quarantined bytes.

## Current blockers

The 28 initial live calls have not started. The production execution issuer is not implemented, so the operator entrypoint is intentionally blocked before artifacts or attempts exist. Codex remains blocked on preventive no-tool isolation, exact additive plugin plus Knowledge composition, and the associated live adversarial probe. Personal cells remain blocked on immutable local snapshot receipts. Canonical readiness also requires cryptographic source, entitlement lease, lock, joined-materialization, and runtime-authentication evidence rather than accepting a semantic-version-looking ref and a non-empty signer list.

Independent security and QA must verify the implementation before TASK-285 can complete. The implementation does not mark TASK-285 complete and does not claim that the ecosystem goal has been achieved merely because the framework code or fixture matrix exists.

## References

Codex non-interactive behavior and JSONL events were verified against [OpenAI non-interactive mode documentation](https://learn.chatgpt.com/docs/non-interactive-mode). Codex sandbox limitations were checked against [OpenAI sandboxing documentation](https://learn.chatgpt.com/docs/sandboxing). Claude flags and headless behavior were verified against [Claude Code CLI usage](https://code.claude.com/docs/en/cli-usage) and [Claude Code headless mode](https://code.claude.com/docs/en/headless).
