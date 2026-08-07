---
name: refactoring-patterns
skill_category: code
description: >-
  Code smell detection, refactoring triggers, and safe transformation patterns
  for extract, inline, and rename operations. Includes deterministic
  code-structure metrics analyzer (refactor_metrics.py) for long functions,
  deep nesting, long parameter lists, large files, and function count — covers
  TypeScript, JavaScript, Python, Go, Java, and Ruby. Use proactively when
  identifying refactoring opportunities, code-reviewing for structural complexity
  signals, prioritizing technical debt, or establishing a complexity baseline for
  a module. Run the metrics analyzer for deterministic scoring.
version: 2.0.0
source: migrated from code/refactoring-patterns.md (v1.0, 2026-03-29); L3 metrics analyzer added 2026-05-20
when_to_use:
  - Identifying refactoring opportunities before or during a refactoring session
  - Code review for structural complexity signals
  - Prioritizing technical debt work
  - Establishing a complexity baseline for a module
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash
tags: [refactoring, clean-code, code-smells, patterns]
trigger_files: ["*.ts", "*.js", "*.py", "*.go", "*.java", "*.rb"]
trigger_keywords: [refactor, code-smell, extract, inline, rename, technical-debt, clean-code]
quality_keywords: [anti-pattern, smell, duplication, responsibility, abstraction]
---

# Refactoring Patterns

Code smell detection, refactoring triggers, and safe transformation patterns for improving existing code without changing behaviour.

refactor_metrics.py detects deterministic complexity signals (long functions, deep nesting, etc.). The prose sections below cover judgment-level smells that the script cannot evaluate (Feature Envy, Primitive Obsession, etc.). Run the script first to get a structural baseline; apply judgment from the prose sections to interpret findings in context.

## Purpose

- Identify code smells systematically before refactoring
- Apply the right refactoring technique for each smell
- Refactor safely with tests as the safety net
- Avoid common refactoring anti-patterns that create new problems

---

## Code Smell Catalog

| Smell | Detection Signal | Refactoring Technique |
|-------|-----------------|----------------------|
| **Long Method** | Method body > 20 lines | Extract Method |
| **Feature Envy** | Method uses another class's data more than its own | Move Method to the class it envies |
| **Shotgun Surgery** | One change requires touching many unrelated classes | Move Field/Method to consolidate responsibility |
| **Long Parameter List** | Function signature has > 3 parameters | Introduce Parameter Object |
| **Primitive Obsession** | Using `string`, `number`, `boolean` for domain concepts (e.g., email, money, status) | Replace with Value Object |
| **Data Clump** | Same group of fields appears together across multiple classes or function signatures | Extract Class |
| **Divergent Change** | One class is changed for multiple unrelated reasons | Extract Class per single responsibility |
| **Middle Man** | Class does nothing but delegate every method call to another | Remove Middle Man or Inline Delegation |

### Detection Examples

```typescript
// SMELL: Long Parameter List (>3 params)
function createOrder(userId: string, productId: string, quantity: number, discount: number, shippingAddress: string) {}

// BETTER: Parameter Object
interface OrderRequest {
  userId: string;
  productId: string;
  quantity: number;
  discount: number;
  shippingAddress: string;
}
function createOrder(request: OrderRequest) {}

// SMELL: Primitive Obsession — email as raw string
function sendWelcome(email: string) {
  if (!email.includes('@')) throw new Error('invalid');
}

// BETTER: Value Object with self-validation
class Email {
  constructor(private readonly value: string) {
    if (!value.includes('@')) throw new Error('Invalid email');
  }
  toString() { return this.value; }
}
function sendWelcome(email: Email) {}
```

---

## Refactoring Decision Rules

### When to Extract

- **3+ duplications** of the same code block (Rule of Three)
- Method body exceeds 20 lines
- Method has more than one clear responsibility
- Code block requires a comment to explain what it does (the comment is the method name)

### When to Inline

- Abstraction adds no value (wrapper is completely transparent)
- Delegation chain exceeds 2 hops without adding logic
- Extracted method is only called from one place and the indirection obscures intent

### When to Rename

- Name no longer matches current behaviour
- Domain language has evolved since the code was written
- Name uses implementation details rather than domain concepts (e.g., `processArray` vs `applyDiscounts`)

---

## Safety Checklist

Complete all steps before beginning a refactoring session.

**Before:**
- [ ] Tests exist and pass at current coverage level
- [ ] Scope is bounded — know which files will change
- [ ] No behaviour changes intended (refactoring = structure only)
- [ ] Create a commit capturing the current working state (clean starting point)

**During:**
- [ ] Run tests after each individual refactoring step
- [ ] Refactor one smell at a time — do not chain multiple techniques in one step
- [ ] Do not fix bugs while refactoring (log them, do them separately)

**After:**
- [ ] All tests still pass
- [ ] No new lint warnings introduced
- [ ] Commit with message starting `refactor:` to distinguish from feature commits
- [ ] Update any documentation that referenced the old structure

---

## Anti-Patterns

| Anti-Pattern | Description | Why It's Harmful |
|-------------|-------------|-----------------|
| **Speculative Generalization** | Abstracting for use cases that don't exist yet | Creates complexity for no current value; YAGNI |
| **Premature Abstraction** | Extracting a pattern after fewer than 3 occurrences | Two instances may be coincidental; wait for the third |
| **Refactoring Without Tests** | Changing structure without a test safety net | No way to know if behaviour was accidentally changed |
| **"Clean Up While We're Here"** | Expanding refactoring scope during a feature branch | Mixes concerns, increases review noise, raises risk of regression |
| **Rename as Disguise** | Renaming a bad abstraction instead of fixing it | The smell remains; only the label changes |

---

## Related Resources

- [Refactoring.Guru](https://refactoring.guru/refactoring/catalog) — full refactoring catalog
- [Working Effectively with Legacy Code — Michael Feathers](https://www.goodreads.com/book/show/44919.Working_Effectively_with_Legacy_Code) — adding tests to untested code
- Related skills: `cc skill get testing-patterns`

---

## Invocation — Code Metrics Analyzer (L3 Script)

Before starting a refactoring session, run the metrics analyzer to get a structural baseline. Consume the script's **output only** — the script source never enters context.

The script supports Python files (AST-based, accurate) and JavaScript/TypeScript files (regex-based, approximate). Smells requiring contextual judgment (Feature Envy, Primitive Obsession, Data Clumps) are not detectable by the script; apply the prose catalog above to interpret findings.

**Metrics detected:**

| ID | Name | Severity | Threshold | Source |
|----|------|----------|-----------|--------|
| METRIC-01 | long_function | HIGH | > 20 lines | Fowler "Refactoring" §3 |
| METRIC-02 | deep_nesting | HIGH | > 4 levels | Sonarqube Cognitive Complexity 2017 |
| METRIC-03 | long_param_list | MEDIUM | > 3 params | Fowler "Refactoring" §3 |
| METRIC-04 | large_file | MEDIUM | > 300 lines | Clean Code §5 |
| METRIC-05 | many_functions | LOW | > 10 functions | SRP signal |

**Run via Bash (Python file):**
```bash
python .claude/skills/code/refactoring-patterns/scripts/refactor_metrics.py path/to/module.py
```

**Run via Bash (JS/TS file):**
```bash
python .claude/skills/code/refactoring-patterns/scripts/refactor_metrics.py path/to/service.ts
```

**Run via Bash (stdin):**
```bash
cat module.py | python .claude/skills/code/refactoring-patterns/scripts/refactor_metrics.py -
```

**Output fields (JSON):**
```json
{
  "findings": [
    {
      "metric_id": "METRIC-01",
      "name": "long_function",
      "severity": "HIGH",
      "message": "Function 'process_order' is 42 lines (threshold: 20)",
      "file": "order_service.py",
      "line": 15,
      "function": "process_order",
      "value": 42,
      "threshold": 20
    }
  ],
  "summary": {
    "total": 3,
    "high": 1,
    "medium": 1,
    "low": 1,
    "language": "python"
  }
}
```

**What the agent does with the output:**
1. Address `HIGH` severity findings first — these are strong refactoring candidates.
2. Review `MEDIUM` findings — large files and long param lists are review signals, not always blockers.
3. Use `LOW` findings as informational context when scoping a refactoring session.
4. Cross-reference with the prose catalog above for smells the script cannot detect.

**Error handling:** Invalid path → exits 1 with `ERROR:` message on stderr. Unsupported file extension → exits 1. Directory argument → exits 1 (pass a single file). Empty input → exits 0 with zero findings.
