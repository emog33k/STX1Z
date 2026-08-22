from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Protocol

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.text import normalize_name
from app.db.models import Genre, Title, title_genres
from app.enums import TitleSort, TitleType

_LIKE_ESCAPE_CHAR = "\\"


def escape_like(value: str) -> str:
    escaped = value.replace(_LIKE_ESCAPE_CHAR, _LIKE_ESCAPE_CHAR * 2)
    for char in ("%", "_"):
        escaped = escaped.replace(char, _LIKE_ESCAPE_CHAR + char)
    return escaped


@dataclass(frozen=True, slots=True)
class TitleFilters:
    q: str | None = None
    type: TitleType | None = None
    genre: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    sort: TitleSort = TitleSort.ID_DESC


class TitleRepositoryProtocol(Protocol):
    def get_by_id(self, title_id: int, *, load_episodes: bool = False) -> Title | None: ...
    def list(
        self, filters: TitleFilters, *, limit: int, offset: int
    ) -> tuple[list[Title], int]: ...
    def exists_duplicate(
        self,
        *,
        name: str,
        year: int | None,
        title_type: TitleType,
        exclude_id: int | None = None,
    ) -> bool: ...
    def add(self, title: Title) -> None: ...
    def delete(self, title: Title) -> None: ...


class TitleRepository:
    _SORT_COLUMNS: ClassVar[dict[TitleSort, ColumnElement]] = {
        TitleSort.ID_DESC: Title.id.desc(),
        TitleSort.ID_ASC: Title.id.asc(),
        TitleSort.NAME_ASC: Title.name.asc(),
        TitleSort.NAME_DESC: Title.name.desc(),
        TitleSort.YEAR_ASC: Title.year.asc().nullslast(),
        TitleSort.YEAR_DESC: Title.year.desc().nullslast(),
        TitleSort.CREATED_ASC: Title.created_at.asc(),
        TitleSort.CREATED_DESC: Title.created_at.desc(),
    }

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_by_id(self, title_id: int, *, load_episodes: bool = False) -> Title | None:
        stmt = select(Title).where(Title.id == title_id)
        if load_episodes:
            stmt = stmt.options(selectinload(Title.episodes))
        return self._db.execute(stmt).scalar_one_or_none()

    def list(
        self, filters: TitleFilters, *, limit: int, offset: int
    ) -> tuple[list[Title], int]:
        conditions = self._build_conditions(filters)
        needs_join = filters.genre is not None

        count_column = func.count(func.distinct(Title.id)) if needs_join else func.count()
        total_stmt = select(count_column).select_from(Title)
        items_stmt = select(Title)

        if needs_join:
            total_stmt = self._join_genres(total_stmt)
            items_stmt = self._join_genres(items_stmt)

        for condition in conditions:
            total_stmt = total_stmt.where(condition)
            items_stmt = items_stmt.where(condition)

        total = self._db.execute(total_stmt).scalar_one()

        items_stmt = self._apply_sort(items_stmt, filters.sort).limit(limit).offset(offset)
        if needs_join:
            items_stmt = items_stmt.distinct()
        items = list(self._db.execute(items_stmt).scalars().unique().all())
        return items, int(total)

    @staticmethod
    def _join_genres(stmt: Select) -> Select:
        return stmt.join(title_genres, Title.id == title_genres.c.title_id).join(
            Genre, Genre.id == title_genres.c.genre_id
        )

    def exists_duplicate(
        self,
        *,
        name: str,
        year: int | None,
        title_type: TitleType,
        exclude_id: int | None = None,
    ) -> bool:
        stmt = select(Title.id).where(
            Title.name_normalized == normalize_name(name),
            Title.type == title_type,
        )
        stmt = stmt.where(Title.year.is_(None) if year is None else Title.year == year)
        if exclude_id is not None:
            stmt = stmt.where(Title.id != exclude_id)
        return self._db.execute(stmt.limit(1)).first() is not None

    def add(self, title: Title) -> None:
        self._db.add(title)

    def delete(self, title: Title) -> None:
        self._db.delete(title)

    @staticmethod
    def _build_conditions(filters: TitleFilters) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = []

        if filters.q:
            pattern = f"%{escape_like(filters.q.strip())}%".lower()
            conditions.append(
                func.lower(Title.name).like(pattern, escape=_LIKE_ESCAPE_CHAR)
            )
        if filters.type is not None:
            conditions.append(Title.type == filters.type)
        if filters.genre:
            conditions.append(Genre.slug == filters.genre.strip().casefold())
        if filters.year_from is not None:
            conditions.append(Title.year >= filters.year_from)
        if filters.year_to is not None:
            conditions.append(Title.year <= filters.year_to)

        return conditions

    @classmethod
    def _apply_sort(cls, stmt: Select, sort: TitleSort) -> Select:
        order_by = cls._SORT_COLUMNS[sort]
        return stmt.order_by(order_by, Title.id.desc())
