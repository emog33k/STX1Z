import base64
import logging
import random
import re
import string
import time

import psutil
import requests

logger = logging.getLogger(__name__)

VERIFY_SSL = False
ATTACH_TOKEN_TRIES = 6
LOL_LAUNCH_TRIES = 6
EULA_TRIES = 8
ATTACH_RETRY_DELAY_S = 0.5
LAUNCH_RETRY_DELAY_S = 0.5
EULA_RETRY_DELAY_S = 1.0
LCU_PROBE_TIMEOUT_S = 2.0
LCU_WAIT_TIMEOUT_S = 120
LCU_WAIT_POLL_S = 0.5
NONCE_LEN = 22

_PORT_RE = re.compile(r"--app-port=(\d+)")
_PASS_RE = re.compile(r"--remoting-auth-token=([\w\-]+)")

_LCU_PROBE_PATHS = (
    "/riotclient/region-locale",
    "/lol-platform-config/v1/namespaces",
    "/lol-summoner/v1/current-summoner",
)

_AUTH_SCOPE = [
    "openid",
    "link",
    "ban",
    "lol_region",
    "lol",
    "summoner",
    "offline_access",
]


def _auth_header(rtok: str) -> str:
    return "Basic " + base64.b64encode(f"riot:{rtok}".encode()).decode()


def ux_call(
    ux_port: int,
    ux_rtok: str,
    method: str,
    path: str,
    json: dict | None = None,
    timeout: int = 20,
) -> requests.Response:
    return requests.request(
        method,
        f"https://127.0.0.1:{ux_port}{path}",
        headers={"Authorization": _auth_header(ux_rtok), "Content-Type": "application/json"},
        json=json,
        timeout=timeout,
        verify=VERIFY_SSL,
    )


def attach_login_token_to_ux(ux_port: int, ux_rtok: str, login_token: str) -> None:
    last_err: Exception | None = None
    for _ in range(ATTACH_TOKEN_TRIES):
        try:
            resp = ux_call(
                ux_port,
                ux_rtok,
                "PUT",
                "/rso-auth/v1/session/login-token",
                json={
                    "authentication_type": "RiotAuth",
                    "login_token": login_token,
                    "persist_login": False,
                },
                timeout=20,
            )
            if resp.status_code in (200, 201, 204):
                return
            last_err = RuntimeError(
                f"UX PUT /session/login-token => {resp.status_code} {resp.text[:200]}"
            )
        except requests.RequestException as exc:
            last_err = exc
        time.sleep(ATTACH_RETRY_DELAY_S)
    raise last_err or RuntimeError("UX: токен не прикрепился")


def create_authorizations(ux_port: int, ux_rtok: str) -> None:
    nonce = "".join(random.choices(string.ascii_letters + string.digits, k=NONCE_LEN))
    body = {
        "clientId": "riot-client",
        "redirectUri": "http://localhost/redirect",
        "nonce": nonce,
        "responseType": ["token", "id_token"],
        "scope": _AUTH_SCOPE,
    }
    resp = ux_call(
        ux_port, ux_rtok, "POST", "/rso-auth/v2/authorizations", json=body, timeout=25
    )
    if resp.status_code != 200:
        raise RuntimeError(f"UX POST /authorizations => {resp.status_code} {resp.text}")


def ux_launch_lol(
    ux_port: int,
    ux_rtok: str,
    patchline: str = "live",
    connect_timeout: int = 5,
    read_timeout: int = 30,
) -> None:
    headers = {"Authorization": _auth_header(ux_rtok), "Content-Type": "application/json"}
    url = (
        f"https://127.0.0.1:{ux_port}/product-launcher/v1/products/"
        f"league_of_legends/patchlines/{patchline}"
    )

    for _ in range(LOL_LAUNCH_TRIES):
        try:
            resp = requests.post(
                url,
                headers=headers,
                json={},
                timeout=(connect_timeout, read_timeout),
                verify=VERIFY_SSL,
            )
            if resp.status_code in (200, 204):
                logger.info(f"UX: запуск League OK ({resp.status_code})")
                return
            logger.debug(f"UX POST {url} => {resp.status_code} {resp.text[:200]}")
        except requests.ReadTimeout:
            logger.warning("UX launch: ReadTimeout, пробуем ждать LCU по процессу")
            return
        except requests.RequestException as exc:
            logger.debug(f"UX launch req error: {exc}")
        time.sleep(LAUNCH_RETRY_DELAY_S)

    logger.warning("UX launch без успешного ответа, ждём LCU по процессу")


def _parse_lcu_from_proc(proc: psutil.Process) -> tuple[int, str] | None:
    try:
        cmdline = " ".join(proc.info.get("cmdline") or [])
        port_match = _PORT_RE.search(cmdline)
        token_match = _PASS_RE.search(cmdline)
        if port_match and token_match:
            return int(port_match.group(1)), token_match.group(1)
    except psutil.Error:
        pass
    return None


def snapshot_lcu_pids() -> set[int]:
    pids: set[int] = set()
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            if proc.info["name"] == "LeagueClientUx.exe":
                pids.add(proc.info["pid"])
        except psutil.Error:
            continue
    return pids


def probe_lcu_ready(port: int, token: str, timeout_s: float = LCU_PROBE_TIMEOUT_S) -> bool:
    headers = {"Authorization": _auth_header(token)}
    for path in _LCU_PROBE_PATHS:
        url = f"https://127.0.0.1:{port}{path}"
        try:
            resp = requests.get(url, headers=headers, timeout=timeout_s, verify=VERIFY_SSL)
            if resp.status_code in (200, 204):
                return True
        except requests.RequestException:
            pass
    return False


def wait_lcu_by_process(
    start_after_ts: float,
    timeout_s: int = LCU_WAIT_TIMEOUT_S,
    exclude_pids: set[int] | None = None,
) -> tuple[int, str]:
    deadline = time.time() + timeout_s
    exclude_pids = exclude_pids or set()
    while time.time() < deadline:
        for proc in psutil.process_iter(["name", "pid", "cmdline", "create_time"]):
            try:
                if proc.info["name"] != "LeagueClientUx.exe":
                    continue
                if proc.info["pid"] in exclude_pids:
                    continue
                ctime = float(proc.info.get("create_time") or 0)
                if ctime < (start_after_ts - 0.25):
                    continue
                parsed = _parse_lcu_from_proc(proc)
                if not parsed:
                    continue
                port, token = parsed
                if probe_lcu_ready(port, token):
                    logger.info(
                        f"LCU найден по процессу: pid={proc.info['pid']} port={port}"
                    )
                    return port, token
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        time.sleep(LCU_WAIT_POLL_S)
    raise TimeoutError("LCU по процессам не найден")


def launch_lol_for_session(
    ux_port: int, ux_rtok: str, patchline: str = "live"
) -> tuple[int, str]:
    known_pids = snapshot_lcu_pids()
    started_at = time.time()
    ux_launch_lol(ux_port, ux_rtok, patchline=patchline)
    return wait_lcu_by_process(start_after_ts=started_at, exclude_pids=known_pids)


def _eula_state_from_json(data) -> str:
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        return (data.get("state") or data.get("value") or data.get("status") or "").strip()
    return ""


def ux_eula_get_state(ux_port: int, ux_rtok: str, timeout_s: int = 12) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            resp = ux_call(
                ux_port, ux_rtok, "GET", "/eula/v1/agreement/acceptance", timeout=8
            )
            if resp.status_code == 200:
                try:
                    state = _eula_state_from_json(resp.json())
                except ValueError:
                    state = (resp.text or "").strip().strip('"')
                if state:
                    return state
        except requests.RequestException:
            pass
        time.sleep(0.4)
    return "Unknown"


def ux_eula_accept(ux_port: int, ux_rtok: str) -> bool:
    try:
        resp = ux_call(
            ux_port, ux_rtok, "PUT", "/eula/v1/agreement/acceptance", json={}, timeout=10
        )
        accepted = resp.status_code in (200, 201, 202, 204)
        if not accepted:
            logger.debug(f"EULA PUT => {resp.status_code} {resp.text[:200]}")
        return accepted
    except requests.RequestException as exc:
        logger.debug(f"EULA PUT exception: {exc}")
        return False


def handle_eula_if_needed(ux_port: int, ux_rtok: str) -> None:
    for _ in range(EULA_TRIES):
        state = ux_eula_get_state(ux_port, ux_rtok, timeout_s=3)
        logger.debug(f"EULA state: {state}")
        if state in ("Accepted", "Unknown"):
            return
        if state == "AcceptanceRequired" and ux_eula_accept(ux_port, ux_rtok):
            logger.info("EULA: условия приняты")
            return
        time.sleep(EULA_RETRY_DELAY_S)
    logger.warning("EULA: не удалось подтвердить")


def ux_logout(ux_port: int, ux_rtok: str) -> bool:
    resp = ux_call(ux_port, ux_rtok, "DELETE", "/rso-auth/v1/session", timeout=15)
    if resp.status_code in (200, 204):
        return True

    try:
        fallback = ux_call(
            ux_port, ux_rtok, "DELETE", "/rso-auth/v2/authorizations", timeout=10
        )
        if fallback.status_code in (200, 204):
            return True
    except requests.RequestException:
        pass

    return False
