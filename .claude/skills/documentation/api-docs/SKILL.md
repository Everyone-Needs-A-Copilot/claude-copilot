---
name: api-docs
skill_category: documentation
description: API documentation patterns with endpoint specs, auth flows, and error handling — plus deterministic OpenAPI/Swagger coverage linting
version: 2.0.0
source: .claude/skills/documentation/api-docs.md (v1.0); L3 linter added 2026-05-20
when_to_use:
  - Documenting REST API endpoints
  - Reviewing OpenAPI/Swagger specs for completeness
  - Ensuring auth flows, error codes, and examples are documented
  - API-first design reviews
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash
  - Write
token_estimate: 700
last_updated: 2026-05-20
owner: Claude Copilot
status: active
tags: [api, documentation, openapi, rest, endpoints, anti-pattern, best-practice, validation]
related_skills: [tutorial-patterns]
trigger_files: ["**/api/**", "**/routes/**", "**/controllers/**", "**/*.openapi.*", "**/swagger.*"]
trigger_keywords: [api docs, endpoint documentation, api reference, swagger, openapi, rest api]
quality_keywords: [anti-pattern, pattern, validation, best-practice, api-first, versioning]
---

# API Documentation

Patterns for creating clear, complete API documentation that developers can use without guessing.

OpenAPI/Swagger spec completeness is deterministic — the linter script checks it exactly. Prose judgment (is this description clear? is this example realistic?) remains L2 work.

## Purpose

- Provide consistent structure for API endpoint documentation
- Ensure all critical information (auth, errors, examples) is included
- Enable developers to make successful API calls on first try

---

## Core Patterns

### Pattern 1: Endpoint Specification

**When to use:** Documenting any REST API endpoint.

**Implementation:**
```markdown
## `METHOD /path/:param`

Brief description of what this endpoint does.

### Authentication
Bearer token required in Authorization header.

### Parameters
| Name | Type | In | Required | Description |
|------|------|-----|----------|-------------|
| id | string | path | Yes | Resource identifier |
| limit | integer | query | No | Max results (default: 20) |

### Request Body
```json
{
  "field": "value"
}
```

### Response
```json
{
  "id": "abc123",
  "created_at": "2024-01-01T00:00:00Z"
}
```

### Errors
| Code | Meaning | Resolution |
|------|---------|------------|
| 400 | Invalid request | Check request body format |
| 401 | Unauthorized | Include valid Bearer token |
| 404 | Not found | Verify resource ID exists |

### Example
```bash
curl -X GET "https://api.example.com/resource/abc123" \
  -H "Authorization: Bearer TOKEN"
```
```

**Benefits:**
- Developers find information predictably
- All edge cases documented upfront
- Copy-paste examples reduce errors

### Pattern 2: Error Response Documentation

**When to use:** Documenting error responses for any endpoint.

**Implementation:**
```markdown
### Error Response Format
All errors return this structure:
```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "User with ID 'xyz' not found",
    "details": {
      "resource": "user",
      "id": "xyz"
    }
  }
}
```

### Common Error Codes
| Code | HTTP Status | Description | Action |
|------|-------------|-------------|--------|
| `INVALID_REQUEST` | 400 | Malformed request body | Validate JSON structure |
| `UNAUTHORIZED` | 401 | Missing or invalid token | Refresh authentication |
| `FORBIDDEN` | 403 | Insufficient permissions | Check user roles |
| `NOT_FOUND` | 404 | Resource doesn't exist | Verify ID |
| `RATE_LIMITED` | 429 | Too many requests | Wait and retry |
```

**Benefits:**
- Consistent error handling in client code
- Actionable resolution guidance
- Reduces support burden

---

## Anti-Patterns

### Anti-Pattern 1: Missing Authentication Details

| Aspect | Description |
|--------|-------------|
| **WHY** | Developers waste time debugging 401 errors; increases support tickets |
| **DETECTION** | Endpoint docs without "Authentication" section; no example with auth header |
| **FIX** | Always include auth method, header format, and token example |

**Bad Example:**
```markdown
## GET /api/users

Returns list of users.

### Response
```json
[{"id": "1", "name": "John"}]
```
```

**Good Example:**
```markdown
## GET /api/users

Returns list of users.

### Authentication
Requires Bearer token in Authorization header.
```
Authorization: Bearer <your-api-key>
```

### Response
```json
[{"id": "1", "name": "John"}]
```

### Example
```bash
curl -X GET "https://api.example.com/api/users" \
  -H "Authorization: Bearer sk_live_abc123"
```
```

### Anti-Pattern 2: Undocumented Error States

| Aspect | Description |
|--------|-------------|
| **WHY** | Clients can't handle errors gracefully; leads to poor UX and debugging chaos |
| **DETECTION** | Docs only show success responses; no error codes or troubleshooting |
| **FIX** | Document every possible error with code, cause, and resolution |

**Bad Example:**
```markdown
### Response
```json
{"status": "success", "data": {...}}
```
```

**Good Example:**
```markdown
### Success Response (200)
```json
{"status": "success", "data": {...}}
```

### Error Responses
| Status | Code | When | Resolution |
|--------|------|------|------------|
| 400 | `INVALID_EMAIL` | Email format wrong | Use valid email |
| 409 | `USER_EXISTS` | Email already registered | Use login endpoint |
| 422 | `WEAK_PASSWORD` | Password too simple | 8+ chars, mixed case |
```

### Anti-Pattern 3: Example-Free Documentation

| Aspect | Description |
|--------|-------------|
| **WHY** | Forces developers to guess; increases time to first successful call |
| **DETECTION** | No curl/code examples; no sample request/response pairs |
| **FIX** | Include complete, copy-paste-ready examples for every endpoint |

**Bad Example:**
```markdown
## POST /api/users
Creates a new user with the provided data.
```

**Good Example:**
```markdown
## POST /api/users
Creates a new user.

### Request
```bash
curl -X POST "https://api.example.com/api/users" \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "name": "John Doe"}'
```

### Response
```json
{
  "id": "usr_abc123",
  "email": "user@example.com",
  "name": "John Doe",
  "created_at": "2024-01-15T10:30:00Z"
}
```
```

---

## Validation Checklist

### Pre-Documentation
- [ ] Endpoint actually exists and works
- [ ] Understand all parameters and their validation
- [ ] Tested all error cases

### Documentation
- [ ] Authentication section included
- [ ] All parameters documented with types
- [ ] Request body example provided (if applicable)
- [ ] Success response example included
- [ ] Error responses documented with resolution
- [ ] Complete curl example provided

### Post-Documentation
- [ ] Example actually works when copied
- [ ] All status codes verified against implementation
- [ ] Cross-linked to related endpoints

---

## Invocation — OpenAPI Coverage Linter (L3 Script)

When reviewing an OpenAPI 3.x or Swagger 2.0 spec, run the linter to get structured, ranked findings. Consume the script's **output only** — the script source never enters context.

**Input format:** JSON object — an OpenAPI or Swagger spec. YAML specs must be converted to JSON upstream (e.g., with `python3 -c "import sys, json, yaml; json.dump(yaml.safe_load(sys.stdin), sys.stdout)" < spec.yaml`).

**Rules checked:**

| Rule | Severity | What it checks |
|------|----------|---------------|
| R01 | MEDIUM | Operation missing `summary` [OAS3 §4.8.10.1] |
| R02 | LOW | Operation missing `description` [OAS3 §4.8.10.1] |
| R03 | MEDIUM | Path parameter missing description [OAS3 §4.8.12.1] |
| R04 | LOW | Query/header/cookie param missing description [OAS3 §4.8.12.1] |
| R05 | MEDIUM | Request body missing description [OAS3 §4.8.13.1] |
| R06 | LOW | Request body media type missing example [OAS3 §4.8.14.1] |
| R07 | MEDIUM | Response missing description [OAS3 §4.8.17.1] |
| R08 | LOW | Response schema present but no example [OAS3 §4.8.14.1] |
| R09 | HIGH | No 4xx response documented [RFC 7231 §6] |
| R10 | HIGH | Secured endpoint missing 401/403 response [OAS3 §4.8.21] |
| R12 | LOW | `operationId` not camelCase [OAS3 community convention] |
| R13 | LOW | `info` block missing `contact` or `license` [OAS3 §4.8.2] |

**Bash invocation (file argument):**
```bash
python .claude/skills/documentation/api-docs/scripts/api_coverage.py spec.json
```

**Bash invocation (stdin):**
```bash
cat openapi.json | python .claude/skills/documentation/api-docs/scripts/api_coverage.py -
```

**Script output:**
1. A JSON block: `{ "spec_version": "oas3|swagger2", "findings": [...], "summary": { "total", "high", "medium", "low" } }`
2. A markdown findings table sorted by severity (HIGH → MEDIUM → LOW).

**What the agent does with the output:**
1. Read the HIGH-severity findings first — these represent auth/error documentation gaps that will cause client failures.
2. Flag MEDIUM findings as required documentation debt.
3. Present LOW findings as enrichment opportunities; leave the decision to fix them to the team.
4. Reference the JSON summary counts in any executive-level documentation review.

**Error handling:** The script exits non-zero with an `ERROR:` message to stderr on bad JSON, non-object input, or unrecognised spec format. Fix the input and re-run.

---

## Related Resources

- Related skills: `tutorial-patterns`
- OpenAPI Specification: https://swagger.io/specification/

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 2.0.0 | 2026-05-20 | L3 script `api_coverage.py` added; Invocation section; allowed-tools updated |
| 1.0.0 | 2026-01-13 | Initial version with anti-patterns |
