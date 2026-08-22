import base64
import logging
import time

import requests

logger = logging.getLogger(__name__)

VERIFY_SSL = False
LOGIN_TIMEOUT_S = 180
SUMMONER_TIMEOUT_S = 120
CHAT_TIMEOUT_S = 120
POLL_S = 1.0
MSG_RETRY_PAUSE_S = 0.8
SEND_MAX_TRIES = 2
POST_CREATE_WAIT_S = 0.3

_UNAVAILABLE_STATES = {"chat_down", "offline", ""}


def make_lcu_session(lcu_port: int, lcu_token: str) -> requests.Session:
    session = requests.Session()
    session.verify = VERIFY_SSL
    auth = base64.b64encode(f"riot:{lcu_token}".encode()).decode()
    session.headers.update(
        {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}
    )
    session.base_url = f"https://127.0.0.1:{lcu_port}"
    return session


def wait_login_succeeded(
    lcu: requests.Session, timeout_s: int = LOGIN_TIMEOUT_S, poll: float = POLL_S
) -> None:
    deadline = time.time() + timeout_s
    url = f"{lcu.base_url}/lol-login/v1/session"
    while time.time() < deadline:
        try:
            resp = lcu.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json() or {}
                state = (data.get("state") or data.get("phase") or "").upper()
                if state == "SUCCEEDED":
                    return
                if state == "FAILED":
                    raise RuntimeError("Сессия LoL login: FAILED")
        except requests.RequestException:
            pass
        time.sleep(poll)
    raise TimeoutError("Таймаут lol-login session")


def wait_summoner_ready(
    lcu: requests.Session, timeout_s: int = SUMMONER_TIMEOUT_S, poll: float = POLL_S
) -> None:
    deadline = time.time() + timeout_s
    url = f"{lcu.base_url}/lol-summoner/v1/current-summoner"
    while time.time() < deadline:
        try:
            resp = lcu.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json() or {}
                has_id = data.get("puuid") or data.get("summonerId")
                has_name = data.get("displayName") or data.get("gameName")
                if has_id and has_name:
                    return
        except requests.RequestException:
            pass
        time.sleep(poll)
    raise TimeoutError("Таймаут current-summoner")


def wait_chat_ready(
    lcu: requests.Session, timeout_s: int = CHAT_TIMEOUT_S, poll: float = POLL_S
) -> None:
    deadline = time.time() + timeout_s
    url = f"{lcu.base_url}/lol-chat/v1/me"
    while time.time() < deadline:
        try:
            resp = lcu.get(url, timeout=5)
            if resp.status_code == 200:
                availability = (resp.json() or {}).get("availability", "").lower()
                if availability not in _UNAVAILABLE_STATES:
                    return
        except requests.RequestException:
            pass
        time.sleep(poll)
    raise TimeoutError("Чат RC не готов")


def wait_ready_full(lcu: requests.Session) -> None:
    wait_login_succeeded(lcu)
    wait_summoner_ready(lcu)
    wait_chat_ready(lcu)


def set_available(lcu: requests.Session) -> None:
    try:
        lcu.patch(
            f"{lcu.base_url}/lol-chat/v1/me", json={"availability": "chat"}, timeout=5
        )
    except requests.RequestException:
        pass


def _friend_pid(friend: dict) -> str | None:
    value = friend.get("pid") or friend.get("id")
    return value if isinstance(value, str) and value else None


def _friend_puuid(friend: dict) -> str | None:
    value = friend.get("puuid")
    return value if isinstance(value, str) and value else None


def _left_of_at(conv_id: str) -> str:
    return conv_id.split("@", 1)[0] if isinstance(conv_id, str) else ""


def _list_conversations(lcu: requests.Session) -> list[dict]:
    try:
        resp = lcu.get(f"{lcu.base_url}/lol-chat/v1/conversations", timeout=10)
        if resp.status_code == 200:
            return resp.json() or []
    except requests.RequestException:
        pass
    return []


def _find_conv_id_for_friend(lcu: requests.Session, friend: dict) -> str | None:
    puuid = _friend_puuid(friend)
    pid = _friend_pid(friend)
    conversations = _list_conversations(lcu)
    logger.info(f"Диалогов: {len(conversations)}")

    if puuid:
        for conv in conversations:
            conv_id = conv.get("id", "")
            if conv.get("type") == "chat" and _left_of_at(conv_id) == puuid:
                logger.info(f"Диалог по puuid: {puuid} -> {conv_id}")
                return conv_id

    for conv in conversations:
        if conv.get("type") != "chat":
            continue
        conv_id = conv.get("id", "")
        for participant in conv.get("participants") or []:
            participant_pid = participant.get("pid") or ""
            if pid and participant_pid == pid:
                logger.info(f"Диалог по participant pid: {conv_id}")
                return conv_id
            if puuid and (
                _left_of_at(participant_pid) == puuid or participant.get("puuid") == puuid
            ):
                logger.info(f"Диалог по participant puuid: {conv_id}")
                return conv_id

    return None


def _create_conversation(lcu: requests.Session, conv_id: str) -> bool:
    body: dict = {"id": conv_id, "type": "chat"}
    if "@pvp.net" in conv_id:
        body["participants"] = [{"pid": conv_id}]
    try:
        resp = lcu.post(
            f"{lcu.base_url}/lol-chat/v1/conversations", json=body, timeout=10
        )
        logger.info(
            f"Создан диалог id={conv_id} => {resp.status_code} {(resp.text or '')[:120]!r}"
        )
        created = resp.status_code in (200, 201)
        if created:
            time.sleep(POST_CREATE_WAIT_S)
        return created
    except requests.RequestException as exc:
        logger.error(f"Не создан диалог id={conv_id} -> {exc}")
        raise


def lcu_list_friends(lcu: requests.Session) -> list[dict]:
    resp = lcu.get(f"{lcu.base_url}/lol-chat/v1/friends", timeout=15)
    if resp.status_code != 200:
        wait_chat_ready(lcu, 90)
        resp = lcu.get(f"{lcu.base_url}/lol-chat/v1/friends", timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"friends => {resp.status_code} {resp.text}")
    friends = resp.json() or []
    logger.info(f"Друзей: {len(friends)}")
    return friends


def lcu_send_message(lcu: requests.Session, conv_id: str, text: str) -> bool:
    logger.info(f"Отправка -> conv_id={conv_id}")

    set_available(lcu)
    wait_chat_ready(lcu, 90)

    url = f"{lcu.base_url}/lol-chat/v1/conversations/{conv_id}/messages"
    for attempt in range(SEND_MAX_TRIES):
        try:
            resp = lcu.post(url, json={"body": text}, timeout=10)
            logger.info(f"Отправка id={conv_id} try={attempt + 1} => {resp.status_code}")
            if resp.status_code == 200:
                return True
            if (
                resp.status_code == 404
                and attempt == 0
                and _create_conversation(lcu, conv_id)
            ):
                continue
            if resp.status_code in (409, 429) and attempt == 0:
                time.sleep(MSG_RETRY_PAUSE_S)
                continue
            logger.error(
                f"Отправка провалилась id={conv_id} code={resp.status_code} "
                f"body={(resp.text or '')[:180]!r}"
            )
            return False
        except requests.RequestException as exc:
            logger.warning(
                f"Отправка req err id={conv_id} try={attempt + 1} -> {exc}"
            )
            time.sleep(0.6 + 0.2 * attempt)
    return False


def lcu_get_or_create_conversation_id(
    lcu: requests.Session, friend: dict
) -> str | None:
    existing = _find_conv_id_for_friend(lcu, friend)
    if existing:
        return existing

    candidate = _friend_pid(friend) or _friend_puuid(friend)
    if not candidate:
        return None

    if _create_conversation(lcu, candidate):
        return candidate
    return None


def lcu_list_recent_messages(
    lcu: requests.Session, conv_id: str, limit: int = 5
) -> list[dict]:
    url = f"{lcu.base_url}/lol-chat/v1/conversations/{conv_id}/messages"
    try:
        resp = lcu.get(url, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"Список сообщений {conv_id} => {resp.status_code}")
            return []
        messages = resp.json() or []
        if isinstance(messages, list):
            return messages[-limit:]
        return []
    except requests.RequestException as exc:
        logger.warning(f"Список сообщений req err id={conv_id} -> {exc}")
        return []
