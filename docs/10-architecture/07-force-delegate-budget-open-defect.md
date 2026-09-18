# Open Defect: force-delegate byte budget still denies bounded, cheap Bash calls

Status: superseded (2026-09-18). The TASK-81 estimator fixes described below held only until the next unpriced shape produced the same flat 8,000-byte denial (41,500/40,000). The byte meter now measures main-session output from the session transcript instead of estimating commands, which removes this whole class of defect; see the 2026-09-18 addendum in `06-adr-005-force-delegate-cost-budget.md`. Everything below is historical: the resolver, the pipeline helper and the floor exemption it describes no longer exist.

## Resolution

The exact `43912/40000` denial came from this command shape in the local Claude
transcript, with 35,912 previously charged bytes:

```bash
cd <project> && grep -rn "bridge" pipeline_copilot/cli/*.py 2>/dev/null | grep -i "def \|command\|add_parser\|help=" | head -20
```

The hook now recognizes the terminal `head -20` and estimates 2,560 bytes
(128 per output line), producing 38,472 total instead of 43,912. The existing
4,096-byte floor also keeps this call usable when the session is already at or
above 40,000 bytes. `head -c N` uses the explicit byte count; large limits remain
expensive. Line limits are estimates, not maximum byte guarantees.

Both other reported cases are covered: matching unquoted file globs sum their
actual regular-file sizes, and `pcopilot bridge --help 2>&1 | grep -i config`
retains the baseline's 300-byte bounded-command estimate. Filters with their own
file operands, additional commands, substitutions and unsupported syntax retain
conservative pricing. Shell input is tokenized/expanded as data and never run.
Denied retries leave accepted spend unchanged; denials report the call's own
estimated charge. No threshold increase, state deletion or bypass is required.

The active `~/.claude/copilot` link resolves to this checkout, so the existing
consumer shim uses this fix on its next invocation. The Python helper lives in
`.claude/hooks/lib/bash_pipeline_cost.py`; a missing helper retains conservative
pricing. This repair covers the live Claude hook, not the separate Codex copy.

Regression checks: `tools/cc/.venv/bin/python -m pytest -o addopts='' tests/test_force_delegate_budget.py`
and the existing `tests/hooks/test-pretool-check.sh` and `test-hook-wiring.sh`
suites. Run the shell suites in a disposable copy: they replace QA/freeze test
state and the override ledger. TASK-81's QA work product records results and
the independently observed pre-existing performance failure described below.

## Start here

The working tree already has two related fixes applied and uncommitted (see "Uncommitted work" below); do not start from a clean-tree assumption. What remains broken after those fixes is the byte-budget resolver's inability to price two extremely common Bash shapes, which causes both to be charged the flat 8000-byte "unbounded" estimate and denied outright once a session's running total has crossed 40000 bytes:

- **Globs.** `grep -rn "bridge" pipeline_copilot/cli/*.py` — the resolver tests `[[ -f "$candidate" ]]` against the literal glob string, which is never a real filename, so it fails to resolve and falls back to 8000.
- **Piped commands that filter stdin rather than read a named file.** `pcopilot bridge --help 2>&1 | grep -i config` — the presence of the pipe alone makes the whole command unresolvable (`_bash_target_bytes` rejects any command containing `|`, `&&`, `>`, `<`, backticks, or `$(` at pretool-check.sh:464-466), so it also falls back to 8000, regardless of how small the actual output is.

Both denials were observed live in a working session today, once at 43912/40000 estimated bytes and again after the counter advanced further. Because the ratchet never decreases mid-session (ADR-005's deliberate design) and both shapes above sit above the 4096-byte floor exemption added by the Defect 1 fix, a session that has gone over budget becomes effectively locked out of ordinary Bash work for the rest of the day, short of the `COPILOT_FORCE_DELEGATE=off` escape hatch.

## Reproduce it

Run these against the framework's own hook, isolated from any live session state:

```bash
cd /Users/pabs/Sites/CSE/claude-copilot
export COPILOT_HOOK_STATE_DIR=/tmp/force-delegate-repro-state
mkdir -p "$COPILOT_HOOK_STATE_DIR"
# Seed a state file already near the ceiling, mirroring an ordinary session's ratchet.
echo '{"session_id":"repro","bytesCharged":38000,"filesTouched":[],"updatedAt":"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"}' \
  > "$COPILOT_HOOK_STATE_DIR/budget-repro.json"

echo '{"session_id":"repro","tool_name":"Bash","cwd":"'"$PWD"'","tool_input":{"command":"grep -rn \"bridge\" pipeline_copilot/cli/*.py"}}' \
  | bash .claude/hooks/pretool-check.sh pretool-check
```

Expected: a deny on stderr and stdout, shaped like:

```
[hook-deny] Main session cost budget exceeded (bytes): 46000/40000 estimated bytes (~11500 tokens), 0/5 distinct file targets. Narrow the call or delegate. Valid agents: ... COPILOT_FORCE_DELEGATE=off is the explicit bypass.
```

(38000 seeded + 8000 flat unbounded charge = 46000, over the 40000 ceiling and over the 4096 floor, so it denies.) Repeat with `"command":"pcopilot bridge --help 2>&1 | grep -i config"` in the payload and the same 8000-byte charge and denial reproduce, even though the actual command output is a few hundred bytes at most.

Contrast with a command that has no `cat`/`find`/`grep`/`rg` token at all, e.g. `"pcopilot bridge --help 2>&1 | head -30"`: this does not match the word-boundary classification at pretool-check.sh:599-602 in the first place, so it gets the flat 300-byte "bounded" charge regardless of the pipe, and is allowed even over budget. The pipe alone is not what triggers the defect; a pipe combined with a command containing a whole-word `cat`/`find`/`grep`/`rg` token is what triggers it, because that combination is classified as unbounded-eligible but cannot be resolved to a real file.

## Inspect or reset the persisted state

The budget lives at `<project>/.claude/hooks/state/budget-<session_id>.json` (`COPILOT_HOOK_STATE_DIR`, set per-project by the shim at `copilot-hook.sh:243`; `STATE_FILE` assembled at `pretool-check.sh:257`). To check a live session's current total: `cat .claude/hooks/state/budget-<session_id>.json` and read `bytesCharged` against the 40000 ceiling. To unblock a locked session immediately without touching state, use the escape hatch: `COPILOT_FORCE_DELEGATE=off <command>` for one call, or `export COPILOT_FORCE_DELEGATE=off` for the rest of the shell session (bypass check at pretool-check.sh:487 for the env var, pretool-check.sh:496-499 for the inline command prefix; both skip the entire rule, byte and file meters alike, charging nothing). To force a full reset of the ratchet itself, delete the state file (`rm .claude/hooks/state/budget-<session_id>.json`) — the next call starts from `{}`, identical to what the 24-hour staleness check does automatically (`STALENESS_SECONDS=86400` at pretool-check.sh:259, consumed at pretool-check.sh:591-592). Deleting the file is safe: it holds only this session's running cost estimate, nothing that represents real work.

## Why this happens (mechanism)

`rule_force_delegate` classifies a Bash command as "unbounded" (eligible for the 8000-byte flat charge unless resolved to a real size) purely by a word-boundary regex over the command string, at pretool-check.sh:599-602: any whole-word `cat` or `find`, or a whole-word `grep`/`rg` lacking a `-m N`/`--max-count=N` flag. Everything else gets the flat "bounded" charge of 300 (pretool-check.sh:603). For a command that matches the unbounded pattern, `_bash_target_bytes` (defined at pretool-check.sh:430) tries to resolve real file targets and sum their sizes instead of charging the flat estimate. It succeeds for a simple, unchained `cat`/`grep`/`find` call against a literal existing file (optionally preceded by a single leading `cd <dir> &&`), and for `;`-separated chains of such calls. It explicitly refuses — returns non-zero, keeping the flat 8000 charge — for:

- **Globs**, because `_bash_single_segment_bytes` (pretool-check.sh:364) resolves each candidate token with `[[ -f "$resolved" ]]` (pretool-check.sh:394), and bash does not expand a glob character inside that test; a literal string like `pipeline_copilot/cli/*.py` never matches an existing file even when the glob itself would.
- **Any command containing a pipe, `&&`, redirection, backtick, or `$(`** anywhere outside a single leading `cd`, because `_bash_target_bytes` rejects the whole command at that point (pretool-check.sh:464-466), by design, per its own comment: "those command shapes return non-zero here so the caller keeps the conservative unbounded charge, which is the correct answer when the target is genuinely unknowable." The comment's assumption is that resolution failures of this kind are rare (piped stdin reads, `find /`) rather than the common case of a `grep`/`cat` inside an everyday filtered pipeline.

The 4096-byte floor exemption added by the Defect 1 fix (`FORCE_DELEGATE_FLOOR_BYTES`, defined at pretool-check.sh:265, applied at pretool-check.sh:624) only protects calls whose cost the resolver could actually compute below that threshold. A call that falls back to the flat 8000 charge is never eligible for the floor, however small its real output would have been.

Separately, and not itself a bug: the "distinct file targets" counter (`0/5` in every Bash deny message) is inert for Bash by design, not a parsing defect. The ternary that populates a call's `$target` only branches for `Read`, `Edit`, and `Write` (pretool-check.sh:594-596); for `Bash` it is always the empty string, and empty targets are filtered out before being added to `filesTouched` (pretool-check.sh:606). `0/5 distinct file targets` in a Bash deny message is a fixed, meaningless placeholder value, not evidence about the file meter. Do not spend time investigating it.

## The tension this creates

The user's global operating rules (`~/.claude/CLAUDE.md`, "Tool Choice: Read With Bash, Mutate With The Native Tools") direct the main session to inspect the filesystem with Bash — `grep`, `cat`, `sed -n`, `find` — in preference to the Read tool, specifically because targeted shell reads cost less context than whole-file Reads. This hook's charge model currently makes exactly those commands the single most expensive class of call it recognizes when their target cannot be resolved (8000 flat vs 300 flat), and once one such call fires in a session, the combination of flat charging, no floor for unresolvable calls, and no mid-session decay (ADR-005's deliberate ratchet) means every later call of the same shape is denied too, however small its real output. Every denial also costs a full round trip in wall-clock and tokens; a denied call is not free.

## Uncommitted work already in the tree

Two prior defects in this same rule are fixed and sitting uncommitted in `/Users/pabs/Sites/CSE/claude-copilot`. Do not assume a clean tree; run `git status` before starting.

- **Defect 1 (fixed):** `rule_force_delegate` used to charge any Bash command matching `cat`, `find`, or unflagged `grep` a flat 8000-byte estimate by command-name pattern alone, regardless of the real target size, while the `Read` branch of the same rule already measured properly via `stat`/`wc -c`. Fixed by adding the size-aware resolver (`_bash_target_bytes` and helpers, pretool-check.sh:334-483) plus the floor exemption (`FORCE_DELEGATE_FLOOR_BYTES`, default 4096, overridable via `COPILOT_FORCE_DELEGATE_FLOOR_BYTES`, pretool-check.sh:265), below which a call is never denied purely because the session total is already over budget.
- **Defect 2 (fixed):** the new resolver never read the PreToolUse payload's `cwd` field, so it resolved relative-path targets against the hook process's own working directory rather than the Bash tool's actual working directory, failed every existence check for an ordinary relative-path call, and silently fell back to the same flat 8000-byte charge — a symptom byte-for-byte identical to the unfixed state, which made the fix look like it had not taken effect at all. Fixed by threading the payload's `cwd` (`PAYLOAD_CWD`, extracted at pretool-check.sh:226, passed into the resolver at pretool-check.sh:565) through to `_resolve_against_cwd` (pretool-check.sh:346), and by narrowly handling a leading `cd <dir> &&` or `cd <dir>;` prefix (pretool-check.sh:466-483). Verified: a previously-refused command chaining a `cd` into an initiative directory with a `grep`/`cat` pair now charges its real combined byte size and runs.

Modified, uncommitted files: `.claude/hooks/pretool-check.sh`, `tests/hooks/test-pretool-check.sh`, `.claude/hooks/README.md`, `docs/10-architecture/06-adr-005-force-delegate-cost-budget.md`.

## Candidate fixes for defect 3

Listed as options with trade-offs, not a ranked mandate. The first four are code changes inside `pretool-check.sh`; the last two touch ADR-005's design decisions and are Pablo's call, not the implementing developer's.

| Option | What it fixes | Trade-off |
|---|---|---|
| Expand globs in the resolver when they match existing files, sum their real sizes | Glob shape only | Smallest change; still leaves the pipe shape open |
| Allowlist bounded, zero-file commands at a low fixed cost (`--help`, `--version`, `git status`, `git log -n <N>`, `ls`) | The no-file-target shape, for a known-safe set | Requires maintaining the allowlist as new safe shapes come up |
| Recognize self-bounding pipelines: a command terminating in `head`, `tail`, or `wc` has a computable output ceiling | Both shapes, for the common case of a deliberately bounded pipeline | More resolver logic; still guesses rather than measures |
| Move accounting from PreToolUse prediction to PostToolUse measurement, charging what a command actually returned rather than what it was guessed to cost | Makes the meter honest in general, not just for these two shapes | Largest change; cannot deny before the call executes, which changes what the rule can guarantee |
| Reopen ADR-005's no-mid-session-decay decision | Removes the "permanently locked for the rest of the day" failure mode entirely | Pablo was already offered this and explicitly chose the narrow fix instead; listed for completeness |
| Downgrade the over-budget deny to a warning for calls that are bounded or small, reserving hard denial for genuinely unbounded ones | Removes the false-positive denial without touching the ratchet | Weakens the rule's enforcement guarantee for the cases it gets wrong, not just the cases it gets right |

## Other things worth knowing while working on this

- Hook test suite currently stands at 79 passed, 1 failed (`bash tests/hooks/test-pretool-check.sh`). The failure is Test 17, hook performance (target under 50ms), and it reproduces identically on unmodified `main` — confirmed by stashing the working tree and re-running. It is pre-existing and unrelated to this defect.
- The `.codex/hooks/pretool-check.sh` copy of this rule (for Codex CLI sessions) does not carry either the Defect 1 or Defect 2 fixes and has a different checksum from the `.claude/hooks` copy. It is not part of the live Claude Code denial path for this project, but the same class of fix would need a second, separate application there if Codex sessions ever enforce this rule.
