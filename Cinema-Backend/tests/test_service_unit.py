import pytest

from app.core.exceptions import DuplicateTitleError, TitleNotFoundError, ValidationError
from app.core.text import make_slug
from app.db.models import Genre, Title
from app.enums import TitleType
from app.repositories.titles import TitleFilters
from app.schemas import TitleCreate, TitleUpdate
from app.services.titles import TitleService


class FakeGenreRepository:
    def __init__(self) -> None:
        self.by_slug: dict[str, Genre] = {}

    def get_or_create_many(self, names):
        result = []
        for name in names:
            slug = make_slug(name)
            if slug not in self.by_slug:
                genre = Genre(slug=slug, name=name.strip())
                genre.id = len(self.by_slug) + 1
                self.by_slug[slug] = genre
            result.append(self.by_slug[slug])
        return result

    def list_all(self):
        return [(genre, 0) for genre in self.by_slug.values()]


class FakeTitleRepository:
    def __init__(self) -> None:
        self.items: dict[int, Title] = {}
        self._next_id = 1

    def get_by_id(self, title_id, *, load_episodes=False):
        return self.items.get(title_id)

    def list(self, filters, *, limit, offset):
        values = list(self.items.values())
        return values[offset:offset + limit], len(values)

    def exists_duplicate(self, *, name, year, title_type, exclude_id=None):
        from app.core.text import normalize_name

        target = normalize_name(name)
        return any(
            item.name_normalized == target
            and item.year == year
            and item.type == title_type
            and item.id != exclude_id
            for item in self.items.values()
        )

    def add(self, title):
        title.id = self._next_id
        self._next_id += 1
        self.items[title.id] = title

    def delete(self, title):
        self.items.pop(title.id, None)


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def flush(self):
        pass

    def refresh(self, instance, attribute_names=None):
        pass


@pytest.fixture
def service():
    return TitleService(FakeTitleRepository(), FakeGenreRepository(), FakeUnitOfWork())


def test_service_works_without_database(service):
    created = service.create(TitleCreate(
        type="movie", name="Довод", year=2020, embed_url="https://p.tv/1",
    ))
    assert created.id == 1
    assert created.name_normalized == "довод"


def test_create_commits_once(service):
    service.create(TitleCreate(type="movie", name="A", embed_url="https://p.tv/1"))
    assert service._uow.commits == 1
    assert service._uow.rollbacks == 0


def test_failed_validation_rolls_back(service):
    with pytest.raises(ValidationError):
        service.create(TitleCreate(
            type="movie", name="A", embed_url="https://p.tv/1",
            episodes=[{"season_number": 1, "episode_number": 1, "name": "e"}],
        ))
    assert service._uow.rollbacks == 1
    assert service._uow.commits == 0


def test_duplicate_is_detected_before_write(service):
    service.create(TitleCreate(type="movie", name="Довод", year=2020, embed_url="https://p.tv/1"))
    with pytest.raises(DuplicateTitleError):
        service.create(TitleCreate(type="movie", name="ДОВОД", year=2020, embed_url="https://p.tv/2"))


def test_get_missing_raises_domain_error(service):
    with pytest.raises(TitleNotFoundError):
        service.get(404)


def test_update_of_missing_title_raises(service):
    with pytest.raises(TitleNotFoundError):
        service.update(404, TitleUpdate(year=2000))


def test_empty_patch_is_rejected(service):
    created = service.create(TitleCreate(type="movie", name="A", embed_url="https://p.tv/1"))
    with pytest.raises(ValidationError):
        service.update(created.id, TitleUpdate())


def test_partial_update_keeps_other_fields(service):
    created = service.create(TitleCreate(
        type="movie", name="A", year=2000, embed_url="https://p.tv/1", genres=["Драма"],
    ))
    updated = service.update(created.id, TitleUpdate(year=2001))
    assert updated.year == 2001
    assert updated.name == "A"
    assert [g.name for g in updated.genres] == ["Драма"]


def test_episodes_without_optional_fields_do_not_break_sync(service):
    created = service.create(TitleCreate(
        type="series", name="S", embed_url="https://p.tv/1",
        episodes=[{"season_number": 1, "episode_number": 1, "name": "e1"}],
    ))
    updated = service.update(created.id, TitleUpdate(
        episodes=[{"episode_number": 1, "name": "переименовано"}],
    ))
    assert updated.episodes[0].name == "переименовано"
    assert updated.episodes[0].season_number == 1


def test_episode_identity_is_preserved_by_position(service):
    created = service.create(TitleCreate(
        type="series", name="S", embed_url="https://p.tv/1",
        episodes=[
            {"season_number": 1, "episode_number": 1, "name": "a"},
            {"season_number": 1, "episode_number": 2, "name": "b"},
        ],
    ))
    first = created.episodes[0]
    updated = service.update(created.id, TitleUpdate(
        episodes=[{"season_number": 1, "episode_number": 1, "name": "a2"}],
    ))
    assert updated.episodes[0] is first
    assert len(updated.episodes) == 1


def test_episodes_are_sorted_in_memory(service):
    created = service.create(TitleCreate(
        type="series", name="S", embed_url="https://p.tv/1",
        episodes=[
            {"season_number": 2, "episode_number": 1, "name": "c"},
            {"season_number": 1, "episode_number": 2, "name": "b"},
            {"season_number": 1, "episode_number": 1, "name": "a"},
        ],
    ))
    positions = [(e.season_number, e.episode_number) for e in created.episodes]
    assert positions == [(1, 1), (1, 2), (2, 1)]


def test_inverted_year_range_is_rejected(service):
    with pytest.raises(ValidationError):
        service.list_titles(TitleFilters(year_from=2020, year_to=2000), limit=10, offset=0)


def test_movie_type_is_normalized_to_enum(service):
    created = service.create(TitleCreate(type="movie", name="A", embed_url="https://p.tv/1"))
    assert created.type is TitleType.MOVIE


class ExplodingUnitOfWork(FakeUnitOfWork):
    def commit(self):
        raise RuntimeError("база отвалилась")


def test_delete_rolls_back_on_commit_failure():
    repo = FakeTitleRepository()
    uow = FakeUnitOfWork()
    service = TitleService(repo, FakeGenreRepository(), uow)
    created = service.create(TitleCreate(type="movie", name="A", embed_url="https://p.tv/1"))

    service._uow = ExplodingUnitOfWork()
    with pytest.raises(RuntimeError):
        service.delete(created.id)
    assert service._uow.rollbacks == 1


def test_update_rolls_back_on_commit_failure():
    repo = FakeTitleRepository()
    service = TitleService(repo, FakeGenreRepository(), FakeUnitOfWork())
    created = service.create(TitleCreate(type="movie", name="A", embed_url="https://p.tv/1"))

    service._uow = ExplodingUnitOfWork()
    with pytest.raises(RuntimeError):
        service.update(created.id, TitleUpdate(year=2000))
    assert service._uow.rollbacks == 1


def test_list_returns_page_and_total():
    service = TitleService(FakeTitleRepository(), FakeGenreRepository(), FakeUnitOfWork())
    for index in range(3):
        service.create(TitleCreate(
            type="movie", name=f"Ф{index}", embed_url=f"https://p.tv/{index}",
        ))
    items, total = service.list_titles(TitleFilters(), limit=2, offset=0)
    assert len(items) == 2
    assert total == 3
