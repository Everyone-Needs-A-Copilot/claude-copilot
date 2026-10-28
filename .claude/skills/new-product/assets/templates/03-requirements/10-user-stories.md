# User Stories

<!--
FACILITATION GUIDE — Service Designer + UX Designer
=====================================================
User stories translate jobs to be done into actionable requirements.
They are written from the user's perspective and must be testable.

Format: "As a [persona], I want to [action], so that [outcome]."

Each story must include inline acceptance criteria — not just what the
user wants, but how we know the product has delivered it. Stories without
acceptance criteria are not implementation-ready.

Story ID format: US-[Persona Code][Number]
  Assign persona codes based on the personas defined in the journey maps.

PREREQUISITE: JTBD, journey maps, and moments that matter must be
completed.

CONVERSATION FLOW:
1. Map stories to personas (from journey maps)
2. Map stories to jobs (from JTBD)
3. Write acceptance criteria inline for each story
4. Ensure every core capability has at least one story
5. Prioritize stories for initial release
6. Confirm critical view coverage

QUESTIONS TO ASK:

## Round 1: Primary Persona Stories
- "As the primary persona, what do they need to do in the core workflow?"
- "What's the trigger for starting this workflow?"
- "What does successful completion look like — what can they now do?"
- "What's the acceptance criterion? If you wrote a test, what would you check?"

## Round 2: Secondary Persona Stories
- "As each secondary persona, what are their most important interactions?"
- "Where do their needs differ from the primary persona?"
- "What information do they need that the primary persona doesn't?"

## Round 3: Administration Stories
- "Who configures the system? What do they need to set up?"
- "What settings need to be adjustable?"
- "How are things maintained over time?"

## Round 4: Prioritization
- "Which stories are essential for the first version?"
- "Which stories can wait for a later release?"
- "Are there stories that depend on other stories?"
- "Which critical views from the design challenge do these stories cover?
  Are there any views with no story coverage?"

SYNTHESIS:
Present stories grouped by persona, then ordered by priority.
Each story should be small enough to be independently testable.
Mark priority: P0 (must have), P1 (should have), P2 (nice to have).
Each story must have inline acceptance criteria before it is
considered implementation-ready.
End with a Story Summary table and Critical View Coverage map.
-->

## [Primary Persona] Stories

### [Core Workflow] (P0)

**US-[CODE]01:** As a [Primary Persona], when [situation], I want to [action], so that [outcome].

**Acceptance Criteria:**
- [Observable, testable condition 1]
- [Observable, testable condition 2]
- [Performance target if applicable]

---

**US-[CODE]02:** As a [Primary Persona], when [situation], I want to [action], so that [outcome].

**Acceptance Criteria:**
- [Observable, testable condition 1]
- [Observable, testable condition 2]

---

## [Secondary Persona] Stories

### [Their Core Workflow] (P0)

**US-[CODE]01:** As a [Secondary Persona], when [situation], I want to [action], so that [outcome].

**Acceptance Criteria:**
- [Observable, testable condition 1]
- [Observable, testable condition 2]

---

## Admin / Configurator Stories

### System Setup (P0)

**US-A01:** As an Admin, when setting up the system, I want to [configure X], so that [the system works correctly for all users].

**Acceptance Criteria:**
- [Observable, testable condition 1]
- [Observable, testable condition 2]

---

## Story Priority Matrix

| ID | Story | Persona | Priority | Depends On |
|----|-------|---------|----------|------------|
| US-[CODE]01 | [Short description] | [Persona] | P0 | — |
| US-[CODE]02 | [Short description] | [Persona] | P1 | US-[CODE]01 |
| US-A01 | [Short description] | Admin | P0 | — |

## Story Summary

| User Type | P0 Stories | P1 Stories | Total |
|-----------|-----------|-----------|-------|
| [Primary Persona] | | | |
| [Secondary Persona] | | | |
| Admin / Configurator | | | |
| **Total** | | | |
