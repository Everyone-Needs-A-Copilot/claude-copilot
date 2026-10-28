# User Journeys

<!--
FACILITATION GUIDE — Service Designer
======================================
This document maps the end-to-end experience as a moments journey map. We're designing for humans, not screens. The Service Designer has VETO POWER over any decision that harms user experience.

PREREQUISITE: 00-vision.md, JTBD, and at least one interview must be completed.

THE METHOD (moments journey map) — apply all of it:
- One PRIMARY stakeholder. The journey is told from their point of view, starting at their TRIGGER: the circumstance that pushes them to act.
- A PROGRESS STATEMENT for every stakeholder: "When [situation], I want to [progress], so I can [outcome]." plus WHY it matters to them.
- Other stakeholders ENTER and EXIT the primary stakeholder's story at the moments where they participate. Example: in the customer's story, the service provider is who the customer hires to make progress; the product is what the provider hires to make their own progress. They do not get parallel stories on the same map.
- A MOMENT is each action a person takes. Every action carries an expectation. When the experience misses it, that is a STRUGGLING MOMENT. Most moments are benign.
- A circumstance or reality ("not enough clients", "it's tax season") is NOT a struggling moment. It can be the trigger; it is never a struggle.
- Each struggling moment gets a STRESS score 1-10 for the stress it creates when the experience prevents progress (10 = most intense pain), backed by cited evidence (interviews, observation, tickets, data). Unvalidated scores are tagged [Assumption].
- For each struggling moment, map the FORCES for each participating stakeholder: Push, Pull, Anxiety, Habit.
- The MOMENTS THAT MATTER are the highest-stress struggling moments: exactly 3 when the journey has fewer than 12 moments, exactly 5 when it has 12 or more. Highlight them and say why each matters. Stress selects them; frequency and how easy a moment is to fix only decide which to design first.
- Journeys can LOOP: someone who dislikes confrontation quietly quits after a struggling moment, restarts the process elsewhere, and carries the poor experience into the next relationship. Mark the loop.
- All copy is in JTBD language (what they're trying to get done, what they expected, where the experience missed), never internal process language.

STRESS RUBRIC (use the anchors, cite the evidence):
- 1-2: expectation slightly missed; progress continues without a workaround.
- 3-4: noticeable friction; a small workaround, delay or repeat.
- 5-6: progress stalls; they have to chase, redo or find another way.
- 7-8: progress blocked or at risk; they escalate, consider giving up, or lose money, time or face.
- 9-10: progress fails or the relationship ends; they quit, switch, or suffer lasting harm.

CONVERSATION FLOW:
1. Identify the stakeholders, choose the primary one, and name their trigger
2. Write a progress statement for every stakeholder
3. Walk the primary stakeholder's journey moment by moment, noting where others enter and exit
4. Find the struggling moments, score stress with evidence, map forces per stakeholder
5. Select the 3 or 5 moments that matter and mark any loops
6. Map the emotional arc (how they feel at each moment)
7. Define touchpoints (every point of interaction)
8. Map intelligence handoffs (what flows between systems and moments)
9. Capture critical design requirements

QUESTIONS TO ASK:

## Round 1: Stakeholders, Primary, Trigger
- "Who are the different people involved in getting this done?"
- "Whose story is this? Which one person's progress are we designing for first?" (the primary stakeholder)
- "What happened that made them act? What was the moment they decided they had to do something?" (the trigger)
- "Who do they hire to help? What does that person or business hire in turn?"
- "Consider: the primary operator, the reviewer/approver, the admin/configurator, and any secondary beneficiaries"

## Round 2: Progress Statements
For each stakeholder:
- "When [what situation] do they turn to this?"
- "What progress are they trying to make?"
- "So they can do what?"
- "Why does that matter to them?"

## Round 3: Primary Stakeholder's Moments
Walk the journey from the trigger, one action at a time:
- "What do they do first? Then what?"
- "What did they expect to happen when they did that?"
- "Who else is involved at this point? Is this where they come in, or where they drop out?"
- "When do they have their 'aha' moment?"
- "What brings them back? What does ongoing use look like?"
- "Have they been through this before with someone else? How did that end?" (loops)

## Round 4: Struggling Moments, Stress, Forces
For each moment:
- "Did it go the way they expected? If not, what happened instead?"
- Check: is this an action with a missed expectation, or a reality? Realities are triggers, not struggles.
- "How stressful was that, on the scale?" Use the rubric anchors. "What tells us that: a quote, a ticket, a number?"
- "Where might they give up and leave?" "Where could the AI get in the way instead of helping?"
For each struggling moment, for each stakeholder present:
- Push: "What's pushing them away from how it works today?"
- Pull: "What would draw them to a better way?"
- Anxiety: "What worries them about changing?"
- Habit: "What do they keep doing even though it doesn't work?"

## Round 5: Moments That Matter and Loops
- Count the moments. Under 12: pick exactly 3. 12 or more: pick exactly 5.
- "Which struggling moments have the highest stress?" Those are the moments that matter. Do not swap in a lower-stress moment because it is more common or easier to fix.
- "Why does each one matter: what progress does it block, for whom, and what does it cost?"
- If there are fewer struggling moments than you need, the research is not finished: go back to the interviews.
- "Does anyone quit here and start over somewhere else? What do they carry with them?"

## Round 6: Emotional Arc
For each moment, ask:
- "How is the user feeling here? Overwhelmed? Hopeful? Skeptical?"
- "What would make them feel confident at this moment?"
- "What could go wrong emotionally?"

## Round 7: Touchpoints
- "What are ALL the ways a user interacts with this product?"
- "Are there touchpoints outside the product? (Email notifications, calendar reminders, team collaboration)"
- "Which touchpoint has the most impact on their overall experience?"

## Round 8: Intelligence Handoffs
- "What data flows in from outside this product?"
- "What does this product hand off to other tools when a moment completes?"
- "What would break if the handoff failed?"

## Round 9: Critical Design Requirements
- "Looking across the moments that matter first, then the rest, what are the must-have design requirements — the ones that, if missed, the product fails?"
- "For each requirement: Why is it required? What's the success metric?"

SYNTHESIS:
Lead with the progress statements and the trigger. Build the primary stakeholder's journey as a moments table in story order, with other stakeholders entering and exiting. Score every struggling moment with evidence, map forces per stakeholder, and highlight the 3 or 5 moments that matter with why each matters. Mark loops. End with a requirements table derived from the moments that matter. Carry the moments that matter into 40-moments-that-matter.md.
-->

## Progress Statements
<!-- From Rounds 1-2. Primary stakeholder first. -->

**Primary stakeholder:** [Name / role] — the journey is told from their point of view.
**Trigger:** [The circumstance that pushed them to act]

- **[Primary stakeholder]:** When [situation], I want to [progress], so I can [outcome]. **Why:** [deeper motivation]
- **[Stakeholder 2]** (hired by [primary]): When [situation], I want to [progress], so I can [outcome]. **Why:** [motivation]
- **[Product / tool]** (hired by [stakeholder 2]), when it participates: When [situation], I want to [progress], so I can [outcome]. **Why:** [motivation]

## Journey Moments
<!-- From Round 3. One row per action, in story order, starting with the trigger. -->

| # | Moment (action) | Participants | Enters / exits | What they expected | Struggling? | Stress (1-10) | Evidence |
|---|-----------------|--------------|----------------|--------------------|-------------|---------------|----------|
| 1 | [Trigger action] | [Primary] | | | No | – | |
| 2 | | | | | | | |
| 3 | | | | | | | |

**Moments in this journey:** [n] → moments that matter required: [3 if under 12, 5 if 12 or more]

## Struggling Moments
<!-- From Round 4. Only actions where the experience missed an expectation. Realities belong in the trigger, not here. -->

| # | Moment | What they expected | Where the experience missed | Stress (1-10) | Evidence |
|---|--------|--------------------|-----------------------------|---------------|----------|
| | | | | | |

### Forces at Moment [#]: [Moment]
<!-- One table per struggling moment, one column per participating stakeholder -->

| Force | [Primary stakeholder] | [Stakeholder 2] |
|-------|-----------------------|-----------------|
| Push | | |
| Pull | | |
| Anxiety | | |
| Habit | | |

## Moments That Matter
<!-- From Round 5. The highest-stress struggling moments: exactly 3 (under 12 moments) or 5 (12 or more). Detailed in 40-moments-that-matter.md. -->

1. **[Moment]** — stress [n]: [why it matters: progress blocked, for whom, what it costs]
2. **[Moment]** — stress [n]: [why it matters]
3. **[Moment]** — stress [n]: [why it matters]

## Loops
<!-- From Round 5. Where someone quits and restarts, and what they carry forward. -->

- [Moment] → back to [moment]: [what they carry into the next attempt]

## Emotional Arc
<!-- From Round 6: How the user feels at each moment -->

| Moment | Feeling | What Builds Confidence | What Could Go Wrong |
|--------|---------|----------------------|---------------------|
| | | | |

## Touchpoints
<!-- From Round 7: Every interaction point, ranked by impact -->

## Intelligence Handoffs (Ecosystem)
<!-- From Round 8: What flows in, what flows out, what breaks if the handoff fails -->

| Handoff | From → To | What Flows |
|---------|-----------|-----------|
| | | |

## Critical Design Requirements (Summary)
<!-- From Round 9: Must-have requirements derived from the moments that matter first -->

| Requirement | Moment it serves | Why | Success Metric |
|-------------|------------------|-----|----------------|
| | | | |

## Service Blueprint Layers
<!-- Filled in after journey is mapped -->

| Layer | Description |
|-------|-------------|
| **Customer Actions** | |
| **Frontstage** | |
| **Backstage** | |
| **Support Processes** | |

---

**Related:** [JTBD](30-jtbd.md) | [Moments That Matter](40-moments-that-matter.md)
