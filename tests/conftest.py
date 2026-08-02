"""Pytest configuration and fixtures for Claude Monitor tests."""

import pytest
from unittest.mock import MagicMock, patch
from typing import Any, Dict, List


@pytest.fixture
def mock_orchestrator():
    """Create a mock MonitoringOrchestrator."""
    orchestrator = MagicMock()
    orchestrator.update_interval = 10
    orchestrator._update_callbacks = []
    orchestrator._session_callbacks = []

    def register_update_callback(callback):
        orchestrator._update_callbacks.append(callback)

    def register_session_callback(callback):
        orchestrator._session_callbacks.append(callback)

    orchestrator.register_update_callback = register_update_callback
    orchestrator.register_session_callback = register_session_callback
    orchestrator.start = MagicMock()
    orchestrator.stop = MagicMock()
    orchestrator.force_refresh = MagicMock()

    return orchestrator


@pytest.fixture
def mock_settings():
    """Create mock settings."""
    settings = MagicMock()
    settings.plan = "max20"
    settings.tui = True
    settings.timezone = "America/Los_Angeles"
    settings.refresh_rate = 10
    settings.log_level = "DEBUG"
    settings.log_file = None
    return settings


@pytest.fixture
def sample_blocks() -> List[Dict[str, Any]]:
    """Create sample usage blocks for testing.

    Note: burnRate is a dict with tokensPerMinute and costPerHour,
    matching the real data structure from the monitoring orchestrator.
    """
    return [
        {
            "startTime": "2024-12-14T10:00:00Z",
            "endTime": "2024-12-14T15:00:00Z",
            "totalTokens": 50000,
            "costUSD": 5.00,
            "isActive": True,
            "burnRate": {
                "tokensPerMinute": 166.67,
                "costPerHour": 2.50,
            },
            "durationMinutes": 300,
            "usagePercentage": 25.0,
            "perModelStats": {
                "claude-3-5-sonnet-20241022": {
                    "tokens": 40000,
                    "cost": 4.00,
                },
                "claude-3-5-haiku-20241022": {
                    "tokens": 10000,
                    "cost": 1.00,
                },
            },
        },
        {
            "startTime": "2024-12-13T08:00:00Z",
            "endTime": "2024-12-13T16:00:00Z",
            "totalTokens": 80000,
            "costUSD": 8.00,
            "isActive": False,
            "burnRate": {
                "tokensPerMinute": 166.67,
                "costPerHour": 2.50,
            },
            "durationMinutes": 480,
            "usagePercentage": 40.0,
            "perModelStats": {},
        },
        {
            "startTime": "2024-12-12T09:00:00Z",
            "endTime": "2024-12-12T17:00:00Z",
            "totalTokens": 60000,
            "costUSD": 6.00,
            "isActive": False,
            "burnRate": {
                "tokensPerMinute": 125.0,
                "costPerHour": 1.88,
            },
            "durationMinutes": 480,
            "usagePercentage": 30.0,
            "perModelStats": {},
        },
    ]


@pytest.fixture
def sample_monitoring_data(sample_blocks) -> Dict[str, Any]:
    """Create sample monitoring data."""
    return {
        "data": {
            "blocks": sample_blocks,
        },
        "token_limit": 200000,
        "args": MagicMock(plan="max20", timezone="UTC"),
        "session_id": "test-session-123",
        "session_count": 1,
    }


@pytest.fixture
def sample_agents() -> List[Dict[str, Any]]:
    """Create sample agent data for testing."""
    return [
        {
            "id": "agent-1",
            "name": "Main Session",
            "type": "Session",
            "tokens": 50000,
            "is_active": True,
            "context_percent": 25.0,
            "last_action": "Processing code",
            "parent_id": None,
        },
        {
            "id": "agent-2",
            "name": "Explore Agent",
            "type": "Explore",
            "tokens": 15000,
            "is_active": True,
            "context_percent": 60.0,
            "last_action": "Searching codebase",
            "parent_id": "agent-1",
        },
        {
            "id": "agent-3",
            "name": "Test Agent",
            "type": "Tester",
            "tokens": 8000,
            "is_active": False,
            "context_percent": 0,
            "last_action": "Completed",
            "parent_id": "agent-1",
        },
    ]
