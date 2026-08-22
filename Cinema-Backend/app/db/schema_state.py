from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

from app.config import get_settings

BASE_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BASE_DIR / "alembic.ini"


class SchemaOutOfDateError(RuntimeError):
    pass


def alembic_config(database_url: str | None = None) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BASE_DIR / "migrations"))
    config.attributes["configure_logger"] = False
    url = database_url or get_settings().database_url
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def upgrade_to_head(database_url: str | None = None) -> None:
    command.upgrade(alembic_config(database_url), "head")


def ensure_schema_is_current(engine: Engine) -> None:
    head = head_revision()
    current = current_revision(engine)
    if current == head:
        return
    if current is None:
        raise SchemaOutOfDateError("База не размечена, нужен alembic upgrade head")
    raise SchemaOutOfDateError(
        f"Схема на {current}, нужна {head}. Выполни alembic upgrade head"
    )
