import pytest


def test_episodes_are_returned_in_order(client, create_title, series_payload):
    payload = series_payload(episodes=[
        {"season_number": 2, "episode_number": 1, "name": "s2e1"},
        {"season_number": 1, "episode_number": 2, "name": "s1e2"},
        {"season_number": 1, "episode_number": 1, "name": "s1e1"},
    ])
    created = create_title(payload)
    order = [(e["season_number"], e["episode_number"]) for e in created["episodes"]]
    assert order == [(1, 1), (1, 2), (2, 1)]


def test_stored_order_survives_reload(client, create_title, series_payload):
    created = create_title(series_payload())
    reloaded = client.get(f"/api/titles/{created['id']}").json()
    assert [e["id"] for e in reloaded["episodes"]] == [e["id"] for e in created["episodes"]]


def test_duplicate_episode_position_is_rejected(client, admin_headers):
    response = client.post("/api/titles", headers=admin_headers, json={
        "type": "series", "name": "Дубли", "embed_url": "https://p.tv/s",
        "episodes": [
            {"season_number": 1, "episode_number": 1, "name": "a"},
            {"season_number": 1, "episode_number": 1, "name": "b"},
        ],
    })
    assert response.status_code == 422
    assert response.json()["error"]["details"]["episode_number"] == 1


@pytest.mark.parametrize("episode", [
    {"season_number": 0, "episode_number": 1, "name": "e"},
    {"season_number": 1, "episode_number": 0, "name": "e"},
    {"season_number": 1, "name": "e"},
    {"season_number": 1, "episode_number": 1, "name": ""},
])
def test_bad_episode_is_rejected_by_schema(client, admin_headers, episode):
    response = client.post("/api/titles", headers=admin_headers, json={
        "type": "series", "name": "Сериал", "embed_url": "https://p.tv/s",
        "episodes": [episode],
    })
    assert response.status_code == 422


def test_patch_keeps_ids_of_matching_episodes(client, admin_headers, create_title, series_payload):
    created = create_title(series_payload())
    before = {(e["season_number"], e["episode_number"]): e["id"] for e in created["episodes"]}

    updated = client.patch(f"/api/titles/{created['id']}", headers=admin_headers, json={
        "episodes": [
            {"season_number": 1, "episode_number": 1, "name": "Тайны (ред.)"},
            {"season_number": 1, "episode_number": 2, "name": "Ложь"},
        ],
    }).json()
    after = {(e["season_number"], e["episode_number"]): e for e in updated["episodes"]}

    assert len(after) == 2
    assert after[(1, 1)]["id"] == before[(1, 1)]
    assert after[(1, 1)]["name"] == "Тайны (ред.)"
    assert (2, 1) not in after


def test_patch_adds_new_episode(client, admin_headers, create_title, series_payload):
    created = create_title(series_payload())
    episodes = [
        {"season_number": e["season_number"], "episode_number": e["episode_number"], "name": e["name"]}
        for e in created["episodes"]
    ]
    episodes.append({"season_number": 2, "episode_number": 2, "name": "новая"})
    updated = client.patch(
        f"/api/titles/{created['id']}", headers=admin_headers, json={"episodes": episodes}
    ).json()
    assert len(updated["episodes"]) == 4
    assert updated["episodes"][-1]["name"] == "новая"


def test_episode_can_carry_own_link(client, create_title):
    created = create_title({
        "type": "series", "name": "Ссылки",
        "episodes": [
            {"season_number": 1, "episode_number": 1, "name": "e1", "embed_url": "https://p.tv/e1"},
        ],
    })
    assert created["episodes"][0]["embed_url"] == "https://p.tv/e1"
