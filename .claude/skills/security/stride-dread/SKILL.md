---
name: stride-dread
description: STRIDE threat enumeration (prose judgment) + deterministic DREAD severity scoring (executable script)
version: 2.0.0
source: derived from .claude/agents/_archive/sec.md (2026-04-22); L3 scorer added 2026-05-20
when_to_use:
  - Reviewing authentication, authorization, or session management
  - Designing APIs that handle user data or PII
  - Reviewing cryptography, secrets management, or key storage
  - Performing threat modeling on new architecture
  - Security-critical code review (auth, crypto, data handling)
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash
---

# STRIDE + DREAD Security Framework

Use this skill for structured threat identification and severity scoring. Apply before code review, not after.

STRIDE enumeration is prose judgment — the model reasons through each category. DREAD scoring is deterministic arithmetic — the script computes it exactly and consistently. Never re-derive DREAD scores by hand; always run the scorer.

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

Rate each identified threat 1–10 on each of the five DREAD dimensions. The script computes the per-finding average and assigns a severity band.

| Key | Dimension | 1 | 5 | 10 |
|-----|-----------|---|---|----|
| D   | Damage potential | Minimal | User data exposed | Mass compromise |
| R   | Reproducibility | Requires specific state | Usually reproducible | Always reproducible |
| E   | Exploitability | Expert + physical access | Authenticated user | Anyone, unauthenticated |
| A   | Affected users | Single user | Subset of users | All users |
| D2  | Discoverability | Obscure internals | Documented behavior | Visible in source/network |

**Band thresholds (documented in script, not guessed):**
- 9.0–10.0: Critical — block deployment
- 7.0–8.9: High — fix in current cycle
- 4.0–6.9: Medium — fix next cycle
- 0.0–3.9: Low — track, accept risk

## Invocation — DREAD Scorer (L3 Script)

After enumerating STRIDE threats, assemble findings as a JSON array and run the scorer. Consume its **output only** — the script source never enters context.

**Format each finding:**
```json
[
  {
    "title": "Short description of the threat",
    "D": 8,
    "R": 7,
    "E": 6,
    "A": 9,
    "D2": 5
  }
]
```

**Run via Bash (file argument):**
```bash
python .claude/skills/security/stride-dread/scripts/dread_score.py findings.json
```

**Run via Bash (stdin):**
```bash
echo '<json array>' | python .claude/skills/security/stride-dread/scripts/dread_score.py -
```

**The script outputs:**
1. A ranked JSON object with `findings` (score + band appended) and a `summary` of band counts.
2. A human-readable markdown table sorted by score descending.

**Error handling:** The script exits non-zero with a clear error message to stderr on invalid dimensions (out of 1-10 range), malformed JSON, or missing fields. Fix the input and re-run — never manually patch the score.

**What the agent does with the output:**
1. Read the markdown table to identify highest-priority findings.
2. Lead remediation recommendations with Critical/High items.
3. Reference the JSON summary counts when giving an executive overview.

## Analysis Process

1. **Map trust boundaries** — Identify where data crosses trust zones (browser → server, service → DB, internal → external)
2. **Enumerate entry points** — All inputs: HTTP params, headers, cookies, file uploads, webhooks, queues
3. **Classify threats (STRIDE)** — For each entry point × each STRIDE category, answer the question
4. **Assemble findings JSON** — Each threat becomes one object: title + D/R/E/A/D2 scores
5. **Run the scorer** — `python .claude/skills/security/stride-dread/scripts/dread_score.py findings.json`
6. **Remediate by rank** — Address Critical/High findings first; do not remediate in order of discovery

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
- NEVER rate severity without running the DREAD scorer — gut feel is not a methodology
- NEVER re-derive DREAD scores manually — inconsistency is the failure mode the script prevents
- NEVER recommend "add a WAF" as a fix — fix the code
- NEVER approve code that handles secrets without reviewing the full lifecycle
- NEVER skip Repudiation — logging and audit trails are security requirements
- NEVER assume input is safe — validate and sanitize at every trust boundary

**Self-Critique:** "Can I classify every finding under STRIDE? Did I run the scorer (not eyeball it)? Would a pentester find something I missed in 10 minutes of black-box testing?"
