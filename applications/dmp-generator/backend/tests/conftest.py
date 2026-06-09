import os
import shutil
import pytest
from fastapi.testclient import TestClient

os.environ["SECRET_KEY"] = "test-secret"

from app.main import app
from app.config import DATA_DIR, DB_PATH
from app.database import init_db


@pytest.fixture(autouse=True)
def clean_data():
    if os.path.exists(DATA_DIR):
        shutil.rmtree(DATA_DIR)
    os.makedirs(DATA_DIR, exist_ok=True)
    init_db(DB_PATH)
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers(client):
    client.post("/api/auth/register", json={"username": "tester", "password": "test123"})
    res = client.post("/api/auth/login", json={"username": "tester", "password": "test123"})
    token = res.json()["token"]
    return {"Authorization": f"Bearer {token}"}
