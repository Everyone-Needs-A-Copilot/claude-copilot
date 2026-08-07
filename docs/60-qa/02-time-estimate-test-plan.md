# Time Estimate Verification Test Plan

**Version:** 1.0
**Date:** 2025-12-26
**Owner:** @agent-qa

## Overview

This test plan verifies that Claude Copilot agents do NOT produce time-based estimates in their outputs. It covers both automated detection and manual verification scenarios.

---

## Test Strategy

| Level | Focus | Coverage |
|-------|-------|----------|
| **Unit** | Regex patterns detect violations | Pattern accuracy |
| **Integration** | Pre-commit/CI blocks violations | Pipeline integration |
| **E2E** | Agent outputs contain no time estimates | Real usage scenarios |
| **Regression** | Violations don't reappear | Continuous monitoring |

---

## Automated Tests

### AT-01: Pre-Commit Hook Blocks Direct Time Units

**Given:** Agent file with "2 weeks" in output template
**When:** Developer attempts to commit
**Then:** Commit is blocked with violation message

**Test Data:**
```markdown
## Task Breakdown
- Task 1: [Description] - 2 weeks
```

**Expected Output:**
```
❌ Time units found in: .claude/agents/ta.md
Direct time reference: "2 weeks"
COMMIT BLOCKED
```

**Status:** PASS / FAIL

---

### AT-02: Pre-Commit Hook Blocks Timeline Language

**Given:** Agent file with "timeline" in output template
**When:** Developer attempts to commit
**Then:** Commit is blocked

**Test Data:**
```markdown
## Project Plan
| Phase | Timeline | Tasks |
```

**Expected Output:**
```
❌ Planning time language found
COMMIT BLOCKED
```

**Status:** PASS / FAIL

---

### AT-03: Pre-Commit Hook Allows Acceptable Context

**Given:** Agent file with "fast" describing system quality
**When:** Developer attempts to commit
**Then:** Commit is allowed

**Test Data:**
```markdown
## DevOps Principles
- Fast recovery (low MTTR)
- Fast query performance
```

**Expected Output:**
```
✓ No time estimate violations found
```

**Status:** PASS / FAIL

---

### AT-04: CI Pipeline Detects Violations

**Given:** PR with agent file containing "schedule"
**When:** CI pipeline runs
**Then:** Build fails with violation report

**Test Data:** PR modifying `.claude/agents/ta.md` with "project schedule"

**Expected Output:**
```
❌ VIOLATION: Time-based planning language found
CHECK FAILED
```

**Status:** PASS / FAIL

---

### AT-05: Audit Script Generates Report

**Given:** Codebase with known violations
**When:** `./scripts/audit-time-language.sh --report` runs
**Then:** Violations are listed with file locations

**Expected Output:**
```
VIOLATION: Direct time units
File: .claude/agents/do.md
229:| P2 | Major feature broken | < 1 hour |
```

**Status:** PASS / FAIL

---

## Manual E2E Tests

### E2E-01: Tech Architect Task Breakdown (No Time Estimates)

**Scenario:** User requests implementation plan for new feature

**Steps:**
1. User: "I need to add user authentication to the app"
2. Invoke `@agent-ta`
3. Agent produces task breakdown

**Verification:**
```bash
# Search agent output for time violations
grep -E '\b(hours?|days?|weeks?|months?|timeline|schedule)\b' output.txt
```

**Expected Result:** No matches found

**Pass Criteria:**
- [ ] Task breakdown has phases, not timeframes
- [ ] Dependencies are explicit, not date-based
- [ ] No "Week 1", "Month 2" references
- [ ] No "timeline" or "schedule" language

**Status:** PASS / FAIL

---

### E2E-02: DevOps Incident Response (No Time SLAs)

**Scenario:** User reports production outage

**Steps:**
1. User: "Production is down, database connection failing"
2. Invoke `@agent-do`
3. Agent produces incident response plan

**Verification:**
```bash
# Check for time-based SLAs
grep -E '(Response\s+Time|within\s+\d+|< \d+\s+(hour|minute))' output.txt
```

**Expected Result:** No matches found

**Pass Criteria:**
- [ ] Severity levels use priority (P1, P2), not time
- [ ] Actions described by sequence, not duration
- [ ] No "respond within X hours" commitments
- [ ] No "ETA" or "deadline" references

**Status:** PASS / FAIL

---

### E2E-03: Knowledge Copilot Discovery (No Timeline Questions)

**Scenario:** User starts knowledge repository setup

**Steps:**
1. User runs `/knowledge-copilot`
2. `@agent-kc` begins discovery interview
3. Review all questions asked

**Verification:**
```bash
# Check discovery questions
grep -E '\b(timeline|schedule|how\s+long|when)\b' questions.txt
```

**Expected Result:** No timeline-focused questions

**Pass Criteria:**
- [ ] Questions focus on "how" and "what", not "when"
- [ ] No "How long does X take?" questions
- [ ] No "What's your timeline?" questions
- [ ] Process-focused, not duration-focused

**Status:** PASS / FAIL

---

### E2E-04: Service Designer Journey Map (No Phase Timing)

**Scenario:** User requests customer journey mapping

**Steps:**
1. User: "Map the onboarding journey for new users"
2. Invoke `@agent-sd`
3. Agent produces journey map

**Verification:**
```bash
# Check for time-based stages
grep -E 'Phase\s+\d+.*\((Week|Month|Day)' output.txt
```

**Expected Result:** No matches found

**Pass Criteria:**
- [ ] Journey stages named by activity, not duration
- [ ] Touchpoints described by sequence
- [ ] No time estimates for stage completion
- [ ] Focus on user actions, not calendar time

**Status:** PASS / FAIL

---

### E2E-05: QA Test Plan (Acceptable Time Context)

**Scenario:** User requests test strategy

**Steps:**
1. User: "Create a test plan for the API"
2. Invoke `@agent-qa`
3. Agent produces test plan

**Verification:**
```bash
# Verify acceptable time language
grep -E '\b(fast|slow|millisecond)\b' output.txt
# Should find references to test speed characteristics
```

**Expected Result:** Terms like "fast execution" are ALLOWED as test characteristics

**Pass Criteria:**
- [ ] "Fast execution" describing unit tests: ALLOWED
- [ ] "Slow but high confidence" for E2E: ALLOWED
- [ ] "3 days to complete testing": VIOLATION
- [ ] Test speed as quality metric: ALLOWED

**Status:** PASS / FAIL

---

## Edge Case Tests

### EC-01: User Directly Asks About Timing

**Scenario:** User explicitly asks for time estimate

**User Input:**
```
"How long will this feature take to implement?"
```

**Expected Agent Response Pattern:**
```
I can break this down by dependencies and scope:

Phase 1: Foundation (Prerequisites: none)
- [Task list]
- Ready when: [completion criteria]

Phase 2: Integration (Prerequisites: Phase 1 complete)
- [Task list]
- Ready when: [completion criteria]

The actual duration depends on [factors]. Would you like me to
identify the critical path and key dependencies?
```

**Pass Criteria:**
- [ ] Agent reframes to dependency-based breakdown
- [ ] No time duration provided
- [ ] Focuses on scope, not calendar
- [ ] Offers to identify critical path

**Status:** PASS / FAIL

---

### EC-02: Historical Reference (Acceptable)

**Scenario:** Agent references past work

**Acceptable:**
```
"We've addressed similar issues in the past"
"This pattern has worked well previously"
```

**Violation:**
```
"This usually takes 2 weeks"
"Last time this took 3 days"
```

**Pass Criteria:**
- [ ] Past experience referenced qualitatively
- [ ] No historical time estimates provided
- [ ] Pattern recognition without duration claims

**Status:** PASS / FAIL

---

### EC-03: System Performance Metrics (Acceptable)

**Scenario:** Agent discusses infrastructure

**Acceptable:**
```
"Fast query performance (<100ms)"
"Cache TTL: 7 days"
"Database backup every 24 hours"
```

**Violation:**
```
"This will be done in 2 days"
"Deploy within 4 hours"
```

**Pass Criteria:**
- [ ] System specs with time units: ALLOWED
- [ ] Performance SLOs: ALLOWED
- [ ] Work delivery promises: VIOLATION

**Status:** PASS / FAIL

---

### EC-04: Process Documentation (Context-Dependent)

**Scenario:** Agent references documented processes

**Acceptable in SECURITY.md:**
```
Security Response Timeline:
- Critical: Within 7 days
```

**Violation in Agent Output:**
```
## Implementation Timeline
- Phase 1: Week 1
```

**Pass Criteria:**
- [ ] Process docs (SECURITY.md): ALLOWED
- [ ] Agent planning output: VIOLATION
- [ ] Infrastructure specs: ALLOWED
- [ ] User-facing promises: VIOLATION

**Status:** PASS / FAIL

---

## Regression Tests

### RT-01: Previously Fixed Violations Don't Return

**Frequency:** Weekly

**Process:**
1. Run `./scripts/audit-time-language.sh --report`
2. Compare to baseline audit report
3. Verify no new violations in previously clean files

**Pass Criteria:**
- [ ] No violations in `.claude/agents/ta.md` (if previously fixed)
- [ ] No violations in `.claude/agents/sd.md` (if previously fixed)
- [ ] Violation count ≤ baseline

**Status:** PASS / FAIL

---

### RT-02: New Agent Files Follow Standards

**Frequency:** On new agent addition

**Process:**
1. New agent file added to `.claude/agents/`
2. Pre-commit hook runs automatically
3. CI pipeline validates

**Pass Criteria:**
- [ ] Pre-commit hook scans new file
- [ ] CI pipeline includes new file in checks
- [ ] No time estimate violations present

**Status:** PASS / FAIL

---

## Performance Tests

### PT-01: Pre-Commit Hook Performance

**Scenario:** Large commit with multiple agent files

**Test Data:** Commit modifying 5 agent files

**Performance Target:** < 2 seconds

**Measurement:**
```bash
time git commit -m "Test commit"
```

**Pass Criteria:**
- [ ] Hook completes in < 2 seconds
- [ ] No false positives
- [ ] No false negatives

**Status:** PASS / FAIL

---

### PT-02: Audit Script Performance

**Scenario:** Full codebase scan

**Performance Target:** < 10 seconds

**Measurement:**
```bash
time ./scripts/audit-time-language.sh --report
```

**Pass Criteria:**
- [ ] Script completes in < 10 seconds
- [ ] All relevant files scanned
- [ ] Results match manual inspection

**Status:** PASS / FAIL

---

## Test Data Library

### Valid Examples (Should Pass)

**Dependency-based planning:**
```markdown
## Task Breakdown

### Phase 1: Foundation
Prerequisites: None
- Set up database schema
- Create authentication service
Ready when: Tests pass, schema deployed

### Phase 2: Integration
Prerequisites: Phase 1 complete
- Connect frontend to auth service
- Add session management
Ready when: E2E tests pass
```

**Quality attributes:**
```markdown
## Performance Requirements
- Fast query response (<100ms)
- Cache TTL: 7 days
- Slow operations moved to background jobs
```

---

### Invalid Examples (Should Fail)

**Time-based planning:**
```markdown
## Implementation Timeline
- Week 1: Database setup
- Week 2: API development
- Week 3: Frontend integration
```

**Time commitments:**
```markdown
| Severity | Response Time |
|----------|---------------|
| P1 | < 1 hour |
| P2 | < 4 hours |
```

---

## Test Execution Log

| Test ID | Date | Result | Notes |
|---------|------|--------|-------|
| AT-01 | YYYY-MM-DD | PASS/FAIL | |
| AT-02 | YYYY-MM-DD | PASS/FAIL | |
| E2E-01 | YYYY-MM-DD | PASS/FAIL | |

---

## Coverage Goals

| Category | Target | Current | Status |
|----------|--------|---------|--------|
| Automated pattern detection | 100% | TBD | 🔴 |
| Agent file coverage | 100% (12/12) | TBD | 🔴 |
| E2E scenario coverage | 80% | TBD | 🔴 |
| Edge case coverage | 100% | TBD | 🔴 |

---

## Continuous Monitoring

### Daily
- [ ] CI pipeline runs on all PRs
- [ ] Pre-commit hook active for contributors

### Weekly
- [ ] Review any bypassed checks
- [ ] Check for new violation patterns

### Monthly
- [ ] Run full audit script
- [ ] Review edge cases
- [ ] Update test scenarios

### Quarterly
- [ ] Full manual E2E test suite
- [ ] Update audit report
- [ ] Review and refine patterns

---

## Escalation Path

| Finding | Action |
|---------|--------|
| Pattern produces false positive | Update exclusion regex in audit script |
| New violation type discovered | Add pattern to all verification tools |
| Violation in production | Immediate fix + update test coverage |
| User reports time estimate in output | Root cause analysis + new E2E test |

---

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| False positive rate | < 5% | Manual review of blocked commits |
| False negative rate | 0% | Manual codebase inspection |
| Time to detect violation | < 1 minute | CI pipeline duration |
| Coverage of agent files | 100% | Grep audit vs file count |
| Regression rate | 0% | Quarterly audit comparison |

---

**Next Actions:**
1. Execute AT-01 through AT-05 to validate automation
2. Execute E2E-01 through E2E-05 with real agent outputs
3. Document results in execution log
4. Refine patterns based on findings
5. Establish monitoring schedule
