import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode

from app.core.exceptions import AuthenticationError

_SECRET_KEY_SALT = b"WebAppData"

# сигнатура в HMAC не участвует
_EXCLUDED_FROM_CHECK_STRING = frozenset({"hash", "signature"})
MAX_INIT_DATA_LENGTH = 4096
CLOCK_SKEW_TOLERANCE = 300


@dataclass(frozen=True, slots=True)
class TelegramUser:
    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    is_premium: bool = False
    is_bot: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TelegramUser":
        user_id = raw.get("id")
        if not isinstance(user_id, int):
            raise AuthenticationError("Нет user.id")
        return cls(
            id=user_id,
            first_name=raw.get("first_name"),
            last_name=raw.get("last_name"),
            username=raw.get("username"),
            language_code=raw.get("language_code"),
            is_premium=bool(raw.get("is_premium", False)),
            is_bot=bool(raw.get("is_bot", False)),
        )


@dataclass(frozen=True, slots=True)
class InitData:
    user: TelegramUser
    auth_date: int
    query_id: str | None = None
    chat_type: str | None = None
    start_param: str | None = None
    raw: dict[str, str] = field(default_factory=dict, repr=False)


def _build_check_string(pairs: list[tuple[str, str]]) -> str:
    return "\n".join(
        f"{key}={value}"
        for key, value in sorted(pairs, key=lambda item: item[0])
        if key not in _EXCLUDED_FROM_CHECK_STRING
    )


def _secret_key(bot_token: str) -> bytes:
    return hmac.new(_SECRET_KEY_SALT, bot_token.encode("utf-8"), hashlib.sha256).digest()


def verify_init_data(init_data: str, bot_token: str) -> list[tuple[str, str]]:
    if not bot_token:
        raise AuthenticationError("BOT_TOKEN не задан")
    if not init_data:
        raise AuthenticationError("initData отсутствует")
    if len(init_data) > MAX_INIT_DATA_LENGTH:
        raise AuthenticationError("initData слишком длинная")

    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=False)
    if not pairs:
        raise AuthenticationError("initData битая")

    received_hash = next((value for key, value in pairs if key == "hash"), None)
    if not received_hash:
        raise AuthenticationError("Нет hash")

    expected_hash = hmac.new(
        _secret_key(bot_token),
        _build_check_string(pairs).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        raise AuthenticationError("Подпись initData неверна")

    return pairs


def parse_init_data(init_data: str, bot_token: str, *, max_age: int | None = None) -> InitData:
    pairs = verify_init_data(init_data, bot_token)
    data = dict(pairs)

    try:
        auth_date = int(data["auth_date"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Кривой auth_date") from exc

    if max_age is not None:
        age = int(time.time()) - auth_date
        if age > max_age:
            raise AuthenticationError(f"initData устарела (возраст {age} с)")
        if age < -CLOCK_SKEW_TOLERANCE:
            raise AuthenticationError("initData выдана в будущем")

    raw_user = data.get("user")
    if not raw_user:
        raise AuthenticationError("Нет пользователя")
    try:
        user_payload = json.loads(raw_user)
    except json.JSONDecodeError as exc:
        raise AuthenticationError("user не JSON") from exc
    if not isinstance(user_payload, dict):
        raise AuthenticationError("Кривой формат user")

    return InitData(
        user=TelegramUser.from_dict(user_payload),
        auth_date=auth_date,
        query_id=data.get("query_id"),
        chat_type=data.get("chat_type"),
        start_param=data.get("start_param"),
        raw=data,
    )


def build_init_data(bot_token: str, payload: dict[str, str]) -> str:
    pairs = sorted(payload.items())
    signature = hmac.new(
        _secret_key(bot_token),
        _build_check_string(pairs).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return urlencode([*pairs, ("hash", signature)])
