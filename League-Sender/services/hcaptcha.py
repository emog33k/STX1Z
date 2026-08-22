import logging
import os
import time
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
RES_DIR = BASE_DIR / "resources"

HC_API_URL = os.getenv("HC_API_URL", "https://asskicker.xyz/SolveHcaptcha")
HC_API_KEY = os.getenv("HC_API_KEY")
if not HC_API_KEY:
    key_path = RES_DIR / "captcha_key.txt"
    if key_path.is_file():
        HC_API_KEY = key_path.read_text(encoding="utf-8", errors="ignore").strip()

DEFAULT_TIMEOUT = float(os.getenv("HC_TIMEOUT_S", "120"))
RETRY_MAX = int(os.getenv("HC_RETRY_MAX", "20"))
RETRY_DELAY = float(os.getenv("HC_RETRY_DELAY_S", "2.5"))
PER_TRY_TIMEOUT = 15.0
TOKEN_MIN_LEN = 30
VERIFY_SSL = False

_POLL_ACTIVE_STATES = {"processing", "queued", "pending"}
_POLL_TERMINAL_ERRORS = {"error", "failed", "banned", "insufficient_funds"}

logger = logging.getLogger(__name__)


def _mk_proxies(proxy: str | None) -> dict[str, str] | None:
    if not proxy:
        return None
    normalized = proxy if "://" in proxy else "http://" + proxy
    return {"http": normalized, "https": normalized}


def _extract_token(data: dict) -> str | None:
    solution = data.get("solution")
    inner_data = data.get("data")
    candidates = [
        data.get("token"),
        solution.get("token") if isinstance(solution, dict) else None,
        solution,
        data.get("gRecaptchaResponse"),
        inner_data.get("token") if isinstance(inner_data, dict) else None,
        data.get("code"),
        data.get("answer"),
        data.get("captcha_key"),
    ]
    for value in candidates:
        if isinstance(value, str) and len(value) >= TOKEN_MIN_LEN:
            return value
    if isinstance(data.get("result"), dict):
        return _extract_token(data["result"])
    return None


def _post(
    url: str, json: dict, headers: dict, proxies: dict | None, timeout: float
) -> requests.Response:
    return requests.post(
        url, json=json, headers=headers, proxies=proxies, timeout=timeout, verify=VERIFY_SSL
    )


def _looks_like_token(text: str) -> bool:
    return len(text) >= TOKEN_MIN_LEN and " " not in text and "\n" not in text


def _status_url() -> str:
    override = os.getenv("HC_API_STATUS_URL")
    if override:
        return override
    return HC_API_URL.rstrip("/").rsplit("/", 1)[0] + "/status"


def _poll_task(
    task_id: str, proxies: dict | None, per_try: float, deadline: float
) -> str | None:
    url = _status_url()
    body = {"id": task_id, "key": HC_API_KEY}
    while time.time() < deadline:
        try:
            resp = _post(url, body, {"api_key": HC_API_KEY}, proxies, per_try)
            if resp.status_code != 200:
                time.sleep(RETRY_DELAY)
                continue
            data = resp.json()
            token = _extract_token(data)
            if token:
                return token
            state = (data.get("status") or data.get("state") or "").lower()
            if state in _POLL_ACTIVE_STATES:
                time.sleep(RETRY_DELAY)
                continue
            if state in _POLL_TERMINAL_ERRORS:
                raise RuntimeError(f"hCaptcha не решена: {data}")
        except requests.RequestException:
            time.sleep(RETRY_DELAY)
    return None


def _submit(
    payload: dict, proxies: dict | None, per_try: float
) -> tuple[str | None, str | None, str | None]:
    try:
        resp = _post(HC_API_URL, payload, {"api_key": HC_API_KEY}, proxies, per_try)
        body_text = resp.text.strip()
    except requests.RequestException as exc:
        return None, None, f"сеть: {exc}"

    if resp.status_code == 200:
        try:
            data = resp.json()
            token = _extract_token(data)
            return token, data.get("task_id") or data.get("id"), None
        except ValueError:
            if _looks_like_token(body_text):
                return body_text, None, None
            return None, None, None

    if resp.status_code in (400, 401) and (
        "MISSING_API_KEY" in body_text or "missing" in body_text.lower()
    ):
        return _submit_with_key_field(payload, proxies, per_try)

    return None, None, f"http {resp.status_code}: {body_text[:200]}"


def _submit_with_key_field(
    payload: dict, proxies: dict | None, per_try: float
) -> tuple[str | None, str | None, str | None]:
    try:
        resp = _post(HC_API_URL, {**payload, "key": HC_API_KEY}, {}, proxies, per_try)
        body_text = resp.text.strip()
    except requests.RequestException as exc:
        return None, None, f"сеть: {exc}"

    if resp.status_code != 200:
        return None, None, f"http {resp.status_code}: {body_text[:200]}"

    try:
        data = resp.json()
        return _extract_token(data), data.get("task_id") or data.get("id"), None
    except ValueError:
        if _looks_like_token(body_text):
            return body_text, None, None
        return None, None, None


def tw_solver(
    rq: str,
    proxy: str | None = None,
    website_key: str | None = None,
    website_url: str | None = None,
    timeout_s: float | None = None,
) -> str:
    if not HC_API_KEY:
        raise RuntimeError("HC_API_KEY не задан")

    payload = {"rqdata": rq, "rqd": rq, "proxy": proxy or ""}
    if website_key:
        payload["site_key"] = website_key
    if website_url:
        payload["site_url"] = website_url

    proxies = _mk_proxies(proxy)
    per_try = min(PER_TRY_TIMEOUT, timeout_s or DEFAULT_TIMEOUT)
    deadline = time.time() + (timeout_s or DEFAULT_TIMEOUT)

    last_err: str | None = None
    for _ in range(RETRY_MAX):
        if time.time() > deadline:
            break

        token, task_id, err = _submit(payload, proxies, per_try)
        if err:
            last_err = err
            time.sleep(RETRY_DELAY)
            continue

        if token:
            return token

        if task_id:
            polled = _poll_task(task_id, proxies, per_try, deadline)
            if polled:
                return polled
            last_err = "таймаут опроса статуса"
            break

        time.sleep(RETRY_DELAY)

    raise RuntimeError(f"hCaptcha не решена: {last_err or 'таймаут'}")
