import logging
from typing import Any, Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError

logger = logging.getLogger(__name__)

_DUPLICATE_TITLE = "Тайтл с таким названием и годом уже существует"
_DUPLICATE_EPISODE = "Серия с таким номером уже есть в этом сезоне"
_DUPLICATE_GENRE = "Такой жанр уже существует"

_CONSTRAINT_MESSAGES = {
    "uq_titles_name_year_type": _DUPLICATE_TITLE,
    "titles.name_normalized": _DUPLICATE_TITLE,
    "uq_episodes_position": _DUPLICATE_EPISODE,
    "episodes.episode_number": _DUPLICATE_EPISODE,
    "ix_genres_slug": _DUPLICATE_GENRE,
    "genres.slug": _DUPLICATE_GENRE,
}


class UnitOfWork(Protocol):
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def flush(self) -> None: ...
    def refresh(self, instance: Any, attribute_names: list[str] | None = None) -> None: ...


class SqlAlchemyUnitOfWork:
    def __init__(self, db: Session) -> None:
        self._db = db

    def commit(self) -> None:
        try:
            self._db.commit()
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(self._explain(exc)) from exc

    def rollback(self) -> None:
        self._db.rollback()

    def flush(self) -> None:
        try:
            self._db.flush()
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(self._explain(exc)) from exc

    def refresh(self, instance: Any, attribute_names: list[str] | None = None) -> None:
        self._db.refresh(instance, attribute_names=attribute_names)

    @staticmethod
    def _explain(exc: IntegrityError) -> str:
        text = str(getattr(exc, "orig", exc))
        for marker, message in _CONSTRAINT_MESSAGES.items():
            if marker in text:
                return message
        logger.warning(f"Неизвестный constraint: {text}")
        return "Нарушение целостности данных"
