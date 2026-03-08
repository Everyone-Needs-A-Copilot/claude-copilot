---
skill_name: aesthetic-directions
skill_category: design
description: Named aesthetic directions with visual moves, industry mapping, and anti-slop detection
allowed_tools: [Read, Edit, Write, Glob, Grep]
token_estimate: 2500
version: 1.0
last_updated: 2026-03-08
owner: Claude Copilot
status: active
tags: [design, aesthetic, visual-direction, brand-identity, anti-pattern]
related_skills: [color-palettes, typography-pairings, design-patterns]
trigger_files: ["**/*.css", "**/*.scss", "**/design/**", "**/brand/**"]
trigger_keywords: [aesthetic, visual-direction, design-style, brand-identity, look-and-feel]
quality_keywords: [anti-pattern, pattern, validation, best-practice]
---

# Aesthetic Directions

Named aesthetic directions for committing to a specific visual identity. Each direction includes concrete visual moves, not vague adjectives.

## Purpose

- Force intentional aesthetic commitment before designing
- Provide concrete visual vocabulary (not "clean and modern")
- Map directions to industries and audiences
- Detect and reject AI-generated visual clichés

---

## Named Directions

### 1. Neo-Brutalist
**Visual Moves:** Raw borders (3-4px black), no border-radius, monospace type, flat colors, visible grid, intentional "ugliness" as confidence
**Type:** Mono headings (Space Mono), grotesque body (Work Sans)
**Color:** Black, white, one screaming accent (yellow, red, cyan)
**Spacing:** Tight, aggressive, asymmetric
**Motion:** None or instant. Movement is dishonest in this aesthetic
**Best For:** Creative agencies, dev tools, counter-culture brands

### 2. Swiss Precision
**Visual Moves:** Strict grid, Helvetica-adjacent type, lots of whitespace, left-aligned, minimal color, information-dense but ordered
**Type:** Grotesk headings (Neue Haas Grotesk), proportional body (Suisse Int'l or Geist)
**Color:** Black + white + one accent (typically red or blue)
**Spacing:** Generous, mathematical, grid-locked
**Motion:** Subtle, functional transitions only
**Best For:** Data platforms, fintech, professional services

### 3. Soft Tech
**Visual Moves:** Large border-radius (12-16px), soft shadows, pastel-adjacent palette, generous padding, rounded illustrations
**Type:** Rounded sans (Nunito Sans, Figtree), friendly weight
**Color:** Soft primaries, tinted neutrals (not pure gray)
**Spacing:** Generous, breathable, comfortable
**Motion:** Gentle easing, subtle bounce on interaction
**Best For:** Consumer SaaS, onboarding flows, education platforms

### 4. Editorial Luxury
**Visual Moves:** Serif dominance, generous line-height, pull quotes, editorial grid with asymmetric columns, restrained palette
**Type:** Display serif headings (Playfair Display, Cormorant), refined body (Source Serif Pro)
**Color:** Deep darks, cream/ivory backgrounds, gold or copper accents
**Spacing:** Luxurious whitespace, dramatic margins
**Motion:** Slow, deliberate fades and reveals
**Best For:** Fashion, publishing, luxury brands, portfolios

### 5. Dark Industrial
**Visual Moves:** Dark backgrounds, monospace accents, subtle grid lines, technical labels, exposed-system aesthetic
**Type:** Mono UI (JetBrains Mono), condensed sans body (Barlow Condensed)
**Color:** Near-black bg, gray-400 text, neon accents (green, cyan)
**Spacing:** Compact, functional, dense
**Motion:** Glitch effects, terminal-style reveals
**Best For:** Cybersecurity, infrastructure, monitoring dashboards

### 6. Organic Warmth
**Visual Moves:** Earth tones, organic shapes (blob borders), hand-drawn accents, textured backgrounds, imperfect geometry
**Type:** Humanist sans (Atkinson Hyperlegible, Cabin), or casual serif (Lora)
**Color:** Terracotta, sage, cream, warm grays
**Spacing:** Irregular but rhythmic, natural feel
**Motion:** Gentle, organic easing curves
**Best For:** Wellness, sustainability, artisan brands, natural products

### 7. Retro-Futuristic
**Visual Moves:** CRT glow effects, scan lines, retro-sci-fi typography, neon on dark, chrome gradients
**Type:** Geometric display (Orbitron, Audiowide), clean sans body (Exo 2)
**Color:** Deep navy/black, neon cyan/magenta, chrome silver
**Spacing:** Structured, symmetrical, padded
**Motion:** Flicker, glow pulse, slide-in reveals
**Best For:** Gaming, entertainment, music, event platforms

### 8. Maximalist Chaos
**Visual Moves:** Clashing colors, mixed media, overlapping elements, broken grid, type as texture, intentional overflow
**Type:** Mixed: display + handwritten + sans in one composition
**Color:** High saturation, complementary clashes, no "safe" palette
**Spacing:** Tight, overlapping, collage-like
**Motion:** Energetic, staggered, unexpected
**Best For:** Youth culture, music festivals, streetwear, creative portfolios

### 9. Japanese Minimal
**Visual Moves:** Extreme whitespace, asymmetric balance, delicate type, subtle dividers, wabi-sabi imperfection
**Type:** Light weight sans (Zen Kaku Gothic, Noto Sans JP for JP; Jost for Latin)
**Color:** Near-white, charcoal, one muted accent (indigo, moss)
**Spacing:** Dramatic whitespace, sparse layout
**Motion:** Slow, meditative transitions
**Best For:** Tea, ceramics, meditation, premium minimalism

### 10. Art Deco Geometric
**Visual Moves:** Symmetrical compositions, geometric patterns, gold/metallic accents, stepped forms, sunburst motifs
**Type:** Geometric display (Poiret One, Tenor Sans), clean body (Josefin Sans)
**Color:** Black, gold, deep jewel tones (emerald, sapphire)
**Spacing:** Symmetrical, grand, ceremonial
**Motion:** Elegant reveals, geometric transitions
**Best For:** Hotels, events, cocktail bars, luxury real estate

### 11. Glassmorphism
**Visual Moves:** Frosted glass layers, blur backgrounds, subtle borders, translucent surfaces, depth via layering
**Type:** Medium-weight sans (Inter, SF Pro — here Inter is intentional)
**Color:** Translucent whites/darks, vibrant background blurs
**Spacing:** Standard with layered depth
**Motion:** Parallax, smooth layer transitions
**Best For:** Dashboards, music apps, weather apps (use sparingly)

### 12. Monochrome Editorial
**Visual Moves:** Single-hue palette (black/white/grays), dramatic type scale, rule lines, strong hierarchy through weight
**Type:** High-contrast pairing (Bebas Neue + Barlow), extreme scale difference
**Color:** Pure black, white, 3 gray values max
**Spacing:** Tight headings, generous body, dramatic section breaks
**Motion:** Minimal, scroll-driven reveals
**Best For:** Photography, journalism, minimal portfolios

### 13. High Contrast Accessibility-First
**Visual Moves:** Maximum contrast, large type, chunky interactive targets, clear focus states, zero ambiguity
**Type:** Atkinson Hyperlegible + large base size (18px+)
**Color:** True black on true white (or reverse), high-saturation accents
**Spacing:** Extra generous, larger touch targets (48px+)
**Motion:** Reduced by default, respects prefers-reduced-motion
**Best For:** Government, healthcare, accessibility-critical apps

### 14. Nordic Calm
**Visual Moves:** Muted palette, clean lines, functional beauty, natural materials reference, understated confidence
**Type:** Red Hat Display + Red Hat Text, or Manrope
**Color:** Fog gray, pale blue, warm white, muted sage
**Spacing:** Generous, balanced, serene
**Motion:** Slow, smooth, almost imperceptible
**Best For:** Furniture, lifestyle, Scandinavian brands, wellness

### 15. Corporate Rebellion
**Visual Moves:** Starts corporate (grid, clean type) then breaks rules (oversized type, unexpected color, broken alignment)
**Type:** Clean grotesque (Geist) with moments of display disruption (Clash Display)
**Color:** Mostly neutral with one "rule-breaking" accent
**Spacing:** Structured with intentional breaks
**Motion:** Professional with surprising micro-interactions
**Best For:** Challenger brands, disruptive startups, rebrand work

### 16. Cyberpunk
**Visual Moves:** Neon glow on dark, HUD-style interfaces, glitch artifacts, data-stream patterns, angular geometry
**Type:** Condensed sans (Chakra Petch), monospace data (Fira Code)
**Color:** Deep purple/navy bg, neon green/cyan/pink accents
**Spacing:** Dense, information-overload-as-aesthetic
**Motion:** Glitch, flicker, data-scroll effects
**Best For:** AI/ML products, crypto, hacking tools, sci-fi games

### 17. Vintage Paper
**Visual Moves:** Cream/sepia backgrounds, aged textures, woodcut-style illustrations, old-style figures, ornamental dividers
**Type:** Old-style serif (EB Garamond, Crimson Pro), small caps headers
**Color:** Cream, sepia, deep brown, muted red
**Spacing:** Book-like margins, generous line height
**Motion:** Page-turn transitions, fade-in reveals
**Best For:** Bookstores, heritage brands, artisan food, whiskey

### 18. Bauhaus
**Visual Moves:** Primary colors + black, geometric shapes, asymmetric grid, functional typography, form = function
**Type:** Geometric sans (Futura, Jost), uppercase headings
**Color:** Red, blue, yellow, black, white — no other hues
**Spacing:** Structured, mathematical, grid-strict
**Motion:** Geometric transitions, rotation, sliding
**Best For:** Design schools, architecture, museums, furniture

### 19. Pastel Dream
**Visual Moves:** Soft pastels, rounded everything, gentle gradients, cloud-like surfaces, whimsical illustrations
**Type:** Rounded sans (Quicksand, Comfortaa), light weights
**Color:** Lavender, mint, blush, soft yellow, cream
**Spacing:** Generous, soft, padded
**Motion:** Float, gentle bounce, dreamy easing
**Best For:** Children's products, wedding, Gen-Z consumer, creative tools

### 20. Sci-Fi Interface
**Visual Moves:** Grid overlays, circular gauges, technical readouts, hexagonal patterns, thin-line icons, HUD corners
**Type:** Condensed sans (Rajdhani, Exo 2), monospace data
**Color:** Dark blue-black bg, cyan/amber data, white text
**Spacing:** Dense, organized into panels/modules
**Motion:** Scan-line reveals, data counter animations, radial transitions
**Best For:** Space/aviation, military, simulation, dashboard-heavy apps

---

## Dual-Mode Framework

| Mode | When to Use | Approach |
|------|-------------|----------|
| **Innovative** (default) | New brand, creative brief, rebrand, greenfield | Choose bold direction, push boundaries, create distinctive identity |
| **Controlled** | Existing design system, extension, maintenance | Work within established tokens, extend rather than replace, maintain consistency |

**Decision:** If codebase contains existing design tokens, CSS custom properties, or a design system config → default to Controlled. Otherwise → Innovative.

---

## Industry Selection Matrix

| Industry + Tone | Top 3 Recommended Directions |
|-----------------|------------------------------|
| Finance + Trust | Swiss Precision, Nordic Calm, Monochrome Editorial |
| Finance + Disruptive | Corporate Rebellion, Dark Industrial, Art Deco Geometric |
| Healthcare + Calm | Organic Warmth, High Contrast Accessibility-First, Nordic Calm |
| SaaS + Professional | Swiss Precision, Soft Tech, Nordic Calm |
| SaaS + Bold | Neo-Brutalist, Corporate Rebellion, Cyberpunk |
| E-commerce + Luxury | Editorial Luxury, Art Deco Geometric, Vintage Paper |
| E-commerce + Youth | Maximalist Chaos, Pastel Dream, Retro-Futuristic |
| Gaming + Immersive | Cyberpunk, Sci-Fi Interface, Retro-Futuristic |
| Education + Friendly | Soft Tech, Organic Warmth, Pastel Dream |
| Dev Tools + Technical | Dark Industrial, Neo-Brutalist, Swiss Precision |
| Creative Agency | Neo-Brutalist, Maximalist Chaos, Corporate Rebellion |

---

## Anti-Slop Detector

Reject these AI-generated visual clichés on sight:

| # | Cliché | Why It's Slop |
|---|--------|---------------|
| 1 | Inter + blue gradient on white | Default AI output, zero design thought |
| 2 | Purple-to-pink gradient hero section | Most overused AI-generated visual |
| 3 | Generic SaaS illustration (flat people, oversized limbs) | Undraw/Humaaans default, signals template |
| 4 | Card grid with identical border-radius and shadow | Cookie-cutter layout, no hierarchy |
| 5 | "Clean and modern" as entire aesthetic rationale | Says nothing, means nothing |
| 6 | Blue CTA button on white with gray text | Bootstrap default disguised as design |
| 7 | Hero section: big text left, mockup right | Every AI landing page ever |
| 8 | Gradient mesh background with no purpose | Eye candy without function |
| 9 | Rounded sans-serif in light weight for everything | Wishy-washy, no typographic conviction |
| 10 | White card on gray background as entire UI system | Minimal effort, not minimalism |
| 11 | Indistinguishable from Stripe, Linear, or Vercel | Derivative, not inspired by |
| 12 | Stock photo hero with overlay gradient | Lazy, impersonal, instantly forgettable |
| 13 | 3D floating elements for no functional reason | Decorative complexity without purpose |
| 14 | Emoji as primary visual language | Casual ≠ designed |
| 15 | Dark mode = just invert colors | Dark mode requires intentional design |

---

## Validation Checklist

- [ ] Aesthetic direction explicitly named (not "clean and modern")
- [ ] Visual moves described concretely (type, color, spacing, radius, motion)
- [ ] Direction justified against audience + content + brand
- [ ] At least 3 directions evaluated before committing
- [ ] Chosen direction passes Anti-Slop Detector
- [ ] Mode (Innovative vs Controlled) explicitly declared
