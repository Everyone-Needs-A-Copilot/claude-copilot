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

## Copy Patterns Quick Reference

| Pattern | Structure | Example |
|---------|-----------|---------|
| Error | [What happened] + [How to fix] | "Email format looks wrong. Try: name@example.com" |
| Button | Action verb + object | "Save changes", "Create project", "Send message" |
| Empty state | [What] + [Why empty] + [Action] | "No projects yet. Create your first one to get started." |
| Success | [Confirmation] + [Next step] | "Changes saved. View your updated profile." |

## Readability Engineering

- Target grade 6–8 reading level (Flesch-Kincaid)
- Sentences: <20 words average
- Paragraphs: <3 sentences for UI copy
- Active voice for all actions
- One idea per sentence

## Anti-Generic Rules

- NEVER use jargon the user wouldn't use in conversation
- NEVER write error messages that blame the user ("You entered an invalid email")
- NEVER be clever at the expense of clarity
- NEVER use passive voice in action-oriented copy
- NEVER write more than 2 sentences for a UI message
- NEVER use vague labels: "Click here", "OK", "Submit" — name the action

**Self-Critique:** "Would MailChimp's content team approve? Is the tone right for this moment? Could I say this more simply? Is the button label an action verb?"
