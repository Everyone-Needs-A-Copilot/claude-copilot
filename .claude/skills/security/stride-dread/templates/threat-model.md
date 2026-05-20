# Threat Model: [Component / Feature Name]

**Review date:** [YYYY-MM-DD]
**Reviewer:** [agent or person]
**Scope:** [One sentence — what is being reviewed]

---

## Trust Boundary Map

| From | To | Data Crossing | Trust Level |
|------|----|---------------|-------------|
| Browser | API Gateway | Auth token, request body | Low → High |
| API Gateway | Auth Service | JWT validation request | High → High |
| API Gateway | Database | Parameterized queries | High → High |
| _(add rows)_ | | | |

---

## Entry Points

| Entry Point | Protocol | Auth Required | Notes |
|-------------|----------|---------------|-------|
| POST /auth/login | HTTPS | No | Credential endpoint |
| GET /api/users/:id | HTTPS | Yes (JWT) | |
| _(add rows)_ | | | |

---

## STRIDE Findings

Complete ALL six categories. Write "None identified" for clean categories — never leave blank.

### Spoofing
- [ ] Can an attacker impersonate a user or service?

Findings:
- _[title] — [brief description]_

### Tampering
- [ ] Can data be modified in transit or at rest?

Findings:
- _[title] — [brief description]_

### Repudiation
- [ ] Can actions be denied without audit trail?

Findings:
- _[title] — [brief description]_

### Information Disclosure
- [ ] Can sensitive data reach unauthorized parties?

Findings:
- _[title] — [brief description]_

### Denial of Service
- [ ] Can availability be degraded or exhausted?

Findings:
- _[title] — [brief description]_

### Elevation of Privilege
- [ ] Can an attacker gain access beyond authorization?

Findings:
- _[title] — [brief description]_

---

## DREAD Scoring Input

Save the following as `findings.json` and run:
```bash
python .claude/skills/security/stride-dread/scripts/dread_score.py findings.json
```

```json
[
  {
    "title": "Example: SQL Injection in login endpoint",
    "D": 9,
    "R": 8,
    "E": 7,
    "A": 10,
    "D2": 6
  }
]
```

---

## DREAD Scorer Output

_(Paste the markdown table output from the scorer here)_

---

## Remediation Plan

Ranked by DREAD score (Critical first).

| # | Finding | Band | Remediation | Owner | Status |
|---|---------|------|-------------|-------|--------|
| 1 | | Critical | | | Open |
| 2 | | High | | | Open |

---

## Secrets Lifecycle Checklist

- [ ] Secrets generated with sufficient entropy
- [ ] Encrypted at rest, not in source control
- [ ] Transmitted only over TLS, not in URLs
- [ ] Rotation possible without downtime
- [ ] Revocation possible immediately if compromised

---

## OWASP Top 10 Coverage

- [ ] A01 Broken Access Control
- [ ] A02 Cryptographic Failures
- [ ] A03 Injection
- [ ] A04 Insecure Design
- [ ] A05 Security Misconfiguration
- [ ] A06 Vulnerable & Outdated Components
- [ ] A07 Identification & Authentication Failures
- [ ] A08 Software & Data Integrity Failures
- [ ] A09 Security Logging & Monitoring Failures
- [ ] A10 Server-Side Request Forgery (SSRF)
