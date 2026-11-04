# Parallel execution troubleshooting

Parallel execution is built into `/protocol`; `/orchestrate` is a deprecated redirect. Start with `tc cycle status CYCLE --json`, the canonical task records and the actual native agent state.

| Symptom | Check and recovery |
|---|---|
| No ready work | Read the named dependency event, owner decision or exhausted resource permit. Do not invent a wait for an entire specialist phase. |
| Only one worker runs | Check native slot availability, `resourceLimits`, scoped dependencies and oversized streams. A printed launch command or claim is not actual dispatch. |
| A new stream is denied while another awaits QA | Preserve the task QA gate. Verify the new scope has a valid current cycle claim, matching role/task/cwd and the normal prompt/Knowledge authorization. A bare cycle marker grants no exception. |
| Ownership validation fails | Give every mutable file/output one owner. Narrow a directory claim, split contribution files or route shared edits through one integrator. Do not bypass the validator. |
| Worker is in the wrong checkout | Stop writes, preserve changes, verify real cwd/root/branch/base and canonical task database, then dispatch with the corrected execution root. `--add-dir` is not a cwd switch. |
| Builds or tests overload the machine | Reduce permits for the contended class; retain independent light work. Check memory, CPU, free disk and actual service capacity instead of launching repeated retries. |
| Test state collides across worktrees | Separate synthetic data/tenants, ports and browser state through the project adapter, or serialize the conflicting state mutation. Git isolation does not isolate servers. |
| Merge conflicts | Preserve both contributions and assign one repair owner. Do not reset, force-checkout or remove either worktree. |
| QA passed before a fix | Recheck source bindings; rerun affected scopes, consumers and integration behavior. Do not reuse a verdict merely because the task name matches. |
| Resource retirement is held | Inspect integration, unique commits, tracked/untracked/ignored files, active consumers, identity receipts and teardown. Preserve dirty, unmerged, drifted, active or unknown work. |
| Coordinator restarts | Recover cycle/task receipts and native liveness before replacing claims. Preserve cumulative attempts, failures and budget; do not restart finished work. |
| `tc cycle` or canonical policy is absent | Report the missing capability; repair the pinned installation through supported tooling. Never call an instruction-only fallback an executing scheduler. |

Run `tc cycle smoke --roles sd,uxd,uids,uid,ta,me,qa,sec,doc,do,ind --json` for provider-free lifecycle diagnosis. A native worker test is separate and must use the actual runtime and existing budget. Keep evidence local and preserve original failures.

See the [execution contract](01-orchestration-workflow.md) and `.claude/agents/_shared/work-lifecycle.md` for authority and retirement boundaries.
