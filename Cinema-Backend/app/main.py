import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logs import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.base import engine
from app.db.schema_state import ensure_schema_is_current, upgrade_to_head
from app.routers import genres as genres_router
from app.routers import system as system_router
from app.routers import titles as titles_router

settings = get_settings()
configure_logging(settings.log_level, json_output=settings.log_json)
logger = logging.getLogger(__name__)


def _prepare_schema() -> None:
    if settings.auto_upgrade_db:
        logger.warning("AUTO_UPGRADE_DB=true, миграции накатываются на старте")
        upgrade_to_head()
    ensure_schema_is_current(engine)


def _log_startup_warnings() -> None:
    if not settings.auth_required:
        logger.warning("AUTH_REQUIRED=false, запись открыта всем")
    elif not settings.admin_ids:
        logger.warning("ADMIN_IDS пуст, писать некому")
    if not settings.cors_origins:
        logger.warning("CORS_ORIGINS пуст")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info(f"Запуск {settings.app_name} {settings.app_version}")
    _prepare_schema()
    _log_startup_warnings()
    yield
    engine.dispose()
    logger.info("Остановка приложения")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    root_path=settings.root_path,
    lifespan=lifespan,
    description="мини-кинотеатр для телеграм мини-апп",
)

app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Telegram-Init-Data", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Location"],
    max_age=3600,
)

register_error_handlers(app)

app.include_router(system_router.router)
app.include_router(titles_router.router)
app.include_router(genres_router.router)
