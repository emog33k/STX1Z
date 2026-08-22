import pytest

from app.core.exceptions import (
    AppError,
    AuthenticationError,
    ConflictError,
    DuplicateTitleError,
    NotFoundError,
    PermissionDeniedError,
    TitleNotFoundError,
    ValidationError,
)


def test_unknown_route_uses_common_error_shape(client):
    response = client.get("/api/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert "request_id" in response.json()


def test_method_not_allowed_uses_common_error_shape(client):
    response = client.request("DELETE", "/api/titles")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_broken_json_is_reported_as_validation_error(client, admin_headers):
    response = client.post(
        "/api/titles",
        headers={**admin_headers, "Content-Type": "application/json"},
        content=b"{ broken",
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_error_carries_request_id_matching_header(client):
    response = client.get("/api/titles/999999")
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_error_body_always_has_details_object(client):
    body = client.get("/api/titles/999999").json()
    assert isinstance(body["error"]["details"], dict)


@pytest.mark.parametrize("error, expected_status", [
    (TitleNotFoundError(1), 404),
    (NotFoundError("нет"), 404),
    (ValidationError("плохо"), 422),
    (DuplicateTitleError("X", 2020), 409),
    (ConflictError("занято"), 409),
    (AuthenticationError(), 401),
    (PermissionDeniedError(), 403),
    (AppError("что-то своё"), 500),
])
def test_domain_error_maps_to_status(error, expected_status):
    from app.core.errors import _status_for

    assert _status_for(error) == expected_status


def test_domain_errors_keep_machine_readable_codes():
    assert TitleNotFoundError(5).code == "title_not_found"
    assert TitleNotFoundError(5).details == {"title_id": 5}
    assert DuplicateTitleError("X", None).details == {"name": "X", "year": None}
    assert ValidationError("плохо", field="name").details == {"field": "name"}


def test_service_layer_does_not_depend_on_web_framework():
    import inspect

    import app.services.titles as service_module

    source = inspect.getsource(service_module)
    assert "fastapi" not in source
    assert "sqlalchemy" not in source


def test_repositories_do_not_depend_on_web_framework():
    import inspect

    import app.repositories.titles as repo_module

    assert "fastapi" not in inspect.getsource(repo_module)


def test_cors_allows_configured_origin(client):
    response = client.options("/api/titles", headers={
        "Origin": "https://usermode.cfd",
        "Access-Control-Request-Method": "POST",
    })
    assert response.headers["access-control-allow-origin"] == "https://usermode.cfd"


def test_cors_rejects_unknown_origin(client):
    response = client.options("/api/titles", headers={
        "Origin": "https://evil.example",
        "Access-Control-Request-Method": "POST",
    })
    assert "access-control-allow-origin" not in response.headers


def test_openapi_documents_error_responses(client):
    spec = client.get("/openapi.json").json()
    responses = spec["paths"]["/api/titles"]["post"]["responses"]
    assert {"201", "401", "403", "409", "422"} <= set(responses)


def test_openapi_exposes_all_write_methods(client):
    spec = client.get("/openapi.json").json()
    assert {"get", "put", "patch", "delete"} <= set(spec["paths"]["/api/titles/{title_id}"])
