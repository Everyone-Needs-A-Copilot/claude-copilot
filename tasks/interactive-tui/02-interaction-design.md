# Interaction Design: Interactive Claude Monitor

> Navigation Model, Screen Layouts, Keyboard Shortcuts, and Patterns

---

## 1. Information Architecture

### View Hierarchy

```
┌─────────────────────────────────────────────────────────────┐
│                    CLAUDE USAGE MONITOR                      │
├─────────────────────────────────────────────────────────────┤
│  [Dashboard]  [Daily]  [Monthly]  [Agents]  [Settings]      │
│       │                                                      │
│       ├─► Overview Panel (always visible)                   │
│       ├─► Session Blocks (drillable)                        │
│       ├─► Projections Panel (conditional)                   │
│       └─► Details Panel (on-demand)                         │
└─────────────────────────────────────────────────────────────┘
```

### Screen Organization

| Screen | Purpose | Key Components |
|--------|---------|----------------|
| **Dashboard** | Real-time monitoring | Overview, Active Block, Projections, Timeline |
| **Daily** | Historical daily breakdown | Date table, model stats, cost trends |
| **Monthly** | Long-term trends | Month table, aggregates, comparisons |
| **Agents** | Live agent activity | Agent list, context usage, relationships |
| **Detail** | Drill-down modal | Session/Agent/Model details |

---

## 2. Navigation Model

### Primary Navigation (Views)

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  Dashboard │ Daily │ Monthly │ Agents          14:32:15 ┃
┃  ──────────                                              ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

**Shortcuts:**
- `Tab` / `Shift+Tab` - Next/previous view
- `1` - Dashboard
- `2` - Daily
- `3` - Monthly
- `4` - Agents
- `0` - Settings

### Secondary Navigation (Panels)

Within each screen, navigate between focusable panels:

- `j` / `↓` - Next panel
- `k` / `↑` - Previous panel
- `Home` - First panel
- `End` - Last panel

### Drill-Down Navigation

- `Enter` - Open detail view
- `Esc` - Close detail, return to parent
- `Backspace` - Same as Esc

### Command Palette

- `/` - Open command palette
- Type to filter commands
- `Enter` - Execute selected
- `Esc` - Close palette

---

## 3. Keyboard Shortcut Map

### Global Shortcuts

| Key | Action |
|-----|--------|
| `q` | Quit application |
| `?` | Show help overlay |
| `/` | Command palette |
| `Space` | Pause/Resume |
| `Ctrl+R` | Force refresh |
| `Ctrl+L` | Redraw screen |

### Navigation

| Key | Action |
|-----|--------|
| `1-4` | Jump to view |
| `0` | Settings |
| `Tab` | Next view tab |
| `Shift+Tab` | Previous view tab |
| `j` / `↓` | Next panel/item |
| `k` / `↑` | Previous panel/item |
| `Enter` | Drill-down |
| `Esc` | Go back |

### Dashboard

| Key | Action |
|-----|--------|
| `r` | Re-detect plan |
| `m` | Model breakdown |
| `w` | What-if calculator |
| `z` | Zoom timeline |

### Daily/Monthly

| Key | Action |
|-----|--------|
| `s` | Sort menu |
| `c` | Compare mode |
| `g` | Toggle graph/table |

### Agents

| Key | Action |
|-----|--------|
| `f` | Filter agents |
| `h` | Health legend |
| `r` | Show relationships |
| `a` | Show all (clear filters) |

### Detail Views

| Key | Action |
|-----|--------|
| `Tab` | Next detail tab |
| `c` | Copy metric |

---

## 4. Interaction Patterns

### 4.1 Drill-Down Pattern

**Flow:**
```
Dashboard → Focus panel (j/k) → Select item (↑/↓) → Enter → Detail overlay → Esc
```

**Detail Overlay Structure:**
```
┌─────────────────────────────────────────────┐
│ Session Block Detail         [ESC to close] │
├─────────────────────────────────────────────┤
│ Block: 2025-12-13 14:00-19:00               │
│ Status: Active | Tokens: 425K (85%)         │
├─────────────────────────────────────────────┤
│ [Models] [Timeline] [Tools]                 │
├─────────────────────────────────────────────┤
│ • claude-sonnet-4.5    320K (75%)  $1.60    │
│ • claude-opus-4        105K (25%)  $0.55    │
└─────────────────────────────────────────────┘
```

### 4.2 Filtering Pattern

**Flow:**
```
Press f → Type filter → Enter → View filters → Ctrl+F to clear
```

**Filter Syntax:**
```
type:Explore          # By agent type
tokens>100000         # Token threshold
active:true           # Only active
model:sonnet          # By model
```

**Visual Indicator:**
```
┌─────────────────────────────────────────────┐
│ Agents [FILTERED: type=Explore]          f  │
└─────────────────────────────────────────────┘
```

### 4.3 Pause/Resume Pattern

**Flow:**
```
Space → Display freezes → "PAUSED" indicator → Space → Resume with latest data
```

**Paused State:**
```
┌─────────────────────────────────────────────┐
│ ⏸ PAUSED  [SPACE to resume]  14:32:15      │
└─────────────────────────────────────────────┘
```

### 4.4 Comparison Mode

**Flow:**
```
Press c → Select baseline → Select comparison → View delta table → Esc
```

**Display:**
```
┌─────────────────────────────────────────────┐
│ Comparison: Today vs Yesterday              │
├─────────────────────────────────────────────┤
│                  Today    Yesterday   Δ     │
│ Tokens:          425K     380K      +11.8%  │
│ Cost:            $2.15    $1.92     +12.0%  │
└─────────────────────────────────────────────┘
```

### 4.5 What-If Scenario

**Flow:**
```
Press w → Adjust burn rate → See projected outcomes → Esc
```

**Display:**
```
┌─────────────────────────────────────────────┐
│ What If...                                  │
├─────────────────────────────────────────────┤
│ Burn rate: [████████░░] 2,800 tok/min       │
│                                             │
│ At this rate:                               │
│ • 90% limit in:     22 minutes              │
│ • Session end:      475K tokens ($2.38)     │
│ • Daily projected:  1.2M tokens ($6.00)     │
└─────────────────────────────────────────────┘
```

---

## 5. Screen Layouts

### 5.1 Dashboard (Default)

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Dashboard │ Daily │ Monthly │ Agents           14:32:15 ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

┌────────────────────────────────────────────────────────┐
│ OVERVIEW                                          [1/4]│
├────────────────────────────────────────────────────────┤
│ Plan: Pro | Limit: 500K tokens | Reset: 19:00          │
│ Usage: [████████████░░░░] 85% (425K / 500K)            │
│ Cost:  $2.15 | Projected: $2.53 at current rate        │
└────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────┐
│ ACTIVE SESSION                                    [2/4]│
├────────────────────────────────────────────────────────┤
│ 14:00-19:00 | 2h 32m elapsed | 2h 28m remaining        │
│ Models: Sonnet 4.5 (75%), Opus 4 (25%)                 │
│ Burn rate: 2,800 tok/min | $0.85/hour                  │
│                                                        │
│ [Enter] details  [m] models  [w] what-if               │
└────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────┐
│ PROJECTIONS                                       [3/4]│
├────────────────────────────────────────────────────────┤
│ At current burn rate:                                  │
│ • 90% limit in:     ~22 minutes                        │
│ • Session end:      475K tokens ($2.38)                │
│ • Daily projected:  1.2M tokens ($6.00)                │
└────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────┐
│ TIMELINE (Last 24h)                               [4/4]│
├────────────────────────────────────────────────────────┤
│ ▁▂▃▅▇█▇▅▃▂▁ ▁ ▃▅▇█▇▅▃                                  │
│ 00 03 06 09 12 15 18 21                                │
│ Peak: 12:00-17:00 | Quiet: 00:00-06:00                 │
└────────────────────────────────────────────────────────┘

┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ [/] Commands  [Space] Pause  [?] Help  [q] Quit         ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

### 5.2 Daily View

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Dashboard │ Daily │ Monthly │ Agents           14:32:15 ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

┌────────────────────────────────────────────────────────┐
│ DAILY USAGE                                   [SORTED] │
├────────────────────────────────────────────────────────┤
│ Date       Tokens    Cost      Models       Δ vs Avg   │
├────────────────────────────────────────────────────────┤
│►2025-12-13 425K     $2.15     S4.5, O4     +15%       │
│ 2025-12-12 380K     $1.92     S4.5         +3%        │
│ 2025-12-11 360K     $1.82     S4.5         -2%        │
│ 2025-12-10 420K     $2.12     S4.5, O4     +14%       │
│ 2025-12-09 310K     $1.55     S4.5         -16%       │
│ ...                                                    │
├────────────────────────────────────────────────────────┤
│ 7-day avg: 369K tokens | $1.86/day                     │
└────────────────────────────────────────────────────────┘

┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ [↑↓] Navigate  [Enter] Details  [s] Sort  [c] Compare   ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

### 5.3 Agents View

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Dashboard │ Daily │ Monthly │ Agents           14:32:15 ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

┌────────────────────────────────────────────────────────┐
│ AGENTS [8 active, 3 subagents]                [FILTER] │
├────────────────────────────────────────────────────────┤
│ Agent             Last Action       Tokens     Health  │
├────────────────────────────────────────────────────────┤
│►● Explore-8d71   Reading src/...   125K       Normal   │
│ ● Plan-a3f2      Writing tests     85K        Light    │
│ ○ QA-9b4c        Idle              42K        Light    │
│   └─ Sub-1f3d    Running pytest    12K        Light    │
│ ● Agent-5c8a     Analyzing data    310K       Heavy    │
├────────────────────────────────────────────────────────┤
│ Total: 574K tokens | Avg: 72K/agent                    │
└────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────┐
│ RELATIONSHIPS                                          │
├────────────────────────────────────────────────────────┤
│ Main → [Sub-1f3d, Sub-2a5b]                            │
│ Explore-8d71 → Plan-a3f2 (context shared)              │
└────────────────────────────────────────────────────────┘

┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ [↑↓] Navigate  [Enter] Details  [f] Filter  [r] Rels    ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

---

## 6. Progressive Disclosure

### Complexity Layers

**Layer 1: Essential (Always Visible)**
- Current usage percentage
- Active block status
- Time to reset
- Basic shortcuts in footer

**Layer 2: Contextual (On Demand)**
- Projections (when active block)
- Model breakdown (on drill-down)
- Alerts (when triggered)

**Layer 3: Advanced (Requires Navigation)**
- Historical comparisons
- Agent relationships
- What-if scenarios

### Density Modes

| Mode | Shortcut | Use Case |
|------|----------|----------|
| Compact | `Ctrl+-` | Minimal info, max screen |
| Normal | Default | Balanced |
| Detailed | `Ctrl++` | All metrics visible |

---

## 7. Terminal Constraints

### Minimum Requirements

| Constraint | Minimum | Recommended |
|------------|---------|-------------|
| Width | 60 chars | 80 chars |
| Height | 20 lines | 30 lines |
| Colors | 16 | 256 |
| Unicode | ASCII | Full |

### Graceful Degradation

**Small width (<80):**
- Tables become scrollable
- Multi-column layouts stack
- Less important columns hidden

**Small height (<30):**
- Panels become scrollable
- Footer shortcuts abbreviated
- Pagination for long lists

### Accessibility

- Color is never sole indicator
- Patterns/symbols for status (●/○, ✓/✗)
- High contrast mode available
- Keyboard-only navigation works fully
