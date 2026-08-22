import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, ValidationError
from app.db.models import Genre, Title
from app.repositories.genres import GenreRepository
from app.repositories.titles import TitleRepository, escape_like
from app.repositories.uow import SqlAlchemyUnitOfWork

BACKSLASH = chr(92)


@pytest.mark.parametrize("raw, expected", [
    ("простое", "простое"),
    ("100%", r"100\%"),
    ("a_b", r"a\_b"),
    ("back" + BACKSLASH + "slash", "back" + BACKSLASH * 2 + "slash"),
    ("%_" + BACKSLASH, r"\%\_" + BACKSLASH * 2),
])
def test_escape_like(raw, expected):
    assert escape_like(raw) == expected


def test_unit_of_work_translates_integrity_error(db_session):
    uow = SqlAlchemyUnitOfWork(db_session)
    db_session.add(Genre(slug="драма", name="Драма"))
    uow.commit()

    db_session.add(Genre(slug="драма", name="Дубль"))
    with pytest.raises(ConflictError, match="жанр"):
        uow.commit()


def test_unit_of_work_explains_title_conflict(db_session):
    uow = SqlAlchemyUnitOfWork(db_session)
    db_session.add(Title(type="movie", name="Довод", year=2020, embed_url="https://p.tv/1"))
    uow.commit()

    db_session.add(Title(type="movie", name="довод", year=2020, embed_url="https://p.tv/2"))
    with pytest.raises(ConflictError, match="названием"):
        uow.commit()


def test_unit_of_work_rolls_back_after_conflict(db_session):
    uow = SqlAlchemyUnitOfWork(db_session)
    db_session.add(Genre(slug="драма", name="Драма"))
    uow.commit()
    db_session.add(Genre(slug="драма", name="Дубль"))
    with pytest.raises(ConflictError):
        uow.commit()

    db_session.add(Genre(slug="комедия", name="Комедия"))
    uow.commit()
    assert db_session.query(Genre).count() == 2


def test_genre_repository_reuses_existing(db_session):
    repo = GenreRepository(db_session)
    first = repo.get_or_create_many(["Фантастика"])
    db_session.flush()
    second = repo.get_or_create_many(["  фантастика  "])
    assert first[0].slug == second[0].slug


def test_genre_repository_keeps_requested_order(db_session):
    repo = GenreRepository(db_session)
    genres = repo.get_or_create_many(["Триллер", "Драма", "Комедия"])
    assert [g.name for g in genres] == ["Триллер", "Драма", "Комедия"]


def test_genre_repository_rejects_name_without_letters(db_session):
    with pytest.raises(ValidationError):
        GenreRepository(db_session).get_or_create_many(["!!!"])


def test_genre_repository_counts_titles(db_session):
    repo = GenreRepository(db_session)
    genre = repo.get_or_create_many(["Драма"])[0]
    title = Title(type="movie", name="A", embed_url="https://p.tv/1")
    title.genres = [genre]
    db_session.add(title)
    db_session.commit()

    counts = {g.slug: count for g, count in repo.list_all()}
    assert counts == {"драма": 1}


def test_title_repository_finds_duplicate_ignoring_case(db_session):
    repo = TitleRepository(db_session)
    db_session.add(Title(type="movie", name="Довод", year=2020, embed_url="https://p.tv/1"))
    db_session.commit()

    assert repo.exists_duplicate(name="ДОВОД", year=2020, title_type="movie") is True
    assert repo.exists_duplicate(name="Довод", year=2021, title_type="movie") is False
    assert repo.exists_duplicate(name="Довод", year=2020, title_type="series") is False


def test_duplicate_check_can_exclude_self(db_session):
    repo = TitleRepository(db_session)
    title = Title(type="movie", name="Довод", year=2020, embed_url="https://p.tv/1")
    db_session.add(title)
    db_session.commit()

    assert repo.exists_duplicate(
        name="Довод", year=2020, title_type="movie", exclude_id=title.id
    ) is False


def test_database_rejects_duplicate_episode_position(db_session):
    from app.db.models import Episode

    title = Title(type="series", name="S", embed_url="https://p.tv/1")
    title.episodes.append(Episode(season_number=1, episode_number=1, name="a"))
    db_session.add(title)
    db_session.commit()

    db_session.add(Episode(title_id=title.id, season_number=1, episode_number=1, name="b"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_sqlite_enforces_foreign_keys(db_session):
    from app.db.models import Episode

    db_session.add(Episode(title_id=999999, season_number=1, episode_number=1, name="ghost"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
