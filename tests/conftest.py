"""Shared test fixtures."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def petstore_v3_path():
    return str(FIXTURES_DIR / "petstore_v3.json")


@pytest.fixture
def petstore_v2_path():
    return str(FIXTURES_DIR / "petstore_v2.yaml")


@pytest.fixture
def minimal_spec_path():
    return str(FIXTURES_DIR / "minimal_spec.yaml")
