---
skill_name: design-heuristics
skill_category: design
description: Rams principles, Nielsen heuristics, Three Lenses evaluation, and senior thinking frameworks
allowed_tools: [Read, Edit, Write, Glob, Grep]
token_estimate: 2000
version: 1.0
last_updated: 2026-03-08
owner: Claude Copilot
status: active
tags: [design, heuristics, evaluation, critique, anti-pattern, best-practice]
related_skills: [ux-patterns, design-patterns]
trigger_files: ["**/*.css", "**/*.tsx", "**/*.jsx", "**/design/**"]
trigger_keywords: [design-review, design-critique, heuristic-evaluation, design-quality, usability-review]
quality_keywords: [anti-pattern, pattern, validation, best-practice, heuristic]
---

# Design Heuristics

Evaluation frameworks for rigorous design critique. Use these to evaluate work before shipping, not after.

## Purpose

- Provide structured evaluation rubrics (not vibes)
- Distinguish senior from junior design thinking
- Identify common design anti-patterns with fixes
- Enable self-critique before peer review

---

## Rams' 10 Principles — Evaluation Rubric

| # | Principle | Ask Yourself | Pass | Fail |
|---|-----------|-------------|------|------|
| 1 | **Innovative** | Does this explore new possibilities or just copy patterns? | Introduces at least one novel interaction or visual approach | Pure template reproduction |
| 2 | **Useful** | Does every element serve the user's goal? | All elements traceable to user needs | Decorative elements with no function |
| 3 | **Aesthetic** | Is the visual design intentional and cohesive? | Named aesthetic direction, consistent application | "Clean and modern" without specifics |
| 4 | **Understandable** | Can a new user grasp this without instructions? | Self-evident UI, progressive disclosure | Requires tutorial or manual |
| 5 | **Unobtrusive** | Does the design serve content, not itself? | Content is hero, chrome is invisible | Design competes with content |
| 6 | **Honest** | Does it promise only what it delivers? | Accurate affordances, no dark patterns | Misleading buttons, hidden costs |
| 7 | **Long-lasting** | Will this feel dated in 6 months? | Based on principles, not trends | Relies on current trend (glassmorphism everywhere) |
| 8 | **Thorough** | Is every detail considered? | All states, edge cases, error paths designed | Only happy path designed |
| 9 | **Environmentally friendly** | Is it efficient with resources? | Optimized assets, minimal HTTP requests, lean code | Bloated, wasteful, over-engineered |
| 10 | **Minimal** | Is anything here unnecessary? | Every element justified | Elements that can be removed without loss |

**Scoring:** Count passes. 8+ = ship it. 6-7 = iterate. Below 6 = rethink approach.

---

## Nielsen's 10 Usability Heuristics — Checklist

| # | Heuristic | Common Violations | How to Detect |
|---|-----------|-------------------|---------------|
| 1 | **Visibility of system status** | No loading indicators, silent failures, no progress feedback | Trigger every action — does the user know what's happening? |
| 2 | **Match between system and real world** | Technical jargon in UI, unfamiliar icons, developer-facing error messages | Read all copy aloud — would a non-technical user understand? |
| 3 | **User control and freedom** | No undo, no cancel, no back button, trapped in modal flows | Try to exit every flow mid-way — can you? |
| 4 | **Consistency and standards** | Same action, different buttons; same icon, different meanings | Catalog all interactive patterns — are they consistent? |
| 5 | **Error prevention** | No validation until submit, easy mis-clicks, no confirmation for destructive actions | Try to make mistakes — does the system prevent them? |
| 6 | **Recognition rather than recall** | Hidden options, empty search, no recent items, no autocomplete | Can you complete tasks without remembering anything? |
| 7 | **Flexibility and efficiency** | No keyboard shortcuts, no bulk actions, no shortcuts for power users | Complete the same task 10 times — is there a faster way? |
| 8 | **Aesthetic and minimalist design** | Cluttered screens, competing CTAs, information overload | Cover each element — if removed, would users miss it? |
| 9 | **Help users recognize and recover from errors** | Generic "Error" messages, no recovery action, unclear next steps | Trigger every error — does the message explain what happened AND what to do? |
| 10 | **Help and documentation** | No tooltips, no onboarding, no contextual help | Can a new user complete key tasks without external help? |

---

## Three Lenses Evaluation

### Desirability (Would users choose this?)

| Question | Evidence Required |
|----------|-------------------|
| Does this solve a real user pain point? | User research, support tickets, analytics data |
| Would users choose this over alternatives? | Competitive analysis, unique value proposition |
| Does the emotional experience match the brand? | Journey emotional mapping, tone consistency |

### Feasibility (Can we build this?)

| Question | Evidence Required |
|----------|-------------------|
| Do we have the technical capability? | Stack assessment, team skills review |
| Can we build this within reasonable complexity? | Architecture review, dependency analysis |
| Does it integrate with existing systems? | API compatibility, data model fit |

### Viability (Does this make business sense?)

| Question | Evidence Required |
|----------|-------------------|
| Does this align with business goals? | OKR mapping, strategy alignment |
| Can we sustain this long-term? | Maintenance cost, operational requirements |
| Does the value justify the investment? | ROI estimate, opportunity cost analysis |

**All three must pass.** A beautiful, feasible design that doesn't make business sense fails. A viable, desirable design that can't be built fails. A feasible, viable design nobody wants fails.

---

## Senior vs Junior Thinking

| Dimension | Junior Approach | Senior Approach |
|-----------|-----------------|-----------------|
| **Scope** | Designs the screen | Designs the system |
| **Principles** | Follows rules | Knows when to break rules (and why) |
| **Feedback** | Takes it personally | Uses it as design fuel |
| **Decisions** | "I like this" | "This works because [principle]" |
| **Collaboration** | Presents finished work | Involves stakeholders in process |
| **Problem framing** | Solves the stated problem | Questions whether it's the right problem |
| **Rationale** | "It looks good" | "It communicates [X] because [Y]" |
| **Systems thinking** | Designs components | Designs relationships between components |
| **Constraints** | Sees limitations | Sees creative opportunities |
| **Output** | One solution | Multiple options with tradeoffs |

---

## 10 Design Anti-Patterns

| # | Anti-Pattern | Symptom | Fix |
|---|-------------|---------|-----|
| 1 | **Assumption-Driven Design** | No user research cited, "users want..." without evidence | Ground every decision in research, data, or analogous cases |
| 2 | **Feature Creep** | Every edge case gets a UI element, cluttered interface | Prioritize ruthlessly, use progressive disclosure |
| 3 | **Inconsistent Patterns** | Same action looks different in different places | Create pattern library, audit for consistency |
| 4 | **Accessibility Afterthought** | WCAG compliance bolted on at the end | Design accessible from the start, test continuously |
| 5 | **Mobile-as-Shrink** | Desktop design squished onto mobile | Design mobile-first, add complexity for larger screens |
| 6 | **Dark Patterns** | Tricks users into unintended actions | Apply the "newspaper test" — would you be embarrassed if reported? |
| 7 | **Information Overload** | Everything visible at once, no hierarchy | Progressive disclosure, clear visual hierarchy |
| 8 | **Generic Copywriting** | "Submit", "Error", "Welcome to our platform" | Name every action specifically, write helpful error messages |
| 9 | **Ignoring Edge Cases** | Only happy path designed, errors crash gracefully | Design empty, error, loading, and partial states first |
| 10 | **Desktop-Only Thinking** | No touch targets, hover-dependent interactions, fixed widths | Test on mobile devices, use responsive patterns |

---

## Validation Checklist

### Before Storing Work Product
- [ ] Scored 8+ on Rams' Principles
- [ ] All 10 Nielsen Heuristics addressed (no violations)
- [ ] All Three Lenses pass (Desirable + Feasible + Viable)
- [ ] No anti-patterns present
- [ ] Rationale given for every major design decision (not "it looks nice")
- [ ] Multiple concepts considered with tradeoffs documented
- [ ] Senior thinking patterns applied (systems, not screens)
