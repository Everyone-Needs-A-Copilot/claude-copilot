---
skill_name: javascript-patterns
skill_category: code
description: JavaScript/TypeScript patterns, anti-patterns, and quality rules
allowed_tools: [Read, Edit, Write, Grep]
token_estimate: 1800
version: 1.0
last_updated: 2026-01-13
owner: Claude Copilot
status: active
tags: [javascript, typescript, nodejs, patterns, quality, async]
related_skills: [react-patterns, testing-patterns]
trigger_files: ["*.js", "*.ts", "*.mjs", "*.cjs", "package.json", "tsconfig.json"]
trigger_keywords: [javascript, typescript, nodejs, async, promise, eslint, npm]
---

# JavaScript Patterns

Modern JavaScript/TypeScript patterns, anti-patterns, and quality rules.

## Core Principles

| Principle | Description |
|-----------|-------------|
| **Immutability** | Prefer const, avoid mutation |
| **Pure Functions** | Same input = same output, no side effects |
| **Async/Await** | Over raw promises and callbacks |
| **Type Safety** | Use TypeScript for non-trivial projects |

## Patterns vs Anti-Patterns

### Variable Declaration

```typescript
// GOOD: const by default
const config = { timeout: 5000 };
const items = ['a', 'b', 'c'];

// OK: let when reassignment needed
let count = 0;
for (const item of items) {
  count++;
}

// BAD: var (hoisting issues)
var data = fetchData();  // Never use var
```

### Async/Await

```typescript
// GOOD: async/await
async function fetchUsers(): Promise<User[]> {
  try {
    const response = await fetch('/api/users');
    return await response.json();
  } catch (error) {
    throw new ApiError('Failed to fetch users', { cause: error });
  }
}

// GOOD: Parallel with Promise.all
const [users, posts] = await Promise.all([
  fetchUsers(),
  fetchPosts()
]);

// BAD: Sequential when parallel possible
const users = await fetchUsers();
const posts = await fetchPosts();  // Waits unnecessarily
```

### Error Handling

```typescript
// GOOD: Custom error classes
class ValidationError extends Error {
  constructor(
    message: string,
    public field: string,
    public code: string
  ) {
    super(message);
    this.name = 'ValidationError';
  }
}

// GOOD: Error boundary with type narrowing
function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

try {
  await riskyOperation();
} catch (error) {
  if (isApiError(error)) {
    handleApiError(error);
  } else {
    throw error;  // Re-throw unknown errors
  }
}

// BAD: Catch and ignore
try {
  await riskyOperation();
} catch (e) {
  // Silent failure - never do this
}
```

### Nullish Handling

```typescript
// GOOD: Nullish coalescing
const value = input ?? defaultValue;  // Only null/undefined

// GOOD: Optional chaining
const name = user?.profile?.name;
const result = callback?.();

// BAD: OR for defaults (falsy issues)
const value = input || defaultValue;  // 0, '', false become default!

// BAD: Manual null checks
const name = user && user.profile && user.profile.name;
```

### Array Methods

```typescript
// GOOD: Functional array methods
const activeUsers = users
  .filter(u => u.active)
  .map(u => ({ id: u.id, name: u.name }));

// GOOD: find/findIndex for single items
const admin = users.find(u => u.role === 'admin');
const index = users.findIndex(u => u.id === targetId);

// GOOD: reduce for accumulation
const byId = users.reduce((acc, user) => {
  acc[user.id] = user;
  return acc;
}, {} as Record<string, User>);

// BAD: forEach with mutation
const results = [];
users.forEach(u => {
  if (u.active) results.push(u.name);
});
```

### Object Operations

```typescript
// GOOD: Spread for immutable updates
const updated = { ...user, name: 'New Name' };
const merged = { ...defaults, ...options };

// GOOD: Destructuring
const { id, name, email } = user;
const { data, error } = await fetchUser(id);

// GOOD: Computed property names
const key = 'dynamicKey';
const obj = { [key]: value };

// BAD: Object.assign mutation
Object.assign(user, { name: 'New Name' });  // Mutates!
```

### String Operations

```typescript
// GOOD: Template literals
const message = `Hello, ${name}! You have ${count} items.`;
const multiline = `
  First line
  Second line
`;

// GOOD: Tagged templates for escaping
const query = sql`SELECT * FROM users WHERE id = ${userId}`;

// BAD: Concatenation
const message = 'Hello, ' + name + '!';
```

## Anti-Patterns to Avoid

### Type Coercion Issues

```typescript
// BAD: Implicit coercion
if (value == null) { }  // Catches both null and undefined
const str = '' + num;   // Use String(num)

// GOOD: Explicit comparison
if (value === null || value === undefined) { }
if (value == null) { }  // OK - intentional loose equality for null/undefined

// GOOD: Explicit conversion
const str = String(num);
const num = Number(str);
const bool = Boolean(value);
```

### Callback Hell

```typescript
// BAD: Nested callbacks
getData((data) => {
  process(data, (result) => {
    save(result, (saved) => {
      notify(saved, () => {
        console.log('Done');
      });
    });
  });
});

// GOOD: async/await
const data = await getData();
const result = await process(data);
const saved = await save(result);
await notify(saved);
```

### Floating Promises

```typescript
// BAD: Unhandled promise
fetchData();  // Fire and forget - errors lost!

// GOOD: Handle or await
await fetchData();
// OR
fetchData().catch(handleError);
// OR
void fetchData();  // Explicit discard (use sparingly)
```

### `this` Binding Issues

```typescript
// BAD: Lost context
class Handler {
  name = 'Handler';
  handleClick() {
    console.log(this.name);  // undefined when used as callback!
  }
}

// GOOD: Arrow function or bind
class Handler {
  name = 'Handler';
  handleClick = () => {
    console.log(this.name);  // Works!
  };
}
```

## TypeScript Best Practices

### Type Definitions

```typescript
// GOOD: Interface for objects
interface User {
  id: string;
  name: string;
  email: string;
}

// GOOD: Type alias for unions/primitives
type Status = 'pending' | 'active' | 'archived';
type ID = string | number;

// GOOD: Generics for reusable types
type Result<T, E = Error> =
  | { success: true; data: T }
  | { success: false; error: E };
```

### Type Guards

```typescript
// Discriminated unions
interface SuccessResponse { status: 'success'; data: unknown }
interface ErrorResponse { status: 'error'; message: string }
type Response = SuccessResponse | ErrorResponse;

function handleResponse(res: Response) {
  if (res.status === 'success') {
    // TypeScript knows res.data exists
    return res.data;
  } else {
    // TypeScript knows res.message exists
    throw new Error(res.message);
  }
}
```

### Avoid `any`

```typescript
// BAD: any disables type checking
function process(data: any): any { }

// GOOD: unknown + type guard
function process(data: unknown): Result {
  if (isValidData(data)) {
    return transform(data);
  }
  throw new ValidationError('Invalid data');
}
```

## Quality Checklist

| Check | Rule |
|-------|------|
| No `var` | Use `const` by default, `let` when needed |
| No `any` | Use `unknown` with type guards |
| Async/await | Over raw promises |
| Nullish ops | `??` and `?.` over `||` and `&&` |
| Immutable | Spread over mutation |
| Type safety | All exports typed |
| Error handling | No silent catches |
| No floating promises | Always handle or await |
