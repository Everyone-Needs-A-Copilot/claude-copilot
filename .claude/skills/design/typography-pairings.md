---
skill_name: typography-pairings
skill_category: design
description: Curated font pairings by character with type scales and fluid typography formulas
allowed_tools: [Read, Edit, Write, Glob, Grep]
token_estimate: 2000
version: 1.0
last_updated: 2026-03-08
owner: Claude Copilot
status: active
tags: [design, typography, font-pairing, type-scale, anti-pattern]
related_skills: [design-patterns, aesthetic-directions]
trigger_files: ["**/*.css", "**/*.scss", "**/typography/**", "**/fonts/**"]
trigger_keywords: [typography, font-pairing, type-scale, font-system]
quality_keywords: [anti-pattern, pattern, validation, best-practice]
---

# Typography Pairings

Curated font pairings organized by character and context, with computed type scales and fluid typography formulas.

## Purpose

- Provide distinctive, intentional typography choices
- Map pairings to personality and use case
- Include ready-to-use type scale systems
- Ban overused AI-default font combinations

---

## Curated Pairings

### Serif + Sans-Serif (Classic Contrast)

| Character | Heading | Body | Best For |
|-----------|---------|------|----------|
| Editorial Authority | Playfair Display | Source Serif Pro | Publishing, luxury, longform |
| Modern Heritage | Cormorant Garamond | Lato | Fashion, hospitality, cultural |
| Warm Storytelling | Lora | Merriweather Sans | Blogs, memoir, narrative |
| Academic Gravitas | Libre Baskerville | Source Sans 3 | Education, research, institutional |
| Art Magazine | DM Serif Display | DM Sans | Gallery, creative, editorial |
| Classic Refinement | Crimson Pro | Cabin | Law, finance, traditional |
| Elegant Contrast | Spectral | Work Sans | Architecture, design, portfolio |

### Sans-Serif + Sans-Serif (Contemporary)

| Character | Heading | Body | Best For |
|-----------|---------|------|----------|
| Tech Confidence | Sora | Plus Jakarta Sans | SaaS, enterprise, dashboards |
| Geometric Precision | Outfit | Albert Sans | Fintech, data, analytics |
| Friendly Professional | Lexend | Nunito Sans | HR tech, onboarding, education |
| Bold Startup | Clash Display | General Sans | Landing pages, marketing, brand |
| Clean Authority | Manrope | Figtree | Enterprise, B2B, productivity |
| Soft Modern | Urbanist | Atkinson Hyperlegible | Accessibility-first, healthcare |
| Nordic Minimal | Red Hat Display | Red Hat Text | Design tools, minimal UI |
| Sharp & Direct | Space Grotesk | Geist | Developer tools, technical docs |
| Warm Geometric | Gilda Display | Jost | Hospitality, events, lifestyle |
| Human Tech | Bricolage Grotesque | Instrument Sans | Community, social, collaboration |

### Monospace + Sans-Serif (Technical)

| Character | Heading/Code | Body | Best For |
|-----------|-------------|------|----------|
| Tech Precision | JetBrains Mono | Inter | IDE, developer tools, docs |
| Hacker Chic | Fira Code | Fira Sans | Terminal, CLI, code editors |
| Retro Terminal | IBM Plex Mono | IBM Plex Sans | Retro tech, system admin |
| Clean Code | Cascadia Code | Segoe UI | Microsoft ecosystem, tutorials |
| Indie Dev | Victor Mono | Karla | Indie tools, creative code |

### Display + Body (High Impact)

| Character | Heading | Body | Best For |
|-----------|---------|------|----------|
| Playful Energy | Fredoka | Nunito | Kids, games, casual apps |
| Bold Statement | Archivo Black | Archivo | Sports, events, activism |
| Retro Futurism | Orbitron | Exo 2 | Sci-fi, space, gaming |
| Handcrafted Digital | Caveat | Quicksand | Personal brand, craft, artisan |
| Maximalist Pop | Bebas Neue | Barlow | Posters, fashion, streetwear |
| Elegant Display | Tenor Sans | Poppins | Luxury, minimalist, gallery |
| Industrial Strength | Oswald | Roboto Flex | Manufacturing, logistics, utility |
| Calligraphic Contrast | Playfair Display SC | Montserrat Alternates | Wedding, luxury events, premium |

---

## Type Scale Systems

### Minor Third (1.200) — Compact, professional

| Step | Size | Use |
|------|------|-----|
| xs | 11.11px (0.694rem) | Captions, legal |
| sm | 13.33px (0.833rem) | Labels, metadata |
| base | 16px (1rem) | Body text |
| lg | 19.2px (1.2rem) | Subheadings |
| xl | 23.04px (1.44rem) | Section titles |
| 2xl | 27.65px (1.728rem) | Page headings |
| 3xl | 33.18px (2.074rem) | Hero text |

### Major Third (1.250) — Balanced, versatile

| Step | Size | Use |
|------|------|-----|
| xs | 10.24px (0.64rem) | Captions, legal |
| sm | 12.8px (0.8rem) | Labels, metadata |
| base | 16px (1rem) | Body text |
| lg | 20px (1.25rem) | Subheadings |
| xl | 25px (1.563rem) | Section titles |
| 2xl | 31.25px (1.953rem) | Page headings |
| 3xl | 39.06px (2.441rem) | Hero text |

### Perfect Fourth (1.333) — Dramatic, editorial

| Step | Size | Use |
|------|------|-----|
| xs | 9px (0.563rem) | Captions, legal |
| sm | 12px (0.75rem) | Labels, metadata |
| base | 16px (1rem) | Body text |
| lg | 21.33px (1.333rem) | Subheadings |
| xl | 28.43px (1.777rem) | Section titles |
| 2xl | 37.9px (2.369rem) | Page headings |
| 3xl | 50.52px (3.157rem) | Hero text |

---

## Fluid Typography

Use `clamp()` for responsive scaling between viewport widths:

```css
/* Formula: clamp(min, preferred, max) */
/* preferred = min + (max - min) * ((100vw - minVW) / (maxVW - minVW)) */

--text-base: clamp(1rem, 0.5rem + 0.75vw, 1.125rem);
--text-lg: clamp(1.2rem, 0.8rem + 0.9vw, 1.5rem);
--text-xl: clamp(1.44rem, 0.9rem + 1.2vw, 2rem);
--text-2xl: clamp(1.728rem, 1rem + 1.6vw, 2.5rem);
--text-3xl: clamp(2.074rem, 1.2rem + 2vw, 3.5rem);
```

**Viewport breakpoints:** min = 320px, max = 1280px

---

## Weight & Leading Rules

| Context | Font Weight | Line Height | Letter Spacing |
|---------|-------------|-------------|----------------|
| Body text | 400 (regular) | 1.5–1.75 | 0 |
| UI labels | 500 (medium) | 1.2 | 0.01em |
| Subheadings | 600 (semibold) | 1.3 | -0.01em |
| Headings | 700 (bold) | 1.1–1.25 | -0.02em |
| Display/Hero | 800-900 (extra-bold) | 1.0–1.1 | -0.03em |
| Code | 400 | 1.6–1.7 | 0 |
| Captions | 400 | 1.4 | 0.02em |

**Rule:** As font size increases, line-height decreases and letter-spacing goes negative.

---

## Anti-Generic Bans

| Banned | Why |
|--------|-----|
| Inter as default/only font | Most overused AI choice — pick it intentionally or not at all |
| Roboto for everything | Android default, signals zero design thought |
| Montserrat + Open Sans | The "free font cliché" — on every template site |
| Poppins as sole font | Overused in generic SaaS, lost all distinctiveness |
| system-ui as design choice | System font stack is for apps, not for designed experiences |
| Using 3+ font families | Visual noise, inconsistent, harder to maintain |
| Same weight for heading + body | Destroys hierarchy, looks unprofessional |

---

## Validation Checklist

- [ ] Font pairing has clear character rationale
- [ ] Heading and body fonts have sufficient contrast (different classification or weight)
- [ ] No more than 2 font families (3 only if including monospace for code)
- [ ] Type scale follows consistent ratio
- [ ] Line heights set per context (not one value for all)
- [ ] Font weights create clear hierarchy (min 200 weight difference heading vs body)
- [ ] No banned combinations used without explicit justification
- [ ] Fluid typography applied for responsive scaling
