"""Keyboard bindings configuration for the TUI application."""

from textual.binding import Binding

# Global bindings available on all screens
GLOBAL_BINDINGS = [
    Binding("q", "quit", "Quit", priority=True),
    Binding("question_mark", "show_help", "Help"),
    Binding("slash", "command_palette", "Commands"),
    Binding("space", "toggle_pause", "Pause/Resume"),
    Binding("ctrl+r", "force_refresh", "Refresh"),
    Binding("ctrl+l", "redraw", "Redraw"),
]

# View switching bindings
VIEW_BINDINGS = [
    Binding("1", "switch_view('dashboard')", "Dashboard", show=True),
    Binding("2", "switch_view('daily')", "Daily", show=True),
    Binding("3", "switch_view('monthly')", "Monthly", show=True),
    Binding("4", "switch_view('agents')", "Agents", show=True),
]

# Navigation bindings within screens
NAVIGATION_BINDINGS = [
    Binding("j", "focus_next", "Next"),
    Binding("k", "focus_previous", "Previous"),
    Binding("down", "focus_next", "Next", show=False),
    Binding("up", "focus_previous", "Previous", show=False),
    Binding("enter", "select", "Select"),
    Binding("escape", "back", "Back"),
]
