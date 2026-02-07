"""Root conftest for core tests."""

import pytest


@pytest.fixture
def project_dir(tmp_path):
    """Return a temporary project directory."""
    return tmp_path
