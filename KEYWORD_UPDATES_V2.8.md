# Magic Keywords Documentation Updates - v2.8.0

## Summary

Updated all protocol command and magic keyword documentation to reflect the modernized Ecomode model router that separates model selection from reasoning effort levels.

## Breaking Changes

### `fast:` Keyword Behavior Change

**Before (v2.7):**
- `fast:` forced Haiku model
- Used for speed priority tasks

**After (v2.8):**
- `fast:` sets medium effort level
- Auto-selects model based on complexity
- No longer forces Haiku

**Migration:**
```bash
# To force Haiku model (old fast: behavior)
/protocol haiku: fix bug

# For low effort + cost optimization
/protocol eco: quick task

# For balanced reasoning (new fast: behavior)
/protocol fast: standard work
```

## New Features

### `max:` Keyword

New keyword for maximum reasoning depth:
- Auto-selects model based on complexity
- Sets effort level to "max" for deepest reasoning
- Use for architecture design, complex optimization, security analysis

**Example:**
```bash
/protocol max: design authentication architecture
```

## Keyword Semantics

### Effort-Level Keywords (Auto-Select Model)

| Keyword | Effort | Description |
|---------|--------|-------------|
| `eco:` | low | Minimal reasoning, fast response, cost-optimized |
| `fast:` | medium | Balanced reasoning (BREAKING: was haiku model) |
| `max:` | max | Maximum reasoning depth (NEW) |
| `auto:` | (complexity-based) | Auto-select model and effort |
| `ralph:` | (complexity-based) | Auto-select model and effort |

### Model-Selection Keywords (Force Specific Model)

| Keyword | Model | Description |
|---------|-------|-------------|
| `opus:` | Opus | Force Opus, effort from task complexity |
| `sonnet:` | Sonnet | Force Sonnet, effort from task complexity |
| `haiku:` | Haiku | Force Haiku, effort from task complexity |

## Effort Level Mapping

Effort levels control reasoning depth independently of model selection:

| Effort | Complexity Score | Description |
|--------|-----------------|-------------|
| low | < 0.3 | Trivial tasks, quick responses |
| medium | Reserved for explicit overrides | Future use |
| high | 0.3-0.7 | Standard tasks, default reasoning |
| max | > 0.7 | Complex architecture/design |

## Files Updated

### Documentation Files

1. **docs/50-features/magic-keywords.md**
   - Updated modifier keywords table with effort levels
   - Added breaking change warnings
   - Updated all examples to show new semantics
   - Added migration guide section
   - Updated decision guide and quick reference

2. **docs/50-features/ecomode.md**
   - Updated modifier keywords table
   - Added breaking change notices
   - Updated routing examples with effort levels

3. **docs/70-reference/01-usage-guide.md**
   - Updated model selection table
   - Updated workflow cheat sheet

4. **docs/30-operations/03-agent-guide.md**
   - Updated complexity scoring section
   - Replaced magic keywords table with effort vs model split
   - Updated examples with breaking change notices
   - Updated best practices and cost optimization strategies

5. **CLAUDE_REFERENCE.md**
   - Updated Ecomode usage examples
   - Added breaking change notices
   - Updated modifier keyword combinations

### Command Files

6. **.claude/commands/protocol.md**
   - Updated modifier keywords section with effort/model split
   - Updated keyword examples
   - Added effort level display to keyword detection output
   - Updated all flow examples with new keyword semantics

7. **.claude/commands/config.md**
   - Updated keyword lists to include `max:`
   - Updated examples to reflect new semantics

## Key Concepts Documented

### Separation of Concerns

**Model Selection:**
- Determined by complexity scoring OR explicit keyword
- Controls which Claude model (haiku/sonnet/opus) executes the task

**Effort Level:**
- Determined by complexity scoring OR explicit keyword
- Controls reasoning depth (low/medium/high/max)
- Independent of model selection

### Example Combinations

```bash
# Low effort, auto-select model
/protocol eco: fix typo
→ Model: haiku (from complexity)
→ Effort: low (from eco: keyword)

# Medium effort, auto-select model
/protocol fast: refactor module
→ Model: sonnet (from complexity)
→ Effort: medium (from fast: keyword)

# Max effort, auto-select model
/protocol max: design architecture
→ Model: opus (from complexity)
→ Effort: max (from max: keyword)

# Force model, effort from complexity
/protocol opus: simple task
→ Model: opus (from opus: keyword - forced)
→ Effort: low (from complexity score)
```

## User Communication

### Breaking Change Notice

All updated documentation includes:
- ⚠️ BREAKING markers on `fast:` keyword changes
- ✨ NEW markers on `max:` keyword
- Clear migration guidance
- Before/after comparison tables

### Migration Guidance

Users upgrading from v2.7 should:

1. Review usages of `fast:` keyword
2. Replace with `haiku:` if model forcing was intended
3. Replace with `eco:` if low effort was intended
4. Keep `fast:` if medium effort is appropriate
5. Consider new `max:` keyword for complex tasks

## Implementation Reference

The implementation in `/Volumes/Dev/Sites/COPILOT/claude-copilot/mcp-servers/task-copilot/src/ecomode/model-router.ts` shows:

- Effort-level keywords set `effortLevel` field
- Model-selection keywords set `targetModel` field
- Complexity scoring determines defaults for both
- Keywords can override either independently

## Testing Recommendations

When testing keyword changes:

1. Verify `eco:` produces low effort
2. Verify `fast:` produces medium effort (NOT haiku model)
3. Verify `max:` produces max effort
4. Verify model keywords (opus:, sonnet:, haiku:) force models
5. Verify effort levels display correctly in keyword detection output
6. Test combinations (e.g., no keywords = auto for both)

## Related Files

- Implementation: `mcp-servers/task-copilot/src/ecomode/model-router.ts`
- Types: `mcp-servers/task-copilot/src/types/omc-features.ts`
- Parser: `.claude/commands/keyword-parser.ts`
