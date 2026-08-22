import pytest


def test_genres_are_created_and_deduplicated(client, create_title, movie_payload):
    created = create_title(movie_payload(genres=["Фантастика", "фантастика", "  Боевик  "]))
    names = sorted(g["name"] for g in created["genres"])
    assert names == ["Боевик", "Фантастика"]


def test_same_genre_is_reused_across_titles(client, create_title, movie_payload, db_session):
    from sqlalchemy import func, select

    from app.db.models import Genre

    create_title(movie_payload(genres=["Драма"]))
    create_title(movie_payload(name="Другой", year=2001, genres=["драма"]))
    total = db_session.execute(select(func.count()).select_from(Genre)).scalar_one()
    assert total == 1


def test_genre_catalog_counts_titles(client, create_title, movie_payload):
    create_title(movie_payload(genres=["Драма", "Комедия"]))
    create_title(movie_payload(name="Второй", year=2001, genres=["Драма"]))
    catalog = {g["slug"]: g["titles_count"] for g in client.get("/api/genres").json()}
    assert catalog["драма"] == 2
    assert catalog["комедия"] == 1


def test_genre_slug_is_normalized(client, create_title, movie_payload):
    create_title(movie_payload(genres=["Научная  Фантастика"]))
    slugs = [g["slug"] for g in client.get("/api/genres").json()]
    assert slugs == ["научная-фантастика"]


def test_filter_by_genre_slug(client, create_title, movie_payload):
    create_title(movie_payload(genres=["Драма"]))
    create_title(movie_payload(name="Комедийный", year=2001, genres=["Комедия"]))
    body = client.get("/api/titles", params={"genre": "драма"}).json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Довод"


def test_patch_can_clear_genres(client, admin_headers, create_title, movie_payload):
    created = create_title(movie_payload(genres=["Драма"]))
    updated = client.patch(
        f"/api/titles/{created['id']}", headers=admin_headers, json={"genres": []}
    ).json()
    assert updated["genres"] == []


def test_genre_survives_title_deletion(client, admin_headers, create_title, movie_payload):
    created = create_title(movie_payload(genres=["Драма"]))
    client.delete(f"/api/titles/{created['id']}", headers=admin_headers)
    catalog = client.get("/api/genres").json()
    assert catalog[0]["slug"] == "драма"
    assert catalog[0]["titles_count"] == 0


@pytest.mark.parametrize("genre", ["!!!", "---", "\U0001f3ac"])
def test_genre_without_letters_is_rejected(client, admin_headers, movie_payload, genre):
    response = client.post("/api/titles", headers=admin_headers, json=movie_payload(genres=[genre]))
    assert response.status_code == 422


def test_too_many_genres_is_rejected(client, admin_headers, movie_payload):
    response = client.post("/api/titles", headers=admin_headers, json=movie_payload(
        genres=[f"жанр{i}" for i in range(21)],
    ))
    assert response.status_code == 422
