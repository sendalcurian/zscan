"""Test configuration and fixtures for zscan."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir() -> Path:
    """Create a temporary directory for tests.

    Yields:
        Path to temporary directory that is cleaned up after test.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def warehouse_path(temp_dir: Path) -> Path:
    """Create a temporary warehouse path.

    Args:
        temp_dir: Temporary directory fixture.

    Returns:
        Path to warehouse directory.
    """
    warehouse = temp_dir / "warehouse"
    warehouse.mkdir(parents=True, exist_ok=True)
    return warehouse
