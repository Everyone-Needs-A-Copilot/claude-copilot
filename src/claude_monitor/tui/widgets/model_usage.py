"""Model usage distribution widget."""

from typing import Any, Dict, List

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class ModelUsageWidget(Widget):
    """Widget displaying per-model token usage breakdown."""

    DEFAULT_CSS = """
    ModelUsageWidget {
        height: auto;
        border: solid $primary;
        padding: 1;
        margin: 0 1 1 1;
    }

    ModelUsageWidget:focus-within {
        border: double $primary;
    }

    ModelUsageWidget .panel-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    ModelUsageWidget .model-row {
        height: 1;
    }

    ModelUsageWidget .model-name {
        width: 25;
    }

    ModelUsageWidget .model-bar {
        width: 1fr;
    }

    ModelUsageWidget .model-value {
        width: 15;
        text-align: right;
    }

    ModelUsageWidget .sonnet-color {
        color: $success;
    }

    ModelUsageWidget .opus-color {
        color: $warning;
    }

    ModelUsageWidget .haiku-color {
        color: cyan;
    }
    """

    model_stats: reactive[Dict[str, Any]] = reactive({}, always_update=True)
    total_tokens: reactive[int] = reactive(0)

    def compose(self) -> ComposeResult:
        """Compose the model usage widget layout."""
        with Vertical():
            yield Static("MODEL BREAKDOWN", classes="panel-title")
            yield Static("", id="model-content")

    def on_mount(self) -> None:
        """Initialize the widget."""
        self._update_display()

    def _get_model_display_name(self, model_id: str) -> str:
        """Get a display-friendly model name."""
        model_lower = model_id.lower()
        if "opus" in model_lower:
            return "Opus 4"
        elif "sonnet" in model_lower:
            return "Sonnet 4.5"
        elif "haiku" in model_lower:
            return "Haiku"
        return model_id[:20]

    def _get_model_color_class(self, model_id: str) -> str:
        """Get CSS class for model color."""
        model_lower = model_id.lower()
        if "opus" in model_lower:
            return "opus-color"
        elif "sonnet" in model_lower:
            return "sonnet-color"
        elif "haiku" in model_lower:
            return "haiku-color"
        return ""

    def _create_bar(self, percentage: float, width: int = 20) -> str:
        """Create a text-based progress bar."""
        filled = int(percentage / 100 * width)
        empty = width - filled
        return "█" * filled + "░" * empty

    def _update_display(self) -> None:
        """Update the display."""
        if not self.is_mounted:
            return

        try:
            content = self.query_one("#model-content", Static)

            if not self.model_stats or self.total_tokens == 0:
                content.update("No model data available")
                return

            lines: List[str] = []

            # Sort models by token usage
            sorted_models = sorted(
                self.model_stats.items(),
                key=lambda x: x[1].get("tokens", 0) if isinstance(x[1], dict) else 0,
                reverse=True,
            )

            for model_id, stats in sorted_models:
                if not isinstance(stats, dict):
                    continue

                tokens = stats.get("tokens", 0)
                cost = stats.get("cost", 0.0)

                # Calculate percentage
                if self.total_tokens > 0:
                    pct = (tokens / self.total_tokens) * 100
                else:
                    pct = 0

                # Format the row
                name = self._get_model_display_name(model_id)
                bar = self._create_bar(pct, 15)
                lines.append(f"{name:<20} {bar} {pct:5.1f}% ({tokens:,} tokens, ${cost:.2f})")

            if lines:
                content.update("\n".join(lines))
            else:
                content.update("No model data available")
        except Exception:
            pass  # Widget not fully mounted yet

    def watch_model_stats(self, value: Dict[str, Any]) -> None:
        """React to model stats changes."""
        if self.is_mounted:
            self._update_display()

    def watch_total_tokens(self, value: int) -> None:
        """React to total token changes."""
        if self.is_mounted:
            self._update_display()
