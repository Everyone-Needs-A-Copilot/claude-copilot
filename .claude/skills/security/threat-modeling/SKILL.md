---
name: threat-modeling
description: STRIDE threat identification with coverage checking (prose judgment) + deterministic STRIDE coverage + DREAD severity scoring (executable script)
version: 2.0.0
source: derived from .claude/skills/security/threat-modeling.md (v1.0); L3 coverage checker added 2026-05-20
when_to_use:
  - Designing or reviewing a new system architecture or API
  - Pre-implementation security review for any feature touching auth, payments, or PII
  - Threat modeling sessions (initial or refresh)
  - Reviewing another team's threat model for completeness
  - Any context where trust boundaries cross multiple services or external parties
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash
---

# Threat Modeling

STRIDE threat identification, attack surface mapping, and deterministic coverage checking.
Use this skill to produce a complete threat model — not just a list of obvious issues.

STRIDE **enumeration** is prose judgment — the model reasons through each category for each trust boundary and entry point. STRIDE **coverage** and optional DREAD scoring are deterministic — the script checks whether every category is represented and computes severity consistently.

Never claim a threat model is complete without running the coverage checker.

## STRIDE Categories

Enumerate ALL six categories for every significant trust boundary. Absence is a finding.

| Letter | Category | Core Question |
|--------|----------|---------------|
| **S** | Spoofing | Can an attacker impersonate a user, service, or system component? |
| **T** | Tampering | Can data be modified in transit, at rest, or during processing? |
| **R** | Repudiation | Can actions be denied without an audit trail? |
| **I** | Information Disclosure | Can sensitive data leak to unauthorized parties? |
| **D** | Denial of Service | Can availability be degraded or exhausted? |
| **E** | Elevation of Privilege | Can an attacker gain access beyond their authorization? |

### Per-Category Design Questions

- **Spoofing:** How does the system verify caller identity at each trust boundary?
- **Tampering:** What validates that data has not been modified in transit or at rest?
- **Repudiation:** Is every sensitive action logged with enough context for forensic reconstruction?
- **Information Disclosure:** Does each response return only the minimum data needed?
- **DoS:** Are all unbounded operations (queries, loops, file reads) protected by limits?
- **EoP:** Is every privileged action checked against the authenticated user's actual permissions?

## STRIDE Tag Reference (for the Coverage Checker)

Use these tags in the `stride` array of each finding:

| Tag | Category | Aliases accepted |
|-----|----------|-----------------|
| `S`  | Spoofing | "Spoofing" |
| `T`  | Tampering | "Tampering" |
| `R2` | Repudiation | "R2", "Rep", "Repudiation" |
| `I`  | Information Disclosure | "I", "Information Disclosure" |
| `D3` | Denial of Service | "D3", "DoS", "Denial of Service" |
| `E`  | Elevation of Privilege | "E", "EoP", "Elevation of Privilege" |

(`R2` and `D3` are used instead of `R`/`D` to avoid colliding with DREAD dimension names.)

## Invocation — STRIDE Coverage Checker (L3 Script)

After enumerating threats, assemble findings as a JSON array and run the checker. Consume its **output only** — the script source never enters context.

**Format each finding (STRIDE only):**
```json
[
  {
    "title": "Unauthenticated admin endpoint accepts commands",
    "stride": ["S", "E"]
  }
]
```

**Format each finding (STRIDE + DREAD scoring):**
```json
[
  {
    "title": "SQL injection in search endpoint",
    "stride": ["T", "I"],
    "D": 9,
    "R": 8,
    "E": 7,
    "A": 10,
    "D2": 6
  }
]
```

**Run via Bash (file argument):**
```bash
python .claude/skills/security/threat-modeling/scripts/stride_coverage.py findings.json
```

**Run via Bash (stdin):**
```bash
echo '<json array>' | python .claude/skills/security/threat-modeling/scripts/stride_coverage.py -
```

**The script outputs:**
1. A JSON object with `findings` (stride_labels + optional score/band), `coverage` (per-category finding list), `gaps` (uncovered categories), and a `summary`.
2. A STRIDE Coverage markdown table showing which categories are covered and which are gaps.
3. (Optional) A DREAD Severity Rankings table if D/R/E/A/D2 dimensions are provided.

**Error handling:** Non-zero exit on invalid input (unknown STRIDE tag, partial DREAD scores, bad JSON). Fix the input and re-run.

**What the agent does with the output:**
1. Check `gaps` — any uncovered STRIDE category is a model deficiency; reason about why it might be N/A before accepting it.
2. Lead remediation recommendations with Critical/High findings (if DREAD scores provided).
3. For each gap: either add findings or document why the category is genuinely not applicable.

## Trust Boundary Mapping

Enumerate all locations where data or control crosses a trust boundary. Controls must exist at every boundary.

```markdown
## Trust Boundary Map: [System Name]

### Boundary 1: External Users → API Layer
- Entry: HTTPS endpoints at /api/*
- Authentication: JWT bearer token
- Controls: Rate limiting, input validation
- STRIDE threats: Spoofing (forged tokens), Tampering (body), DoS (unbounded requests), EoP (IDOR)

### Boundary 2: API Layer → Database
- Entry: Connection pool, parameterized queries
- Authentication: DB credentials from secrets manager
- Controls: Least-privilege DB user, no dynamic SQL
- STRIDE threats: Tampering (injection), Information Disclosure (over-fetching)
```

## Attack Surface Checklist

**Public Entry Points**
- [ ] All public HTTP endpoints
- [ ] WebSocket connections
- [ ] File upload endpoints
- [ ] OAuth / redirect callback parameters

**Privileged Entry Points**
- [ ] Admin interfaces (separate auth path?)
- [ ] Internal service-to-service APIs
- [ ] Scheduled jobs and background workers

**Data Entry Points**
- [ ] Deserialization of untrusted data (JSON, XML, binary)
- [ ] Parsed file formats (CSV, PDF, images)
- [ ] Environment variables and config files at startup

## Anti-Patterns

| Anti-Pattern | Why It Fails |
|-------------|-------------|
| **Threat model after launch** | Finding threats post-deployment means expensive code changes; threat model during design |
| **Skipping Repudiation** | Logging is a security requirement, not an operational nicety |
| **"We're internal only"** | Lateral movement after any breach renders internal = trusted false |
| **WAF as a fix** | WAFs bypass via application logic; fix the code |
| **Checkbox compliance** | Compliance frameworks lag behind real threats; they are a floor, not a ceiling |

## Anti-Generic Rules

- NEVER declare a threat model complete without running the coverage checker
- NEVER skip Repudiation — logging and audit trails are security requirements
- NEVER assume internal network = trusted
- NEVER rate severity by gut feel — use DREAD dimensions if you need a score
- NEVER recommend "add a WAF" as a remediation — fix the code

**Self-Critique:** "Have I tagged every finding with STRIDE categories and run the checker? Did the coverage output show zero gaps, or did I explain each gap? Would a pentester find something in 10 minutes of black-box testing that I missed?"
