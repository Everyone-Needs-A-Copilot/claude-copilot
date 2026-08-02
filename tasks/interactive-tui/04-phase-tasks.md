# Phase Tasks: Interactive TUI Implementation

> Detailed task breakdown for each implementation phase

---

## Phase 0: Foundation

**Goal:** Runnable Textual app skeleton with state management

### Tasks

- [ ] **0.1** Add `textual>=0.47.0` to pyproject.toml
- [ ] **0.2** Create `tui/` module directory structure
  ```
  src/claude_monitor/tui/
  ├── __init__.py
  ├── app.py
  ├── bindings.py
  ├── styles.tcss
  ├── screens/__init__.py
  ├── widgets/__init__.py
  └── state/__init__.py
  ```
- [ ] **0.3** Implement `ClaudeMonitorApp` skeleton in `tui/app.py`
  - Extend `textual.app.App`
  - Define BINDINGS and SCREENS
  - Wire up orchestrator callback
- [ ] **0.4** Implement `AppState` in `tui/state/app_state.py`
  - SessionState dataclass
  - AppState with reactive properties
  - `update_data()` method
  - `toggle_paused()` method
- [ ] **0.5** Add `--tui` flag to CLI
  - Modify `core/settings.py` to add `tui: bool = False`
  - Modify `cli/main.py` to conditionally launch Textual app
- [ ] **0.6** Create base TCSS theme in `tui/styles.tcss`
  - Define color variables
  - Panel styling
  - Focus indicators
- [ ] **0.7** Create empty screen placeholders
  - `DashboardScreen`
  - `DailyScreen`
  - `MonthlyScreen`
  - `AgentsScreen`
- [ ] **0.8** Test: App launches with `--tui` flag
- [ ] **0.9** Test: State updates from orchestrator work

### Deliverables
- Running app with empty screen
- State updates working
- `--tui` flag functional

---

## Phase 1: Dashboard Screen

**Goal:** Functional real-time dashboard with visual parity to Rich version

### Tasks

- [ ] **1.1** Implement `HeaderWidget` in `tui/widgets/header.py`
  - Plan name display
  - Current time
  - Paused indicator
- [ ] **1.2** Implement `FooterWidget` in `tui/widgets/footer.py`
  - Keybinding hints
  - Last refresh time
- [ ] **1.3** Implement `TokenBar` in `tui/widgets/progress_bars.py`
  - Progress bar with percentage
  - Threshold-based coloring (normal/warning/critical)
- [ ] **1.4** Implement `CostBar` in `tui/widgets/progress_bars.py`
  - Cost display with projected end
- [ ] **1.5** Implement `UsagePanel` in `tui/widgets/usage_panel.py`
  - Compose TokenBar, CostBar
  - Summary text
  - Reactive to state changes
- [ ] **1.6** Implement `BurnRateWidget` in `tui/widgets/burn_rate.py`
  - Tokens per minute
  - Velocity indicator
- [ ] **1.7** Implement `PredictionsPanel` in `tui/widgets/predictions.py`
  - Time to limit
  - Session end projection
  - Daily projection
- [ ] **1.8** Implement `ModelDistributionWidget` in `tui/widgets/model_usage.py`
  - Per-model breakdown
  - Percentage bars
- [ ] **1.9** Implement `DashboardScreen` composition
  - Wire all widgets together
  - Subscribe to state
  - Handle focus navigation
- [ ] **1.10** Style dashboard with TCSS
  - Panel borders
  - Color scheme
  - Focus highlighting
- [ ] **1.11** Test: Dashboard displays current session data
- [ ] **1.12** Test: Live updates work (10s interval)
- [ ] **1.13** Test: Pause/Resume with Space key

### Deliverables
- Functional realtime dashboard
- Visual parity with Rich version
- Live updates working

---

## Phase 2: View Switching

**Goal:** All four views accessible with keyboard navigation

### Tasks

- [ ] **2.1** Implement `SessionDataTable` in `tui/widgets/session_table.py`
  - Sortable columns
  - Row selection
  - Scrollable
- [ ] **2.2** Implement `DailyScreen` in `tui/screens/daily.py`
  - SessionDataTable with daily data
  - 7-day summary
  - Sort controls (s key)
- [ ] **2.3** Implement `MonthlyScreen` in `tui/screens/monthly.py`
  - SessionDataTable with monthly data
  - 3-month summary
  - Trend sparklines (if feasible)
- [ ] **2.4** Implement `AgentDataTable` in `tui/widgets/agent_table.py`
  - Agent rows with status
  - Token usage
  - Health indicator
- [ ] **2.5** Implement `AgentsScreen` in `tui/screens/agents.py`
  - AgentDataTable
  - Relationships panel
  - Summary footer
- [ ] **2.6** Wire view switching (1-4 keys)
  - `action_switch_screen()` in app
  - Tab navigation
  - Screen transitions
- [ ] **2.7** Implement view-specific data loading
  - Lazy load daily/monthly data
  - Cache with TTL
- [ ] **2.8** Add view indicator to header
  - Current view highlighted
- [ ] **2.9** Test: Switch between all views
- [ ] **2.10** Test: Data loads correctly per view
- [ ] **2.11** Test: Sorting works in table views

### Deliverables
- All four views accessible
- View switching with 1-4 keys
- DataTable sorting and scrolling

---

## Phase 3: Interactivity

**Goal:** Focus navigation, drill-down, filtering, and command palette

### Tasks

- [ ] **3.1** Implement panel focus system
  - Focus chain within screens
  - Visual focus indicator
  - j/k navigation between panels
- [ ] **3.2** Implement `DetailScreen` modal in `tui/screens/detail.py`
  - Tab-based content (Models, Timeline, Tools)
  - Close with Esc
  - Overlay rendering
- [ ] **3.3** Add drill-down from dashboard
  - Enter on active block → BlockDetail
  - Model breakdown tab
  - Tool usage tab
- [ ] **3.4** Add drill-down from daily/monthly
  - Enter on row → DateDetail
  - Session breakdown
- [ ] **3.5** Add drill-down from agents
  - Enter on agent → AgentDetail
  - Context usage
  - Tool breakdown
- [ ] **3.6** Implement `FilterBar` in `tui/widgets/filter_bar.py`
  - Text input
  - Filter syntax parsing
  - Apply/clear buttons
- [ ] **3.7** Add filtering to agents view
  - f key opens filter
  - Filter by type, tokens, active
  - Visual filter indicator
- [ ] **3.8** Implement command palette
  - / key opens
  - Fuzzy search commands
  - Execute on Enter
- [ ] **3.9** Implement help overlay
  - ? key opens
  - Context-sensitive shortcuts
  - Dismiss with any key
- [ ] **3.10** Test: Panel focus navigation
- [ ] **3.11** Test: Drill-down and back navigation
- [ ] **3.12** Test: Filter application
- [ ] **3.13** Test: Command palette execution

### Deliverables
- Focusable panels with visual feedback
- Detail modals for drill-down
- Filter and search functionality
- Command palette

---

## Phase 4: Analysis Features

**Goal:** What-if scenarios, comparison mode, and advanced analytics

### Tasks

- [ ] **4.1** Implement what-if calculator modal
  - Slider for burn rate adjustment
  - Real-time projection updates
  - Close with Esc
- [ ] **4.2** Add what-if trigger (w key) to dashboard
  - Open modal from active block panel
  - Pre-populate current burn rate
- [ ] **4.3** Implement comparison mode
  - c key triggers selection
  - Baseline period picker
  - Comparison period picker
- [ ] **4.4** Implement comparison display
  - Side-by-side metrics
  - Delta highlighting (+/-)
  - Return to normal view
- [ ] **4.5** Add sparkline graphs to daily/monthly
  - Trend visualization
  - ASCII/Unicode rendering
- [ ] **4.6** Implement peak hours analysis
  - Aggregate by hour of day
  - Visual heatmap (if feasible)
- [ ] **4.7** Add model efficiency metrics
  - Cost per output token
  - Comparison across models
- [ ] **4.8** Test: What-if scenarios calculate correctly
- [ ] **4.9** Test: Comparison mode displays deltas
- [ ] **4.10** Test: Trends render correctly

### Deliverables
- What-if scenario UI
- Comparison view
- Trend visualizations

---

## Phase 5: Advanced Features

**Goal:** Alerts, relationships, polish, and deprecation

### Tasks

- [ ] **5.1** Implement settings screen
  - Alert configuration
  - Theme selection
  - Plan override
- [ ] **5.2** Implement alert thresholds
  - Token percentage alerts
  - Time remaining alerts
  - Cost alerts
- [ ] **5.3** Implement alert notifications
  - Visual indicator in header
  - Terminal bell (optional)
  - Alert history
- [ ] **5.4** Implement agent relationships view
  - Parent-child hierarchy
  - Context sharing visualization
- [ ] **5.5** Add density modes
  - Compact: Ctrl+-
  - Normal: Default
  - Detailed: Ctrl++
- [ ] **5.6** Performance optimization
  - Profile render times
  - Optimize data updates
  - Reduce unnecessary redraws
- [ ] **5.7** Accessibility review
  - Keyboard-only verification
  - Screen reader testing
  - High contrast mode
- [ ] **5.8** Documentation
  - Update README with TUI usage
  - Add keyboard shortcut reference
  - Migration guide from Rich UI
- [ ] **5.9** Add deprecation notices
  - Warning when using old Rich UI
  - Migration messaging
- [ ] **5.10** Archive old ui/ module
  - Move to _archive/ui_rich/
  - Update imports
- [ ] **5.11** Final testing
  - All features end-to-end
  - Edge cases
  - Small terminal handling
- [ ] **5.12** Release prep
  - Version bump
  - Changelog update
  - Tag release

### Deliverables
- Configurable alerts
- Agent relationships
- Complete documentation
- Production-ready TUI

---

## Task Dependencies

```
Phase 0 (Foundation)
    │
    ├── 0.1-0.6 can run in parallel
    │
    └── 0.7-0.9 depend on 0.1-0.6
           │
           ▼
Phase 1 (Dashboard)
    │
    ├── 1.1-1.8 can run in parallel
    │
    └── 1.9-1.13 depend on widgets
           │
           ▼
Phase 2 (Views)
    │
    ├── 2.1, 2.4 can run in parallel
    │
    └── 2.2-2.3, 2.5 depend on tables
           │
           ▼
Phase 3 (Interactivity)
    │
    ├── 3.1 (focus) blocks 3.2-3.5 (drill-down)
    │
    └── 3.6-3.9 can run in parallel after 3.1
           │
           ▼
Phase 4 (Analysis)
    │
    ├── 4.1-4.4 can run in parallel
    │
    └── 4.5-4.7 can run in parallel
           │
           ▼
Phase 5 (Polish)
    │
    └── All tasks sequential for quality
```

---

## Checkpoints

| Phase | Checkpoint | Verification |
|-------|------------|--------------|
| 0 | App launches | `claude-monitor --tui` shows blank screen |
| 1 | Dashboard works | Real-time data displays correctly |
| 2 | Views switch | 1-4 keys change views |
| 3 | Interactive | Drill-down and filter work |
| 4 | Analysis | What-if and comparison work |
| 5 | Release | All tests pass, docs complete |

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Textual API changes | Pin version, test before updates |
| Performance issues | Profile early, optimize Phase 5 |
| Scope creep | Strict phase boundaries |
| User resistance | Keep Rich UI available during transition |
