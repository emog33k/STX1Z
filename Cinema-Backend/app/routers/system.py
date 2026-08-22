import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.base import get_db
from app.dependencies import require_user
from app.schemas import HealthOut, TelegramUserOut
from app.security.telegram import TelegramUser

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


@router.get("/", include_in_schema=False)
def root(settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    return {"status": "ok", "service": settings.app_name, "docs": "/docs"}


@router.get("/health", response_model=HealthOut, summary="Живость")
def health(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> dict:
    database = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("База недоступна")
        database = "unavailable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if database == "ok" else "degraded",
        "version": settings.app_version,
        "database": database,
    }


@router.get(
    "/api/me",
    response_model=TelegramUserOut,
    summary="Текущий пользователь",
)
def me(
    user: Annotated[TelegramUser, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    return {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "username": user.username,
        "language_code": user.language_code,
        "is_premium": user.is_premium,
        "is_admin": user.id in settings.admin_ids,
    }
