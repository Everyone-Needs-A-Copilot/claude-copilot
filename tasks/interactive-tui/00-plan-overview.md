# Interactive TUI Implementation Plan

> Transform Claude Code Usage Monitor from a read-only Rich dashboard to an interactive Textual TUI.

**Status:** Implementation Complete
**Created:** 2025-12-13
**Updated:** 2025-12-14
**Documents:** 4 supporting documents in this folder

---

## Vision

An interactive terminal experience that empowers developers to monitor, analyze, and control their Claude AI token usage through efficient keyboard-driven interactions—without breaking their development flow.

---

## Jobs To Be Done

### Primary Job
> "When using Claude Code, I want to understand my token consumption and remaining capacity so I can make informed decisions about my work session without interruption."

### Supporting Jobs

| Job | Success Metric |
|-----|----------------|
| **Session Planning** | Know budget before starting work |
| **Real-Time Awareness** | Glanceable status, no flow interruption |
| **Crisis Prevention** | Early warnings before hitting limits |
| **Historical Analysis** | Understand patterns to optimize usage |
| **Cost Control** | Track and optimize AI spend |

---

## Experience Principles

| Principle | Meaning |
|-----------|---------|
| **Flow-First Awareness** | Info is glanceable. Interaction is intentional. |
| **Context Over Data** | Show insights, not just numbers. Answer "so what?" |
| **Progressive Expertise** | Simple by default. Powerful when needed. |
| **Trust Through Transparency** | Show your work. Explain predictions. |
| **Proactive Partnership** | Anticipate needs. Suggest actions. |

---

## Feature Set

### Phase 1: Foundation
- [x] Textual app skeleton
- [x] Dashboard view with real-time updates
- [x] Basic keyboard navigation
- [x] Pause/Resume functionality

### Phase 2: Views
- [x] Daily aggregation view
- [x] Monthly aggregation view
- [x] Agents activity view
- [x] View switching (1-4 keys)

### Phase 3: Interactivity
- [x] Panel focus/navigation
- [x] Drill-down into details
- [x] Filter/search functionality
- [x] Help overlay (?)

### Phase 4: Analysis
- [x] What-if scenario calculator
- [ ] Comparison mode (today vs yesterday) - future
- [ ] Historical trends with sparklines - future
- [ ] Peak hours analysis - future

### Phase 5: Advanced
- [ ] Configurable alert thresholds - future
- [ ] Agent relationships view - future
- [ ] Model efficiency metrics - future
- [ ] Density modes (compact/normal/detailed) - future

---

## Technical Approach

**Framework Migration:** Rich → Textual (parallel development)

```
Current: Rich Live (read-only)
    ↓
New: Textual App (interactive)
    - Screen-based views
    - Widget composition
    - Reactive state
    - Keyboard events
```

**Key Technical Decisions:**
1. **Parallel development** - New `tui/` module alongside existing `ui/`
2. **Centralized state** - `AppState` dataclass with reactive properties
3. **Thread safety** - `call_from_thread()` for background updates
4. **TCSS theming** - Dark/light detection, CSS-like styling

---

## Implementation Summary

### Files Created

```
src/claude_monitor/tui/
├── __init__.py
├── app.py                 # ClaudeMonitorApp main class
├── bindings.py            # Keyboard bindings configuration
├── events.py              # Custom Textual events
├── styles.tcss            # Textual CSS theme
├── screens/
│   ├── __init__.py
│   ├── base.py            # BaseMonitorScreen class
│   ├── dashboard.py       # Real-time monitoring
│   ├── daily.py           # 7-day aggregation
│   ├── monthly.py         # 3-month aggregation
│   ├── agents.py          # Agent activity
│   ├── help.py            # Help overlay modal
│   └── whatif.py          # What-if calculator modal
├── widgets/
│   ├── __init__.py
│   ├── header.py          # App header
│   ├── footer.py          # App footer with hints
│   ├── usage_panel.py     # Token/cost overview
│   ├── progress_bars.py   # TokenBar, CostBar, TimeBar
│   ├── burn_rate.py       # Consumption rate display
│   ├── predictions.py     # Usage projections
│   ├── model_usage.py     # Per-model breakdown
│   ├── session_table.py   # Daily/monthly data table
│   └── agent_table.py     # Agent data table
└── state/
    ├── __init__.py
    └── app_state.py       # AppState, SessionState
```

### Files Modified

| File | Change |
|------|--------|
| `pyproject.toml` | Added textual>=0.47.0, textual-dev>=1.0.0 |
| `core/settings.py` | Added `tui: bool` field |
| `cli/main.py` | Added `_run_tui()` function, `--tui` flag handling |

---

## Usage

```bash
# Launch interactive TUI
claude-monitor --tui

# With specific plan
claude-monitor --tui --plan max5

# With custom refresh rate
claude-monitor --tui --refresh-rate 5
```

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `1-4` | Switch views |
| `Space` | Pause/Resume |
| `r` | Force refresh |
| `?` | Show help |
| `w` | What-if calculator |
| `q` | Quit |

---

## Documents

| Document | Purpose |
|----------|---------|
| [01-experience-design.md](./01-experience-design.md) | JTBD, user journey, struggling moments, principles |
| [02-interaction-design.md](./02-interaction-design.md) | Navigation, shortcuts, screen layouts, patterns |
| [03-technical-architecture.md](./03-technical-architecture.md) | Module structure, data flow, state management |
| [04-phase-tasks.md](./04-phase-tasks.md) | Detailed task breakdown by phase |

---

## Success Criteria

1. ✅ **Developers can check usage in <3 seconds** (glanceable dashboard)
2. ✅ **No mouse required for any task** (keyboard-first)
3. ✅ **Works on smallest reasonable terminal** (60x20 minimum)
4. ✅ **Advanced features discoverable but not intrusive**
5. ✅ **Users report feeling "in control" of their usage**

---

## Future Enhancements

1. Comparison mode (today vs yesterday)
2. Historical trends with sparklines
3. Peak hours analysis
4. Configurable alert thresholds
5. Agent relationships visualization
6. Model efficiency metrics
7. Density modes (compact/normal/detailed)
