import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

TEST_DIR = Path(tempfile.mkdtemp(prefix="cinema-tests-"))
TEST_DB = TEST_DIR / "test.db"
BOT_TOKEN = "123456:TEST-BOT-TOKEN"
ADMIN_ID = 42
STRANGER_ID = 999

os.environ.update({
    "DATABASE_URL": f"sqlite:///{TEST_DB.as_posix()}",
    "BOT_TOKEN": BOT_TOKEN,
    "ADMIN_IDS": str(ADMIN_ID),
    "AUTH_REQUIRED": "true",
    "AUTO_UPGRADE_DB": "false",
    "DEBUG": "false",
    "CORS_ORIGINS": "https://usermode.cfd",
    "LOG_LEVEL": "CRITICAL",
    "DEFAULT_PAGE_SIZE": "20",
    "MAX_PAGE_SIZE": "100",
})

from fastapi.testclient import TestClient

from app.db.base import Base, SessionLocal, engine
from app.db.schema_state import upgrade_to_head
from app.main import app
from app.security.telegram import build_init_data


@pytest.fixture(scope="session")
def migrated_db():
    upgrade_to_head()
    yield
    engine.dispose()
    shutil.rmtree(TEST_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def client(migrated_db):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_tables(migrated_db):
    yield
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_init_data(user_id: int, *, age_seconds: int = 0, **user_fields) -> str:
    user = {"id": user_id, "first_name": "Tester"} | user_fields
    return build_init_data(BOT_TOKEN, {
        "auth_date": str(int(time.time()) - age_seconds),
        "query_id": "AAHtest",
        "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False),
    })


@pytest.fixture(scope="session")
def admin_id() -> int:
    return ADMIN_ID


@pytest.fixture(scope="session")
def stranger_id() -> int:
    return STRANGER_ID


@pytest.fixture(scope="session")
def bot_token() -> str:
    return BOT_TOKEN


@pytest.fixture(scope="session")
def init_data():
    return _make_init_data


@pytest.fixture(scope="session")
def auth_header():
    def factory(raw: str) -> dict[str, str]:
        return {"Authorization": f"tma {raw}"}
    return factory


@pytest.fixture
def admin_headers(auth_header, init_data) -> dict[str, str]:
    return auth_header(init_data(ADMIN_ID))


@pytest.fixture
def stranger_headers(auth_header, init_data) -> dict[str, str]:
    return auth_header(init_data(STRANGER_ID))


@pytest.fixture
def movie_payload():
    def factory(**overrides):
        return {
            "type": "movie",
            "name": "Довод",
            "year": 2020,
            "embed_url": "https://player.example/v/1",
        } | overrides
    return factory


@pytest.fixture
def series_payload():
    def factory(**overrides):
        return {
            "type": "series",
            "name": "Тьма",
            "year": 2017,
            "embed_url": "https://player.example/s/1",
            "episodes": [
                {"season_number": 1, "episode_number": 1, "name": "Тайны"},
                {"season_number": 1, "episode_number": 2, "name": "Ложь"},
                {"season_number": 2, "episode_number": 1, "name": "Начало"},
            ],
        } | overrides
    return factory


@pytest.fixture
def create_title(client, admin_headers):
    def factory(payload):
        response = client.post("/api/titles", headers=admin_headers, json=payload)
        assert response.status_code == 201, response.text
        return response.json()
    return factory
