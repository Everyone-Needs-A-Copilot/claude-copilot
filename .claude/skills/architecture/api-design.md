---
skill_name: api-design
skill_category: architecture
description: Design and review REST/GraphQL APIs with anti-patterns and best practices
allowed_tools: [Read, Edit, Glob, Grep]
token_estimate: 1800
version: 1.0
last_updated: 2026-01-13
owner: Claude Copilot
status: active
tags: [api, rest, graphql, design, architecture, http, endpoints]
related_skills: [distributed-systems]
trigger_files: ["**/api/**", "**/routes/**", "**/*controller*", "**/*endpoint*", "**/schema.graphql"]
trigger_keywords: [api, endpoint, rest, graphql, http, route, controller, request, response]
---

# API Design

Design and review REST/GraphQL APIs following best practices and avoiding common anti-patterns.

## Purpose

Consistent, well-designed APIs reduce integration friction, improve developer experience, and prevent breaking changes. This skill codifies API design principles for both new designs and reviews.

## Design Principles

### 1. Resource-Oriented Design (REST)

| Principle | Do | Don't |
|-----------|-----|-------|
| Use nouns | `/users`, `/orders` | `/getUsers`, `/createOrder` |
| Plural collections | `/users/123` | `/user/123` |
| Nest relationships | `/users/123/orders` | `/orders?userId=123` (for ownership) |
| Flat when independent | `/orders/456` | `/users/123/orders/456` (if orders exist independently) |

### 2. HTTP Methods

| Method | Use For | Idempotent | Safe |
|--------|---------|------------|------|
| GET | Read resources | Yes | Yes |
| POST | Create resources, actions | No | No |
| PUT | Replace entire resource | Yes | No |
| PATCH | Partial update | Yes | No |
| DELETE | Remove resource | Yes | No |

### 3. Status Codes

| Range | Meaning | Common Codes |
|-------|---------|--------------|
| 2xx | Success | 200 OK, 201 Created, 204 No Content |
| 3xx | Redirect | 301 Moved, 304 Not Modified |
| 4xx | Client error | 400 Bad Request, 401 Unauthorized, 403 Forbidden, 404 Not Found, 409 Conflict, 422 Unprocessable |
| 5xx | Server error | 500 Internal, 502 Bad Gateway, 503 Unavailable |

## Anti-Patterns

### 1. Chatty APIs

**Problem:** Requiring many requests to complete one operation.

```
❌ GET /users/123
❌ GET /users/123/preferences
❌ GET /users/123/addresses
❌ GET /users/123/payment-methods
```

**Solution:** Use includes/expands or aggregate endpoints.

```
✅ GET /users/123?include=preferences,addresses,payment-methods
```

### 2. Breaking Changes Without Versioning

**Problem:** Modifying response structure without version bump.

```
❌ Removing fields from responses
❌ Changing field types (string → number)
❌ Changing enum values
❌ Making optional fields required
```

**Solution:** Version your API and maintain backwards compatibility.

```
✅ /api/v1/users → stable, no breaking changes
✅ /api/v2/users → new version with different structure
✅ Add fields (additive changes don't break)
```

### 3. Inconsistent Naming

**Problem:** Mixed conventions across endpoints.

```
❌ GET /users (plural) vs GET /order (singular)
❌ POST /createUser vs POST /users
❌ camelCase vs snake_case in same API
```

**Solution:** Establish and enforce naming conventions.

```
✅ All collections plural: /users, /orders, /products
✅ Consistent case: camelCase OR snake_case, never mixed
✅ Verbs only for non-CRUD actions: POST /orders/123/cancel
```

### 4. God Endpoints

**Problem:** One endpoint doing too many unrelated things.

```
❌ POST /api?action=createUser&...
❌ POST /api?action=deleteOrder&...
❌ POST /api?action=generateReport&...
```

**Solution:** Separate resources and actions.

```
✅ POST /users (create user)
✅ DELETE /orders/123 (delete order)
✅ POST /reports/generate (action on resource)
```

### 5. Leaky Abstractions

**Problem:** Internal implementation details exposed in API.

```
❌ /users/123/database_id
❌ Returning SQL column names directly
❌ Exposing internal service names in errors
```

**Solution:** Abstract internal details behind stable contracts.

```
✅ /users/123 (use stable ID)
✅ Map database columns to API field names
✅ Generic error messages without internals
```

### 6. Missing Pagination

**Problem:** Returning unbounded collections.

```
❌ GET /users → returns ALL 1M users
```

**Solution:** Default pagination with limits.

```
✅ GET /users → returns first 20 with pagination
✅ GET /users?page=2&limit=50
✅ GET /users?cursor=abc123 (cursor-based)
```

### 7. N+1 Query Patterns in API

**Problem:** API structure that encourages N+1 client calls.

```
❌ GET /orders → [{id: 1}, {id: 2}]
❌ GET /orders/1/items → [...]
❌ GET /orders/2/items → [...]
# N+1 calls to fetch order items
```

**Solution:** Support batch operations and includes.

```
✅ GET /orders?include=items
✅ GET /order-items?orderIds=1,2,3 (batch)
```

## Design Checklist

### New Endpoint Review

| Check | Question |
|-------|----------|
| Resource naming | Is it a noun? Is it plural? |
| HTTP method | Does it match CRUD semantics? |
| Status codes | Are all cases covered? |
| Error responses | Structured with codes and messages? |
| Pagination | Does it return collections? Paginated? |
| Filtering | Can clients filter server-side? |
| Idempotency | Is it safe to retry? |
| Versioning | Is version in path or header? |

### Breaking Change Review

| Change Type | Breaking? | Action |
|-------------|-----------|--------|
| Add field | No | Ship it |
| Remove field | Yes | Deprecate first, remove in v2 |
| Rename field | Yes | Add alias first, remove old in v2 |
| Change type | Yes | New field or version |
| New required parameter | Yes | Make optional or version |
| New error code | No | Document it |

## Output Format

When reviewing or designing APIs:

```markdown
## API Design: [Resource/Endpoint]

### Endpoint Specification

| Method | Path | Description |
|--------|------|-------------|
| GET | /resources | List with pagination |
| POST | /resources | Create new |
| GET | /resources/:id | Get single |
| PATCH | /resources/:id | Update |
| DELETE | /resources/:id | Remove |

### Request/Response Examples

**GET /resources**
```json
{
  "data": [...],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 100
  }
}
```

### Anti-Patterns Avoided
- [List specific anti-patterns checked and avoided]

### Design Decisions
- [Key decisions and rationale]
```

## GraphQL Considerations

### Schema Design

```graphql
# Use clear, domain-driven types
type User {
  id: ID!
  email: String!
  profile: UserProfile  # Separate concerns
}

# Avoid god types
type Query {
  user(id: ID!): User
  users(filter: UserFilter, pagination: Pagination): UserConnection!
}
```

### Anti-Patterns (GraphQL)

| Anti-Pattern | Problem | Solution |
|--------------|---------|----------|
| Deep nesting | N+1 DataLoader issues | Flatten where possible, use DataLoader |
| Nullable everything | Unclear contracts | Be explicit about nullability |
| No pagination | Memory issues | Use connections/edges pattern |
| Enum strings | Type safety lost | Use GraphQL enums |
