import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Query, Request
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.db.base import get_db
from app.repositories.genres import GenreRepository
from app.repositories.titles import TitleRepository
from app.repositories.uow import SqlAlchemyUnitOfWork
from app.security.telegram import InitData, TelegramUser, parse_init_data
from app.services.titles import TitleService

logger = logging.getLogger(__name__)

_settings = get_settings()

_AUTH_SCHEME = "tma"


def get_title_service(db: Annotated[Session, Depends(get_db)]) -> TitleService:
    return TitleService(
        repo=TitleRepository(db),
        genres=GenreRepository(db),
        uow=SqlAlchemyUnitOfWork(db),
    )


def get_genre_repository(db: Annotated[Session, Depends(get_db)]) -> GenreRepository:
    return GenreRepository(db)


@dataclass(frozen=True, slots=True)
class Pagination:
    limit: int
    offset: int


def get_pagination(
    limit: Annotated[
        int,
        Query(ge=1, le=_settings.max_page_size, description="Размер страницы"),
    ] = _settings.default_page_size,
    offset: Annotated[int, Query(ge=0, le=100_000, description="Смещение")] = 0,
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


def _extract_raw_init_data(
    request: Request,
    authorization: str | None,
    header_init_data: str | None,
    allow_query_param: bool,
) -> str | None:
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == _AUTH_SCHEME and value.strip():
            return value.strip()
    if header_init_data:
        return header_init_data.strip()
    # Только для отладки, светится в логах.
    if allow_query_param:
        return request.query_params.get("init_data")
    return None


def get_init_data(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    x_telegram_init_data: Annotated[str | None, Header()] = None,
) -> InitData | None:
    raw = _extract_raw_init_data(
        request, authorization, x_telegram_init_data, allow_query_param=settings.debug
    )
    if not raw:
        return None
    return parse_init_data(raw, settings.bot_token, max_age=settings.init_data_max_age)


def get_current_user(
    init_data: Annotated[InitData | None, Depends(get_init_data)],
) -> TelegramUser | None:
    return init_data.user if init_data else None


def require_user(
    user: Annotated[TelegramUser | None, Depends(get_current_user)],
) -> TelegramUser:
    if user is None:
        raise AuthenticationError("Нужна initData")
    return user


def require_admin(
    init_data: Annotated[InitData | None, Depends(get_init_data)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TelegramUser | None:
    # Локалка, в прод конфиг такое не пустит.
    if not settings.auth_required:
        return None

    if init_data is None:
        raise AuthenticationError("Нужна initData")

    user = init_data.user
    if user.id not in settings.admin_ids:
        logger.warning(f"Не админ: {user.id}")
        raise PermissionDeniedError("Только для админов")
    return user


TitleServiceDep = Annotated[TitleService, Depends(get_title_service)]
GenreRepositoryDep = Annotated[GenreRepository, Depends(get_genre_repository)]
PaginationDep = Annotated[Pagination, Depends(get_pagination)]
