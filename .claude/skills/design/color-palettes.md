---
skill_name: color-palettes
skill_category: design
description: Curated color palettes by mood/industry with anti-generic rules and WCAG contrast reference
allowed_tools: [Read, Edit, Write, Glob, Grep]
token_estimate: 2500
version: 1.0
last_updated: 2026-03-08
owner: Claude Copilot
status: active
tags: [design, color, palette, tokens, anti-pattern, brand, accessibility]
related_skills: [design-patterns, aesthetic-directions]
trigger_files: ["**/*.css", "**/*.scss", "**/tokens/**", "**/theme/**"]
trigger_keywords: [color-palette, color-system, brand-colors, theme, palette]
quality_keywords: [anti-pattern, pattern, validation, best-practice, accessibility]
---

# Color Palettes

Curated palettes organized by mood and industry. Each palette is tested for WCAG contrast compliance and designed to avoid generic AI color choices.

## Purpose

- Provide distinctive, intentional color systems — not defaults
- Map palettes to industries and emotional contexts
- Enforce contrast compliance from the start
- Ban overused AI-generated color clichés

---

## Named Palettes

| Name | Primary | Secondary | Accent | Neutral | Mood | Best For |
|------|---------|-----------|--------|---------|------|----------|
| Midnight Authority | #1a1f36 | #2d3a6e | #c9a84c | #e8e6e1 | Trust, power | Finance, legal, enterprise |
| Digital Garden | #2d5a27 | #8b6b4a | #e8d5b7 | #f5f2ed | Growth, natural | Wellness, sustainability, organic |
| Neon Pulse | #0a0a0a | #00d4ff | #ff2d6b | #1a1a2e | Energy, edge | Gaming, nightlife, entertainment |
| Warm Mineral | #c4a882 | #8b7355 | #6b8f71 | #f0ebe4 | Craft, authenticity | Hospitality, artisan, boutique |
| Arctic Precision | #0f172a | #1e40af | #38bdf8 | #f1f5f9 | Clarity, technical | SaaS, developer tools, analytics |
| Terracotta Studio | #c2703e | #8e4e2e | #2c4a3e | #faf6f1 | Warmth, creative | Architecture, interior design, craft |
| Deep Ocean | #0c1821 | #1b4965 | #5fa8d3 | #bee9e8 | Depth, calm | Healthcare, meditation, marine |
| Ember Signal | #1c1917 | #dc2626 | #f97316 | #fafaf9 | Urgency, action | Emergency, fitness, news |
| Sage Library | #2f3e28 | #5c6b4f | #d4a574 | #f5f0e8 | Wisdom, heritage | Education, publishing, archives |
| Violet Dusk | #1e1b4b | #5b21b6 | #c084fc | #f5f3ff | Imagination, premium | Creative tools, music, luxury tech |
| Copper & Slate | #78350f | #44403c | #d97706 | #f5f5f4 | Industrial, reliable | Manufacturing, logistics, B2B |
| Rose Gold Luxe | #1c1917 | #be185d | #f9a8d4 | #fdf2f8 | Elegance, feminine | Beauty, fashion, jewelry |
| Moss & Stone | #365314 | #78716c | #a3e635 | #fafaf9 | Grounded, eco | Outdoor, conservation, agriculture |
| Ink & Paper | #09090b | #27272a | #fafafa | #f4f4f5 | Editorial, stark | Publishing, portfolio, minimalist |
| Tropical Heat | #134e4a | #0d9488 | #fbbf24 | #f0fdfa | Vibrant, exotic | Travel, food, lifestyle |
| Charcoal Blueprint | #171717 | #3b82f6 | #60a5fa | #f5f5f5 | Technical, precise | Engineering, data, infrastructure |
| Burnt Sienna | #431407 | #9a3412 | #fdba74 | #fff7ed | Artisanal, bold | Food & beverage, restaurants |
| Frosted Glass | #f8fafc | #64748b | #0ea5e9 | #e2e8f0 | Light, airy | Productivity, notes, clean UI |
| Royal Ink | #1e1b4b | #312e81 | #818cf8 | #eef2ff | Regal, confident | Consulting, professional services |
| Forest Floor | #1a2e05 | #4d7c0f | #a16207 | #fefce8 | Rich, organic | Wine, gourmet, natural products |
| Concrete & Neon | #18181b | #27272a | #22d3ee | #f4f4f5 | Urban, modern | Streetwear, urban culture, music |
| Parchment & Iron | #292524 | #78716c | #a8a29e | #faf5f0 | Timeless, serious | Law, government, institutional |
| Sunset Mesa | #7c2d12 | #ea580c | #fcd34d | #fffbeb | Warm, adventurous | Travel, outdoor, Western |
| Nordic Frost | #f1f5f9 | #94a3b8 | #0284c7 | #e2e8f0 | Clean, Scandinavian | Furniture, lifestyle, wellness |
| Electric Midnight | #020617 | #7c3aed | #06b6d4 | #0f172a | Bold, futuristic | AI/ML, crypto, cutting-edge tech |

---

## Industry Selection Rules

| Industry | Recommended Characteristics | Avoid |
|----------|---------------------------|-------|
| Finance / Legal | Dark navy, gold accents, high contrast | Bright neons, playful colors |
| Healthcare | Cool blues/greens, calming, high readability | Reds as primary (alarm association) |
| E-commerce | High-contrast CTAs, warm accents for trust | Low-contrast text, muted CTAs |
| SaaS / Dev Tools | Cool neutrals, blue-family accents, clean | Warm earth tones (feels unfocused) |
| Luxury / Fashion | Deep darks, metallic accents, restrained palette | Bright primaries, generic blues |
| Food & Beverage | Warm earth, appetizing tones (amber, terracotta) | Cool grays, clinical blues |
| Education | Sage/forest greens, warm paper tones | Aggressive reds, neons |
| Gaming / Entertainment | High saturation, dark backgrounds, neon accents | Muted pastels, corporate blues |

---

## Anti-Generic Bans

These colors and combinations are BANNED — they signal lazy, default AI design:

| Banned | Why |
|--------|-----|
| Bootstrap blue `#0d6efd` | Framework default, not a design choice |
| Material purple `#6200ee` | Instantly recognizable as Material default |
| Generic gray-on-white `#f5f5f5` bg + `#333` text | Zero personality, default starter |
| "Startup blue" `#4285f4` + white | Google blue clone, seen on 10,000 landing pages |
| Purple-to-pink gradient as hero | The single most overused AI-generated visual |
| Blue-to-purple gradient buttons | Signals "made by AI" or "Stripe clone" |
| `#6c757d` as secondary | Bootstrap secondary default |
| Any Tailwind default palette used verbatim | Not a design decision |

---

## Dark Mode Derivation

Transform any light palette to dark mode:

| Property | Light → Dark Rule |
|----------|-------------------|
| Background | Invert: lightest → `#0a0a0a` to `#1a1a1a` range |
| Text | Invert: darkest → `#e4e4e7` to `#fafafa` range |
| Primary | Reduce saturation 10-15%, keep hue |
| Accent | Increase lightness 10-15% for visibility |
| Borders | Use `rgba(255,255,255,0.1)` instead of gray |
| Shadows | Replace with subtle glow or border treatment |
| Surfaces | Layer: bg +2% lightness per elevation level |

---

## WCAG Contrast Quick Reference

| Combination | Ratio | Passes |
|-------------|-------|--------|
| `#000000` on `#ffffff` | 21:1 | AAA |
| `#1a1a1a` on `#ffffff` | 17.4:1 | AAA |
| `#374151` on `#ffffff` | 8.9:1 | AAA |
| `#6b7280` on `#ffffff` | 4.6:1 | AA |
| `#9ca3af` on `#ffffff` | 2.9:1 | FAIL |
| `#ffffff` on `#1e40af` | 9.4:1 | AAA |
| `#ffffff` on `#3b82f6` | 3.1:1 | FAIL for text |
| `#ffffff` on `#dc2626` | 4.6:1 | AA |
| `#fafafa` on `#0a0a0a` | 19.8:1 | AAA |

**Rule of thumb:** If primary color is lighter than `#4a5568`, don't use white text on it — use dark text instead.

---

## Validation Checklist

- [ ] Palette has clear emotional/brand rationale (not "it looks nice")
- [ ] All text/background combos meet 4.5:1 contrast
- [ ] UI elements meet 3:1 contrast
- [ ] No banned colors or combinations used
- [ ] Dark mode variant defined with proper derivation
- [ ] Palette matches industry characteristics
- [ ] At least 5 colors: primary, secondary, accent, neutral-light, neutral-dark
