import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.config import _split_csv
from app.db.base import _engine_kwargs
from app.dependencies import get_title_service
from app.main import app
from app.repositories.uow import SqlAlchemyUnitOfWork


@pytest.fixture
def failing_client(migrated_db):
    def explode():
        raise RuntimeError("внутренний сбой")

    app.dependency_overrides[get_title_service] = explode
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_title_service, None)


def test_unexpected_error_returns_common_shape(failing_client):
    response = failing_client.get("/api/titles")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "Внутренняя ошибка сервера"


def test_unexpected_error_does_not_leak_details(failing_client):
    assert "внутренний сбой" not in failing_client.get("/api/titles").text


def test_unexpected_error_carries_request_id(failing_client):
    body = failing_client.get("/api/titles", headers={"X-Request-ID": "trace-500"}).json()
    assert body["request_id"] == "trace-500"


def test_unknown_integrity_error_falls_back_to_generic_message(db_session):
    uow = SqlAlchemyUnitOfWork(db_session)
    fake = IntegrityError("stmt", {}, Exception("что-то незнакомое"))
    assert "целостности" in uow._explain(fake)


@pytest.mark.parametrize("raw, expected", [
    (None, []),
    ("", []),
    ("a,b", ["a", "b"]),
    (["a", " b "], ["a", "b"]),
    (("a",), ["a"]),
    ({"a"}, ["a"]),
])
def test_split_csv_accepts_strings_and_sequences(raw, expected):
    assert sorted(_split_csv(raw)) == sorted(expected)


def test_split_csv_rejects_other_types():
    with pytest.raises(ValueError):
        _split_csv(42)


def test_engine_kwargs_for_sqlite():
    kwargs = _engine_kwargs()
    assert kwargs["connect_args"] == {"check_same_thread": False}
    assert "pool_size" not in kwargs


def test_engine_kwargs_for_server_database(monkeypatch):
    import app.db.base as database_module

    monkeypatch.setattr(database_module.settings, "database_url",
                        "postgresql+psycopg://u:p@host/db")
    kwargs = _engine_kwargs()
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_size"] == database_module.settings.db_pool_size
    assert "connect_args" not in kwargs
