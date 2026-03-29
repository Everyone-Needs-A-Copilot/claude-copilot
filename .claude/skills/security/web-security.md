---
skill_name: web-security
skill_category: security
description: Web application security patterns covering OWASP Top 10 vulnerabilities
allowed_tools: [Read, Grep, Glob, Edit, Write, WebSearch]
token_estimate: 1200
version: 1.0
last_updated: 2026-01-13
owner: Security Team
status: active
tags: [security, owasp, web, vulnerability, anti-pattern, validation]
trigger_files: ["**/auth/**", "**/api/**", "**/middleware/**", "**/security/**", "**/login/**", "**/session/**"]
trigger_keywords: [security, owasp, xss, csrf, injection, authentication, authorization, vulnerability, sanitize]
quality_keywords: [anti-pattern, vulnerability, exploit, remediation, validation]
---

# Web Security

Comprehensive web application security patterns covering OWASP Top 10 vulnerabilities with detection and remediation guidance.

## Purpose

- Identify common web security vulnerabilities before exploitation
- Provide actionable remediation with code examples
- Establish security review checklists for web applications

---

## OWASP Top 10 (2021)

### A01: Broken Access Control

| Aspect | Description |
|--------|-------------|
| **Risk** | Unauthorized access to data, privilege escalation |
| **Detection** | Missing auth checks, IDOR, path traversal, CORS misconfig |
| **Impact** | Data breach, account takeover, full system compromise |

**Anti-Patterns:**

```typescript
// BAD: No authorization check
app.get('/api/users/:id', (req, res) => {
  return db.users.findById(req.params.id); // Anyone can access any user
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
- [ ] Check authorization on every request
- [ ] Validate user owns requested resource (no IDOR)
- [ ] Disable directory listing
- [ ] Log access control failures

---

### A02: Cryptographic Failures

| Aspect | Description |
|--------|-------------|
| **Risk** | Exposure of sensitive data (passwords, PII, secrets) |
| **Detection** | Plain text storage, weak algorithms, missing encryption |
| **Impact** | Data breach, credential theft, compliance violations |

**Anti-Patterns:**

```typescript
// BAD: Plain text password storage
const user = { password: req.body.password };

// GOOD: Hash with bcrypt
import bcrypt from 'bcrypt';
const hashedPassword = await bcrypt.hash(req.body.password, 12);
const user = { password: hashedPassword };

// BAD: Weak algorithm
const hash = crypto.createHash('md5').update(data).digest('hex');

// GOOD: Strong algorithm
const hash = crypto.createHash('sha256').update(data).digest('hex');
```

**Checklist:**
- [ ] Never store passwords in plain text (use bcrypt/argon2)
- [ ] Use TLS for all data transmission
- [ ] Classify data by sensitivity level
- [ ] Encrypt sensitive data at rest
- [ ] Use strong, modern algorithms (AES-256, SHA-256+)

---

### A03: Injection

| Aspect | Description |
|--------|-------------|
| **Risk** | Arbitrary code execution, data theft/corruption |
| **Detection** | Unsanitized user input in queries/commands |
| **Impact** | Full database access, system compromise, data loss |

**SQL Injection:**

```typescript
// BAD: String concatenation
const query = `SELECT * FROM users WHERE id = ${userId}`;

// GOOD: Parameterized query
const query = 'SELECT * FROM users WHERE id = ?';
const result = await db.query(query, [userId]);

// GOOD: ORM with escaping
const user = await User.findOne({ where: { id: userId } });
```

**Command Injection:**

```typescript
// BAD: Shell command with user input
exec(`ls ${userInput}`);

// GOOD: Use array arguments
execFile('ls', [userInput], { shell: false });

// GOOD: Validate/sanitize input
const sanitized = userInput.replace(/[^a-zA-Z0-9]/g, '');
```

**NoSQL Injection:**

```typescript
// BAD: Direct object insertion
db.users.find({ username: req.body.username });

// GOOD: Type validation
if (typeof req.body.username !== 'string') throw new Error('Invalid');
db.users.find({ username: req.body.username });
```

---

### A04: Insecure Design

| Aspect | Description |
|--------|-------------|
| **Risk** | Fundamental security flaws in architecture |
| **Detection** | Missing threat modeling, no security requirements |
| **Impact** | Cannot be fixed with patches alone |

**Patterns:**
- Threat model before implementation
- Security requirements from design phase
- Defense in depth (multiple security layers)
- Fail securely (deny on error)

---

### A05: Security Misconfiguration

| Aspect | Description |
|--------|-------------|
| **Risk** | Exposed admin interfaces, default credentials, verbose errors |
| **Detection** | Stack traces in production, open cloud storage |
| **Impact** | Information disclosure, unauthorized access |

**Anti-Patterns:**

```typescript
// BAD: Verbose errors in production
app.use((err, req, res, next) => {
  res.status(500).json({ error: err.stack }); // Leaks internals
});

// GOOD: Generic errors in production
app.use((err, req, res, next) => {
  console.error(err); // Log internally
  res.status(500).json({ error: 'Internal server error' });
});

// BAD: Permissive CORS
app.use(cors({ origin: '*' }));

// GOOD: Specific CORS
app.use(cors({ origin: ['https://trusted-domain.com'] }));
```

**Checklist:**
- [ ] Remove/disable unused features
- [ ] No default credentials
- [ ] Proper error handling (no stack traces)
- [ ] Security headers configured (CSP, HSTS, X-Frame-Options)
- [ ] Automated configuration scanning

---

### A06: Vulnerable Components

| Aspect | Description |
|--------|-------------|
| **Risk** | Known vulnerabilities in dependencies |
| **Detection** | Outdated packages, CVE alerts |
| **Impact** | Varies by vulnerability (up to RCE) |

**Mitigation:**
- Run `npm audit` / `pip-audit` / `bundler-audit` regularly
- Subscribe to security advisories
- Automated dependency updates (Dependabot, Renovate)
- Remove unused dependencies

---

### A07: Authentication Failures

| Aspect | Description |
|--------|-------------|
| **Risk** | Account takeover, credential stuffing |
| **Detection** | Weak passwords, no rate limiting, session issues |
| **Impact** | Unauthorized access, identity theft |

**Anti-Patterns:**

```typescript
// BAD: No rate limiting
app.post('/login', async (req, res) => {
  const user = await authenticate(req.body);
});

// GOOD: Rate limiting
import rateLimit from 'express-rate-limit';
const loginLimiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 5, // 5 attempts
  message: 'Too many attempts, try again later'
});
app.post('/login', loginLimiter, async (req, res) => {
  const user = await authenticate(req.body);
});

// BAD: Session in URL
res.redirect(`/dashboard?session=${sessionId}`);

// GOOD: Session in secure cookie
res.cookie('session', sessionId, {
  httpOnly: true,
  secure: true,
  sameSite: 'strict'
});
```

**Checklist:**
- [ ] Implement rate limiting on auth endpoints
- [ ] Use secure session management
- [ ] Require strong passwords (length > complexity)
- [ ] Implement MFA for sensitive operations
- [ ] Account lockout after failed attempts

---

### A08: Software and Data Integrity Failures

| Aspect | Description |
|--------|-------------|
| **Risk** | Untrusted code execution, CI/CD compromise |
| **Detection** | Unsigned updates, insecure deserialization |
| **Impact** | Malware distribution, supply chain attacks |

**Anti-Patterns:**

```typescript
// BAD: Deserialize untrusted data
const obj = JSON.parse(userInput); // Less dangerous but still risky
eval(userInput); // NEVER do this

// BAD: Load from CDN without integrity
<script src="https://cdn.example.com/lib.js"></script>

// GOOD: Subresource integrity
<script
  src="https://cdn.example.com/lib.js"
  integrity="sha384-abc123..."
  crossorigin="anonymous"
></script>
```

---

### A09: Security Logging and Monitoring Failures

| Aspect | Description |
|--------|-------------|
| **Risk** | Undetected breaches, insufficient forensics |
| **Detection** | Missing logs, no alerting, logs without context |
| **Impact** | Extended breach duration, no incident response |

**Pattern:**

```typescript
// GOOD: Comprehensive security logging
logger.warn('authentication_failure', {
  username: req.body.username,
  ip: req.ip,
  userAgent: req.headers['user-agent'],
  timestamp: new Date().toISOString(),
  // Never log passwords or sensitive data
});
```

**Log These Events:**
- Authentication success/failure
- Authorization failures
- Input validation failures
- Session management events
- Configuration changes

---

### A10: Server-Side Request Forgery (SSRF)

| Aspect | Description |
|--------|-------------|
| **Risk** | Access internal services, cloud metadata |
| **Detection** | User-controlled URLs in server requests |
| **Impact** | Internal network access, credential theft |

**Anti-Patterns:**

```typescript
// BAD: Fetch user-provided URL
const response = await fetch(req.body.url);

// GOOD: Allowlist validation
const ALLOWED_HOSTS = ['api.trusted.com', 'cdn.trusted.com'];
const url = new URL(req.body.url);
if (!ALLOWED_HOSTS.includes(url.hostname)) {
  throw new Error('Host not allowed');
}
const response = await fetch(url);

// GOOD: Block internal IPs
import isPrivateIP from 'private-ip';
const url = new URL(req.body.url);
const ip = await dns.resolve(url.hostname);
if (isPrivateIP(ip)) {
  throw new Error('Internal IPs not allowed');
}
```

---

## XSS Prevention Deep Dive

### Types of XSS

| Type | Vector | Prevention |
|------|--------|------------|
| Reflected | URL parameters | Output encoding |
| Stored | Database content | Input validation + output encoding |
| DOM-based | Client-side JS | Safe APIs, avoid innerHTML |

### Output Encoding by Context

```typescript
// HTML context
const safe = escapeHtml(userInput);
// Result: &lt;script&gt; instead of <script>

// JavaScript context
const safe = JSON.stringify(userInput);
// Use in: <script>var data = ${safe};</script>

// URL context
const safe = encodeURIComponent(userInput);
// Use in: <a href="/search?q=${safe}">

// CSS context
const safe = CSS.escape(userInput);
// Use in: <div style="background: ${safe}">
```

### Content Security Policy

```typescript
// Strict CSP header
app.use((req, res, next) => {
  res.setHeader('Content-Security-Policy', [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https:",
    "connect-src 'self' https://api.example.com",
    "frame-ancestors 'none'",
    "form-action 'self'"
  ].join('; '));
  next();
});
```

---

## CSRF Prevention

```typescript
// Token-based protection
import csrf from 'csurf';
app.use(csrf({ cookie: true }));

// Include in forms
<input type="hidden" name="_csrf" value="<%= csrfToken %>" />

// SameSite cookie (additional layer)
res.cookie('session', value, {
  sameSite: 'strict', // or 'lax' for GET navigation
  httpOnly: true,
  secure: true
});
```

---

## Security Headers Checklist

```typescript
// Essential security headers
app.use((req, res, next) => {
  // Prevent clickjacking
  res.setHeader('X-Frame-Options', 'DENY');

  // Prevent MIME sniffing
  res.setHeader('X-Content-Type-Options', 'nosniff');

  // Enable XSS filter (legacy browsers)
  res.setHeader('X-XSS-Protection', '1; mode=block');

  // Force HTTPS
  res.setHeader('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');

  // Control referrer
  res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');

  // Permissions policy
  res.setHeader('Permissions-Policy', 'geolocation=(), microphone=()');

  next();
});
```

---

## Validation Checklist

### Pre-Review
- [ ] Identify all user input entry points
- [ ] Map data flow through application
- [ ] Identify sensitive data handling

### During Review
- [ ] Check each OWASP Top 10 category
- [ ] Verify input validation at boundaries
- [ ] Confirm output encoding by context
- [ ] Review authentication/authorization flows
- [ ] Check security headers and CSP

### Post-Review
- [ ] Document findings with severity
- [ ] Provide remediation code examples
- [ ] Prioritize: Critical > High > Medium
- [ ] Verify fixes don't introduce new issues

---

## Related Resources

- [OWASP Top 10](https://owasp.org/Top10/)
- [OWASP Cheat Sheets](https://cheatsheetseries.owasp.org/)
- [CWE Top 25](https://cwe.mitre.org/top25/)
- Related skills: `skill_get("crypto-patterns")`
