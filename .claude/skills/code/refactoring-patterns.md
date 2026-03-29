---
skill_name: refactoring-patterns
skill_category: code
description: Code smell detection, refactoring triggers, and safe transformation patterns
allowed_tools: [Read, Grep, Glob, Edit, Write]
token_estimate: 1800
version: 1.0
last_updated: 2026-03-29
owner: Claude Copilot
status: active
tags: [refactoring, clean-code, code-smells, patterns]
trigger_files: ["*.ts", "*.js", "*.py", "*.go", "*.java", "*.rb"]
trigger_keywords: [refactor, code-smell, extract, inline, rename, technical-debt, clean-code]
quality_keywords: [anti-pattern, smell, duplication, responsibility, abstraction]
---

# Refactoring Patterns

Code smell detection, refactoring triggers, and safe transformation patterns for improving existing code without changing behaviour.

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
- Related skills: `skill_get("testing-patterns")`
