---
name: call-summary
description: Process call notes or a transcript — extract action items, draft follow-up email, generate internal summary. Use when pasting rough notes or a transcript after a discovery, demo, or negotiation call, drafting a customer follow-up, logging the activity for your CRM, or capturing objections and next steps for your team.
argument-hint: "<call notes or transcript>"
---

# /call-summary

Process call notes or a transcript to extract action items, draft follow-up communications, and update records.

## Usage

```
/call-summary <notes or transcript>
```

Process these call notes: $ARGUMENTS

If a file is referenced: @$1

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                      CALL SUMMARY                                │
├─────────────────────────────────────────────────────────────────┤
│  STANDALONE (always works)                                       │
│  ✓ Paste call notes or transcript                               │
│  ✓ Extract key discussion points and decisions                  │
│  ✓ Identify action items with owners and due dates              │
│  ✓ Surface objections, concerns, and open questions             │
│  ✓ Draft customer-facing follow-up email                        │
│  ✓ Generate internal summary for your team                      │
├─────────────────────────────────────────────────────────────────┤
│  SUPERCHARGED (when you connect your tools)                      │
│  + Transcripts: Pull recording via Fireflies CLI                │
│  + CRM: Update opportunity, log activity, create tasks          │
│  + Email: Send follow-up directly from draft                    │
│  + Calendar: Link to meeting, pull attendee context             │
└─────────────────────────────────────────────────────────────────┘
```

---

## What I Need From You

**Option 1: Paste your notes**
Just paste whatever you have — bullet points, rough notes, stream of consciousness. I'll structure it.

**Option 2: Paste a transcript**
If you have a full transcript from your video conferencing tool (e.g. Zoom, Teams) or conversation intelligence tool (e.g. Gong, Fireflies), paste it. I'll extract the key moments.

**Option 3: Describe the call**
Tell me what happened: "Had a discovery call with Acme Corp. Met with their VP Eng and CTO. They're evaluating us vs Competitor X. Main concern is integration timeline."

---

## Output

### Internal Summary
```markdown
## Call Summary: [Company] — [Date]

**Attendees:** [Names and titles]
**Call Type:** [Discovery / Demo / Negotiation / Check-in]
**Duration:** [If known]

### Key Discussion Points
1. [Topic] — [What was discussed, decisions made]
2. [Topic] — [Summary]

### Customer Priorities
- [Priority 1 they expressed]
- [Priority 2]

### Objections / Concerns Raised
- [Concern] — [How you addressed it / status]

### Competitive Intel
- [Any competitor mentions, what was said]

### Action Items
| Owner | Action | Due |
|-------|--------|-----|
| [You] | [Task] | [Date] |
| [Customer] | [Task] | [Date] |

### Next Steps
- [Agreed next step with timeline]

### Deal Impact
- [How this call affects the opportunity — stage change, risk, acceleration]
```

### Customer Follow-Up Email
```
Subject: [Meeting recap + next steps]

Hi [Name],

Thank you for taking the time to meet today...

[Key points discussed]

[Commitments you made]

[Clear next step with timeline]

Best,
[You]
```

---

## Email Style Guidelines

When drafting customer-facing emails:

1. **Be concise but informative** — Get to the point quickly. Customers are busy.
2. **No markdown formatting** — Don't use asterisks, bold, or other markdown syntax. Write in plain text that looks natural in any email client.
3. **Use simple structure** — Short paragraphs, line breaks between sections. No headers or bullet formatting unless the customer's email client will render it.
4. **Keep it scannable** — If listing items, use plain dashes or numbers, not fancy formatting.

**Good:**
```
Here's what we discussed:
- Quote for 20 seats at $480/seat/year
- W9 and supplier onboarding docs
- Point of contact for the contract
```

**Bad:**
```
**What You Need from Us:**
- Quote for 20 seats at $480/seat/year
```

---

## If Connectors Available

**Transcripts connected (Fireflies via cli-copilot):**
- If the user gives a transcript or meeting ID, run:
    `copilot fireflies get <transcript_id>`
  and parse the returned `sentences` array for speaker text and the `summary` field for
  action items and overview. If `copilot` is unavailable or the command errors,
  fall back to the standalone branch above — ask the user to paste the transcript directly.
- To find a transcript by meeting name or date, first run:
    `copilot fireflies list --limit 25`
  and search the returned titles for a match, then fetch the ID.

**CRM connected (NocoDB via cli-copilot):**
- Run `copilot crm clients list --search "<company>"` to look up the account/client record.
- Offer to log the call as an activity row and update the opportunity stage.
- If `copilot crm` is unavailable, prompt the user to update their CRM manually.

**Email connected:**
- Offer to create a draft email from the follow-up template.
- Or send directly if the user approves.

---

## Tips

1. **More detail = better output** — Even rough notes help. "They seemed concerned about X" is useful context.
2. **Name the attendees** — Helps me structure the summary and assign action items.
3. **Flag what matters** — If something was important, tell me: "The big thing was..."
4. **Tell me the deal stage** — Helps me tailor the follow-up tone and next steps.
