import sys
import os
import tempfile
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Set database path and data source mode to simulation before any app imports
temp_db = tempfile.NamedTemporaryFile(delete=False)
os.environ["DATABASE_PATH"] = temp_db.name
os.environ["DATA_SOURCE_MODE"] = "simulation"

from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture(scope="session", autouse=True)
def cleanup():
    yield
    # Clean up the temporary database after all tests
    try:
        temp_db.close()
        os.unlink(temp_db.name)
    except Exception:
        pass
