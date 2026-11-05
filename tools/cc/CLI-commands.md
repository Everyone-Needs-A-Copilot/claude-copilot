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
│ workspace      Discover and activate project Copilot setup.                                      │
│ reconcile      Assess, plan, apply, recover, and verify the selected Copilot ecosystem.          │
│ resources      Bound and clean newly managed synthetic Docker test servers.                      │
│ store          Verify shared-store access.                                                       │
│ survival       What fraction of agent-authored lines survive untouched (git-only, no rubric).    │
│ support        Access redacted setup support reports.                                            │
│ settings-hook  Register/revert framework hooks in a project's .claude/settings.json via the      │
│                reversible mutations[] ledger.                                                    │
│ conformance    Verify ecosystem conformance across tier, stack, install, lock, round-trip, and   │
│                regression layers.                                                                │
│ rule           Add, list and propose rules (rewrite in place; no appended exceptions).           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
                                                                                                    
 Guide: tools/cc/CLI.md in the source repository (purpose, intent, output and recovery).
```

## `cc priorities`

```text
                                                                                                    
 Usage: cc priorities [OPTIONS]                                                                     
                                                                                                    
 Weekly outcomes from every project's open tasks. Read-only.                                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --week        <str>  Reference date YYYY-MM-DD; default today.                                   │
│ --json               Output JSON.                                                                │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc onboard`

```text
                                                                                                    
 Usage: cc onboard [OPTIONS]                                                                        
                                                                                                    
 Discover personal repositories, then optionally create confirmed-missing ones.                     
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope                  <str>  Repository scope; currently personal. [default: personal]        │
│ --components             <str>  Comma-separated ecosystem components.                            │
│                                 [default: knowledge,cli,claude,codex]                            │
│ --apply                         Create confirmed-missing private repositories.                   │
│ --json                          Emit the versioned onboarding report.                            │
│ --org                    <str>  Organization slug for the complete ecosystem transaction.        │
│ --products               <str>  Comma-separated Copilot products. [default: claude,codex]        │
│ --adopt-existing         <str>  Comma-separated components (or `ssh`, for the device's existing  │
│                                 GitHub SSH alias) whose existing content the person consented to │
│                                 include (B1). Scoped per item: each is decided on its own, never │
│                                 all-or-nothing. Any adoptable item left out of this list is a    │
│                                 no-op.                                                           │
│ --repository-root        <str>  Visible folder where ecosystem repositories are kept. When       │
│                                 omitted, cc uses the saved folder or a single unambiguous match  │
│                                 inside approved project roots.                                   │
│ --help                          Show this message and exit.                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc status`

```text
                                                                                                    
 Usage: cc status [OPTIONS]                                                                         
                                                                                                    
 Show installation observations and the last verification run, without probes.                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --project,--root        <path>  Project to inspect (default: current directory). [default: .]    │
│ --json                          Output local observations as JSON.                               │
│ --help                          Show this message and exit.                                      │
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
                                                                                                    
 Usage: cc resolve [OPTIONS] [key]                                                                  
                                                                                                    
 Print the resolved value of a single config key, OR (with `--explain` and no KEY) report the WS-A  
 `resolve --explain --json` ecosystem contract. Read-only in both modes -- does not take the        
 copilot lock.                                                                                      
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   key      <str>  Dotted config key to resolve (e.g. paths.shared_docs). Omit together with      │
│                   --explain for the ecosystem-resolve report.                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope          <str>  machine | project | effective                                            │
│ --explain               Explain the layered ecosystem resolution (winning layer per item, shadow │
│                         chain, override-stale flags) instead of resolving a config key. Requires │
│                         no KEY argument.                                                         │
│ --json                  Output JSON (the WS-A resolve contract, in --explain mode).              │
│ --help                  Show this message and exit.                                              │
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
                                                                                                    
 Usage: cc connect [OPTIONS] {service_id}                                                           
                                                                                                    
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
│ *    service_id      <str>  The service id/name to connect (from `cc connections --json`).       │
│                             [required]                                                           │
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
│ --all-projects          Machine-wide per-project freshness sweep (Component Sync) instead of the │
│                         single-SHA tier poll -- dispatches to                                    │
│                         commands.projects.build_all_projects_freshness().                        │
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
                                                                                                    
 `--project`/`--fanout` are opt-in Component Sync additions (see                                    
 cc/commands/projects.py) -- with neither flag this command is                                      
 byte-shape-identical to the pre-existing contract (regression guard).                              
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                         Output the WS-A update contract as JSON.                          │
│ --dry-run                      Compute the reconciling-sync plan WITHOUT writing/pruning         │
│                                materialize-root content or the lockfile.                         │
│ --project               <str>  Materialize a single embedding project's component instead of the │
│                                machine-wide ecosystem sync (Component Sync Stream-E). Requires   │
│                                --component. Reuses this same --json contract shape plus an       │
│                                additive `path` field.                                            │
│ --component             <str>  The component to materialize for --project (e.g. 'claude',        │
│                                'codex').                                                         │
│ --target-version        <str>  Target version for --project's --component (defaults to its       │
│                                current recorded version -- an up-to-date no-op check).           │
│ --release-tag           <str>  Published release tag licensing the --project apply (required to  │
│                                actually apply a version change; an unverified target is          │
│                                blocked).                                                         │
│ --source-root           <str>  Content root to materialize --project's framework-owned files     │
│                                from.                                                             │
│ --fanout                       Machine-wide fan-out materialize sweep across every discovered    │
│                                project's stale components (Component Sync Stream-E) instead of   │
│                                the machine-wide ecosystem sync.                                  │
│ --help                         Show this message and exit.                                       │
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
│ --json                  Output the WS-A deprovision contract as JSON.                            │
│ --dry-run               Compute the wipe plan WITHOUT removing/quarantining anything.            │
│ --mode           <str>  'soft' (default): wipe materialized content, quarantine mirror clones so │
│                         a flip-back restores without a re-clone. 'hard': also permanently delete │
│                         mirror clones (including any quarantined ones).                          │
│                         [default: soft]                                                          │
│ --soft                  Shorthand for --mode soft (the default).                                 │
│ --hard                  Shorthand for --mode hard.                                               │
│ --help                  Show this message and exit.                                              │
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
                                                                                                    
 Usage: cc memory store [OPTIONS] {content}                                                         
                                                                                                    
 Store a new memory entry as a UUID-named markdown file.                                            
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    content      <str>  Memory content to store. [required]                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --type   -t      <str>  Entry type: decision|context|lesson|reference|person [default: context]  │
│ --tags           <str>  Comma-separated tags, e.g. --tags auth,security                          │
│ --scope  -s      <str>  Scope: project (default if in git repo) or global.                       │
│ --json                  Output result as JSON.                                                   │
│ --help                  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc memory get`

```text
                                                                                                    
 Usage: cc memory get [OPTIONS] {entry_id}                                                          
                                                                                                    
 Retrieve a memory entry by UUID (full or prefix match).                                            
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    entry_id      <str>  Entry UUID (full or prefix). [required]                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope  -s      <str>                                                                           │
│ --json                                                                                           │
│ --help                  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc memory list`

```text
                                                                                                    
 Usage: cc memory list [OPTIONS]                                                                    
                                                                                                    
 List memory entries, optionally filtered by type or tag.                                           
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --type   -t      <str>  Filter by type.                                                          │
│ --tags           <str>  Filter by tag.                                                           │
│ --scope  -s      <str>                                                                           │
│ --json                                                                                           │
│ --help                  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc memory delete`

```text
                                                                                                    
 Usage: cc memory delete [OPTIONS] {entry_id}                                                       
                                                                                                    
 Delete a memory entry file.                                                                        
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    entry_id      <str>  Entry UUID (full or prefix). [required]                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope  -s      <str>                                                                           │
│ --yes    -y             Skip confirmation.                                                       │
│ --help                  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc memory search`

```text
                                                                                                    
 Usage: cc memory search [OPTIONS] {query}                                                          
                                                                                                    
 Search memory entries (FTS index when available, file-based fallback).                             
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    query      <str>  Search query. [required]                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope  -s      <str>                                                                           │
│ --json                                                                                           │
│ --help                  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc memory index`

```text
                                                                                                    
 Usage: cc memory index [OPTIONS]                                                                   
                                                                                                    
 Manage the SQLite FTS search index (local cache, gitignored).                                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --rebuild                 Rebuild the FTS index from files.                                      │
│ --status                  Show index freshness.                                                  │
│ --scope    -s      <str>                                                                         │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc memory export`

```text
                                                                                                    
 Usage: cc memory export [OPTIONS] [query]                                                          
                                                                                                    
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
│   query      <str>  Optional keyword filter — exports only entries matching this search query.   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --type   -t      <str>   Filter by type: decision|context|lesson|reference|person.               │
│ --all                    Export all entries (default when no query or --type is given).          │
│ --json                   Export as a JSON array instead of Markdown.                             │
│ --out            <path>  Write output to this file path instead of stdout.                       │
│ --scope  -s      <str>                                                                           │
│ --help                   Show this message and exit.                                             │
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
│ --scope           -s      <str>                                                                  │
│ --json                           Output structured JSON report.                                  │
│ --no-paths                       Skip path-existence checks.                                     │
│ --no-commands                    Skip command-resolves checks.                                   │
│ --no-stale                       Skip staleness checks.                                          │
│ --staleness-days          <int>  Days threshold for staleness warning. [default: 90]             │
│ --help                           Show this message and exit.                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc memory migrate`

```text
                                                                                                    
 Usage: cc memory migrate [OPTIONS]                                                                 
                                                                                                    
 Migrate legacy copilot-memory SQLite entries to the new file-per-entry format.                     
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --from-global                 Migrate from legacy ~/.claude/memory/*/memory.db databases.        │
│ --status                      Show migration status: source DB entry count vs existing .md       │
│                               files.                                                             │
│ --dry-run                     Print what would be migrated without writing files.                │
│ --scope        -s      <str>  Target scope: project (default if in git repo) or global.          │
│ --all                         Migrate from all discovered legacy databases without prompting.    │
│ --help                        Show this message and exit.                                        │
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
│ --scope        <str>  Scope to scan: project | machine | knowledge | all [default: all]          │
│ --json                Output as JSON.                                                            │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc skill search`

```text
                                                                                                    
 Usage: cc skill search [OPTIONS] {query}                                                           
                                                                                                    
 Search skills by keyword (matches name, description, tags).                                        
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    query      <str>  Search query (keyword match). [required]                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope        <str>  Scope to scan: project | machine | knowledge | all [default: all]          │
│ --json                Output as JSON.                                                            │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc skill get`

```text
                                                                                                    
 Usage: cc skill get [OPTIONS] {name}                                                               
                                                                                                    
 Print the full SKILL.md content (plain text, pipeable).                                            
                                                                                                    
 Example:                                                                                           
 cc skill get security                                                                              
 @include <(cc skill get stride-dread)                                                              
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Skill name (from frontmatter or directory name). [required]                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope        <str>  Scope to scan: project | machine | knowledge | all [default: all]          │
│ --json                Output content and provenance as JSON.                                     │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc skill path`

```text
                                                                                                    
 Usage: cc skill path [OPTIONS] {name}                                                              
                                                                                                    
 Print the absolute path to a SKILL.md file (plain text, pipeable).                                 
                                                                                                    
 Example:                                                                                           
 cc skill path stride-dread                                                                         
 # → /path/to/.claude/skills/security/stride-dread/SKILL.md                                         
 @include $(cc skill path stride-dread)                                                             
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Skill name (from frontmatter or directory name). [required]                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope        <str>  Scope to scan: project | machine | knowledge | all [default: all]          │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc skill select`

```text
                                                                                                    
 Usage: cc skill select [OPTIONS] [query]                                                           
                                                                                                    
 Load relevant optional context with a reproducible selection receipt.                              
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   query      <str>  Keywords for optional skill selection.                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --required         <str>               Required skill; repeatable, never budget-truncated.       │
│ --max-chars        <int range> [x>=0]  Character budget for returned content, not tokens.        │
│                                        [default: 12000]                                          │
│ --scope            <str>               project | machine | knowledge | all [default: all]        │
│ --json                                 Return content and source/selection receipts.             │
│ --help                                 Show this message and exit.                               │
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
                                                                                                    
 Usage: cc config get [OPTIONS] {key}                                                               
                                                                                                    
 Get a resolved configuration value.                                                                
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    key      <str>  Dotted config key (e.g. paths.shared_docs). [required]                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope        <str>  Restrict to: machine | project | effective (default).                      │
│ --raw                 Print raw value without formatting.                                        │
│ --json                Output as JSON.                                                            │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc config set`

```text
                                                                                                    
 Usage: cc config set [OPTIONS] {key} {value}                                                       
                                                                                                    
 Set a configuration value (machine config by default).                                             
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    key        <str>  Dotted config key. [required]                                             │
│ *    value      <str>  Value to set. For list-valued keys (e.g. paths.knowledge_repo), a         │
│                        comma-separated value (e.g. 'a,b,c') is parsed into a list.               │
│                        [required]                                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --project          Write to project config instead of machine config.                            │
│ --help             Show this message and exit.                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc config add`

```text
                                                                                                    
 Usage: cc config add [OPTIONS] {key} {value}                                                       
                                                                                                    
 Append a value to a list-valued config key, idempotently.                                          
                                                                                                    
 Creates the list if the key was previously a string or unset. A value                              
 already present in the list is not duplicated. Order is preserved —                                
 the first entry in the list is consulted first at resolution time.                                 
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    key        <str>  Dotted config key (list-valued, e.g. paths.knowledge_repo). [required]    │
│ *    value      <str>  Value to append to the list. [required]                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --project          Write to project config instead of machine config.                            │
│ --help             Show this message and exit.                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc config remove`

```text
                                                                                                    
 Usage: cc config remove [OPTIONS] {key} {value}                                                    
                                                                                                    
 Remove a value from a list-valued config key (symmetric to `add`).                                 
                                                                                                    
 No-op if the value is not present.                                                                 
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    key        <str>  Dotted config key (list-valued, e.g. paths.knowledge_repo). [required]    │
│ *    value      <str>  Value to remove from the list. [required]                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --project          Remove from project config instead of machine config.                         │
│ --help             Show this message and exit.                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc config unset`

```text
                                                                                                    
 Usage: cc config unset [OPTIONS] {key}                                                             
                                                                                                    
 Remove a key from machine or project config.                                                       
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    key      <str>  Dotted config key to remove. [required]                                     │
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
│ --scope        <str>  Show: machine | project | effective (default).                             │
│ --json                Output as JSON.                                                            │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc config where`

```text
                                                                                                    
 Usage: cc config where [OPTIONS] {key}                                                             
                                                                                                    
 Show which config layer provides a key's value.                                                    
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    key      <str>  Dotted config key. [required]                                               │
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
│ --scope        <str>  Validate: machine | project | both. [default: both]                        │
│ --help                Show this message and exit.                                                │
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
                                                                                                    
 Usage: cc docs resolve [OPTIONS] {pkg}                                                             
                                                                                                    
 Detect the installed/declared version of a package.                                                
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    pkg      <str>  Package name (e.g. 'react', 'requests'). [required]                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --lang  -l      <str>  Ecosystem: js|npm|python|pip  (auto-detected when omitted).               │
│ --json                 Output as JSON.                                                           │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc docs get`

```text
                                                                                                    
 Usage: cc docs get [OPTIONS] {pkg}                                                                 
                                                                                                    
 Fetch documentation for a package.                                                                 
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    pkg      <str>  Package name. [required]                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --topic    -t      <str>               Documentation topic / query string (optional).            │
│ --lang     -l      <str>               Ecosystem: js|npm|python|pip  (auto-detected when         │
│                                        omitted).                                                 │
│ --source   -s      <auto|local|fetch>  Backend: auto (local→fetch), local, or fetch.             │
│                                        [default: auto]                                           │
│ --refresh  -r                          Bypass cache and fetch fresh docs.                        │
│ --json                                 Output as JSON.                                           │
│ --help                                 Show this message and exit.                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc docs search`

```text
                                                                                                    
 Usage: cc docs search [OPTIONS] {pkg} {query}                                                      
                                                                                                    
 Search package documentation for a query topic.                                                    
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    pkg        <str>  Package name. [required]                                                  │
│ *    query      <str>  Search query / topic. [required]                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --lang  -l      <str>                                                                            │
│ --json                                                                                           │
│ --help                 Show this message and exit.                                               │
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
                                                                                                    
 Usage: cc docs cache [OPTIONS] [pkg]                                                               
                                                                                                    
 Inspect or clear the docs cache.                                                                   
                                                                                                    
 Examples:                                                                                          
                                                                                                    
 cc docs cache --status          # show totals                                                      
 cc docs cache --clear           # clear all                                                        
 cc docs cache --clear requests  # not yet supported (pkg-specific clear TBD)                       
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   pkg      <str>  Package to operate on (optional — omit for all packages).                      │
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
                                                                                                    
 Usage: cc design guide [OPTIONS] [action]                                                          
                                                                                                    
 List focused actions or load one source-hashed playbook.                                           
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   action      <str>                                                                              │
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
│ --output        <str>                                                                            │
│ --json                                                                                           │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc design context`

```text
                                                                                                    
 Usage: cc design context [OPTIONS]                                                                 
                                                                                                    
 Load a surface contract and bounded explicit authority, with selection receipts.                   
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --contract         <str>                       [required]                                     │
│    --action           <str>                       [default: shape]                               │
│    --max-chars        <int range> [0<=x<=100000]  [default: 12000]                               │
│    --json                                                                                        │
│    --help                                         Show this message and exit.                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc design review`

```text
                                                                                                    
 Usage: cc design review [OPTIONS]                                                                  
                                                                                                    
 Record initial design judgment before running the detector.                                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --contract          <str>  [required]                                                         │
│ *  --assessment        <str>  [required]                                                         │
│ *  --output            <str>  [required]                                                         │
│    --json                                                                                        │
│    --help                     Show this message and exit.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc design audit`

```text
                                                                                                    
 Usage: cc design audit [OPTIONS] [targets]...                                                      
                                                                                                    
 Run a pinned local static scan; exit 1 when scan evidence is unavailable.                          
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   targets      <str>                                                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --review         <str>                                                                           │
│ --output         <str>                                                                           │
│ --timeout        <int range> [1<=x<=60]  [default: 20]                                           │
│ --json                                                                                           │
│ --help                                   Show this message and exit.                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc design report`

```text
                                                                                                    
 Usage: cc design report [OPTIONS]                                                                  
                                                                                                    
 Check criterion coverage and evidence identity; never issue a QA verdict.                          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --review              <str>  [required]                                                       │
│ *  --audit               <str>  [required]                                                       │
│ *  --verification        <str>  [required]                                                       │
│ *  --output              <str>  [required]                                                       │
│    --json                                                                                        │
│    --help                       Show this message and exit.                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc design compare`

```text
                                                                                                    
 Usage: cc design compare [OPTIONS] {manifest}                                                      
                                                                                                    
 Create a self-contained baseline/candidate screenshot comparison.                                  
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    manifest      <str>  [required]                                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --output        <str>  [required]                                                             │
│    --json                                                                                        │
│    --help                 Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc design feedback-config`

```text
                                                                                                    
 Usage: cc design feedback-config [OPTIONS]                                                         
                                                                                                    
 Enable/disable project feedback and preserve unrelated native hooks.                               
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --runtime                 <str>  [required]                                                   │
│    --enable     --disable           [default: enable]                                            │
│    --json                                                                                        │
│    --help                           Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc design feedback`

```text
                                                                                                    
 Usage: cc design feedback [OPTIONS]                                                                
                                                                                                    
 Native PostToolUse adapter; bounded input/output and no task-state mutation.                       
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --runtime        <str>  [required]                                                            │
│    --help                  Show this message and exit.                                           │
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
                                                                                                    
 Usage: cc design tool register [OPTIONS] {binary}                                                  
                                                                                                    
 Pin a separately verified local Impeccable engine; never trust project-selected executables.       
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    binary      <path>  [required]                                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --sha256         <str>  [required]                                                            │
│ *  --version        <str>  [required]                                                            │
│ *  --source         <str>  [required]                                                            │
│    --replace                                                                                     │
│    --json                                                                                        │
│    --help                  Show this message and exit.                                           │
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
│ --root            <path>  Repository root. [default: .]                                          │
│ --manifest        <str>   Repository-relative manifest. [default: verification.json]             │
│ --changed         <str>   Changed path; repeat as needed.                                        │
│ --base            <str>   Git review base; includes dirty and untracked files.                   │
│ --lane            <str>   Explicit lane scope; repeat as needed.                                 │
│ --task            <str>   Task association only, not approval.                                   │
│ --json                                                                                           │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc verify run`

```text
                                                                                                    
 Usage: cc verify run [OPTIONS]                                                                     
                                                                                                    
 Execute a fresh manifest-bound plan and retain logs under .copilot/verification.                   
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --plan         <path>  Saved JSON plan from cc verify plan. [required]                        │
│    --root         <path>  [default: .]                                                           │
│    --reuse                Opt in to matching hermetic execution reuse; never approval reuse.     │
│    --task         <str>   Override execution's task association; not approval.                   │
│    --json                                                                                        │
│    --help                 Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc verify status`

```text
                                                                                                    
 Usage: cc verify status [OPTIONS]                                                                  
                                                                                                    
 Read durable status without a daemon or task-state changes.                                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --run         <str>   Local run ID. [required]                                                │
│    --root        <path>  [default: .]                                                            │
│    --json                                                                                        │
│    --help                Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc eval`

```text
                                                                                                    
 Usage: cc eval [OPTIONS] COMMAND [ARGS]...                                                         
                                                                                                    
 Run regression evals against agent contracts.                                                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --agent                 <str>    Agent name to evaluate (e.g. qa).                               │
│ --threshold             <float>  Pass-rate threshold [0.0–1.0].                                  │
│ --json                           Emit JSON to stdout.                                            │
│ --list-agents                    List agents that have eval cases.                               │
│ --runner                <str>    'local' (default, static) or 'live' (real headless dispatch;    │
│                                  costs API spend).                                               │
│                                  [default: local]                                                │
│ --max-budget-usd        <float>  Per-dispatch spend cap for --runner live (default: 0.50).       │
│ --help                           Show this message and exit.                                     │
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
│ *  --agent                 <str>    Agent name to evaluate (e.g. qa). [required]                 │
│    --threshold             <float>  Pass-rate threshold [0.0–1.0]. Default from                  │
│                                     quality-gates.json (0.8).                                    │
│    --json                           Emit JSON to stdout.                                         │
│    --runner                <str>    'local' (default): static assertion engine, no LLM calls.    │
│                                     'live': dispatches source.type=live-agent cases through a    │
│                                     real headless `claude --print --agent` session and asserts   │
│                                     against the model's actual output; costs real API spend.     │
│                                     [default: local]                                             │
│    --max-budget-usd        <float>  Per-dispatch spend cap for --runner live (default: 0.50).    │
│    --help                           Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc eval adoption-freeze`

```text
                                                                                                    
 Usage: cc eval adoption-freeze [OPTIONS] {plan}                                                    
                                                                                                    
 Freeze held-out inputs, pinned controls and adoption thresholds.                                   
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    plan      <path>  Pilot plan JSON; brief/rubric paths resolve from its directory.           │
│                        [required]                                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --output        <path>  New frozen receipt path; refuses overwrite. [required]                │
│    --help                  Show this message and exit.                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc eval adoption-check`

```text
                                                                                                    
 Usage: cc eval adoption-check [OPTIONS] {frozen} {observations}                                    
                                                                                                    
 Apply frozen gates to benchmark observations; no runtime dispatch.                                 
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    frozen            <path>  Frozen receipt JSON, located in the pilot directory. [required]   │
│ *    observations      <path>  JSON array of reviewed trial observations. [required]             │
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
│ --agent        <str>  Agent ID to resolve (e.g. sd, cw, ta).                                     │
│ --all                 Resolve every agent ID found in .claude/agents/.                           │
│ --json                Output as JSON.                                                            │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc auth`

```text
                                                                                                    
 Usage: cc auth [OPTIONS] COMMAND [ARGS]...                                                         
                                                                                                    
 GitHub sign-in and least-privilege permission grants.                                              
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --poll                      Perform one device-flow poll step instead of initiating.             │
│ --device-code        <str>  The device_code from a prior `cc auth --json`.                       │
│ --org                <str>  GitHub org slug to sign in through -- see `cc auth login --help`.    │
│ --json                      Output the WS-A auth contract as JSON.                               │
│ --help                      Show this message and exit.                                          │
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
│ --poll                      Perform one device-flow poll step instead of initiating.             │
│ --device-code        <str>  The device_code from a prior `cc auth login --json`.                 │
│ --org                <str>  GitHub org slug to sign in through, on a machine with no             │
│                             github_app.client_id/org configured yet. Required again on every     │
│                             --poll call for the same reason --device-code is: this CLI holds no  │
│                             session state between processes. Falls back to the github_app.org    │
│                             config key (set once via `cc config set` by the app or an admin)     │
│                             when omitted.                                                        │
│ --json                      Output the WS-A auth contract as JSON.                               │
│ --help                      Show this message and exit.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc auth grant`

```text
                                                                                                    
 Usage: cc auth grant [OPTIONS]                                                                     
                                                                                                    
 Request only the permission needed to add this Mac's public SSH key.                               
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --poll                      Perform one permission-grant poll step instead of initiating.        │
│ --device-code        <str>  The device_code from a prior `cc auth grant --json`.                 │
│ --org                <str>  GitHub org slug; falls back to github_app.org.                       │
│ --json                      Output the strict auth permission-grant contract as JSON.            │
│ --help                      Show this message and exit.                                          │
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
                                                                                                    
 Usage: cc layers join [OPTIONS] {layer_id}                                                         
                                                                                                    
 Join an entitled, not-yet-joined department/org layer (WS-A `layers join <id> --json` contract) -- 
 MUTATING: acquires the copilot lock, syncs the layer's mirror, extends the local manifest, and     
 materializes it via `cc update`'s own pipeline. `not-entitled` is a normal outcome, not a crash.   
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    layer_id      <str>  The layer id to join (from `cc layers list`). [required]               │
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
│ *  --task                    <int>  [required]                                                   │
│ *  --runtime                 <str>  [required]                                                   │
│ *  --classification          <str>  [required]                                                   │
│ *  --specialists-json        <str>  [required]                                                   │
│ *  --events-json             <str>  [required]                                                   │
│ *  --prompt-sha256           <str>  [required]                                                   │
│ *  --session                 <str>  [required]                                                   │
│    --json                                                                                        │
│    --help                           Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc journey prepare`

```text
                                                                                                    
 Usage: cc journey prepare [OPTIONS]                                                                
                                                                                                    
 Prepare the next specialist dispatch and return its evidence marker.                               
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --run               <str>  [required]                                                         │
│ *  --specialist        <str>  [required]                                                         │
│    --json                                                                                        │
│    --help                     Show this message and exit.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc journey inspect`

```text
                                                                                                    
 Usage: cc journey inspect [OPTIONS]                                                                
                                                                                                    
 Read the recorded state of one journey run.                                                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --run         <str>  [required]                                                               │
│    --json                                                                                        │
│    --help               Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc journey bind-prompt`

```text
                                                                                                    
 Usage: cc journey bind-prompt [OPTIONS]                                                            
                                                                                                    
 Bind the exact complete Agent prompt before PreToolUse dispatch.                                   
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --run                  <str>  [required]                                                      │
│ *  --specialist           <str>  [required]                                                      │
│ *  --prompt-sha256        <str>  [required]                                                      │
│    --json                                                                                        │
│    --help                        Show this message and exit.                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc journey pause`

```text
                                                                                                    
 Usage: cc journey pause [OPTIONS]                                                                  
                                                                                                    
 Record a continuation point for the selected journey.                                              
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --run         <str>  [required]                                                               │
│    --json                                                                                        │
│    --help               Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc journey abandon`

```text
                                                                                                    
 Usage: cc journey abandon [OPTIONS]                                                                
                                                                                                    
 Close an unfinished run so it stops gating its session.                                            
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --run            <str>  [required]                                                            │
│ *  --session        <str>  [required]                                                            │
│ *  --reason         <str>  [required]                                                            │
│    --json                                                                                        │
│    --help                  Show this message and exit.                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc journey resume`

```text
                                                                                                    
 Usage: cc journey resume [OPTIONS]                                                                 
                                                                                                    
 Resume a recorded journey for the selected task.                                                   
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --task        <int>  [required]                                                               │
│    --run         <str>                                                                           │
│    --json                                                                                        │
│    --help               Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc journey verify-dispatch`

```text
                                                                                                    
 Usage: cc journey verify-dispatch [OPTIONS]                                                        
                                                                                                    
 Verify a dispatch against its session, specialist and exact prompt identity.                       
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --session                 <str>  [required]                                                   │
│ *  --subagent                <str>  [required]                                                   │
│    --marker                  <str>                                                               │
│ *  --prompt-sha256           <str>  [required]                                                   │
│    --knowledge-sha256        <str>                                                               │
│    --json                                                                                        │
│    --help                           Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc workspace`

```text
                                                                                                    
 Usage: cc workspace [OPTIONS] COMMAND [ARGS]...                                                    
                                                                                                    
 Discover and activate project Copilot setup.                                                       
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --project        <str>  Inspect one project workspace.                                           │
│ --all                   Inspect Git projects under approved roots.                               │
│ --json                  Emit the versioned workspace report.                                     │
│ --help                  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ configure     Plan or apply the safe workspace declaration and personal association.             │
│ finish        Plan or apply one immutable, independently verified safe finish.                   │
│ verify        Run authoritative read-only verification for one project.                          │
│ plan          Return a bounded external-assistant prompt or project-owner handoff.               │
│ migrate       Plan or apply deterministic migrations for recognized guided projects.             │
│ hold          Plan or persist an opaque owner-decision hold; never writes the project.           │
│ approve-root  Plan or approve one project folder; never scans outside that folder.               │
│ forget-root   Plan or apply removing one approved folder. Never deletes anything inside it.      │
│ roots         Read configured project folders plus detected one-click candidates. Never writes.  │
│ decline       Plan or apply 'I don't keep projects on this Mac.' Reversible by approving a       │
│               folder later.                                                                      │
│ revert        Plan or apply removing only what Copilot itself added to one project. Never        │
│               touches the person's own files.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc workspace configure`

```text
                                                                                                    
 Usage: cc workspace configure [OPTIONS]                                                            
                                                                                                    
 Plan or apply the safe workspace declaration and personal association.                             
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --project                                          <str>  Project workspace to configure.        │
│ --apply-all                                               Configure every discovered project     │
│                                                           that can be set up, in one call.       │
│ --components                                       <str>  auto or comma-separated claude,codex.  │
│                                                           [default: auto]                        │
│ --share-with-project                                      Write the portable shared project      │
│                                                           declaration.                           │
│ --associate-personal    --no-associate-personal           Associate the opaque project id with   │
│                                                           the private personal-profile seam.     │
│                                                           [default: associate-personal]          │
│ --apply                                                   Apply the explicit                     │
│                                                           declaration/personal association plan. │
│ --json                                                    Emit the versioned workspace report.   │
│ --help                                                    Show this message and exit.            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc workspace finish`

```text
                                                                                                    
 Usage: cc workspace finish [OPTIONS]                                                               
                                                                                                    
 Plan or apply one immutable, independently verified safe finish.                                   
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --project          <str>  Project carrying the exact safe-finish action. [required]           │
│ *  --action-id        <str>  Opaque action id returned by workspace inspection. [required]       │
│    --apply                   Apply the exact action and verify the result.                       │
│    --json                    Emit the versioned workspace report.                                │
│    --help                    Show this message and exit.                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc workspace verify`

```text
                                                                                                    
 Usage: cc workspace verify [OPTIONS]                                                               
                                                                                                    
 Run authoritative read-only verification for one project.                                          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --project        <str>  Project to verify independently. [required]                           │
│    --json                  Emit the versioned workspace report.                                  │
│    --help                  Show this message and exit.                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc workspace plan`

```text
                                                                                                    
 Usage: cc workspace plan [OPTIONS]                                                                 
                                                                                                    
 Return a bounded external-assistant prompt or project-owner handoff.                               
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --project        <str>  Custom project to prepare an integration route for. [required]        │
│    --json                  Emit the versioned workspace report.                                  │
│    --help                  Show this message and exit.                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc workspace migrate`

```text
                                                                                                    
 Usage: cc workspace migrate [OPTIONS]                                                              
                                                                                                    
 Plan or apply deterministic migrations for recognized guided projects.                             
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --project        <str>  One guided project to inspect or migrate.                                │
│ --all                   Inspect every guided project under approved roots.                       │
│ --plan-id        <str>  Exact reviewed plan id required by --apply.                              │
│ --apply                 Apply only the exact eligible deterministic actions.                     │
│ --json                  Emit the versioned migration census and ledger.                          │
│ --help                  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc workspace hold`

```text
                                                                                                    
 Usage: cc workspace hold [OPTIONS]                                                                 
                                                                                                    
 Plan or persist an opaque owner-decision hold; never writes the project.                           
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --project        <str>  Project whose incomplete plan needs its owner. [required]             │
│ *  --plan-id        <str>  Opaque plan id returned by workspace inspection. [required]           │
│    --apply                 Persist the incomplete owner-decision hold.                           │
│    --json                  Emit the versioned workspace report.                                  │
│    --help                  Show this message and exit.                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc workspace approve-root`

```text
                                                                                                    
 Usage: cc workspace approve-root [OPTIONS]                                                         
                                                                                                    
 Plan or approve one project folder; never scans outside that folder.                               
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --path         <str>  Folder the user selected for project discovery. [required]              │
│    --apply               Add this folder to bounded workspace discovery.                         │
│    --json                Emit the versioned root-approval report.                                │
│    --help                Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc workspace forget-root`

```text
                                                                                                    
 Usage: cc workspace forget-root [OPTIONS]                                                          
                                                                                                    
 Plan or apply removing one approved folder. Never deletes anything inside it.                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --path         <str>  Folder to stop watching for projects. [required]                        │
│    --apply               Remove this folder from bounded workspace discovery.                    │
│    --json                Emit the versioned root-approval report.                                │
│    --help                Show this message and exit.                                             │
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

## `cc workspace revert`

```text
                                                                                                    
 Usage: cc workspace revert [OPTIONS]                                                               
                                                                                                    
 Plan or apply removing only what Copilot itself added to one project. Never touches the person's   
 own files.                                                                                         
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --project        <str>  Project to remove Copilot's own added files from. [required]          │
│    --apply                 Remove only the framework files this Mac recorded, and stop offering  │
│                            automatic setup for this project.                                     │
│    --json                  Emit the versioned workspace report.                                  │
│    --help                  Show this message and exit.                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile`

```text
                                                                                                    
 Usage: cc reconcile [OPTIONS] COMMAND [ARGS]...                                                    
                                                                                                    
 Assess, plan, apply, recover, and verify the selected Copilot ecosystem.                           
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ assess             Inspect the Mac and every project below approved roots without writing.       │
│ prepare            Checkpoint Product work and download safe shared updates before setup.        │
│ run                Prepare, update, integrate, and verify this Mac and all projects.             │
│ request            Check the cc/tc prerequisites and write the one-project request.              │
│ plan               Create an exact, expiring plan after a fresh read-only inspection.            │
│ assistant-prepare  Prepare one private content-free Claude Code selection session.               │
│ assistant-run      Run one already-prepared Claude Code session without project access.          │
│ assistant-status   Read one private session and issue a proposal only after fresh validation.    │
│ guide-prepare      Write one Sites-root work order for Codex or Claude Code.                     │
│ guide-start        Record that one visible root-level assistant session started.                 │
│ guide-check        Freshly verify one project and update Python-owned progress.                  │
│ guide-status       Read one guided session without trusting assistant output.                    │
│ guide-finalize     Freshly verify every selected project and close the guided run.               │
│ apply              Apply one claimed plan through the guarded Python transaction.                │
│ verify             Freshly verify the selected components without mutating state.                │
│ recover            Safely finalize interrupted private reconciliation runs.                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile assess`

```text
                                                                                                    
 Usage: cc reconcile assess [OPTIONS]                                                               
                                                                                                    
 Inspect the Mac and every project below approved roots without writing.                            
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Emit the versioned reconciliation report.                                        │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile prepare`

```text
                                                                                                    
 Usage: cc reconcile prepare [OPTIONS]                                                              
                                                                                                    
 Checkpoint Product work and download safe shared updates before setup.                             
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Emit the active setup preparation report.                                        │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile run`

```text
                                                                                                    
 Usage: cc reconcile run [OPTIONS]                                                                  
                                                                                                    
 Prepare, update, integrate, and verify this Mac and all projects.                                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Emit the complete Python-owned setup journey.                                    │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile request`

```text
                                                                                                    
 Usage: cc reconcile request [OPTIONS]                                                              
                                                                                                    
 Check the cc/tc prerequisites and write the one-project request.                                   
                                                                                                    
 This runs inside cc's own runtime so `/setup-project` and `/update-project`                        
 never depend on whichever `python3` happens to be on PATH, and work the same                       
 for a development venv and a frozen release binary.                                                
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --project        <path>  The Git project root to set up or update.                               │
│ --output         <path>  File that receives the canonical request JSON.                          │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile plan`

```text
                                                                                                    
 Usage: cc reconcile plan [OPTIONS]                                                                 
                                                                                                    
 Create an exact, expiring plan after a fresh read-only inspection.                                 
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --request        <path>  Versioned explicit roots/projects/components JSON.                      │
│ --json                   Emit the versioned reconciliation report.                               │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile assistant-prepare`

```text
                                                                                                    
 Usage: cc reconcile assistant-prepare [OPTIONS]                                                    
                                                                                                    
 Prepare one private content-free Claude Code selection session.                                    
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --request        <path>  The exact selected project batch.                                       │
│ --json                   Emit the bounded preparation session report.                            │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile assistant-run`

```text
                                                                                                    
 Usage: cc reconcile assistant-run [OPTIONS]                                                        
                                                                                                    
 Run one already-prepared Claude Code session without project access.                               
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --session-id        <str>  Opaque session identifier returned by prepare.                        │
│ --json                     Emit the bounded Claude Code runner report.                           │
│ --help                     Show this message and exit.                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile assistant-status`

```text
                                                                                                    
 Usage: cc reconcile assistant-status [OPTIONS]                                                     
                                                                                                    
 Read one private session and issue a proposal only after fresh validation.                         
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --session-id        <str>  Opaque session identifier returned by prepare.                        │
│ --json                     Emit the validated proposal status report.                            │
│ --help                     Show this message and exit.                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile guide-prepare`

```text
                                                                                                    
 Usage: cc reconcile guide-prepare [OPTIONS]                                                        
                                                                                                    
 Write one Sites-root work order for Codex or Claude Code.                                          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --request        <path>  The exact selected project batch.                                       │
│ --json                   Emit the guided instruction-package report.                             │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile guide-start`

```text
                                                                                                    
 Usage: cc reconcile guide-start [OPTIONS]                                                          
                                                                                                    
 Record that one visible root-level assistant session started.                                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --guide-id         <str>  Opaque guided-session identifier.                                      │
│ --assistant        <str>  codex or claude-code.                                                  │
│ --json                    Emit the guided-session start report.                                  │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile guide-check`

```text
                                                                                                    
 Usage: cc reconcile guide-check [OPTIONS]                                                          
                                                                                                    
 Freshly verify one project and update Python-owned progress.                                       
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --guide-id        <str>  Opaque guided-session identifier.                                       │
│ --project         <str>  One exact project path from the work order.                             │
│ --json                   Emit the fresh per-project check.                                       │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile guide-status`

```text
                                                                                                    
 Usage: cc reconcile guide-status [OPTIONS]                                                         
                                                                                                    
 Read one guided session without trusting assistant output.                                         
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --guide-id        <str>  Opaque guided-session identifier.                                       │
│ --json                   Emit current Python-owned guided progress.                              │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile guide-finalize`

```text
                                                                                                    
 Usage: cc reconcile guide-finalize [OPTIONS]                                                       
                                                                                                    
 Freshly verify every selected project and close the guided run.                                    
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --guide-id        <str>  Opaque guided-session identifier.                                       │
│ --json                   Emit the fresh whole-run verification.                                  │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile apply`

```text
                                                                                                    
 Usage: cc reconcile apply [OPTIONS]                                                                
                                                                                                    
 Apply one claimed plan through the guarded Python transaction.                                     
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --request        <path>  The exact reviewed selection request.                                   │
│ --plan-id        <str>   Fresh opaque plan identifier returned by plan.                          │
│ --json                   Emit the versioned reconciliation receipt.                              │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile verify`

```text
                                                                                                    
 Usage: cc reconcile verify [OPTIONS]                                                               
                                                                                                    
 Freshly verify the selected components without mutating state.                                     
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --request        <path>  Versioned explicit roots/projects/components JSON.                      │
│ --json                   Emit the versioned reconciliation report.                               │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc reconcile recover`

```text
                                                                                                    
 Usage: cc reconcile recover [OPTIONS]                                                              
                                                                                                    
 Safely finalize interrupted private reconciliation runs.                                           
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Emit the versioned recovery report.                                              │
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
│ validate-env  Refuse provisioning unless PG* settings match this managed test server.            │
│ maintain      Scheduled sweep and capacity audit; write a bounded local maintenance report.      │
│ audit         Read-only database-server inventory, including unmanaged test candidates.          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc resources run`

```text
                                                                                                    
 Usage: cc resources run [OPTIONS]                                                                  
                                                                                                    
 Run COMMAND after -- with a fresh server; success cleans, failure retains 48h.                     
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│    --project        <path>  [default: .]                                                         │
│ *  --task           <str>   [required]                                                           │
│    --profile        <str>   [default: postgres]                                                  │
│    --help                   Show this message and exit.                                          │
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
                                                                                                    
 Usage: cc resources finish [OPTIONS] {run_id}                                                      
                                                                                                    
 Dispose of a stopped managed run now, after inspecting its retained evidence.                      
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    run_id      <str>  [required]                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc resources validate-env`

```text
                                                                                                    
 Usage: cc resources validate-env [OPTIONS]                                                         
                                                                                                    
 Refuse provisioning unless PG* settings match this managed test server.                            
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --project        <path>  [default: .]                                                            │
│ --help                   Show this message and exit.                                             │
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
│ --scope        <str>  Store scope to verify. [default: shared]                                   │
│ --json                Output JSON.                                                               │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc survival`

```text
                                                                                                    
 Usage: cc survival [OPTIONS] COMMAND [ARGS]...                                                     
                                                                                                    
 What fraction of agent-authored lines survive untouched (git-only, no rubric).                     
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --repo                     <path>  Repository to measure. [default: .]                           │
│ --since                    <str>   Only consider commits after this date (git --since syntax).   │
│ --include-framework                Also count framework-installed files (.claude/, plugins/,     │
│                                    CLAUDE.md). Off by default: those are replaced wholesale on   │
│                                    every framework update, so their survival measures release    │
│                                    cadence, not the work.                                        │
│ --by-window                        Split by authoring year, so eras are compared at comparable   │
│                                    ages.                                                         │
│ --top                      <int>   Also show the N lowest-survival files. [default: 0]           │
│ --json                             Machine-readable output.                                      │
│ --help                             Show this message and exit.                                   │
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
                                                                                                    
 Register/revert framework hooks in a project's .claude/settings.json via the reversible            
 mutations[] ledger.                                                                                
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ add           Idempotently register the framework's hook entries into the                        │
│               project's settings file, recording one `mutations[]` ledger row.                   │
│ remove        Surgically strip this mutation's fingerprint-matched hook entries and              │
│               drop its ledger row. Safe to run twice (the second run reports                     │
│               `not-found`, not an error).                                                        │
│ rollback      Byte-exact revert: restore the target to precisely its pre-mutation                │
│               content, refusing (status `conflict`) if the file has changed since.               │
│ list-sources  Read-only report of every hook entry in this project's settings                    │
│               files, classified ours / orphaned / foreign.                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc settings-hook add`

```text
                                                                                                    
 Usage: cc settings-hook add [OPTIONS]                                                              
                                                                                                    
 Idempotently register the framework's hook entries into the project's settings file, recording one 
 `mutations[]` ledger row.                                                                          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --project          <str>  Project root (defaults to the current directory).                      │
│ --scope            <str>  'project' writes .claude/settings.json (team-shared); 'local' writes   │
│                           .claude/settings.local.json (personal, gitignored).                    │
│                           [default: project]                                                     │
│ --source           <str>  Framework layer applying this mutation. [default: claude-copilot]      │
│ --component        <str>  Component this mutation belongs to. [default: claude]                  │
│ --dry-run                 Compute the merge WITHOUT writing anything.                            │
│ --force                   Register even if this project was disabled via `cc settings-hook       │
│                           remove --disable` (clears the sticky opt-out's effect for this run,    │
│                           but does not remove the marker file itself).                           │
│ --json                    Output as JSON.                                                        │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc settings-hook remove`

```text
                                                                                                    
 Usage: cc settings-hook remove [OPTIONS]                                                           
                                                                                                    
 Surgically strip this mutation's fingerprint-matched hook entries and drop its ledger row. Safe to 
 run twice (the second run reports `not-found`, not an error).                                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --id             <str>  The mutations[] id to remove. [required]                              │
│    --project        <str>  Project root (defaults to the current directory).                     │
│    --disable               Clean, ONE-command uninstall: remove this registration AND write the  │
│                            sticky .claude/copilot-hooks-disabled marker, so a later `cc          │
│                            reconcile apply` / `cc update --project` / `cc settings-hook add`     │
│                            does not silently re-add it.                                          │
│    --json                  Output as JSON.                                                       │
│    --help                  Show this message and exit.                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc settings-hook rollback`

```text
                                                                                                    
 Usage: cc settings-hook rollback [OPTIONS]                                                         
                                                                                                    
 Byte-exact revert: restore the target to precisely its pre-mutation content, refusing (status      
 `conflict`) if the file has changed since.                                                         
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --id             <str>  The mutations[] id to roll back. [required]                           │
│    --project        <str>  Project root (defaults to the current directory).                     │
│    --json                  Output as JSON.                                                       │
│    --help                  Show this message and exit.                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc settings-hook list-sources`

```text
                                                                                                    
 Usage: cc settings-hook list-sources [OPTIONS]                                                     
                                                                                                    
 Read-only report of every hook entry in this project's settings files, classified ours / orphaned  
 / foreign.                                                                                         
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --project        <str>  Project root (defaults to the current directory).                        │
│ --json                  Output as JSON.                                                          │
│ --help                  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc conformance`

```text
                                                                                                    
 Usage: cc conformance [OPTIONS] COMMAND [ARGS]...                                                  
                                                                                                    
 Verify ecosystem conformance across tier, stack, install, lock, round-trip, and regression layers. 
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ check     Run the ecosystem conformance harness and report pass/fail.                            │
│ report    Render the ecosystem conformance harness's results in the requested format.            │
│ explain   Print one check's assertion, remediation, and (for non-mutating                        │
│           layers) freshly recomputed evidence against this machine.                              │
│ list      List every registered conformance check id.                                            │
│ baseline  Freeze or diff a conformance baseline.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc conformance check`

```text
                                                                                                    
 Usage: cc conformance check [OPTIONS]                                                              
                                                                                                    
 Run the ecosystem conformance harness and report pass/fail.                                        
                                                                                                    
 Exit codes: 0 conforms, 1 a check failed, 2 the harness could not run                              
 at least one selected check, 3 a --baseline comparison found a                                     
 PASS->FAIL regression. Precedence: baseline-regression > could-not-run                             
 > fail (HARNESS-DESIGN.md section 6.4).                                                            
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --layer           <str>   Restrict to one or more layers                                         │
│                           (tier|stack|repo|lock|regression|roundtrip); default is every layer    │
│                           except roundtrip; --full includes roundtrip in a disposable scratch    │
│                           clone.                                                                 │
│ --fast                    Local-only, cached, no network (the default).                          │
│ --full                    Everything --fast covers plus network/git-remote checks; bypasses the  │
│                           cache.                                                                 │
│ --repo            <str>   Restrict to one or more repos (path or path-suffix match).             │
│ --class           <str>   Restrict to one or more rubric classes (A|B|C|D|E) or                  │
│                           classification.toml classes                                            │
│                           (COMPONENT|PRODUCT|SITE-CONTENT|DOCS-KNOWLEDGE|SCRATCH-ARCHIVE).       │
│ --check           <str>   Restrict to one or more specific check ids.                            │
│ --fail-on         <str>   Exit non-zero if any check at or above this severity fails             │
│                           (S0|S1|S2|S3).                                                         │
│                           [default: S3]                                                          │
│ --baseline        <path>  Compare against a frozen baseline (cc conformance baseline write); a   │
│                           PASS->FAIL regression forces exit 3.                                   │
│ --jobs            <int>   Parallel workers for the repo-layer sweep. [default: 8]                │
│ --no-cache                Bypass the per-repo fast-mode cache even in --fast mode.               │
│ --json                    Output the conformance.schema.json envelope as JSON.                   │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc conformance report`

```text
                                                                                                    
 Usage: cc conformance report [OPTIONS]                                                             
                                                                                                    
 Render the ecosystem conformance harness's results in the requested format.                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --layer           <str>   Restrict layers; fast/default excludes roundtrip, while --full         │
│                           includes its disposable scratch clone.                                 │
│ --fast                    Local-only, cached, no network (the default).                          │
│ --full                    Everything --fast covers plus network/git-remote checks.               │
│ --repo            <str>   Restrict to one or more repos (path or path-suffix match).             │
│ --class           <str>   Restrict to one or more rubric classes (A|B|C|D|E) or                  │
│                           classification.toml classes                                            │
│                           (COMPONENT|PRODUCT|SITE-CONTENT|DOCS-KNOWLEDGE|SCRATCH-ARCHIVE).       │
│ --check           <str>   Restrict to one or more specific check ids.                            │
│ --baseline        <path>  Compare against a frozen baseline and include fixed/still-failing/new  │
│                           counts.                                                                │
│ --jobs            <int>   Parallel workers for the repo-layer sweep. [default: 8]                │
│ --no-cache                Bypass the per-repo fast-mode cache.                                   │
│ --format          <str>   table|tsv|md|json -- how to render the results. [default: table]       │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc conformance explain`

```text
                                                                                                    
 Usage: cc conformance explain [OPTIONS] {check_id}                                                 
                                                                                                    
 Print one check's assertion, remediation, and (for non-mutating layers) freshly recomputed         
 evidence against this machine.                                                                     
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    check_id      <str>  A registered check id, e.g. tier.shadow.substance. [required]          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Output the registration plus live evidence as JSON.                              │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc conformance list`

```text
                                                                                                    
 Usage: cc conformance list [OPTIONS]                                                               
                                                                                                    
 List every registered conformance check id.                                                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --layer           <str>  Filter to one or more layers.                                           │
│ --severity        <str>  Filter to one or more severities (S0|S1|S2|S3).                         │
│ --json                   Output the filtered registration list as JSON.                          │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc conformance baseline`

```text
                                                                                                    
 Usage: cc conformance baseline [OPTIONS] COMMAND [ARGS]...                                         
                                                                                                    
 Freeze or diff a conformance baseline.                                                             
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ write  Freeze the current verdict set as a baseline (`cc conformance check                       │
│        --baseline`/`cc conformance baseline diff` compare future runs against                    │
│        it).                                                                                      │
│ diff   Show what changed since a frozen baseline. Exit 3 on any PASS->FAIL                       │
│        regression, else 0 -- independent of --fail-on (there is none here;                       │
│        this command reports, it never gates on absolute severity).                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc conformance baseline write`

```text
                                                                                                    
 Usage: cc conformance baseline write [OPTIONS] {path}                                              
                                                                                                    
 Freeze the current verdict set as a baseline (`cc conformance check --baseline`/`cc conformance    
 baseline diff` compare future runs against it).                                                    
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    path      <path>  Where to write the frozen baseline JSON. [required]                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --layer           <str>  Restrict layers; fast/default excludes roundtrip, while --full includes │
│                          its disposable scratch clone.                                           │
│ --fast                   Local-only, cached, no network (the default).                           │
│ --full                   Everything --fast covers plus network/git-remote checks.                │
│ --jobs            <int>  Parallel workers for the repo-layer sweep. [default: 8]                 │
│ --no-cache               Bypass the per-repo fast-mode cache.                                    │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc conformance baseline diff`

```text
                                                                                                    
 Usage: cc conformance baseline diff [OPTIONS] {path}                                               
                                                                                                    
 Show what changed since a frozen baseline. Exit 3 on any PASS->FAIL regression, else 0 --          
 independent of --fail-on (there is none here; this command reports, it never gates on absolute     
 severity).                                                                                         
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    path      <path>  An existing baseline JSON (from `baseline write`). [required]             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --layer           <str>  Restrict layers; fast/default excludes roundtrip, while --full includes │
│                          its disposable scratch clone.                                           │
│ --fast                   Local-only, cached, no network (the default).                           │
│ --full                   Everything --fast covers plus network/git-remote checks.                │
│ --jobs            <int>  Parallel workers for the repo-layer sweep. [default: 8]                 │
│ --no-cache               Bypass the per-repo fast-mode cache.                                    │
│ --json                   Output the comparison as JSON.                                          │
│ --help                   Show this message and exit.                                             │
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
│ *  --text               <str>  The rule, one current statement. [required]                       │
│    --destination        <str>  global|framework|project|memory [default: global]                 │
│    --replaces           <str>  Substring of the one current rule line to rewrite.                │
│    --section            <str>  `## ` heading to insert under (last bullet).                      │
│    --file               <str>  Target file (required for framework).                             │
│    --date               <str>  YYYY-MM-DD; default today.                                        │
│    --dry-run                   Show the result without writing or logging.                       │
│    --json                      Output JSON.                                                      │
│    --help                      Show this message and exit.                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc rule list`

```text
                                                                                                    
 Usage: cc rule list [OPTIONS]                                                                      
                                                                                                    
 Print the append-only rules log.                                                                   
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --since        <str>  Only entries recorded on or after YYYY-MM-DD.                              │
│ --json                Output JSON.                                                               │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `cc rule propose`

```text
                                                                                                    
 Usage: cc rule propose [OPTIONS]                                                                   
                                                                                                    
 Recommend a destination using the placement test (judgment, procedure, fact).                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --text        <str>  The correction. [required]                                               │
│    --json               Output JSON.                                                             │
│    --help               Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

