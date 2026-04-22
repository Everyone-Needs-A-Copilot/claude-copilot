---
name: stride-dread
description: STRIDE threat modeling and DREAD severity scoring for security review
version: 1.0.0
source: derived from .claude/agents/_archive/sec.md (2026-04-22)
when_to_use:
  - Reviewing authentication, authorization, or session management
  - Designing APIs that handle user data or PII
  - Reviewing cryptography, secrets management, or key storage
  - Performing threat modeling on new architecture
  - Security-critical code review (auth, crypto, data handling)
---

# STRIDE + DREAD Security Framework

Use this skill for structured threat identification and severity scoring. Apply before code review, not after.

## STRIDE Threat Categories

Enumerate ALL six categories before reviewing code. Never skip categories — absence of a threat is still a finding.

| Category | Question to Answer |
|----------|--------------------|
| **S**poofing | Can an attacker impersonate a user, service, or system component? |
| **T**ampering | Can data be modified in transit, at rest, or in processing? |
| **R**epudiation | Can actions be denied without an audit trail? |
| **I**nformation Disclosure | Can sensitive data leak to unauthorized parties? |
| **D**enial of Service | Can availability be degraded or exhausted? |
| **E**levation of Privilege | Can an attacker gain access beyond their authorization? |

## DREAD Severity Scoring

Rate each identified threat 0–10 on each factor. Total score = sum / 5.

| Factor | Question | 0 | 5 | 10 |
|--------|----------|---|---|----|
| **D**amage potential | How bad if exploited? | Minimal | User data exposed | Mass compromise |
| **R**eproducibility | How reliably reproducible? | Requires specific state | Usually reproducible | Always reproducible |
| **E**xploitability | How much skill/effort required? | Expert + physical access | Authenticated user | Anyone, unauthenticated |
| **A**ffected users | How many users impacted? | Single user | Subset of users | All users |
| **D**iscoverability | How easy to discover? | Obscure internals | Documented behavior | Visible in source/network |

**Score thresholds:**
- 8–10: Critical — block deployment
- 6–7: High — fix in current cycle
- 4–5: Medium — fix next cycle
- 0–3: Low — track, accept risk

## Analysis Process

1. **Map trust boundaries** — Identify where data crosses trust zones (browser → server, service → DB, internal → external)
2. **Enumerate entry points** — All inputs: HTTP params, headers, cookies, file uploads, webhooks, queues
3. **Classify threats (STRIDE)** — For each entry point × each STRIDE category, answer the question
4. **Score severity (DREAD)** — For each identified threat, apply DREAD scoring
5. **Remediate highest scores first** — Don't implement fixes in order of discovery

## OWASP Top 10 Checklist

Cross-reference findings against OWASP Top 10. Any miss here is a gap in the review.

1. Injection (SQL, NoSQL, OS, LDAP)
2. Broken Authentication
3. Sensitive Data Exposure
4. XML External Entities (XXE)
5. Broken Access Control
6. Security Misconfiguration
7. Cross-Site Scripting (XSS)
8. Insecure Deserialization
9. Using Components with Known Vulnerabilities
10. Insufficient Logging & Monitoring

## Secrets Lifecycle Review

For any code handling secrets (API keys, tokens, passwords):
- **Creation:** Is the secret generated with sufficient entropy?
- **Storage:** Encrypted at rest? Not in source control? Not in logs?
- **Transmission:** Only over TLS? Not in URLs or query params?
- **Rotation:** Can it be rotated without downtime?
- **Revocation:** Can it be invalidated immediately if compromised?

If ANY step is missing, flag as High severity minimum.

## Anti-Generic Rules

- NEVER review code without mapping trust boundaries first
- NEVER rate severity without DREAD scoring — gut feel is not a methodology
- NEVER recommend "add a WAF" as a fix — fix the code
- NEVER approve code that handles secrets without reviewing the full lifecycle
- NEVER skip Repudiation — logging and audit trails are security requirements
- NEVER assume input is safe — validate and sanitize at every trust boundary

**Self-Critique:** "Can I classify every finding under STRIDE? Can I score it with DREAD? Would a pentester find something I missed in 10 minutes of black-box testing?"
