# Time-Free Language Guide

**Quick Reference for Writing Agent Templates**

## Core Principle

**Agents should NEVER promise or estimate time durations. Focus on dependencies, priorities, and completion criteria instead.**

---

## Before/After Examples

### Planning & Task Breakdown

❌ **Wrong:**
```markdown
## Implementation Timeline
- Week 1: Database setup
- Week 2: API development
- Week 3: Frontend integration
- Week 4: Testing
Expected completion: 1 month
```

✅ **Right:**
```markdown
## Implementation Sequence

### Phase 1: Foundation
Prerequisites: None
- Database schema design
- Initial migrations
Ready when: Schema deployed, tests pass

### Phase 2: API Layer
Prerequisites: Phase 1 complete
- REST endpoints
- Authentication integration
Ready when: API tests pass, documentation complete

### Phase 3: Frontend Integration
Prerequisites: Phase 2 complete
- Connect UI to API
- State management
Ready when: E2E tests pass

### Phase 4: Verification
Prerequisites: Phase 3 complete
- Load testing
- Security review
Ready when: All quality gates pass
```

---

### Incident Response & Severity

❌ **Wrong:**
```markdown
| Severity | Description | Response Time |
|----------|-------------|---------------|
| P1 | Complete outage | < 1 hour |
| P2 | Major feature broken | < 4 hours |
| P3 | Minor issue | < 1 day |
```

✅ **Right:**
```markdown
| Severity | Description | Expected Action |
|----------|-------------|-----------------|
| P1 | Complete outage | Immediate response, all hands |
| P2 | Major feature broken | Dedicated incident response |
| P3 | Minor issue | Standard workflow |
| P4 | Low impact | Backlog prioritization |
```

Or even better:
```markdown
| Priority | Impact | Response Pattern |
|----------|--------|------------------|
| P1 | System unavailable | Incident commander assigned, stakeholder notification, rollback evaluation |
| P2 | Major degradation | Root cause investigation, fix prioritization, workaround if available |
| P3 | Minor degradation | Normal fix workflow, scheduled deployment |
| P4 | Cosmetic/minor | Backlog, batch with other fixes |
```

---

### Roadmaps & Feature Planning

❌ **Wrong:**
```markdown
## Q2 Roadmap
- March: User authentication
- April: Payment integration
- May: Mobile app launch
- June: Analytics dashboard
```

✅ **Right:**
```markdown
## Feature Sequence

### Tier 1: Core Platform
Dependencies: None
- User authentication system
- Basic profile management
Enables: Tier 2 features requiring user identity

### Tier 2: Monetization
Dependencies: Tier 1 (user authentication)
- Payment gateway integration
- Subscription management
Enables: Revenue generation

### Tier 3: Extended Experience
Dependencies: Tier 1 (user base)
- Mobile application
- Cross-platform sync
Enables: Broader user access

### Tier 4: Intelligence
Dependencies: Tier 1 (user data)
- Analytics dashboard
- Usage insights
Enables: Data-driven decisions
```

---

### User Requests & Discovery

❌ **Wrong:**
```markdown
## Discovery Questions
- What's your timeline for this project?
- When do you need this delivered?
- How long do you have?
- What's your deadline?
```

✅ **Right:**
```markdown
## Discovery Questions
- What's driving the need for this?
- What happens if this isn't available?
- What other work depends on this?
- What would make this successful?
- What's the minimum viable version?
```

---

### Process Documentation

❌ **Wrong:**
```markdown
## Development Process
1. Planning (1 week)
2. Development (2-3 weeks)
3. Testing (1 week)
4. Deployment (2 days)
Total: 4-5 weeks
```

✅ **Right:**
```markdown
## Development Process

### Step 1: Requirements & Design
Activities:
- Gather requirements
- Create technical design
- Security review
Exit criteria:
- Acceptance criteria defined
- Technical approach approved
- Security concerns addressed

### Step 2: Implementation
Activities:
- Feature development
- Unit testing
- Code review
Exit criteria:
- All acceptance criteria met
- Tests passing
- Code review approved

### Step 3: Integration & Testing
Activities:
- Integration testing
- E2E testing
- Performance validation
Exit criteria:
- All tests passing
- Performance acceptable
- Security scan clean

### Step 4: Deployment
Activities:
- Staging validation
- Production deployment
- Smoke testing
Exit criteria:
- Staging validation complete
- Production rollout successful
- Monitoring shows healthy state
```

---

## Vocabulary Substitutions

| Instead of | Use |
|------------|-----|
| Timeline | Sequence, Dependencies, Plan |
| Schedule | Plan, Order, Approach |
| Deadline | Completion criteria, Ready state |
| Due date | Target milestone, Completion goal |
| ETA | Status, Progress, Next steps |
| Delivery date | Ready when, Done when |
| Duration | Scope, Effort level |
| Timeframe | Phasing, Sequencing |
| Sprint | Iteration, Increment, Batch |
| Quarter (Q1, Q2) | Phase, Stage, Tier |
| Week 1, Month 1 | Phase 1, First iteration |
| ASAP | High priority, Critical |
| Soon | Next, Upcoming, Prioritized |
| Eventually | Later phase, Lower priority |
| Quick | Simple, Straightforward |
| Long-term | Future, Extended, Advanced |

---

## Pattern Library

### Dependency-Based Planning

```markdown
Prerequisites: [What must be done first]
Activities: [What gets done]
Enables: [What this unlocks]
Ready when: [Completion criteria]
```

### Priority-Based Ordering

```markdown
Priority: High/Medium/Low
Impact: [Business value]
Effort: [Complexity indicator]
Dependencies: [What blocks this]
```

### Scope-Based Phasing

```markdown
## Minimal (MVP)
[Core features only]

## Enhanced
[Additional capabilities]
Prerequisites: Minimal complete

## Advanced
[Nice-to-have features]
Prerequisites: Enhanced complete
```

### Criteria-Based Completion

```markdown
Done when:
- [ ] All acceptance criteria met
- [ ] Tests passing
- [ ] Documentation complete
- [ ] Security review approved
- [ ] Stakeholder sign-off received
```

---

## Edge Cases & Exceptions

### ✅ ALLOWED: System Characteristics

These describe inherent properties, not promises:

```markdown
- Fast query response (<100ms)
- Database backup every 24 hours
- Cache TTL: 7 days
- Session timeout: 30 minutes
- Unit tests execute in milliseconds
- E2E tests are slower but provide high confidence
```

### ✅ ALLOWED: Process Documentation

In SECURITY.md, CONFIGURATION.md, etc.:

```markdown
## Security Response Timeline
- Initial response: Within 48 hours
- Fix timeline: Depends on severity
```

### ✅ ALLOWED: Infrastructure Specs

```markdown
- Retention period: 90 days
- Backup frequency: Daily
- Log rotation: Weekly
```

### ❌ VIOLATION: Work Estimates

Even when asked directly:

```markdown
User: "How long will this take?"
Agent: "Based on the scope, this breaks down into 3 phases:
        Phase 1: Database (2 weeks)   ← VIOLATION
        Phase 2: API (3 weeks)         ← VIOLATION
```

Instead:
```markdown
Agent: "I can break this down by dependencies:

        Phase 1: Foundation
        - Database schema
        - Authentication
        Dependencies: None
        Complexity: Medium

        Phase 2: Integration
        - API endpoints
        - Frontend connection
        Dependencies: Phase 1
        Complexity: High

        The critical path is Phase 1 → Phase 2.
        Would you like me to identify risks or unknowns?"
```

---

## Common Pitfalls

### 1. Disguised Time Estimates

❌ "This is a quick fix" → Implies fast/short
❌ "This will take effort" → Vague but time-coded
❌ "Short-term vs long-term" → Time-based categorization

✅ "This is straightforward" → Complexity, not duration
✅ "This has high complexity" → Scope, not time
✅ "Immediate vs future" → Priority, not time

### 2. Comparative Timing

❌ "Faster than the previous approach"
❌ "This usually takes longer"
❌ "Quicker to implement"

✅ "Simpler than the previous approach"
✅ "This has higher complexity"
✅ "More straightforward to implement"

### 3. Urgency Language

❌ "ASAP" or "Urgent"
❌ "As soon as possible"
❌ "Rush this"

✅ "High priority"
✅ "Critical blocker"
✅ "Prioritize this"

---

## Self-Check Questions

Before committing agent changes, ask:

1. **Does this output make any time promises?**
   - Direct: "2 weeks", "by Friday"
   - Indirect: "soon", "quickly", "long-term"

2. **Could a user interpret this as a commitment?**
   - "Response Time: < 1 hour" → Yes, violation
   - "High priority response" → No, describes approach

3. **Is time used to describe system behavior?**
   - "Cache TTL: 7 days" → Yes, acceptable
   - "Complete in 7 days" → No, violation

4. **Does the output use dependencies or dates?**
   - "After authentication is complete" → Dependencies ✅
   - "Week 2: After week 1" → Calendar dates ❌

---

## Tools & Verification

### Pre-Commit Check
```bash
# Installed at .git/hooks/pre-commit
# Automatically scans staged agent files
```

### Manual Scan
```bash
# Scan specific file
./scripts/audit-time-language.sh --file .claude/agents/ta.md

# Full codebase scan
./scripts/audit-time-language.sh --report
```

### CI Pipeline
Runs automatically on all PRs modifying:
- `.claude/agents/**/*.md`
- `.claude/commands/**/*.md`
- `templates/**/*.md`

---

## Getting Help

**Unsure if something is a violation?**
1. Check this guide's examples
2. Run `./scripts/audit-time-language.sh`
3. Review `docs/qa/time-estimate-audit-report.md`
4. Ask in PR review

**Found a violation that should be allowed?**
1. Document why it's acceptable
2. Add to "Edge Cases & Exceptions" section
3. Update audit script exclusion patterns

---

## Quick Decision Tree

```
Does it reference time units?
├─ Yes → Is it a system spec (TTL, cache, SLA)?
│  ├─ Yes → ALLOWED (document in spec)
│  └─ No → VIOLATION (rewrite)
└─ No → Does it imply duration or urgency?
   ├─ Yes → VIOLATION (use priority/complexity)
   └─ No → ALLOWED
```

---

**Remember:** Focus on WHAT needs to happen and WHY, in what ORDER, with what DEPENDENCIES. Never promise WHEN.
