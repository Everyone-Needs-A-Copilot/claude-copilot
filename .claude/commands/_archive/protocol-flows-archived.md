<!-- Archived 2026-10-29 by consolidation pass A8 (gap plan). Evidence base: October 2026 Claude Code transcripts (2,384 session files), not post-change data. Reason: these flows had zero October sessions where the assistant emitted their markers. To restore, move the section back into .claude/commands/protocol.md at its original position (Flow F and D before Flow B/E in the flow list, the orchestration and Knowledge sections where named), and restore the routing rows. -->

# Archived protocol flows

## Archived: Flow F: Critique

### Flow F: Critique (OPT-IN — not the default, and deliberately so)

**Detection:** Never automatic. Reached only when the user asks for it: `/protocol --critique <request>`, or wording like "explore options", "give me alternatives", "I don't know what this should be yet".

**Shape:** three candidates in parallel → mutual critique → synthesis.

```
sd, uxd, ind          each produce a DIFFERENT candidate direction, in parallel,
                      without seeing the others
      ↓
uids, uid, ta, qa     each critiques ALL THREE from its own lens — no handoff,
                      no elaboration, only "what breaks here and why"
      ↓
Feature Filter        SOUL.md Section 5's five gates, applied to each candidate
                      rather than to one, so the gates SELECT instead of approve
      ↓
synthesis             one direction, grafting what the runners-up got right;
                      state what was taken from each and what was dropped
      ↓
me                    implementation
```

**Checkpoints:** After the critique round, before synthesis. That is the moment the user's judgement is worth most — three live options with their weaknesses named, rather than one direction already elaborated four stages deep.

**Why this exists as an alternative.** Flow A is a waterfall with human gates, and a pipeline's error compounds: if `sd` frames the journey wrongly, every downstream specialist elaborates the wrong frame with rising confidence and rising cost, and nothing revisits. The checkpoints are supposed to catch that, but a checkpoint reviews the stage that just ran, not the framing three stages back.

Same agents, different topology. Plausibly cheaper too — three shallow passes plus a synthesis costs less than six deep sequential ones with a full handoff document between each — though that is a prediction, not a measurement.

**Why it is NOT the default.** No evidence supports it over Flow A. None. Flow A is what this framework has always done and what every result in `copilot-bench` describes. Making an unevidenced re-architecture the default would be exactly the mistake this framework's own Honesty Test exists to prevent: claiming better output with no data for it.

So it ships as an opt-in, alongside a way to find out. Paired against Flow A on identical work in `copilot-bench`, the comparison is: which produces the direction the user leaves alone? That is `cc survival` and blind scoring, not token counts — a cheaper wrong answer is not a better one.

**Two things to watch, stated up front so a favourable result is not over-read:**
- Three parallel candidates cost three framings. If they converge on near-identical directions, the divergence was theatre and the flow is paying triple for one candidate. Say so when it happens.
- Critique is easier than creation. A round where every lens finds fault with every candidate and nothing is chosen has produced sophistication, not a decision. The synthesis step is mandatory for that reason, and it must name a winner.

**Unknowns still apply.** Every specialist in this flow emits its `Unknowns:` line, and a genuine contradiction in the brief escalates as a `QUESTION:` block before three candidates are built on top of it. Divergent exploration is not a substitute for asking; a wrong brief produces three wrong candidates.

---

---

## Archived: Flow D: Clarification

### Flow D: Clarification

**Detection:** User input is ambiguous - could be experience, technical, or defect work.

**Ambiguous Keywords:**
```
improve, enhance, update, change, modify, revise, adjust
better, faster, cleaner, simpler, easier, more, less
```

**Behavior:** Ask user which flow they intend before routing.

**Example:**
```
User: /protocol improve the dashboard

[PROTOCOL: CLARIFYING | Action: ASKING]

I detected an ambiguous request: "improve the dashboard"

What type of improvement are you looking for?

1. User experience (redesign, new features, better flows) → Experience Flow
2. Technical (performance, code quality, architecture) → Technical Flow
3. Bug fix (something is broken) → Defect Flow
4. Not sure, help me decide

Please select [1-4] or describe in more detail.
```

After user clarifies, route to appropriate flow.

---

---

## Archived: Orchestration Flow: Clarification (Flow D)

### Orchestration Flow: Clarification (Flow D)

```
1. User: /protocol improve dashboard
2. Main Session: Detect ambiguous intent
3. Main Session: Show clarification request
   [PROTOCOL: CLARIFYING | Action: RESPONDING]

   I detected an ambiguous request: "improve dashboard"

   Recommended: <flow> because <reason>. Routing there now; say "technical" or "bug" to switch.
```

---

## Archived: Skip Warning Pattern (main-session copy; the same pattern is kept under Handling User Responses)

### Skip Warning Pattern

When user chooses to skip a stage:

```
⚠️ Skipping [stage name] means you'll proceed without [what they miss].

For example, skipping visual design means:
- No design tokens or style guide
- Implementation will lack visual consistency
- You'll need to add design later via: /protocol add visual design to [feature]

Do you want to proceed? (yes to skip, no to return)

[If yes: Continue to next stage]
[If no: Return to checkpoint options]
```

---

## Archived: Knowledge Status Check (Pull-Based)

## Knowledge Status Check (Pull-Based)

Before presenting the protocol acknowledgment, check knowledge status:

### Check Knowledge Configuration

Check the REAL configured knowledge repos (`CC_KNOWLEDGE_REPOS`, exported by `cc env`) -- never the machine template path (`~/.claude/knowledge/`), which is not a member of that list on a correctly onboarded machine and reports a false negative for anyone whose knowledge repos live elsewhere (the normal case):

```bash
eval "$(cc env)"
if [ -n "$CC_KNOWLEDGE_REPOS" ]; then echo "KNOWLEDGE_CONFIGURED"; else echo "NO_KNOWLEDGE"; fi
```

**Decision Matrix:**

| Status | User Intent | Action |
|--------|-------------|--------|
| KNOWLEDGE_CONFIGURED | Any | Proceed normally (knowledge available) |
| NO_KNOWLEDGE | Experience-first features | Offer knowledge setup contextually |
| NO_KNOWLEDGE | Technical/Defect work | Proceed without mention |
| NO_KNOWLEDGE | Agent runs `cc skill select` for optional context | Selection still runs against project/machine skills only; report "Knowledge tier unconfigured; optional context limited to project and machine skills." Never block. |

### When to Offer Knowledge Setup

**Only offer when ALL conditions are true:**
1. No knowledge configured (`NO_KNOWLEDGE`)
2. User is building experience-first features (Flow A keywords detected)
3. Keywords suggest company/product/brand relevance (e.g., "branding", "product page", "about us", "company info")

**Contextual prompt (include in acknowledgment if applicable):**

```
Protocol active. [Constitution: Active/Not Found]

💡 **Knowledge Tip:** You're building features that could benefit from shared knowledge (company info, voice guidelines, product details). Run `/knowledge-copilot` to set up a knowledge repository.

Ready for your request.
```

**When NOT to offer:**
- Defect flows (bug fixes don't need company knowledge)
- Technical flows (refactors don't need company knowledge)
- User has already been offered this session
- Keywords don't suggest knowledge relevance

### Pull-Based Philosophy

**NEVER force or require knowledge setup.** The framework works without it. Knowledge is an enhancement that:
- Provides company context to agents
- Enables consistent voice/branding
- Shares product information

Offer when relevant. Never block work.

---

---

## Rationale moved out of instructions

Audit of protocol.md, me.md and qa.md on 2026-10-29 found no commit hash, ADR citation or incident-dated justification in the kept text; the only date, the `(2026-10-29)` on the Done Block heading, is the rule's own date and stays. The only justification prose was Flow F's "Why this exists" and "Why it is NOT the default" paragraphs (copilot-bench and Honesty Test references), which are archived above with the flow.

