# Configuration Dashboard

Display and manage Claude Copilot configuration settings, including ecomode thresholds, cost tracking preferences, and other framework settings.

## Step 1: Detect Intent

Parse user input to determine action:

| Pattern | Action |
|---------|--------|
| `/config` (no args) | Show current configuration |
| `/config ecomode enable` | Enable ecomode |
| `/config ecomode disable` | Disable ecomode |
| `/config ecomode thresholds` | Show/update thresholds |
| `/config ecomode cost` | Show cost tracking settings |
| `/config reset` | Reset to defaults |

## Step 2: Load Current Configuration

Configuration is stored in Memory Copilot metadata. Use these tools:

1. **Get ecomode configuration from memory:**
   ```
   memory_list({ tags: ['ecomode_config'], limit: 1 })
   ```

2. **If no config exists, use defaults:**
   - enabled: false (ecomode off by default)
   - thresholds.low: 0.3 (haiku below 0.3)
   - thresholds.medium: 0.7 (sonnet below 0.7)
   - cost.displayInMemory: true (show in /memory)
   - cost.trackUsage: true (track model usage)

## Step 3: Display Configuration

### Show Current Configuration

Format as clean dashboard:

```
## Claude Copilot Configuration

### Ecomode

**Status:** [Enabled / Disabled]

**Model Routing Thresholds:**
- Low complexity (haiku): < 0.3 (default: 0.3)
- Medium complexity (sonnet): < 0.7 (default: 0.7)
- High complexity (opus): >= 0.7

**Cost Tracking:**
- Display in /memory: [Yes / No]
- Track usage: [Yes / No]

**How it works:**
- Tasks are scored 0.0-1.0 based on complexity (keywords, file count, agent type)
- Scores below 0.3 → haiku (fast, low cost)
- Scores 0.3-0.7 → sonnet (balanced)
- Scores 0.7+ → opus (complex work)
- Override anytime with keywords: `eco:`, `fast:`, `max:`, `opus:`, `sonnet:`, `haiku:`

**Current Session Cost Summary:**
[If ecomode enabled and cost tracking active, call cost_get_summary({ format: 'compact' })]
[Otherwise: "No cost data yet (ecomode disabled or no usage tracked)"]

### Configuration File

Configuration is stored in Memory Copilot at:
- Location: ~/.claude/memory/[workspace-id]/memory.db
- Tags: ecomode_config
- Type: context

To modify settings, use `/config ecomode [command]`
```

## Step 4: Handle Configuration Commands

### Enable Ecomode

```
/config ecomode enable
```

Actions:
1. Update or create ecomode config memory:
   ```
   memory_store({
     content: 'Ecomode configuration: enabled=true, thresholds={low: 0.3, medium: 0.7}, cost={displayInMemory: true, trackUsage: true}',
     type: 'context',
     tags: ['ecomode_config'],
     metadata: {
       enabled: true,
       thresholds: { low: 0.3, medium: 0.7 },
       cost: { displayInMemory: true, trackUsage: true }
     }
   })
   ```

2. Show confirmation:
   ```
   Ecomode enabled!

   - Tasks will be automatically routed to haiku/sonnet/opus based on complexity
   - Cost tracking is active
   - Override anytime with keywords: eco:, fast:, max:, opus:, sonnet:, haiku:

   Run `/config` to see current settings.
   ```

### Disable Ecomode

```
/config ecomode disable
```

Actions:
1. Update config memory (set enabled: false)
2. Show confirmation:
   ```
   Ecomode disabled.

   All tasks will use the default model (sonnet) unless explicitly overridden.
   Cost tracking data is preserved but no new usage will be tracked.

   Run `/config ecomode enable` to re-enable.
   ```

### Update Thresholds

```
/config ecomode thresholds low=0.4 medium=0.8
```

Actions:
1. Parse threshold values from input
2. Validate: 0.0 <= low < medium <= 1.0
3. Update config memory with new thresholds
4. Show confirmation:
   ```
   Thresholds updated:
   - Low complexity (haiku): < 0.4 (was: 0.3)
   - Medium complexity (sonnet): < 0.8 (was: 0.7)
   - High complexity (opus): >= 0.8

   These changes apply to all future task routing.
   ```

### Show Cost Tracking Settings

```
/config ecomode cost
```

Actions:
1. Call cost_get_summary({ format: 'full' })
2. Display full cost breakdown (if ecomode enabled)
3. Show settings:
   ```
   ### Cost Tracking Settings

   - **Display in /memory:** Yes
   - **Track usage:** Yes
   - **Current session:** [summary from cost_get_summary]

   To disable cost tracking:
   /config ecomode cost disable

   To hide from /memory (but keep tracking):
   /config ecomode cost hide
   ```

### Reset to Defaults

```
/config reset
```

Actions:
1. Delete existing config memory (if exists)
2. Create new config with defaults
3. Show confirmation:
   ```
   Configuration reset to defaults:
   - Ecomode: Disabled
   - Thresholds: low=0.3, medium=0.7
   - Cost tracking: Enabled, displayed in /memory
   ```

## Step 5: Validation

### Threshold Validation

Before updating thresholds:
- Ensure `0.0 <= low < medium <= 1.0`
- If invalid, show error:
  ```
  Invalid thresholds: low must be less than medium, and both must be between 0.0 and 1.0.
  Example: /config ecomode thresholds low=0.3 medium=0.7
  ```

### Config Storage

- Always store config in Memory Copilot with tag `ecomode_config`
- Use type `context` (not `decision` or `lesson`)
- Include full metadata object for easy retrieval
- Only keep the most recent config (delete old ones before storing new)

## Step 6: Integration with /memory Command

When `/memory` is called, if ecomode config exists with `cost.displayInMemory: true`:

1. Call cost_get_summary({ format: 'compact' })
2. Add to memory dashboard output:
   ```
   ### Ecomode Cost Summary
   [Output from cost_get_summary compact format]

   Run `/config ecomode cost` for detailed breakdown.
   ```

## Examples

### Example 1: First time setup

User: `/config ecomode enable`

Output:
```
Ecomode enabled!

Configuration:
- Low complexity (< 0.3): haiku
- Medium complexity (0.3-0.7): sonnet
- High complexity (>= 0.7): opus

Cost tracking is active. View savings with `/memory` or `/config ecomode cost`.

Override model selection and effort anytime with keywords:
- `eco: fix the bug` → auto-route by complexity, low effort
- `fast: implement feature` → auto-route by complexity, medium effort
- `max: design architecture` → auto-route by complexity, max effort
- `opus: anything` → force opus model
- `haiku: simple task` → force haiku model
```

### Example 2: Update thresholds

User: `/config ecomode thresholds low=0.4 medium=0.8`

Output:
```
Thresholds updated successfully.

New routing:
- Low complexity (< 0.4): haiku (was: < 0.3)
- Medium complexity (0.4-0.8): sonnet (was: 0.3-0.7)
- High complexity (>= 0.8): opus (was: >= 0.7)

This will route fewer tasks to haiku and more to sonnet/opus.
```

### Example 3: View current config

User: `/config`

Output:
```
## Claude Copilot Configuration

### Ecomode

**Status:** Enabled

**Model Routing Thresholds:**
- Low complexity (haiku): < 0.3
- Medium complexity (sonnet): < 0.7
- High complexity (opus): >= 0.7

**Cost Tracking:**
- Display in /memory: Yes
- Track usage: Yes

**Current Session:**
Ecomode: 12 calls (haiku=7, sonnet=4, opus=1) | Cost: $0.0342 (saved $0.1876 vs Opus = 84.6%)

### How to Modify

- Enable/disable: `/config ecomode enable` or `/config ecomode disable`
- Update thresholds: `/config ecomode thresholds low=0.3 medium=0.7`
- View cost details: `/config ecomode cost`
- Reset to defaults: `/config reset`
```

## Error Handling

### No Active Ecomode

If ecomode is disabled and user tries to view cost:
```
Ecomode is currently disabled.

No cost tracking data available.
Run `/config ecomode enable` to activate ecomode and cost tracking.
```

### Invalid Threshold Values

If user provides invalid values:
```
Error: Invalid threshold values.

Requirements:
- Both values must be between 0.0 and 1.0
- low must be less than medium
- Example: /config ecomode thresholds low=0.3 medium=0.7

Current thresholds unchanged.
```

### No Cost Data

If ecomode enabled but no usage tracked yet:
```
### Cost Tracking

Ecomode is enabled but no usage has been tracked yet.

Cost tracking will begin automatically as tasks are processed.
Check back with `/memory` or `/config ecomode cost` after some work.
```

## Notes

- Configuration is workspace-specific (stored per project)
- Thresholds can be customized per team/project
- Cost tracking uses Memory Copilot tools (cost_track_usage, cost_get_summary)
- Modifier keywords always override ecomode routing
- Default is ecomode disabled to maintain backward compatibility
- Cost estimates are based on current Claude pricing (Jan 2025)

## End

After displaying configuration, ask:

"Would you like to enable ecomode, adjust thresholds, or view cost tracking details?"
