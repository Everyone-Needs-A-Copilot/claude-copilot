---
skill_name: threat-modeling
skill_category: security
description: STRIDE threat identification, DREAD severity scoring, and attack surface analysis
allowed_tools: [Read, Grep, Glob, Edit, Write]
token_estimate: 1500
version: 1.0
last_updated: 2026-03-29
owner: Claude Copilot
status: active
tags: [security, threat-modeling, stride, dread, risk-assessment]
trigger_files: ["**/auth/**", "**/security/**", "**/api/**", "**/middleware/**"]
trigger_keywords: [threat-model, stride, dread, attack-surface, trust-boundary, security-review]
quality_keywords: [anti-pattern, threat, vulnerability, risk, trust-boundary]
---

# Threat Modeling

STRIDE threat identification, DREAD severity scoring, and attack surface analysis for structured security review.

## Purpose

- Identify threats systematically using STRIDE before implementation
- Score and prioritise threats using the DREAD rubric
- Map trust boundaries to find where controls must exist
- Enumerate attack surface entry points for focused review

---

## STRIDE Categories with Examples

| Category | What It Means | Common Examples |
|----------|--------------|-----------------|
| **Spoofing** | Claiming an identity that is not yours | Forged auth tokens, session hijacking, IP spoofing, claiming another user's ID |
| **Tampering** | Modifying data or code without authorization | Modified request body, SQL injection, parameter manipulation, file tampering |
| **Repudiation** | Denying an action without ability to disprove it | Missing audit logs, no request signing, anonymous destructive actions |
| **Information Disclosure** | Exposing data to unauthorised parties | Verbose error messages, directory listing, debug endpoints in production, over-fetching API responses |
| **Denial of Service** | Making a system unavailable | Unbounded database queries, missing rate limits, resource exhaustion, ReDoS in regex |
| **Elevation of Privilege** | Gaining permissions not granted | IDOR on resource IDs, role manipulation via request params, JWT claim tampering, mass assignment |

### Per-Category Design Questions

- **Spoofing:** How does the system verify the caller's identity at each trust boundary?
- **Tampering:** What validates that data has not been modified in transit or at rest?
- **Repudiation:** Is every sensitive action logged with enough context to reconstruct it forensically?
- **Information Disclosure:** Does each response return only the minimum data needed?
- **DoS:** Are all unbounded operations (queries, loops, file reads) protected by limits?
- **EoP:** Is every privileged action checked against the authenticated user's actual permissions?

---

## DREAD Scoring Rubric

Score each threat 0–10 across five dimensions. Total ÷ 5 = severity score.

| Dimension | 0 (Low) | 5 (Medium) | 10 (High) |
|-----------|---------|-----------|----------|
| **Damage** | Minor inconvenience, no data loss | Partial data loss, service degradation | Full data breach, system compromise |
| **Reproducibility** | Requires rare conditions | Reproducible with effort | Trivially reproducible every time |
| **Exploitability** | Requires deep expertise and physical access | Exploitable with intermediate skill | Script-kiddie level, automated tools exist |
| **Affected Users** | Single user, no customer data | Subset of users | All users or all data |
| **Discoverability** | Requires source code access | Discoverable by testing | Publicly known or visible in UI/docs |

**Priority thresholds:** Score 8–10 → Critical (fix before release) | 6–8 → High (fix this sprint) | 4–6 → Medium (fix next sprint) | 0–4 → Low (backlog)

---

## Trust Boundary Mapping Template

Enumerate all locations where data or control crosses a trust boundary. Controls must exist at every boundary.

```markdown
## Trust Boundary Map: [System Name]

### Boundary 1: External Users → API Layer
- Entry: HTTPS endpoints at /api/*
- Authentication: JWT bearer token
- Controls: Rate limiting, input validation, WAF
- Threats: Spoofing (forged tokens), Tampering (request body), DoS (unbounded requests)

### Boundary 2: API Layer → Internal Services
- Entry: Internal RPC / message queue
- Authentication: mTLS or service account token
- Controls: Network policy, service identity verification
- Threats: Spoofing (compromised service), Tampering (message manipulation)

### Boundary 3: Internal Services → Database
- Entry: Connection pool
- Authentication: Database credentials from secrets manager
- Controls: Least-privilege DB user, parameterised queries only
- Threats: Tampering (injection), Information Disclosure (over-fetching)

### Boundary 4: System → Third-Party Integrations
- Entry: Outbound HTTP calls to [service names]
- Authentication: API keys stored in secrets manager
- Controls: Allowlist of outbound hosts, timeout limits, circuit breaker
- Threats: SSRF, Information Disclosure (credential leakage in logs)
```

---

## Attack Surface Checklist

Audit each entry point for applicable STRIDE threats.

**Public Entry Points**
- [ ] All public HTTP endpoints (list them)
- [ ] WebSocket connections
- [ ] File upload endpoints
- [ ] Redirect / callback URL parameters
- [ ] OAuth redirect URIs

**Privileged Entry Points**
- [ ] Admin interfaces (separate from user-facing API?)
- [ ] Internal service-to-service APIs
- [ ] Scheduled jobs and background workers

**Data Entry Points**
- [ ] Deserialization of untrusted data (JSON, XML, binary)
- [ ] Parsed file formats (CSV, PDF, images)
- [ ] Environment variables and config files at startup

**Output / Disclosure Points**
- [ ] Error messages and stack traces
- [ ] API responses (minimum data principle)
- [ ] Log output (no credentials, no PII)

---

## Anti-Patterns

| Anti-Pattern | Why It Fails |
|-------------|-------------|
| **Security Theater** | Adding a WAF without fixing the underlying vulnerability — attackers bypass WAFs via application logic |
| **Checkbox Compliance** | Passing a compliance audit without reducing actual risk; compliance frameworks lag behind real threats |
| **"We're Internal Only"** | Assuming internal network = trusted; lateral movement after any breach renders this false |
| **Trusting Client-Side Validation** | Browser-side checks are UI courtesy, not security; all validation must be re-done server-side |
| **Threat Modeling After Launch** | Finding threats post-deployment means expensive code changes; threat model during design phase |

---

## Related Resources

- [OWASP Threat Modeling Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Threat_Modeling_Cheat_Sheet.html)
- [Microsoft STRIDE Threat Model](https://learn.microsoft.com/en-us/azure/security/develop/threat-modeling-tool-threats)
- Related skills: `skill_get("web-security")`
