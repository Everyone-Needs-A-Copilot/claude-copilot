# Changelog

All notable changes to Claude Copilot will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [5.13.0]

Layered knowledge repos — `paths.knowledge_repo` accepts an ordered list. Component bump: cc 1.7.0.

### Added

- **Layered knowledge repos** (`tools/cc/`): `paths.knowledge_repo` now accepts an ORDERED LIST of repo paths (shared + personal both active simultaneously), in addition to the existing single-string form. A new `resolve_knowledge_repos()` normalizer in `cc.core.config` returns the ordered list for all three supported shapes — legacy string (1-element list), JSON list (order preserved), or null/absent (empty list). Layer precedence for *which source* wins is unchanged (env > project > machine > default); the winning layer supplies the whole ordered list — config layers are never concatenated. Closes the gap between the extension spec's promised layering and the previous single-repo-only implementation.
- **`cc config add <key> <value>`**: appends a value to a list-valued config key, idempotently (no-op if already present); upgrades an existing string value to a list on first append. Honors `--project`/machine-default scoping like `cc config set`.
- **`cc config remove <key> <value>`**: symmetric removal from a list-valued config key (no-op if the value is not present).
- **`CC_PATHS_KNOWLEDGE_REPO` env var now accepts a comma-separated list**: `export CC_PATHS_KNOWLEDGE_REPO="/vol/shared-kc,/vol/personal-kc"` splits into an ordered list (whitespace-trimmed, empty segments dropped). A single path continues to work unchanged.
- **`cc config set paths.knowledge_repo a,b,c`** parses a comma-separated value into a JSON list for this key only; a single value with no comma is still stored as a plain string (back-compat unaffected for other keys and for existing single-repo configs).

### Changed

- **`cc env`**: `CC_PATHS_KNOWLEDGE_REPO` is now emitted as a comma-joined string when the resolved value is a list. The back-compat alias `CC_KNOWLEDGE_REPO` carries only the **first** element of the list, so agents/hooks reading a single value keep working unchanged.
- **`cc config doctor`**: path-existence checks now handle list-valued config keys, checking each path in the list individually rather than stringifying the whole list.
- **`docs/40-extensions/00-extension-spec.md`**: added an "Implementation status" note distinguishing what `cc` resolves deterministically (config values, including the new ordered-list `paths.knowledge_repo`) from the richer per-agent `.override.md`/`.extension.md`/`.skills.json` manifest-merging model the spec describes, which is an agent-read convention, not something `cc` parses or merges automatically. Added a dedicated "Layered Knowledge Repos" section documenting the value shapes, precedence rule, and new `cc config add`/`remove` commands.
- **`tools/cc/README.md`**: documented the ordered-list value shapes, `cc config add`/`remove`, and the `cc env` comma-join + first-element alias behavior for `paths.knowledge_repo`.

### Architecture

- **cc 1.7.0**: `resolve_knowledge_repos()` normalizer, `LIST_VALUED_KEYS` registry, `add_to_list_config()`/`remove_from_list_config()` in `cc.core.config`; `cc config add`/`remove` CLI commands; comma-split env-var handling for list-valued keys.

## [5.12.0] - 2026-06-29

Regression-eval harness, per-task cost cap flag, hook hardening, CLI-owned Discord re-arm architecture, and AI-ecosystem gap audit. Component bumps: cc 1.6.0, tc 1.3.0.

### Added

- **`cc eval` — regression-eval harness** (`tools/cc/`): cross-version regression suite for framework agents. Authors write golden cases in `.claude/evals/<agent>/*.yaml` (input prompt + expected output criteria); `cc eval run [--agent <name>]` executes them via a pluggable pure-Python runner, scores each case, and persists results to `cc memory` for longitudinal tracking. Gate pattern: failing evals on a `cc` or `tc` VERSION.json bump blocks the bump from merging. See `tools/cc/README.md` → Eval section.
- **`--max-budget-usd <float>` dispatch flag** (`tools/tc/`): per-task cost-cap annotation on `tc task create` and `tc task claim`. The flag plumbing is live (stored in task metadata); enforcement (rejecting a dispatch that would exceed the cap) is a roadmap P1 item. See `tools/tc/README.md` → tc worker section.
- **AI-ecosystem gap audit report** (`docs/70-reference/ai-ecosystem-research-methodology.md`): cross-product documentation gap inventory produced during the 5.12.0 initiative cycle. WP-173 is the machine-readable form; the committed file is the human-readable reference.

### Changed

- **`pretool-check.sh` hook hardening** (`.claude/hooks/pretool-check.sh`): deny-reason output is now always visible in the hook response (`python3 -c` replaced with `jq` for JSON reads, eliminating the silent-deny regression introduced in 5.11.0). Agents now see the exact rule that fired rather than a blank rejection.
- **Discord re-arm architecture** — re-arm loop ownership moved from `CLAUDE.md` behavioral instruction to a registered Claude Code Stop hook (`cli-copilot discord install-hook`). The behavioral instruction in `CLAUDE.md` remains as a fallback description; the Stop hook is the runtime mechanism. Pairs with new `cli-copilot` commands `handoff --await`, `stop-hook`, `discord close`, and `COPILOT_DISCORD_LOOP=off` escape (documented in `cli-copilot` README; see the companion instruction-set WP for details).

### Architecture

- **cc 1.6.0**: `cc eval` command family (`eval run`, `eval list`, `eval add`, `eval show`); eval runner and `.claude/evals/` golden-case convention; score persistence to `cc memory`
- **tc 1.3.0**: `--max-budget-usd` flag on `task create`/`task claim`; `tc worker` dispatch surface (enforcement is roadmap P1)

## [5.11.0] - 2026-06-25

Safety primitives, cross-model adversarial QA, CONFUSED loop-state, HTML work-product renderer, and `cc memory export`. Inspired in part by **gstack** (Garry Tan, `github.com/garrytan/gstack`, MIT) and **"The Unreasonable Effectiveness of HTML"** (Thariq Shihipar, Anthropic Engineering Blog) — see ADR-004.

### Added

- **HTML work-product renderer** (`tools/tc/src/tc/services/render_html.py`, `tc wp render <id> --html`): renders any work product to a fully self-contained HTML file at `.copilot/renders/WP-<id>.html` (inline CSS, vanilla JS, no CDN). Token-free side artifact — the CLI prints only the absolute file path; the HTML body never enters the context window. Auto-detects three templates: severity (P0/P1/P2/CRITICAL/HIGH/MEDIUM/LOW color-coding + legend), variant-grid (≥ 2 option/variant/approach headings → tabbed comparison), and rendered-diff (` ```diff ` block or ≥ 3 diff lines → syntax-highlighted viewer). All renders include "Copy as Markdown" and "Copy as JSON" buttons. Zero new PyPI dependencies. Inspired by gstack's `/design-html` side-artifact pattern and the HTML-output-with-copy-buttons approach from Thariq Shihipar's Anthropic blog post.
- **Safety primitives — `/careful` and `/freeze`** (`.claude/hooks/pretool-check.sh`, `.claude/hooks/security-rules.json`, `.claude/hooks/bin/freeze.sh`): two new PreToolUse rule functions. `/careful` (`rule_destructive_command`) reads `security-rules.json` at runtime and blocks (`action: block`, exit 2) or warns (`action: warn`, stderr + exit 0) on matching Bash commands (patterns include `git push --force`, `rm -rf`, `git reset --hard`, `git clean -f`, `chmod -R`). `/freeze` (`rule_path_scope`) locks Edit/Write/Bash to a declared directory tree (state: `.claude/hooks/state/.freeze`; managed via `.claude/hooks/bin/freeze.sh on|off|status`). Escape hatches: `COPILOT_CAREFUL=off`, `COPILOT_FREEZE=off`, `COPILOT_SAFETY=off` (disables both). Inspired by gstack's `/careful` and `/freeze` primitives; reimplemented natively in bash/jq.
- **Cross-model adversarial QA pass** (`.claude/hooks/bin/adversarial-pass.sh`): optional "try to break this diff" pass that @agent-qa can run after its own verification. Availability-gated: checks `COPILOT_ADVERSARIAL_CMD` env var, then PATH-probes for `codex`, `llm`, `mods`; clean no-op if none found. New `adversarial-run` ARTIFACT type recognized by `subagent-stop.sh` alongside `test-run`, `file-check`, `diff-check` — satisfies the artifact requirement on its own but is never a new mandatory gate. Config: `COPILOT_ADVERSARIAL_CMD`, `COPILOT_ADVERSARIAL_TIMEOUT` (default 30 s), `COPILOT_ADVERSARIAL=off`. Inspired by gstack's cross-model adversarial review (`/codex` second-opinion pass); reimplemented natively.
- **`<promise>CONFUSED</promise>` loop-state** (`CLAUDE.md`, `me.md`, `ta.md`, `do.md`, `sec.md`, `qa.md`, `subagent-stop.sh`): in-flight decision-point signal for agents that hit a genuine decision fork requiring user judgment. Distinct from `<promise>BLOCKED</promise>` (technical blocker / unmet dependency). When emitted, `subagent-stop.sh` surfaces it to the user instead of activating the QA gate. Added to `completionPromises` in all agents that carry BLOCKED. Inspired by gstack's Confusion Protocol; adapted to the Copilot loop-state model.
- **`cc memory export`** (`tools/cc/src/cc/commands/memory.py`): export memory entries to a portable Markdown or JSON bundle. `cc memory export` (all entries, Markdown); `--json` (JSON array); positional query (keyword-filtered via FTS); `--type` (type-filtered); `--all` (explicit all); `--out <path>` (write to file). Type and keyword filters compose.

### Changed

- **CLAUDE.md**: added `tc wp render <id> --html` to Task Copilot commands; added `cc memory export` to memory commands; updated Testing Gate to list `adversarial-run` as a fourth ARTIFACT type; added safety primitives (`/careful`, `/freeze`, escape hatches) to the Main Session Guardrails enforcement paragraph; CONFUSED and Confused Loop-State already present from prior me-agent pass (no change)
- **`tools/tc/README.md`**: added `tc wp render` to the `tc wp` command section; added HTML rendering template reference table; added `render_html.py` to layout
- **`tools/cc/README.md`**: added `cc memory export` examples to the Memory section; updated layout to reflect `export` in `memory.py`
- **`.claude/hooks/README.md`**: safety primitives, adversarial pass, and CONFUSED/BLOCKED guards documented in prior me-agent pass (no change needed)
- **tc component**: `render_html.py` added; `wp.py` extended with `render` subcommand; `api.py` exports `render_wp_html`
- **cc component**: `memory.py` extended with `export` subcommand
- **Agents component**: `me.md`, `ta.md`, `do.md`, `sec.md`, `qa.md` updated with `<promise>CONFUSED</promise>` in `completionPromises`

### Attribution

- **gstack** by Garry Tan (`github.com/garrytan/gstack`, MIT) — inspiration for `/careful`+`/freeze` safety primitives, cross-model adversarial review, the `/design-html` side-artifact pattern, and the Confusion Protocol. Concepts adopted natively; no code copied.
- **"The Unreasonable Effectiveness of HTML"** by Thariq Shihipar (Anthropic Engineering Blog) — inspiration for HTML-as-output-format with "Copy as Markdown/JSON" buttons and variant-grid comparison layouts. Concepts adopted natively; no code copied.

### Architecture

- **ADR-004** (`docs/10-architecture/05-adr-004-html-output-format.md`): records the decision to use HTML as a work-product output format, alternatives rejected, and full attribution.

## [5.10.0] - 2026-06-17

Framework hardening initiative (PRD-7): four workstreams closing drift/verification gaps — failable QA gate, memory drift detection, usage observability, and declarative agent manifest.

### Added

- **WS1 — Failable-check QA gate** (`qa.md`, `sec.md`, `subagent-stop.sh`, `pretool-check.sh`): QA verdicts must now name an external artifact (`ARTIFACT: <type>|<detail>` — one of `test-run`, `file-check`, `diff-check`). A bare `VERDICT: APPROVED` with no artifact line does NOT unblock the gate. `@agent-sec` accumulates warnings silently up to a threshold (3) before halting, preventing over-flagging on minor advisory items.
- **WS2 — `cc memory check`** (`tools/cc/`): token-free deterministic drift detection for memory/WP entries. Checkers: `path-exists`, `command-resolves`, `version-conflict`, `staleness`. 0–100 score (100 − fail×10 + warn×3 + info×1); exits 1 on any `fail`-severity finding. Negation-aware: paths under "not yet built", "removed", "deprecated" sections are not flagged.
- **WS3 — `cc usage` + session quota statusline** (`tools/cc/`): idle-gated quota probe using Keychain OAuth + 1-token probe, reads `anthropic-ratelimit-unified-*` response headers. Producer/consumer split (ADR-003): `cc usage` writes `~/.claude/session-usage.json`; session-start hook reads the cache without probing. Transcript-reconstruction fallback for offline/non-macOS.
- **WS4 — Declarative agent manifest** (`.claude/agents/manifest.json`): single source of truth for agent roster, routing edges, and tool grants. Consumed by the session-start banner, `pretool-check.sh` force-delegate agent list, and `/protocol`. Fixes stale banner (removes retired `design` agent and setup-only `kc` from the framework-agent list).

### Changed

- **Agents component → 5.5.0**: `qa.md` (artifact-gated verdicts), `sec.md` (warning-accumulation threshold), manifest-driven session-start banner (`session-start.sh`)
- **cc component → 1.4.0**: new `cc memory check` (WS2) and `cc usage` (WS3) subcommands
- **commands component → 5.3.2**: `/memory` command updated to reference `cc usage`
- **CLAUDE.md**: agent count corrected to 15 framework agents + kc (setup-only); manifest named as authoritative roster; `cc memory check` and ARTIFACT gate requirement documented

## [5.9.0] - 2026-06-13

Adds a re-plan-on-invalidated-assumption trigger to `@agent-me` and `@agent-ta`, closing a forward-only-flow gap identified during a review of mrtooher/fable-mode.

Previously the agent chain was strictly forward: `ta → me → qa`. When `@agent-me` encountered a broken upstream assumption (infeasible approach, wrong constraint, incorrect architecture), the only options were to improvise a workaround or emit `BLOCKED` for human intervention. This left the task graph diverged from reality — patch-tasks stacked on a broken foundation, drift accumulating silently.

### Added

- **Re-plan loop: @agent-me → @agent-ta** (`me.md` **Never** bullet): when the planned approach, architecture, or constraint from @agent-ta proves wrong or infeasible, @agent-me now STOPs, surfaces the invalidated assumption explicitly, emits `<promise>BLOCKED</promise>`, and routes back to @agent-ta to re-plan — rather than improvising a workaround that diverges from the task graph
- **Re-plan self-critique: @agent-ta** (`ta.md` **Self-Critique**): when a downstream finding from @agent-me or @agent-qa invalidates an upstream assumption, @agent-ta now explicitly re-plans affected tasks and dependencies rather than appending patch-tasks on top of a broken foundation
- **BLOCKED signal table updated** (`docs/50-features/04-goal-driven-agents.md`): added "Invalidated upstream assumption" row documenting the new @agent-me → @agent-ta backward route

### Changed

- **Agents component bumped to 5.4.0**: behavioral change in `me.md` and `ta.md`; no cc/tc source changes (cc 1.3.0 / tc 1.1.0 unchanged)

## [5.8.0] - 2026-06-09

Framework-wide remediation: completed the migration off the MCP tool API removed in
v5.0.0, retired the broken Python orchestrator, and fixed runtime/CI/doc gaps surfaced
by a full audit. No `cc`/`tc` source changes (components stay cc 1.3.0 / tc 1.1.0).

### Removed
- **Python orchestration layer retired in full** — deleted `.claude/orchestrator/` and `templates/orchestration/` (`orchestrate.py`, `task_copilot_client.py`, `monitor-workers.py`, `start-ready-streams.py`, `check_streams_data.py`, shell wrappers, `validate-setup.py`, guides; ~12.6K lines). `task_copilot_client.py` queried a removed SQLite `initiative` schema and crashed against the current `tc` backend; the CHANGELOG-claimed `subprocess(["tc", ...])` rewrite never landed. `/orchestrate` is now native-`Task`-only.
- **Dead integration test suites** (`tests/integration/*.test.ts` for initiative/correction/stream-unarchive) and their README/summary.
- **Duplicate `docs/EXTENSION-SPEC.md`** (consolidated into `docs/40-extensions/00-extension-spec.md`).

### Changed
- **Slash-command flows migrated to the `cc`/`tc` CLIs** — `/protocol`, `/continue`, `/pause`, `/config`, `/knowledge-copilot`, `/orchestrate` (+ templates). Removed-concept mappings: `initiative_*`/`checkpoint_*` → file-based memory + `tc task --status paused`; `progress_summary` → `tc progress`; `task_*`/`prd_*`/`stream_*`/`work_product_get` → `tc`; `memory_*` → `cc memory`; `skill_get`/`skill_evaluate` → `cc skill`.
- **`/reflect` repurposed** from the removed `correction_*` queue to a `cc memory` review command (matching its feature doc).
- **`/orchestrate` rewritten to native execution** — `generate`/`status`/`merge` via `tc` + plain `git worktree`/`git merge` (dead `worktree_*` MCP calls removed); `start` scaffolds worktrees and prints launch instructions for native `Task` agents.
- **`CLAUDE.template.md`** corrected to the real 16-agent roster (was "11 specialists"; removed non-existent `cmo`/`ccro`, restored `cco`/`ind`).
- **Skills discoverability** — `documentation/tutorial-patterns` converted to `SKILL.md` directory form; duplicate flat `copywriting/voice-and-tone.md` folded into canonical `voice-tone/SKILL.md`.
- **Security-hooks docs** corrected to reflect what `pretool-check.sh` actually enforces (force-delegate + qa-gate); `security-rules.json` flagged as present-but-unwired.
- **`_archive/` agents** scrubbed of removed-tool references.

### Fixed
- **SessionStart hook wired** in `settings.json` (+ `plugin.json`) — the protocol-injection guardrail was silently never firing for clone/plugin installs.
- **Version-sync CI guard restored** — `plugin.json`/`marketplace.json` corrected from a stale 5.2.0; `check-manifest.py` now derives the expected agent roster from `VERSION.json` instead of hard-coding the retired `design` agent.
- **`/update-project` existence check** now gates on `.claude/` presence, not `.mcp.json` — projects without MCP servers (the norm post-CLI-migration) are no longer misreported as un-set-up.
- **Invalid CLI flags** in docs/commands corrected: `cc memory list --limit`/`--verbose`, `tc task update --notes` (none exist).
- **~40 broken internal doc links** repaired (post-restructure stale paths); `docs/README.md` index gaps filled.
- **Agent metadata** — `cs` reconciled to "Sales Advisor"; glossary agent-count corrected.
- **`CONTRIBUTING.md`** dev-setup updated from the removed `mcp-servers/` build to the `cc`/`tc` install path.

## [5.7.0] - 2026-06-08

### Added
- **Live Docs — `cc docs` command family** (`tools/cc/`): agents now fetch version-exact documentation for installed packages instead of relying on stale training-data memory; `@agent-me` and `@agent-ta` are wired to reach for `cc docs get <pkg>` before implementing against any third-party API; closes the silent correctness gap where agents code confidently against APIs that moved between their training cutoff and the project's installed version
  - **Verbs:** `cc docs get <pkg>` (main — returns relevant docs slice), `cc docs resolve <pkg>` (print detected version + source), `cc docs search <pkg> <query>` (keyword search within cached docs), `cc docs sources` (list all registered source backends), `cc docs cache --status|--clear [<pkg>]` (inspect or flush the local cache)
  - **Local-first source order:** (1) installed package files on disk (primary — version-exact, fully offline); (2) fetch fallback (`httpx` extra only) — tries `llms.txt`, then GitHub raw at the version tag, then the package's docs site; core install stays network-free
  - **Honest version flag:** every `cc docs get` response includes `exact: bool` — `true` when docs were sourced from the installed version on disk, `false` when the fetch path was used (docs may lag by a patch)
  - **Gitignored cache** with configurable TTL (`docs.cache_ttl_hours`, default 168 h / 7 days)
  - **npm + pip** package ecosystems supported
  - **Optional `httpx` extra:** `pip install cc[fetch]` enables the network fallback; the base `pip install cc` install remains fully offline/headless
  - **Context7 deferred** (ADR-002): Context7 was evaluated and deliberately excluded — its external service dependency reintroduces the headless/offline fragility the local-first design avoids; a pluggable `SourceBackend` seam and reserved `docs.context7_endpoint` config key let it drop in later without interface changes
  - **CLAUDE.md shared behavior** added: agents check `cc docs` before implementing against installed third-party packages; me.md and ta.md updated with explicit pointers

### Changed
- **`cc` component version bumped to 1.3.0**: Live Docs is the only net-new surface in this component release; all other cc command families (memory, skill, config, env) are unchanged

[See feature page](docs/50-features/15-live-docs.md)

## [5.6.0] - 2026-06-04

### Added
- **`cc install.sh` auto-PATH** (`tools/cc/install.sh`): installer now automatically appends `~/.local/bin` to shell rc if not already on `PATH`; eliminates manual PATH configuration step after install

### Changed
- **Python floor raised to 3.9→3.10** (`pyproject.toml`, root `requires-python`): drops EOL Python 3.9; cc and tc already required 3.10 — root package now declares the same floor consistently
- **Black formatting applied** to all copilot-owned Python source files (no logic changes)

### Fixed
- **`setup-project` cc precheck** (`.claude/commands/setup-project.md`): distinguishes framework `cc` from system `/usr/bin/cc` (C compiler) so precheck no longer false-passes on machines without the framework CLI installed
- **`check-versions.sh` TypeError** (`.claude/fitness-check.sh` / version scripts): fixed TypeError that caused version validation to fail on clean installs
- **Smoke-test agent count** (CI): corrected assertion from 8 to 16 agents; stale integration-test assertions updated to match current CLI contracts
- **pytest config** (`pyproject.toml`): excludes vendored `claude_monitor` directory to prevent collection errors on test runs
- **uv.lock security patch**: resolved 35 vulnerability alerts in locked dependency tree

### Removed
- **`mcp-servers/` tree**: entire legacy MCP server implementation removed — framework fully migrated to cc/tc CLI
- **Legacy TypeScript test suite + `keyword-parser.ts`**: dead TS code removed; no replacement needed (functionality lives in Python)
- **Dead `.mjs` scripts**: stale ESM utility scripts with no callers removed
- **`packages/installer/`**: legacy NPM installer removed; `install.sh` is the sole install path

## [5.4.0] - 2026-06-04

### Added
- **`owner: project` agent preservation** (`update-project.md`, `setup-project.md`): agents with `owner: project` in their frontmatter are never overwritten by framework sync — project teams can customize or extend any agent file and that file is permanently preserved across updates and re-setups; `fitness-check.sh` FF3 recognizes the flag and passes retired agents that carry it as intentional project overrides

### Fixed
- **`fitness-check.sh` hyphenated agent names** (`.claude/fitness-check.sh`): FF1 and FF5 `@agent-X` regexes now correctly match multi-segment names (e.g. `@agent-line-editor`, `@agent-structural-editor`); prior regex stopped at the first hyphen, causing false orphan-route failures for any project-owned hyphenated agent
- **`fitness-check.sh` on-disk orphan resolution** (`.claude/fitness-check.sh`): FF5 now seeds `KNOWN_AGENTS` from the actual `.md` files present on disk in addition to the VERSION.json roster; project-owned agents (e.g. `critic.md`, `structural-editor.md`) are treated as known without requiring a roster entry or allowlist addition

### Changed
- **cs / cpa optional-advisory labeling**: `cs.md` (Customer Success) and `cpa.md` (Copywriting Assistant) documented as optional business-advisory agents — present in the roster but not required in every project's flow; references in docs and roster notes updated accordingly

## [5.3.0] - 2026-06-03

### Added
- **`fitness-check.sh` FF6** (`.claude/fitness-check.sh`): new fitness function scans repo-root `CLAUDE.md` for `@agent-design` literals and routing-stage uses of bare `design` (e.g. `→ design →`); false-positive-safe — ignores legitimate prose ("Atomic Design", "Design chain", "design tokens", "service design"); closes the guard gap that allowed stale design refs to slip through in the 5.3.0 restoration

### Changed
- **16-agent specialist roster restored**: `design` agent retired; full specialist chain restored — sd → uxd → uids → uid → ta → me with ind (Industrial Designer) and cco/cw (Creative Direction/Copywriting) as optional branches; sec, cs, cpa re-introduced as independent agents
- **Roster-aware update-project / setup-project**: no longer clobbers project-local agent customizations; syncs only agents in the current VERSION.json roster, skipping agents absent from the manifest
- **CLAUDE.md Use Case Mapping**: "Build a feature" row updated from stale `sd → design → ta → me → qa` to correct `sd → uxd → uids → uid → ta → me → qa` experience flow
- **CLAUDE.md Agent Shared Behaviors**: `Specification Workflow` bullet updated from `(sd, design)` to full specialist list `(sd, ind, uxd, uids, cco, cw)`

### Fixed
- Stale `@agent-design` and `design`-as-routing-stage references purged from CLAUDE.md; FF6 now catches this class of defect automatically on every fitness check run

## [5.2.0] - 2026-05-20

### Added
- **Opt-in semantic embeddings** (`cc memory search --semantic`): sentence-transformers backend wired behind `search.backend: semantic` config key; default remains `fts5` (keyword/BM25); zero behavior change for existing installs — no model downloaded unless explicitly enabled
- **Native plugin packaging** (`.claude-plugin/`): `plugin.json` manifest + `marketplace.json` for `/plugin install claude-copilot` distribution; `check-manifest.py` fitness guard added to CI; version field in both files now auto-validated against `VERSION.json.framework`
- **`check-manifest.py` CI guard**: validates agent/skill/command/hook paths, version sync between `plugin.json` and `VERSION.json`, marketplace→plugin manifest cross-reference, and `settings.json` clone-wiring integrity

### Changed
- **FTS5 stack unified**: `cc` and `tc` now share a single vendored `fts5_core` module; BM25 ranking available in `cc memory search` and `tc wp search`; removes duplicate trigram-index code that existed in both tools independently
- **Design-skill normalization**: 9 flat `.md` design skills migrated to `SKILL.md` directory format (matching all other skill categories); `cc skill search` and `@include` discovery now resolves them correctly; fixes the discoverability regression introduced in 5.0.0 skill restructure
- **Documentation modernization**: setup, update-project, and agent docs fully aligned to `cc`/`tc` CLI; all remaining MCP-era code snippets replaced; `CC_SHARED_DOCS` paths corrected throughout

### Fixed
- **`test_sentinel_resolution` hermetic fix** (`tools/tc/tests/`): test no longer relies on ambient `COPILOT_ROOT` env var; fixture now creates a hermetic temp dir with sentinel file so CI passes on clean machines without framework installed

### Removed
- Duplicate FTS trigram-index implementation in `tools/cc/src/cc/core/` (replaced by shared `fts5_core`)

---

## [5.1.0] - 2026-05-20

### Changed (Breaking)
- **Memory search renamed**: `cc memory search` now documented as FTS5/BM25 keyword search — "semantic search" language removed throughout; no embeddings or vector similarity; the `SearchBackend` seam exists for future opt-in embeddings (config-gated, default off)
- **`cc skill evaluate` removed**: confidence-scorer subcommand removed; native progressive skill discovery replaces it — use `cc skill search "<topic>"` to find skills by keyword, then `@include` the returned path
- **`@include` de-emphasized as primary**: `@include` remains the load mechanism, but `cc skill search` is now the discovery step; agents no longer call a separate evaluate step
- **MCP bridge retired from docs**: `cc mcp serve` still exists as an escape hatch but is no longer listed in `VERSION.json` provides[] or featured in setup docs

### Added
- **Code-bearing skills (L1/L2)**: Skills can now be directories containing an executable script (`run.sh` or `run.py`); script output enters context; implementation code does NOT; 16 skills converted to code-bearing form
- **Known References registry**: `cc config set refs.<name> <value>` registers stable paths/values; the `UserPromptSubmit` hook injects them at session turn 1 so every session starts with correct paths without manual re-supply; `type:reference` memory entries also surface at turn 1
- **Code-execution path (tc.api + cc.api)**: `tc.api` and `cc.api` Python facades over the services layer; agents performing 3+ related ops use a single `python3` block importing the facade instead of multiple CLI calls; eliminates round-trip token cost (~9-20K tokens saved for PRD+tasks batches)
- **QA-gate clearing fix**: `@agent-qa` pass verdict now correctly clears the gate state in `.claude/hooks/state/qa-gate.json`; 3-retry fallback to advisory after repeated hook failures
- **Coolify config-gate** (`tc deploy wait`): deploy command now gates on `CC_DEPLOY_CLI` config presence; fails fast with actionable message if not configured, instead of silently running wrong binary
- **100MB repository cleanup**: `.claude/skills/design/` and `.claude/skills/documentation/` large binary assets removed; replaced by code-bearing skill scripts that generate equivalent output on demand

### Removed
- `cc skill evaluate` subcommand and `--threshold` flag (confidence scorer removed; native discovery replaces it)
- 100MB of binary assets from `.claude/skills/design/` and `.claude/skills/documentation/`
- `KEYWORD_UPDATES_V2.8.md` root file (v2.8-era point-in-time doc; superseded by CHANGELOG 2.8.0)
- `STREAM-E-IMPLEMENTATION-SUMMARY.md` root file (one-off Stream-E summary; content preserved in CHANGELOG 2.8.0 and tc WP history)

---

## [5.0.2] - 2026-05-06

### Fixed
- **`cc skill` discovery** (`tools/cc/src/cc/core/skill_store.py`): follows symlinked skill directories so projects can bridge shared framework skills into `.claude/skills` without copying them

## [5.0.1] - 2026-05-06

### Fixed
- **`/setup` command** (`.claude/commands/setup.md`): removed MCP server build steps (Steps 4-5 that built `copilot-memory` and `skills-copilot` no longer exist); setup now installs `tc` and `cc` CLIs only; prerequisites reduced to Python 3 (Node.js no longer required)
- **`/update-project` command** (`.claude/commands/update-project.md`): Step 2 verification now checks for `cc` and `tc` CLIs instead of defunct MCP `dist/index.js` files; error message updated accordingly
- **Hook tests** (`tests/hooks/test-pretool-check.sh`): added Tests 12–14 for git push/pull allowlist, `COPILOT_FORCE_DELEGATE=off` escape hatch, and crash-fix regression

---

## [5.0.0] - 2026-05-06

### Changed (Breaking)
- **MCP servers removed**: `mcp-servers/copilot-memory/` and `mcp-servers/skills-copilot/` deleted from the repository — no MCP servers remain
- **Memory storage format**: from MCP server + PostgreSQL/SQLite to committed Markdown files at `.claude/memory/entries/<uuid>.md`; index is a local SQLite cache (`memory.db`, gitignored) rebuilt on demand
- **Skills access**: from MCP `skill_get`/`skill_search` tools to `cc skill get`/`cc skill search` CLI commands
- **Agent env hydration**: from `initiative_get`/MCP context to `eval "$(cc env)"` at agent start, which exports `CC_SHARED_DOCS`, `CC_KNOWLEDGE_REPO`, and other machine-level paths
- **VERSION.json**: `mcp-servers` section replaced with `cc` and `tc` component entries

### Added
- **`cc` CLI** (`tools/cc/`): unified Python CLI replacing both MCP servers
  - `cc memory store/get/list/delete/search/index` — persistent cross-session memory as committed files
  - `cc skill get/search/list/evaluate` — local and global skill discovery
  - `cc config get/set/list/init/doctor` — layered config (machine → project)
  - `cc env` — emits shell-eval-able `CC_*` exports for agent env hydration
  - `cc mcp serve` — optional MCP adapter so agents can still use MCP tooling if preferred
  - Installed at `~/.local/bin/cc` via `tools/cc/install.sh`

### Migration Guide (4.x → 5.0.0)

**Action Required:**

1. **Install `cc` CLI**:
   ```bash
   bash ~/.claude/copilot/tools/cc/install.sh
   cc config init --machine
   ```

2. **Initialize project memory directory**:
   ```bash
   mkdir -p .claude/memory/entries
   touch .claude/memory/entries/.gitkeep
   printf 'memory.db\nmemory.db-*\n' > .claude/memory/.gitignore
   cc config init --project
   ```

3. **Update all projects** with `/update-project` — this handles steps 2 automatically

4. **Remove MCP server entries** from `.mcp.json` (if you added them manually):
   - `copilot-memory` — delete this entry
   - `skills-copilot` — delete this entry
   - `.mcp.json` can be empty `{"mcpServers":{}}` or removed if no other servers remain

5. **Update agent calls**: replace `memory_store()`/`initiative_get()` MCP calls with `cc memory store` / `eval "$(cc env)"` CLI calls (agents in `.claude/agents/` are already updated)

**Breaking Changes:**
- `memory_store`, `memory_search`, `initiative_get`, `initiative_start`, `initiative_update`, `initiative_complete` MCP tools no longer exist
- `skill_get`, `skill_search`, `skill_list`, `skill_evaluate` MCP tools no longer exist
- The copilot-memory and skills-copilot MCP servers will not be found in `.mcp.json` — remove those entries to avoid connection errors at session start

---

## [4.0.1] - 2026-04-22

### Fixed
- **PreToolUse hook deadlock** (`.claude/hooks/pretool-check.sh`): matcher narrowed from `Bash|Read|Edit|Agent` to `Bash` only — a crashing hook previously blocked `Read` and `Edit`, making it impossible to repair without deleting the hook file
- **Hook paths**: replaced `$CLAUDE_PROJECT_DIR/...` with absolute paths — env var was not reliably expanded in hook subprocess environments
- **Hook fail-open**: replaced `set -euo pipefail` with `set -u` + ERR trap that exits 0 with a stderr warning — hook errors now degrade gracefully instead of blocking all tool use
- `git push`/`git pull` covered by `FORCE_DELEGATE_SAFE_PREFIXES` allowlist — never counted toward streak or force-delegate threshold

---

## [4.0.0] - 2026-04-22

### Changed (Breaking)
- Agent roster trimmed from 14 → 8 always-loaded agents: `me, qa, ta, do, sd, doc, design, kc`
- `uxd`, `uids`, `uid` merged into single `design` agent preserving Nielsen/Rams/Atomic framing
- `sec`, `cw`, `cco` demoted to skills (`stride-dread`, `voice-tone`, `litmus-test`); load via `@include`
- `cs`, `cpa` archived — no replacement agent
- Model tier inverted: strategy agents (`sd`, `design`, `ta`) run on Opus; execution agents (`me`, `qa`, `do`, `doc`) run on Sonnet
- Main-session model recommendation changed to Sonnet 4.6 1M via `.claude/claude-launcher`

### Added
- **PreToolUse hook — force-delegate rule** (`.claude/hooks/pretool-check.sh`): denies the 5th consecutive `Bash`/`Read`/`Edit` call and requires delegation to a framework agent
- **PreToolUse hook — QA gate rule**: after `@agent-me` completes, main session is blocked from all tool calls except `@agent-qa` until QA passes (file-based state machine in `.claude/hooks/state/qa-gate.json`)
- **SubagentStop hook** (`.claude/hooks/subagent-stop.sh`): sets QA-gate pending state when `@agent-me` stops; clears it when `@agent-qa` passes; 3-retry fallback to advisory after repeated failures
- **UserPromptSubmit hook** (`.claude/hooks/user-prompt-submit.sh`): advisory at 500 turns, stronger advisory at 750; prevents the 22-hour /continue context-bloat pattern
- **Flow E — Infrastructure** added to `/protocol`: `do → me → qa` chain triggered by `staging`, `deploy`, `coolify`, `docker`, `ci`, and related keywords; `--infra` flag overrides
- **`tc deploy wait`** subcommand (`tools/tc/src/tc/commands/deploy.py`): replaces hand-rolled `until curl` polling loops; shells out to `cli-copilot`'s Coolify commands; stores `deploy_report` work product; supports `--test <spec>` for post-deploy Playwright runs
- **`tc task update --title` and `--metadata`** flags: structured metadata updates with merge semantics (existing keys preserved, new keys added, conflicting keys overridden)
- **`.claude/claude-launcher`**: project-local bash wrapper that auto-loads Sonnet 4.6 1M; reads `.claude/.model` config file; `CLAUDE_MODEL` env var overrides
- **`.claude/settings.json`**: registers all three hooks with correct matchers
- Escape hatch env vars: `COPILOT_FORCE_DELEGATE=off`, `COPILOT_QA_GATE=off`, `COPILOT_SESSION_CAP=off`
- 349 new test assertions across 6 hook test suites
- `docs/10-architecture/04-framework-restructure-2026-04.md`: full diagnostic context (why, benefits, before/after data)
- `docs/30-operations/05-deploy-and-verify.md`: how-to guide for Flow E and `tc deploy wait`

### Motivation
Cross-session diagnostic (15 sessions, 18.3 MB, Apr 17–22 2026) found:
- 94% of tool calls were main-session-direct (6% delegated) — framework rules were advisory, not enforced
- 5-day staging saga: 4 sessions, 12 MB, 26 `until curl` polling loops, 57 back-to-back bash runs
- Protocol declarations appeared in 3.5% of assistant turns
- Model tier was wrong-way: orchestrator on Opus 4.7, specialists on Sonnet 4.6

## [3.5.0] - 2026-03-29

### Added
- Elite Craft methodology layer for uxd and uids agents (Jony Ive inevitable design, AKQA purposeful motion, spatial depth, luminosity, materiality)
- 3 premium design skills: premium-interaction-craft (GSAP, spring physics, micro-timing), spatial-luminous-design (depth layers, glassmorphism, atmospheric color), motion-choreography (easing personality, choreography, restraint)

### Changed
- Design agents now operate at three levels: Foundation (Nielsen/Rams), Methodology (IDEO), Elite Craft (Ive/AKQA)
- uxd.md self-critique elevated to "Would AKQA present this? Does it feel inevitable?"
- uids.md self-critique elevated to "Would Jony Ive call this inevitable?"

## [3.4.0] - 2026-03-29

### Added
- Named industry methodology for every agent: ADR/Fitness Functions (ta), Kent Beck's 4 Rules (me), STRIDE/DREAD (sec), Diátaxis (doc), 12-Factor/SRE (do), Atomic Design (uid), Meszaros/Property-Based Testing (qa), Voice & Tone (cw)
- 5 new skills: system-design-patterns, refactoring-patterns, threat-modeling, docker-patterns, voice-and-tone
- Anti-generic rules and self-critique questions for every agent
- Iteration config for cco agent

### Removed
- architect.md agent (was project docs for claude-monitor, not methodology)
- engineer.md agent (was project docs for claude-monitor, not methodology)
- tester.md agent (was project docs for claude-monitor, not methodology)

### Changed
- Agent count: 17 → 14
- Narrowed trigger_files for web-security and aesthetic-directions skills (were overly broad)

## [3.3.0] - 2026-03-29

### Removed
- CLAUDE_REFERENCE.md (761 lines, 50% duplicated with CLAUDE.md)
- CODE_REVIEW_OVERVIEW.md (stale Phase 1 review)
- docs/50-features/01-orchestration-guide.md (2-line stub)
- docs/50-features/03-auto-checkpoint-hooks.md (documented removed MCP tools)
- docs/50-features/lifecycle-hooks.md (documented removed hook_* tools)
- docs/60-references/ directory (empty placeholder, never populated)

### Changed
- CLAUDE.md consolidated from 464 to 260 lines (~5.7K fewer tokens per session)
- Unique content from CLAUDE_REFERENCE.md (Feature Comparison table, Session Boundary Protocol) merged into CLAUDE.md
- Fixed dangling references in 3 feature docs

## [3.2.0] - 2026-03-29

### Fixed
- Removed 137 hardcoded absolute user paths across 25 files
- All scripts now use portable path resolution ($REPO_ROOT, os.homedir(), Path.home())
- Documentation updated with relative paths

### Added
- Pre-commit hook (scripts/pre-commit-no-hardcoded-paths) to block future hardcoded user paths
- CI workflow (.github/workflows/no-hardcoded-paths.yml) as safety net

### Removed
- 8 redundant/personal scripts (update-all-projects.sh, verify-builds.py, test-build-*.sh, etc.)

## [3.1.0] - 2026-03-08

### Added

- **Design Knowledge Skills (`.claude/skills/design/`)**: 6 design skills providing concrete creative methodology
  - `color-palettes.md` — 25 named palettes by mood/industry, anti-generic bans, dark mode derivation, WCAG contrast reference
  - `typography-pairings.md` — 30 curated font pairings, 3 type scale systems, fluid typography formulas
  - `aesthetic-directions.md` — 20 named aesthetic directions, industry selection matrix, 15-item AI anti-slop detector
  - `design-heuristics.md` — Rams' 10 Principles rubric, Nielsen's 10 Heuristics checklist, Three Lenses evaluation, senior vs junior thinking
  - `design-patterns.md` — Component state matrices, spacing scales, WCAG requirements (from templates)
  - `ux-patterns.md` — Task flow structures, service blueprints, accessibility checklists (from templates)

### Changed

- **Design Agents Upgraded to AKQA/IDEO Quality**:
  - `sd.md` (64 → 154 lines) — Added Double Diamond, JTBD, Moments Framework, Three Lenses, mandatory 7-step creative process, 6 anti-generic NEVER rules, quality evaluation criteria
  - `uxd.md` (63 → 184 lines) — Added Fitts/Hick/Jakob/Miller laws, Crazy Eights divergence, microinteraction anatomy, error prevention hierarchy, loading strategy decision tree, 9 anti-generic NEVER rules
  - `uids.md` (72 → 233 lines) — Added Bold Commitment First philosophy, Rams' Principles, mandatory 11-step creative process with aesthetic direction commitment, concrete design knowledge (spacing/radius/elevation/motion/sizing), AI Slop Detector, Innovative/Controlled dual-mode
  - All three agents now include: iteration config, validation rules, diverge-before-converge creative process, self-critique loops, and design skill references
- **Agent count**: 20 → 17 (removed 3 legacy agents)
- **VERSION.json**: Updated to v3.1.0 with new agent counts, design skill category added

### Removed

- **Legacy design agents**: Deleted `service-designer.md`, `ux-designer.md`, `ui-designer.md` (hardcoded to specific project, never referenced by framework routing)

## [3.0.0] - 2026-02-21

### Added

- **`tc` CLI Tool (`tools/tc/`)**: New Python + Typer + Rich CLI replacing the Task Copilot MCP server for all task management operations
  - Full CRUD for PRDs, streams, tasks, and work products
  - Atomic task claiming with `BEGIN IMMEDIATE` for safe concurrent agent access
  - Dependency-aware `tc task next` for automatic task sequencing
  - FTS5 full-text search on work products via `tc wp search`
  - Hybrid storage: content <100KB in SQLite, >100KB on disk at `.copilot/wp/`
  - Agent handoff tracking via `tc handoff` with activity log
  - `tc watch` live terminal dashboard (Rich Live + Layout) for monitoring parallel streams
  - `tc progress` for per-stream and overall progress summaries
  - `tc db stats` and `tc db path` for database introspection
  - Project-local `.copilot/tasks.db` with SQLite WAL mode and busy_timeout for concurrency

- **Pytest Test Suite (`tools/tc/tests/`)**: 225 tests at 97% coverage on active code
  - 10 test files covering all commands and modules
  - Atomic claiming, double-claim prevention, dependency resolution, FTS search, hybrid storage

### Changed

- **Task Copilot: MCP to CLI Migration** (BREAKING): All 55 MCP tool schemas replaced with `tc` CLI commands via Bash
  - Eliminates ~4,600 tokens of MCP tool schema overhead per agent session
  - No long-running MCP server process, no stdio pipe failures, no timeout errors
  - Agents call `tc <command> --json` via Bash tool instead of MCP function calls
  - Memory Copilot and Skills Copilot MCP servers unchanged
- **14 Agent Files**: All `.claude/agents/*.md` frontmatter and workflows migrated from MCP tool calls to `tc` CLI commands
- **5 Command Files**: `protocol.md`, `orchestrate.md`, `continue.md`, `memory.md`, `pause.md` migrated to `tc` CLI
- **CLAUDE.md and CLAUDE_REFERENCE.md**: Task Copilot sections rewritten for `tc` CLI
- **15 Documentation Files**: All `docs/` files migrated from MCP function-call syntax to `tc` CLI commands
- **Orchestrator Client Rewritten**: `.claude/orchestrator/task_copilot_client.py` uses `subprocess.run(["tc", ...])` instead of direct SQLite
- **`tc watch` Replaces `watch-status`**: Self-contained dashboard eliminates symlink path resolution errors across projects

### Removed

- Task Copilot MCP tool dependencies from agent frontmatter: `iteration_start`, `iteration_validate`, `iteration_next`, `iteration_complete`, `checkpoint_create`, `checkpoint_resume`, `hook_register`, `hook_clear`, `preflight_check`, `validation_config_get`
- Agents now self-manage iteration loops using standard tools (Bash for tests/compile, `tc` for state)

## [2.10.0] - 2026-02-20

### Added

- Stream token budgets, path ownership, security hardening

## [2.9.0] - 2026-02-12

### Added

- **Multi-Agent Foreman Architecture**: Each stream now coordinates multiple specialist agents
  - Foreman agent (`general-purpose`) spawned per stream as coordinator
  - Phase-based intra-stream parallelism: backend → frontend → quality → docs → devops → integration
  - Specialists run in parallel within each phase via `Task(run_in_background: true)`
  - Automatic QA + Security review phases generated per stream
  - Foreman prompt template at `.claude/orchestrator/foreman-prompt.md`

- **Agent Assignment Rules**: Tasks auto-assigned to correct specialist agents
  - `me` for backend APIs, business logic, data models
  - `uid` for frontend pages, component wiring, UI integration
  - `ta` for architecture, schema design, system contracts
  - `qa` for test suites, edge cases, coverage
  - `sec` for security review, auth flows, input validation
  - `doc` for technical docs, API docs, setup guides
  - `do` for CI/CD, deployment, infrastructure

- **Task Phase Metadata**: Every task includes execution phase
  - Defines intra-stream ordering: backend → frontend → quality → docs → devops → integration
  - Parallel execution within phases, sequential between phases
  - Used by Foreman agents to coordinate specialist spawning

### Changed

- **Status Dashboard**: Derived entirely from Task Copilot data (no PID/log dependencies)
  - Removed PID file detection and log parsing from `check-streams`
  - New status codes: RUN (active tasks), DONE (100%), BLK (blocked), IDLE (partial progress)
  - Simplified footer: `Data: Task Copilot + Memory Copilot (initiative-scoped)`
  - `watch-status` simplified: removed auto-restart logic and worker monitoring

- **`/orchestrate start`**: Now launches Foreman agents instead of single workers
  - Each stream gets a Foreman that coordinates multiple specialists
  - Replaced flat worker model with hierarchical Foreman → Specialist pattern
  - Inter-stream dependencies still respected (Foreman waits for dependency streams)

- **`/orchestrate generate`**: Includes agent assignment and phase metadata
  - Agent Assignment Rules table enforces correct specialist selection
  - Phase metadata required on every task for intra-stream ordering

### Removed

- PID-based worker detection from status dashboard
- Log file parsing and runtime tracking from `check-streams`
- Auto-restart logic from `watch-status`
- `worker-wrapper.sh` dependency for stream execution (replaced by native Task agents)

## [2.8.0] - 2026-01-26

### Added

- **OMC Features - Five Productivity Enhancements**:
  - **Ecomode**: Smart model routing (haiku/sonnet/opus) based on complexity scoring
    - Automatic complexity analysis from task title, description, file count, agent type
    - Modifier keywords for explicit overrides: `eco:`, `opus:`, `fast:`, `sonnet:`, `haiku:`
    - Cost optimization: < 0.3 complexity → haiku, 0.3-0.7 → sonnet, > 0.7 → opus
    - Model router at `mcp-servers/task-copilot/src/ecomode/model-router.ts`

  - **Magic Keywords**: Action keywords for quick agent routing and task type detection
    - Supported: `fix:`, `add:`, `refactor:`, `optimize:`, `test:`, `doc:`, `deploy:`
    - Suggests agent routing (e.g., `fix:` → @agent-qa, `add:` → @agent-me)
    - Combines with modifiers: `eco: fix: login bug` or `fast: doc: API`
    - Parser at `.claude/commands/keyword-parser.ts`
    - False positive prevention (e.g., "economics:" not matched)

  - **Progress HUD**: Live statusline with task progress, model, and token estimates
    - Format: `[Stream-A] ▶ 50% | sonnet | ~1.2k tokens`
    - Unicode progress indicators (⏸ pending, ▶ in progress, ⚠ blocked, ✓ completed)
    - Color-coded model display (green haiku, yellow sonnet, magenta opus)
    - Statusline component at `mcp-servers/task-copilot/src/hud/statusline.ts`
    - Event-driven updates via `StatuslineUpdater` class

  - **Skill Extraction**: Auto-detect repeated patterns and suggest skill creation
    - Detects file patterns, keyword patterns, workflow patterns, best practices
    - Confidence scoring for pattern candidates
    - Pattern detection at `mcp-servers/copilot-memory/src/tools/pattern-detection.ts`
    - Review and approval via `/skills-approve` command
    - Auto-generates skill files with triggers and quality checklists

  - **Zero-Config Install**: One-command installer with dependency auto-fix
    - `npx claude-copilot install --global --auto-fix` for complete setup
    - Auto-detects missing dependencies (Node.js, Git, build tools)
    - Platform-specific fixes: Homebrew (macOS), apt/dnf/pacman (Linux)
    - Commands: `check` (dependencies), `validate` (installation), `install` (setup)
    - Installer package at `packages/installer/`

- **OMC Feature Types**:
  - New type definitions at `mcp-servers/task-copilot/src/types/omc-features.ts`
  - Interfaces: `ComplexityScore`, `ModelRoute`, `ModifierKeyword`, `ActionKeyword`
  - Interfaces: `ParsedCommand`, `StatuslineState`, `ProgressEvent`, `PatternCandidate`

- **Integration Tests**:
  - Comprehensive test suite at `tests/integration/omc-features.test.ts`
  - Tests all 5 features individually and in integration
  - 40+ test cases covering edge cases and workflows

### Changed

- **SETUP.md**: Zero-config install now primary method (manual setup alternative)
- **CLAUDE.md**: Added "OMC Features" section with usage examples and quick reference

### Documentation

- Added OMC features overview in CLAUDE.md with usage patterns
- Updated SETUP.md with npx installer as recommended approach
- Comprehensive test coverage for all features
- Feature documentation includes benefits and practical examples

### Acknowledgements

- Inspired by [Oh My Claude Code](https://github.com/code-yeongyu/oh-my-opencode) by @code-yeongyu
- Ecomode concept adapted from OMC's ralph/auto routing
- Magic keywords adapted from OMC's action prefixes
- Progress HUD adapted from OMC's statusline
- Skill extraction adapted from OMC's pattern learning
- Zero-config install adapted from OMC's setup simplification

## [2.7.1] - 2026-01-17

### Changed

- **Update Project Command**: Improved messaging to clarify what gets updated
  - Shows orchestrator update status when `.claude/orchestrator/` exists
  - Clearer summary of refreshed vs preserved files

## [2.7.0] - 2026-01-17

### Added

- **Experience-First Protocol Redesign**:
  - Flipped default routing from technical-first to experience-first (sd → uxd → uids → ta → me)
  - Four flow types: Experience (default), Defect, Technical, Clarification
  - Checkpoint system with explicit approval required (~100 token summaries)
  - 50-char handoff context between agents
  - Skip warnings when bypassing design stages
  - Single `/protocol` entry point with smart intent detection (no command proliferation)
  - All 6 relevant agents updated with checkpoint templates

- **Experience-First Orchestration**:
  - `/orchestrate generate` now uses experience-first workflow by default
  - `--technical` flag to skip design stages for technical-only work
  - 4-stage flow: @agent-sd → @agent-uxd → @agent-uids → @agent-ta with checkpoints
  - sourceSpecifications traceability in tasks (links back to design work products)
  - Technical keyword detection with user confirmation

- **Task Copilot Client Enhancements**:
  - `archive_initiative_streams()` - Archives stream tasks when initiative completes
  - `complete_initiative()` - Marks initiative as COMPLETE in Memory Copilot

### Changed

- **Protocol Routing**: Intent detection now looks for technical/defect exceptions rather than experience indicators
- **Agent Summaries**: All design agents (sd, uxd, uids, ta, qa, me) output standardized checkpoint summaries
- **Orchestration**: `/orchestrate generate` validates workflow mode before task creation

### Documentation

- Added service design specification: `docs/specifications/protocol-redesign-service-spec.md`
- Added testing guide: `docs/specifications/protocol-redesign-testing-guide.md`
- Updated CLAUDE.md with Protocol Flow System documentation

## [2.3.1] - 2026-01-13

### Added

- **Orchestration Initiative Lifecycle Management**:
  - Initiative-scoped stream filtering in `orchestrate.py`
  - Auto-completion detection when all streams reach 100%
  - Automatic stream archival on initiative completion
  - `initiative_complete()` integration with Memory Copilot
  - PRD-scoped `stream_unarchive()` prevents cross-initiative pollution

- **Mandatory Generation Verification**:
  - `/orchestrate generate` verifies PRDs/tasks exist after @agent-ta
  - Clear error messaging when verification fails
  - Retry mechanism with stronger tool enforcement
  - `initiative_link()` called before PRD creation (archives old streams)

- **File Management Improvements**:
  - Orchestrator file creation moved from `start` to `generate`
  - `start` command only verifies files exist (doesn't create)
  - `watch-status` symlink created at project root by `generate`
  - Completion callback in watch-status with celebration banner

- **Lean Agent + Deep Skills Architecture**:
  - Agents refactored from 400+ tokens to 60-100 tokens (67% reduction)
  - Domain expertise moved to loadable skill files
  - `skill_evaluate()` for context-aware skill detection
  - TF-IDF-based confidence scoring for skill relevance
  - Skills support `trigger_files` and `trigger_keywords` patterns
  - 11+ deep skills created across code, testing, architecture, security, devops, design

- **Integration Tests**:
  - Orchestration lifecycle tests (generate → start → complete)
  - Initiative switch and stream archival tests
  - Hooks, evaluation, and correction detection tests

### Changed

- **Agent Count**: Updated from 12 to 13 agents throughout documentation
- **Agent Model**: All agents now use lean model with on-demand skill loading
- **Documentation**: Comprehensive alignment with new architecture
- **Acknowledgements**: Added Lean Agent + Deep Skills pattern attribution

### Technical

- New methods in `task_copilot_client.py`: `get_active_initiative_id()`, `archive_initiative_streams()`, `complete_initiative()`
- Initiative filtering in `_query_streams()` and `_get_stream_status()`
- Watch-status completion detection and auto-exit
- 1,200+ lines changed across orchestrator, agents, skills, and documentation

## [2.2.0] - 2026-01-12

### Added

- **Confidence Scoring for Work Products** (P0):
  - `work_product_store()` accepts optional `confidence` parameter (0-1 scale)
  - `progress_summary()` filters by `minConfidence` with stats
  - Agents (ta, qa, sec) include confidence guidance tables
  - Database migration v9 adds confidence column

- **PreToolUse Security Hooks** (P0):
  - Secret detection (AWS keys, GitHub tokens, passwords)
  - Destructive command prevention (`rm -rf`, `DROP TABLE`)
  - Sensitive file protection (`.env`, credentials)
  - MCP tools: `hook_register_security`, `hook_test_security`, `hook_list_security`
  - Configurable rules via `.claude/hooks/security-rules.json`

- **SessionStart Protocol Injection** (P1):
  - Protocol guardrails injected directly at session start
  - Violation tracking with severity levels (low/medium/high/critical)
  - MCP tools: `protocol_violation_log`, `protocol_violations_get`
  - `/memory` command shows violation counts and recent violations

- **Context-Triggered Skill Auto-Invocation** (P1):
  - Skill manifest supports `triggers: { files, keywords }`
  - `skill_auto_detect()` MCP tool detects matching skills
  - Example skills updated with trigger definitions
  - Scoring algorithm ranks triggered skills

- **Auto-Checkpoint Hooks** (P2):
  - Checkpoints automatically created at start of each iteration
  - Optional checkpoint on iteration validation failure
  - Simplified agent prompts - no manual `checkpoint_create()` calls needed
  - Backwards compatible - manual checkpoints still work
  - New `src/hooks/auto-checkpoint.ts` module

### Changed

- **Skills Copilot Marked Optional** (P2):
  - Native `@include` directive documented as primary method
  - Skills Copilot MCP only needed for marketplace/database access
  - CLAUDE.md, SETUP.md, README updated with guidance

- **Agent Prompts Simplified**:
  - Removed manual checkpoint instructions from iteration loops
  - Added confidence scoring guidance to ta, qa, sec agents
  - `checkpoint_create()` marked optional in CLAUDE.md

### Technical

- Database migrations: v9 (confidence), v10 (protocol_violations)
- New TypeScript modules: `hooks/`, `triggers.ts`, `protocol.ts`
- 62 files changed, +10,632 lines
- All modules compile and build successfully

## [2.1.0] - 2026-01-12

### Added

- **Orchestration Script Generation**: `/orchestrate generate` creates production-ready scripts
  - `orchestrate.py` - Main orchestrator with dynamic dependency resolution
  - `task_copilot_client.py` - Task Copilot data abstraction layer
  - `check_streams_data.py` - Stream data fetcher for bash scripts
  - `check-streams` - Colorful status dashboard (Bash 3.2+ compatible)
  - `watch-status` - Live monitoring with configurable refresh interval
  - Automatic workspace ID detection from project directory name
  - No hardcoded phases - execution order from task dependencies
  - Auto-restart failed workers with configurable limits

- **Orchestration Documentation**: Comprehensive guides
  - Updated `docs/50-features/01-orchestration-guide.md` (920+ lines)
  - Quick reference in `ORCHESTRATION_IMPLEMENTATION.md`
  - Clear dependency patterns and metadata format

### Changed

- **Orchestration Architecture**: Fully dynamic dependency resolution
  - Removed hardcoded foundation/parallel/integration phases
  - Streams execute based on `metadata.dependencies` arrays
  - Continuous 30s polling for newly-ready streams

### Technical

- New Python client for Task Copilot SQLite database
- Bash scripts use dynamic workspace detection
- Full symlink resolution in all generated scripts

## [2.0.0] - 2026-01-08

### Added

- **Parallel Stream Orchestration**: Run multiple Claude sessions simultaneously
  - `/orchestrate` command for headless parallel execution
  - `start-streams.py` template for automated stream management
  - `watch-status.py` for real-time terminal monitoring
  - Foundation → Parallel → Integration phase workflow
  - Automatic stream conflict detection

- **WebSocket Bridge**: New MCP server for real-time event streaming
  - `mcp-servers/websocket-bridge/` with JWT authentication
  - Live task status updates across sessions
  - Event subscription and filtering
  - Integration with Task Copilot events

- **HTTP API for Task Copilot**: REST endpoints for external integration
  - `/api/tasks`, `/api/streams`, `/api/activity`, `/api/checkpoints`
  - Python client library (`task_copilot_client.py`)
  - Enables dashboard and monitoring tools

- **New Project Commands** (5 new commands):
  - `/map` - Generate PROJECT_MAP.md with codebase analysis
  - `/pause [reason]` - Create checkpoint for context switching
  - `/orchestrate` - Parallel stream management
  - `/memory` - View current initiative state
  - `/extensions` - List agent extensions

- **Enhanced Pause/Resume**: Extended checkpoint expiry for manual pauses
  - `/pause` creates 7-day checkpoints (vs 24h for auto)
  - `/continue` checks pause checkpoints first
  - Named checkpoints with reason tracking

- **Progress Visibility Enhancements**:
  - ASCII progress bars in `progress_summary`
  - Velocity trends (7d/14d/30d) with directional indicators
  - Milestone tracking in PRDs

- **Worktree Conflict Handling**:
  - `worktree_conflict_status` tool
  - `worktree_conflict_resolve` tool
  - Git worktree manager utilities

### Changed

- **Major Version Bump**: 1.8.0 → 2.0.0 reflecting paradigm shift to parallel orchestration
- **Update Project Command**: Now copies 8 project commands (was 2)
- All MCP servers aligned to version 2.0.0

### Technical

- 18,246 lines of new code
- 91 compiled JavaScript files across 4 MCP servers
- 28 integration tests passing
- New event bus architecture in Task Copilot

## [1.7.1] - 2026-01-05

### Added

- **Stream Auto-Archive**: Streams automatically archive when switching initiatives
  - Prevents stream pollution when using `/continue` across different initiatives
  - `stream_list` and `stream_get` filter archived streams by default
  - Use `includeArchived: true` parameter to view archived streams
- **Stream Recovery Tools**:
  - `stream_unarchive`: Recover an archived stream to make it active again
  - `stream_archive_all`: One-time cleanup for legacy streams (requires `confirm: true`)
- **Task Protection**: Archived tasks cannot be updated (clear error with recovery instructions)

### Changed

- `initiative_link` now auto-archives streams from previous initiative when switching
- Database schema v6: Added `archived`, `archived_at`, `archived_by_initiative_id` columns to tasks table
- Updated `/continue` command documentation with archived stream handling

### Migration

After updating from pre-1.7.1, optionally run `stream_archive_all({ confirm: true })` once to clean up existing streams. Without this, legacy streams remain visible until you naturally switch initiatives.

## [1.7.0] - 2026-01-04

### Added

- **Context Engineering Features**: 6 enhancements from community research
  - **Self-improving Memory Schema**: Agents can store improvement suggestions via `agent_improvement` memory type with structured metadata (agentId, targetSection, currentContent, suggestedContent, rationale, status)
  - **Quality Gates Configuration**: Project-level `.claude/quality-gates.json` enforces automated checks (tests, lint, build) before task completion
  - **Activation Mode Detection**: Auto-detects work intensity from keywords in prompts (`quick`, `thorough`, `analyze`, `ultrawork`)
  - **Git Worktree Isolation**: Documentation and tooling for parallel stream development without merge conflicts
  - **Continuation Enforcement**: Agents must emit `<promise>COMPLETE</promise>` signals or be marked blocked
  - **Auto-compaction Threshold**: Agents auto-store work products at 85% context usage (3,482 tokens)
- **New Utilities**: Context engineering support
  - `context-monitor.ts`: Token estimation and threshold detection
  - `mode-detection.ts`: Keyword-based activation mode parsing
  - `continuation-guard.ts`: Promise-based completion validation
  - `quality-gates.ts`: Gate configuration and execution
  - `worktree-manager.ts`: Git worktree helpers for parallel streams
- **Enhanced Documentation**
  - `docs/ENHANCEMENT-FEATURES.md`: Comprehensive guide with user examples
  - Quick Start examples for activation modes, quality gates, worktrees
  - Updated README with Context Engineering feature row

### Changed

- All 12 agent files updated with "Automatic Context Compaction" section
- `/continue` command enhanced with worktree management documentation
- `/memory` command shows agent improvement suggestions
- `/protocol` command supports activation mode keywords

### Acknowledgements

- [oh-my-opencode](https://github.com/code-yeongyu/oh-my-opencode) by code-yeongyu (continuation enforcement, auto-compaction patterns)
- [mcp-shrimp-task-manager](https://github.com/cjo4m06/mcp-shrimp-task-manager) by cjo4m06 (quality gates, project rules)
- [BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) by bmad-code-org (activation modes, agent customization)

## [1.6.4] - 2025-12-31

### Security

- Updated `qs` dependency to 6.14.1 to fix CVE-2025-15284 (arrayLimit bypass DoS vulnerability)

## [1.6.3] - 2025-12-31

### Fixed

- Smoke test now validates actual agent structure (removed obsolete Identity/Decision Authority checks)
- Smoke test skips `.mcp.json` check in CI environments (file is gitignored)
- Updated CLAUDE.md "Required Agent Sections" to match current agent structure

## [1.6.2] - 2025-12-31

### Changed

- Added disclaimer to README clarifying no affiliation with Microsoft Copilot or GitHub Copilot

## [1.6.0] - 2025-12-30

### Added

- **Performance Tracking System**: Agent performance metrics and analytics
  - `agent_performance_get` tool to retrieve aggregated metrics by agent
  - Success rate, token usage, and validation tracking per agent
  - Performance database tables for historical analysis
  - Complexity-based filtering for targeted performance insights
- **Validation System**: Work product quality enforcement
  - `work_product_validate` tool with comprehensive quality checks
  - Validation status tracking (pending, passed, failed, skipped)
  - Quality gate enforcement before work product storage
  - Validation error reporting and remediation guidance
- **Checkpoint System**: Mid-task recovery capabilities
  - `checkpoint_create` tool for saving task state snapshots
  - `checkpoint_get` and `checkpoint_resume` for recovery workflows
  - `checkpoint_list` and `checkpoint_cleanup` for checkpoint management
  - Automatic expiry (24 hours for auto-checkpoints, 7 days for manual)
  - Sequence-based checkpoint ordering (max 5 per task)
- **Token Efficiency Enforcement**: Protocol-level guardrails
  - Critical rules in `/protocol` to prevent context bloat
  - Explicit prohibition of reading >3 files in main session
  - Mandatory delegation to framework agents for substantive work
  - Self-check requirements before every response
  - Framework vs generic agent guidance

### Changed

- Enhanced protocol enforcement with stricter token efficiency rules
- Updated all agent configurations to support performance tracking
- Improved Task Copilot database schema with new validation and performance tables

### Fixed

- Token usage optimization in agent routing and task management

## [1.5.0] - 2024-12-XX

### Added

- **New Commands**: Streamlined workflow management
  - `/memory` command to view current memory state and recent activity
  - `/extensions` command to list and manage agent extensions
- **Extension Support**: Enhanced agent customization
  - `extension_get` tool to retrieve agent extensions
  - `extension_list` tool to list all available extensions
  - `manifest_status` tool to check knowledge repository status
  - Section-level extension merging for flexible customization

### Changed

- **Simplified All 12 Agents**: Reduced each agent to ~60 lines
  - Streamlined agent structure for better maintainability
  - Focused agent responsibilities and clearer routing
  - Removed redundancy across agent definitions
- **Migrated to Task Copilot Exclusively**: Centralized task management
  - Removed `docs/tasks/` directory (tasks now stored in Task Copilot database)
  - All task tracking now uses Task Copilot MCP server
  - Eliminated file-based task management in favor of database persistence
- **Centralized Agent Routing**: Single source of truth
  - All routing logic moved to `protocol.md`
  - Consistent cross-agent routing rules
  - Removed duplicate routing tables from individual agents

### Removed

- `docs/tasks/` directory and file-based task tracking
- Redundant routing sections from individual agent files
- Duplicate decision matrices (consolidated in DECISION-GUIDE.md)

## [1.4.0] - 2024-11-XX

### Added

- **Task Copilot MCP Server**: Ephemeral task and work product storage
  - PRD management with `prd_create`, `prd_get`, `prd_list` tools
  - Task hierarchy with `task_create`, `task_update`, `task_get`, `task_list` tools
  - Work product storage with `work_product_store`, `work_product_get`, `work_product_list` tools
  - Progress tracking with `progress_summary` tool (~200 token summaries)
  - Initiative linking with `initiative_link` tool
  - Activity log for audit trail
  - Workspace-based database isolation
- **Framework-Wide Task Copilot Integration**: 96% context reduction
  - All 12 agents updated to store work products instead of returning to main session
  - Agent responses now return only summaries (~100-200 tokens)
  - Full work products stored in Task Copilot database
  - Clear guidance on when to use Task Copilot vs returning to session

### Changed

- Updated agent workflows to leverage Task Copilot for all detailed outputs
- Enhanced protocol to enforce Task Copilot usage patterns
- Improved memory efficiency across all agent interactions

## [1.3.0] - 2024-10-XX

### Added

- **Skills Copilot MCP Server**: On-demand skill and knowledge loading
  - `skill_get`, `skill_search`, `skill_list`, `skill_save` tools
  - `knowledge_search` and `knowledge_get` tools for documentation access
  - Two-tier resolution (project-level → machine-level)
  - Support for public skill marketplace (25,000+ skills)
  - Private skill storage in SQLite database
- **Knowledge Repository System**: Shared documentation framework
  - `/knowledge-copilot` command for repository setup
  - Global knowledge repository at `~/.claude/knowledge`
  - Project-specific knowledge via `KNOWLEDGE_REPO_PATH`
  - Knowledge manifest schema and validation

### Changed

- Enhanced agent system with automatic skill loading
- Improved documentation search across project and global sources

## [1.2.0] - 2024-09-XX

### Added

- **Extension System**: Agent customization via knowledge repositories
  - Override extensions (full agent replacement)
  - Extension type extensions (section-level merging)
  - Skills injection for specialized capabilities
  - Two-tier extension resolution (project → global → base)
  - `EXTENSION-SPEC.md` documentation

### Changed

- Agent loading system now supports extensions
- Updated agent structure to support extension merging

## [1.1.0] - 2024-08-XX

### Added

- **12 Specialized Agents**: Complete team of development specialists
  - `@agent-ta` (Tech Architect): System design and architecture
  - `@agent-me` (Engineer): Code implementation
  - `@agent-qa` (QA Engineer): Testing and quality assurance
  - `@agent-sec` (Security): Security review and threat modeling
  - `@agent-doc` (Documentation): Technical writing
  - `@agent-do` (DevOps): CI/CD and infrastructure
  - `@agent-sd` (Service Designer): Experience strategy
  - `@agent-uxd` (UX Designer): Interaction design
  - `@agent-uids` (UI Designer): Visual design
  - `@agent-uid` (UI Developer): UI implementation
  - `@agent-cw` (Copywriter): Content and microcopy
  - `@agent-kc` (Knowledge Copilot): Knowledge repository setup
- **Agent-First Protocol**: Structured workflow enforcement
  - `/protocol` command for fresh work sessions
  - Automatic agent routing based on request type
  - Protocol declaration requirements for all responses
- **Core Commands**: Project lifecycle management
  - `/setup-project` for new project initialization
  - `/update-project` for syncing with latest framework
  - `/update-copilot` for framework updates
  - `/continue` for session resumption

### Changed

- Enhanced routing between agents based on expertise
- Improved agent decision authority documentation

## [1.0.0] - 2024-07-XX

### Added

- **Memory Copilot MCP Server**: Persistent cross-session memory
  - `initiative_get`, `initiative_start`, `initiative_update`, `initiative_complete` tools
  - `memory_store` and `memory_search` tools with semantic search
  - SQLite-based storage with vector embeddings
  - Workspace isolation based on project path
  - `WORKSPACE_ID` support for explicit workspace management
- **Core Framework Structure**: Base installation and configuration
  - `.claude/` directory structure for agents and commands
  - `.mcp.json` configuration for MCP servers
  - `CLAUDE.md` project instructions
  - `/setup` command for machine-level initialization
- **Documentation**: Comprehensive guides and references
  - `README.md` with quick start guide
  - `SETUP.md` for manual installation
  - `PHILOSOPHY.md` explaining framework rationale
  - `ARCHITECTURE.md` for technical deep dive
  - `DECISION-GUIDE.md` with decision matrices
  - `USER-JOURNEY.md` for complete setup walkthrough

### Security

- No Time Estimates Policy implemented across all outputs
  - Prohibition of hours, days, weeks, months, quarters in all agent outputs
  - Enforcement through protocol and validation
  - Alternative phrasing using phases, priorities, complexity, dependencies

## [0.9.0] - 2024-06-XX (Beta)

### Added

- Initial beta release for testing
- Basic agent framework prototype
- Memory persistence proof of concept

---

## Version History Summary

| Version | Release Date | Key Features |
|---------|-------------|--------------|
| **5.4.0** | 2026-06-04 | `owner: project` agent preservation in sync commands; fitness-check hyphenated-name + on-disk orphan resolution fix; cs/cpa optional-advisory labeling |
| **5.3.0** | 2026-06-03 | 16-agent specialist roster restored (`design` retired), fitness-check FF6 scans CLAUDE.md for stale design refs, stale `design` routing purged from CLAUDE.md |
| **5.2.0** | 2026-05-20 | FTS5 stack unification (shared fts5_core, BM25 in cc+tc), opt-in semantic embeddings, native plugin packaging + CI guard, design-skill normalization (9 skills → SKILL.md dirs), doc modernization, hermetic test_sentinel_resolution fix |
| **5.1.0** | 2026-05-20 | PRD-2 correctness: FTS5 honesty, skills-as-code (L1/L2), Known References registry, code-exec path, QA-gate fix, Coolify config-gate, 100MB cleanup |
| **5.0.1** | 2026-05-06 | Setup command fixes for cc CLI migration; hook tests 12-14 |
| **5.0.0** | 2026-05-06 | `cc` CLI replaces Memory + Skills MCP servers; memory as committed files |
| **4.0.1** | 2026-04-22 | Hook deadlock fix; fail-open ERR trap; git push/pull allowlisted |
| **4.0.0** | 2026-04-22 | 8-agent roster, mechanical delegation enforcement, model-tier inversion |
| **3.5.0** | 2026-03-29 | Elite Craft design methodology layer |
| **3.0.0** | 2026-02-21 | `tc` CLI replaces Task Copilot MCP server, 225 tests, full MCP-to-CLI migration |
| **2.10.0** | 2026-02-20 | Stream token budgets, path ownership, security hardening |
| **2.9.0** | 2026-02-12 | Multi-agent Foreman architecture, agent assignment rules, task-data status dashboard |
| **2.8.0** | 2026-01-26 | OMC features: ecomode, magic keywords, progress HUD, skill extraction, zero-config |
| **2.7.0** | 2026-01-17 | Experience-first protocol, checkpoint system, orchestration redesign |
| **2.3.1** | 2026-01-13 | Initiative lifecycle, lean agents, deep skills, generation verification |
| **2.2.0** | 2026-01-12 | Confidence scoring, security hooks, session protocol, auto-checkpoints |
| **2.1.0** | 2026-01-12 | Orchestration script generation, dynamic dependency resolution |
| **2.0.0** | 2026-01-08 | Parallel stream orchestration, WebSocket bridge, HTTP API |
| **1.7.0** | 2026-01-04 | Context engineering: activation modes, auto-compaction, quality gates |
| **1.6.0** | 2025-12-30 | Performance tracking, validation system, checkpoints, token efficiency |
| **1.5.0** | 2024-12-XX | Simplified agents, Task Copilot migration, centralized routing |
| **1.4.0** | 2024-11-XX | Task Copilot MCP server, 96% context reduction |
| **1.3.0** | 2024-10-XX | Skills Copilot, knowledge repositories |
| **1.2.0** | 2024-09-XX | Extension system for agent customization |
| **1.1.0** | 2024-08-XX | 12 specialized agents, Agent-First Protocol |
| **1.0.0** | 2024-07-XX | Memory Copilot, core framework structure |
| **0.9.0** | 2024-06-XX | Beta release |

---

## Migration Guides

### Upgrading from 2.x to 3.0.0

**Action Required:**

1. **Install `tc` CLI**: `cd tools/tc && pip install -e .`
2. **Initialize project database**: `tc init` in your project root
3. **Task Copilot MCP server is no longer used for task management**: Agents now use `tc` CLI via Bash tool
4. **Memory Copilot and Skills Copilot MCP servers are unchanged**

**Breaking Changes:**

- All 55 MCP Task Copilot tool schemas removed from agent frontmatter
- Agents use `tc <command> --json` via Bash instead of MCP function calls
- Task data stored in `.copilot/tasks.db` (project-local) instead of MCP server database
- `watch-status` script replaced by `tc watch`

### Upgrading from 1.5.x to 1.6.0

**Action Required:**

1. **Update Protocol Usage**: Review new token efficiency rules in `/protocol`
2. **Validate Work Products**: New validation system may flag quality issues
3. **Performance Metrics**: Optionally enable performance tracking for agents

**Database Changes:**

- New tables: `performance_tracking`, `work_product_validations`, `checkpoints`
- Automatic migration on first run
- No data loss expected

**Breaking Changes:**

- None

### Upgrading from 1.4.x to 1.5.0

**Action Required:**

1. **Migrate File-Based Tasks**: Move any tasks from `docs/tasks/` to Task Copilot
2. **Update Agent References**: Simplified agents may have different routing
3. **Review Extension Usage**: Extension system enhanced in this release

**Breaking Changes:**

- `docs/tasks/` directory removed (use Task Copilot exclusively)
- Agent file structure changed (~60 lines each vs previous verbosity)

### Upgrading from 1.3.x to 1.4.0

**Action Required:**

1. **Install Task Copilot**: Add to `.mcp.json` configuration
2. **Configure TASK_DB_PATH**: Set storage location for task database
3. **Update Agent Workflows**: Agents now use Task Copilot automatically

**Breaking Changes:**

- None (additive release)

---

## Support

For issues, questions, or contributions:

- **Issues**: [GitHub Issues](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/issues)
- **Discussions**: [GitHub Discussions](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/discussions)
- **Documentation**: [docs/](docs/)

---

## Contributors

Thank you to all contributors who have helped build Claude Copilot!

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

---

[unreleased]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v5.4.0...HEAD
[5.4.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v5.3.0...v5.4.0
[5.3.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v5.2.0...v5.3.0
[5.2.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v5.1.0...v5.2.0
[5.1.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v5.0.2...v5.1.0
[5.0.1]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v5.0.0...v5.0.1
[5.0.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v4.0.1...v5.0.0
[4.0.1]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v4.0.0...v4.0.1
[4.0.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v3.5.0...v4.0.0
[3.5.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v3.0.0...v3.5.0
[3.0.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v2.10.0...v3.0.0
[2.10.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v2.9.0...v2.10.0
[2.9.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v2.8.0...v2.9.0
[2.8.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v2.7.0...v2.8.0
[2.7.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v2.3.1...v2.7.0
[2.3.1]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v2.2.0...v2.3.1
[2.2.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v1.7.0...v2.0.0
[1.7.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/compare/v0.9.0...v1.0.0
[0.9.0]: https://github.com/Everyone-Needs-A-Copilot/claude-copilot/releases/tag/v0.9.0
