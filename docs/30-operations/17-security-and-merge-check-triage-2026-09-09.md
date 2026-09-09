# Security and merge-check triage — 2026-09-09

TASK69 / PRD6. This is a bounded source-remediation receipt, not a clean-security
certificate or permission to bypass repository rules. Live task evidence and
the final acceptance result remain in Task Copilot.

## Current remote facts

Authenticated, read-only GitHub API responses were captured for remote `main`
at `328ec6a1e06d6ddb10578145bbdd33cacf3464f3`. Six Dependabot alerts remain open:
two high, three medium (reported as moderate in the push notice), and one low.
No alert was dismissed or remotely changed by this task.

| Alert | Severity / package | Locked before → local candidate | Actual dependency owner |
|---|---|---|---|
| [126](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/security/dependabot/126) | High / cryptography | 49.0.0 → 50.0.0 | Root monitor development extra: twine → keyring → SecretStorage on Linux → cryptography |
| [125](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/security/dependabot/125) | High / aiohttp | 3.14.1 → 3.14.3 | Root monitor development extra: textual-dev / textual-serve / aiohttp-jinja2 → aiohttp |
| [124](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/security/dependabot/124) | Medium / aiohttp | 3.14.1 → 3.14.3; first patched 3.14.2 | Same root development graph |
| [123](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/security/dependabot/123) | Medium / aiohttp | 3.14.1 → 3.14.3; first patched 3.14.2 | Same root development graph |
| [122](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/security/dependabot/122) | Medium / setuptools | 81.0.0 → 83.0.0 | Optional cc embeddings extra: sentence-transformers → torch → setuptools |
| [121](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/security/dependabot/121) | Low / torch | 2.12.1 → 2.13.0 | Optional cc embeddings extra: sentence-transformers → torch |

These versions are the advisory-reported first patched versions, except aiohttp
3.14.3 also covers the two advisories fixed in 3.14.2. GitHub labels these lock
dependencies runtime; the owner column follows the actual optional-extra paths
in the local manifests and lock graph. Optional/development ownership is not an
alert dismissal or proof that a vulnerable path can never execute.

The aiohttp issues concern response parsing and WebSocket handling; the
cryptography issue concerns PKCS#7 decryption; setuptools concerns source-package
manifest exclusions on normalization-sensitive filesystems; torch concerns
`torch.jit.script`. No direct calls to these specific APIs were found in the
framework and monitor source inspected here. Transitive exploit reachability
was not established or exhaustively excluded.

## Scoped source corrections

Only `uv.lock` and `tools/cc/uv.lock` were regenerated with targeted
`uv lock --upgrade-package` selectors after successful dry runs. No Python
minimum, project manifest, application code, installed environment or workflow
was changed by this task.

- Root graph: aiohttp 3.14.3 and cryptography 50.0.0. The resolver also adds
  published ppc64le/s390x wheel records for unchanged cffi 2.0.0; no existing
  cffi artifact is removed and its version/dependencies are unchanged.
- cc optional graph: setuptools 83.0.0, torch 2.13.0, and its required
  cuda-toolkit adjustment 13.0.2 → 13.0.3.0.
- Resolution retains the existing Python `>=3.10` contract and package counts
  (98 root / 84 cc). No unrelated package version was upgraded.

This is metadata/lock remediation. No model, CUDA package, browser, or optional
embedding environment was installed. Resolver compatibility does not establish
runtime compatibility of the upgraded optional graph. Consumers installing from
unconstrained manifests rather than these locks do not automatically inherit a
new minimum; no transitive runtime dependency was promoted to a mandatory direct
dependency merely to silence an alert.

## Merge rules and current checks

The active [main-protection ruleset](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/rules/11318595)
requires a pull request, linear history, signed commits, strict required `CodeQL`
status, and restrictions on deletion/non-fast-forward updates. Classic branch
protection reports disabled, but the active ruleset still protects `main`;
those are different mechanisms.

Rule-suite `3995586132` records the 2026-09-08 push to the SHA above as **bypass**:
linear history, pull request and the then-expected CodeQL check failed at push
time. Signatures passed. The ruleset currently grants always-bypass to configured
organization administrators and repository administrators, including the current
authenticated account. This task did not exercise or change that permission.

The later [CodeQL check](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/actions/runs/34291686871/job/102279400321)
is now successful and its job name exactly matches the required `CodeQL` context.
That later success does not retroactively satisfy the PR or linear-history
failures at push time. The current workflow analyzes JavaScript/TypeScript; its
success is not a Python security audit. No CodeQL workflow repair was justified
by these facts.

Three other checks on the same remote SHA failed before this task:

| Check | Captured cause | Boundary |
|---|---|---|
| [Hardcoded paths](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/actions/runs/34291686908/job/102279400752) | Machine-specific checkout path in a comment at `tools/cc/tests/test_codex_plugin_source_mirror.py:140` | Source portability; not a workflow defect |
| [TypeScript + shell](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/actions/runs/34291686863/job/102279400586) | `me` missing the `**Always:**` marker required by `tests/integration/lean-agents-skills.test.ts:214` | Instruction compatibility; routed to policy owner |
| [Smoke](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/actions/runs/34291686854/job/102279400238) | `qa.md` missing `## Core Behaviors`, checked at `scripts/smoke-test.sh:114` | Instruction compatibility; routed to policy owner |

Checks were not disabled, skipped, renamed or loosened to convert these failures
to success. Their eventual repair status belongs to the owning task, not this
receipt's captured remote snapshot.

## Bounded acceptance and stop condition

The acceptance pass checks both locks with `uv lock --check --offline`, exports
each complete extras graph with `uv export --locked --offline --all-extras`, and
verifies the six captured advisory floors plus the exact allowed package-change
set and unchanged Python constraints. It also checks this receipt's local file
references and the scoped diff. Every command has a 60-second cap; no full suite,
global vulnerability scanner, installed-package upgrade, or model run is needed
to prove these lock/receipt criteria. Resolver dry runs completed in 5.93 seconds
for root and 1.12 seconds for cc; these are observations, not delivery estimates.

Raw read-only API responses, failed-check logs, resolver logs and final scoped
validation artifacts are local and ignored under
`.copilot/evidence/security-merge-task69/`. TASK69 retains before/after source
identity and the task-bound work products. No raw evidence was uploaded.

This stream stops after that acceptance pass. Remote alerts can only be
reevaluated after an authorized publication and GitHub dependency refresh;
current open-alert status remains explicit. Future merges should use an
authorized PR and linear merge method with required checks, not the account's
bypass ability. Removing bypass actors is a separate owner decision. Historical
merge rewriting, branch-rule changes, remote publication, package deployment and
optional model-runtime validation were not performed.
