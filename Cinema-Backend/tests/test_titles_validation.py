import pytest


@pytest.mark.parametrize("payload, reason", [
    ({"type": "cartoon", "name": "X", "embed_url": "https://p.tv/1"}, "неизвестный тип"),
    ({"type": "movie", "name": "", "embed_url": "https://p.tv/1"}, "пустое имя"),
    ({"type": "movie", "name": "   ", "embed_url": "https://p.tv/1"}, "имя из пробелов"),
    ({"type": "movie", "name": "Я" * 256, "embed_url": "https://p.tv/1"}, "слишком длинное имя"),
    ({"type": "movie", "name": "X", "embed_url": "javascript:alert(1)"}, "не http-схема"),
    ({"type": "movie", "name": "X", "embed_url": "https://"}, "url без домена"),
    ({"type": "movie", "name": "X", "embed_url": "https://p.tv/1", "year": 1000}, "год до кино"),
    ({"type": "movie", "name": "X", "embed_url": "https://p.tv/1", "year": 3000}, "год из будущего"),
    ({"type": "movie", "name": "X", "embed_url": "https://p.tv/1", "typo": 1}, "лишнее поле"),
    ({"name": "X", "embed_url": "https://p.tv/1"}, "нет типа"),
    ({"type": "movie", "embed_url": "https://p.tv/1"}, "нет имени"),
], ids=lambda value: value if isinstance(value, str) else "")
def test_schema_rejects_bad_payload(client, admin_headers, payload, reason):
    response = client.post("/api/titles", headers=admin_headers, json=payload)
    assert response.status_code == 422, reason
    assert response.json()["error"]["code"] == "validation_error"


def test_validation_error_names_the_field(client, admin_headers):
    response = client.post("/api/titles", headers=admin_headers, json={
        "type": "movie", "name": "X", "embed_url": "not-a-url",
    })
    fields = [item["field"] for item in response.json()["error"]["details"]["errors"]]
    assert "embed_url" in fields


def test_movie_requires_embed_url(client, admin_headers, movie_payload):
    payload = movie_payload()
    payload.pop("embed_url")
    response = client.post("/api/titles", headers=admin_headers, json=payload)
    assert response.status_code == 422
    assert "embed_url" in response.json()["error"]["message"]


def test_movie_cannot_have_episodes(client, admin_headers, movie_payload):
    response = client.post("/api/titles", headers=admin_headers, json=movie_payload(
        episodes=[{"season_number": 1, "episode_number": 1, "name": "e1"}],
    ))
    assert response.status_code == 422
    assert response.json()["error"]["details"]["field"] == "episodes"


def test_series_needs_embed_url_or_episodes(client, admin_headers):
    response = client.post("/api/titles", headers=admin_headers, json={
        "type": "series", "name": "Пустой сериал",
    })
    assert response.status_code == 422


def test_series_without_common_embed_needs_it_on_every_episode(client, admin_headers):
    response = client.post("/api/titles", headers=admin_headers, json={
        "type": "series",
        "name": "Сериал",
        "episodes": [
            {"season_number": 1, "episode_number": 1, "name": "e1", "embed_url": "https://p.tv/1"},
            {"season_number": 1, "episode_number": 2, "name": "e2"},
        ],
    })
    assert response.status_code == 422
    assert response.json()["error"]["details"]["missing"] == ["s1e2"]


def test_series_with_per_episode_links_is_accepted(client, admin_headers):
    response = client.post("/api/titles", headers=admin_headers, json={
        "type": "series",
        "name": "Сериал",
        "episodes": [
            {"season_number": 1, "episode_number": 1, "name": "e1", "embed_url": "https://p.tv/1"},
        ],
    })
    assert response.status_code == 201


def test_duplicate_is_conflict(client, admin_headers, create_title, movie_payload):
    create_title(movie_payload())
    response = client.post("/api/titles", headers=admin_headers, json=movie_payload())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate_title"


@pytest.mark.parametrize("name", ["довод", "ДОВОД", "  Довод  ", "До\tвод".replace("\t", "")])
def test_duplicate_detection_ignores_case_and_spaces(
    client, admin_headers, create_title, movie_payload, name
):
    create_title(movie_payload())
    response = client.post("/api/titles", headers=admin_headers, json=movie_payload(name=name))
    assert response.status_code == 409


def test_duplicate_without_year_is_detected(client, admin_headers, movie_payload):
    payload = movie_payload()
    payload.pop("year")
    client.post("/api/titles", headers=admin_headers, json=payload)
    response = client.post("/api/titles", headers=admin_headers, json=payload | {"name": "довод"})
    assert response.status_code == 409


def test_same_name_different_year_is_allowed(client, admin_headers, create_title, movie_payload):
    create_title(movie_payload())
    response = client.post("/api/titles", headers=admin_headers, json=movie_payload(year=2021))
    assert response.status_code == 201


def test_database_blocks_duplicate_bypassing_service(db_session, create_title, movie_payload):
    from sqlalchemy.exc import IntegrityError

    from app.db.models import Title

    create_title(movie_payload())
    db_session.add(Title(
        type="movie", name="довод", year=2020, embed_url="https://p.tv/race",
    ))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_patch_cannot_null_required_field(client, admin_headers, create_title, movie_payload):
    created = create_title(movie_payload())
    response = client.patch(
        f"/api/titles/{created['id']}", headers=admin_headers, json={"name": None}
    )
    assert response.status_code == 422


def test_patch_to_existing_name_is_conflict(client, admin_headers, create_title, movie_payload):
    create_title(movie_payload())
    other = create_title(movie_payload(name="Престиж", year=2006))
    response = client.patch(f"/api/titles/{other['id']}", headers=admin_headers, json={
        "name": "ДОВОД", "year": 2020,
    })
    assert response.status_code == 409


def test_changing_type_to_movie_requires_dropping_episodes(
    client, admin_headers, create_title, series_payload
):
    created = create_title(series_payload())
    response = client.patch(
        f"/api/titles/{created['id']}", headers=admin_headers, json={"type": "movie"}
    )
    assert response.status_code == 422

    response = client.patch(f"/api/titles/{created['id']}", headers=admin_headers, json={
        "type": "movie", "episodes": [],
    })
    assert response.status_code == 200
