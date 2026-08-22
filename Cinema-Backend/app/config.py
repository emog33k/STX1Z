from functools import lru_cache
from typing import Annotated, Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _split_csv(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(raw, list | tuple | set | frozenset):
        return [str(item).strip() for item in raw if str(item).strip()]
    raise ValueError(f"нужна строка или список, пришло {type(raw)!r}")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "CineApp Backend"
    app_version: str = "0.9.0"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = False

    database_url: str = "sqlite:///./database.db"
    db_echo: bool = False
    auto_upgrade_db: bool = False
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=20, ge=0, le=100)

    bot_token: str = ""
    webapp_url: str = ""
    auth_required: bool = True
    init_data_max_age: int = Field(default=3600, ge=60)
    admin_ids: Annotated[set[int], NoDecode] = Field(default_factory=set)

    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    root_path: str = ""

    default_page_size: int = Field(default=24, ge=1, le=500)
    max_page_size: int = Field(default=96, ge=1, le=1000)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: Any) -> list[str]:
        return _split_csv(value)

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: Any) -> set[int]:
        parsed: set[int] = set()
        for item in _split_csv(value):
            try:
                parsed.add(int(item))
            except ValueError as exc:
                raise ValueError(f"ADMIN_IDS: {item!r} не является числом") from exc
        return parsed

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: Any) -> str:
        level = str(value).strip().upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
        if level not in allowed:
            raise ValueError(f"LOG_LEVEL должен быть одним из {sorted(allowed)}")
        return level

    @model_validator(mode="after")
    def _check_consistency(self) -> "Settings":
        if self.auth_required and not self.bot_token:
            raise ValueError("AUTH_REQUIRED=true, но BOT_TOKEN пустой")
        if not self.auth_required and not self.debug:
            raise ValueError("AUTH_REQUIRED=false можно только с DEBUG=true")
        if self.max_page_size < self.default_page_size:
            raise ValueError("MAX_PAGE_SIZE меньше DEFAULT_PAGE_SIZE")
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
