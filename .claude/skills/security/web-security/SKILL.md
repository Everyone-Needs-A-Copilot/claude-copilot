---
name: web-security
description: Web application security covering OWASP Top 10 (2021) with prose guidance (judgment) + deterministic OWASP coverage scoring (executable script)
version: 2.0.0
source: derived from .claude/skills/security/web-security.md (v1.0); L3 OWASP scorer added 2026-05-20
when_to_use:
  - Web application security review
  - API security audit
  - Pre-launch security checklist
  - Post-incident gap analysis against OWASP Top 10
  - Any review touching authentication, authorization, injection, or session management
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash
---

# Web Security

Comprehensive web application security patterns covering OWASP Top 10 (2021). Apply before code review, not after.

OWASP **analysis** is prose judgment — the model reasons about attack vectors, code patterns, and mitigations. OWASP **coverage** is deterministic — the script validates that every finding maps to a real OWASP category and reports which of the 10 categories have zero findings (the blind spots).

Never report a "clean" security review without running the coverage checker.

## OWASP Top 10 (2021) — Quick Reference

| Code | Category | Core Risk |
|------|----------|-----------|
| A01 | Broken Access Control | Unauthorized access, IDOR, privilege escalation |
| A02 | Cryptographic Failures | Plaintext storage, weak algorithms, missing TLS |
| A03 | Injection | SQL, NoSQL, OS, LDAP injection; XSS |
| A04 | Insecure Design | Missing threat model, no security requirements |
| A05 | Security Misconfiguration | Default creds, verbose errors, open CORS |
| A06 | Vulnerable and Outdated Components | CVE-carrying dependencies |
| A07 | Identification and Authentication Failures | Weak passwords, no MFA, session issues |
| A08 | Software and Data Integrity Failures | Unsigned updates, unsafe deserialization |
| A09 | Security Logging and Monitoring Failures | Undetected breaches, missing audit logs |
| A10 | Server-Side Request Forgery (SSRF) | Internal service access via user-controlled URLs |

## Invocation — OWASP Coverage Scorer (L3 Script)

After identifying findings, assemble them as a JSON array and run the scorer. Consume its **output only** — the script source never enters context.

**Format each finding:**
```json
[
  {
    "title": "Admin endpoint lacks authentication check",
    "owasp": "A01",
    "severity": "Critical",
    "status": "open"
  }
]
```

**OWASP field:** Use short codes `A01`–`A10`, or full OWASP 2021 category names (e.g. `"Injection"`), or common shorthands (`"SSRF"`, `"IDOR"`, `"sqli"`, `"authentication"`).

**severity field (optional):** `Critical` | `High` | `Medium` | `Low`

**status field (optional):** `open` | `mitigated` | `accepted` | `n/a`

**Run via Bash (file argument):**
```bash
python .claude/skills/security/web-security/scripts/owasp_score.py findings.json
```

**Run via Bash (stdin):**
```bash
echo '<json array>' | python .claude/skills/security/web-security/scripts/owasp_score.py -
```

**The script outputs:**
1. A JSON object with `findings` (normalized), `category_counts` (findings per category), `gaps` (uncovered categories), and a `summary`.
2. An OWASP Top 10 Coverage markdown table showing finding counts and gaps.
3. (Optional) A Severity Summary table if severity fields are present.

**Error handling:** Non-zero exit on unknown OWASP category, invalid severity, or malformed JSON. Fix the input and re-run.

**What the agent does with the output:**
1. Check `gaps` — any OWASP category with zero findings is a potential blind spot; document why it is N/A before accepting the gap.
2. Address Critical and High open findings before signing off.
3. Use the coverage table as an executive summary.

## Vulnerability Patterns and Mitigations

### A01 — Broken Access Control

```typescript
// BAD: No authorization check
app.get('/api/users/:id', (req, res) => {
  return db.users.findById(req.params.id);
});

// GOOD: Verify ownership
app.get('/api/users/:id', authenticate, (req, res) => {
  if (req.user.id !== req.params.id && !req.user.isAdmin) {
    return res.status(403).json({ error: 'Forbidden' });
  }
  return db.users.findById(req.params.id);
});
```

**Checklist:**
- [ ] Deny by default (explicit allow required)
- [ ] Check authorization on every request, not just on first load
- [ ] Validate user owns the requested resource (no IDOR)
- [ ] Log access control failures

### A02 — Cryptographic Failures

**Checklist:**
- [ ] Never store passwords in plaintext (use bcrypt or Argon2id — see crypto-patterns skill)
- [ ] TLS for all data transmission; no HTTP fallback
- [ ] Encrypt sensitive data at rest
- [ ] Strong, modern algorithms — see crypto-patterns skill for specifics

### A03 — Injection

```typescript
// BAD: String concatenation in query
const q = `SELECT * FROM users WHERE id = ${userId}`;

// GOOD: Parameterized query
const q = 'SELECT * FROM users WHERE id = ?';
const result = await db.query(q, [userId]);
```

**Checklist:**
- [ ] Parameterized queries or ORM for all database access
- [ ] No dynamic shell commands with user input
- [ ] Output encoding at every rendering context (HTML, JS, CSS, URL)
- [ ] Content Security Policy deployed

### A05 — Security Misconfiguration

```typescript
// BAD: Stack trace in production error
app.use((err, req, res, next) => {
  res.status(500).json({ error: err.stack });
});

// GOOD: Generic error in production
app.use((err, req, res, next) => {
  console.error(err);
  res.status(500).json({ error: 'Internal server error' });
});
```

**Security Headers Checklist:**
- [ ] `X-Frame-Options: DENY`
- [ ] `X-Content-Type-Options: nosniff`
- [ ] `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- [ ] `Referrer-Policy: strict-origin-when-cross-origin`
- [ ] Content-Security-Policy configured

### A07 — Authentication Failures

```typescript
// BAD: No rate limiting on login
app.post('/login', async (req, res) => { ... });

// GOOD: Rate limiting + secure session cookie
import rateLimit from 'express-rate-limit';
const loginLimiter = rateLimit({ windowMs: 15 * 60 * 1000, max: 5 });
app.post('/login', loginLimiter, async (req, res) => {
  // ...
  res.cookie('session', sessionId, { httpOnly: true, secure: true, sameSite: 'strict' });
});
```

### A10 — SSRF

```typescript
// BAD: Fetch user-provided URL
const response = await fetch(req.body.url);

// GOOD: Allowlist validation
const ALLOWED = ['api.trusted.com'];
const url = new URL(req.body.url);
if (!ALLOWED.includes(url.hostname)) throw new Error('Host not allowed');
const response = await fetch(url);
```

## Review Workflow

1. **Map entry points** — List every public and privileged endpoint
2. **Identify findings** — For each entry point, check relevant OWASP categories
3. **Assemble findings JSON** — Include `owasp` category, `severity`, and `status`
4. **Run the coverage scorer** — `python .claude/skills/security/web-security/scripts/owasp_score.py findings.json`
5. **Address gaps** — Every uncovered OWASP category needs a documented rationale (not just silence)
6. **Remediate by severity** — Critical first; do not remediate in order of discovery

## Anti-Generic Rules

- NEVER report a clean security review without running the coverage scorer
- NEVER fix only the top-priority finding — all Critical/High open items must be addressed before sign-off
- NEVER use client-side validation as a security control
- NEVER leave verbose error messages in production (stack traces are recon material)
- NEVER assume a WAF replaces code-level fixes

**Self-Critique:** "Did I run the scorer and inspect the gaps? Can I justify every gap as genuinely N/A, or did I just skip it? Would the A09 (Logging) category pass a pen test today?"
