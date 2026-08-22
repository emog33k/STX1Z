from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.dependencies import PaginationDep, TitleServiceDep, require_admin
from app.enums import MAX_YEAR, MIN_YEAR, TitleSort, TitleType
from app.repositories.titles import TitleFilters
from app.schemas import (
    ErrorOut,
    Page,
    TitleCreate,
    TitleDetailOut,
    TitleOut,
    TitleUpdate,
)

router = APIRouter(prefix="/api/titles", tags=["titles"])

TitleId = Annotated[int, Path(ge=1)]

ADMIN_ONLY = [Depends(require_admin)]

_NOT_FOUND = {404: {"model": ErrorOut, "description": "Не найден"}}
_WRITE_ERRORS = {
    401: {"model": ErrorOut, "description": "Нет initData"},
    403: {"model": ErrorOut, "description": "Не админ"},
    409: {"model": ErrorOut, "description": "Дубль"},
    422: {"model": ErrorOut, "description": "Не прошло проверку"},
}


@router.get(
    "",
    response_model=Page[TitleOut],
    summary="Каталог",
)
def list_titles(
    service: TitleServiceDep,
    pagination: PaginationDep,
    q: Annotated[
        str | None, Query(max_length=100, description="поиск по названию")
    ] = None,
    title_type: Annotated[
        TitleType | None, Query(alias="type")
    ] = None,
    genre: Annotated[
        str | None, Query(max_length=64, description="slug жанра")
    ] = None,
    year_from: Annotated[int | None, Query(ge=MIN_YEAR, le=MAX_YEAR)] = None,
    year_to: Annotated[int | None, Query(ge=MIN_YEAR, le=MAX_YEAR)] = None,
    sort: Annotated[TitleSort, Query()] = TitleSort.ID_DESC,
) -> dict:
    filters = TitleFilters(
        q=q,
        type=title_type,
        genre=genre,
        year_from=year_from,
        year_to=year_to,
        sort=sort,
    )
    items, total = service.list_titles(
        filters, limit=pagination.limit, offset=pagination.offset
    )
    return {
        "items": items,
        "total": total,
        "limit": pagination.limit,
        "offset": pagination.offset,
    }


@router.get(
    "/{title_id}",
    response_model=TitleDetailOut,
    responses=_NOT_FOUND,
    summary="Тайтл",
)
def get_title(title_id: TitleId, service: TitleServiceDep):
    return service.get(title_id, with_episodes=True)


@router.post(
    "",
    response_model=TitleDetailOut,
    status_code=status.HTTP_201_CREATED,
    responses=_WRITE_ERRORS,
    dependencies=ADMIN_ONLY,
    summary="Добавить тайтл",
)
def create_title(
    payload: TitleCreate,
    service: TitleServiceDep,
    response: Response,
):
    title = service.create(payload)
    response.headers["Location"] = f"{router.prefix}/{title.id}"
    return title


@router.put(
    "/{title_id}",
    response_model=TitleDetailOut,
    responses=_NOT_FOUND | _WRITE_ERRORS,
    dependencies=ADMIN_ONLY,
    summary="Заменить тайтл",
)
def replace_title(
    title_id: TitleId,
    payload: TitleCreate,
    service: TitleServiceDep,
):
    return service.replace(title_id, payload)


@router.patch(
    "/{title_id}",
    response_model=TitleDetailOut,
    responses=_NOT_FOUND | _WRITE_ERRORS,
    dependencies=ADMIN_ONLY,
    summary="Изменить тайтл",
)
def update_title(
    title_id: TitleId,
    payload: TitleUpdate,
    service: TitleServiceDep,
):
    return service.update(title_id, payload)


@router.delete(
    "/{title_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_NOT_FOUND | _WRITE_ERRORS,
    dependencies=ADMIN_ONLY,
    summary="Удалить тайтл",
)
def delete_title(title_id: TitleId, service: TitleServiceDep) -> Response:
    service.delete(title_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
