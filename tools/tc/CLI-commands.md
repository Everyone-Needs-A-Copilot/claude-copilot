# tc command reference

Generated from the registered parser. Command callbacks were not executed. For intent, effects, configuration and recovery, read the companion CLI guide.

## `tc`

```text
                                                                                                    
 Usage: tc [OPTIONS] COMMAND [ARGS]...                                                              
                                                                                                    
 Agent-agnostic task management CLI for AI development workflows.                                   
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --install-completion          Install completion for the current shell.                          │
│ --show-completion             Show completion for the current shell, to copy it or customize the │
│                               installation.                                                      │
│ --help                        Show this message and exit.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ archive     Move finished tasks (with their log and work products) into the history file.        │
│ init        Initialize a new Task Copilot database in the current directory.                     │
│ version     Show the tc version.                                                                 │
│ progress    Show task progress summary by status per stream and totals.                          │
│ handoff     Log an agent handoff and update the task's assigned agent.                           │
│ log         List agent activity log entries.                                                     │
│ watch       Live dashboard showing task progress, agents, and activity.                          │
│ worker      Dispatch a Claude agent to work on a task in non-interactive mode.                   │
│ provenance  Verify source, dependency and enforcement capability against install receipts.       │
│ prd         PRD management commands.                                                             │
│ stream      Stream management commands.                                                          │
│ task        Task management commands.                                                            │
│ wp          Work product commands.                                                               │
│ db          Database management commands.                                                        │
│ deploy      Deployment orchestration commands.                                                   │
│ history     Archived tasks (.copilot/tasks.db-history).                                          │
│ execution   Persistent scope, experiment limits, evidence and handoff status.                    │
│ repo        Registered repositories for contract externalSources (id -> checkout and origin).    │
│ tests       Per-project test selection.                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
                                                                                                    
 Guide: tools/tc/CLI.md in the source repository (purpose, intent, output and recovery).
```

## `tc archive`

```text
                                                                                                    
 Usage: tc archive [OPTIONS]                                                                        
                                                                                                    
 Move finished tasks (with their log and work products) into the history file.                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --days           <int>  Archive finished tasks idle at least this many days. [default: 14]       │
│ --dry-run               List what would move without moving it.                                  │
│ --json                  Output as JSON.                                                          │
│ --help                  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc init`

```text
                                                                                                    
 Usage: tc init [OPTIONS]                                                                           
                                                                                                    
 Initialize a new Task Copilot database in the current directory.                                   
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --path        <path>  Directory to initialize in (default: current directory).                   │
│ --json                Output as JSON.                                                            │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc version`

```text
                                                                                                    
 Usage: tc version [OPTIONS]                                                                        
                                                                                                    
 Show the tc version.                                                                               
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc progress`

```text
                                                                                                    
 Usage: tc progress [OPTIONS]                                                                       
                                                                                                    
 Show task progress summary by status per stream and totals.                                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --stream        <int>  Filter by stream ID.                                                      │
│ --json                 Output as JSON.                                                           │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc handoff`

```text
                                                                                                    
 Usage: tc handoff [OPTIONS]                                                                        
                                                                                                    
 Log an agent handoff and update the task's assigned agent.                                         
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --from           <str>  Handing-off agent. [required]                                         │
│ *  --to             <str>  Receiving agent. [required]                                           │
│ *  --task           <int>  Task ID being handed off. [required]                                  │
│ *  --context        <str>  Handoff context (max 200 chars). [required]                           │
│    --json                  Output as JSON.                                                       │
│    --help                  Show this message and exit.                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc log`

```text
                                                                                                    
 Usage: tc log [OPTIONS]                                                                            
                                                                                                    
 List agent activity log entries.                                                                   
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --agent         <str>  Filter by agent.                                                          │
│ --stream        <int>  Filter by stream ID.                                                      │
│ --task          <int>  Filter by task ID.                                                        │
│ --limit         <int>  Maximum entries to return. [default: 50]                                  │
│ --json                 Output as JSON.                                                           │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc watch`

```text
                                                                                                    
 Usage: tc watch [OPTIONS]                                                                          
                                                                                                    
 Live dashboard showing task progress, agents, and activity.                                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --refresh  -r      <int>  Refresh interval in seconds. [default: 5]                              │
│ --compact                 Simplified view without activity log.                                  │
│ --stream   -s      <int>  Filter to single stream.                                               │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc worker`

```text
                                                                                                    
 Usage: tc worker [OPTIONS] {task_id}                                                               
                                                                                                    
 Dispatch a Claude agent to work on a task in non-interactive mode.                                 
                                                                                                    
 Wraps ``claude --print --output-format json`` with the ``--max-budget-usd``                        
 flag plumbed through when set.  The spending cap itself is enforced by the                         
 harness at the API boundary; tc's job is measurement and breach handling:                          
 the run's cost/turn data is recorded to ``agent_log``, and if the run is                           
 killed for exceeding its cap, the task is released back to ``pending``                             
 (claim cleared) instead of being left silently stuck ``in_progress``.                              
                                                                                                    
 In dry-run mode, prints the command that would be executed and exits                               
 without touching the database or spending anything.                                                
                                                                                                    
 This is the canonical tc-side dispatch path for non-interactive (headless)                         
 agent runs, and `/orchestrate` mirrors this flag set.  Chat delivery is not                        
 a dispatch path here: `copilot discord dispatch -- tc worker <id> ...` wraps                       
 this command from CLI Copilot's side, so the reporting concern stays there                         
 and this command stays unaware of it.                                                              
                                                                                                    
 Examples::                                                                                         
                                                                                                    
     tc worker 42                                                                                   
     tc worker 42 --max-budget-usd 2.50                                                             
     tc worker 42 --max-budget-usd 2.50 --dry-run                                                   
     tc worker 42 --max-budget-usd 2.50 --dry-run --json                                            
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task_id      <int>  Task ID to dispatch an agent for. [required]                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --criterion             <str>    Required acceptance criterion for guarded workers.              │
│ --max-budget-usd        <float>  Per-run spending cap in USD, passed to 'claude --print          │
│                                  --max-budget-usd' and enforced by the harness at the API        │
│                                  boundary. tc records the resulting spend to agent_log and       │
│                                  releases the task if the run is killed for exceeding it.        │
│ --model                 <str>    Model override passed to 'claude --print --model'.              │
│ --agent                 <str>    Agent role to invoke (default: me).                             │
│ --dry-run                        Print the dispatch command without executing it.                │
│ --json                           Emit JSON result to stdout.                                     │
│ --help                           Show this message and exit.                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc provenance`

```text
                                                                                                    
 Usage: tc provenance [OPTIONS]                                                                     
                                                                                                    
 Verify source, dependency and enforcement capability against install receipts.                     
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --record          Explicitly record this installation after package setup.                       │
│ --json                                                                                           │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc prd`

```text
                                                                                                    
 Usage: tc prd [OPTIONS] COMMAND [ARGS]...                                                          
                                                                                                    
 PRD management commands.                                                                           
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ create  Create a new PRD.                                                                        │
│ list    List all PRDs.                                                                           │
│ get     Get a PRD by ID.                                                                         │
│ update  Update a PRD.                                                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc prd create`

```text
                                                                                                    
 Usage: tc prd create [OPTIONS]                                                                     
                                                                                                    
 Create a new PRD.                                                                                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --title              <str>   PRD title. [required]                                            │
│    --description        <str>   Short description.                                               │
│    --content            <str>   Full PRD content.                                                │
│    --file               <path>  Read content from file.                                          │
│    --json                       Output as JSON.                                                  │
│    --help                       Show this message and exit.                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc prd list`

```text
                                                                                                    
 Usage: tc prd list [OPTIONS]                                                                       
                                                                                                    
 List all PRDs.                                                                                     
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --status        <str>  Filter by status.                                                         │
│ --json                 Output as JSON.                                                           │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc prd get`

```text
                                                                                                    
 Usage: tc prd get [OPTIONS] {prd_id}                                                               
                                                                                                    
 Get a PRD by ID.                                                                                   
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    prd_id      <int>  PRD ID. [required]                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Output as JSON.                                                                  │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc prd update`

```text
                                                                                                    
 Usage: tc prd update [OPTIONS] {prd_id}                                                            
                                                                                                    
 Update a PRD.                                                                                      
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    prd_id      <int>  PRD ID. [required]                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --title          <str>   New title.                                                              │
│ --status         <str>   New status.                                                             │
│ --content        <str>   New content.                                                            │
│ --file           <path>  Read content from file.                                                 │
│ --json                   Output as JSON.                                                         │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc stream`

```text
                                                                                                    
 Usage: tc stream [OPTIONS] COMMAND [ARGS]...                                                       
                                                                                                    
 Stream management commands.                                                                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ create     Create a new stream.                                                                  │
│ list       List all streams.                                                                     │
│ get        Get a stream by name or ID.                                                           │
│ conflicts  Find files claimed by more than one active/paused stream's tasks.                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc stream create`

```text
                                                                                                    
 Usage: tc stream create [OPTIONS]                                                                  
                                                                                                    
 Create a new stream.                                                                               
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --name                 <str>  Stream name (unique). [required]                                │
│ *  --prd                  <int>  Associated PRD ID. [required]                                   │
│    --worktree-path        <str>  Git worktree path.                                              │
│    --json                        Output as JSON.                                                 │
│    --help                        Show this message and exit.                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc stream list`

```text
                                                                                                    
 Usage: tc stream list [OPTIONS]                                                                    
                                                                                                    
 List all streams.                                                                                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --status        <str>  Filter by status.                                                         │
│ --json                 Output as JSON.                                                           │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc stream get`

```text
                                                                                                    
 Usage: tc stream get [OPTIONS] {name_or_id}                                                        
                                                                                                    
 Get a stream by name or ID.                                                                        
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name_or_id      <str>  Stream name or ID. [required]                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Output as JSON.                                                                  │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc stream conflicts`

```text
                                                                                                    
 Usage: tc stream conflicts [OPTIONS]                                                               
                                                                                                    
 Find files claimed by more than one active/paused stream's tasks.                                  
                                                                                                    
 Reads each stream's tasks' `metadata.files` (written by `/orchestrate                              
 generate`) and reports any file more than one stream claims. Exits                                 
 non-zero when a conflict is found so `/orchestrate start` can use this as                          
 a hard precondition before creating worktrees for parallel streams.                                
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Output as JSON.                                                                  │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc task`

```text
                                                                                                    
 Usage: tc task [OPTIONS] COMMAND [ARGS]...                                                         
                                                                                                    
 Task management commands.                                                                          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ create             Create a new task.                                                            │
│ list               List tasks with optional filters. Parked tasks are hidden unless asked for.   │
│ get                Get a task by ID.                                                             │
│ update             Update a task.                                                                │
│ check-qa           Check task-bound QA evidence using the completion predicate.                  │
│ claim              Atomically claim a task for an agent.                                         │
│ next               Get the next highest-priority pending task with all dependencies completed.   │
│ stale              List open, unparked tasks with no activity for --days days (oldest first).    │
│ park               Set open tasks aside without closing them. Hidden from `list` and `next`;     │
│                    undo with `unpark`.                                                           │
│ unpark             Return parked tasks to the active list.                                       │
│ cancel             Cancel tasks with a recorded reason (metadata.cancelReason).                  │
│ contract           Register observable acceptance criteria before implementation/QA.             │
│ review             Record the four close-out booleans on a task, or summarise them for this      │
│                    project.                                                                      │
│ evidence-identity  Capture task/source/runtime identity BEFORE running verification.             │
│ tier               Record a task's verification tier, or check the diff against it. Tiers only   │
│                    rise without owner authority.                                                 │
│ attest             Record the one T1/T2 check and its result. tc refuses when the diff needs a   │
│                    higher tier.                                                                  │
│ qa-packet          Print a T3 QA packet pre-filled with the captured IDENTITY and each           │
│                    criterion's exact text.                                                       │
│ deps               Task dependency management.                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc task create`

```text
                                                                                                    
 Usage: tc task create [OPTIONS]                                                                    
                                                                                                    
 Create a new task.                                                                                 
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --title              <str>  Task title. [required]                                            │
│    --prd                <int>  Associated PRD ID.                                                │
│    --stream             <int>  Associated stream ID.                                             │
│    --agent              <str>  Assigned agent.                                                   │
│    --priority           <int>  Priority 0-3 (0=highest). [default: 2]                            │
│    --parent             <int>  Parent task ID.                                                   │
│    --description        <str>  Task description.                                                 │
│    --metadata           <str>  JSON metadata string.                                             │
│    --json                      Output as JSON.                                                   │
│    --help                      Show this message and exit.                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc task list`

```text
                                                                                                    
 Usage: tc task list [OPTIONS]                                                                      
                                                                                                    
 List tasks with optional filters. Parked tasks are hidden unless asked for.                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --status                <str>  Filter by status.                                                 │
│ --agent                 <str>  Filter by agent.                                                  │
│ --stream                <int>  Filter by stream ID.                                              │
│ --prd                   <int>  Filter by PRD ID.                                                 │
│ --include-parked               Also list parked tasks (hidden by default).                       │
│ --parked                       List only parked tasks.                                           │
│ --json                         Output as JSON.                                                   │
│ --help                         Show this message and exit.                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc task get`

```text
                                                                                                    
 Usage: tc task get [OPTIONS] {task_id}                                                             
                                                                                                    
 Get a task by ID.                                                                                  
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task_id      <int>  Task ID. [required]                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Output as JSON.                                                                  │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc task update`

```text
                                                                                                    
 Usage: tc task update [OPTIONS] {task_id}                                                          
                                                                                                    
 Update a task.                                                                                     
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task_id      <int>  Task ID. [required]                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --status             <str>  New status.                                                          │
│ --agent              <str>  Assigned agent.                                                      │
│ --description        <str>  New description.                                                     │
│ --priority           <int>  New priority 0-3.                                                    │
│ --title              <str>  New title.                                                           │
│ --metadata           <str>  JSON metadata to merge into existing metadata.                       │
│ --json                      Output as JSON.                                                      │
│ --help                      Show this message and exit.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc task check-qa`

```text
                                                                                                    
 Usage: tc task check-qa [OPTIONS] {task_id}                                                        
                                                                                                    
 Check task-bound QA evidence using the completion predicate.                                       
                                                                                                    
 Read-only inspector: reports what `tc task update --status completed`                              
 would decide for this task right now, without changing anything. Exits                             
 1 when the evidence does not currently support approval.                                           
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task_id      <int>  Task ID. [required]                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Output as JSON.                                                                  │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc task claim`

```text
                                                                                                    
 Usage: tc task claim [OPTIONS] {task_id}                                                           
                                                                                                    
 Atomically claim a task for an agent.                                                              
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task_id      <int>  Task ID. [required]                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --agent        <str>  Agent claiming the task. [required]                                     │
│    --json                Output as JSON.                                                         │
│    --help                Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc task next`

```text
                                                                                                    
 Usage: tc task next [OPTIONS]                                                                      
                                                                                                    
 Get the next highest-priority pending task with all dependencies completed.                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --stream        <int>  Filter by stream ID.                                                      │
│ --agent         <str>  Filter by agent.                                                          │
│ --json                 Output as JSON.                                                           │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc task stale`

```text
                                                                                                    
 Usage: tc task stale [OPTIONS]                                                                     
                                                                                                    
 List open, unparked tasks with no activity for --days days (oldest first).                         
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --days        <int>  Idle for at least this many days. [default: 30]                             │
│ --json               Output as JSON.                                                             │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc task park`

```text
                                                                                                    
 Usage: tc task park [OPTIONS] [task_ids]...                                                        
                                                                                                    
 Set open tasks aside without closing them. Hidden from `list` and `next`; undo with `unpark`.      
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   task_ids      <int>  Task IDs to park.                                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --reason        <str>  Why it is set aside. [required]                                        │
│    --stale                Park every stale task instead of listed IDs.                           │
│    --days          <int>  With --stale: idle threshold in days. [default: 30]                    │
│    --json                 Output as JSON.                                                        │
│    --help                 Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc task unpark`

```text
                                                                                                    
 Usage: tc task unpark [OPTIONS] {task_ids}...                                                      
                                                                                                    
 Return parked tasks to the active list.                                                            
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task_ids      <int>  Task IDs to return to the active list. [required]                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Output as JSON.                                                                  │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc task cancel`

```text
                                                                                                    
 Usage: tc task cancel [OPTIONS] [task_ids]...                                                      
                                                                                                    
 Cancel tasks with a recorded reason (metadata.cancelReason).                                       
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   task_ids      <int>  Task IDs to cancel.                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --reason        <str>  Why it will not be done. [required]                                    │
│    --stale                Cancel every stale task instead of listed IDs.                         │
│    --days          <int>  With --stale: idle threshold in days. [default: 30]                    │
│    --json                 Output as JSON.                                                        │
│    --help                 Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc task contract`

```text
                                                                                                    
 Usage: tc task contract [OPTIONS] {task_id}                                                        
                                                                                                    
 Register observable acceptance criteria before implementation/QA.                                  
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task_id      <int>  [required]                                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --file                   <str>  JSON acceptance contract: schemaVersion 2 (criteria, sources), 3 │
│                                 (adds externalSources: [{repo, ref, paths}] for registered       │
│                                 repos; see tc repo add) or 4 (kind, optional sources, lane,      │
│                                 excluded, assumptions).                                          │
│ --from-done-block        <str>  Text file with the five done-block lines; registers a            │
│                                 schemaVersion 4 contract and execution limits.                   │
│ --kind                   <str>  With --from-done-block: software, document, design, research or  │
│                                 automation.                                                      │
│                                 [default: software]                                              │
│ --source                 <str>  With --from-done-block: project-relative source (repeatable).    │
│ --criterion              <str>  With --from-done-block: extra criterion as ID=expected           │
│                                 (repeatable).                                                    │
│ --lane-focused           <str>  Focused check command.                                           │
│ --lane-affected          <str>  Affected check command.                                          │
│ --cap-seconds            <int>  Lane cap in seconds.                                             │
│ --json                                                                                           │
│ --help                          Show this message and exit.                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc task review`

```text
                                                                                                    
 Usage: tc task review [OPTIONS] [task_id]                                                          
                                                                                                    
 Record the four close-out booleans on a task, or summarise them for this project.                  
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   task_id      <int>  Task ID to record the close-out review on.                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --scope-recovered           --no-scope-recovered                  [default: no-scope-recovered]  │
│ --completion-recovered      --no-completion-recovered             [default:                      │
│                                                                   no-completion-recovered]       │
│ --authorization-repeated    --no-authorization-repeated           [default:                      │
│                                                                   no-authorization-repeated]     │
│ --rework-from-assumption    --no-rework-from-assumption           [default:                      │
│                                                                   no-rework-from-assumption]     │
│ --note                                                     <str>  Short free-text note.          │
│ --summary                                                         Print this project's review    │
│                                                                   counts instead of recording.   │
│ --since                                                    <str>  With --summary: only tasks     │
│                                                                   completed on or after          │
│                                                                   YYYY-MM-DD.                    │
│ --json                                                                                           │
│ --help                                                            Show this message and exit.    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc task evidence-identity`

```text
                                                                                                    
 Usage: tc task evidence-identity [OPTIONS] {task_id}                                               
                                                                                                    
 Capture task/source/runtime identity BEFORE running verification.                                  
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task_id      <int>  [required]                                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                           │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc task tier`

```text
                                                                                                    
 Usage: tc task tier [OPTIONS] {task_id} [tier]                                                     
                                                                                                    
 Record a task's verification tier, or check the diff against it. Tiers only rise without owner     
 authority.                                                                                         
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task_id      <int>  [required]                                                              │
│      tier         <str>  T1 copy, T2 structural, T3 foundational. Omit with --check.             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --reason           <str>  Why this tier.                                                         │
│ --authority        <str>  The owner's verbatim words; required to LOWER a tier. Never write this │
│                           on the owner's behalf.                                                 │
│ --check                   Classify the actual diff and print the minimum tier.                   │
│ --base             <str>  Git revision to diff against (default: the revision recorded with the  │
│                           tier, else HEAD).                                                      │
│ --json                                                                                           │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc task attest`

```text
                                                                                                    
 Usage: tc task attest [OPTIONS] {task_id}                                                          
                                                                                                    
 Record the one T1/T2 check and its result. tc refuses when the diff needs a higher tier.           
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task_id      <int>  [required]                                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --tier           <str>  T1 or T2. [required]                                                  │
│    --in             <str>  T1: built file to read.                                               │
│    --present        <str>  T1: new text that must be in --in (repeatable).                       │
│    --absent         <str>  T1: old text that must be gone (repeatable).                          │
│    --load           <str>  T1: screenshot of one successful browser load.                        │
│    --render         <str>  T2: render artifact, one or two (repeatable).                         │
│    --checks         <str>  T2: cc verify run id (tc reads its stored status).                    │
│    --source         <str>  VALUE=file:line | WP-id | pablo:<quote>, for each changed number.     │
│    --base           <str>  Git revision to diff against.                                         │
│    --agent          <str>                                                                        │
│    --json                                                                                        │
│    --help                  Show this message and exit.                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc task qa-packet`

```text
                                                                                                    
 Usage: tc task qa-packet [OPTIONS] {task_id}                                                       
                                                                                                    
 Print a T3 QA packet pre-filled with the captured IDENTITY and each criterion's exact text.        
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task_id      <int>  [required]                                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --carry        <str>  WP-N:C1,C2 - pre-fill those criteria from an earlier packet (repeatable).  │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc task deps`

```text
                                                                                                    
 Usage: tc task deps [OPTIONS] COMMAND [ARGS]...                                                    
                                                                                                    
 Task dependency management.                                                                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ add     Add a dependency to a task.                                                              │
│ remove  Remove a dependency from a task.                                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc task deps add`

```text
                                                                                                    
 Usage: tc task deps add [OPTIONS] {task_id}                                                        
                                                                                                    
 Add a dependency to a task.                                                                        
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task_id      <int>  Task ID. [required]                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --depends-on        <int>  Dependency task ID. [required]                                     │
│    --json                     Output as JSON.                                                    │
│    --help                     Show this message and exit.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc task deps remove`

```text
                                                                                                    
 Usage: tc task deps remove [OPTIONS] {task_id}                                                     
                                                                                                    
 Remove a dependency from a task.                                                                   
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task_id      <int>  Task ID. [required]                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --depends-on        <int>  Dependency task ID to remove. [required]                           │
│    --json                     Output as JSON.                                                    │
│    --help                     Show this message and exit.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc wp`

```text
                                                                                                    
 Usage: tc wp [OPTIONS] COMMAND [ARGS]...                                                           
                                                                                                    
 Work product commands.                                                                             
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ render  Render a work product to a standalone self-contained HTML file.                          │
│ store   Store a work product, using hybrid storage for large content.                            │
│ get     Get a work product by ID, reading file content if stored externally.                     │
│ list    List work products with optional filters.                                                │
│ search  Search work products using FTS5 full-text search.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc wp render`

```text
                                                                                                    
 Usage: tc wp render [OPTIONS] {wp_id}                                                              
                                                                                                    
 Render a work product to a standalone self-contained HTML file.                                    
                                                                                                    
 Prints only the absolute path to the rendered file — the HTML body is                              
 never written to stdout (token-free side artifact).                                                
                                                                                                    
 Output path convention: .copilot/renders/WP-<id>.html                                              
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    wp_id      <int>  Work product ID to render. [required]                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --html    --no-html            Render as self-contained HTML (default: true). [default: html]    │
│ --out                  <path>  Override the output file path (default:                           │
│                                .copilot/renders/WP-<id>.html).                                   │
│ --help                         Show this message and exit.                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc wp store`

```text
                                                                                                    
 Usage: tc wp store [OPTIONS]                                                                       
                                                                                                    
 Store a work product, using hybrid storage for large content.                                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --task           <int>   Associated task ID. [required]                                       │
│ *  --type           TYPE    Work product type. [required]                                        │
│ *  --title          <str>   Work product title. [required]                                       │
│    --content        <str>   Work product content.                                                │
│    --file           <path>  Read content from file.                                              │
│    --agent          <str>   Authoring agent.                                                     │
│    --json                   Output as JSON.                                                      │
│    --help                   Show this message and exit.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc wp get`

```text
                                                                                                    
 Usage: tc wp get [OPTIONS] {wp_id}                                                                 
                                                                                                    
 Get a work product by ID, reading file content if stored externally.                               
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    wp_id      <int>  Work product ID. [required]                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Output as JSON.                                                                  │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc wp list`

```text
                                                                                                    
 Usage: tc wp list [OPTIONS]                                                                        
                                                                                                    
 List work products with optional filters.                                                          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --task         <int>  Filter by task ID.                                                         │
│ --type         TYPE   Filter by type.                                                            │
│ --agent        <str>  Filter by agent.                                                           │
│ --json                Output as JSON.                                                            │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc wp search`

```text
                                                                                                    
 Usage: tc wp search [OPTIONS] {query}                                                              
                                                                                                    
 Search work products using FTS5 full-text search.                                                  
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    query      <str>  Full-text search query. [required]                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --limit        <int>  Maximum results to return. [default: 10]                                   │
│ --json                Output as JSON.                                                            │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc db`

```text
                                                                                                    
 Usage: tc db [OPTIONS] COMMAND [ARGS]...                                                           
                                                                                                    
 Database management commands.                                                                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ path   Print the path to the current database.                                                   │
│ stats  Show table row counts for the database.                                                   │
│ track  Make .gitignore commit the task database, history and work products (and ignore SQLite    │
│        side files).                                                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc db path`

```text
                                                                                                    
 Usage: tc db path [OPTIONS]                                                                        
                                                                                                    
 Print the path to the current database.                                                            
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc db stats`

```text
                                                                                                    
 Usage: tc db stats [OPTIONS]                                                                       
                                                                                                    
 Show table row counts for the database.                                                            
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Output as JSON.                                                                  │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc db track`

```text
                                                                                                    
 Usage: tc db track [OPTIONS]                                                                       
                                                                                                    
 Make .gitignore commit the task database, history and work products (and ignore SQLite side        
 files).                                                                                            
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --check          Exit 1 if .gitignore is not at the standard; change nothing.                    │
│ --help           Show this message and exit.                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc deploy`

```text
                                                                                                    
 Usage: tc deploy [OPTIONS] COMMAND [ARGS]...                                                       
                                                                                                    
 Deployment orchestration commands.                                                                 
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ wait  Trigger a Coolify deploy and wait for completion.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc deploy wait`

```text
                                                                                                    
 Usage: tc deploy wait [OPTIONS] {app_id}                                                           
                                                                                                    
 Trigger a Coolify deploy and wait for completion.                                                  
                                                                                                    
 Polls until the deploy finishes (success, failure, or timeout), then                               
 optionally runs a test command. Stores a deploy_report work product.                               
                                                                                                    
 Exit codes:                                                                                        
   0 — deploy succeeded (and test passed if --test was given)                                       
   1 — deploy failed                                                                                
   2 — deploy timed out                                                                             
   3 — test failed (deploy succeeded)                                                               
   4 — invalid config / missing dependency                                                          
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    app_id      <str>  Application UUID or tag to deploy. [required]                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --branch                           <str>  Branch to deploy (default: current git branch).        │
│ --timeout                          <int>  Max wait time in seconds (default: 600).               │
│                                           [default: 600]                                         │
│ --test                             <str>  Command to run after successful deploy (e.g.           │
│                                           Playwright spec).                                      │
│ --env                              <str>  Environment name (staging|production).                 │
│                                           [default: staging]                                     │
│ --json                                    Emit JSON to stdout.                                   │
│ --task-id                          <int>  Link deploy_report WP to this task.                    │
│ --force                                   Force rebuild.                                         │
│ --trigger          --no-trigger           Trigger deploy (default: true). [default: trigger]     │
│ --poll-interval                    <int>  Polling interval in seconds. [default: 5]              │
│ --dry-run                                 Exercise the flow without hitting Coolify.             │
│ --help                                    Show this message and exit.                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc history`

```text
                                                                                                    
 Usage: tc history [OPTIONS] COMMAND [ARGS]...                                                      
                                                                                                    
 Archived tasks (.copilot/tasks.db-history).                                                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ list     List archived tasks, newest first.                                                      │
│ search   Search archived tasks by title and work-product text.                                   │
│ get      Show an archived task with its activity log and work products.                          │
│ restore  Move archived tasks back into the live task list.                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc history list`

```text
                                                                                                    
 Usage: tc history list [OPTIONS]                                                                   
                                                                                                    
 List archived tasks, newest first.                                                                 
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --limit        <int>  Maximum rows. [default: 50]                                                │
│ --json                Output as JSON.                                                            │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc history search`

```text
                                                                                                    
 Usage: tc history search [OPTIONS] {query}                                                         
                                                                                                    
 Search archived tasks by title and work-product text.                                              
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    query      <str>  Words to match in titles and work products. [required]                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --limit        <int>  Maximum rows. [default: 50]                                                │
│ --json                Output as JSON.                                                            │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc history get`

```text
                                                                                                    
 Usage: tc history get [OPTIONS] {task_id}                                                          
                                                                                                    
 Show an archived task with its activity log and work products.                                     
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task_id      <int>  Task ID. [required]                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Output as JSON.                                                                  │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc history restore`

```text
                                                                                                    
 Usage: tc history restore [OPTIONS] {task_ids}...                                                  
                                                                                                    
 Move archived tasks back into the live task list.                                                  
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task_ids      <int>  Task IDs to move back into tasks.db. [required]                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Output as JSON.                                                                  │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc execution`

```text
                                                                                                    
 Usage: tc execution [OPTIONS] COMMAND [ARGS]...                                                    
                                                                                                    
 Persistent scope, experiment limits, evidence and handoff status.                                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ register        Freeze task scope. Policy v2 (no --attempts): no fixed attempt cap, stops on     │
│                 no progress, hard runaway ceiling, paid calls come from the project budget.      │
│                 With --attempts: legacy v1 caps (--authority required, may be repeated).         │
│ amend           Audit a contract correction; preserve all history, limits and failure stops.     │
│ reopen          Raise a runaway ceiling after an owner decision. Carries all history.            │
│ migrate         Append a policy-v2 round to v1 tasks and seed the project budget from their      │
│                 existing approvals. Idempotent; history, usage and QA identity are untouched.    │
│ succeed         Open a successor round. Caps are lifetime totals and can only rise; all          │
│                 usage and failures carry forward. Needs a new, verbatim owner --authority.       │
│ status          Observed execution state and exact authorizations; no guessed ETA.               │
│ begin           Begin a criterion-bound attempt and reserve its external-call allowance.         │
│ consume         Preflight one external call against a persistent reservation.                    │
│ settle          Record the attempt result, artifact, actual calls and cost.                      │
│ diagnose        Record a regression artifact at the selected criterion diagnosis checkpoint.     │
│ run             Run a check in replay mode (APP_ENV=test API_MODE=stub_strict, zero miss         │
│                 budget).                                                                         │
│                 --live reserves --calls/--usd from the project budget and allows paid calls.     │
│                 --usage-file consumes a machine-produced transport report.                       │
│ stub-miss-hint  Print the message a project adapter shows on a stub miss, with the real budget.  │
│ prove           Run a corrective regression in strict-stub mode without resetting live budgets.  │
│ budget          Per-project lifetime paid-call budget (append-only).                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc execution register`

```text
                                                                                                    
 Usage: tc execution register [OPTIONS] {task}                                                      
                                                                                                    
 Freeze task scope. Policy v2 (no --attempts): no fixed attempt cap, stops on no progress, hard     
 runaway ceiling, paid calls come from the project budget. With --attempts: legacy v1 caps          
 (--authority required, may be repeated).                                                           
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task      <int>  [required]                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --attempts                <int>    Legacy v1 fixed attempt cap. Omit for policy v2               │
│                                    (recommended).                                                │
│ --calls                   <int>    [default: 0]                                                  │
│ --usd                     <float>  [default: 0]                                                  │
│ --authority               <str>                                                                  │
│ --root                    <path>                                                                 │
│ --timeout                 <int>    [default: 900]                                                │
│ --stale                   <int>    [default: 300]                                                │
│ --no-progress-n           <int>                                                                  │
│ --ceiling-attempts        <int>                                                                  │
│ --ceiling-seconds         <int>                                                                  │
│ --help                             Show this message and exit.                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc execution amend`

```text
                                                                                                    
 Usage: tc execution amend [OPTIONS] {task}                                                         
                                                                                                    
 Audit a contract correction; preserve all history, limits and failure stops.                       
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task      <int>  [required]                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --file                            <path>  The complete owner-approved acceptance contract     │
│                                              JSON.                                               │
│                                              [required]                                          │
│ *  --expected-contract-sha256        <str>   Current limits.contract_sha256 from execution       │
│                                              status (not QA identity).                           │
│                                              [required]                                          │
│ *  --decision                        <str>   The verbatim owner decision approving this          │
│                                              amendment.                                          │
│                                              [required]                                          │
│    --help                                    Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc execution reopen`

```text
                                                                                                    
 Usage: tc execution reopen [OPTIONS] {task}                                                        
                                                                                                    
 Raise a runaway ceiling after an owner decision. Carries all history.                              
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task      <int>  [required]                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --decision                <str>  Pablo's recorded decision to continue. [required]            │
│    --ceiling-attempts        <int>                                                               │
│    --ceiling-seconds         <int>                                                               │
│    --help                           Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc execution migrate`

```text
                                                                                                    
 Usage: tc execution migrate [OPTIONS]                                                              
                                                                                                    
 Append a policy-v2 round to v1 tasks and seed the project budget from their existing approvals.    
 Idempotent; history, usage and QA identity are untouched.                                          
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --task                           <int>                                                           │
│ --dry-run                                                                                        │
│ --no-backup    --no-no-backup           [default: no-no-backup]                                  │
│ --help                                  Show this message and exit.                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc execution succeed`

```text
                                                                                                    
 Usage: tc execution succeed [OPTIONS] {task}                                                       
                                                                                                    
 Open a successor round. Caps are lifetime totals and can only rise; all usage and failures carry   
 forward. Needs a new, verbatim owner --authority.                                                  
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task      <int>  [required]                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --attempts         <int>    [required]                                                        │
│    --calls            <int>    [default: 0]                                                      │
│    --usd              <float>  [default: 0]                                                      │
│ *  --authority        <str>    [required]                                                        │
│    --timeout          <int>                                                                      │
│    --stale            <int>                                                                      │
│    --help                      Show this message and exit.                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc execution status`

```text
                                                                                                    
 Usage: tc execution status [OPTIONS] {task}                                                        
                                                                                                    
 Observed execution state and exact authorizations; no guessed ETA.                                 
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task      <int>  [required]                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc execution begin`

```text
                                                                                                    
 Usage: tc execution begin [OPTIONS] {task}                                                         
                                                                                                    
 Begin a criterion-bound attempt and reserve its external-call allowance.                           
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task      <int>  [required]                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --criterion        <str>    [required]                                                        │
│ *  --label            <str>    [required]                                                        │
│    --calls            <int>    [default: 0]                                                      │
│    --usd              <float>  [default: 0]                                                      │
│    --help                      Show this message and exit.                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc execution consume`

```text
                                                                                                    
 Usage: tc execution consume [OPTIONS] {token}                                                      
                                                                                                    
 Preflight one external call against a persistent reservation.                                      
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    token      <str>  [required]                                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc execution settle`

```text
                                                                                                    
 Usage: tc execution settle [OPTIONS] {token}                                                       
                                                                                                    
 Record the attempt result, artifact, actual calls and cost.                                        
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    token      <str>  [required]                                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --artifact                       <path>   [required]                                          │
│    --succeeded    --no-succeeded             [default: no-succeeded]                             │
│    --calls                          <int>                                                        │
│    --usd                            <float>                                                      │
│    --reason                         <str>                                                        │
│    --help                                    Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc execution diagnose`

```text
                                                                                                    
 Usage: tc execution diagnose [OPTIONS] {task}                                                      
                                                                                                    
 Record a regression artifact at the selected criterion diagnosis checkpoint.                       
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task      <int>  [required]                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --criterion         <str>   [required]                                                        │
│ *  --regression        <path>  [required]                                                        │
│    --help                      Show this message and exit.                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc execution run`

```text
                                                                                                    
 Usage: tc execution run [OPTIONS] {task}                                                           
                                                                                                    
 Run a check in replay mode (APP_ENV=test API_MODE=stub_strict, zero miss budget). --live reserves  
 --calls/--usd from the project budget and allows paid calls. --usage-file consumes a               
 machine-produced transport report.                                                                 
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task      <int>  [required]                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --criterion         <str>    [required]                                                       │
│    --label             <str>    [default: verification]                                          │
│    --calls             <int>    [default: 0]                                                     │
│    --usd               <float>  [default: 0]                                                     │
│    --usage-file        <path>                                                                    │
│    --live                       The only way to make a paid call; needs --calls and --usd (>0).  │
│    --help                       Show this message and exit.                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc execution stub-miss-hint`

```text
                                                                                                    
 Usage: tc execution stub-miss-hint [OPTIONS]                                                       
                                                                                                    
 Print the message a project adapter shows on a stub miss, with the real budget.                    
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --provider        <str>  provider:model, e.g. openrouter:anthropic/claude-sonnet-5-5          │
│                             [required]                                                           │
│ *  --hash            <str>  Prompt hash that has no recording. [required]                        │
│ *  --test            <str>  Test id to record. [required]                                        │
│    --adapter         <str>  Project test adapter command. [default: scripts/test.sh]             │
│    --help                   Show this message and exit.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc execution prove`

```text
                                                                                                    
 Usage: tc execution prove [OPTIONS] {task}                                                         
                                                                                                    
 Run a corrective regression in strict-stub mode without resetting live budgets.                    
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task      <int>  [required]                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --criterion        <str>  [required]                                                          │
│    --help                    Show this message and exit.                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc execution budget`

```text
                                                                                                    
 Usage: tc execution budget [OPTIONS] COMMAND [ARGS]...                                             
                                                                                                    
 Per-project lifetime paid-call budget (append-only).                                               
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ show  Budget, lifetime spend and remaining for this project (one task database;                  │
│       linked worktrees share their main checkout's).                                             │
│ set   Append a budget round with lifetime totals. Needs a new verbatim owner quote.              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc execution budget show`

```text
                                                                                                    
 Usage: tc execution budget show [OPTIONS]                                                          
                                                                                                    
 Budget, lifetime spend and remaining for this project (one task database; linked worktrees share   
 their main checkout's).                                                                            
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json    --no-json      Always JSON. [default: json]                                            │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc execution budget set`

```text
                                                                                                    
 Usage: tc execution budget set [OPTIONS]                                                           
                                                                                                    
 Append a budget round with lifetime totals. Needs a new verbatim owner quote.                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --calls            <int>    [required]                                                        │
│ *  --usd              <float>  [required]                                                        │
│ *  --authority        <str>    [required]                                                        │
│    --help                      Show this message and exit.                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc repo`

```text
                                                                                                    
 Usage: tc repo [OPTIONS] COMMAND [ARGS]...                                                         
                                                                                                    
 Registered repositories for contract externalSources (id -> checkout and origin).                  
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ add   Register or repoint a repo id. Repointing requires the same origin URL.                    │
│ list  List registered repositories.                                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc repo add`

```text
                                                                                                    
 Usage: tc repo add [OPTIONS] {ID}                                                                  
                                                                                                    
 Register or repoint a repo id. Repointing requires the same origin URL.                            
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    ID      <str>  [required]                                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --path        <path>  Top level of the git work tree; must have an origin remote. [required]  │
│    --json                                                                                        │
│    --help                Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc repo list`

```text
                                                                                                    
 Usage: tc repo list [OPTIONS]                                                                      
                                                                                                    
 List registered repositories.                                                                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                           │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc tests`

```text
                                                                                                    
 Usage: tc tests [OPTIONS] COMMAND [ARGS]...                                                        
                                                                                                    
 Per-project test selection.                                                                        
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ map  Change-to-test map (.copilot/test-map.json).                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc tests map`

```text
                                                                                                    
 Usage: tc tests map [OPTIONS] COMMAND [ARGS]...                                                    
                                                                                                    
 Change-to-test map (.copilot/test-map.json).                                                       
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ show    Show the map.                                                                            │
│ set     Add or replace a map entry.                                                              │
│ remove  Remove a map entry.                                                                      │
│ select  Pick focused/affected commands, lane and cap for changed paths.                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc tests map show`

```text
                                                                                                    
 Usage: tc tests map show [OPTIONS]                                                                 
                                                                                                    
 Show the map.                                                                                      
                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                           │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc tests map set`

```text
                                                                                                    
 Usage: tc tests map set [OPTIONS] {glob}                                                           
                                                                                                    
 Add or replace a map entry.                                                                        
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    glob      <str>  Source glob, or 'release' with --broad. [required]                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --focused            <str>                                                                       │
│ --affected           <str>                                                                       │
│ --lane               <str>  focused, affected (default) or broad.                                │
│ --cap-seconds        <int>                                                                       │
│ --broad              <str>  Only for 'release': the full-suite command.                          │
│ --help                      Show this message and exit.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc tests map remove`

```text
                                                                                                    
 Usage: tc tests map remove [OPTIONS] {glob}                                                        
                                                                                                    
 Remove a map entry.                                                                                
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    glob      <str>  [required]                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `tc tests map select`

```text
                                                                                                    
 Usage: tc tests map select [OPTIONS] [paths]...                                                    
                                                                                                    
 Pick focused/affected commands, lane and cap for changed paths.                                    
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   paths      <str>  Changed paths.                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --diff               Use git diff --name-only in the project root.                               │
│ --base        <str>  With --diff: compare against this ref (default HEAD).                       │
│ --json                                                                                           │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

