import pytest

from app.config import Settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.dependencies import require_admin, require_user
from app.security.telegram import InitData, TelegramUser


def settings_for(**overrides) -> Settings:
    base = {"bot_token": "1:TOKEN", "auth_required": True, "debug": False, "admin_ids": "42"}
    return Settings(**(base | overrides))


def init_data_for(user_id: int) -> InitData:
    return InitData(user=TelegramUser(id=user_id), auth_date=0)


def test_admin_passes():
    user = require_admin(init_data_for(42), settings_for())
    assert user.id == 42


def test_non_admin_is_denied():
    with pytest.raises(PermissionDeniedError):
        require_admin(init_data_for(7), settings_for())


def test_missing_init_data_is_unauthorized():
    with pytest.raises(AuthenticationError):
        require_admin(None, settings_for())


def test_empty_admin_list_denies_everyone():
    with pytest.raises(PermissionDeniedError):
        require_admin(init_data_for(42), settings_for(admin_ids=""))


def test_auth_can_be_disabled_for_local_development():
    assert require_admin(None, settings_for(auth_required=False, debug=True)) is None


def test_require_user_needs_init_data():
    with pytest.raises(AuthenticationError):
        require_user(None)


def test_require_user_returns_user():
    assert require_user(TelegramUser(id=5)).id == 5
