import pytest


@pytest.fixture
def catalog(create_title):
    return [
        create_title({"type": "movie", "name": "Довод", "year": 2020,
                      "embed_url": "https://p.tv/1", "genres": ["Фантастика"]}),
        create_title({"type": "movie", "name": "Престиж", "year": 2006,
                      "embed_url": "https://p.tv/2", "genres": ["Драма"]}),
        create_title({"type": "series", "name": "Тьма", "year": 2017,
                      "embed_url": "https://p.tv/3", "genres": ["Фантастика", "Триллер"]}),
        create_title({"type": "series", "name": "Без года",
                      "embed_url": "https://p.tv/4"}),
    ]


def test_page_shape(client, catalog):
    body = client.get("/api/titles").json()
    assert set(body) == {"items", "total", "limit", "offset", "has_more"}
    assert body["total"] == 4
    assert body["limit"] == 20
    assert body["has_more"] is False


def test_limit_and_offset(client, catalog):
    first = client.get("/api/titles", params={"limit": 2, "offset": 0, "sort": "id"}).json()
    second = client.get("/api/titles", params={"limit": 2, "offset": 2, "sort": "id"}).json()
    assert len(first["items"]) == 2
    assert first["has_more"] is True
    assert second["has_more"] is False
    assert {t["id"] for t in first["items"]}.isdisjoint({t["id"] for t in second["items"]})


def test_offset_beyond_total_returns_empty_page(client, catalog):
    body = client.get("/api/titles", params={"offset": 1000}).json()
    assert body["items"] == []
    assert body["total"] == 4
    assert body["has_more"] is False


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_limit_out_of_range_is_rejected(client, limit):
    assert client.get("/api/titles", params={"limit": limit}).status_code == 422


def test_search_is_case_insensitive_for_cyrillic(client, catalog):
    assert client.get("/api/titles", params={"q": "тьм"}).json()["total"] == 1
    assert client.get("/api/titles", params={"q": "ТЬМА"}).json()["total"] == 1


def test_search_matches_substring(client, catalog):
    assert client.get("/api/titles", params={"q": "рести"}).json()["total"] == 1


@pytest.mark.parametrize("needle", ["%", "_", "%%", "\\"])
def test_like_metacharacters_are_escaped(client, catalog, needle):
    assert client.get("/api/titles", params={"q": needle}).json()["total"] == 0


def test_escaped_metacharacter_still_matches_literal(client, create_title):
    create_title({"type": "movie", "name": "100%_кино", "embed_url": "https://p.tv/9"})
    assert client.get("/api/titles", params={"q": "100%_"}).json()["total"] == 1


def test_filter_by_type(client, catalog):
    assert client.get("/api/titles", params={"type": "series"}).json()["total"] == 2
    assert client.get("/api/titles", params={"type": "movie"}).json()["total"] == 2


def test_unknown_type_is_rejected(client):
    assert client.get("/api/titles", params={"type": "cartoon"}).status_code == 422


def test_filter_by_year_range(client, catalog):
    body = client.get("/api/titles", params={"year_from": 2010, "year_to": 2020}).json()
    assert {t["name"] for t in body["items"]} == {"Довод", "Тьма"}


def test_inverted_year_range_is_rejected(client):
    response = client.get("/api/titles", params={"year_from": 2020, "year_to": 2010})
    assert response.status_code == 422
    assert response.json()["error"]["details"]["field"] == "year_from"


def test_filters_combine(client, catalog):
    body = client.get("/api/titles", params={
        "type": "series", "genre": "фантастика", "year_from": 2000,
    }).json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Тьма"


@pytest.mark.parametrize("sort, expected_first", [
    ("name", "Без года"),
    ("-name", "Тьма"),
    ("id", "Довод"),
    ("-id", "Без года"),
])
def test_sorting(client, catalog, sort, expected_first):
    body = client.get("/api/titles", params={"sort": sort}).json()
    assert body["items"][0]["name"] == expected_first


def test_null_years_sort_last(client, catalog):
    years = [t["year"] for t in client.get("/api/titles", params={"sort": "year"}).json()["items"]]
    filled = [y for y in years if y is not None]
    assert filled == sorted(filled)
    assert years[len(filled):] == [None]


def test_unknown_sort_is_rejected(client):
    assert client.get("/api/titles", params={"sort": "name; DROP TABLE titles"}).status_code == 422


def test_pagination_is_stable_across_pages(client, create_title):
    for index in range(5):
        create_title({"type": "movie", "name": f"Фильм {index}", "year": 2000,
                      "embed_url": f"https://p.tv/{index}"})
    seen = []
    for offset in range(0, 5, 2):
        page = client.get("/api/titles", params={"limit": 2, "offset": offset, "sort": "year"}).json()
        seen.extend(item["id"] for item in page["items"])
    assert len(seen) == len(set(seen)) == 5


def test_genre_filter_does_not_duplicate_rows(client, create_title):
    create_title({"type": "movie", "name": "Мультижанр", "embed_url": "https://p.tv/m",
                  "genres": ["Драма", "Комедия", "Триллер"]})
    body = client.get("/api/titles", params={"genre": "драма"}).json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
