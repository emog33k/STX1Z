from app.db.base import get_db
from app.main import app


class BrokenSession:
    def execute(self, *args, **kwargs):
        raise RuntimeError("database is gone")


def test_health_reports_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_health_returns_503_when_database_is_down(client):
    app.dependency_overrides[get_db] = lambda: BrokenSession()
    try:
        response = client.get("/health")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"


def test_root_is_available(client):
    assert client.get("/").json()["status"] == "ok"


def test_request_id_is_returned_and_echoed(client):
    assert client.get("/health").headers["X-Request-ID"]

    response = client.get("/health", headers={"X-Request-ID": "trace-me"})
    assert response.headers["X-Request-ID"] == "trace-me"
