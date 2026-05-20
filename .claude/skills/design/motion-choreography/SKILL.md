---
name: motion-choreography
description: Motion as design language — grammar, easing personality, choreography patterns, restraint philosophy, animation principles
version: 1.0.0
tags: [design, motion, animation, choreography, easing, timing, restraint, premium]
when_to_use:
  - Designing multi-element animation sequences or entrance/exit choreography
  - Selecting easing curves with personality for each interaction type
  - Applying restraint principles to avoid over-animation
  - Implementing anticipation and follow-through in UI interactions
  - Auditing animation systems for motion budget and prefers-reduced-motion compliance
---

# Motion Choreography

Motion as a design language. Not decoration — communication. These patterns define how elements enter, behave, and exit as a coherent system.

## Purpose

- Establish motion grammar before implementing individual animations
- Provide a named easing library with personality profiles
- Define choreography patterns for multi-element sequences
- Encode restraint philosophy to prevent over-animation
- Apply classic animation principles to UI context

---

## 1. Motion as Language

Motion has grammar. Learn it before using it.

**Vocabulary:** fade, slide, scale, rotate, morph, spring, stagger, clip, blur

**Syntax:** entrance → interaction → exit. Breaking this sequence disorients users.

**Rhythm:** Consistent timing across a flow creates expectation. Breaking rhythm creates emphasis — use this sparingly and intentionally.

**Tone:**
| Motion Quality | Message Sent |
|---|---|
| Fast + snappy | Energetic, playful, responsive |
| Slow + smooth | Premium, confident, considered |
| Springy | Friendly, organic, alive |
| Abrupt | Urgent, alarming, decisive |

**Silence:** No-motion is a choice. Stillness after movement creates contrast. Not everything should move — the absence of motion is part of the composition.

---

## 2. Choreography Patterns for Multi-Element Sequences

| Pattern | Description | Best For |
|---------|-------------|---------|
| **Cascade** (top-down) | Header → hero → cards → footer. Natural reading order. | Default choice, content pages |
| **Wave** (center-out) | Central element first, radiating outward. | Focus + context reveal |
| **Random** (organic) | Elements enter at varied delays (not uniform). | Creative, editorial, energetic |
| **Reverse cascade** (coordinated exit) | Elements leave in reverse order of entry. | Page transitions, modal close |
| **Shared axis** | Related elements move along the same axis (all slide-left, or all scale-center). | Grouped families, related content |
| **Focal** | Secondary elements animate AFTER primary element settles. | Hero sections, feature showcases |

**Stagger math:**
```
total_stagger = (N − 1) × per_element_delay

Rule: Keep total_stagger < 600ms to avoid tedium
Adjustment: If N > 8, reduce per-element delay proportionally
```

Example: 10 cards, keep total under 600ms → delay = 600 / 9 = ~67ms per element

**Focal choreography sequence:**
1. Primary element enters (full animation, no competition)
2. Primary settles (100ms rest)
3. Secondary elements begin
4. Supporting elements begin (after secondary settles)

---

## 3. Easing as Personality

Custom Bézier curves per interaction type. Never use just `ease` or `ease-in-out` globally.

| Name | Value | Feel | Use For |
|------|-------|------|---------|
| Snappy | `cubic-bezier(0.25, 0.1, 0.25, 1)` | Quick start, smooth end | Button feedback, toggles |
| Gentle | `cubic-bezier(0.16, 1, 0.3, 1)` | Slow start, confident end | Content reveals, fades |
| Elastic | `cubic-bezier(0.68, -0.55, 0.27, 1.55)` | Overshoot + settle | Notifications, badges, playful elements |
| Dramatic | `cubic-bezier(0.7, 0, 0.84, 0)` | Accelerating, commanding | Hero entrances, cinematic moments |
| Smooth | `cubic-bezier(0.4, 0, 0.2, 1)` | Material Design standard | General transitions |
| Sharp | `cubic-bezier(0.4, 0, 0.6, 1)` | Quick, decisive | Exit animations, removals |
| Decelerate | `cubic-bezier(0, 0, 0.2, 1)` | Entering with momentum | Slide-in panels, incoming content |
| Accelerate | `cubic-bezier(0.4, 0, 1, 1)` | Leaving with momentum | Slide-out panels, exiting content |

**Define as CSS custom properties for system-wide consistency:**
```css
:root {
  --ease-snappy:      cubic-bezier(0.25, 0.1, 0.25, 1);
  --ease-gentle:      cubic-bezier(0.16, 1, 0.3, 1);
  --ease-elastic:     cubic-bezier(0.68, -0.55, 0.27, 1.55);
  --ease-dramatic:    cubic-bezier(0.7, 0, 0.84, 0);
  --ease-smooth:      cubic-bezier(0.4, 0, 0.2, 1);
  --ease-sharp:       cubic-bezier(0.4, 0, 0.6, 1);
  --ease-decelerate:  cubic-bezier(0, 0, 0.2, 1);
  --ease-accelerate:  cubic-bezier(0.4, 0, 1, 1);
}
```

**Pairing rule:** Entrance uses `--ease-decelerate` (arrives with momentum). Exit uses `--ease-accelerate` (leaves with purpose). They are not interchangeable.

---

## 4. Anticipation & Follow-Through

Classic animation principles applied to UI. These are what separate alive interactions from mechanical ones.

**Anticipation** — slight preparation before the main action:
- Button: depresses 2px before releasing the click action
- Menu items: shift 4px opposite direction before sliding in
- Creates "coiled spring" energy that makes the resulting action feel powerful

**Follow-through** — overshoot + settle after arrival:
- Elements don't stop dead at their destination — they arrive and breathe
- Spring physics: overshoot by 3–8% then settle to final position over 100–200ms
- CSS approach: add a second keyframe past the target then return

**Squash & stretch** (subtle, not cartoonish):
```css
@keyframes press {
  0%   { transform: scale(1); }
  40%  { transform: scale(0.95); }   /* compress */
  70%  { transform: scale(1.05); }   /* expand */
  100% { transform: scale(1.0); }    /* settle */
}
/* Keep scale range tight: ±5–8% max for UI elements */
```

**Staging** — direct the eye before the action:
1. Dim surrounding elements (opacity 0.6)
2. Highlight target area (subtle glow or brightness increase)
3. THEN animate the primary action
Staging ensures users are looking in the right place before the important thing happens.

**Secondary action** — environment responds to primary:
- Card lifts → shadow deepens + adjacent cards shift 4px apart
- Modal opens → page content scales to 0.98 (depth cue)
- Creates spatial awareness — the world responds to interactions

---

## 5. Restraint Philosophy

This is the most important section. Read it twice.

**The 3-element rule:** Animate the 3 elements that matter, not all 30. More animations do not mean better experience — they mean more noise.

**The purpose test:** If removing an animation changes nothing about user comprehension or emotional response, remove it. Motion must earn its place.

**The invisibility standard:** The best motion is the motion users don't consciously notice but would miss if absent. Like good typography — invisible until it's wrong.

**prefers-reduced-motion — respect it fully:**
```css
@media (prefers-reduced-motion: reduce) {
  /* Remove non-essential motion entirely */
  /* Do NOT just reduce duration — remove the animation */
  .reveal { animation: none; opacity: 1; }
  .slide-in { transform: none; }

  /* KEEP: instant state changes for critical feedback */
  .toggle { transition: background-color 0ms; }
}
```

**Motion budget per view:**
| Type | Limit | Notes |
|------|-------|-------|
| Hero animation | 1 | The primary narrative moment |
| Entrance staggers | 3–5 | Content entering the viewport |
| Micro-feedback | Unlimited | Hover, focus, press states |
| Anything beyond | Requires justification | Ask: does this serve the user? |

**The amateur vs elite signal:**
- Amateur: everything bounces
- Elite: you can't point to what moved, but it felt right

---

## 6. Sound + Motion Integration

When sound enhances rather than intrudes:

| Sound Type | Duration | Character | Trigger |
|---|---|---|---|
| Soft click | 50–100ms | Short, percussive | Button press (confirms registration) |
| Success tone | 200–400ms | Ascending, warm | Positive completion |
| Error tone | 200–300ms | Distinct, not jarring | Alert without alarm |
| Ambient | Continuous | Subtle, atmospheric | Scroll or state (user-controlled) |

**Sync rule:** Sound begins at animation midpoint for maximum perceived responsiveness. Starting at animation start feels delayed; starting at midpoint feels simultaneous.

**Mandatory controls:**
- ALWAYS provide a mute control
- NEVER autoplay sound without user consent
- Sound is opt-in, not opt-out

---

## Anti-Patterns

| Anti-Pattern | Why It Fails |
|---|---|
| Bounce on page load | Dated since 2018; immediately signals amateur work |
| Identical easing curve on every element | Robotic, uncanny uniformity — each interaction type needs its own curve |
| UI feedback duration > 500ms | User perceives system as sluggish and unresponsive |
| Scroll-jacking without clear navigation | User loses sense of position and how much content remains |
| Motion that fights user intent | Element moves away from where user is trying to interact |
| Parallax on critical content | Makes text hard to read; causes nausea in sensitive users |
| "Playful" loading animations past 3 seconds | Delight becomes impatience at the 3-second mark |
| Animating layout properties | width, height, top, left cause reflow; use transform + opacity only |
| Entrance animation identical to exit | Entrances decelerate; exits accelerate — never swap them |
| Sound without mute control | Immediately hostile to users in quiet environments |

---

## Validation Checklist

- [ ] Motion grammar defined: vocabulary, syntax, rhythm, tone declared before implementation
- [ ] Choreography pattern selected and documented (cascade/wave/random/etc.)
- [ ] Named easing curves used (no bare `ease` or `ease-in-out`)
- [ ] Entrance uses `--ease-decelerate`, exit uses `--ease-accelerate`
- [ ] Stagger total under 600ms for any sequence
- [ ] Anticipation present on primary interactive elements
- [ ] Follow-through present on spring-animated elements
- [ ] Secondary actions respond to primary actions
- [ ] Motion budget respected: ≤1 hero, ≤5 staggers per view
- [ ] prefers-reduced-motion removes non-essential motion (not just shortens it)
- [ ] No layout property animations (transform + opacity only)
- [ ] Sound is opt-in with visible mute control
