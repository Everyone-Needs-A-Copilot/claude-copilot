# Technical Architecture: Rich to Textual Migration

> Module Structure, Data Flow, State Management, and Implementation Guide

---

## 1. Migration Strategy

### Approach: Parallel Development

**Rationale**: Textual and Rich are compatible (Textual is built on Rich). We can:

1. Create new `tui/` module alongside existing `ui/`
2. Develop Textual app iteratively
3. Add `--tui` flag to switch between modes
4. Eventually deprecate Rich-only mode

**Benefits**:
- No disruption to existing users
- Gradual testing and refinement
- Easy rollback if issues arise

---

## 2. Current Architecture

### Existing Module Structure

```
src/claude_monitor/
├── cli/
│   ├── main.py              # Entry point, Rich Live display
│   └── bootstrap.py         # Environment setup
├── core/
│   ├── models.py            # UsageEntry, SessionBlock, AgentActivity
│   ├── calculations.py      # Burn rate, projections
│   ├── plans.py             # Plan definitions, token limits
│   ├── settings.py          # Pydantic settings, CLI args
│   └── plan_detector.py     # Auto-detection logic
├── data/
│   ├── reader.py            # JSONL file parsing
│   ├── analysis.py          # analyze_usage() main entry
│   ├── analyzer.py          # SessionAnalyzer, limit detection
│   ├── aggregator.py        # Daily/monthly aggregation
│   ├── agent_reader.py      # Agent activity loading
│   └── agent_analyzer.py    # Agent snapshot creation
├── monitoring/
│   ├── orchestrator.py      # MonitoringOrchestrator
│   ├── data_manager.py      # DataManager (caching)
│   └── session_monitor.py   # Session change tracking
├── ui/                       # <<< TO BE REPLACED >>>
│   ├── layouts.py           # HeaderManager, ScreenManager
│   ├── components.py        # VelocityIndicator, etc.
│   ├── display_controller.py
│   ├── session_display.py
│   ├── progress_bars.py
│   ├── agent_display.py
│   └── table_views.py
├── terminal/
│   ├── manager.py           # Terminal setup/restore
│   └── themes.py            # ThemeManager
└── utils/
    ├── time_utils.py
    ├── formatting.py
    └── notifications.py
```

### Current Data Flow

```
JSONL Files (~/.claude/projects/)
        │
        ▼
data/reader.py::load_usage_entries()
        │
        ▼
data/analysis.py::analyze_usage()
        │
        ▼
core/models.py::SessionBlock (list)
        │
        ▼
monitoring/orchestrator.py (threading, callbacks)
        │
        ▼
ui/display_controller.py
        │
        ▼
Rich Live display
```

---

## 3. New Architecture

### New Module Structure

```
src/claude_monitor/
├── tui/                          # NEW
│   ├── __init__.py
│   ├── app.py                    # ClaudeMonitorApp
│   ├── screens/
│   │   ├── __init__.py
│   │   ├── base.py               # BaseMonitorScreen
│   │   ├── dashboard.py          # DashboardScreen
│   │   ├── daily.py              # DailyScreen
│   │   ├── monthly.py            # MonthlyScreen
│   │   ├── agents.py             # AgentsScreen
│   │   └── detail.py             # DetailScreen (modal)
│   ├── widgets/
│   │   ├── __init__.py
│   │   ├── usage_panel.py        # UsagePanel
│   │   ├── progress_bars.py      # TokenBar, CostBar, TimeBar
│   │   ├── burn_rate.py          # BurnRateWidget
│   │   ├── predictions.py        # PredictionsPanel
│   │   ├── model_usage.py        # ModelDistributionWidget
│   │   ├── agent_table.py        # AgentDataTable
│   │   ├── session_table.py      # SessionDataTable
│   │   ├── header.py             # HeaderWidget
│   │   ├── footer.py             # FooterWidget
│   │   └── filter_bar.py         # FilterInput
│   ├── state/
│   │   ├── __init__.py
│   │   ├── app_state.py          # AppState
│   │   ├── actions.py            # State mutations
│   │   └── selectors.py          # Derived state
│   ├── bindings.py               # Keyboard bindings
│   ├── styles.tcss               # Textual CSS
│   └── events.py                 # Custom events
├── ui/                           # KEEP for compatibility
│   └── ...
```

### Module Responsibilities

| Module | Purpose |
|--------|---------|
| `tui/app.py` | Main App class, orchestrator integration |
| `tui/screens/` | Screen classes for each view |
| `tui/widgets/` | Reusable widget components |
| `tui/state/` | Centralized reactive state |
| `tui/bindings.py` | Keyboard configuration |
| `tui/styles.tcss` | CSS-like theming |

---

## 4. Application Class

```python
# tui/app.py

from textual.app import App, ComposeResult
from textual.binding import Binding

class ClaudeMonitorApp(App):
    """Interactive Claude Code Usage Monitor TUI."""

    CSS_PATH = "styles.tcss"
    TITLE = "Claude Code Usage Monitor"

    BINDINGS = [
        Binding("1", "switch_screen('dashboard')", "Dashboard"),
        Binding("2", "switch_screen('daily')", "Daily"),
        Binding("3", "switch_screen('monthly')", "Monthly"),
        Binding("4", "switch_screen('agents')", "Agents"),
        Binding("space", "toggle_pause", "Pause"),
        Binding("r", "refresh", "Refresh"),
        Binding("/", "command_palette", "Commands"),
        Binding("?", "show_help", "Help"),
        Binding("q", "quit", "Quit"),
    ]

    SCREENS = {
        "dashboard": DashboardScreen,
        "daily": DailyScreen,
        "monthly": MonthlyScreen,
        "agents": AgentsScreen,
    }

    def __init__(self, orchestrator, settings):
        super().__init__()
        self.orchestrator = orchestrator
        self.settings = settings
        self.state = AppState(settings)

    def on_mount(self) -> None:
        self.orchestrator.register_update_callback(self._on_data_update)
        self.orchestrator.start()
        self.push_screen("dashboard")

    def _on_data_update(self, data: dict) -> None:
        # Thread-safe UI update
        self.call_from_thread(self.state.update_data, data)
```

---

## 5. State Management

### Centralized AppState

```python
# tui/state/app_state.py

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

@dataclass
class SessionState:
    """Current active session."""
    tokens_used: int = 0
    token_limit: int = 44_000
    cost_used: float = 0.0
    burn_rate: float = 0.0
    usage_percentage: float = 0.0
    elapsed_minutes: float = 0.0
    reset_time: Optional[datetime] = None
    per_model_stats: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AppState:
    """Central application state."""

    # UI state
    is_paused: bool = False
    is_loading: bool = True
    current_view: str = "dashboard"
    last_refresh: Optional[datetime] = None

    # Session data
    session: SessionState = field(default_factory=SessionState)

    # Historical data
    blocks: List[Dict[str, Any]] = field(default_factory=list)

    # Agent data
    agents: List[Dict[str, Any]] = field(default_factory=list)

    # Filter state
    filter_text: str = ""

    def update_data(self, monitoring_data: Dict[str, Any]) -> None:
        """Update state from orchestrator."""
        if self.is_paused:
            return

        # Extract and update session data
        data = monitoring_data.get("data", {})
        blocks = data.get("blocks", [])
        active = next((b for b in blocks if b.get("isActive")), None)

        if active:
            self.session.tokens_used = active.get("totalTokens", 0)
            self.session.cost_used = active.get("costUSD", 0.0)
            # ... more updates

        self.blocks = blocks
        self.last_refresh = datetime.now()
        self.is_loading = False

    def toggle_paused(self) -> None:
        self.is_paused = not self.is_paused
```

### State Flow

```
MonitoringOrchestrator (background thread)
        │
        │  callback
        ▼
ClaudeMonitorApp.call_from_thread()
        │
        ▼
AppState.update_data()
        │
        │  reactive changes
        ▼
Textual Reactivity → Widget updates
```

---

## 6. Screen Examples

### Dashboard Screen

```python
# tui/screens/dashboard.py

from textual.app import ComposeResult
from textual.screen import Screen
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static

from claude_monitor.tui.widgets import (
    HeaderWidget,
    FooterWidget,
    UsagePanel,
    BurnRateWidget,
    PredictionsPanel,
    TimelineWidget,
)


class DashboardScreen(Screen):
    """Real-time monitoring dashboard."""

    BINDINGS = [
        ("m", "show_models", "Models"),
        ("w", "show_whatif", "What-If"),
        ("z", "zoom_timeline", "Zoom"),
    ]

    def compose(self) -> ComposeResult:
        yield HeaderWidget()

        with Vertical():
            yield UsagePanel(id="overview")

            with Horizontal():
                yield BurnRateWidget(id="burn-rate")
                yield PredictionsPanel(id="predictions")

            yield TimelineWidget(id="timeline")

        yield FooterWidget()

    def on_mount(self) -> None:
        # Subscribe to state updates
        self.app.state.watch("session", self._update_display)

    def _update_display(self, session) -> None:
        panel = self.query_one("#overview", UsagePanel)
        panel.tokens_used = session.tokens_used
        panel.token_limit = session.token_limit
```

---

## 7. Widget Examples

### Usage Panel

```python
# tui/widgets/usage_panel.py

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import ProgressBar, Static


class UsagePanel(Widget):
    """Token, cost, and message usage display."""

    tokens_used: reactive[int] = reactive(0)
    token_limit: reactive[int] = reactive(44_000)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("OVERVIEW", classes="panel-title")
            yield TokenBar()
            yield CostBar()
            yield Static("", id="usage-summary")

    def watch_tokens_used(self, value: int) -> None:
        """React to token changes."""
        bar = self.query_one(TokenBar)
        bar.progress = value / self.token_limit

        summary = self.query_one("#usage-summary")
        pct = (value / self.token_limit) * 100
        summary.update(f"{value:,} / {self.token_limit:,} ({pct:.1f}%)")
```

### Progress Bar

```python
# tui/widgets/progress_bars.py

from textual.widgets import ProgressBar


class TokenBar(ProgressBar):
    """Token usage progress bar with thresholds."""

    DEFAULT_CSS = """
    TokenBar {
        height: 1;
    }
    TokenBar > .bar--bar {
        color: $success;
    }
    TokenBar.warning > .bar--bar {
        color: $warning;
    }
    TokenBar.critical > .bar--bar {
        color: $error;
    }
    """

    def watch_progress(self, progress: float) -> None:
        """Update styling based on usage level."""
        self.remove_class("warning", "critical")
        if progress >= 0.9:
            self.add_class("critical")
        elif progress >= 0.75:
            self.add_class("warning")
```

---

## 8. Styling (TCSS)

```css
/* tui/styles.tcss */

/* Theme variables */
$success: green;
$warning: yellow;
$error: red;
$primary: cyan;
$secondary: blue;

/* Base layout */
Screen {
    layout: vertical;
}

/* Panels */
.panel {
    border: solid $primary;
    padding: 1;
    margin: 0 1;
}

.panel-title {
    text-style: bold;
    color: $primary;
}

/* Header */
HeaderWidget {
    dock: top;
    height: 3;
    background: $surface;
}

/* Footer */
FooterWidget {
    dock: bottom;
    height: 1;
}

/* Focus indicators */
.panel:focus-within {
    border: double $primary;
}
```

---

## 9. Module Reuse

### Modules to Keep (No Changes)

| Module | Reason |
|--------|--------|
| `core/models.py` | UI-agnostic data models |
| `core/calculations.py` | Pure logic |
| `core/plans.py` | Plan definitions |
| `core/settings.py` | Settings work same |
| `data/*` | All data loading |
| `monitoring/*` | Background monitoring |
| `utils/*` | All utilities |

### Modules to Replace

| Old | New |
|-----|-----|
| `ui/layouts.py` | `tui/widgets/header.py`, `footer.py` |
| `ui/display_controller.py` | `tui/app.py`, `tui/state/` |
| `ui/session_display.py` | `tui/screens/dashboard.py` |
| `ui/progress_bars.py` | `tui/widgets/progress_bars.py` |
| `ui/agent_display.py` | `tui/screens/agents.py` |
| `ui/table_views.py` | `tui/screens/daily.py`, `monthly.py` |

### Modules to Adapt

| Module | Changes |
|--------|---------|
| `terminal/themes.py` | Add TCSS variable generation |
| `cli/main.py` | Add `--tui` flag |

---

## 10. Thread Safety

Textual requires UI updates on main thread:

```python
def _on_data_update(self, data: dict) -> None:
    """Called from background thread."""
    # WRONG: Direct update from thread
    # self.state.update_data(data)

    # RIGHT: Use call_from_thread
    self.call_from_thread(self.state.update_data, data)
```

---

## 11. Testing Strategy

### Unit Tests

```python
# tests/tui/test_state.py

def test_state_updates_from_orchestrator():
    state = AppState()
    data = {"blocks": [{"isActive": True, "totalTokens": 5000}]}

    state.update_data(data)

    assert state.session.tokens_used == 5000
    assert not state.is_loading
```

### Widget Tests

```python
# tests/tui/test_widgets.py

from textual.pilot import Pilot

async def test_usage_panel_updates():
    async with ClaudeMonitorApp().run_test() as pilot:
        panel = pilot.app.query_one(UsagePanel)
        panel.tokens_used = 10000
        panel.token_limit = 44000

        await pilot.pause()

        assert "22.7%" in panel.query_one("#usage-summary").render()
```

### Integration Tests

```python
# tests/tui/test_navigation.py

async def test_view_switching():
    async with ClaudeMonitorApp().run_test() as pilot:
        await pilot.press("2")  # Switch to Daily
        assert isinstance(pilot.app.screen, DailyScreen)

        await pilot.press("4")  # Switch to Agents
        assert isinstance(pilot.app.screen, AgentsScreen)
```

---

## 12. Dependencies

```toml
# pyproject.toml

[project.dependencies]
textual = ">=0.47.0"

[project.optional-dependencies]
dev = [
    "textual-dev>=1.0.0",  # Dev tools
]
```

---

## 13. Entry Point Changes

```python
# cli/main.py

def main():
    settings = parse_args()

    if settings.tui:
        # New Textual TUI
        from claude_monitor.tui.app import ClaudeMonitorApp

        orchestrator = MonitoringOrchestrator(settings)
        app = ClaudeMonitorApp(orchestrator, settings)
        app.run()
    else:
        # Existing Rich display
        run_rich_monitor(settings)
```

---

## 14. File Listing

### New Files to Create

```
src/claude_monitor/tui/
├── __init__.py
├── app.py
├── bindings.py
├── events.py
├── styles.tcss
├── screens/
│   ├── __init__.py
│   ├── base.py
│   ├── dashboard.py
│   ├── daily.py
│   ├── monthly.py
│   ├── agents.py
│   └── detail.py
├── widgets/
│   ├── __init__.py
│   ├── usage_panel.py
│   ├── progress_bars.py
│   ├── burn_rate.py
│   ├── predictions.py
│   ├── model_usage.py
│   ├── agent_table.py
│   ├── session_table.py
│   ├── header.py
│   ├── footer.py
│   └── filter_bar.py
└── state/
    ├── __init__.py
    ├── app_state.py
    ├── actions.py
    └── selectors.py
```

### Files to Modify

| File | Change |
|------|--------|
| `cli/main.py` | Add `--tui` flag |
| `core/settings.py` | Add `tui: bool` field |
| `terminal/themes.py` | Add TCSS generation |
| `pyproject.toml` | Add textual dependency |
