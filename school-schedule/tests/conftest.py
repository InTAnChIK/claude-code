import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, security  # noqa: E402
from app.db import connection, init_db, now_iso  # noqa: E402
from app.seed import seed  # noqa: E402

PASSWORDS = {"zavuch": "admin-pass-123", "teacher": "teacher-pass-123", "teacher2": "teacher-pass-456"}


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    init_db()
    with connection() as conn:
        seed(conn)
        for username, role in (("zavuch", "admin"), ("teacher", "teacher"), ("teacher2", "teacher")):
            conn.execute(
                "INSERT INTO users (username, full_name, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (username, f"Тест {username}", security.hash_password(PASSWORDS[username]), role, now_iso()),
            )
    yield


def make_client(username: str | None = None) -> TestClient:
    from app.main import app

    client = TestClient(app)
    if username:
        r = client.post("/api/auth/login", json={"username": username, "password": PASSWORDS[username]})
        assert r.status_code == 200, r.text
        client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return client


@pytest.fixture
def anon():
    return make_client()


@pytest.fixture
def admin():
    return make_client("zavuch")


@pytest.fixture
def teacher():
    return make_client("teacher")


@pytest.fixture
def teacher2():
    return make_client("teacher2")
