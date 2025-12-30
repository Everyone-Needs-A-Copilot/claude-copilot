"""Pytest configuration and shared fixtures for EPUB builder tests."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from build_epub import BuildState, EPUBConfig, setup_logging


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal project structure for testing."""
    # Create root markdown file
    readme = tmp_path / "README.md"
    readme.write_text("# Test Project\n\nThis is a test.")

    # Create a chapter directory
    chapter_dir = tmp_path / "01-test-chapter"
    chapter_dir.mkdir()
    (chapter_dir / "README.md").write_text("# Chapter Overview\n\nOverview content.")
    (chapter_dir / "section.md").write_text("# Section\n\nSection content.")

    # Create a proper PNG logo using PIL
    from PIL import Image as PILImage

    logo_path = tmp_path / "claude-howto-logo.png"
    img = PILImage.new("RGB", (100, 100), color=(26, 26, 46))
    img.save(logo_path, "PNG")

    return tmp_path


@pytest.fixture
def config(tmp_project: Path) -> EPUBConfig:
    """Create a test configuration."""
    return EPUBConfig(
        root_path=tmp_project,
        output_path=tmp_project / "test.epub",
    )


@pytest.fixture
def state() -> BuildState:
    """Create a fresh build state."""
    return BuildState()


@pytest.fixture
def logger() -> logging.Logger:
    """Create a test logger."""
    return setup_logging(verbose=False)
