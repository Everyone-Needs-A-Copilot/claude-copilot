# cc command reference

Generated from the registered parser. Command callbacks were not executed. For intent, effects, configuration and recovery, read the companion CLI guide.

## `cc`

```text
                                                                                                    
 Usage: cc [OPTIONS] COMMAND [ARGS]...                                                              
                                                                                                    
 Unified Claude Copilot CLI — memory, skills, config, and live docs in one tool.                    
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --version             -V        Show the cc version and exit.                                    │
│ --install-completion            Install completion for the current shell.                        │
│ --show-completion               Show completion for the current shell, to copy it or customize   │
│                                 the installation.                                                │
│ --help                          Show this message and exit.                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ priorities     Weekly outcomes from every project's open tasks. Read-only.                       │
│ onboard        Discover personal repositories, then optionally create confirmed-missing ones.    │
│ status         Show installation observations and the last verification run, without probes.     │
│ env            Emit shell-eval-able CC_* exports for the effective config.                       │
│ resolve        Print the resolved value of a single config key, OR (with `--explain`             │
│                and no KEY) report the WS-A `resolve --explain --json` ecosystem                  │
│                contract. Read-only in both modes -- does not take the copilot lock.              │
│ doctor         Run health checks and report status (WS-A `doctor --json` contract).              │
│ connections    Enumerate the organization's declared services and each one's                     │
│                shared-credential-store connection state (WP-388/389/390 stage B).                │
│ connect        Write locally-supplied secret VALUES into the per-user OS keychain                │
│                for one service's missing credential NAMES (WP-395 D-6, the manual                │
│                keychain floor), then re-run `cc connections`' own presence checks and            │
│                report the fresh row.                                                             │
│ freshness      Cheap single-SHA staleness poll (WS-A `freshness --json` contract).               │
│ update         Reconciling ecosystem sync (WS-A `update --json` contract) --                     │
│                MUTATING: acquires the copilot lock, syncs read-only mirrors, runs the            │
│                policy gate, reconciles the materialize root (add/update/prune), and              │
│                writes `copilot.lock.json`. See cc/commands/update.py's module                    │
│                docstring for the never-destroy guarantees.                                       │
│ repair         Repair the ecosystem (ENGINE-BLOCKED — WS-A doctor-slice stub only).              │
│ deprovision    Wipe the disposable ecosystem trees (WS-A `deprovision --json`                    │
│                contract) -- MUTATING: acquires the copilot lock, then removes every              │
│                item `copilot.lock.json` recorded as materialized plus every mirror               │
│                clone, retaining (never touching) any personal/dirty path. See                    │
│                cc/commands/deprovision.py's module docstring for the never-destroy               │
│                guarantees and the soft/hard split.                                               │
│ version        Show the cc version.                                                              │
│ memory         Manage persistent memory entries (store, get, list, delete, search, index).       │
│ skill          Discover, search, and inspect reusable skills (SKILL.md files).                   │
│ config         Manage cc configuration (get, set, list, where, validate, edit, init, doctor,     │
│                export).                                                                          │
│ docs           Look up package documentation (local-first, network fallback).                    │
│ design         Design guidance, pinned audits and review evidence; tc retains QA authority.      │
│ usage          Show Claude session quota / rate-limit state.                                     │
│ verify         Plan and run repository-owned bounded checks (opt-in).                            │
│ eval           Run regression evals against agent contracts.                                     │
│ extensions     Resolve knowledge-repository agent extensions (override/extension/skills).        │
│ auth           GitHub sign-in and least-privilege permission grants.                             │
│ layers         Discover and join department/org layers (WS-A `layers`/`layers join` contract,    │
│                D7.1 -- proposed addition, not yet upstream).                                     │
│ journey        Record explicit protocol routes and actual dispatch receipts.                     │
│ workspace      Project folders for Control Tower (activation is `cc project init`).              │
│ reconcile      RETIRED: use `cc project init` and `cc release` (framework copies into projects   │
│                no longer exist).                                                                 │
│ resources      Bound and clean newly managed synthetic Docker test servers.                      │
│ store          Verify shared-store access.                                                       │
│ survival       What fraction of agent-authored lines survive untouched (git-only, no rubric).    │
│ support        Access redacted setup support reports.                                            │
│ settings-hook  Register/revert the framework hook shim in ~/.claude/settings.json (user level).  │
│ conformance    RETIRED: use `cc doctor` (per-project copy and lock conformance no longer         │
│                exists).                                                                          │
│ rule           Add, list and propose rules (rewrite in place; no appended exceptions).           │
│ release        Release pointer: immutable releases behind ~/.copilot/current.                    │
│ project        Initialise and inspect project Copilot state.                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
                                                                                                    
 Guide: tools/cc/CLI.md in the source repository (purpose, intent, output and recovery).
```

## `cc priorities`

```text
                                                                                                    
 Usage: cc priorities [OPTIONS]                                                                     
                                                                                                    
 Weekly outcomes from every project's open tasks. Read-only.                                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --week        TEXT  Reference date YYYY-MM-DD; default today.                                    │
│ --json              Output JSON.                                                                 │
│ --help              Show this message and exit.                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc onboard`

```text
                                                                                                    
 Usage: cc onboard [OPTIONS]                                                                        
                                                                                                    
 Discover personal repositories, then optionally create confirmed-missing ones.                     
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope                  TEXT  Repository scope; currently personal. [default: personal]         │
│ --components             TEXT  Comma-separated ecosystem components.                             │
│                                [default: knowledge,cli,claude,codex]                             │
│ --apply                        Create confirmed-missing private repositories.                    │
│ --json                         Emit the versioned onboarding report.                             │
│ --org                    TEXT  Organization slug for the complete ecosystem transaction.         │
│ --products               TEXT  Comma-separated Copilot products. [default: claude,codex]         │
│ --adopt-existing         TEXT  Comma-separated components (or `ssh`, for the device's existing   │
│                                GitHub SSH alias) whose existing content the person consented to  │
│                                include (B1). Scoped per item: each is decided on its own, never  │
│                                all-or-nothing. Any adoptable item left out of this list is a     │
│                                no-op.                                                            │
│ --repository-root        TEXT  Visible folder where ecosystem repositories are kept. When        │
│                                omitted, cc uses the saved folder or a single unambiguous match   │
│                                inside approved project roots.                                    │
│ --help                         Show this message and exit.                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc status`

```text
                                                                                                    
 Usage: cc status [OPTIONS]                                                                         
                                                                                                    
 Show installation observations and the last verification run, without probes.                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --project,--root        PATH  Project to inspect (default: current directory). [default: .]      │
│ --json                        Output local observations as JSON.                                 │
│ --help                        Show this message and exit.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc env`

```text
                                                                                                    
 Usage: cc env [OPTIONS]                                                                            
                                                                                                    
 Emit shell-eval-able CC_* exports for the effective config.                                        
                                                                                                    
 Agents call:  eval "$(cc env)"                                                                     
 to hydrate CC_* environment variables for the current session.                                     
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --include-secrets          Also emit values from secrets.env files. CAUTION: exposes secrets to  │
│                            shell history.                                                        │
│ --json                     Output JSON instead of shell exports.                                 │
│ --help                     Show this message and exit.                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc resolve`

```text
                                                                                                    
 Usage: cc resolve [OPTIONS] [KEY]                                                                  
                                                                                                    
 Print the resolved value of a single config key, OR (with `--explain` and no KEY) report the WS-A  
 `resolve --explain --json` ecosystem contract. Read-only in both modes -- does not take the        
 copilot lock.                                                                                      
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   [key]      TEXT  Dotted config key to resolve (e.g. paths.shared_docs). Omit together with     │
│                    --explain for the ecosystem-resolve report.                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope          TEXT  machine | project | effective                                             │
│ --explain              Explain the layered ecosystem resolution (winning layer per item, shadow  │
│                        chain, override-stale flags) instead of resolving a config key. Requires  │
│                        no KEY argument.                                                          │
│ --json                 Output JSON (the WS-A resolve contract, in --explain mode).               │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc doctor`

```text
                                                                                                    
 Usage: cc doctor [OPTIONS]                                                                         
                                                                                                    
 Run health checks and report status (WS-A `doctor --json` contract).                               
                                                                                                    
 Naming note: the upstream design's user-facing verb is `copilot doctor`                            
 (the `copilot` binary wraps `cc`); until that wrapper exists, `cc doctor`                          
 IS the doctor verb. Read-only — does not take the copilot lock.                                    
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                      Output the WS-A doctor contract as JSON.                             │
│ --runtime-details           Report project runtime evidence separately from the stable doctor    │
│                             contract.                                                            │
│ --exercise-runtime          Explicitly run native hook diagnostics in disposable state; implies  │
│                             --runtime-details.                                                   │
│ --release                   Check the machine release pointer, links, Codex marketplace and      │
│                             Control Tower record; exit 1 on any failure.                         │
│ --help                      Show this message and exit.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc connections`

```text
                                                                                                    
 Usage: cc connections [OPTIONS]                                                                    
                                                                                                    
 Enumerate the organization's declared services and each one's shared-credential-store connection   
 state (WP-388/389/390 stage B).                                                                    
                                                                                                    
 Read-only -- does not take the copilot lock. Shells `copilot --json                                
 layers` (cli-copilot foundation >=0.3.2) for the service roster and,                               
 for each service's store/any-hinted `requires_secret` names, checks                                
 presence (never values) in the organization's shared Infisical store                               
 via one `copilot infisical --json secret list` call per distinct                                   
 (workspace, environment, path) scope. Computed entirely CLI-side                                   
 (invariant #1) -- Control Tower only ever filters on `secret_state`.                               
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Output the `cc connections --json` contract as JSON.                             │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc connect`

```text
                                                                                                    
 Usage: cc connect [OPTIONS] SERVICE_ID                                                             
                                                                                                    
 Write locally-supplied secret VALUES into the per-user OS keychain for one service's missing       
 credential NAMES (WP-395 D-6, the manual keychain floor), then re-run `cc connections`' own        
 presence checks and report the fresh row.                                                          
                                                                                                    
 Values are read EXCLUSIVELY from stdin, as a JSON object                                           
 `{"<NAME>": "<value>", ...}` -- never argv (world-readable via `ps` for                            
 the lifetime of the call), never an environment variable (inherited by                             
 every child process and dumped more readily than argv or stdin by                                  
 shells/supervisors/crash reporters), and never a file (would leave the                             
 value at rest on disk, which this verb's entire job is to avoid doing                              
 anywhere but the OS keychain). See `cc.commands.connect`'s module                                  
 docstring for the full rationale. Use `--check` for a read-only                                    
 re-evaluation with no stdin at all.                                                                
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    service_id      TEXT  The service id/name to connect (from `cc connections --json`).        │
│                            [required]                                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --check          Re-evaluate and return the service's connection row only -- never reads stdin,  │
│                  never writes anything (the app's post-connect refresh).                         │
│ --json           Output the `cc connect --json` contract as JSON.                                │
│ --help           Show this message and exit.                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc freshness`

```text
                                                                                                    
 Usage: cc freshness [OPTIONS]                                                                      
                                                                                                    
 Cheap single-SHA staleness poll (WS-A `freshness --json` contract).                                
                                                                                                    
 Read-only -- does not take the copilot lock. Compares the local                                    
 resolved lock state against a tier's published lock-pointer ref (see                               
 core/ecosystem/mirror.py); never a full `update`. With no flags this                               
 is byte-shape-identical to the pre-existing contract (regression                                   
 guard) -- `--all-projects` and `--per-layer` are opt-in additions.                                 
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                  Output the WS-A freshness contract as JSON.                              │
│ --all-projects          RETIRED: per-project freshness no longer exists (no project copies).     │
│ --per-layer             Also fold in a per-layer freshness breakdown alongside the top-level     │
│                         single-SHA fields.                                                       │
│ --help                  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc update`

```text
                                                                                                    
 Usage: cc update [OPTIONS]                                                                         
                                                                                                    
 Reconciling ecosystem sync (WS-A `update --json` contract) -- MUTATING: acquires the copilot lock, 
 syncs read-only mirrors, runs the policy gate, reconciles the materialize root (add/update/prune), 
 and writes `copilot.lock.json`. See cc/commands/update.py's module docstring for the never-destroy 
 guarantees.                                                                                        
                                                                                                    
 `--project`/`--fanout` (per-project materialization) are retired and                               
 refuse; the plain machine-wide sync is unchanged.                                                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                        Output the WS-A update contract as JSON.                           │
│ --dry-run                     Compute the reconciling-sync plan WITHOUT writing/pruning          │
│                               materialize-root content or the lockfile.                          │
│ --project               TEXT  RETIRED: materializing a project component. Refuses; use `cc       │
│                               project init`.                                                     │
│ --component             TEXT  The component to materialize for --project (e.g. 'claude',         │
│                               'codex').                                                          │
│ --target-version        TEXT  Target version for --project's --component (defaults to its        │
│                               current recorded version -- an up-to-date no-op check).            │
│ --release-tag           TEXT  Published release tag licensing the --project apply (required to   │
│                               actually apply a version change; an unverified target is blocked). │
│ --source-root           TEXT  Content root to materialize --project's framework-owned files      │
│                               from.                                                              │
│ --fanout                      Machine-wide fan-out materialize sweep across every discovered     │
│                               project's stale components (Component Sync Stream-E) instead of    │
│                               the machine-wide ecosystem sync.                                   │
│ --help                        Show this message and exit.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc repair`

```text
                                                                                                    
 Usage: cc repair [OPTIONS]                                                                         
                                                                                                    
 Repair the ecosystem (ENGINE-BLOCKED — WS-A doctor-slice stub only).                               
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc deprovision`

```text
                                                                                                    
 Usage: cc deprovision [OPTIONS]                                                                    
                                                                                                    
 Wipe the disposable ecosystem trees (WS-A `deprovision --json` contract) -- MUTATING: acquires the 
 copilot lock, then removes every item `copilot.lock.json` recorded as materialized plus every      
 mirror clone, retaining (never touching) any personal/dirty path. See cc/commands/deprovision.py's 
 module docstring for the never-destroy guarantees and the soft/hard split.                         
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                 Output the WS-A deprovision contract as JSON.                             │
│ --dry-run              Compute the wipe plan WITHOUT removing/quarantining anything.             │
│ --mode           TEXT  'soft' (default): wipe materialized content, quarantine mirror clones so  │
│                        a flip-back restores without a re-clone. 'hard': also permanently delete  │
│                        mirror clones (including any quarantined ones).                           │
│                        [default: soft]                                                           │
│ --soft                 Shorthand for --mode soft (the default).                                  │
│ --hard                 Shorthand for --mode hard.                                                │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc version`

```text
                                                                                                    
 Usage: cc version [OPTIONS]                                                                        
                                                                                                    
 Show the cc version.                                                                               
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc memory`

```text
                                                                                                    
 Usage: cc memory [OPTIONS] COMMAND [ARGS]...                                                       
                                                                                                    
 Manage persistent memory entries (store, get, list, delete, search, index).                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ store    Store a new memory entry as a UUID-named markdown file.                                 │
│ get      Retrieve a memory entry by UUID (full or prefix match).                                 │
│ list     List memory entries, optionally filtered by type or tag.                                │
│ delete   Delete a memory entry file.                                                             │
│ search   Search memory entries (FTS index when available, file-based fallback).                  │
│ index    Manage the SQLite FTS search index (local cache, gitignored).                           │
│ export   Export memory entries to a portable Markdown or JSON bundle.                            │
│ check    Check memory entries for drift: missing paths, stale claims, version conflicts.         │
│ migrate  Migrate legacy copilot-memory SQLite entries to the new file-per-entry format.          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc memory store`

```text
                                                                                                    
 Usage: cc memory store [OPTIONS] CONTENT                                                           
                                                                                                    
 Store a new memory entry as a UUID-named markdown file.                                            
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    content      TEXT  Memory content to store. [required]                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --type   -t      TEXT  Entry type: decision|context|lesson|reference|person [default: context]   │
│ --tags           TEXT  Comma-separated tags, e.g. --tags auth,security                           │
│ --scope  -s      TEXT  Scope: project (default if in git repo) or global.                        │
│ --json                 Output result as JSON.                                                    │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc memory get`

```text
                                                                                                    
 Usage: cc memory get [OPTIONS] ENTRY_ID                                                            
                                                                                                    
 Retrieve a memory entry by UUID (full or prefix match).                                            
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    entry_id      TEXT  Entry UUID (full or prefix). [required]                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope  -s      TEXT                                                                            │
│ --json                                                                                           │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc memory list`

```text
                                                                                                    
 Usage: cc memory list [OPTIONS]                                                                    
                                                                                                    
 List memory entries, optionally filtered by type or tag.                                           
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --type   -t      TEXT  Filter by type.                                                           │
│ --tags           TEXT  Filter by tag.                                                            │
│ --scope  -s      TEXT                                                                            │
│ --json                                                                                           │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc memory delete`

```text
                                                                                                    
 Usage: cc memory delete [OPTIONS] ENTRY_ID                                                         
                                                                                                    
 Delete a memory entry file.                                                                        
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    entry_id      TEXT  Entry UUID (full or prefix). [required]                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope  -s      TEXT                                                                            │
│ --yes    -y            Skip confirmation.                                                        │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc memory search`

```text
                                                                                                    
 Usage: cc memory search [OPTIONS] QUERY                                                            
                                                                                                    
 Search memory entries (FTS index when available, file-based fallback).                             
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    query      TEXT  Search query. [required]                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope  -s      TEXT                                                                            │
│ --json                                                                                           │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc memory index`

```text
                                                                                                    
 Usage: cc memory index [OPTIONS]                                                                   
                                                                                                    
 Manage the SQLite FTS search index (local cache, gitignored).                                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --rebuild                Rebuild the FTS index from files.                                       │
│ --status                 Show index freshness.                                                   │
│ --scope    -s      TEXT                                                                          │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc memory export`

```text
                                                                                                    
 Usage: cc memory export [OPTIONS] [QUERY]                                                          
                                                                                                    
 Export memory entries to a portable Markdown or JSON bundle.                                       
                                                                                                    
 With no arguments, exports all entries.  Provide a QUERY to filter by                              
 keyword (FTS search), --type to filter by entry type, or both together.                            
 Output is Markdown by default; use --json for a JSON array.                                        
                                                                                                    
 Examples:                                                                                          
                                                                                                    
                                                                                                    
     cc memory export                     # all entries as Markdown (stdout)                        
     cc memory export --json              # all entries as JSON (stdout)                            
     cc memory export auth --type decision  # filtered, Markdown                                    
     cc memory export --all --out dump.md   # write to file                                         
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   [query]      TEXT  Optional keyword filter — exports only entries matching this search query.  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --type   -t      TEXT  Filter by type: decision|context|lesson|reference|person.                 │
│ --all                  Export all entries (default when no query or --type is given).            │
│ --json                 Export as a JSON array instead of Markdown.                               │
│ --out            PATH  Write output to this file path instead of stdout.                         │
│ --scope  -s      TEXT                                                                            │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc memory check`

```text
                                                                                                    
 Usage: cc memory check [OPTIONS]                                                                   
                                                                                                    
 Check memory entries for drift: missing paths, stale claims, version conflicts.                    
                                                                                                    
 Runs deterministic (token-free) checkers on all stored memory entries:                             
                                                                                                    
                                                                                                    
 - path-exists      : referenced file paths exist on disk                                           
 - command-resolves : binaries or npm scripts are available                                         
 - version-conflict : same package with conflicting versions across entries                         
 - staleness        : entries not updated within the configured threshold                           
                                                                                                    
 Negation-aware: paths under "not yet built", "removed", "deprecated" etc.                          
 are not flagged. URL routes (/api/x) and <placeholder> tokens are skipped.                         
                                                                                                    
 Scoring: 100 − (fail×10 + warn×3 + info×1), floored at 0.                                          
                                                                                                    
 Examples:                                                                                          
                                                                                                    
                                                                                                    
     cc memory check                                                                                
     cc memory check --json                                                                         
     cc memory check --scope global --staleness-days 60                                             
     cc memory check --no-commands --json                                                           
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope           -s      TEXT                                                                   │
│ --json                             Output structured JSON report.                                │
│ --no-paths                         Skip path-existence checks.                                   │
│ --no-commands                      Skip command-resolves checks.                                 │
│ --no-stale                         Skip staleness checks.                                        │
│ --staleness-days          INTEGER  Days threshold for staleness warning. [default: 90]           │
│ --help                             Show this message and exit.                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc memory migrate`

```text
                                                                                                    
 Usage: cc memory migrate [OPTIONS]                                                                 
                                                                                                    
 Migrate legacy copilot-memory SQLite entries to the new file-per-entry format.                     
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --from-global                Migrate from legacy ~/.claude/memory/*/memory.db databases.         │
│ --status                     Show migration status: source DB entry count vs existing .md files. │
│ --dry-run                    Print what would be migrated without writing files.                 │
│ --scope        -s      TEXT  Target scope: project (default if in git repo) or global.           │
│ --all                        Migrate from all discovered legacy databases without prompting.     │
│ --help                       Show this message and exit.                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc skill`

```text
                                                                                                    
 Usage: cc skill [OPTIONS] COMMAND [ARGS]...                                                        
                                                                                                    
 Discover, search, and inspect reusable skills (SKILL.md files).                                    
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ list    List all discovered skills with name and description.                                    │
│ search  Search skills by keyword (matches name, description, tags).                              │
│ get     Print the full SKILL.md content (plain text, pipeable).                                  │
│ path    Print the absolute path to a SKILL.md file (plain text, pipeable).                       │
│ select  Load relevant optional context with a reproducible selection receipt.                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc skill list`

```text
                                                                                                    
 Usage: cc skill list [OPTIONS]                                                                     
                                                                                                    
 List all discovered skills with name and description.                                              
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope        TEXT  Scope to scan: project | machine | knowledge | all [default: all]           │
│ --json               Output as JSON.                                                             │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc skill search`

```text
                                                                                                    
 Usage: cc skill search [OPTIONS] QUERY                                                             
                                                                                                    
 Search skills by keyword (matches name, description, tags).                                        
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    query      TEXT  Search query (keyword match). [required]                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope        TEXT  Scope to scan: project | machine | knowledge | all [default: all]           │
│ --json               Output as JSON.                                                             │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc skill get`

```text
                                                                                                    
 Usage: cc skill get [OPTIONS] NAME                                                                 
                                                                                                    
 Print the full SKILL.md content (plain text, pipeable).                                            
                                                                                                    
 Example:                                                                                           
 cc skill get security                                                                              
 @include <(cc skill get stride-dread)                                                              
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      TEXT  Skill name (from frontmatter or directory name). [required]                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope        TEXT  Scope to scan: project | machine | knowledge | all [default: all]           │
│ --json               Output content and provenance as JSON.                                      │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc skill path`

```text
                                                                                                    
 Usage: cc skill path [OPTIONS] NAME                                                                
                                                                                                    
 Print the absolute path to a SKILL.md file (plain text, pipeable).                                 
                                                                                                    
 Example:                                                                                           
 cc skill path stride-dread                                                                         
 # → /path/to/.claude/skills/security/stride-dread/SKILL.md                                         
 @include $(cc skill path stride-dread)                                                             
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      TEXT  Skill name (from frontmatter or directory name). [required]                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope        TEXT  Scope to scan: project | machine | knowledge | all [default: all]           │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc skill select`

```text
                                                                                                    
 Usage: cc skill select [OPTIONS] [QUERY]                                                           
                                                                                                    
 Load relevant optional context with a reproducible selection receipt.                              
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   [query]      TEXT  Keywords for optional skill selection.                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --required         TEXT                  Required skill; repeatable, never budget-truncated.     │
│ --max-chars        INTEGER RANGE [x>=0]  Character budget for returned content, not tokens.      │
│                                          [default: 12000]                                        │
│ --scope            TEXT                  project | machine | knowledge | all [default: all]      │
│ --json                                   Return content and source/selection receipts.           │
│ --help                                   Show this message and exit.                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc config`

```text
                                                                                                    
 Usage: cc config [OPTIONS] COMMAND [ARGS]...                                                       
                                                                                                    
 Manage cc configuration (get, set, list, where, validate, edit, init, doctor, export).             
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ get       Get a resolved configuration value.                                                    │
│ set       Set a configuration value (machine config by default).                                 │
│ add       Append a value to a list-valued config key, idempotently.                              │
│ remove    Remove a value from a list-valued config key (symmetric to `add`).                     │
│ unset     Remove a key from machine or project config.                                           │
│ list      List configuration keys and values with source annotation.                             │
│ where     Show which config layer provides a key's value.                                        │
│ validate  Validate config files against the schema.                                              │
│ edit      Open the config file in $EDITOR.                                                       │
│ init      Write a default config template to machine or project config.                          │
│ export    Export the effective (or machine-only) config for sharing or debugging.                │
│ doctor    Run config health checks: paths, files, gitignore, permissions.                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc config get`

```text
                                                                                                    
 Usage: cc config get [OPTIONS] KEY                                                                 
                                                                                                    
 Get a resolved configuration value.                                                                
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    key      TEXT  Dotted config key (e.g. paths.shared_docs). [required]                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope        TEXT  Restrict to: machine | project | effective (default).                       │
│ --raw                Print raw value without formatting.                                         │
│ --json               Output as JSON.                                                             │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc config set`

```text
                                                                                                    
 Usage: cc config set [OPTIONS] KEY VALUE                                                           
                                                                                                    
 Set a configuration value (machine config by default).                                             
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    key        TEXT  Dotted config key. [required]                                              │
│ *    value      TEXT  Value to set. For list-valued keys (e.g. paths.knowledge_repo), a          │
│                       comma-separated value (e.g. 'a,b,c') is parsed into a list.                │
│                       [required]                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --project          Write to project config instead of machine config.                            │
│ --help             Show this message and exit.                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc config add`

```text
                                                                                                    
 Usage: cc config add [OPTIONS] KEY VALUE                                                           
                                                                                                    
 Append a value to a list-valued config key, idempotently.                                          
                                                                                                    
 Creates the list if the key was previously a string or unset. A value                              
 already present in the list is not duplicated. Order is preserved —                                
 the first entry in the list is consulted first at resolution time.                                 
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    key        TEXT  Dotted config key (list-valued, e.g. paths.knowledge_repo). [required]     │
│ *    value      TEXT  Value to append to the list. [required]                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --project          Write to project config instead of machine config.                            │
│ --help             Show this message and exit.                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc config remove`

```text
                                                                                                    
 Usage: cc config remove [OPTIONS] KEY VALUE                                                        
                                                                                                    
 Remove a value from a list-valued config key (symmetric to `add`).                                 
                                                                                                    
 No-op if the value is not present.                                                                 
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    key        TEXT  Dotted config key (list-valued, e.g. paths.knowledge_repo). [required]     │
│ *    value      TEXT  Value to remove from the list. [required]                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --project          Remove from project config instead of machine config.                         │
│ --help             Show this message and exit.                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc config unset`

```text
                                                                                                    
 Usage: cc config unset [OPTIONS] KEY                                                               
                                                                                                    
 Remove a key from machine or project config.                                                       
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    key      TEXT  Dotted config key to remove. [required]                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --project          Remove from project config.                                                   │
│ --help             Show this message and exit.                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc config list`

```text
                                                                                                    
 Usage: cc config list [OPTIONS]                                                                    
                                                                                                    
 List configuration keys and values with source annotation.                                         
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope        TEXT  Show: machine | project | effective (default).                              │
│ --json               Output as JSON.                                                             │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc config where`

```text
                                                                                                    
 Usage: cc config where [OPTIONS] KEY                                                               
                                                                                                    
 Show which config layer provides a key's value.                                                    
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    key      TEXT  Dotted config key. [required]                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                           │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc config validate`

```text
                                                                                                    
 Usage: cc config validate [OPTIONS]                                                                
                                                                                                    
 Validate config files against the schema.                                                          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope        TEXT  Validate: machine | project | both. [default: both]                         │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc config edit`

```text
                                                                                                    
 Usage: cc config edit [OPTIONS]                                                                    
                                                                                                    
 Open the config file in $EDITOR.                                                                   
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --project          Edit project config.                                                          │
│ --help             Show this message and exit.                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc config init`

```text
                                                                                                    
 Usage: cc config init [OPTIONS]                                                                    
                                                                                                    
 Write a default config template to machine or project config.                                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --machine          Create machine config template.                                               │
│ --project          Create project config template.                                               │
│ --help             Show this message and exit.                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc config export`

```text
                                                                                                    
 Usage: cc config export [OPTIONS]                                                                  
                                                                                                    
 Export the effective (or machine-only) config for sharing or debugging.                            
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --machine               Export machine config only.                                              │
│ --mask-secrets          Mask secret values.                                                      │
│ --json                                                                                           │
│ --help                  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc config doctor`

```text
                                                                                                    
 Usage: cc config doctor [OPTIONS]                                                                  
                                                                                                    
 Run config health checks: paths, files, gitignore, permissions.                                    
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc docs`

```text
                                                                                                    
 Usage: cc docs [OPTIONS] COMMAND [ARGS]...                                                         
                                                                                                    
 Look up package documentation (local-first, network fallback).                                     
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ resolve  Detect the installed/declared version of a package.                                     │
│ get      Fetch documentation for a package.                                                      │
│ search   Search package documentation for a query topic.                                         │
│ sources  List registered documentation source backends and their availability.                   │
│ cache    Inspect or clear the docs cache.                                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc docs resolve`

```text
                                                                                                    
 Usage: cc docs resolve [OPTIONS] PKG                                                               
                                                                                                    
 Detect the installed/declared version of a package.                                                
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    pkg      TEXT  Package name (e.g. 'react', 'requests'). [required]                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --lang  -l      TEXT  Ecosystem: js|npm|python|pip  (auto-detected when omitted).                │
│ --json                Output as JSON.                                                            │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc docs get`

```text
                                                                                                    
 Usage: cc docs get [OPTIONS] PKG                                                                   
                                                                                                    
 Fetch documentation for a package.                                                                 
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    pkg      TEXT  Package name. [required]                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --topic    -t      TEXT                Documentation topic / query string (optional).            │
│ --lang     -l      TEXT                Ecosystem: js|npm|python|pip  (auto-detected when         │
│                                        omitted).                                                 │
│ --source   -s      [auto|local|fetch]  Backend: auto (local→fetch), local, or fetch.             │
│                                        [default: auto]                                           │
│ --refresh  -r                          Bypass cache and fetch fresh docs.                        │
│ --json                                 Output as JSON.                                           │
│ --help                                 Show this message and exit.                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc docs search`

```text
                                                                                                    
 Usage: cc docs search [OPTIONS] PKG QUERY                                                          
                                                                                                    
 Search package documentation for a query topic.                                                    
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    pkg        TEXT  Package name. [required]                                                   │
│ *    query      TEXT  Search query / topic. [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --lang  -l      TEXT                                                                             │
│ --json                                                                                           │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc docs sources`

```text
                                                                                                    
 Usage: cc docs sources [OPTIONS]                                                                   
                                                                                                    
 List registered documentation source backends and their availability.                              
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                           │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc docs cache`

```text
                                                                                                    
 Usage: cc docs cache [OPTIONS] [PKG]                                                               
                                                                                                    
 Inspect or clear the docs cache.                                                                   
                                                                                                    
 Examples:                                                                                          
                                                                                                    
 cc docs cache --status          # show totals                                                      
 cc docs cache --clear           # clear all                                                        
 cc docs cache --clear requests  # not yet supported (pkg-specific clear TBD)                       
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   [pkg]      TEXT  Package to operate on (optional — omit for all packages).                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --status          Show cache statistics.                                                         │
│ --clear           Clear cached entries.                                                          │
│ --json                                                                                           │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc design`

```text
                                                                                                    
 Usage: cc design [OPTIONS] COMMAND [ARGS]...                                                       
                                                                                                    
 Design guidance, pinned audits and review evidence; tc retains QA authority.                       
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ guide            List focused actions or load one source-hashed playbook.                        │
│ template         Print a draft surface contract; --output creates a new file exclusively.        │
│ context          Load a surface contract and bounded explicit authority, with selection          │
│                  receipts.                                                                       │
│ review           Record initial design judgment before running the detector.                     │
│ audit            Run a pinned local static scan; exit 1 when scan evidence is unavailable.       │
│ report           Check criterion coverage and evidence identity; never issue a QA verdict.       │
│ compare          Create a self-contained baseline/candidate screenshot comparison.               │
│ feedback-config  Enable/disable project feedback and preserve unrelated native hooks.            │
│ feedback         Native PostToolUse adapter; bounded input/output and no task-state mutation.    │
│ tool             Explicitly manage the machine-pinned external detector.                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc design guide`

```text
                                                                                                    
 Usage: cc design guide [OPTIONS] [ACTION]                                                          
                                                                                                    
 List focused actions or load one source-hashed playbook.                                           
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   [action]      TEXT                                                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                           │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc design template`

```text
                                                                                                    
 Usage: cc design template [OPTIONS]                                                                
                                                                                                    
 Print a draft surface contract; --output creates a new file exclusively.                           
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --output        TEXT                                                                             │
│ --json                                                                                           │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc design context`

```text
                                                                                                    
 Usage: cc design context [OPTIONS]                                                                 
                                                                                                    
 Load a surface contract and bounded explicit authority, with selection receipts.                   
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --contract         TEXT                          [required]                                   │
│    --action           TEXT                          [default: shape]                             │
│    --max-chars        INTEGER RANGE [0<=x<=100000]  [default: 12000]                             │
│    --json                                                                                        │
│    --help                                           Show this message and exit.                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc design review`

```text
                                                                                                    
 Usage: cc design review [OPTIONS]                                                                  
                                                                                                    
 Record initial design judgment before running the detector.                                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --contract          TEXT  [required]                                                          │
│ *  --assessment        TEXT  [required]                                                          │
│ *  --output            TEXT  [required]                                                          │
│    --json                                                                                        │
│    --help                    Show this message and exit.                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc design audit`

```text
                                                                                                    
 Usage: cc design audit [OPTIONS] [TARGETS]...                                                      
                                                                                                    
 Run a pinned local static scan; exit 1 when scan evidence is unavailable.                          
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   [targets]...      TEXT                                                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --review         TEXT                                                                            │
│ --output         TEXT                                                                            │
│ --timeout        INTEGER RANGE [1<=x<=60]  [default: 20]                                         │
│ --json                                                                                           │
│ --help                                     Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc design report`

```text
                                                                                                    
 Usage: cc design report [OPTIONS]                                                                  
                                                                                                    
 Check criterion coverage and evidence identity; never issue a QA verdict.                          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --review              TEXT  [required]                                                        │
│ *  --audit               TEXT  [required]                                                        │
│ *  --verification        TEXT  [required]                                                        │
│ *  --output              TEXT  [required]                                                        │
│    --json                                                                                        │
│    --help                      Show this message and exit.                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc design compare`

```text
                                                                                                    
 Usage: cc design compare [OPTIONS] MANIFEST                                                        
                                                                                                    
 Create a self-contained baseline/candidate screenshot comparison.                                  
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    manifest      TEXT  [required]                                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --output        TEXT  [required]                                                              │
│    --json                                                                                        │
│    --help                Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc design feedback-config`

```text
                                                                                                    
 Usage: cc design feedback-config [OPTIONS]                                                         
                                                                                                    
 Enable/disable project feedback and preserve unrelated native hooks.                               
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --runtime                 TEXT  [required]                                                    │
│    --enable     --disable          [default: enable]                                             │
│    --json                                                                                        │
│    --help                          Show this message and exit.                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc design feedback`

```text
                                                                                                    
 Usage: cc design feedback [OPTIONS]                                                                
                                                                                                    
 Native PostToolUse adapter; bounded input/output and no task-state mutation.                       
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --runtime        TEXT  [required]                                                             │
│    --help                 Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc design tool`

```text
                                                                                                    
 Usage: cc design tool [OPTIONS] COMMAND [ARGS]...                                                  
                                                                                                    
 Explicitly manage the machine-pinned external detector.                                            
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ status    Verify the registered executable's current content hash.                               │
│ install   Download the reviewed release asset and verify its packaged SHA256.                    │
│ register  Pin a separately verified local Impeccable engine; never trust project-selected        │
│           executables.                                                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc design tool status`

```text
                                                                                                    
 Usage: cc design tool status [OPTIONS]                                                             
                                                                                                    
 Verify the registered executable's current content hash.                                           
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                           │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc design tool install`

```text
                                                                                                    
 Usage: cc design tool install [OPTIONS]                                                            
                                                                                                    
 Download the reviewed release asset and verify its packaged SHA256.                                
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --replace                                                                                        │
│ --json                                                                                           │
│ --help             Show this message and exit.                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc design tool register`

```text
                                                                                                    
 Usage: cc design tool register [OPTIONS] BINARY                                                    
                                                                                                    
 Pin a separately verified local Impeccable engine; never trust project-selected executables.       
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    binary      PATH  [required]                                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --sha256         TEXT  [required]                                                             │
│ *  --version        TEXT  [required]                                                             │
│ *  --source         TEXT  [required]                                                             │
│    --replace                                                                                     │
│    --json                                                                                        │
│    --help                 Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc usage`

```text
                                                                                                    
 Usage: cc usage [OPTIONS] COMMAND [ARGS]...                                                        
                                                                                                    
 Show Claude session quota / rate-limit state.                                                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json              Output raw JSON cache.                                                       │
│ --refresh           Force a new probe even if idle (bypasses the 12-min gate).                   │
│ --no-probe          Never probe; return cached data or transcript fallback only.                 │
│ --help              Show this message and exit.                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc verify`

```text
                                                                                                    
 Usage: cc verify [OPTIONS] COMMAND [ARGS]...                                                       
                                                                                                    
 Plan and run repository-owned bounded checks (opt-in).                                             
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ plan    Select checks without executing manifest commands; unknown impact broadens.              │
│ run     Execute a fresh manifest-bound plan and retain logs under .copilot/verification.         │
│ status  Read durable status without a daemon or task-state changes.                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc verify plan`

```text
                                                                                                    
 Usage: cc verify plan [OPTIONS]                                                                    
                                                                                                    
 Select checks without executing manifest commands; unknown impact broadens.                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --root            PATH  Repository root. [default: .]                                            │
│ --manifest        TEXT  Repository-relative manifest. [default: verification.json]               │
│ --changed         TEXT  Changed path; repeat as needed.                                          │
│ --base            TEXT  Git review base; includes dirty and untracked files.                     │
│ --lane            TEXT  Explicit lane scope; repeat as needed.                                   │
│ --task            TEXT  Task association only, not approval.                                     │
│ --json                                                                                           │
│ --help                  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc verify run`

```text
                                                                                                    
 Usage: cc verify run [OPTIONS]                                                                     
                                                                                                    
 Execute a fresh manifest-bound plan and retain logs under .copilot/verification.                   
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --plan         PATH  Saved JSON plan from cc verify plan. [required]                          │
│    --root         PATH  [default: .]                                                             │
│    --reuse              Opt in to matching hermetic execution reuse; never approval reuse.       │
│    --task         TEXT  Override execution's task association; not approval.                     │
│    --json                                                                                        │
│    --help               Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc verify status`

```text
                                                                                                    
 Usage: cc verify status [OPTIONS]                                                                  
                                                                                                    
 Read durable status without a daemon or task-state changes.                                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --run         TEXT  Local run ID. [required]                                                  │
│    --root        PATH  [default: .]                                                              │
│    --json                                                                                        │
│    --help              Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc eval`

```text
                                                                                                    
 Usage: cc eval [OPTIONS] COMMAND [ARGS]...                                                         
                                                                                                    
 Run regression evals against agent contracts.                                                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --agent                 TEXT   Agent name to evaluate (e.g. qa).                                 │
│ --threshold             FLOAT  Pass-rate threshold [0.0–1.0].                                    │
│ --json                         Emit JSON to stdout.                                              │
│ --list-agents                  List agents that have eval cases.                                 │
│ --runner                TEXT   'local' (default, static) or 'live' (real headless dispatch;      │
│                                costs API spend).                                                 │
│                                [default: local]                                                  │
│ --max-budget-usd        FLOAT  Per-dispatch spend cap for --runner live (default: 0.50).         │
│ --help                         Show this message and exit.                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ run              Run the golden eval set for an agent and exit non-zero on regression.           │
│ adoption-freeze  Freeze held-out inputs, pinned controls and adoption thresholds.                │
│ adoption-check   Apply frozen gates to benchmark observations; no runtime dispatch.              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc eval run`

```text
                                                                                                    
 Usage: cc eval run [OPTIONS]                                                                       
                                                                                                    
 Run the golden eval set for an agent and exit non-zero on regression.                              
                                                                                                    
 Exit codes:                                                                                        
 0 — pass-rate >= threshold AND no P0 case regressed                                                
 1 — pass-rate < threshold OR any P0 case regressed                                                 
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --agent                 TEXT   Agent name to evaluate (e.g. qa). [required]                   │
│    --threshold             FLOAT  Pass-rate threshold [0.0–1.0]. Default from quality-gates.json │
│                                   (0.8).                                                         │
│    --json                         Emit JSON to stdout.                                           │
│    --runner                TEXT   'local' (default): static assertion engine, no LLM calls.      │
│                                   'live': dispatches source.type=live-agent cases through a real │
│                                   headless `claude --print --agent` session and asserts against  │
│                                   the model's actual output; costs real API spend.               │
│                                   [default: local]                                               │
│    --max-budget-usd        FLOAT  Per-dispatch spend cap for --runner live (default: 0.50).      │
│    --help                         Show this message and exit.                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc eval adoption-freeze`

```text
                                                                                                    
 Usage: cc eval adoption-freeze [OPTIONS] PLAN                                                      
                                                                                                    
 Freeze held-out inputs, pinned controls and adoption thresholds.                                   
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    plan      PATH  Pilot plan JSON; brief/rubric paths resolve from its directory. [required]  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --output        PATH  New frozen receipt path; refuses overwrite. [required]                  │
│    --help                Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc eval adoption-check`

```text
                                                                                                    
 Usage: cc eval adoption-check [OPTIONS] FROZEN OBSERVATIONS                                        
                                                                                                    
 Apply frozen gates to benchmark observations; no runtime dispatch.                                 
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    frozen            PATH  Frozen receipt JSON, located in the pilot directory. [required]     │
│ *    observations      PATH  JSON array of reviewed trial observations. [required]               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc extensions`

```text
                                                                                                    
 Usage: cc extensions [OPTIONS] COMMAND [ARGS]...                                                   
                                                                                                    
 Resolve knowledge-repository agent extensions (override/extension/skills).                         
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ resolve  Resolve the winning knowledge-repo extension for one agent (or all).                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc extensions resolve`

```text
                                                                                                    
 Usage: cc extensions resolve [OPTIONS]                                                             
                                                                                                    
 Resolve the winning knowledge-repo extension for one agent (or all).                               
                                                                                                    
 Walks the real configured knowledge repos (CC_KNOWLEDGE_REPOS order --                             
 personal-over-org precedence falls out of that order), matches                                     
 extensions[] entries by agent id, verifies requiredSkills, and applies                             
 fallbackBehavior. Never raises on a missing/malformed manifest.                                    
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --agent        TEXT  Agent ID to resolve (e.g. sd, cw, ta).                                      │
│ --all                Resolve every agent ID found in .claude/agents/.                            │
│ --json               Output as JSON.                                                             │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc auth`

```text
                                                                                                    
 Usage: cc auth [OPTIONS] COMMAND [ARGS]...                                                         
                                                                                                    
 GitHub sign-in and least-privilege permission grants.                                              
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --poll                     Perform one device-flow poll step instead of initiating.              │
│ --device-code        TEXT  The device_code from a prior `cc auth --json`.                        │
│ --org                TEXT  GitHub org slug to sign in through -- see `cc auth login --help`.     │
│ --json                     Output the WS-A auth contract as JSON.                                │
│ --help                     Show this message and exit.                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ login   Initiate GitHub device-flow sign-in (no flags), or perform one poll                      │
│         step (`--poll --device-code <code>`). Read-only w.r.t. the copilot                       │
│         lock -- auth never acquires it.                                                          │
│ grant   Request only the permission needed to add this Mac's public SSH key.                     │
│ status  Report who is currently signed in, if anyone. Offline-safe -- never                      │
│         touches the network.                                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc auth login`

```text
                                                                                                    
 Usage: cc auth login [OPTIONS]                                                                     
                                                                                                    
 Initiate GitHub device-flow sign-in (no flags), or perform one poll step (`--poll --device-code    
 <code>`). Read-only w.r.t. the copilot lock -- auth never acquires it.                             
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --poll                     Perform one device-flow poll step instead of initiating.              │
│ --device-code        TEXT  The device_code from a prior `cc auth login --json`.                  │
│ --org                TEXT  GitHub org slug to sign in through, on a machine with no              │
│                            github_app.client_id/org configured yet. Required again on every      │
│                            --poll call for the same reason --device-code is: this CLI holds no   │
│                            session state between processes. Falls back to the github_app.org     │
│                            config key (set once via `cc config set` by the app or an admin) when │
│                            omitted.                                                              │
│ --json                     Output the WS-A auth contract as JSON.                                │
│ --help                     Show this message and exit.                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc auth grant`

```text
                                                                                                    
 Usage: cc auth grant [OPTIONS]                                                                     
                                                                                                    
 Request only the permission needed to add this Mac's public SSH key.                               
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --poll                     Perform one permission-grant poll step instead of initiating.         │
│ --device-code        TEXT  The device_code from a prior `cc auth grant --json`.                  │
│ --org                TEXT  GitHub org slug; falls back to github_app.org.                        │
│ --json                     Output the strict auth permission-grant contract as JSON.             │
│ --help                     Show this message and exit.                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc auth status`

```text
                                                                                                    
 Usage: cc auth status [OPTIONS]                                                                    
                                                                                                    
 Report who is currently signed in, if anyone. Offline-safe -- never touches the network.           
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Output the WS-A auth contract as JSON.                                           │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc layers`

```text
                                                                                                    
 Usage: cc layers [OPTIONS] COMMAND [ARGS]...                                                       
                                                                                                    
 Discover and join department/org layers (WS-A `layers`/`layers join` contract, D7.1 -- proposed    
 addition, not yet upstream).                                                                       
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Output the WS-A layers contract as JSON.                                         │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ list  List every department/org layer this account could join (same as                           │
│       the bare `cc layers` default).                                                             │
│ join  Join an entitled, not-yet-joined department/org layer (WS-A `layers                        │
│       join <id> --json` contract) -- MUTATING: acquires the copilot lock,                        │
│       syncs the layer's mirror, extends the local manifest, and materializes                     │
│       it via `cc update`'s own pipeline. `not-entitled` is a normal outcome,                     │
│       not a crash.                                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc layers list`

```text
                                                                                                    
 Usage: cc layers list [OPTIONS]                                                                    
                                                                                                    
 List every department/org layer this account could join (same as the bare `cc layers` default).    
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Output the WS-A layers contract as JSON.                                         │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc layers join`

```text
                                                                                                    
 Usage: cc layers join [OPTIONS] LAYER_ID                                                           
                                                                                                    
 Join an entitled, not-yet-joined department/org layer (WS-A `layers join <id> --json` contract) -- 
 MUTATING: acquires the copilot lock, syncs the layer's mirror, extends the local manifest, and     
 materializes it via `cc update`'s own pipeline. `not-entitled` is a normal outcome, not a crash.   
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    layer_id      TEXT  The layer id to join (from `cc layers list`). [required]                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Output the WS-A layers-join contract as JSON.                                    │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc journey`

```text
                                                                                                    
 Usage: cc journey [OPTIONS] COMMAND [ARGS]...                                                      
                                                                                                    
 Record explicit protocol routes and actual dispatch receipts.                                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ begin        Record a task journey with runtime, prompt and planned specialist evidence.         │
│ prepare      Prepare the next specialist dispatch and return its evidence marker.                │
│ inspect      Read the recorded state of one journey run.                                         │
│ bind-prompt  Bind the exact complete Agent prompt before PreToolUse dispatch.                    │
│ pause        Record a continuation point for the selected journey.                               │
│ abandon      Close an unfinished run so it stops gating its session.                             │
│ resume       Resume a recorded journey for the selected task.                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc journey begin`

```text
                                                                                                    
 Usage: cc journey begin [OPTIONS]                                                                  
                                                                                                    
 Record a task journey with runtime, prompt and planned specialist evidence.                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --task                    INTEGER  [required]                                                 │
│ *  --runtime                 TEXT     [required]                                                 │
│ *  --classification          TEXT     [required]                                                 │
│ *  --specialists-json        TEXT     [required]                                                 │
│ *  --events-json             TEXT     [required]                                                 │
│ *  --prompt-sha256           TEXT     [required]                                                 │
│ *  --session                 TEXT     [required]                                                 │
│    --json                                                                                        │
│    --help                             Show this message and exit.                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc journey prepare`

```text
                                                                                                    
 Usage: cc journey prepare [OPTIONS]                                                                
                                                                                                    
 Prepare the next specialist dispatch and return its evidence marker.                               
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --run               TEXT  [required]                                                          │
│ *  --specialist        TEXT  [required]                                                          │
│    --json                                                                                        │
│    --help                    Show this message and exit.                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc journey inspect`

```text
                                                                                                    
 Usage: cc journey inspect [OPTIONS]                                                                
                                                                                                    
 Read the recorded state of one journey run.                                                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --run         TEXT  [required]                                                                │
│    --json                                                                                        │
│    --help              Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc journey bind-prompt`

```text
                                                                                                    
 Usage: cc journey bind-prompt [OPTIONS]                                                            
                                                                                                    
 Bind the exact complete Agent prompt before PreToolUse dispatch.                                   
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --run                  TEXT  [required]                                                       │
│ *  --specialist           TEXT  [required]                                                       │
│ *  --prompt-sha256        TEXT  [required]                                                       │
│    --json                                                                                        │
│    --help                       Show this message and exit.                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc journey pause`

```text
                                                                                                    
 Usage: cc journey pause [OPTIONS]                                                                  
                                                                                                    
 Record a continuation point for the selected journey.                                              
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --run         TEXT  [required]                                                                │
│    --json                                                                                        │
│    --help              Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc journey abandon`

```text
                                                                                                    
 Usage: cc journey abandon [OPTIONS]                                                                
                                                                                                    
 Close an unfinished run so it stops gating its session.                                            
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --run            TEXT  [required]                                                             │
│ *  --session        TEXT  [required]                                                             │
│ *  --reason         TEXT  [required]                                                             │
│    --json                                                                                        │
│    --help                 Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc journey resume`

```text
                                                                                                    
 Usage: cc journey resume [OPTIONS]                                                                 
                                                                                                    
 Resume a recorded journey for the selected task.                                                   
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --task        INTEGER  [required]                                                             │
│    --run         TEXT                                                                            │
│    --json                                                                                        │
│    --help                 Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc journey verify-dispatch`

```text
                                                                                                    
 Usage: cc journey verify-dispatch [OPTIONS]                                                        
                                                                                                    
 Verify a dispatch against its session, specialist and exact prompt identity.                       
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --session                 TEXT  [required]                                                    │
│ *  --subagent                TEXT  [required]                                                    │
│    --marker                  TEXT                                                                │
│ *  --prompt-sha256           TEXT  [required]                                                    │
│    --knowledge-sha256        TEXT                                                                │
│    --json                                                                                        │
│    --help                          Show this message and exit.                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc workspace`

```text
                                                                                                    
 Usage: cc workspace [OPTIONS] COMMAND [ARGS]...                                                    
                                                                                                    
 Project folders for Control Tower (activation is `cc project init`).                               
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --project        TEXT  Retired.                                                                  │
│ --all                  Retired.                                                                  │
│ --json                 Emit JSON.                                                                │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ configure     RETIRED. `cc workspace configure` is retired: the framework is resolved centrally  │
│               from the release pointer, and nothing is copied into projects. Use `cc project     │
│               init` to set a project up and `cc release` to publish or roll back the framework;  │
│               `cc doctor` verifies the machine.                                                  │
│ finish        RETIRED. `cc workspace finish` is retired: the framework is resolved centrally     │
│               from the release pointer, and nothing is copied into projects. Use `cc project     │
│               init` to set a project up and `cc release` to publish or roll back the framework;  │
│               `cc doctor` verifies the machine.                                                  │
│ verify        RETIRED. `cc workspace verify` is retired: the framework is resolved centrally     │
│               from the release pointer, and nothing is copied into projects. Use `cc project     │
│               init` to set a project up and `cc release` to publish or roll back the framework;  │
│               `cc doctor` verifies the machine.                                                  │
│ plan          RETIRED. `cc workspace plan` is retired: the framework is resolved centrally from  │
│               the release pointer, and nothing is copied into projects. Use `cc project init` to │
│               set a project up and `cc release` to publish or roll back the framework; `cc       │
│               doctor` verifies the machine.                                                      │
│ migrate       RETIRED. `cc workspace migrate` is retired: the framework is resolved centrally    │
│               from the release pointer, and nothing is copied into projects. Use `cc project     │
│               init` to set a project up and `cc release` to publish or roll back the framework;  │
│               `cc doctor` verifies the machine.                                                  │
│ hold          RETIRED. `cc workspace hold` is retired: the framework is resolved centrally from  │
│               the release pointer, and nothing is copied into projects. Use `cc project init` to │
│               set a project up and `cc release` to publish or roll back the framework; `cc       │
│               doctor` verifies the machine.                                                      │
│ revert        RETIRED. `cc workspace revert` is retired: the framework is resolved centrally     │
│               from the release pointer, and nothing is copied into projects. Use `cc project     │
│               init` to set a project up and `cc release` to publish or roll back the framework;  │
│               `cc doctor` verifies the machine.                                                  │
│ approve-root  Plan or approve one project folder; never scans outside that folder.               │
│ forget-root   Plan or apply removing one approved folder. Never deletes anything inside it.      │
│ roots         Read configured project folders plus detected one-click candidates. Never writes.  │
│ decline       Plan or apply 'I don't keep projects on this Mac.' Reversible by approving a       │
│               folder later.                                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc workspace configure`

```text
                                                                                                    
 Usage: cc workspace configure [OPTIONS]                                                            
                                                                                                    
 RETIRED. `cc workspace configure` is retired: the framework is resolved centrally from the release 
 pointer, and nothing is copied into projects. Use `cc project init` to set a project up and `cc    
 release` to publish or roll back the framework; `cc doctor` verifies the machine.                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc workspace finish`

```text
                                                                                                    
 Usage: cc workspace finish [OPTIONS]                                                               
                                                                                                    
 RETIRED. `cc workspace finish` is retired: the framework is resolved centrally from the release    
 pointer, and nothing is copied into projects. Use `cc project init` to set a project up and `cc    
 release` to publish or roll back the framework; `cc doctor` verifies the machine.                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc workspace verify`

```text
                                                                                                    
 Usage: cc workspace verify [OPTIONS]                                                               
                                                                                                    
 RETIRED. `cc workspace verify` is retired: the framework is resolved centrally from the release    
 pointer, and nothing is copied into projects. Use `cc project init` to set a project up and `cc    
 release` to publish or roll back the framework; `cc doctor` verifies the machine.                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc workspace plan`

```text
                                                                                                    
 Usage: cc workspace plan [OPTIONS]                                                                 
                                                                                                    
 RETIRED. `cc workspace plan` is retired: the framework is resolved centrally from the release      
 pointer, and nothing is copied into projects. Use `cc project init` to set a project up and `cc    
 release` to publish or roll back the framework; `cc doctor` verifies the machine.                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc workspace migrate`

```text
                                                                                                    
 Usage: cc workspace migrate [OPTIONS]                                                              
                                                                                                    
 RETIRED. `cc workspace migrate` is retired: the framework is resolved centrally from the release   
 pointer, and nothing is copied into projects. Use `cc project init` to set a project up and `cc    
 release` to publish or roll back the framework; `cc doctor` verifies the machine.                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc workspace hold`

```text
                                                                                                    
 Usage: cc workspace hold [OPTIONS]                                                                 
                                                                                                    
 RETIRED. `cc workspace hold` is retired: the framework is resolved centrally from the release      
 pointer, and nothing is copied into projects. Use `cc project init` to set a project up and `cc    
 release` to publish or roll back the framework; `cc doctor` verifies the machine.                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc workspace revert`

```text
                                                                                                    
 Usage: cc workspace revert [OPTIONS]                                                               
                                                                                                    
 RETIRED. `cc workspace revert` is retired: the framework is resolved centrally from the release    
 pointer, and nothing is copied into projects. Use `cc project init` to set a project up and `cc    
 release` to publish or roll back the framework; `cc doctor` verifies the machine.                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc workspace approve-root`

```text
                                                                                                    
 Usage: cc workspace approve-root [OPTIONS]                                                         
                                                                                                    
 Plan or approve one project folder; never scans outside that folder.                               
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --path         TEXT  Folder the user selected for project discovery. [required]               │
│    --apply              Add this folder to bounded workspace discovery.                          │
│    --json               Emit the versioned root-approval report.                                 │
│    --help               Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc workspace forget-root`

```text
                                                                                                    
 Usage: cc workspace forget-root [OPTIONS]                                                          
                                                                                                    
 Plan or apply removing one approved folder. Never deletes anything inside it.                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --path         TEXT  Folder to stop watching for projects. [required]                         │
│    --apply              Remove this folder from bounded workspace discovery.                     │
│    --json               Emit the versioned root-approval report.                                 │
│    --help               Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc workspace roots`

```text
                                                                                                    
 Usage: cc workspace roots [OPTIONS]                                                                
                                                                                                    
 Read configured project folders plus detected one-click candidates. Never writes.                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Emit the versioned workspace-root report.                                        │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc workspace decline`

```text
                                                                                                    
 Usage: cc workspace decline [OPTIONS]                                                              
                                                                                                    
 Plan or apply 'I don't keep projects on this Mac.' Reversible by approving a folder later.         
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --apply          Record that Control Tower should not offer project setup on this Mac.           │
│ --json           Emit the versioned workspace-root report.                                       │
│ --help           Show this message and exit.                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile`

```text
                                                                                                    
 Usage: cc reconcile [OPTIONS] COMMAND [ARGS]...                                                    
                                                                                                    
 RETIRED: use `cc project init` and `cc release` (framework copies into projects no longer exist).  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ assess             RETIRED. `cc reconcile assess` is retired: the framework is resolved          │
│                    centrally from the release pointer, and nothing is copied into projects. Use  │
│                    `cc project init` to set a project up and `cc release` to publish or roll     │
│                    back the framework; `cc doctor` verifies the machine.                         │
│ prepare            RETIRED. `cc reconcile prepare` is retired: the framework is resolved         │
│                    centrally from the release pointer, and nothing is copied into projects. Use  │
│                    `cc project init` to set a project up and `cc release` to publish or roll     │
│                    back the framework; `cc doctor` verifies the machine.                         │
│ run                RETIRED. `cc reconcile run` is retired: the framework is resolved centrally   │
│                    from the release pointer, and nothing is copied into projects. Use `cc        │
│                    project init` to set a project up and `cc release` to publish or roll back    │
│                    the framework; `cc doctor` verifies the machine.                              │
│ request            RETIRED. `cc reconcile request` is retired: the framework is resolved         │
│                    centrally from the release pointer, and nothing is copied into projects. Use  │
│                    `cc project init` to set a project up and `cc release` to publish or roll     │
│                    back the framework; `cc doctor` verifies the machine.                         │
│ plan               RETIRED. `cc reconcile plan` is retired: the framework is resolved centrally  │
│                    from the release pointer, and nothing is copied into projects. Use `cc        │
│                    project init` to set a project up and `cc release` to publish or roll back    │
│                    the framework; `cc doctor` verifies the machine.                              │
│ assistant-prepare  RETIRED. `cc reconcile assistant-prepare` is retired: the framework is        │
│                    resolved centrally from the release pointer, and nothing is copied into       │
│                    projects. Use `cc project init` to set a project up and `cc release` to       │
│                    publish or roll back the framework; `cc doctor` verifies the machine.         │
│ assistant-run      RETIRED. `cc reconcile assistant-run` is retired: the framework is resolved   │
│                    centrally from the release pointer, and nothing is copied into projects. Use  │
│                    `cc project init` to set a project up and `cc release` to publish or roll     │
│                    back the framework; `cc doctor` verifies the machine.                         │
│ assistant-status   RETIRED. `cc reconcile assistant-status` is retired: the framework is         │
│                    resolved centrally from the release pointer, and nothing is copied into       │
│                    projects. Use `cc project init` to set a project up and `cc release` to       │
│                    publish or roll back the framework; `cc doctor` verifies the machine.         │
│ guide-prepare      RETIRED. `cc reconcile guide-prepare` is retired: the framework is resolved   │
│                    centrally from the release pointer, and nothing is copied into projects. Use  │
│                    `cc project init` to set a project up and `cc release` to publish or roll     │
│                    back the framework; `cc doctor` verifies the machine.                         │
│ guide-start        RETIRED. `cc reconcile guide-start` is retired: the framework is resolved     │
│                    centrally from the release pointer, and nothing is copied into projects. Use  │
│                    `cc project init` to set a project up and `cc release` to publish or roll     │
│                    back the framework; `cc doctor` verifies the machine.                         │
│ guide-check        RETIRED. `cc reconcile guide-check` is retired: the framework is resolved     │
│                    centrally from the release pointer, and nothing is copied into projects. Use  │
│                    `cc project init` to set a project up and `cc release` to publish or roll     │
│                    back the framework; `cc doctor` verifies the machine.                         │
│ guide-status       RETIRED. `cc reconcile guide-status` is retired: the framework is resolved    │
│                    centrally from the release pointer, and nothing is copied into projects. Use  │
│                    `cc project init` to set a project up and `cc release` to publish or roll     │
│                    back the framework; `cc doctor` verifies the machine.                         │
│ guide-finalize     RETIRED. `cc reconcile guide-finalize` is retired: the framework is resolved  │
│                    centrally from the release pointer, and nothing is copied into projects. Use  │
│                    `cc project init` to set a project up and `cc release` to publish or roll     │
│                    back the framework; `cc doctor` verifies the machine.                         │
│ apply              RETIRED. `cc reconcile apply` is retired: the framework is resolved centrally │
│                    from the release pointer, and nothing is copied into projects. Use `cc        │
│                    project init` to set a project up and `cc release` to publish or roll back    │
│                    the framework; `cc doctor` verifies the machine.                              │
│ verify             RETIRED. `cc reconcile verify` is retired: the framework is resolved          │
│                    centrally from the release pointer, and nothing is copied into projects. Use  │
│                    `cc project init` to set a project up and `cc release` to publish or roll     │
│                    back the framework; `cc doctor` verifies the machine.                         │
│ recover            RETIRED. `cc reconcile recover` is retired: the framework is resolved         │
│                    centrally from the release pointer, and nothing is copied into projects. Use  │
│                    `cc project init` to set a project up and `cc release` to publish or roll     │
│                    back the framework; `cc doctor` verifies the machine.                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile assess`

```text
                                                                                                    
 Usage: cc reconcile assess [OPTIONS]                                                               
                                                                                                    
 RETIRED. `cc reconcile assess` is retired: the framework is resolved centrally from the release    
 pointer, and nothing is copied into projects. Use `cc project init` to set a project up and `cc    
 release` to publish or roll back the framework; `cc doctor` verifies the machine.                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile prepare`

```text
                                                                                                    
 Usage: cc reconcile prepare [OPTIONS]                                                              
                                                                                                    
 RETIRED. `cc reconcile prepare` is retired: the framework is resolved centrally from the release   
 pointer, and nothing is copied into projects. Use `cc project init` to set a project up and `cc    
 release` to publish or roll back the framework; `cc doctor` verifies the machine.                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile run`

```text
                                                                                                    
 Usage: cc reconcile run [OPTIONS]                                                                  
                                                                                                    
 RETIRED. `cc reconcile run` is retired: the framework is resolved centrally from the release       
 pointer, and nothing is copied into projects. Use `cc project init` to set a project up and `cc    
 release` to publish or roll back the framework; `cc doctor` verifies the machine.                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile request`

```text
                                                                                                    
 Usage: cc reconcile request [OPTIONS]                                                              
                                                                                                    
 RETIRED. `cc reconcile request` is retired: the framework is resolved centrally from the release   
 pointer, and nothing is copied into projects. Use `cc project init` to set a project up and `cc    
 release` to publish or roll back the framework; `cc doctor` verifies the machine.                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile plan`

```text
                                                                                                    
 Usage: cc reconcile plan [OPTIONS]                                                                 
                                                                                                    
 RETIRED. `cc reconcile plan` is retired: the framework is resolved centrally from the release      
 pointer, and nothing is copied into projects. Use `cc project init` to set a project up and `cc    
 release` to publish or roll back the framework; `cc doctor` verifies the machine.                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile assistant-prepare`

```text
                                                                                                    
 Usage: cc reconcile assistant-prepare [OPTIONS]                                                    
                                                                                                    
 RETIRED. `cc reconcile assistant-prepare` is retired: the framework is resolved centrally from the 
 release pointer, and nothing is copied into projects. Use `cc project init` to set a project up    
 and `cc release` to publish or roll back the framework; `cc doctor` verifies the machine.          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile assistant-run`

```text
                                                                                                    
 Usage: cc reconcile assistant-run [OPTIONS]                                                        
                                                                                                    
 RETIRED. `cc reconcile assistant-run` is retired: the framework is resolved centrally from the     
 release pointer, and nothing is copied into projects. Use `cc project init` to set a project up    
 and `cc release` to publish or roll back the framework; `cc doctor` verifies the machine.          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile assistant-status`

```text
                                                                                                    
 Usage: cc reconcile assistant-status [OPTIONS]                                                     
                                                                                                    
 RETIRED. `cc reconcile assistant-status` is retired: the framework is resolved centrally from the  
 release pointer, and nothing is copied into projects. Use `cc project init` to set a project up    
 and `cc release` to publish or roll back the framework; `cc doctor` verifies the machine.          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile guide-prepare`

```text
                                                                                                    
 Usage: cc reconcile guide-prepare [OPTIONS]                                                        
                                                                                                    
 RETIRED. `cc reconcile guide-prepare` is retired: the framework is resolved centrally from the     
 release pointer, and nothing is copied into projects. Use `cc project init` to set a project up    
 and `cc release` to publish or roll back the framework; `cc doctor` verifies the machine.          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile guide-start`

```text
                                                                                                    
 Usage: cc reconcile guide-start [OPTIONS]                                                          
                                                                                                    
 RETIRED. `cc reconcile guide-start` is retired: the framework is resolved centrally from the       
 release pointer, and nothing is copied into projects. Use `cc project init` to set a project up    
 and `cc release` to publish or roll back the framework; `cc doctor` verifies the machine.          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile guide-check`

```text
                                                                                                    
 Usage: cc reconcile guide-check [OPTIONS]                                                          
                                                                                                    
 RETIRED. `cc reconcile guide-check` is retired: the framework is resolved centrally from the       
 release pointer, and nothing is copied into projects. Use `cc project init` to set a project up    
 and `cc release` to publish or roll back the framework; `cc doctor` verifies the machine.          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile guide-status`

```text
                                                                                                    
 Usage: cc reconcile guide-status [OPTIONS]                                                         
                                                                                                    
 RETIRED. `cc reconcile guide-status` is retired: the framework is resolved centrally from the      
 release pointer, and nothing is copied into projects. Use `cc project init` to set a project up    
 and `cc release` to publish or roll back the framework; `cc doctor` verifies the machine.          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile guide-finalize`

```text
                                                                                                    
 Usage: cc reconcile guide-finalize [OPTIONS]                                                       
                                                                                                    
 RETIRED. `cc reconcile guide-finalize` is retired: the framework is resolved centrally from the    
 release pointer, and nothing is copied into projects. Use `cc project init` to set a project up    
 and `cc release` to publish or roll back the framework; `cc doctor` verifies the machine.          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile apply`

```text
                                                                                                    
 Usage: cc reconcile apply [OPTIONS]                                                                
                                                                                                    
 RETIRED. `cc reconcile apply` is retired: the framework is resolved centrally from the release     
 pointer, and nothing is copied into projects. Use `cc project init` to set a project up and `cc    
 release` to publish or roll back the framework; `cc doctor` verifies the machine.                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile verify`

```text
                                                                                                    
 Usage: cc reconcile verify [OPTIONS]                                                               
                                                                                                    
 RETIRED. `cc reconcile verify` is retired: the framework is resolved centrally from the release    
 pointer, and nothing is copied into projects. Use `cc project init` to set a project up and `cc    
 release` to publish or roll back the framework; `cc doctor` verifies the machine.                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile recover`

```text
                                                                                                    
 Usage: cc reconcile recover [OPTIONS]                                                              
                                                                                                    
 RETIRED. `cc reconcile recover` is retired: the framework is resolved centrally from the release   
 pointer, and nothing is copied into projects. Use `cc project init` to set a project up and `cc    
 release` to publish or roll back the framework; `cc doctor` verifies the machine.                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc resources`

```text
                                                                                                    
 Usage: cc resources [OPTIONS] COMMAND [ARGS]...                                                    
                                                                                                    
 Bound and clean newly managed synthetic Docker test servers.                                       
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ run           Run COMMAND after -- with a fresh server; success cleans, failure retains 48h.     │
│ status        Show managed runs, ownership and live database counts (read-only).                 │
│ capacity      Measure Docker filesystem usage and enforce 70/85 percent thresholds.              │
│ sweep         Clean only expired, stopped, verified synthetic runs; report holds.                │
│ finish        Dispose of a stopped managed run now, after inspecting its retained evidence.      │
│ validate-env  Refuse provisioning unless database settings match this managed test server.       │
│ maintain      Scheduled sweep and capacity audit; write a bounded local maintenance report.      │
│ audit         Read-only database-server inventory, including unmanaged test candidates.          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc resources run`

```text
                                                                                                    
 Usage: cc resources run [OPTIONS]                                                                  
                                                                                                    
 Run COMMAND after -- with a fresh server; success cleans, failure retains 48h.                     
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│    --project        PATH  [default: .]                                                           │
│ *  --task           TEXT  [required]                                                             │
│    --profile        TEXT  [default: postgres]                                                    │
│    --help                 Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc resources status`

```text
                                                                                                    
 Usage: cc resources status [OPTIONS]                                                               
                                                                                                    
 Show managed runs, ownership and live database counts (read-only).                                 
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc resources capacity`

```text
                                                                                                    
 Usage: cc resources capacity [OPTIONS]                                                             
                                                                                                    
 Measure Docker filesystem usage and enforce 70/85 percent thresholds.                              
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc resources sweep`

```text
                                                                                                    
 Usage: cc resources sweep [OPTIONS]                                                                
                                                                                                    
 Clean only expired, stopped, verified synthetic runs; report holds.                                
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc resources finish`

```text
                                                                                                    
 Usage: cc resources finish [OPTIONS] RUN_ID                                                        
                                                                                                    
 Dispose of a stopped managed run now, after inspecting its retained evidence.                      
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    run_id      TEXT  [required]                                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc resources validate-env`

```text
                                                                                                    
 Usage: cc resources validate-env [OPTIONS]                                                         
                                                                                                    
 Refuse provisioning unless database settings match this managed test server.                       
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --project        PATH  [default: .]                                                              │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc resources maintain`

```text
                                                                                                    
 Usage: cc resources maintain [OPTIONS]                                                             
                                                                                                    
 Scheduled sweep and capacity audit; write a bounded local maintenance report.                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc resources audit`

```text
                                                                                                    
 Usage: cc resources audit [OPTIONS]                                                                
                                                                                                    
 Read-only database-server inventory, including unmanaged test candidates.                          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc store`

```text
                                                                                                    
 Usage: cc store [OPTIONS] COMMAND [ARGS]...                                                        
                                                                                                    
 Verify shared-store access.                                                                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ verify  Check readiness and authorization of the selected secret-store scope.                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc store verify`

```text
                                                                                                    
 Usage: cc store verify [OPTIONS]                                                                   
                                                                                                    
 Check readiness and authorization of the selected secret-store scope.                              
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope        TEXT  Store scope to verify. [default: shared]                                    │
│ --json               Output JSON.                                                                │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc survival`

```text
                                                                                                    
 Usage: cc survival [OPTIONS] COMMAND [ARGS]...                                                     
                                                                                                    
 What fraction of agent-authored lines survive untouched (git-only, no rubric).                     
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --repo                     PATH     Repository to measure. [default: .]                          │
│ --since                    TEXT     Only consider commits after this date (git --since syntax).  │
│ --include-framework                 Also count framework-installed files (.claude/, plugins/,    │
│                                     CLAUDE.md). Off by default: those are replaced wholesale on  │
│                                     every framework update, so their survival measures release   │
│                                     cadence, not the work.                                       │
│ --by-window                         Split by authoring year, so eras are compared at comparable  │
│                                     ages.                                                        │
│ --top                      INTEGER  Also show the N lowest-survival files. [default: 0]          │
│ --json                              Machine-readable output.                                     │
│ --help                              Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc support`

```text
                                                                                                    
 Usage: cc support [OPTIONS] COMMAND [ARGS]...                                                      
                                                                                                    
 Access redacted setup support reports.                                                             
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ latest  Read the latest redacted support report or explain why none is available.                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc support latest`

```text
                                                                                                    
 Usage: cc support latest [OPTIONS]                                                                 
                                                                                                    
 Read the latest redacted support report or explain why none is available.                          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print a paste-ready JSON envelope containing the redacted report.                │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc settings-hook`

```text
                                                                                                    
 Usage: cc settings-hook [OPTIONS] COMMAND [ARGS]...                                                
                                                                                                    
 Register/revert the framework hook shim in ~/.claude/settings.json (user level).                   
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ add           RETIRED. `cc settings-hook add` is retired: the framework is resolved centrally    │
│               from the release pointer, and nothing is copied into projects. Projects carry no   │
│               hook registration; `cc settings-hook user-add` registers the shim once for every   │
│               project. Use `cc project init` to set a project up and `cc release` to publish or  │
│               roll back the framework; `cc doctor` verifies the machine.                         │
│ remove        RETIRED. `cc settings-hook remove` is retired: the framework is resolved centrally │
│               from the release pointer, and nothing is copied into projects. Projects carry no   │
│               hook registration; `cc settings-hook user-add` registers the shim once for every   │
│               project. Use `cc project init` to set a project up and `cc release` to publish or  │
│               roll back the framework; `cc doctor` verifies the machine.                         │
│ rollback      RETIRED. `cc settings-hook rollback` is retired: the framework is resolved         │
│               centrally from the release pointer, and nothing is copied into projects. Projects  │
│               carry no hook registration; `cc settings-hook user-add` registers the shim once    │
│               for every project. Use `cc project init` to set a project up and `cc release` to   │
│               publish or roll back the framework; `cc doctor` verifies the machine.              │
│ list-sources  RETIRED. `cc settings-hook list-sources` is retired: the framework is resolved     │
│               centrally from the release pointer, and nothing is copied into projects. Projects  │
│               carry no hook registration; `cc settings-hook user-add` registers the shim once    │
│               for every project. Use `cc project init` to set a project up and `cc release` to   │
│               publish or roll back the framework; `cc doctor` verifies the machine.              │
│ user-add      Register the framework hook shim once in ~/.claude/settings.json (and              │
│               the skill-listing budget env). Backs up first; preserves all other keys.           │
│ user-remove   Reverse `user-add`: remove only the entries and env keys it added.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc settings-hook add`

```text
                                                                                                    
 Usage: cc settings-hook add [OPTIONS]                                                              
                                                                                                    
 RETIRED. `cc settings-hook add` is retired: the framework is resolved centrally from the release   
 pointer, and nothing is copied into projects. Projects carry no hook registration; `cc             
 settings-hook user-add` registers the shim once for every project. Use `cc project init` to set a  
 project up and `cc release` to publish or roll back the framework; `cc doctor` verifies the        
 machine.                                                                                           
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc settings-hook remove`

```text
                                                                                                    
 Usage: cc settings-hook remove [OPTIONS]                                                           
                                                                                                    
 RETIRED. `cc settings-hook remove` is retired: the framework is resolved centrally from the        
 release pointer, and nothing is copied into projects. Projects carry no hook registration; `cc     
 settings-hook user-add` registers the shim once for every project. Use `cc project init` to set a  
 project up and `cc release` to publish or roll back the framework; `cc doctor` verifies the        
 machine.                                                                                           
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc settings-hook rollback`

```text
                                                                                                    
 Usage: cc settings-hook rollback [OPTIONS]                                                         
                                                                                                    
 RETIRED. `cc settings-hook rollback` is retired: the framework is resolved centrally from the      
 release pointer, and nothing is copied into projects. Projects carry no hook registration; `cc     
 settings-hook user-add` registers the shim once for every project. Use `cc project init` to set a  
 project up and `cc release` to publish or roll back the framework; `cc doctor` verifies the        
 machine.                                                                                           
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc settings-hook list-sources`

```text
                                                                                                    
 Usage: cc settings-hook list-sources [OPTIONS]                                                     
                                                                                                    
 RETIRED. `cc settings-hook list-sources` is retired: the framework is resolved centrally from the  
 release pointer, and nothing is copied into projects. Projects carry no hook registration; `cc     
 settings-hook user-add` registers the shim once for every project. Use `cc project init` to set a  
 project up and `cc release` to publish or roll back the framework; `cc doctor` verifies the        
 machine.                                                                                           
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc settings-hook user-add`

```text
                                                                                                    
 Usage: cc settings-hook user-add [OPTIONS]                                                         
                                                                                                    
 Register the framework hook shim once in ~/.claude/settings.json (and the skill-listing budget     
 env). Backs up first; preserves all other keys.                                                    
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --home           TEXT  Home directory (defaults to $HOME).                                       │
│ --dry-run              Compute without writing.                                                  │
│ --json                 Output as JSON.                                                           │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc settings-hook user-remove`

```text
                                                                                                    
 Usage: cc settings-hook user-remove [OPTIONS]                                                      
                                                                                                    
 Reverse `user-add`: remove only the entries and env keys it added.                                 
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --home        TEXT  Home directory (defaults to $HOME).                                          │
│ --json              Output as JSON.                                                              │
│ --help              Show this message and exit.                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc conformance`

```text
                                                                                                    
 Usage: cc conformance [OPTIONS] COMMAND [ARGS]...                                                  
                                                                                                    
 RETIRED: use `cc doctor` (per-project copy and lock conformance no longer exists).                 
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ check     RETIRED. `cc conformance check` is retired: the framework is resolved centrally from   │
│           the release pointer, and nothing is copied into projects. Use `cc project init` to set │
│           a project up and `cc release` to publish or roll back the framework; `cc doctor`       │
│           verifies the machine.                                                                  │
│ report    RETIRED. `cc conformance report` is retired: the framework is resolved centrally from  │
│           the release pointer, and nothing is copied into projects. Use `cc project init` to set │
│           a project up and `cc release` to publish or roll back the framework; `cc doctor`       │
│           verifies the machine.                                                                  │
│ baseline  RETIRED. `cc conformance baseline` is retired: the framework is resolved centrally     │
│           from the release pointer, and nothing is copied into projects. Use `cc project init`   │
│           to set a project up and `cc release` to publish or roll back the framework; `cc        │
│           doctor` verifies the machine.                                                          │
│ explain   RETIRED. `cc conformance explain` is retired: the framework is resolved centrally from │
│           the release pointer, and nothing is copied into projects. Use `cc project init` to set │
│           a project up and `cc release` to publish or roll back the framework; `cc doctor`       │
│           verifies the machine.                                                                  │
│ list      RETIRED. `cc conformance list` is retired: the framework is resolved centrally from    │
│           the release pointer, and nothing is copied into projects. Use `cc project init` to set │
│           a project up and `cc release` to publish or roll back the framework; `cc doctor`       │
│           verifies the machine.                                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc conformance check`

```text
                                                                                                    
 Usage: cc conformance check [OPTIONS]                                                              
                                                                                                    
 RETIRED. `cc conformance check` is retired: the framework is resolved centrally from the release   
 pointer, and nothing is copied into projects. Use `cc project init` to set a project up and `cc    
 release` to publish or roll back the framework; `cc doctor` verifies the machine.                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc conformance report`

```text
                                                                                                    
 Usage: cc conformance report [OPTIONS]                                                             
                                                                                                    
 RETIRED. `cc conformance report` is retired: the framework is resolved centrally from the release  
 pointer, and nothing is copied into projects. Use `cc project init` to set a project up and `cc    
 release` to publish or roll back the framework; `cc doctor` verifies the machine.                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc conformance baseline`

```text
                                                                                                    
 Usage: cc conformance baseline [OPTIONS]                                                           
                                                                                                    
 RETIRED. `cc conformance baseline` is retired: the framework is resolved centrally from the        
 release pointer, and nothing is copied into projects. Use `cc project init` to set a project up    
 and `cc release` to publish or roll back the framework; `cc doctor` verifies the machine.          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc conformance explain`

```text
                                                                                                    
 Usage: cc conformance explain [OPTIONS]                                                            
                                                                                                    
 RETIRED. `cc conformance explain` is retired: the framework is resolved centrally from the release 
 pointer, and nothing is copied into projects. Use `cc project init` to set a project up and `cc    
 release` to publish or roll back the framework; `cc doctor` verifies the machine.                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc conformance list`

```text
                                                                                                    
 Usage: cc conformance list [OPTIONS]                                                               
                                                                                                    
 RETIRED. `cc conformance list` is retired: the framework is resolved centrally from the release    
 pointer, and nothing is copied into projects. Use `cc project init` to set a project up and `cc    
 release` to publish or roll back the framework; `cc doctor` verifies the machine.                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc rule`

```text
                                                                                                    
 Usage: cc rule [OPTIONS] COMMAND [ARGS]...                                                         
                                                                                                    
 Add, list and propose rules (rewrite in place; no appended exceptions).                            
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ add      Write a rule as a rewrite or a section insert, never appended at the end.               │
│ list     Print the append-only rules log.                                                        │
│ propose  Recommend a destination using the placement test (judgment, procedure, fact).           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc rule add`

```text
                                                                                                    
 Usage: cc rule add [OPTIONS]                                                                       
                                                                                                    
 Write a rule as a rewrite or a section insert, never appended at the end.                          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --text               TEXT  The rule, one current statement. [required]                        │
│    --destination        TEXT  global|framework|project|memory [default: global]                  │
│    --replaces           TEXT  Substring of the one current rule line to rewrite.                 │
│    --section            TEXT  `## ` heading to insert under (last bullet).                       │
│    --file               TEXT  Target file (required for framework).                              │
│    --date               TEXT  YYYY-MM-DD; default today.                                         │
│    --dry-run                  Show the result without writing or logging.                        │
│    --json                     Output JSON.                                                       │
│    --help                     Show this message and exit.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc rule list`

```text
                                                                                                    
 Usage: cc rule list [OPTIONS]                                                                      
                                                                                                    
 Print the append-only rules log.                                                                   
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --since        TEXT  Only entries recorded on or after YYYY-MM-DD.                               │
│ --json               Output JSON.                                                                │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc rule propose`

```text
                                                                                                    
 Usage: cc rule propose [OPTIONS]                                                                   
                                                                                                    
 Recommend a destination using the placement test (judgment, procedure, fact).                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --text        TEXT  The correction. [required]                                                │
│    --json              Output JSON.                                                              │
│    --help              Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc release`

```text
                                                                                                    
 Usage: cc release [OPTIONS] COMMAND [ARGS]...                                                      
                                                                                                    
 Release pointer: immutable releases behind ~/.copilot/current.                                     
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ build     Build a release from signed tags; current changes only with --flip.                    │
│ flip      Atomically point current at RELEASE_ID.                                                │
│ rollback  Walk back --steps releases through history, or to the --to named release.              │
│ status    Show the active release pointer and its manifest.                                      │
│ history   Read the recorded central release transitions.                                         │
│ prune     List exact paths a prune would delete; delete only with --approve --receipt ID.        │
│ shims     (Re)write the cc, tc and tc-limits shims.                                              │
│ doctor    Run release checks; exit 1 on any failure (also used by `cc doctor --release`).        │
│ publish   Build, flip, link, refresh the Codex marketplace, run doctor, record history; restore  │
│           on failure.                                                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc release build`

```text
                                                                                                    
 Usage: cc release build [OPTIONS]                                                                  
                                                                                                    
 Build a release from signed tags; current changes only with --flip.                                
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --pins          PATH  JSON file of framework component pins. [required]                       │
│    --layers        PATH  [default:                                                               │
│                          /private/tmp/cr-release-readiness-20261107/task234-generation/home/.co… │
│    --home          PATH  Home directory (default: user home).                                    │
│    --flip                Flip current to the new release.                                        │
│    --help                Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc release flip`

```text
                                                                                                    
 Usage: cc release flip [OPTIONS] RELEASE_ID                                                        
                                                                                                    
 Atomically point current at RELEASE_ID.                                                            
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    release_id      TEXT  [required]                                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --home          PATH  Home directory (default: user home).                                       │
│ --reason        TEXT                                                                             │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc release rollback`

```text
                                                                                                    
 Usage: cc release rollback [OPTIONS]                                                               
                                                                                                    
 Walk back --steps releases through history, or to the --to named release.                          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --to            TEXT                                                                             │
│ --steps         INTEGER RANGE [x>=1]  Walk back this many releases [default: 1]                  │
│ --home          PATH                  Home directory (default: user home).                       │
│ --reason        TEXT                                                                             │
│ --help                                Show this message and exit.                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc release status`

```text
                                                                                                    
 Usage: cc release status [OPTIONS]                                                                 
                                                                                                    
 Show the active release pointer and its manifest.                                                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --home        PATH  Home directory (default: user home).                                         │
│ --help              Show this message and exit.                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc release history`

```text
                                                                                                    
 Usage: cc release history [OPTIONS]                                                                
                                                                                                    
 Read the recorded central release transitions.                                                     
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --home        PATH  Home directory (default: user home).                                         │
│ --help              Show this message and exit.                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc release prune`

```text
                                                                                                    
 Usage: cc release prune [OPTIONS]                                                                  
                                                                                                    
 List exact paths a prune would delete; delete only with --approve --receipt ID.                    
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --keep           INTEGER  [default: 5]                                                           │
│ --approve                 Delete the paths of --receipt.                                         │
│ --receipt        TEXT                                                                            │
│ --home           PATH     Home directory (default: user home).                                   │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc release shims`

```text
                                                                                                    
 Usage: cc release shims [OPTIONS]                                                                  
                                                                                                    
 (Re)write the cc, tc and tc-limits shims.                                                          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --home        PATH  Home directory (default: user home).                                         │
│ --help              Show this message and exit.                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc release doctor`

```text
                                                                                                    
 Usage: cc release doctor [OPTIONS]                                                                 
                                                                                                    
 Run release checks; exit 1 on any failure (also used by `cc doctor --release`).                    
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --home              PATH  Home directory (default: user home).                                   │
│ --codex-home        PATH  Codex home (default: $CODEX_HOME or ~/.codex).                         │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc release publish`

```text
                                                                                                    
 Usage: cc release publish [OPTIONS]                                                                
                                                                                                    
 Build, flip, link, refresh the Codex marketplace, run doctor, record history; restore on failure.  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --pins                    PATH  JSON file of framework component pins. [required]             │
│    --layers                  PATH  [default:                                                     │
│                                    /private/tmp/cr-release-readiness-20261107/task234-generatio… │
│    --home                    PATH  Home directory (default: user home).                          │
│    --codex-home              PATH                                                                │
│    --retrust                 TEXT  Plugin whose Codex content trust may reset.                   │
│    --no-strict-frozen              Allow plugin directory changes (resets Codex trust).          │
│    --help                          Show this message and exit.                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc project`

```text
                                                                                                    
 Usage: cc project [OPTIONS] COMMAND [ARGS]...                                                      
                                                                                                    
 Initialise and inspect project Copilot state.                                                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ status   Read thin project wiring without changing files or checking machine health.             │
│ init     Write the marker, thin CLAUDE.md/AGENTS.md sections and Codex trust.                    │
│ migrate  Convert a synced project to the central model. Dry run unless --apply.                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc project status`

```text
                                                                                                    
 Usage: cc project status [OPTIONS] [PATH]                                                          
                                                                                                    
 Read thin project wiring without changing files or checking machine health.                        
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   [path]      PATH  Inspect exactly this folder (default: current).                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --all           Registered projects and approved folders only.                                   │
│ --json          Machine-readable output.                                                         │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc project init`

```text
                                                                                                    
 Usage: cc project init [OPTIONS] [PATH]                                                            
                                                                                                    
 Write the marker, thin CLAUDE.md/AGENTS.md sections and Codex trust.                               
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   [path]      PATH  Project folder (default: current). [default: .]                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --force          Back up and recreate a corrupt copilot.project.json.                            │
│ --json           Machine-readable output.                                                        │
│ --help           Show this message and exit.                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc project migrate`

```text
                                                                                                    
 Usage: cc project migrate [OPTIONS] [PATH]                                                         
                                                                                                    
 Convert a synced project to the central model. Dry run unless --apply.                             
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   [path]      PATH  Project folder (default: current). [default: .]                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --apply                            Write the changes. Default is a dry run that only prints the  │
│                                    plan.                                                         │
│ --commit-branch              TEXT  With --apply: commit the migration on a new branch.           │
│ --allow-missing-codex              Proceed when no Codex root resolves; Codex files are kept.    │
│ --source-repo                      Treat PATH as a framework source repo: remove only consumer   │
│                                    artefacts (locks, synced copies outside protected source      │
│                                    paths) and write the marker. Release components are detected  │
│                                    automatically.                                                │
│ --rollback                         Undo a migration from its backup manifest (latest by          │
│                                    default).                                                     │
│ --manifest                   TEXT  With --rollback: the run id or backup folder to restore.      │
│ --scan                             Report copied framework files and locks per project (PATH, or │
│                                    --all); exit 1 if any.                                        │
│ --all                              With --scan: every project in the machine registry.           │
│ --json                             Machine-readable output.                                      │
│ --help                             Show this message and exit.                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

