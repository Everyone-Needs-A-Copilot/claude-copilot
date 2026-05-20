---
name: spatial-luminous-design
description: Spatial depth systems, luminosity techniques, glassmorphism, material reference, atmospheric color, mesh gradients
version: 1.0.0
tags: [design, spatial, depth, luminosity, glass, material, atmosphere, gradient, light]
when_to_use:
  - Assigning z-axis layers and shadow depth tokens to interface elements
  - Implementing glassmorphism at the correct tier for context
  - Applying luminosity effects — ambient glow, neon, rim lighting
  - Choosing material surfaces (glass, metal, paper, fabric) as design tokens
  - Building atmospheric color and animated mesh gradients
---

# Spatial & Luminous Design

Depth, light, and material systems that elevate interfaces from flat to three-dimensional. These techniques separate premium products from generic ones.

## Purpose

- Provide a consistent 5-layer spatial model for z-axis depth
- Define luminosity techniques with specific CSS values
- Give production-ready glassmorphism across three tiers
- Reference material surfaces as design tokens
- Guide atmospheric color and mesh gradient usage

---

## 1. Spatial Depth System (5-Layer Model)

Every element belongs to exactly one layer. Elements never skip layers.

| Layer | Z-Index Range | Parallax Speed | Purpose | CSS Techniques |
|-------|--------------|----------------|---------|----------------|
| Background | 0 | 0.3× scroll | Environment, atmosphere | Fixed or slow-scroll gradient, ambient tint |
| Ground | 1–10 | 1× scroll (normal) | Content foundation | Cards, surfaces, main content |
| Floating | 11–100 | 1.05–1.1× scroll | Active elements | Dropdowns, tooltips, selections |
| Overlay | 101–1000 | Fixed | Focused attention | Modals, lightboxes, drawers |
| Foreground | 1001+ | Fixed | Persistent UI | Navigation, FAB, toasts |

**Layer rules:**
- Each layer has a consistent shadow depth token (e.g., `--shadow-ground`, `--shadow-floating`)
- Parallax ratios create natural depth perception — heavier layers move slower
- Background layer anchors the atmosphere; changing it shifts the entire page mood

**Shadow depth tokens:**
```css
:root {
  --shadow-ground:     0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.08);
  --shadow-floating:   0 4px 16px rgba(0,0,0,0.12), 0 2px 4px rgba(0,0,0,0.08);
  --shadow-overlay:    0 20px 60px rgba(0,0,0,0.20), 0 4px 16px rgba(0,0,0,0.12);
  --shadow-foreground: 0 8px 32px rgba(0,0,0,0.24);
}
```

---

## 2. Luminosity Techniques

**Ambient glow** (behind focal elements):
```css
.focal-element {
  box-shadow: 0 0 60px 20px rgba(120, 80, 255, 0.20);
  /* spread: 20–60px | blur: 40–100px | opacity: 15–30% */
  /* color: element's dominant hue */
}
```

**Backlit text** (dark backgrounds):
```css
.hero-heading {
  text-shadow: 0 0 40px rgba(120, 80, 255, 0.30);
  /* Creates ethereal, premium feel — use sparingly */
}
```

**Neon effect (3-layer technique):**
```css
.neon {
  box-shadow:
    0 0 7px  #7850ff,           /* tight glow */
    0 0 20px #7850ff,           /* medium spread */
    0 0 60px rgba(120,80,255,0.3); /* ambient wash */
}
```

**Rim lighting** (overhead light source suggestion):
```css
.dark-card {
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.10);
  /* Simulates light hitting the top edge */
}
```

**Brightness hierarchy rule:**
The brightest element = highest attention priority. Use `filter: brightness()` or direct color lightness to control visual hierarchy intentionally.

---

## 3. Glassmorphism (3 Tiers)

| Tier | Background | Blur | Border | Use Case |
|------|-----------|------|--------|----------|
| Subtle | rgba(255,255,255, 0.05–0.10) | backdrop-filter: blur(8px) | 1px rgba(255,255,255, 0.10) | Floating cards, secondary panels |
| Medium | rgba(255,255,255, 0.15–0.25) | backdrop-filter: blur(16px) | 1px rgba(255,255,255, 0.20) | Navigation, toolbars, active panels |
| Immersive | rgba(255,255,255, 0.30–0.40) | backdrop-filter: blur(24px) | 1px rgba(255,255,255, 0.30) | Modal backgrounds, hero overlays |

**Implementation pattern:**
```css
.glass-medium {
  background: rgba(255, 255, 255, 0.18);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);  /* Safari */
  border: 1px solid rgba(255, 255, 255, 0.20);
  border-radius: var(--radius-lg);
}
```

**Mandatory rules:**
- MUST maintain 4.5:1 text contrast ratio over the blurred background — test on varied backgrounds
- Always add border for edge definition (without it, elements float directionlessly)
- Light source direction must match the elevation system
- Dark glassmorphism: swap white rgba for dark rgba values — do not just invert, redesign

---

## 4. Material Reference Library

| Material | CSS Implementation | Token Name |
|----------|-------------------|------------|
| Glass | `backdrop-filter: blur(Xpx); background: rgba(R,G,B, 0.1–0.3)` | `--surface-glass` |
| Metal | `background: linear-gradient(135deg, hsl(0,0%,22%), hsl(0,0%,18%)); box-shadow: inset 0 1px 0 rgba(255,255,255,0.15)` | `--surface-metal` |
| Paper | `background: var(--color-surface)` + noise overlay pseudo-element at 0.5–1.5% opacity | `--surface-paper` |
| Fabric | `background: repeating-linear-gradient(0deg, transparent, transparent 1px, rgba(0,0,0,0.02) 1px, rgba(0,0,0,0.02) 2px)` | `--surface-fabric` |
| Liquid | Multi-point radial gradients + morphing SVG shapes + slow transform animation (20–40s cycle) | `--surface-liquid` |

**Noise texture (Paper material):**
```css
.paper::after {
  content: '';
  position: absolute;
  inset: 0;
  background-image: url("data:image/svg+xml,...");  /* SVG noise */
  opacity: 0.015;  /* MAX 1.5% — above this reads as dirty, not refined */
  pointer-events: none;
}
```

---

## 5. Atmospheric Color

**Ambient tint:**
Full-page overlay at 2–5% opacity of brand primary. Creates environmental cohesion and brand presence without competing with content.
```css
body::before {
  content: '';
  position: fixed;
  inset: 0;
  background: var(--color-brand-primary);
  opacity: 0.03;
  pointer-events: none;
  z-index: 0;
}
```

**Content-responsive tinting:**
Extract dominant color from hero image via canvas `getImageData()`, apply as page ambient tint. Technique used by Apple Music, Spotify.

**Color temperature depth (spatial use):**
- Warm colors (red, orange, yellow) → advance toward viewer
- Cool colors (blue, purple, teal) → recede from viewer
- Use intentionally to reinforce z-axis depth, not just for decoration

**Chromatic shadows (not pure black/gray):**
```css
/* Instead of: box-shadow: 0 4px 16px rgba(0,0,0,0.2) */
/* Use shadow tinted toward complementary of light source: */
.card {
  box-shadow: 0 4px 16px rgba(80, 40, 120, 0.25);  /* purple-tinted for warm light */
}
```

**Time-aware theming (optional, delightful):**
- After 6pm: subtle warm shift (hue rotate +5deg, saturation +3%)
- Morning: cool shift (hue rotate -3deg, brightness +2%)
- Implement via CSS custom property update on schedule or user preference

---

## 6. Mesh Gradient Patterns

**CSS implementation:**
```css
.mesh-bg {
  background:
    radial-gradient(ellipse at 20% 20%, rgba(120,80,255,0.4) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 20%, rgba(255,80,120,0.3) 0%, transparent 50%),
    radial-gradient(ellipse at 50% 80%, rgba(80,200,255,0.3) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 80%, rgba(255,200,80,0.2) 0%, transparent 50%);
}
```

**Construction rules:**
- Place gradient points at grid intersections (3×3 or 4×4 grid)
- 4–6 color stops per point
- Saturation delta between adjacent stops: 3–5% (subtle variation, not jarring)

**Animated mesh:**
```css
@keyframes mesh-drift {
  0%, 100% { transform: translate(0, 0); }
  33%       { transform: translate(-20px, 10px); }
  66%       { transform: translate(10px, -20px); }
}
.mesh-point {
  animation: mesh-drift 30s ease-in-out infinite;
  will-change: transform;  /* GPU acceleration */
}
```
- Animation cycle: 20–40s (longer = more atmospheric, less distracting)
- Always set `will-change: transform` on animated gradient containers

**Stripe's approach:** WebGL noise functions via fragment shaders for GPU-rendered organic gradients with minimal CPU cost. Use for high-performance, complex mesh needs.

---

## Anti-Patterns

| Anti-Pattern | Why It Fails |
|---|---|
| Heavy blur killing text readability | Always verify contrast OVER the blurred background, not against a solid |
| Frosted glass without border | Edges disappear; elements float without spatial context |
| Shadows inconsistent with light source | Elements casting shadows in different directions feel physically wrong |
| Flat single-tone backgrounds | Misses the depth and atmosphere that elevates premium products |
| Noise texture above 2% opacity | Reads as gritty and industrial, not refined premium |
| Gradients with > 20% saturation jumps between stops | Jarring, not luminous |
| Black (#000) in shadows | Feels heavy and dead — use tinted dark values instead |
| Glassmorphism on glassmorphism | Stacked blur layers collapse depth, create visual noise |
| Same ambient glow color everywhere | Loses intentionality; glow should reflect the element's own hue |

---

## Validation Checklist

- [ ] Every element assigned to correct spatial layer (no z-index guessing)
- [ ] Shadow tokens consistent with elevation level
- [ ] Glassmorphism tier matches context (subtle/medium/immersive)
- [ ] 4.5:1 text contrast verified over glass surfaces on varied backgrounds
- [ ] Borders present on all glass surfaces for edge definition
- [ ] Ambient glow color derives from element's dominant hue
- [ ] Chromatic shadows used instead of pure rgba(0,0,0)
- [ ] Noise texture at or below 1.5% opacity
- [ ] Mesh gradient animation cycle 20–40s with will-change: transform
- [ ] prefers-reduced-motion stops mesh gradient animation
