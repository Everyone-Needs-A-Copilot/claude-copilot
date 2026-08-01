"""Agent data table widget for agents view."""

from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import DataTable


class AgentDataTable(Widget):
    """Data table for displaying agent activity."""

    DEFAULT_CSS = """
    AgentDataTable {
        height: 1fr;
    }

    AgentDataTable DataTable {
        height: 100%;
    }
    """

    agents: reactive[List[Dict[str, Any]]] = reactive([], always_update=True)
    filter_text: reactive[str] = reactive("")
    show_inactive: reactive[bool] = reactive(False)
    sort_column: reactive[str] = reactive("tokens")
    sort_reverse: reactive[bool] = reactive(True)

    def compose(self) -> ComposeResult:
        """Compose the data table."""
        yield DataTable(id="agent-data-table")

    def on_mount(self) -> None:
        """Initialize the table."""
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        self._setup_columns()
        self._load_data()

    def _setup_columns(self) -> None:
        """Setup table columns."""
        table = self.query_one(DataTable)
        table.clear(columns=True)

        table.add_column("Status", key="status", width=3)
        table.add_column("Agent", key="name", width=20)
        table.add_column("Type", key="type", width=12)
        table.add_column("Tokens", key="tokens", width=12)
        table.add_column("Context %", key="context", width=10)
        table.add_column("Last Action", key="action")

    def _filter_agents(self) -> List[Dict[str, Any]]:
        """Filter agents based on current filter settings."""
        filtered = []

        for agent in self.agents:
            # Filter by active state
            if not self.show_inactive and not agent.get("is_active", False):
                continue

            # Filter by text
            if self.filter_text:
                filter_lower = self.filter_text.lower()
                name = agent.get("name", "").lower()
                agent_type = agent.get("type", "").lower()
                if filter_lower not in name and filter_lower not in agent_type:
                    continue

            filtered.append(agent)

        return filtered

    def _load_data(self) -> None:
        """Load data into the table."""
        table = self.query_one(DataTable)
        table.clear()

        filtered = self._filter_agents()

        if not filtered:
            table.add_row("--", "No agents", "--", "--", "--", "--")
            return

        # Sort data
        sorted_agents = sorted(
            filtered,
            key=lambda x: x.get(self.sort_column, 0) if isinstance(x.get(self.sort_column), (int, float)) else str(x.get(self.sort_column, "")),
            reverse=self.sort_reverse,
        )

        for agent in sorted_agents:
            # Status indicator
            if agent.get("is_active"):
                status = "[green]●[/]"
            else:
                status = "[dim]○[/]"

            # Agent name (with hierarchy indicator for subagents)
            name = agent.get("name", "Unknown")[:20]
            if agent.get("parent_id"):
                name = f"  └─ {name}"

            # Type
            agent_type = agent.get("type", "Unknown")[:12]

            # Tokens
            tokens = agent.get("tokens", 0)
            tokens_str = f"{tokens:,}" if tokens else "--"

            # Context percentage
            context_pct = agent.get("context_percent", 0)
            if context_pct > 80:
                context_str = f"[red]{context_pct:.0f}%[/]"
            elif context_pct > 60:
                context_str = f"[yellow]{context_pct:.0f}%[/]"
            else:
                context_str = f"{context_pct:.0f}%"

            # Last action
            last_action = agent.get("last_action", "--")[:30]

            table.add_row(status, name, agent_type, tokens_str, context_str, last_action)

    def watch_agents(self, value: List[Dict[str, Any]]) -> None:
        """React to agent data changes."""
        self._load_data()

    def watch_filter_text(self, value: str) -> None:
        """React to filter changes."""
        self._load_data()

    def watch_show_inactive(self, value: bool) -> None:
        """React to inactive filter changes."""
        self._load_data()

    def watch_sort_column(self, value: str) -> None:
        """React to sort column changes."""
        self._load_data()

    def watch_sort_reverse(self, value: bool) -> None:
        """React to sort direction changes."""
        self._load_data()

    def sort_by(self, column: str) -> None:
        """Sort by the specified column."""
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = True

    def get_selected_agent(self) -> Optional[Dict[str, Any]]:
        """Get the currently selected agent data."""
        table = self.query_one(DataTable)
        filtered = self._filter_agents()
        if table.cursor_row is not None and filtered:
            idx = table.cursor_row
            if 0 <= idx < len(filtered):
                return filtered[idx]
        return None

    def set_filter(self, text: str) -> None:
        """Set the filter text."""
        self.filter_text = text

    def clear_filter(self) -> None:
        """Clear the filter."""
        self.filter_text = ""
        self.show_inactive = False
