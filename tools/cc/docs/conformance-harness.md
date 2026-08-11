# The ecosystem conformance harness

This is the operator guide for `cc conformance` — the harness that turns "is the Copilot ecosystem correct?" into a command you run instead of a judgement call. Design source of truth: `HARNESS-DESIGN.md` and `TEST-MATRIX.md` (the design specs this package implements against). This document explains what exists today, how to run it, how to read a failure, and how the committed baseline works.

## What it proves

The harness asserts, across six layers, that the Copilot ecosystem's tier inheritance, component stack, per-repo install conformance, lock integrity, installer round-trip, and five systemic root causes are all in the state they claim to be in — and it does this by calling the same `cc` modules that already compute ecosystem state (`resolver`, `manifest`, `discovery`, `extensions_resolver`, `project_integration`) rather than re-implementing any of it. A check is either a thin wrap around an existing `cc` verb/module, or — for the six things nothing in the ecosystem verifies today (shadow-substance, pin-ancestry, lock-uniqueness, the rubric dimensions as executable assertions, installer-source contracts, and the round-trip) — new, purpose-built code that lives alongside everything else under `core/conformance/`.

Every check produces one or more `CheckResult` records (`core/conformance/types.py`), each carrying an `id`, a `layer`, a `severity` (S0 most severe, S3 cosmetic — `RUBRIC.md` §4's scale, reused verbatim), a `verdict` (`pass` / `fail` / `skip` / `could-not-run`), and — for any `fail` — mandatory, concrete evidence: a path, an expected value, an actual value. A failure with no evidence is a harness bug, not a reportable result, and `CheckResult`'s own constructor raises rather than allow one to be built. `could-not-run` is a fourth, honest verdict distinct from both `pass` and `fail` — it means the harness could not determine an answer (a crashed check, an unreadable repo, a dimension module that failed to import), and it is never coerced into a passing result anywhere in this codebase.

The harness deliberately does **not** compute a health score. `RUBRIC.md` §4 states plainly that S0 and S3 are not commensurable, so nothing here averages or rolls up to a percentage — `report.render_human` and `report.to_envelope` both scan their own output and raise if a `%` character or a bare, unqualified `ready` ever appears (`cc workspace verify`'s `ready` classification is not a pass oracle; see `EXISTING-VERIFICATION.md` §2 for the full trace of why, and always read it as "ready (by waiver, N files)" or not at all).

## Command surface

**Today**, before the `cc conformance` CLI verb (WP-8) lands, every check is reachable as a pytest suite:

```
cd tools/cc
.venv/bin/python -m pytest tests/conformance/ -v                    # everything this machine can run
.venv/bin/python -m pytest tests/conformance/ -m "not machine" -v   # hermetic — no real ecosystem needed
.venv/bin/python -m pytest tests/conformance/test_layer3_dimensions.py -v   # one layer
```

`-m "not machine"` selects only the synthetic-fleet (World A) tests — see "The two worlds" below — and is the invocation that runs anywhere, including a CI runner with no ecosystem installed at all. Every check's positive case (a fixture where it passes) and negative case (a fixture where it fails) live there; a check that has never been proven to fail is not a check, and this is enforced as its own fitness function.

**Once WP-8 lands**, the same checks are reachable as `cc conformance check|report|baseline|explain|list`, with `--layer`, `--fast`/`--full`, `--repo`, `--class`, `--check`, `--fail-on`, `--baseline`, and `--json` — see `HARNESS-DESIGN.md` §6 for the full CLI contract. Nothing in this package depends on that CLI existing; every check, the baseline mechanism, and the CI wiring documented here work against the pytest face directly.

## The two worlds

Every conformance test runs in exactly one of two worlds, and no test straddles both.

**World A — synthetic.** A complete fake ecosystem built fresh under `tmp_path` for each test: a temporary `$HOME`, a generated `copilot.layers.yml`, real `git init`/commit/tag tier repos (ancestry is a genuine git property, so a mocked repo can't fail the way a real one does). Nothing outside `tmp_path` is ever read or written. This is what `-m "not machine"` selects, and it is what makes the harness portable to any machine, including one with no ecosystem installed.

**World B — machine truth.** Reads the real manifest, the real tier repos, and the real project repos under this developer's own `projects.roots`, strictly read-only, enforced by a pre/post SHA-256 tripwire (`core/conformance/fsguard.py`) rather than by discipline — any test that mutates a real path fails the whole run loudly, naming the offending path. These tests are marked `@pytest.mark.machine`.

A known gap, found while building the CI wiring for this package and worth stating plainly rather than silently working around: `test_layer1_tier.py` and `test_rc_regressions.py` guard their `@pytest.mark.machine` tests with an explicit `requires_real_machine` skipif, so they skip cleanly (never fail) when the real ecosystem is absent. `test_layer2_stack.py`'s `TestMachineTruth` and `test_layer3_dimensions.py`'s `TestRealFleetDiscovery` are correctly marked `@pytest.mark.machine` but are **not** guarded the same way — run bare (without `-m "not machine"`) on a machine with no real ecosystem, they error or fail instead of skipping. Verified directly by emptying `$HOME` and running the suite both ways. `-m "not machine"` sidesteps this structurally (it deselects by marker, independent of each file's own discipline), which is why every documented invocation in this file and in the CI workflow uses it explicitly rather than relying on convention. This is not this package's file to fix (`test_layer2_stack.py` and `test_layer3_dimensions.py` belong to the layer-2/layer-3 work packages), and it does not block anything documented here — it is recorded so the next person who runs a bare `pytest tests/conformance/` on a clean box understands what they are seeing.

## Reading a failure

Human output (`report.render_human`) groups by layer, then lists every `fail` with its severity, id, subject, evidence, and remediation string:

```
LAYER  repo        install conformance             2026 checks   1537 pass    489 FAIL
  FAIL  S0  repo.d04.hook_present_and_locked  (/Volumes/Dev/Sites/COPILOT/claude-copilot)
            expected='present, executable, recorded in the lock' actual='present=True, executable=True, locked=False'
            fix  Wire projects.write_project_lock into setup-project.md / update-project.md's install steps.
```

Every check id follows `<layer>.<area>.<name>` (`tier.shadow.substance`, `repo.d04.hook_present_and_locked`, `rc.rc3.orphan_release_tags`) — stable and greppable, safe to paste into a remediation ticket. The `--json` envelope (once WP-8 lands; the same shape is what `report.to_envelope` already produces against pytest-collected results today) carries the identical fields under `checks[]`, plus a `summary` block with counts **by severity and by layer, never averaged**.

Exit codes (`report.compute_exit_code`):

| Code | Meaning |
|---|---|
| 0 | Conforms at the requested `--fail-on` threshold |
| 1 | At least one check at or above the threshold failed |
| 2 | The harness could not run at least one selected check — never conflated with a real failure |
| 3 | A `--baseline` comparison found something that PASSED before and now FAILS, regardless of severity |

Precedence when more than one applies: a baseline regression (3) is checked first, then `could-not-run` (2), then plain `fail` (1) — see `report.compute_exit_code`'s own docstring for the reasoning.

## The baseline mechanism

The harness runs against an ecosystem that is known, today, to have five systemic root causes and a large number of per-repo dimension failures. A conformance run that reports "36% pass" on that ecosystem is not informative on its own — what matters is whether a specific check, on a specific subject, changes from passing to failing. That is what the baseline captures.

**The file.** `tests/conformance/baselines/2026-08-10-known-bad.json` freezes every `(check id, subject)` pair's verdict as measured on this machine, generated from a live run — never written or edited by hand. `report.load_baseline` reads its `entries` array; every other top-level key (`reason`, `generated_by`, `generated_at`, `mode`, `counts`) is this script's own audit trail, ignored by every consumer, kept so the file's own history explains itself.

**The comparison.** `report.compare_to_baseline` buckets every fresh result against the baseline by `(id, subject)`: `fixed` (baseline FAIL, now PASS), `still_failing` (FAIL both times), `regressed` (baseline PASS, now FAIL — the sole trigger for exit code 3), and `new_failures` (no baseline entry at all, now FAIL — reported, but not itself a regression, since there was nothing to regress from).

**Regenerating it is deliberately not trivial.** The generator (`tests/conformance/baselines/generate_baseline.py`) is a dry run by default — it always computes and prints a summary, and writes nothing unless `--write` is passed. Writing additionally requires a non-empty `--reason` (why is this being regenerated), and if a baseline already exists at the target path, the generator refuses to overwrite it when the fresh run would silently bake in a regression — something PASS in the old file, FAIL in the new one — unless `--acknowledge-regression` is also passed, in which case every acknowledged pair is written into the file's own `acknowledged_regressions` list rather than disappearing. This is the mechanism that stops "the check broke, so someone refreshed the baseline instead of fixing it" from ever being silent.

```
# Dry run — prints the summary, writes nothing:
tools/cc/.venv/bin/python tools/cc/tests/conformance/baselines/generate_baseline.py

# Regenerate for real:
tools/cc/.venv/bin/python tools/cc/tests/conformance/baselines/generate_baseline.py \
    --write --reason "describe why this baseline needed a fresh capture"

# Faster, partial regeneration (fast-mode sweep, skip the round-trip layer):
tools/cc/.venv/bin/python tools/cc/tests/conformance/baselines/generate_baseline.py \
    --fast --no-roundtrip --write --reason "..."
```

The generator runs against the real machine — Layer 1 (tier resolution) against the real manifest, config, and framework agents; Layer 2 (component stack) against every real `copilot.layers.yml`; Layer 3 (the 13-dimension sweep) in full mode over every repo under `projects.roots`; Layer 4 (lock integrity) over the same repo set; Layer 5 (round-trip) by running the real `setup-project.md` / `update-project.md` bash steps against disposable `tempfile.TemporaryDirectory()` scratch clones, never a real product repo; and Layer 6 (the five root-cause regression pins) via `root_causes.run_all_root_cause_checks`. It never depends on the `cc conformance` CLI existing.

**What it validates on its own.** `tests/conformance/baselines/test_baseline_file.py` is a hermetic, always-on test module — no real machine access required — that asserts the committed baseline is non-empty, well-formed, free of duplicate `(id, subject)` keys, contains at least one FAIL for each of RC-1 through RC-5 (`test_baseline_captures_every_known_root_cause` — the fitness function `HARNESS-DESIGN.md` §5.4/§13 names), and meets `TEST-MATRIX.md` §8's own floor ("if the harness's first run reports fewer failures than this list, the harness is under-detecting"). It also replays the committed baseline through `report.compute_exit_code` unchanged (proving an honest, non-regressed run never fabricates a `pass` while real `could-not-run` entries exist) and with one synthetic PASS→FAIL flip (proving exit code 3 fires), so the regression path is a standing, automated test rather than a one-off demonstration.

## Layer and dimension map

| Layer | What it proves | Registered checks (measured) | Severities |
|---|---|---|---|
| 1 — tier (`tier.*` + `tier.effectiveness.*`) | Foundation → org → dept → personal resolves correctly; a nearer tier's *empty* declaration never silently shadows real upstream content; AND (the `effectiveness.*` sub-module) that resolved content is INSTALLED, WIRED, and EFFECTIVE, not merely computable — see "Installed vs wired vs effective" below | 15 | 5×S0, 8×S1, 2×S2 |
| 2 — stack (`stack.*`) | Every product × tier cell declares itself, resolves, pins to a real ref, and that ref is a genuine ancestor of its branch | 7 | 3×S0, 4×S1 |
| 3 — repo / the 13 rubric dimensions (`repo.*`) | D1–D13 as executable, per-repo assertions with concrete evidence — the machine-readable successor to the original audit | 29 | 1×S0, 16×S1, 9×S2, 3×S3 |
| 4 — lock (`lock.*`) | `copilot.lock.json` reflects the actual install, `ready` cannot be produced by a waiver over missing required paths | 5 | 3×S0, 2×S1 |
| 5 — round-trip (`roundtrip.*`) | The real installer produces the reference install and the real updater is idempotent and destroys nothing project-owned | 8 | 5×S0, 3×S1 |
| 6 — root-cause regression pins (`rc.*`) | One named, `expected_today=FAIL` test per systemic root cause (RC-1..RC-5) | 5 | 5×S0 |

69 checks registered in total as of this writing (`registry.DEFAULT_REGISTRY`), the large majority `fast` mode (local filesystem and local git only, no network); `roundtrip.*` and a handful of `repo.d01`/`stack` checks are `full`-only (they shell out to `fitness-check.sh` or read a mirror/remote).

### Installed vs wired vs effective

Every check above `tier.effectiveness.*` was added to close one specific blind spot: everything else in this harness measures whether a project's install **matches a reference** (INSTALLED) — none of it measured whether the tier hierarchy **delivers anything** (WIRED: a real consumer reads the resolved content; EFFECTIVE: it changes what an agent actually does). A harness that only checks the first property can report green while the second is broken end to end, which is exactly what this machine's installer (`setup-project.md`'s literal `~/.claude/copilot`-only "Copy Agents" step) was doing before these checks existed — a project's `.claude/agents/*.md` matched the reference install shape while `copilot.layers.yml` had never been consulted at all.

Six checks, `core/conformance/effectiveness.py`:

| id | proves | fixture that proves it can still FAIL |
|---|---|---|
| `tier.effectiveness.org_content_reaches_project` (E-1, S0) | A nearer tier's content reaches a project's INSTALLED file, verified by running the real `setup-project.md` bash steps against a scratch project and reading the result off disk — never by inspecting config | today's single-source installer never wires a synthetic org-tier marker in |
| `tier.effectiveness.nearest_wins_preserves_siblings` (E-2, S1) | Overriding one artifact never costs the project every artifact it did not override | a fixture "naive wholesale switch" installer that drops every non-overridden roster item |
| `tier.effectiveness.draft_placeholder_never_shadows_resolver_wide` (E-3, S0) | Generalizes H-3/Q25's shadow-substance guard from agent extensions to `resolve_layers()`'s own fold (every override-semantics dimension) — nothing checked this before | a TODO-marked/empty fixture winner shadowing real content via `resolve_layers` |
| `tier.effectiveness.resolve_attribution_matches_lock` (E-4, S0) | Every item's `winning_layer` is backed by a REAL recorded materialization in `copilot.lock.json`, never a `_meta`-only entry | a fixture winner whose lock entry carries only `_meta` |
| `tier.effectiveness.knowledge_ladder_actually_consumed` (E-5, S1) | An agent that hydrates `$CC_KNOWLEDGE_REPOS` also walks and reads it — hydrate-then-never-read is installed but not effective | a fixture agent text that hydrates `cc env` and reads nothing |
| `tier.effectiveness.extension_resolution_wired_beyond_prose` (E-6, S2) | `cc extensions resolve` is invoked by an executable hook/script, not merely described in `.md` prose | a fixture `.sh` file with only a commented-out invocation |

`tests/conformance/test_layer1_effectiveness.py` carries the PASS-shape and FAIL-shape fixture for each, plus one `@pytest.mark.machine` test per check recording this machine's live verdict as of 2026-08-11 — several came back FAIL (E-1, E-4, E-6, and E-3's one live instance), matching the corresponding underlying defects three concurrently-landing fixes (a tier-aware install plan, `cc update --fanout`, and the design agents' ladder reads) are expected to turn green over time; `expected_today` is set per result to match, never weakened to make a number look better.

The 13 rubric dimensions (D1–D13), each implemented as its own `dimensions/dNN_*.py` module:

| Dim | Area | Dim | Area |
|---|---|---|---|
| D1 | Claude framework install (agents, commands, fitness-check, `CLAUDE.md` heading) | D8 | Tier participation (`NA` for class C/D/E, never silently "missing") |
| D2 | Codex framework install (`AGENTS.md`, plugin tree, skill bridge symlink) | D9 | `copilot.project.json` portable declaration |
| D3 | Lock schema and checksums | D10 | `.mcp.json` shape and committability |
| D4 | Enforcement hook present **and** locked (RC-1) | D11 | `ECOSYSTEM.md` registry entry |
| D5 | `.claude/cc/config.json` machine sentinel | D12 | `docs/40-initiatives/` scaffold |
| D6 | Memory entries committed, `memory.db` ignored | D13 | Scanner reachability |
| D7 | Knowledge wiring resolves, no hardcoded absolute paths | | |

Repo classification (A = foundation, B = tier variant, C = product/site, D = markdown-knowledge, E = not a git root / archive / scratch) is data, not code — `classification.toml`, with a one-line rationale per override entry, per the ratified Q9/Q27 decisions.

## Known gaps outside this package's ownership

Recorded here for operator honesty, not fixed by this package (this package owns the baseline, CI wiring, and documentation — not `tier.py`, `stack.py`, `sweep.py`, `lock.py`, `roundtrip.py`, `root_causes.py`, or `dimensions/*`):

- **`dimensions/dx_gitignore.py` does not exist yet.** `repo.gitignore.no_self_exclusion` (the check that generalizes the Q23 batch — "no repo's own `.gitignore` excludes a path its own lock records as framework-owned" — into one structural rule) is referenced by `HARNESS-DESIGN.md`'s file layout but the module itself has not landed. `sweep.run_sweep` reports this honestly as one `repo.dx_gitignore.module_unavailable` `could-not-run` result per sweep, never as a fabricated pass, which is why a full sweep's exit code is 2 until it lands.
- **The three invariants lifted from the retired Rust fitness functions are not yet registered.** `inv.no_bare_cli_name`, `inv.no_fabricated_healthy`, and `inv.registry_completeness` are named in `HARNESS-DESIGN.md` §13's fitness-function table as Layer 6 additions but do not currently exist in `registry.DEFAULT_REGISTRY`.
- **`test_layer2_stack.py` / `test_layer3_dimensions.py`'s machine-marked classes lack a clean skipif** — see "The two worlds" above.

None of these block the CI wiring or the baseline documented here — `-m "not machine"` sidesteps the skipif gap, the baseline test suite treats `could-not-run` honestly rather than masking it, and the missing `inv.*` checks are additive (their absence does not make anything already registered less true).

## What was retired

The design supersedes three one-off audit scripts (`audit.py`, `scan.sh`, `ecosystem-scan.tsv`) with this harness — but all three were verified, before writing anything here, to live only in the ephemeral scratchpad used to produce the design documents, never in this repository. A repo-wide search for `audit.py`, `scan.sh`, `scan_component.py`, `lockcheck.py`, `probe.py`, `gen.py`, and `ecosystem-scan.tsv` found no matches under `claude-copilot` outside third-party vendored packages (`tools/cc/src/cc/usage/probe.py` is unrelated production code, not the audit's throwaway probe). There was nothing to delete; this is recorded rather than silently skipped, per the instruction to verify before removing and never delete anything not confirmed dead.

Separately, `copilot-control-tower/src-tauri/tests/fitness_*.rs` (38 files) are **not** touched by this package — they live in a different repository, scan a retired Rust tree behind a disabled CI job, and the design's own recommendation is to port only three ecosystem-wide invariant *statements* (`fitness_no_bare_cli_name`, `fitness_no_fabricated_healthy`, `fitness_single_process_ff_m4_7`) into this harness's Layer 6 as Python assertions, restated from scratch — not to wrap or delete the Rust. That porting is the `inv.*` gap noted above, and remains future work for whichever package picks up Layer 6 next.

## CI

`.github/workflows/conformance.yml` triggers unconditionally on every push and pull request to `main` — no opt-in variable gate, a direct response to `copilot-control-tower`'s release gate being switched off behind `vars.RELEASE_CI_ENABLED` and skipping every tagged release in one second. It installs `tools/cc[dev]` and runs `pytest tests/conformance/ -m "not machine" -v`, which is fully portable (World A only, no real ecosystem needed) and genuinely fails the build on a real regression — verified directly by injecting a deliberately-broken test file into the suite and confirming a non-zero exit code, then removing it.

What it cannot prove, structurally: the World-B (`@pytest.mark.machine`) checks against a real developer's own ecosystem. There is no GitHub-hosted substitute for `~/.claude/cc/config.json`, a real `copilot.layers.yml`, or the ~75 repos under a real `projects.roots` — the same conclusion `TEST-MATRIX.md` §7 item 6 reaches for the adjacent `cc workspace verify` sweep ("a separate, explicitly-labeled local-only machine-sweep integration test ... never in shared CI"). Checking or regenerating the baseline against the real machine is documented above as a local operation, not something the CI workflow attempts to fake.

Because this repository's own working tree is on an unmerged branch, this workflow — like every other file this package's design depends on — has not yet executed inside GitHub-hosted Actions; it has been proven by running its exact `pip install` and `pytest` steps locally, in a fresh virtualenv, with `$HOME` pointed at an empty directory to simulate a runner with no ecosystem installed, and separately by injecting and then removing a synthetic failing test to confirm a non-zero exit propagates. It will run for real the moment this branch reaches `main`.
