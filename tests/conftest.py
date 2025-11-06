"""
tests/conftest.py

Configuration for pytest.
"""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def tests_root() -> Path:
    """
    Root directory for tests.
    Returns:
        Path to the tests directory.
    """
    return Path(__file__).parent.resolve()


@pytest.fixture(scope="session")
def data_dir(tests_root: Path) -> Path:
    """
    Directory containing test data files.
    Returns:
        Path to tests/data.
    """
    d = tests_root / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture(scope="session")
def input_data_dir(data_dir: Path) -> Path:
    """
    Directory containing input test data files.
    Returns:
        Path to tests/data/input.
    """
    d = data_dir / "input"
    d.mkdir(parents=True, exist_ok=True)
    return d
