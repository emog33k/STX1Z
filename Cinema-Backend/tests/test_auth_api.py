import pytest

WRITE_REQUESTS = [
    ("post", "/api/titles"),
    ("put", "/api/titles/1"),
    ("patch", "/api/titles/1"),
    ("delete", "/api/titles/1"),
]


def _write(client, method, url, **kwargs):
    if method != "delete":
        kwargs["json"] = {"name": "X"}
    return client.request(method.upper(), url, **kwargs)


@pytest.mark.parametrize("method, url", WRITE_REQUESTS)
def test_write_without_credentials_is_unauthorized(client, method, url):
    response = _write(client, method, url)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.headers["WWW-Authenticate"] == "tma"


@pytest.mark.parametrize("method, url", WRITE_REQUESTS)
def test_write_by_non_admin_is_forbidden(client, stranger_headers, method, url):
    response = _write(client, method, url, headers=stranger_headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_tampered_signature_is_unauthorized(client, movie_payload, init_data, auth_header, admin_id):
    raw = init_data(admin_id)
    headers = auth_header(raw[:-4] + "0000")
    response = client.post("/api/titles", headers=headers, json=movie_payload())
    assert response.status_code == 401


def test_stale_init_data_is_unauthorized(client, movie_payload, init_data, auth_header, admin_id):
    headers = auth_header(init_data(admin_id, age_seconds=200_000))
    response = client.post("/api/titles", headers=headers, json=movie_payload())
    assert response.status_code == 401


def test_init_data_accepted_from_dedicated_header(client, movie_payload, init_data, admin_id):
    headers = {"X-Telegram-Init-Data": init_data(admin_id)}
    response = client.post("/api/titles", headers=headers, json=movie_payload())
    assert response.status_code == 201


def test_init_data_in_query_is_ignored_outside_debug(client, movie_payload, init_data, admin_id):
    response = client.post(
        "/api/titles",
        params={"init_data": init_data(admin_id)},
        json=movie_payload(),
    )
    assert response.status_code == 401


def test_wrong_auth_scheme_is_ignored(client, movie_payload, init_data, admin_id):
    headers = {"Authorization": f"Bearer {init_data(admin_id)}"}
    response = client.post("/api/titles", headers=headers, json=movie_payload())
    assert response.status_code == 401


def test_reading_catalog_needs_no_auth(client):
    assert client.get("/api/titles").status_code == 200


def test_me_returns_admin_flag(client, admin_headers, admin_id):
    body = client.get("/api/me", headers=admin_headers).json()
    assert body["id"] == admin_id
    assert body["is_admin"] is True


def test_me_for_stranger_is_not_admin(client, stranger_headers):
    assert client.get("/api/me", headers=stranger_headers).json()["is_admin"] is False


def test_me_requires_init_data(client):
    assert client.get("/api/me").status_code == 401
