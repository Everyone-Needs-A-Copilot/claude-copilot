---
name: voice-tone
description: >-
  MailChimp Voice & Tone framework for UX copy, microcopy, error messages, and
  interface text — calibrates tone to user emotional state and context. Covers
  the four-quadrant tone map, plain-language rules, and anti-patterns for
  corporate or condescending copy. Use proactively when writing error messages,
  button labels, help text, onboarding flows, empty states, success
  confirmations, destructive action warnings, or any user-facing copy in product
  UI, or when reviewing copy for tone consistency.
version: 1.0.0
source: derived from .claude/agents/_archive/cw.md (2026-04-22)
when_to_use:
  - Writing error messages, button labels, or help text
  - Onboarding flows and empty states
  - Success confirmations and destructive action warnings
  - Any user-facing copy in product UI
  - Reviewing copy for tone consistency
---

# MailChimp Voice & Tone Framework

**Voice** = constant personality (who we are). **Tone** = situational modulation (how we adapt to context).

Voice stays consistent. Tone shifts with user emotion and situation.

---

## Voice Definition Template

Voice is consistent — it does not change. Tone changes by situation.

```markdown
## [Product Name] Voice

We are [quality], but not [negative extreme].

Examples:
- We are **confident**, but not arrogant.
- We are **clear**, but not simplistic.
- We are **warm**, but not sycophantic.
- We are **direct**, but not blunt.
- We are **expert**, but not technical.

### Voice in Practice

| We say...               | We don't say...          |
|-------------------------|--------------------------|
| "Something went wrong"  | "An error has occurred"  |
| "Check your inbox"      | "A message has been sent to your registered email address" |
| "Delete account"        | "Terminate user profile" |
| "You're all caught up"  | "No unread notifications exist at this time" |
```

---

## Tone Matrix

Map user situation to the correct tone before writing. Wrong tone in high-stakes moments (errors, destructive actions) damages trust.

| Situation | User Emotion | Tone | Example |
|-----------|-------------|------|---------|
| Success | Accomplished | Warm, celebratory | "You're all set! Your changes are live." |
| Error | Frustrated | Calm, helpful | "Something went wrong. Here's what to try." |
| Onboarding | Uncertain | Encouraging, clear | "Let's get you started. This takes about 2 minutes." |
| Destructive action | Cautious | Serious, specific | "This will permanently delete 3 projects. This can't be undone." |
| Empty state | Lost | Guiding, optimistic | "No results yet. Try adjusting your filters." |
| Loading/waiting | Impatient | Reassuring, brief | "Almost there..." |
| Warning | Cautious, uncertain | Direct, non-alarmist, actionable | "Your session expires in 5 minutes. Save your work." |
| Help text | Uncertain | Concise, example-driven | "Use your full legal name as it appears on your ID." |
| Confirmation | Seeking reassurance | Specific, action-named, scannable | "Delete 3 files? This cannot be undone." |
| Upgrade prompt | Skeptical | Value-led, non-pushy, honest | "Get unlimited exports. Upgrade to Pro." |

---

## Copy Patterns Quick Reference

| Pattern | Structure | Example |
|---------|-----------|---------|
| Error | [What happened] + [How to fix] | "Email format looks wrong. Try: name@example.com" |
| Button | Action verb + object | "Save changes", "Create project", "Send message" |
| Empty state | [What] + [Why empty] + [Action] | "No projects yet. Create your first one to get started." |
| Success | [Confirmation] + [Next step] | "Changes saved. View your updated profile." |

---

## Microcopy Patterns

### Button Labels

Active verb + object. Describe the action, not the outcome.

| Bad | Good | Why |
|-----|------|-----|
| Submit | Save changes | "Submit" describes the mechanism; "Save changes" describes the result |
| OK | Got it | "OK" is ambiguous; "Got it" confirms comprehension |
| Yes | Delete account | "Yes" doesn't say what will happen |
| Continue | Next: Review order | Tells the user what's coming next |

### Error Messages

What happened + how to fix it. Never blame the user.

| Bad | Good |
|-----|------|
| Invalid input | Email must contain an @ symbol |
| Error 500 | Something went wrong on our end. Refresh the page or try again in a minute. |
| Password incorrect | Wrong password. [Reset your password] |

### Empty States

What the space is for + why it's empty + one clear action.

```
No teammates yet.
Invite people to collaborate on this project.
[Invite teammates]
```

### Confirmation Dialogs

State the specific consequence + use the action as the button name.

```
Delete "Q3 Report.pdf"?
This file will be permanently removed. You cannot undo this action.

[Cancel]  [Delete file]
```

### Placeholder Text

Show an example of the expected format. Never use placeholders as a substitute for labels.

| Bad | Good |
|-----|------|
| Enter your name | Jane Smith |
| Phone number | +1 (555) 000-0000 |
| Enter search query | Search by name or email |

### Tooltip Text

One sentence. Completes the UI element — does not repeat the label.

```
Label: "API Rate Limit"
Tooltip (Bad): "This is your API rate limit."
Tooltip (Good): "Maximum requests per minute. Contact support to increase your limit."
```

### Progress Indicators

What's happening now + what to expect.

```
"Uploading 3 of 5 files…"    (not just a spinner)
"Processing your order…"      (not "Loading")
"Almost done — finalising your export."
```

### Permission Requests

Why you need it + what happens if the user declines.

```
"Allow notifications
Get updates when your team comments or assigns you a task.
You can change this in Settings anytime."
```

### Success Messages

Confirmation + next logical step.

```
"Password updated.
All other sessions have been signed out for security."
```

### Form Labels

Noun phrase, not a question. Label floats — it should not disappear.

| Bad | Good |
|-----|------|
| What is your email? | Email address |
| Enter your date of birth | Date of birth |

---

## Readability Engineering

- Target grade 6–8 reading level (Flesch-Kincaid)
- Sentences: <20 words average
- Paragraphs: <3 sentences for UI copy
- Active voice for all actions
- One idea per sentence

**Test your copy:**
- Read aloud — if you stumble, rewrite
- Remove every word that does not change the meaning
- Replace every passive voice construction with active

---

## Anti-Patterns

| Anti-Pattern | Example | Fix |
|-------------|---------|-----|
| **Corporate speak** | "Leverage our best-in-class platform" | "Use [product] to [specific outcome]" |
| **Blame language** | "You entered an incorrect password" | "That password doesn't match" |
| **Jargon** | "Authenticate your credentials" | "Sign in" |
| **Clever over clear** | "Oops! Looks like something went sideways" | "Something went wrong. Try again." |
| **Walls of text in UI** | Three-paragraph explanation inside a modal | One sentence + a help link |
| **Vague actions** | "Click here", "Learn more" | "View pricing", "Read the security guide" |

## Anti-Generic Rules

- NEVER use jargon the user wouldn't use in conversation
- NEVER write error messages that blame the user ("You entered an invalid email")
- NEVER be clever at the expense of clarity
- NEVER use passive voice in action-oriented copy
- NEVER write more than 2 sentences for a UI message
- NEVER use vague labels: "Click here", "OK", "Submit" — name the action

**Self-Critique:** "Would MailChimp's content team approve? Is the tone right for this moment? Could I say this more simply? Is the button label an action verb?"

---

## Related Resources

- [Nielsen Norman Group — UX Writing](https://www.nngroup.com/topic/writing/)
- [Hemingway App](https://hemingwayapp.com/) — readability scoring
- [Mailchimp Voice and Tone](https://styleguide.mailchimp.com/voice-and-tone/) — industry reference
- Related skills: `cc skill get aesthetic-directions`
