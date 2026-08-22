import base64
import json
import logging

import requests

from core.config import CFG
from services.hcaptcha import tw_solver

logger = logging.getLogger(__name__)

VERIFY_SSL = False
LOGIN_URL = "https://authenticate.riotgames.com/api/v1/login"
ORIGIN_URL = "https://authenticate.riotgames.com/"
TOKEN_MIN_LEN = 30

API_HEADERS = {
    "User-Agent": CFG.user_agent,
    "Accept": "application/json",
    "Accept-Encoding": "deflate, gzip, zstd",
    "Content-Type": "application/json",
    "Connection": "keep-alive",
    "Origin": "https://authenticate.riotgames.com",
}
CLIENT_HINTS = {
    "sec-ch-ua": '"Not.A/Brand";v="8", "Chromium";v="125"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "X-Riot-ClientVersion": f"riotclient {CFG.sdk_version}",
    "X-Riot-ClientPlatform": base64.b64encode(
        b'{"platform":"windows","arch":"x64"}'
    ).decode(),
}
DEFAULT_HEADERS = {**API_HEADERS, **CLIENT_HINTS}


def _safe_json(resp: requests.Response, where: str) -> dict:
    content_type = resp.headers.get("Content-Type", "")
    if content_type.startswith("application/json"):
        return resp.json()
    raise RuntimeError(
        f"{where}: ожидался JSON, пришло {resp.status_code} {content_type} – {resp.text}"
    )


def _build_proxies(proxy: str | None) -> dict[str, str] | None:
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def _solve_hcaptcha_if_needed(resp_json: dict, proxy: str | None) -> str | None:
    if "captcha" not in resp_json:
        return None
    if not tw_solver:
        raise RuntimeError("Riot вернул hCaptcha, а решатель не подключен")

    logger.info("Решаем капчу")
    rq_data = resp_json["captcha"]["hcaptcha"]["data"]
    token = tw_solver(rq_data, proxy=proxy)
    if not token or len(token) < TOKEN_MIN_LEN:
        raise RuntimeError("hCaptcha не решена")
    logger.info(f"hCaptcha решена len={len(token)} head={token[:10]!r}")
    return token


def _login_body(username: str | None, password: str | None, captcha: str | None) -> dict:
    return {
        "campaign": None,
        "clientId": CFG.client_id,
        "language": "ru_RU",
        "platform": "windows",
        "sdkVersion": CFG.sdk_version,
        "remember": False,
        "type": "auth",
        "riot_identity": {
            "username": username,
            "password": password,
            "captcha": captcha,
            "state": "auth" if username is None else None,
        },
    }


def network_login(username: str, password: str, proxy: str | None) -> str:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    proxies = _build_proxies(proxy)
    if proxies:
        session.proxies.update(proxies)

    session.get(ORIGIN_URL, timeout=10, verify=VERIFY_SSL)

    init = _safe_json(
        session.post(
            LOGIN_URL, json=_login_body(None, None, None), timeout=15, verify=VERIFY_SSL
        ),
        "POST /login",
    )

    captcha_token = _solve_hcaptcha_if_needed(init, proxy)
    captcha_field = f"hcaptcha {captcha_token}" if captcha_token else None

    auth = _safe_json(
        session.put(
            LOGIN_URL,
            json=_login_body(username, password, captcha_field),
            timeout=25,
            verify=VERIFY_SSL,
        ),
        "PUT /login",
    )
    if auth.get("type") != "success":
        raise RuntimeError(f"Логин отклонён: {json.dumps(auth, ensure_ascii=False)}")

    login_token = auth["success"]["login_token"]
    logger.info(f"login_token получен len={len(login_token)}")
    return login_token
