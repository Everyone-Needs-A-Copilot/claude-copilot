# Magic Keywords

Magic keywords provide shortcuts for model selection and task routing in the `/protocol` command.

## Overview

Magic keywords are special prefixes you add to your `/protocol` commands to control:

1. **Model selection** (modifier keywords) - Which Claude model to use
2. **Task routing** (action keywords) - Which agent flow to activate

**Syntax:**
```
/protocol [modifier:] [action:] description
```

**Benefits:**
- Faster command entry (no need for flags)
- Explicit model control when needed
- Direct routing to specific flows
- Cost optimization through model selection

---

## Modifier Keywords

Modifier keywords control model selection and reasoning effort level.

### Model Selection vs Effort Level

**BREAKING CHANGE (v2.8.0):** Keywords now separate model selection from effort level:

| Keyword | Selects Model? | Sets Effort | Description |
|---------|----------------|-------------|-------------|
| `eco:` | No (auto-select) | **low** | Cost optimization with minimal effort |
| `fast:` | No (auto-select) | **medium** | ⚠️ CHANGED: Was haiku, now medium effort auto-select |
| `max:` | No (auto-select) | **max** | NEW: Maximum reasoning depth |
| `opus:` | Yes → Opus | (complexity-based) | Force Opus model |
| `sonnet:` | Yes → Sonnet | (complexity-based) | Force Sonnet model |
| `haiku:` | Yes → Haiku | (complexity-based) | Force Haiku model |
| `auto:` | No (auto-select) | (complexity-based) | Automatic selection |
| `ralph:` | No (auto-select) | (complexity-based) | Automatic selection |

### How It Works

**Effort-level keywords** (`eco:`, `fast:`, `max:`):
- Let complexity scoring choose the best model (haiku/sonnet/opus)
- Override the reasoning effort level for that model
- Example: `eco: fix bug` → might select sonnet, but use low effort

**Model-selection keywords** (`opus:`, `sonnet:`, `haiku:`):
- Force a specific model regardless of complexity
- Effort level determined by task complexity
- Example: `opus: fix bug` → opus model with medium effort (based on complexity)

**Rules:**
- Maximum 1 modifier keyword per command
- Must be at the start of the message
- Case-insensitive (`eco:` = `ECO:` = `Eco:`)
- Must be followed by space or colon only (prevents false positives like "economics:")

### Examples

**Cost-optimized with low effort:**
```
/protocol eco: fix the login bug
→ Auto-selects model by complexity (likely sonnet)
→ Uses low effort (fast, minimal reasoning)
```

**Medium effort, auto-select model:**
```
/protocol fast: refactor the auth module
→ Auto-selects model by complexity (likely sonnet)
→ Uses medium effort (balanced reasoning)
⚠️ BREAKING: Previously forced Haiku model
```

**Maximum reasoning depth:**
```
/protocol max: design the new checkout flow
→ Auto-selects model by complexity (likely opus)
→ Uses max effort (deepest reasoning)
```

**Force specific model:**
```
/protocol opus: add console logging
→ Forces Opus model (ignores low complexity)
→ Effort level based on task complexity
```

**Balanced approach:**
```
/protocol sonnet: refactor the API layer
→ Forces Sonnet model
→ Effort level based on task complexity
```

---

## Action Keywords

Action keywords route your task to specific agent flows.

| Keyword | Agent Flow | Agent Chain | Use When |
|---------|-----------|-------------|----------|
| `fix:` | Defect | qa → me → qa | Fixing bugs, errors, broken features |
| `add:` | Experience | sd → uxd → uids → ta → me | Adding new features, UI, functionality |
| `refactor:` | Technical | ta → me | Restructuring code, improving architecture |
| `optimize:` | Technical | ta → me | Performance improvements, efficiency |
| `test:` | QA | qa | Writing tests, test coverage |
| `doc:` | Documentation | doc | Writing documentation, API docs |
| `deploy:` | DevOps | do | Deployment, CI/CD, infrastructure |

**Rules:**
- Maximum 1 action keyword per command
- Can be combined with modifier keywords
- Overrides standard intent detection
- Case-insensitive

### Examples

**Fix bugs:**
```
/protocol fix: login authentication not working
→ Routes to Defect Flow: qa → me → qa
```

**Add features:**
```
/protocol add: dark mode toggle to settings
→ Routes to Experience Flow: sd → uxd → uids → ta → me
```

**Refactor code:**
```
/protocol refactor: auth module to use new patterns
→ Routes to Technical Flow: ta → me
```

**Optimize performance:**
```
/protocol optimize: database queries in user service
→ Routes to Technical Flow: ta → me
```

**Write tests:**
```
/protocol test: add unit tests for auth module
→ Routes directly to @agent-qa
```

**Write documentation:**
```
/protocol doc: API endpoints for user service
→ Routes directly to @agent-doc
```

**Deploy/infrastructure:**
```
/protocol deploy: set up staging environment
→ Routes directly to @agent-do
```

---

## Hybrid Usage

Combine modifier and action keywords for precise control.

### Format

```
/protocol [modifier:] [action:] description
```

**Order matters:** Modifier must come before action.

### Examples

**Cost-optimized bug fix:**
```
/protocol eco: fix: the login bug

[KEYWORDS DETECTED]
Model: eco → auto-select
Effort: low
Action: fix → Defect Flow

[PROTOCOL: DEFECT | Agent: @agent-qa | Action: INVOKING]
Routing to defect flow: qa → me → qa
Model selection: Auto-select based on complexity (sonnet likely)
Effort level: low (minimal reasoning, fast response)
```

**High-quality feature with design:**
```
/protocol opus: add: user profile customization

[KEYWORDS DETECTED]
Model: opus → opus (forced)
Effort: (complexity-based)
Action: add → Experience Flow

[PROTOCOL: EXPERIENCE | Agent: @agent-sd | Action: INVOKING]
Routing to experience-first flow: sd → uxd → uids → ta → me
Model selection: Claude Opus (forced override)
Effort level: high (complex feature, standard reasoning)
```

**Medium effort refactoring:**
```
/protocol fast: refactor: simplify auth logic

[KEYWORDS DETECTED]
Model: fast → auto-select
Effort: medium
Action: refactor → Technical Flow

[PROTOCOL: TECHNICAL | Agent: @agent-ta | Action: INVOKING]
Routing to technical-only flow: ta → me
Model selection: Auto-select based on complexity (sonnet likely)
Effort level: medium (balanced reasoning)
⚠️ BREAKING: Previously forced Haiku model
```

**Maximum reasoning depth:**
```
/protocol max: optimize: API response times

[KEYWORDS DETECTED]
Model: max → auto-select
Effort: max
Action: optimize → Technical Flow

[PROTOCOL: TECHNICAL | Agent: @agent-ta | Action: INVOKING]
Routing to technical-only flow: ta → me
Model selection: Auto-select based on complexity (opus likely for optimization)
Effort level: max (deepest reasoning, thorough analysis)
```

---

## Validation

The keyword parser validates your input and shows errors if you use invalid combinations.

### Invalid Combinations

**Multiple modifiers:**
```
/protocol eco: opus: fix the bug
❌ Invalid keyword combination:
Multiple modifiers detected: eco:, opus:. Use only one.
```

**Conflicting modifiers:**
```
/protocol fast: sonnet: add feature
❌ Invalid keyword combination:
Conflicting modifiers: fast: and sonnet: cannot be used together
```

### Valid Examples

**Single modifier only:**
```
✅ /protocol eco: the login bug
✅ /protocol opus: design the checkout flow
```

**Single action only:**
```
✅ /protocol fix: the login bug
✅ /protocol add: dark mode feature
```

**Both modifier and action:**
```
✅ /protocol eco: fix: the login bug
✅ /protocol opus: add: user profiles
```

**Neither (standard detection):**
```
✅ /protocol fix login authentication bug
✅ /protocol add dark mode to dashboard
```

---

## False Positive Protection

The parser only matches exact keywords at the start of the message to prevent false positives.

### What's NOT a Keyword

**Keyword in the middle of a word:**
```
/protocol fix economics database issue
→ No keyword detected (economics: is not eco:)
→ Standard intent detection applies
```

**Keyword in the middle of the message:**
```
/protocol the app needs to add: dark mode
→ No keyword detected (add: is not at start)
→ Standard intent detection applies
```

**Keyword without colon:**
```
/protocol fix the eco system
→ No keyword detected (eco needs colon)
→ Standard intent detection applies
```

### What IS a Keyword

**Exact match at start:**
```
✅ /protocol eco: fix the bug
✅ /protocol ECO: fix the bug (case-insensitive)
✅ /protocol eco:fix the bug (no space needed after colon)
```

**After another keyword:**
```
✅ /protocol eco: fix: the bug (modifier then action)
```

---

## Decision Guide

### When to Use Modifier Keywords

| Situation | Use | Why |
|-----------|-----|-----|
| Quick tasks, minimal thinking | `eco:` | Low effort, fast response, save cost |
| Balanced reasoning | `fast:` | Medium effort, good for most tasks |
| Complex reasoning needed | `max:` | Maximum reasoning depth |
| Force specific model | `opus:`, `sonnet:`, `haiku:` | Override auto-selection |
| Unsure | Omit or `auto:` | Let complexity scoring decide everything |

### Effort Levels Explained

| Effort | When to Use | Example Tasks |
|--------|-------------|---------------|
| **low** (`eco:`) | Simple, obvious tasks | Typo fixes, minor updates, simple bug fixes |
| **medium** (`fast:`) | Standard development work | Feature implementation, refactoring, most bugs |
| **high** (default) | Complex tasks | Architecture decisions, complex features |
| **max** (`max:`) | Maximum reasoning needed | System design, critical optimizations, security

### When to Use Action Keywords

| Situation | Use | Why |
|-----------|-----|-----|
| Clear intent | Use action keyword | Direct routing, faster |
| Ambiguous intent | Omit | Let system clarify |
| Experience work | `add:` | Skip to experience flow |
| Bug fix | `fix:` | Direct to defect flow |
| Refactoring | `refactor:` | Skip to technical flow |

### Comparison with Flags

| Feature | Magic Keywords | Explicit Flags |
|---------|---------------|----------------|
| Model selection | `eco:`, `opus:`, `fast:` | N/A (not available as flags) |
| Flow override | `fix:`, `add:`, `refactor:` | `--defect`, `--experience`, `--technical` |
| Typing speed | Faster (5-10 chars) | Slower (15-20 chars) |
| Clarity | Implicit | Explicit |
| Skip stages | Not available | `--skip-sd`, `--skip-uxd`, etc. |

**Recommendation:** Use magic keywords for quick commands. Use flags for advanced control (skip stages, checkpoint control, etc.).

---

## Quick Reference

### All Modifier Keywords

**Effort-level keywords** (auto-select model):
```
eco:     → effort: low (minimal reasoning)
fast:    → effort: medium (balanced) ⚠️ BREAKING: was haiku model
max:     → effort: max (deepest reasoning) ✨ NEW
auto:    → effort: (complexity-based)
ralph:   → effort: (complexity-based)
```

**Model-selection keywords** (force model):
```
opus:    → Claude Opus (effort based on complexity)
sonnet:  → Claude Sonnet (effort based on complexity)
haiku:   → Claude Haiku (effort based on complexity)
```

### All Action Keywords

```
fix:      → Defect Flow (qa → me → qa)
add:      → Experience Flow (sd → uxd → uids → ta → me)
refactor: → Technical Flow (ta → me)
optimize: → Technical Flow (ta → me)
test:     → QA Testing (@agent-qa)
doc:      → Documentation (@agent-doc)
deploy:   → DevOps (@agent-do)
```

### Common Patterns

```bash
# Low effort bug fix (minimal reasoning)
/protocol eco: fix: login authentication error

# Maximum reasoning for architecture
/protocol max: add: user voice recording system

# Medium effort refactoring (BREAKING: was haiku model)
/protocol fast: refactor: simplify auth logic

# Force sonnet model for optimization
/protocol sonnet: optimize: database queries

# Medium effort test writing
/protocol fast: test: auth module coverage

# Low effort documentation
/protocol eco: doc: API endpoints for users

# Deployment work (auto-select)
/protocol deploy: staging environment setup
```

---

## Implementation Notes

### Parser Location

The keyword parser is implemented in `.claude/commands/keyword-parser.ts`.

### Integration

The `/protocol` command imports and uses the parser:

```typescript
import { parseKeywords } from './keyword-parser';

const parsed = parseKeywords(userMessage);

if (!parsed.valid) {
  return parsed.errors; // Show validation errors
}

const modelPreference = parsed.modifier?.targetModel;
const actionKeyword = parsed.action?.keyword;
const cleanMessage = parsed.cleanMessage;

// Route based on parsed information
```

### Type Definitions

Types are defined in `types/omc-features.ts`:

```typescript
interface ModifierKeyword {
  keyword: 'eco' | 'fast' | 'max' | 'opus' | 'sonnet' | 'haiku' | 'auto' | 'ralph';
  position: number;
  raw: string;
  targetModel: 'haiku' | 'sonnet' | 'opus' | null;
  effortLevel: 'low' | 'medium' | 'high' | 'max' | null;
}

interface ActionKeyword {
  keyword: 'fix' | 'add' | 'refactor' | 'optimize' | 'test' | 'doc' | 'deploy';
  position: number;
  raw: string;
  suggestedAgent?: string;
}

interface ParsedCommand {
  originalMessage: string;
  cleanMessage: string;
  modifier: ModifierKeyword | null;
  action: ActionKeyword | null;
  errors: string[];
  valid: boolean;
}
```

---

## Migration Guide (v2.7 → v2.8)

### Breaking Change: `fast:` Keyword

**What Changed:**
- **v2.7 and earlier:** `fast:` forced Haiku model
- **v2.8 and later:** `fast:` sets medium effort level, auto-selects model

**Migration:**

| Old Usage | New Equivalent | Notes |
|-----------|---------------|-------|
| `fast: fix bug` | `haiku: fix bug` | To keep Haiku model |
| `fast: quick task` | `eco: quick task` | For low effort + cost optimization |
| `fast: standard work` | `fast: standard work` | OK as-is (medium effort appropriate) |

**Why This Change:**
- Separates model selection from reasoning depth
- `fast:` now means "medium effort" (balanced reasoning)
- More consistent with `eco:` (low effort) and `max:` (high effort)
- Model selection should be based on complexity, not speed preference

**Recommended Migration:**

```bash
# If you used fast: for quick tasks
# OLD: /protocol fast: fix typo
# NEW: /protocol eco: fix typo

# If you specifically want Haiku model
# OLD: /protocol fast: anything
# NEW: /protocol haiku: anything

# If you want balanced reasoning (new behavior)
# OLD: (no equivalent)
# NEW: /protocol fast: standard task
```

### New: `max:` Keyword

**Purpose:** Maximum reasoning depth for complex tasks

**Use Cases:**
- Architecture design
- System optimization
- Security analysis
- Complex debugging

**Example:**
```bash
/protocol max: design authentication architecture
→ Auto-selects model (likely opus for high complexity)
→ Uses maximum reasoning depth
```

---

## Related Documentation

- [Protocol Command](../../.claude/commands/protocol.md) - Main protocol documentation
- [Ecomode](../50-features/ecomode.md) - Auto-select model routing details
- [Agent Routing](../10-architecture/02-agent-routing.md) - Agent flow details

---

## Future Enhancements

Potential future additions to magic keywords:

1. **Priority keywords:** `urgent:`, `low:`, `high:` for task prioritization
2. **Context keywords:** `solo:`, `pair:`, `team:` for collaboration mode
3. **Scope keywords:** `quick:`, `thorough:`, `deep:` for depth control
4. **Phase keywords:** `design:`, `impl:`, `test:` to skip to specific phase

See the OMC feature docs (ecomode, magic-keywords, progress-hud) for roadmap details.
