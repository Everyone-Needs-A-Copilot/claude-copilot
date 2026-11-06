# PRD-16 central-resolution acceptance harness

One fixed checklist, derived from the done block, run against a replica of the real machine and real projects, rerun in full on every release. It exists because earlier QA rounds each tested a different ad-hoc checklist in clean temp homes and kept finding new defects.

## Run

```
python3 tests/acceptance/central_resolution/run.py                      # full run
python3 tests/acceptance/central_resolution/run.py --only CR-C,CR-F     # selected checks (prerequisites run silently)
python3 tests/acceptance/central_resolution/run.py --rerun-failed REPORT.json --with-adjacent
python3 tests/acceptance/central_resolution/run.py --list
```

Exit code is nonzero when any check fails. Output is one PASS/FAIL line per check ID, a JSON report (`<sandbox>/report.json`) and a consolidated defect list (check ID, expected, observed, suspected cause, files, adjacent checks). Every check runs to completion even after earlier failures. After fixes rerun the failed checks plus their adjacent ones (checks sharing a component tag); `rerun_after_fix` in the report prints the exact command. A release-ready run is always the full run.

## Checks (stable IDs, never renumber)

| ID | Done-block criterion |
| --- | --- |
| CR-R | Precondition: replica is isolated (no link or config reaches real state) and faithful (git status per project) |
| CR-A | `cc project init` under 10 s on a fresh repo, a foreign repo and a non-Git folder; idempotent; marker, CLAUDE.md and AGENTS.md sections, Codex trust |
| CR-B | `migrate --apply` on every replica project: framework copies gone, only planned paths touched, holds listed; `--rollback` exact (symlink-aware snapshot: type, mode, link target, content hash); re-apply and idempotence |
| CR-C | Test release changing one agent, one command, one skill and one hook's logic is flipped; `claude -p` observes agent, command, skill, hook and `codex exec` observes skill and hook in three migrated projects; no project file touched; Codex trust unchanged |
| CR-D | `release rollback` restores the previous release; both runtimes observe the old versions |
| CR-E | Scan of migrated replicas: zero framework copies and locks (independent hash scan plus cc's own scanner; also checks the CLI flag exists) |
| CR-F | Coordinator guard: `cat` blocked and `git status` allowed in the live main session of both runtimes, plus the installed hook commands at payload level |
| CR-G | Unmigrated replica projects: each hook's logic runs exactly once per event in both runtimes |
| CR-H | Every user-level entry (`~/.claude/{agents,commands,skills}`, `~/.codex/skills`) is a release link, a personal link or in the kept list; 0 dangling |
| CR-S | Real-state sentinel: real `~/.copilot/current` target, release history, links receipt, `~/.claude/settings.json`, `~/.codex/config.toml`, user-level link trees and the six real projects (git status, HEAD, framework files) are hashed before and after; any change fails the run |

## Replica

`replica.py` copies (never modifies) `~/.claude` configuration, `~/.codex` (config, AGENTS.md, skills, plugin cache, hooks, trust), `~/.copilot` (all releases, pointer, history, receipts) and shims into `<sandbox>/home`, rewriting absolute paths and links that point into home state or cloned projects. Projects (pipeline-copilot, convoco, the-herd, claude-copilot-private, knowledge-copilot-internal, and the Codex-heavy convoco-creative-studio) are `git clone --local` clones plus dirty, deleted and untracked files and the ignored framework configuration (`.claude`, `.codex`, `.agents`, `.mcp.json`, locks, `plugins`), with symlinks copied exactly. Live-link tier checkouts found through links are cloned too. Every command runs with `HOME`, `CODEX_HOME` and `COPILOT_HOME` (ending `.copilot`) inside the sandbox.

Not copied: sessions, history, caches, project `.copilot` runtime state, `node_modules`, `.venv`, `__pycache__`, `.claude/worktrees`, files over 200 MB. `registered-projects.json` is emptied so no tool is led to a real folder. Copied credentials (`auth.json`) and the read-only keychain link needed by `claude -p` are removed at the end of the run.

## Release under test and the test release

The replica's `current` is the real current release. CR-G and CR-C/D first flip to an instrumented twin of it (identical, plus one log line per hook script, written to `$CRACC_OBS`), so hook firing is counted at the logic level. CR-C builds the test release from that twin by appending a probe sentence to one agent (`cw`), one command (`memory`), one skill (`aesthetic-directions`) and changing the version tag the hooks log. It is flipped with `cc release flip`; no project is touched.

## Known limits

- Probes are deterministic: agent, command and skill are verified by the resolved file each runtime would load (realpath inside the current release, sha256, token), live Claude sessions are asserted on the command expansion / Skill tool result in the stream-json transcript (never the model's reply), Codex hook trust comes from the app-server `hooks/list` inventory. Codex has no user-level agent or command surface a release flip can change (its specialists are plugin skills, frozen by design for trust); the harness asserts none exists, and observes the skill (file level) and hook (per-hook log).
- The report carries an `adjacency` map (selected check -> checks sharing a component).
- `codex exec` runs with `-m gpt-5.6-sol` (override `CR_CODEX_MODEL`) because the configured model is rejected by this account.
- `claude -p` authenticates through the login keychain; token refresh by the child process can write to the real keychain item. Everything else is read-only.
- The sentinel cannot tell a harness write from a concurrent real session; inspect the changed item's timestamp.
