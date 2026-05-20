---
name: premium-interaction-craft
description: Elite interaction patterns — scroll choreography, spring physics, micro-timing, text reveals, magnetic elements, page transitions
version: 1.0.0
tags: [design, interaction, animation, gsap, spring-physics, scroll, motion, premium]
when_to_use:
  - Implementing scroll-driven choreography with GSAP ScrollTrigger
  - Applying spring physics to user-initiated drag, toggle, or swipe interactions
  - Selecting precise timing durations from the elite micro-timing scale
  - Building text reveal effects or magnetic/tilt interactions
  - Engineering page transitions with shared element morphing
---

# Premium Interaction Craft

Elite interaction patterns used by top agencies (AKQA, Huge, Fantasy) to create interactions that feel alive, responsive, and intentional.

## Purpose

- Provide production-ready patterns for scroll choreography, spring physics, and micro-timing
- Define the timing scales used by elite design teams
- Give concrete implementation references for text reveals, magnetic elements, and page transitions
- Identify anti-patterns that signal amateur animation work

---

## 1. Scroll-Driven Choreography

**GSAP ScrollTrigger pattern:**
```js
gsap.to(element, {
  scrollTrigger: {
    trigger: element,
    start: "top 80%",
    end: "bottom 20%",
    scrub: 0.5,  // 0.5 = half-second catch-up lag (organic feel)
    pin: true,   // locks element during scroll-linked animation
    pinSpacing: true  // adds spacing to prevent content jump
  },
  y: -100,
  opacity: 1
});
```

**Staggered reveals:**
- Delay per element: 0.1s
- Y-translation: 30px (subtle, not dramatic)
- Easing: `power2.out`
- Trigger: when element enters 80% from top of viewport

**CSS scroll-timeline (progressive enhancement):**
```css
@supports (animation-timeline: scroll()) {
  .reveal {
    animation: fade-up linear;
    animation-timeline: scroll();
    animation-range: entry 0% entry 30%;
  }
}
/* GSAP fallback for unsupported browsers */
```

**Scroll-linked opacity:**
Element fades 0→1 as it traverses the viewport center. Use `scrub: true` for perfect 1:1 tracking.

**Section-based narrative:**
Each viewport-height section = one story beat. Pin for scroll-locked transitions between beats.

---

## 2. Spring Physics for Organic Motion

**When to use springs vs duration:**
- ALWAYS use springs for user-initiated interactions: drag, swipe, toggle, pull-to-refresh
- Use duration for system animations: loading states, auto-transitions, scheduled sequences

**Spring config profiles:**

| Profile | Tension | Friction | Mass | Feel |
|---------|---------|----------|------|------|
| Snappy | 300 | 20 | 1 | Quick, responsive |
| Smooth | 170 | 26 | 1 | Standard, balanced |
| Gentle | 120 | 14 | 1 | Soft, floating |
| Heavy | 170 | 26 | 3 | Weighty, deliberate |
| Bouncy | 200 | 10 | 1 | Playful, elastic |

**React Spring implementation:**
```jsx
const spring = useSpring({
  transform: isOpen ? 'scale(1)' : 'scale(0.95)',
  config: { tension: 300, friction: 20, mass: 1 }  // Snappy profile
});
```

**Framer Motion implementation:**
```jsx
<motion.div
  animate={{ x: 0 }}
  transition={{ type: "spring", stiffness: 300, damping: 20 }}
/>
```

---

## 3. Micro-Timing Precision

The timing scale elite agencies use:

| Window | Duration | Use Case | Easing |
|--------|----------|----------|--------|
| Instant | 0–80ms | Checkbox, radio, toggle state | step or linear |
| Micro | 80–120ms | Hover highlight, focus ring | ease-out |
| Fast | 120–200ms | Button press, tab switch, tooltip | ease-out |
| Standard | 200–350ms | Dropdown, accordion, card flip | ease-out or spring |
| Slow | 350–500ms | Modal open, drawer slide, page transition | ease-in-out or spring |
| Narrative | 500ms+ | Hero entrance, scroll story beat | custom bezier |

**Core rule:** User-initiated = faster (user expects immediate response). System-initiated = can be slower (user is observing, not waiting).

Define as CSS custom properties for system-wide consistency:
```css
:root {
  --duration-instant: 80ms;
  --duration-micro: 100ms;
  --duration-fast: 150ms;
  --duration-standard: 250ms;
  --duration-slow: 400ms;
}
```

---

## 4. Text Reveal Patterns

**Timing scales by unit:**
- Character stagger: 0.02–0.04s delay per character (use lower end for long text)
- Word stagger: 0.06–0.1s delay per word
- Line stagger: 0.1–0.15s delay per line

**Mask-based reveal (recommended for premium feel):**
```css
.line-wrapper {
  overflow: hidden;  /* clip mask */
}
.line {
  transform: translateY(100%);
  animation: reveal 0.6s cubic-bezier(0.16, 1, 0.3, 1) forwards;
}
@keyframes reveal {
  to { transform: translateY(0); }
}
```

**Variable font weight morphing:**
```css
@keyframes weight-morph {
  from { font-variation-settings: 'wght' 300; }
  to   { font-variation-settings: 'wght' 700; }
}
```
Animate weight 300→700 during entrance. Creates cinematic emphasis.

**DOM splitting tools:**
- SplitType: lightweight, no GSAP dependency
- GSAP SplitText: full-featured plugin
- CSS word-spacing animation: for simple per-word effects

---

## 5. Magnetic & Responsive Elements

Track mouse position relative to element center and apply a subtle pull:

```js
element.addEventListener('mousemove', (e) => {
  const rect = element.getBoundingClientRect();
  const centerX = rect.left + rect.width / 2;
  const centerY = rect.top + rect.height / 2;
  const deltaX = (e.clientX - centerX) * 0.15;  // 15% follow ratio
  const deltaY = (e.clientY - centerY) * 0.15;

  requestAnimationFrame(() => {
    element.style.transform = `translate(${deltaX}px, ${deltaY}px)`;
  });
});

element.addEventListener('mouseleave', () => {
  // Spring reset — react-spring or CSS transition handles overshoot
  element.style.transform = 'translate(0, 0)';
});
```

**Max displacement:** 8–15px (beyond this feels unstable, not magnetic)

**Tilt effect:**
```js
const rotateX = (deltaY / (rect.height / 2)) * 10;  // max 10deg
const rotateY = (deltaX / (rect.width / 2)) * -10;
element.style.transform =
  `perspective(800px) rotateX(${rotateX}deg) rotateY(${rotateY}deg)`;
```

**Performance:** Always use `requestAnimationFrame`. Set `will-change: transform` on elements that animate frequently.

---

## 6. Page Transition Patterns

**View Transitions API (modern approach):**
```js
document.startViewTransition(() => {
  // DOM update happens here (navigate, swap content)
  updateDOM();
});
```

**Shared element morphing:**
```css
/* Old page */
.hero-image { view-transition-name: hero; }

/* New page — same name, browser interpolates position/size */
.product-image { view-transition-name: hero; }
```

**Cinematic crossfade:**
1. Stagger exit: current elements fade out 0.05s apart
2. Route change / DOM swap
3. Stagger enter: new elements fade in 0.05s apart

**Clip-path wipe:**
```css
@keyframes wipe-in {
  from { clip-path: circle(0% at 50% 50%); }
  to   { clip-path: circle(150% at 50% 50%); }
}
```

**AJAX + animation pattern:**
1. Fetch new content (in background)
2. Animate old content out
3. Swap DOM
4. Animate new content in
This prevents blank-screen flash during route transitions.

---

## Anti-Patterns

| Anti-Pattern | Why It Fails |
|---|---|
| Scroll-jacking without orientation cues | User loses sense of position and progress |
| Motion without purpose | If removing it changes nothing, it shouldn't exist |
| Bouncing/wobbling on page load | Dated since 2018, signals amateur work |
| Parallax ignoring prefers-reduced-motion | Causes motion sickness in sensitive users |
| Over-animated forms | Typing in a field should not trigger visual fireworks |
| Identical easing on every element | Creates robotic, uncanny uniformity |
| UI feedback duration > 500ms | User perceives system as sluggish |
| Animating layout properties (width, height, top, left) | Triggers browser reflow, destroys performance |

---

## Validation Checklist

- [ ] Timing matches the correct window (instant/micro/fast/standard/slow/narrative)
- [ ] User-initiated interactions use spring physics, not duration
- [ ] Scroll animations have orientation cues (progress indicator or pinned context)
- [ ] Text reveals use mask technique (not fade-only)
- [ ] Magnetic elements respect max displacement (8–15px)
- [ ] Page transitions handle back navigation gracefully
- [ ] `prefers-reduced-motion` respected: non-essential motion removed, not just shortened
- [ ] `will-change: transform` applied to frequently-animated elements
- [ ] No layout property animations (use transform + opacity only)
