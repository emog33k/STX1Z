import json
import time

import pytest

from app.core.exceptions import AuthenticationError
from app.security.telegram import (
    MAX_INIT_DATA_LENGTH,
    build_init_data,
    parse_init_data,
    verify_init_data,
)

TOKEN = "123456:TEST-BOT-TOKEN"


def signed(**overrides) -> str:
    payload = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": 7, "first_name": "Bob"}, separators=(",", ":")),
    } | overrides
    return build_init_data(TOKEN, payload)


def test_valid_init_data_parses():
    data = parse_init_data(signed(), TOKEN, max_age=3600)
    assert data.user.id == 7
    assert data.user.first_name == "Bob"


def test_signature_is_rejected_for_other_token():
    with pytest.raises(AuthenticationError):
        parse_init_data(signed(), "999:OTHER-TOKEN")


def test_tampered_payload_is_rejected():
    raw = signed()
    tampered = raw.replace("Bob", "Eve")
    with pytest.raises(AuthenticationError):
        verify_init_data(tampered, TOKEN)


def test_tampered_hash_is_rejected():
    raw = signed()
    with pytest.raises(AuthenticationError):
        verify_init_data(raw[:-4] + "0000", TOKEN)


def test_stale_init_data_is_rejected():
    raw = signed(auth_date=str(int(time.time()) - 100_000))
    with pytest.raises(AuthenticationError, match="устарела"):
        parse_init_data(raw, TOKEN, max_age=3600)


def test_init_data_from_future_is_rejected():
    raw = signed(auth_date=str(int(time.time()) + 3600))
    with pytest.raises(AuthenticationError, match="будущем"):
        parse_init_data(raw, TOKEN, max_age=86_400)


def test_age_is_not_checked_without_max_age():
    raw = signed(auth_date=str(int(time.time()) - 100_000))
    assert parse_init_data(raw, TOKEN).user.id == 7


@pytest.mark.parametrize("raw", ["", "not-a-query-string", "user=%7B%7D"])
def test_broken_init_data_is_rejected(raw):
    with pytest.raises(AuthenticationError):
        parse_init_data(raw, TOKEN)


def test_oversized_init_data_is_rejected():
    with pytest.raises(AuthenticationError, match="длинная"):
        verify_init_data("x" * (MAX_INIT_DATA_LENGTH + 1), TOKEN)


def test_missing_bot_token_is_rejected():
    with pytest.raises(AuthenticationError, match="BOT_TOKEN"):
        verify_init_data(signed(), "")


def test_signature_field_is_excluded_from_check_string():
    # Telegram добавляет собственную Ed25519-подпись, она не участвует в HMAC
    raw = signed()
    assert parse_init_data(f"{raw}&signature=abc", TOKEN).user.id == 7


def test_user_without_id_is_rejected():
    raw = build_init_data(TOKEN, {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"first_name": "NoId"}),
    })
    with pytest.raises(AuthenticationError, match="user.id"):
        parse_init_data(raw, TOKEN)


def test_init_data_without_user_is_rejected():
    raw = build_init_data(TOKEN, {"auth_date": str(int(time.time()))})
    with pytest.raises(AuthenticationError, match="пользовател"):
        parse_init_data(raw, TOKEN)


def test_user_that_is_not_json_is_rejected():
    raw = build_init_data(TOKEN, {
        "auth_date": str(int(time.time())),
        "user": "{broken",
    })
    with pytest.raises(AuthenticationError, match="JSON"):
        parse_init_data(raw, TOKEN)


def test_user_that_is_not_an_object_is_rejected():
    raw = build_init_data(TOKEN, {
        "auth_date": str(int(time.time())),
        "user": "[1, 2]",
    })
    with pytest.raises(AuthenticationError, match="формат"):
        parse_init_data(raw, TOKEN)


def test_non_numeric_auth_date_is_rejected():
    raw = build_init_data(TOKEN, {
        "auth_date": "вчера",
        "user": json.dumps({"id": 1}),
    })
    with pytest.raises(AuthenticationError, match="auth_date"):
        parse_init_data(raw, TOKEN)


def test_init_data_without_hash_is_rejected():
    with pytest.raises(AuthenticationError, match="hash"):
        verify_init_data("auth_date=1&user=%7B%7D", TOKEN)


def test_optional_fields_are_parsed():
    raw = build_init_data(TOKEN, {
        "auth_date": str(int(time.time())),
        "query_id": "QID",
        "chat_type": "private",
        "start_param": "ref42",
        "user": json.dumps({"id": 3, "username": "u", "is_premium": True}),
    })
    data = parse_init_data(raw, TOKEN)
    assert data.query_id == "QID"
    assert data.chat_type == "private"
    assert data.start_param == "ref42"
    assert data.user.is_premium is True


def test_matches_reference_signature_from_telegram_spec():
    # Подписываем так, как это делает сам Telegram, не через build_init_data:
    # иначе подмена соли осталась бы незамеченной — обе стороны врали бы одинаково.
    import hashlib
    import hmac
    from urllib.parse import urlencode

    payload = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": 42, "first_name": "Ref"}, separators=(",", ":")),
    }
    pairs = sorted(payload.items())
    check_string = "\n".join(f"{key}={value}" for key, value in pairs)
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    raw = urlencode([*pairs, ("hash", signature)])

    assert parse_init_data(raw, TOKEN, max_age=3600).user.id == 42
