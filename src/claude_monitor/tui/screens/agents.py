"""Agents activity screen."""

from typing import Any, Dict, List

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Input, Static

from claude_monitor.tui.events import DataUpdated
from claude_monitor.tui.screens.base import BaseMonitorScreen
from claude_monitor.tui.widgets import AgentDataTable


class AgentsScreen(BaseMonitorScreen):
    """Live agent activity screen.

    Shows active agents with their token usage and status.
    """

    DEFAULT_CSS = """
    AgentsScreen {
        layout: vertical;
        height: 1fr;
        width: 100%;
    }

    #agents-container {
        height: 1fr;
        width: 100%;
    }

    #agents-header {
        height: auto;
        border: solid $primary;
        padding: 1;
        margin: 0 1 1 1;
    }

    #filter-container {
        height: auto;
        margin: 0 1 1 1;
        display: none;
    }

    #filter-container.visible {
        display: block;
    }

    #agents-table-container {
        height: 1fr;
        margin: 0 1;
    }

    #relationships-panel {
        height: auto;
        border: solid $primary;
        padding: 1;
        margin: 0 1 1 1;
    }

    #agents-footer {
        height: auto;
        border: solid $primary;
        padding: 1;
        margin: 0 1 1 1;
    }
    """

    BINDINGS = [
        ("f", "toggle_filter", "Filter"),
        ("r", "show_relationships", "Relationships"),
        ("a", "show_all", "Show All"),
        ("i", "toggle_inactive", "Inactive"),
        ("enter", "show_details", "Details"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the agents view layout."""
        with Container(id="agents-container"):
            # Header
            with Vertical(id="agents-header"):
                yield Static("AGENTS", classes="panel-title")
                yield Static("Live agent activity", id="agents-subtitle", classes="muted")

            # Filter input (hidden by default)
            with Vertical(id="filter-container"):
                yield Input(placeholder="Filter agents by name or type...", id="filter-input")

            # Table
            with Vertical(id="agents-table-container"):
                yield AgentDataTable(id="agents-table")

            # Relationships panel
            with Vertical(id="relationships-panel"):
                yield Static("RELATIONSHIPS", classes="panel-title")
                yield Static("--", id="relationships-content")

            # Footer summary
            with Vertical(id="agents-footer"):
                yield Static("Summary: Loading...", id="agents-summary")

    def on_mount(self) -> None:
        """Handle screen mount."""
        self._load_data()

    def on_data_updated(self, event: DataUpdated) -> None:
        """Handle data update events."""
        self._load_data()

    def _load_data(self) -> None:
        """Load and display agent data from state."""
        # Get agents from state
        agents = self.state.agents

        # If no agent data in state, try to extract from blocks
        if not agents:
            agents = self._extract_agents_from_blocks(self.state.blocks)

        table = self.query_one("#agents-table", AgentDataTable)
        table.agents = agents

        # Update summary and relationships
        self._update_summary(agents)
        self._update_relationships(agents)

    def _extract_agents_from_blocks(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract agent info from blocks (placeholder)."""
        # This would be populated from the orchestrator with actual agent data
        # For now, return mock data showing the structure
        agents = []

        for block in blocks:
            if block.get("isActive"):
                agents.append({
                    "name": "Main Session",
                    "type": "Session",
                    "tokens": block.get("totalTokens", 0),
                    "is_active": True,
                    "context_percent": block.get("usagePercentage", 0),
                    "last_action": "Active monitoring",
                    "parent_id": None,
                })

        return agents

    def _update_summary(self, agents: List[Dict[str, Any]]) -> None:
        """Update the summary display."""
        summary = self.query_one("#agents-summary", Static)
        subtitle = self.query_one("#agents-subtitle", Static)

        if not agents:
            summary.update("Summary: No agents active")
            subtitle.update("Live agent activity")
            return

        active_count = sum(1 for a in agents if a.get("is_active"))
        total_tokens = sum(a.get("tokens", 0) for a in agents)
        subagents = sum(1 for a in agents if a.get("parent_id"))

        subtitle.update(f"{active_count} active, {subagents} subagents")
        summary.update(f"Total: {total_tokens:,} tokens | Agents: {len(agents)}")

    def _update_relationships(self, agents: List[Dict[str, Any]]) -> None:
        """Update the relationships display."""
        relationships = self.query_one("#relationships-content", Static)

        if not agents:
            relationships.update("No relationship data")
            return

        # Find parent-child relationships
        parents: Dict[str, List[str]] = {}
        for agent in agents:
            parent_id = agent.get("parent_id")
            if parent_id:
                if parent_id not in parents:
                    parents[parent_id] = []
                parents[parent_id].append(agent.get("name", "Unknown"))

        if parents:
            lines = []
            for parent_id, children in parents.items():
                parent_name = next(
                    (a.get("name") for a in agents if a.get("id") == parent_id),
                    parent_id
                )
                lines.append(f"{parent_name} → [{', '.join(children)}]")
            relationships.update("\n".join(lines) if lines else "No relationships")
        else:
            relationships.update("No parent-child relationships detected")

    def action_toggle_filter(self) -> None:
        """Toggle filter input visibility."""
        filter_container = self.query_one("#filter-container")
        if "visible" in filter_container.classes:
            filter_container.remove_class("visible")
            # Clear filter when hiding
            table = self.query_one("#agents-table", AgentDataTable)
            table.clear_filter()
        else:
            filter_container.add_class("visible")
            # Focus the input
            self.query_one("#filter-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle filter input changes."""
        if event.input.id == "filter-input":
            table = self.query_one("#agents-table", AgentDataTable)
            table.set_filter(event.value)

    def action_show_relationships(self) -> None:
        """Show agent relationships."""
        self.app.notify("Relationships panel shown below")

    def action_show_all(self) -> None:
        """Clear filters and show all agents."""
        table = self.query_one("#agents-table", AgentDataTable)
        table.clear_filter()
        table.show_inactive = True

        # Hide filter container
        filter_container = self.query_one("#filter-container")
        filter_container.remove_class("visible")

        self.app.notify("Showing all agents")

    def action_toggle_inactive(self) -> None:
        """Toggle showing inactive agents."""
        table = self.query_one("#agents-table", AgentDataTable)
        table.show_inactive = not table.show_inactive
        status = "shown" if table.show_inactive else "hidden"
        self.app.notify(f"Inactive agents {status}")

    def action_show_details(self) -> None:
        """Show details for selected agent."""
        table = self.query_one("#agents-table", AgentDataTable)
        selected = table.get_selected_agent()
        if selected:
            name = selected.get("name", "Unknown")
            tokens = selected.get("tokens", 0)
            self.app.notify(f"Agent: {name} ({tokens:,} tokens)")
        else:
            self.app.notify("No agent selected")
