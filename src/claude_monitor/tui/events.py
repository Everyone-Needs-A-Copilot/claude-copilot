"""Custom events for the TUI application."""

from typing import Any, Dict, Optional

from textual.message import Message


class DataUpdated(Message):
    """Posted when monitoring data is updated from the orchestrator."""

    def __init__(self, data: Dict[str, Any]) -> None:
        super().__init__()
        self.data = data


class SessionChanged(Message):
    """Posted when a session change is detected."""

    def __init__(self, event_type: str, session_id: str, session_data: Optional[Dict[str, Any]] = None) -> None:
        super().__init__()
        self.event_type = event_type
        self.session_id = session_id
        self.session_data = session_data


class PauseToggled(Message):
    """Posted when pause state is toggled."""

    def __init__(self, is_paused: bool) -> None:
        super().__init__()
        self.is_paused = is_paused


class ViewSwitched(Message):
    """Posted when the view is switched."""

    def __init__(self, view_name: str) -> None:
        super().__init__()
        self.view_name = view_name
