---
skill_name: design-patterns
skill_category: design
description: Visual design patterns, design tokens, component specifications, WCAG compliance
allowed_tools: [Read, Edit, Write, Glob, Grep]
token_estimate: 1400
version: 1.0
last_updated: 2026-01-13
owner: Claude Copilot
status: active
tags: [design, tokens, visual, components, accessibility, pattern, anti-pattern]
related_skills: [ux-patterns]
trigger_files: ["**/*.css", "**/*.scss", "**/tokens/**", "**/design/**", "**/styles/**"]
trigger_keywords: [design-tokens, visual-design, component-spec, color-system, typography, spacing, WCAG, contrast, design-system]
quality_keywords: [anti-pattern, pattern, validation, best-practice, accessibility]
---

# Design Patterns

Visual design patterns for creating consistent, accessible interfaces with proper design tokens and component specifications.

## Purpose

Provides patterns for:
- Design token systems (colors, typography, spacing)
- Component visual specifications
- WCAG 2.1 AA accessibility compliance
- Responsive design across breakpoints

---

## Core Patterns

### Pattern 1: Semantic Color Tokens

**When to use:** Defining color systems that work across themes.

**Implementation:**
```css
/* Base palette (reference only) */
--blue-500: #3b82f6;
--blue-700: #1d4ed8;

/* Semantic tokens (use these) */
--color-primary: var(--blue-500);
--color-primary-hover: var(--blue-700);
--color-text: #111827;
--color-text-muted: #6b7280;
--color-background: #ffffff;
--color-error: #ef4444;
--color-success: #10b981;
```

**Benefits:**
- Theme switching via semantic tokens
- Consistent color usage across components
- Easier maintenance and updates

### Pattern 2: 8px Spacing Scale

**When to use:** All spacing decisions (padding, margins, gaps).

**Implementation:**
```css
--space-1: 0.25rem;  /* 4px - tight */
--space-2: 0.5rem;   /* 8px - compact */
--space-3: 0.75rem;  /* 12px */
--space-4: 1rem;     /* 16px - default */
--space-6: 1.5rem;   /* 24px - medium */
--space-8: 2rem;     /* 32px - large */
--space-12: 3rem;    /* 48px - section */
```

**Benefits:**
- Visual rhythm and consistency
- Predictable spacing relationships
- Easier to maintain

### Pattern 3: Component State Matrix

**When to use:** Defining all interactive component states.

**Implementation:**
| State | Background | Border | Text | Cursor |
|-------|------------|--------|------|--------|
| Default | `--color-bg` | `--color-border` | `--color-text` | default |
| Hover | `--color-bg-hover` | `--color-border` | `--color-text` | pointer |
| Focus | `--color-bg` | `--color-focus-ring` | `--color-text` | — |
| Active | `--color-bg-active` | `--color-border` | `--color-text` | pointer |
| Disabled | `--color-bg` | `--color-border` | `--color-text-muted` | not-allowed |
| Loading | `--color-bg` | `--color-border` | `--color-text-muted` | wait |
| Error | `--color-bg` | `--color-error` | `--color-error` | — |

---

## Anti-Patterns

### Anti-Pattern 1: Hard-Coded Values

| Aspect | Description |
|--------|-------------|
| **WHY** | Breaks design system consistency, makes theme switching impossible |
| **DETECTION** | Raw hex colors, pixel values without tokens in CSS |
| **FIX** | Always use design tokens for colors, spacing, typography |

**Bad Example:**
```css
.button {
  background: #3b82f6;
  padding: 12px 16px;
  color: white;
}
```

**Good Example:**
```css
.button {
  background: var(--color-primary);
  padding: var(--space-3) var(--space-4);
  color: var(--color-on-primary);
}
```

### Anti-Pattern 2: Missing States

| Aspect | Description |
|--------|-------------|
| **WHY** | Creates incomplete interactions, accessibility failures |
| **DETECTION** | Components only define default + hover, missing focus/disabled/error |
| **FIX** | Define ALL states: default, hover, focus, active, disabled, loading, error |

### Anti-Pattern 3: Insufficient Contrast

| Aspect | Description |
|--------|-------------|
| **WHY** | WCAG 2.1 AA violation, excludes users with visual impairments |
| **DETECTION** | Text contrast < 4.5:1, UI component contrast < 3:1 |
| **FIX** | Use contrast checker, ensure text 4.5:1, UI elements 3:1 minimum |

---

## WCAG 2.1 AA Requirements

| Requirement | Threshold | Applies To |
|-------------|-----------|------------|
| Text contrast | 4.5:1 | All text |
| Large text contrast | 3:1 | 18px+ or 14px bold |
| UI component contrast | 3:1 | Borders, icons, focus rings |
| Touch target | 44x44px | Mobile interactive elements |
| Focus visible | 2px outline | All focusable elements |

---

## Validation Checklist

### Color System
- [ ] All colors use semantic tokens, not raw values
- [ ] Text meets 4.5:1 contrast ratio
- [ ] UI components meet 3:1 contrast ratio
- [ ] Color is not sole indicator (add icons/text)

### Components
- [ ] All states defined (default, hover, focus, active, disabled, loading, error)
- [ ] Touch targets minimum 44x44px
- [ ] Focus ring visible with 2px minimum
- [ ] Tokens used for all values

### Responsive
- [ ] Works on mobile, tablet, desktop
- [ ] Typography scales appropriately
- [ ] Spacing adjusts for viewport
- [ ] No horizontal scroll on mobile

---

## Output Templates

### Design Tokens Spec
```markdown
## Design Tokens: [System Name]

### Colors
| Token | Value | Usage |
|-------|-------|-------|
| --color-primary | #3b82f6 | Primary actions |
| --color-text | #111827 | Body text (4.54:1) |

### Typography
| Token | Value | Usage |
|-------|-------|-------|
| --text-base | 1rem | Body text |
| --font-sans | 'Inter', sans-serif | Primary font |

### Spacing
| Token | Value | Usage |
|-------|-------|-------|
| --space-4 | 1rem | Default padding |
```

### Component Spec
```markdown
## Component: [Name]

### Variants
| Variant | Use Case | Treatment |
|---------|----------|-----------|
| Primary | Main actions | Filled, brand |
| Secondary | Alternative | Outlined |

### States
| State | Background | Border | Text |
|-------|------------|--------|------|
| Default | --color-bg | --color-border | --color-text |

### Accessibility
- Contrast: X.X:1 (meets AA)
- Touch target: 44x44px
- Focus: 2px outline
```
