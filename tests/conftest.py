import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"

@pytest.fixture
def test_ini_path():
    return str(FIXTURES_DIR / "test.ini")
