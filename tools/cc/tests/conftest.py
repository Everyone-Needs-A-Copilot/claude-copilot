"""Shared test fixtures for cc CLI tests."""

import pytest
from typer.testing import CliRunner

from cc.main import app


@pytest.fixture
def runner() -> CliRunner:
    """Typer test runner."""
    return CliRunner()


@pytest.fixture
def cli(runner: CliRunner):
    """Return a callable that invokes CLI commands.

    Usage:
        result = cli(["version"])
    """
    def invoke(*args, **kwargs):
        return runner.invoke(app, *args, **kwargs)

    return invoke
