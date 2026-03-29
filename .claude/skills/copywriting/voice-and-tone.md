---
skill_name: voice-and-tone
skill_category: copywriting
description: Voice definition, tone matrix by situation, and readability engineering for UX copy
allowed_tools: [Read, Grep, Glob, Edit, Write]
token_estimate: 1200
version: 1.0
last_updated: 2026-03-29
owner: Claude Copilot
status: active
tags: [copywriting, voice, tone, ux-writing, readability, content]
trigger_files: ["**/copy/**", "**/content/**", "**/i18n/**", "**/locales/**"]
trigger_keywords: [voice, tone, copy, microcopy, ux-writing, content-strategy, readability]
quality_keywords: [anti-pattern, clarity, readability, active-voice, jargon]
---

# Voice and Tone

Voice definition, tone matrix by situation, and readability engineering for UX copy that serves users rather than the business.

## Purpose

- Define a consistent product voice that sounds like a person, not a corporation
- Adjust tone to match the user's emotional state in each situation
- Apply readability rules that lower cognitive load
- Write microcopy patterns that guide users to success

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

Adjust tone to the user's emotional state. Voice stays constant; tone adapts.

| Situation | User Emotion | Tone Qualities | Example Copy |
|-----------|-------------|---------------|--------------|
| **Success** | Pleased, relieved | Warm, brief, forward-looking | "Payment sent. Your recipient will be notified." |
| **Error** | Frustrated, confused | Calm, specific, solution-focused | "Card declined. Check the card number and try again." |
| **Warning** | Cautious, uncertain | Direct, non-alarmist, actionable | "Your session expires in 5 minutes. Save your work." |
| **Onboarding** | Curious, slightly anxious | Encouraging, simple, step-focused | "Let's set up your account. It only takes two steps." |
| **Empty state** | Neutral, expectant | Helpful, motivating, clear next action | "No projects yet. Create your first one to get started." |
| **Loading** | Impatient | Honest, grounding, time-aware | "Loading your report…" (add time context if >3s) |
| **Destructive action** | Hesitant, cautious | Precise, consequence-clear, no alarm | "This will permanently delete all files in this folder." |
| **Upgrade prompt** | Skeptical | Value-led, non-pushy, honest | "Get unlimited exports. Upgrade to Pro." |
| **Help text** | Uncertain | Concise, example-driven | "Use your full legal name as it appears on your ID." |
| **Confirmation** | Seeking reassurance | Specific, action-named, scannable | "Delete 3 files? This cannot be undone." |

---

## Readability Rules

| Rule | Standard |
|------|---------|
| **Reading level** | Grade 6–8 (Flesch-Kincaid) — most adults read at grade 7 in a task context |
| **Sentence length** | Average < 20 words; no sentence > 30 words |
| **Voice** | Active voice for all actions and instructions |
| **Density** | One idea per sentence |
| **Negatives** | No double negatives ("not unable to") |
| **Nouns** | Concrete nouns over abstract ones ("your files" not "your content assets") |

**Test your copy:**
- Read aloud — if you stumble, rewrite
- Remove every word that does not change the meaning
- Replace every passive voice construction with active

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

## Anti-Patterns

| Anti-Pattern | Example | Fix |
|-------------|---------|-----|
| **Corporate speak** | "Leverage our best-in-class platform" | "Use [product] to [specific outcome]" |
| **Blame language** | "You entered an incorrect password" | "That password doesn't match" |
| **Jargon** | "Authenticate your credentials" | "Sign in" |
| **Clever over clear** | "Oops! Looks like something went sideways" | "Something went wrong. Try again." |
| **Walls of text in UI** | Three-paragraph explanation inside a modal | One sentence + a help link |
| **Vague actions** | "Click here", "Learn more" | "View pricing", "Read the security guide" |

---

## Related Resources

- [Nielsen Norman Group — UX Writing](https://www.nngroup.com/topic/writing/)
- [Hemingway App](https://hemingwayapp.com/) — readability scoring
- [Mailchimp Voice and Tone](https://styleguide.mailchimp.com/voice-and-tone/) — industry reference
- Related skills: `skill_get("aesthetic-directions")`
