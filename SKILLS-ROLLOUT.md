# Skills Rollout Recipe

Repeatable recipe for converting code-worthy skills from flat-markdown to the L1/L2/L3 pattern established by the stride-dread exemplar (TASK-35). Use this document to onboard each skill in the queue below.

---

## The Recipe

Each code-worthy skill conversion follows these steps exactly. Do not invent steps; do not skip steps.

### Step 1 — Identify the deterministic core

Before writing any code, answer: "Is there logic here that the model currently re-derives from scratch every session, where re-derivation is both possible and error-prone?"

Valid deterministic cores:
- Arithmetic (scoring, averaging, band assignment)
- Table lookups (known-bad algorithms, deprecated API patterns, category membership)
- Coverage checking (which categories have zero findings)
- Structural validation (required fields, value ranges, type constraints)
- Pattern matching against a closed, authoritative list (OWASP Top 10, STRIDE categories, NIST-deprecated algorithms)

Not a valid deterministic core:
- Prose judgment (is this architecture good?)
- Aesthetic evaluation (is this code readable?)
- Contextual interpretation (does this threat matter in this system?)
- Anything requiring understanding of domain intent

If you cannot identify a genuine deterministic core, downgrade the skill to `prose-legit` in the queue below and document the reason in one line. Do not manufacture a script.

### Step 2 — Plan the directory layout

```
.claude/skills/<category>/<skill-name>/
  SKILL.md                # L1 frontmatter + L2 prose (unchanged) + Invocation section
  scripts/<name>.py       # L3 executable (Python stdlib only, preferred)
  scripts/test_<name>.py  # pytest test suite
  templates/              # optional output scaffolds
```

The old flat `.claude/skills/<category>/<skill-name>.md` file is retired when the directory form ships.

### Step 3 — Write the script

Rules:
1. **Python stdlib only** — no `pip install`. Use `json`, `sys`, `argparse`, `re`, `pathlib`.
2. **File-path OR stdin** — first arg is a path OR `'-'`/no-arg → read stdin.
3. **Validate all inputs** — unknown values, wrong types, out-of-range numbers → `stderr` message + exit 1.
4. **Structured output** — emit JSON first, then a human-readable markdown section. Both go to stdout.
5. **No voodoo constants** — every threshold, band boundary, minimum key size, or severity cutoff must be defined as a named constant with a comment citing the standard (NIST SP 800-131A, OWASP, RFC number, etc.).
6. **Exit 0 on empty input** — empty input is not an error; return an empty-findings structure.
7. **Exit 1 on invalid input** — bad JSON, missing required fields, out-of-range values.
8. **Exit 0 even on bad findings** — the script classifies (FAIL/WARN/PASS, gap, etc.) but the agent decides what to block on.

### Step 4 — Update SKILL.md

1. Bump `version` to `2.0.0`.
2. Add `allowed-tools: [Read, Grep, Glob, Bash]` to frontmatter. Bash is required so the script runs.
3. Keep all existing L2 prose (the judgment content) unchanged or lightly refined.
4. Add an **Invocation** section that:
   - Shows the exact JSON input format with field descriptions.
   - Shows the Bash invocation (file-path form and stdin form).
   - Describes the output (what fields, what the agent should do with each).
   - States error handling behavior.
5. State explicitly: "Consume the script's **output only** — the script source never enters context."

### Step 5 — Write pytest tests

Cover:
- All named constants at their boundaries (band thresholds, key size minimums, work factor minimums).
- Each invalid-input path exits non-zero with an `ERROR` message on stderr.
- Each valid-input path exits 0.
- stdin (`-`) and file-path argument both parse correctly.
- Empty input exits 0.
- Output structure (JSON block present, markdown section present).
- Sort/ranking order is correct where applicable.

### Step 6 — Run and verify

```bash
python .claude/skills/<category>/<skill-name>/scripts/<name>.py - <<'EOF'
[... minimal valid input ...]
EOF

python -m pytest .claude/skills/<category>/<skill-name>/scripts/test_<name>.py -v
```

Both must succeed before marking the skill converted.

### Step 7 — Store work product

```bash
tc wp store --task <id> --type implementation \
  --title "CONVERTED: <skill-name> — script + tests" \
  --content "..."
tc task update --task <id> --status completed
```

---

## The @include Note

`@include .claude/skills/NAME/SKILL.md` is a documentation convention — the `@include` syntax causes Claude Code to literally insert the file contents, which is fine for loading skills manually. It is NOT a parsed contract; no framework component reads or enforces it. Skills are discovered via `cc skill evaluate` (FTS5 keyword search) or loaded directly by the agent using the Read tool.

Going forward:
- SKILL.md is the canonical skill contract (frontmatter + prose).
- `@include` may be mentioned in SKILL.md as an optional manual-load note.
- Do NOT describe `@include` as the primary invocation mechanism anywhere.

---

## Skill Queue

16 code-worthy skills in priority order. Security batch runs first because it shares the DREAD scorer pattern with the exemplar.

### Status Key

| Symbol | Meaning |
|--------|---------|
| DONE | Converted (SKILL.md + script + tests) |
| PENDING | Not yet converted |
| PROSE-LEGIT | Downgraded — no genuine deterministic core found |

---

### SECURITY (batch 1 — this batch)

| # | Skill | Status | Script | Deterministic Core |
|---|-------|--------|--------|--------------------|
| 1 | `security/stride-dread` | **DONE** (TASK-35) | `dread_score.py` | DREAD 5-dim average + band assignment |
| 2 | `security/threat-modeling` | **DONE** (TASK-36) | `stride_coverage.py` | STRIDE category coverage checking + DREAD scoring |
| 3 | `security/web-security` | **DONE** (TASK-36) | `owasp_score.py` | OWASP Top 10 category coverage + severity tally |
| 4 | `security/crypto-patterns` | **DONE** (TASK-36) | `crypto_check.py` | Weak-algorithm/key-size/mode detection (NIST/OWASP/RFC lookup) |

**Notes on the security batch:**
- `threat-modeling` shares the DREAD scoring logic with `stride-dread` (independent re-implementation in `stride_coverage.py`; STRIDE category tags use `R2`/`D3` to avoid collisions with DREAD `R`/`D`).
- `web-security` deterministic core is OWASP category normalization + coverage gap detection; prose guidance on each vulnerability pattern stays in L2.
- `crypto-patterns` deterministic core is a lookup table of algorithms/modes against NIST SP 800-131A, OWASP Password Storage CS, Mozilla TLS, and RFC 8725. Judgment about when to accept WARN is left to prose.

---

### TESTING (batch 2)

| # | Skill | Status | Script | Deterministic Core |
|---|-------|--------|--------|--------------------|
| 5 | `testing/pytest-patterns` | **DONE** (TASK-38 batch) | `pytest_smell.py` | AST-based: no-assert, empty test, bare except, magic number ≥1000, sleep, print (7 smells; ERROR/WARN severities) |
| 6 | `testing/jest-patterns` | **DONE** (TASK-38 batch) | `jest_smell.py` | Regex-based: .only, .skip, no expect, async-no-await, setTimeout(0), console.log, done callback (7 smells) |

---

### LANGUAGES / CODE (batch 3)

| # | Skill | Status | Script | Deterministic Core |
|---|-------|--------|--------|--------------------|
| 7  | `code/refactoring-patterns` | **DONE** (TASK-38 batch) | `refactor_metrics.py` | AST/regex: long_function >20L, deep_nesting >4, long_param_list >3, large_file >300L, many_functions >10 (Python AST + JS regex; thresholds cite Fowler/Martin/Sonarqube) |
| 8  | `code/python-idioms` | **DONE** | `python_lint.py` | AST-based: MUTABLE_DEFAULT, BARE_EXCEPT (HIGH); EQ_NONE, RANGE_LEN, TYPE_COMPARE (MEDIUM) |
| 9  | `code/javascript-patterns` | **DONE** | `js_patterns.py` | Regex lint-lite: VAR_DECL, LOOSE_EQUALITY, CALLBACK_NESTING (MEDIUM); CONSOLE_LOG (LOW). Closed-set only — not a full AST parser. |
| 10 | `code/react-patterns` | **DONE** | `react_patterns.py` | Structural regex: INDEX_AS_KEY, HOOK_IN_CONDITIONAL (HIGH); MISSING_KEY (MEDIUM). Prop-drilling depth omitted — requires component-tree analysis (semantic, not structural). |

---

### DEVOPS (batch 4)

| # | Skill | Status | Script | Deterministic Core |
|---|-------|--------|--------|--------------------|
| 11 | `devops/docker-patterns` | **DONE** (TASK-38) | `docker_lint.py` | Dockerfile linter: root USER (CIS §4.1), :latest tag, missing HEALTHCHECK, apt without --no-install-recommends, secrets in ENV/ARG (CIS §4.10), layer-bloat, COPY order |
| 12 | `devops/kubernetes` | **DONE** (TASK-38) | `k8s_lint.py` | K8s manifest auditor: missing resource requests/limits, missing probes, :latest image, privileged (CIS §5.2.1), hostNetwork (CIS §5.2.4), no non-root securityContext (CIS §5.2.6), single replica — JSON input (YAML→JSON documented) |
| 13 | `devops/ci-cd-patterns` | **DONE** (TASK-38) | `cicd_lint.py` | GitHub Actions linter: unpinned action versions (branch=CRITICAL/tag=HIGH), missing timeout, no permissions block (OSSF Scorecard), hardcoded secrets — JSON input (YAML→JSON documented) |
| 14 | `devops/git-workflows` | **DONE** (TASK-38) | `git_check.py` | Conventional Commits 1.0.0 format + valid-type check (HIGH); branch prefix/kebab-case convention (MEDIUM) — strategy/workflow decisions remain prose |

---

### DOCS / ARCHITECTURE (batch 5)

| # | Skill | Status | Script | Deterministic Core |
|---|-------|--------|--------|--------------------|
| 15 | `documentation/api-docs` | **DONE** | `api_coverage.py` | OpenAPI 3.x/Swagger 2.0 linter: 12 rules — missing summaries/descriptions/examples, undocumented params, missing 4xx responses, missing auth error codes (401/403 on secured endpoints), operationId casing, info block completeness. Severities cite OAS3 spec sections + RFC 7231. |
| 16 | `architecture/system-design-patterns` | **DONE** | `arch_fitness.py` | ADR structural completeness scorer: required-field presence checking (7 fields per Nygard ADR format) + coverage banding (COMPLETE/ADEQUATE/PARTIAL/INCOMPLETE, thresholds per ISO/IEC 25010) + trade-off checklist gap detection (8 items). NOTE: "dependency-direction fitness-function checks" from original plan was downgraded — it requires running code analysis tools (madge, import scanners) against a real codebase, which cannot be exercised on a structured JSON input. The ADR completeness scorer is the genuine deterministic core for this skill. |

---

## Prose-Legit Skills (do NOT convert)

These skills have been evaluated and confirmed to have no genuine deterministic core. Converting them would produce fake scripts. Keep them as pure markdown.

| Skill | Reason |
|-------|--------|
| `copywriting/litmus-test` | Output is a subjective judgment about whether copy passes brand voice criteria |
| `copywriting/voice-tone` | Voice and tone are generative/taste concerns — no closed rule set |
| `copywriting/voice-and-tone` | Same as above |
| `design/aesthetic-directions` | Aesthetic evaluation is irreducibly subjective |
| `design/color-palettes` | Color choices depend on brand context and perceptual judgment |
| `design/design-heuristics` | Nielsen heuristics are judgment calls, not deterministic checks |
| `design/design-patterns` | Pattern applicability requires contextual judgment |
| `design/motion-choreography` | Motion quality is perceptual |
| `design/premium-interaction-craft` | "Premium" is a subjective quality |
| `design/spatial-luminous-design` | Design taste |
| `design/typography-pairings` | Typographic harmony is aesthetic judgment |
| `design/ux-patterns` | UX pattern selection is contextual |
| `documentation/tutorial-patterns` | Tutorial pedagogy is Diátaxis judgment, not a deterministic check |

---

## Dependency Notes

- Batches 2–5 depend on TASK-36 (this recipe) shipping first.
- Each batch conversion spawns its own task(s) under PRD-2.
- All P1 conversions feed into TASK-38 (QA gate) before P2 starts.
- The recipe itself is the contract — deviation requires a new version of this document, not silent divergence.
