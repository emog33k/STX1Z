from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.core.text import make_slug
from app.db.models import Genre, title_genres


class GenreRepositoryProtocol(Protocol):
    def get_or_create_many(self, names: list[str]) -> list[Genre]: ...
    def list_all(self) -> list[tuple[Genre, int]]: ...


class GenreRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_or_create_many(self, names: list[str]) -> list[Genre]:
        if not names:
            return []

        wanted: dict[str, str] = {}
        for name in names:
            try:
                slug = make_slug(name)
            except ValueError as exc:
                raise ValidationError(str(exc), field="genres") from exc
            wanted.setdefault(slug, name.strip())

        existing = {
            genre.slug: genre
            for genre in self._db.execute(
                select(Genre).where(Genre.slug.in_(wanted.keys()))
            )
            .scalars()
            .all()
        }

        for slug, display_name in wanted.items():
            if slug in existing:
                continue
            existing[slug] = self._create(slug, display_name)

        return [existing[slug] for slug in wanted]

    def list_all(self) -> list[tuple[Genre, int]]:
        stmt = (
            select(Genre, func.count(title_genres.c.title_id))
            .outerjoin(title_genres, title_genres.c.genre_id == Genre.id)
            .group_by(Genre.id)
            .order_by(Genre.name.asc())
        )
        return [(genre, int(count)) for genre, count in self._db.execute(stmt).all()]

    def _create(self, slug: str, display_name: str) -> Genre:
        genre = Genre(slug=slug, name=display_name)
        try:
            with self._db.begin_nested():
                self._db.add(genre)
        except IntegrityError:
            genre = self._db.execute(
                select(Genre).where(Genre.slug == slug)
            ).scalar_one()
        return genre
