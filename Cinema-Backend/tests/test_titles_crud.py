import time


def test_create_returns_created_resource(client, admin_headers, movie_payload):
    response = client.post("/api/titles", headers=admin_headers, json=movie_payload())
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Довод"
    assert body["type"] == "movie"
    assert body["episodes"] == []
    assert body["created_at"] and body["updated_at"]
    assert response.headers["Location"] == f"/api/titles/{body['id']}"


def test_create_trims_and_normalizes_input(client, admin_headers, movie_payload):
    body = client.post("/api/titles", headers=admin_headers, json=movie_payload(
        name="  Довод  ", description="  инверсия  ", embed_url="  https://p.tv/1  ",
    )).json()
    assert body["name"] == "Довод"
    assert body["description"] == "инверсия"
    assert body["embed_url"] == "https://p.tv/1"


def test_empty_strings_become_null(client, admin_headers, movie_payload):
    body = client.post("/api/titles", headers=admin_headers, json=movie_payload(
        description="", poster_url="",
    )).json()
    assert body["description"] is None
    assert body["poster_url"] is None


def test_get_returns_title_with_episodes(client, create_title, series_payload):
    created = create_title(series_payload())
    body = client.get(f"/api/titles/{created['id']}").json()
    assert body["id"] == created["id"]
    assert "title" not in body
    assert len(body["episodes"]) == 3


def test_get_missing_title_is_404(client):
    response = client.get("/api/titles/999999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "title_not_found"
    assert response.json()["error"]["details"]["title_id"] == 999999


def test_patch_changes_only_given_fields(client, admin_headers, create_title, movie_payload):
    created = create_title(movie_payload(genres=["Драма"]))
    body = client.patch(
        f"/api/titles/{created['id']}", headers=admin_headers, json={"year": 2021}
    ).json()
    assert body["year"] == 2021
    assert body["name"] == created["name"]
    assert len(body["genres"]) == 1


def test_patch_can_clear_nullable_field(client, admin_headers, create_title, movie_payload):
    created = create_title(movie_payload(description="было"))
    body = client.patch(
        f"/api/titles/{created['id']}", headers=admin_headers, json={"description": None}
    ).json()
    assert body["description"] is None


def test_patch_with_empty_body_is_rejected(client, admin_headers, create_title, movie_payload):
    created = create_title(movie_payload())
    response = client.patch(f"/api/titles/{created['id']}", headers=admin_headers, json={})
    assert response.status_code == 422


def test_patch_missing_title_is_404(client, admin_headers):
    response = client.patch("/api/titles/999999", headers=admin_headers, json={"year": 2000})
    assert response.status_code == 404


def test_put_replaces_whole_resource(client, admin_headers, create_title, movie_payload):
    created = create_title(movie_payload(genres=["Драма"], description="было"))
    body = client.put(f"/api/titles/{created['id']}", headers=admin_headers, json={
        "type": "movie", "name": "Довод", "embed_url": "https://p.tv/new",
    }).json()
    assert body["year"] is None
    assert body["genres"] == []
    assert body["description"] is None
    assert body["embed_url"] == "https://p.tv/new"


def test_delete_removes_title(client, admin_headers, create_title, movie_payload):
    created = create_title(movie_payload())
    assert client.delete(f"/api/titles/{created['id']}", headers=admin_headers).status_code == 204
    assert client.get(f"/api/titles/{created['id']}").status_code == 404
    assert client.delete(f"/api/titles/{created['id']}", headers=admin_headers).status_code == 404


def test_delete_cascades_to_episodes(client, admin_headers, create_title, series_payload, db_session):
    from sqlalchemy import func, select

    from app.db.models import Episode

    created = create_title(series_payload())
    client.delete(f"/api/titles/{created['id']}", headers=admin_headers)
    left = db_session.execute(
        select(func.count()).select_from(Episode).where(Episode.title_id == created["id"])
    ).scalar_one()
    assert left == 0


def test_created_at_is_stable_and_updated_at_grows(client, admin_headers, create_title, movie_payload):
    created = create_title(movie_payload())
    time.sleep(1.1)
    updated = client.patch(
        f"/api/titles/{created['id']}", headers=admin_headers, json={"year": 1999}
    ).json()
    assert updated["created_at"] == created["created_at"]
    assert updated["updated_at"] > created["updated_at"]
