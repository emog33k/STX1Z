from datetime import datetime
from typing import Annotated, Any, Generic, TypeVar
from urllib.parse import urlparse

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    field_validator,
)

from app.core.text import has_slug
from app.enums import MAX_YEAR, MIN_YEAR, TitleType

MAX_URL_LENGTH = 2048
MAX_GENRES = 12
MAX_EPISODES = 1200


def _validate_http_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("нужен http или https")
    if not parsed.netloc:
        raise ValueError("URL не содержит домена")
    return value


def _empty_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


NonEmptyStr = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]


def _validate_genre_name(value: str) -> str:
    if not has_slug(value):
        raise ValueError("в жанре нужны буквы или цифры")
    return value


GenreName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    AfterValidator(_validate_genre_name),
]
HttpUrlStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_URL_LENGTH),
    AfterValidator(_validate_http_url),
]
OptionalHttpUrlStr = Annotated[HttpUrlStr | None, BeforeValidator(_empty_to_none)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=8000)]
OptionalText = Annotated[Description | None, BeforeValidator(_empty_to_none)]
Year = Annotated[int, Field(ge=MIN_YEAR, le=MAX_YEAR)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _dedupe_genres(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    seen: set[str] = set()
    result: list[str] = []
    for genre in value:
        key = genre.casefold()
        if key not in seen:
            seen.add(key)
            result.append(genre)
    return result


class EpisodeIn(StrictModel):
    season_number: int = Field(default=1, ge=1, le=100)
    episode_number: int = Field(ge=1, le=5000)
    name: NonEmptyStr
    embed_url: OptionalHttpUrlStr = None


class EpisodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    season_number: int
    episode_number: int
    name: str
    embed_url: str | None = None


class GenreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str


class GenreCatalogOut(GenreOut):
    titles_count: int = Field(ge=0)


class TitleCreate(StrictModel):
    type: TitleType
    name: NonEmptyStr
    description: OptionalText = None
    poster_url: OptionalHttpUrlStr = None
    backdrop_url: OptionalHttpUrlStr = None
    year: Year | None = None
    embed_url: OptionalHttpUrlStr = None
    genres: list[GenreName] = Field(default_factory=list, max_length=MAX_GENRES)
    episodes: list[EpisodeIn] = Field(default_factory=list, max_length=MAX_EPISODES)

    _normalize_genres = field_validator("genres")(_dedupe_genres)


class TitleUpdate(StrictModel):
    type: TitleType | None = None
    name: NonEmptyStr | None = None
    description: OptionalText = None
    poster_url: OptionalHttpUrlStr = None
    backdrop_url: OptionalHttpUrlStr = None
    year: Year | None = None
    embed_url: OptionalHttpUrlStr = None
    genres: Annotated[list[GenreName], Field(max_length=MAX_GENRES)] | None = None
    episodes: Annotated[list[EpisodeIn], Field(max_length=MAX_EPISODES)] | None = None

    @field_validator("type", "name", "genres", "episodes", mode="before")
    @classmethod
    def _reject_explicit_null(cls, value: Any) -> Any:
        # Сюда доходит только явный null в теле.
        if value is None:
            raise ValueError("нельзя null, просто не присылай поле")
        return value

    _normalize_genres = field_validator("genres")(_dedupe_genres)


class TitleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: TitleType
    name: str
    description: str | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    year: int | None = None
    embed_url: str | None = None
    genres: list[GenreOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TitleDetailOut(TitleOut):
    episodes: list[EpisodeOut] = Field(default_factory=list)


ItemT = TypeVar("ItemT")


class Page(BaseModel, Generic[ItemT]):
    items: list[ItemT]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)

    @computed_field
    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class TelegramUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    is_premium: bool = False
    is_admin: bool = False


class HealthOut(BaseModel):
    status: str
    version: str
    database: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorOut(BaseModel):
    error: ErrorBody
    request_id: str | None = None
