import pytest
from pydantic import ValidationError as PydanticValidationError

from app.config import Settings


def make_settings(**overrides) -> Settings:
    base = {
        "bot_token": "1:TOKEN",
        "auth_required": True,
        "debug": False,
        "admin_ids": "1",
        "cors_origins": "",
    }
    return Settings(**(base | overrides))


def test_auth_without_bot_token_is_rejected():
    with pytest.raises(PydanticValidationError, match="BOT_TOKEN"):
        make_settings(bot_token="")


def test_disabled_auth_requires_debug():
    with pytest.raises(PydanticValidationError, match="AUTH_REQUIRED=false"):
        make_settings(auth_required=False, debug=False)


def test_disabled_auth_is_allowed_in_debug():
    settings = make_settings(auth_required=False, debug=True, bot_token="")
    assert settings.auth_required is False


def test_page_sizes_must_be_consistent():
    with pytest.raises(PydanticValidationError, match="MAX_PAGE_SIZE"):
        make_settings(default_page_size=100, max_page_size=10)


@pytest.mark.parametrize("raw, expected", [
    ("", []),
    ("https://a.dev", ["https://a.dev"]),
    ("https://a.dev,https://b.dev", ["https://a.dev", "https://b.dev"]),
    ("  https://a.dev ,  https://b.dev  ", ["https://a.dev", "https://b.dev"]),
    ("https://a.dev,,", ["https://a.dev"]),
])
def test_cors_origins_parsed_from_csv(raw, expected):
    assert make_settings(cors_origins=raw).cors_origins == expected


@pytest.mark.parametrize("raw, expected", [
    ("", set()),
    ("1", {1}),
    ("1, 2 ,3", {1, 2, 3}),
    ("7,7", {7}),
])
def test_admin_ids_parsed_from_csv(raw, expected):
    assert make_settings(admin_ids=raw).admin_ids == expected


def test_non_numeric_admin_id_is_rejected():
    with pytest.raises(PydanticValidationError, match="ADMIN_IDS"):
        make_settings(admin_ids="1,abc")


@pytest.mark.parametrize("raw, expected", [("debug", "DEBUG"), ("  info ", "INFO")])
def test_log_level_is_normalized(raw, expected):
    assert make_settings(log_level=raw).log_level == expected


def test_unknown_log_level_is_rejected():
    with pytest.raises(PydanticValidationError, match="LOG_LEVEL"):
        make_settings(log_level="verbose")


@pytest.mark.parametrize("url, expected", [
    ("sqlite:///./database.db", True),
    ("postgresql+psycopg://u:p@host/db", False),
])
def test_is_sqlite_flag(url, expected):
    assert make_settings(database_url=url).is_sqlite is expected


def test_postgres_url_enables_pool_settings():
    settings = make_settings(database_url="postgresql+psycopg://u:p@host/db")
    assert settings.db_pool_size >= 1
    assert settings.is_sqlite is False
