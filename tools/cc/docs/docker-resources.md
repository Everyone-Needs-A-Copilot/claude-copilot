# Managed synthetic Docker tests

Status: local implementation, TASK-179 / PRD-14. Framework owns the registry;
CLI Copilot only forwards commands. No remote publication is part of this work.

A managed run creates one fresh PostgreSQL server and named volume, publishes only
on loopback, and supplies its connection settings to the child test command.
Per-case databases remain isolated inside that server. No existing server can be
adopted. Main application databases and all pre-existing Docker resources are out
of scope. A project lock permits one managed run per checkout at a time.

Creation records include project, task, owner, expiry, Docker endpoint/daemon,
container ID, volume creation time and random ownership token. Cleanup requires
both private host records and matching runtime identity, exclusive volume use,
and no active run lock. Labels or names alone never authorize deletion. Failed
identity checks are holds, not permission to broaden a filter. There is no prune.

Success removes only that run's container and volume. Failure stops the server,
saves bounded logs and keeps its data for 48 hours. Hourly scheduled cleanup can
remove expired stopped resources; active, unknown or changed resources stay held.
Abrupt creation failures remain recorded and require inspection if identity was
not fully recorded. All creation and cleanup receipts remain available.

Capacity preflight warns at 70% and refuses new test servers at 85% Docker VM
filesystem usage. A tiny read-only, network-disabled helper measures Docker's own
filesystem (not host free space). Failure to measure blocks creation. Test
servers use bounded logs and memory. Existing daemon configuration already has a
10 GB builder GC target and 3 × 10 MB log rotation; this is not a hard cache cap.

Owner authorization: on 2026-10-27 Pablo said “Let's put this in plcae” after the
proposal to permit automatic cleanup only of newly created explicitly managed
synthetic test resources. This narrow exception must be explicitly enabled in
private machine policy. It does not authorize legacy or application data removal.

Validation: negative controls cover remote contexts, capacity, missing policy,
identity/label drift, foreign volume consumers, locks and expiry. Live tests must
exercise success cleanup, failure retention and expiration, while comparing the
entire pre-existing container/volume inventory. Ops and Convoco adapters must
refuse application-server fallbacks. Existing application assertions are unchanged.

Work lifecycle: the maintained source worktrees and installed local feature
snapshot are active deliverables, retained intentionally. Audit evidence and
rollback originals stay private. No historical evidence is retired by this work.

## Commands and integration

- `cc resources run --project PATH --task TASK-ID --profile ops|convoco|postgres -- COMMAND`
  runs from that checkout. The local image must already exist; there are no pulls.
- `cc resources status` lists ownership, expiry, disposition and running database
  counts. `copilot docker tests status` forwards to the same framework command.
- `cc resources finish RUN_ID` removes a stopped, verified managed failure after
  inspection. It refuses a live session or a foreign volume consumer.
- `cc resources audit` also inventories unmanaged database servers, their ages,
  PostgreSQL database counts and test-name review candidates. Candidates never
  grant deletion authority. The hourly report includes this inventory.
- `cc resources sweep` handles expired stopped failures only. `maintain` also
  checks capacity and writes `maintenance.json`, keeping the latest report bounded.
- Ops: `bash scripts/test-db.sh` runs its existing pytest suite. Pass an explicit
  command for a subset. `bash scripts/dev-db.sh` opens a managed development shell;
  exit it to dispose of a successful session.
- Convoco: `bash scripts/test-db.sh` provisions and migrates dedicated ask/session
  databases before verification. It accepts a command to run instead. Provisioning
  directly, or supplying application-server URLs, is refused. The migration/test
  stage in verify-promotion also validates ownership; it has no application fallback.

Failure logs (last 150 lines, at most 12 KB) and disposition remain in private run
receipts. Inspect a retained volume with Docker tools without importing production
data or attaching another container; a foreign consumer intentionally blocks
cleanup. Existing per-case test assertions and fixtures are unchanged.

## Local installation and recovery

`tools/cc/scripts/install-docker-resources.py --cli-source CLI_WORKTREE --evidence
PRIVATE_EVIDENCE_DIRECTORY` installs a separate source snapshot using the existing
Python interpreters/dependencies. It requires owner-enabled machine policy first.
It preserves both original console scripts, then points the console scripts at
that snapshot and loads the user's hourly `com.copilot.docker-resources` LaunchAgent.
Visible release-pinned checkouts remain untouched. This is a local feature install,
not a published framework release; a future framework update can replace it and
must carry forward this feature or reinstall it.

The snapshot lives under `~/.local/share/copilot/docker-resources/TIMESTAMP/`.
Its `install.json` records source hashes, original executables, source worktrees,
LaunchAgent and private verification evidence. Roll back by unloading that exact
LaunchAgent with `launchctl bootout gui/$(id -u) PLIST_PATH`, then restoring the
preserved `cc.original` and `copilot.original` to the recorded executable paths.
Move the disabled plist aside if desired; retain it and all source/evidence.
Restoring old commands does not remove Docker resources. Inspect/finish any managed
run first, or keep the feature snapshot callable until its data has been handled.

The owner-enabled policy is `~/.config/copilot/docker-resources.json`; disable
`automatic_synthetic_cleanup` there to hold all future automatic removals. Records
live under `~/.local/state/copilot/docker-resources/`. The hourly job runs when the
user is logged in; it cannot sweep while the machine is asleep or Docker is down.
Startup and every new run also check capacity. Inspect `maintenance.json` for the
latest hourly warning/hold; no email, Discord or external notifications are sent.

## Verification and limits

Implementation evidence is retained in the install receipt's private evidence
folder. Real Docker checks exercise success disposal, failure preservation and a
controlled clock advance for expiry. Ops executes existing database assertions;
Convoco provisions fresh databases and applies its current migration head. Full
application suites are not implied by this infrastructure verification.

The tool cannot prevent someone from bypassing it with raw Docker/SQL commands;
shared instructions and the project entry points make the managed path the
standard. Unknown/legacy resources remain protected and are never swept. A killed
runner or incomplete creation receipt is a reported hold requiring inspection,
not a license to guess ownership. The hourly report retains the current result;
run receipts retain bounded diagnostic evidence. Task/source worktrees and the
installed snapshot remain active deliverables; no old audit history was deleted.
