import logging
from typing import Any

from app.core.exceptions import DuplicateTitleError, TitleNotFoundError, ValidationError
from app.db.models import Episode, Title
from app.enums import TitleType
from app.repositories.genres import GenreRepositoryProtocol
from app.repositories.titles import TitleFilters, TitleRepositoryProtocol
from app.repositories.uow import UnitOfWork
from app.schemas import EpisodeIn, TitleCreate, TitleUpdate

logger = logging.getLogger(__name__)

_SCALAR_FIELDS = (
    "type",
    "name",
    "description",
    "poster_url",
    "backdrop_url",
    "year",
    "embed_url",
)


class TitleService:
    def __init__(
        self,
        repo: TitleRepositoryProtocol,
        genres: GenreRepositoryProtocol,
        uow: UnitOfWork,
    ) -> None:
        self._repo = repo
        self._genres = genres
        self._uow = uow

    def list_titles(
        self, filters: TitleFilters, *, limit: int, offset: int
    ) -> tuple[list[Title], int]:
        if (
            filters.year_from is not None
            and filters.year_to is not None
            and filters.year_from > filters.year_to
        ):
            raise ValidationError(
                "year_from не может быть больше year_to", field="year_from"
            )
        return self._repo.list(filters, limit=limit, offset=offset)

    def get(self, title_id: int, *, with_episodes: bool = False) -> Title:
        title = self._repo.get_by_id(title_id, load_episodes=with_episodes)
        if title is None:
            raise TitleNotFoundError(title_id)
        return title

    def create(self, payload: TitleCreate) -> Title:
        data = self._to_data(payload)
        self._ensure_unique(data["name"], data["year"], data["type"])

        title = Title()
        try:
            self._repo.add(title)
            self._apply(title, data)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise

        logger.info(f"Создан тайтл id={title.id} name={title.name!r}")
        return title

    def replace(self, title_id: int, payload: TitleCreate) -> Title:
        title = self.get(title_id, with_episodes=True)
        data = self._to_data(payload)
        self._ensure_unique(data["name"], data["year"], data["type"], exclude_id=title_id)
        return self._write(title, data)

    def update(self, title_id: int, payload: TitleUpdate) -> Title:
        title = self.get(title_id, with_episodes=True)
        data = self._to_data(payload, partial=True)
        if not data:
            raise ValidationError("Пустое тело запроса")

        self._ensure_unique(
            data.get("name", title.name),
            data.get("year", title.year),
            data.get("type", title.type),
            exclude_id=title_id,
        )
        return self._write(title, data)

    def delete(self, title_id: int) -> None:
        title = self.get(title_id)
        try:
            self._repo.delete(title)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        logger.info(f"Удалён тайтл id={title_id}")

    @staticmethod
    def _to_data(
        payload: TitleCreate | TitleUpdate, *, partial: bool = False
    ) -> dict[str, Any]:
        data = payload.model_dump(exclude_unset=partial)
        if "episodes" in data:
            data["episodes"] = list(payload.episodes or [])
        return data

    def _write(self, title: Title, data: dict[str, Any]) -> Title:
        try:
            self._apply(title, data)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise

        self._uow.refresh(title, ["updated_at"])
        logger.info(f"Обновлён тайтл id={title.id}")
        return title

    def _apply(self, title: Title, data: dict[str, Any]) -> None:
        for field in _SCALAR_FIELDS:
            if field in data:
                setattr(title, field, data[field])

        if "genres" in data:
            title.genres = self._genres.get_or_create_many(list(data["genres"] or []))

        if "episodes" in data:
            self._sync_episodes(title, list(data["episodes"] or []))

        self._validate(title)
        self._uow.flush()

    @staticmethod
    def _sync_episodes(title: Title, incoming: list[EpisodeIn]) -> None:
        existing: dict[tuple[int, int], Episode] = {
            (ep.season_number, ep.episode_number): ep for ep in title.episodes
        }
        seen: set[tuple[int, int]] = set()

        for item in incoming:
            key = (item.season_number, item.episode_number)
            if key in seen:
                raise ValidationError(
                    f"Серия s{key[0]}e{key[1]} указана дважды",
                    field="episodes",
                    details={"season_number": key[0], "episode_number": key[1]},
                )
            seen.add(key)

            episode = existing.get(key)
            if episode is None:
                title.episodes.append(Episode(
                    season_number=item.season_number,
                    episode_number=item.episode_number,
                    name=item.name,
                    embed_url=item.embed_url,
                ))
            else:
                episode.name = item.name
                episode.embed_url = item.embed_url

        for key, episode in existing.items():
            if key not in seen:
                title.episodes.remove(episode)

        title.episodes.sort(key=lambda ep: (ep.season_number, ep.episode_number))

    @staticmethod
    def _validate(title: Title) -> None:
        if title.type == TitleType.MOVIE:
            if title.episodes:
                raise ValidationError("У фильма не бывает серий", field="episodes")
            if not title.embed_url:
                raise ValidationError("Фильму нужен embed_url", field="embed_url")
            return

        if not title.embed_url and not title.episodes:
            raise ValidationError(
                "Нужен embed_url или хотя бы одна серия", field="embed_url"
            )
        if not title.embed_url:
            missing = [
                f"s{ep.season_number}e{ep.episode_number}"
                for ep in title.episodes
                if not ep.embed_url
            ]
            if missing:
                raise ValidationError(
                    f"Нет ссылки у серий: {', '.join(missing[:5])}",
                    field="episodes",
                    details={"missing": missing},
                )

    def _ensure_unique(
        self,
        name: str,
        year: int | None,
        title_type: TitleType,
        *,
        exclude_id: int | None = None,
    ) -> None:
        if self._repo.exists_duplicate(
            name=name, year=year, title_type=title_type, exclude_id=exclude_id
        ):
            raise DuplicateTitleError(name, year)
