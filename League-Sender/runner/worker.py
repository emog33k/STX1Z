import logging
import time
from queue import Empty, Queue
from typing import Any

import requests

from core.config import CFG
from runner.client_handle import ClientHandle
from services.auth import network_login
from services.lcu import (
    lcu_get_or_create_conversation_id,
    lcu_list_friends,
    lcu_list_recent_messages,
    lcu_send_message,
    make_lcu_session,
    wait_ready_full,
)
from services.riot_client import close_lcu_by_port_token
from services.ux import (
    attach_login_token_to_ux,
    create_authorizations,
    handle_eula_if_needed,
    launch_lol_for_session,
    ux_logout,
)

logger = logging.getLogger(__name__)

VERIFY_LOOKUP_DELAY_S = 1.0
LOGOUT_RETRY_DELAY_S = 1.0
TASK_POLL_S = 1.0

EMPTY_METRICS: dict[str, int] = {
    "total_friends": 0,
    "sent_ok": 0,
    "sent_fail": 0,
    "duplicates_in_list": 0,
    "skipped_dupe": 0,
    "verify_mismatch": 0,
}


def _friend_key(friend: dict[str, Any]) -> str:
    return (
        friend.get("puuid")
        or friend.get("id")
        or f"{friend.get('gameName', '?')}#{friend.get('gameTag', '?')}"
    )


def _friend_name(friend: dict[str, Any]) -> str:
    return f"{friend.get('gameName', '?')}#{friend.get('gameTag', '?')}"


def _reprobe_lcu(client: ClientHandle) -> requests.Session:
    lcu_port, lcu_token = launch_lol_for_session(
        client.ux_port, client.ux_rtok, patchline=CFG.patchline
    )
    logger.info(f"[{client.name}] reprobe LCU: port={lcu_port}")
    lcu = make_lcu_session(lcu_port, lcu_token)
    wait_ready_full(lcu)
    return lcu


def _ensure_lcu_ok(lcu: requests.Session) -> requests.Session:
    try:
        resp = lcu.get(f"{lcu.base_url}/lol-login/v1/session", timeout=5)
        if resp.status_code == 200:
            return lcu
    except requests.RequestException:
        pass
    raise requests.ConnectionError("LCU session нездорова")


def _dedupe_friends(
    friends: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    duplicates = 0
    for friend in friends:
        key = _friend_key(friend)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        unique.append(friend)
    return unique, duplicates


def _verify_last_message(
    lcu: requests.Session, conv_id: str, expected: str
) -> bool:
    recent = lcu_list_recent_messages(lcu, conv_id, limit=1)
    if recent and (recent[-1] or {}).get("body") == expected:
        return True
    time.sleep(VERIFY_LOOKUP_DELAY_S)
    recent = lcu_list_recent_messages(lcu, conv_id, limit=1)
    return bool(recent and (recent[-1] or {}).get("body") == expected)


def _send_one(
    lcu: requests.Session, client: ClientHandle, user: str, friend: dict[str, Any]
) -> tuple[requests.Session, bool, str | None, bool]:
    try:
        conv_id = lcu_get_or_create_conversation_id(lcu, friend)
        if not conv_id:
            logger.error(f"[{user}] нет conversation id для {_friend_name(friend)}")
            return lcu, False, None, False

        recent = lcu_list_recent_messages(lcu, conv_id, limit=10)
        if any((message or {}).get("body") == CFG.message_text for message in recent):
            logger.info(f"[{user}] SKIP duplicate for {_friend_name(friend)}")
            return lcu, False, conv_id, True

        sent = lcu_send_message(lcu, conv_id, CFG.message_text)
        return lcu, sent, conv_id, False
    except requests.RequestException:
        lcu = _reprobe_lcu(client)
        try:
            conv_id = lcu_get_or_create_conversation_id(lcu, friend)
            sent = bool(conv_id) and lcu_send_message(lcu, conv_id, CFG.message_text)
            return lcu, sent, conv_id, False
        except requests.RequestException:
            return lcu, False, None, False


def _spam_friends(
    lcu: requests.Session,
    client: ClientHandle,
    user: str,
    friends: list[dict[str, Any]],
) -> dict[str, int]:
    unique, duplicates_in_list = _dedupe_friends(friends)

    try:
        lcu = _ensure_lcu_ok(lcu)
    except requests.RequestException:
        lcu = _reprobe_lcu(client)

    sent_ok = sent_fail = skipped_dupe = verify_mismatch = 0

    for friend in unique:
        lcu, sent, conv_id, was_dupe = _send_one(lcu, client, user, friend)
        time.sleep(CFG.message_delay_s)

        if was_dupe:
            skipped_dupe += 1
            continue

        if sent and conv_id and not _verify_last_message(lcu, conv_id, CFG.message_text):
            verify_mismatch += 1
            sent = False

        if sent:
            sent_ok += 1
        else:
            sent_fail += 1

        logger.info(
            f"[{user}] -> [{_friend_name(friend)}] {'OK' if sent else 'FAIL'}"
        )

    return {
        "total_friends": len(friends),
        "sent_ok": sent_ok,
        "sent_fail": sent_fail,
        "duplicates_in_list": duplicates_in_list,
        "skipped_dupe": skipped_dupe,
        "verify_mismatch": verify_mismatch,
    }


def process_account_on_client(
    client: ClientHandle, account: tuple[str, str]
) -> dict[str, Any]:
    user, password = account

    login_token = network_login(user, password, proxy=client.proxy)

    attach_login_token_to_ux(client.ux_port, client.ux_rtok, login_token)
    create_authorizations(client.ux_port, client.ux_rtok)
    logger.info(f"[{user}] UX авторизация завершена")

    handle_eula_if_needed(client.ux_port, client.ux_rtok)
    lcu_port, lcu_token = launch_lol_for_session(
        client.ux_port, client.ux_rtok, patchline=CFG.patchline
    )
    logger.info(f"[{user}] LCU готов: port={lcu_port}")

    metrics = dict(EMPTY_METRICS)

    if CFG.send_messages:
        lcu = make_lcu_session(lcu_port, lcu_token)
        try:
            wait_ready_full(lcu)
        except (requests.RequestException, RuntimeError, TimeoutError):
            lcu = _reprobe_lcu(client)

        friends = lcu_list_friends(lcu) or []
        metrics = _spam_friends(lcu, client, user, friends)

    close_lcu_by_port_token(lcu_port, lcu_token)

    if not ux_logout(client.ux_port, client.ux_rtok):
        time.sleep(LOGOUT_RETRY_DELAY_S)
        if not ux_logout(client.ux_port, client.ux_rtok):
            raise RuntimeError("UX logout failed twice; forcing client restart")

    return {
        "user": user,
        "status": "OK",
        "ux": {"pid": client.pid, "port": client.ux_port, "rtok": client.ux_rtok},
        "lcu": {"port": lcu_port, "token": lcu_token},
        "proxy": client.proxy,
        "metrics": metrics,
    }


def _is_logout_block(msg: str) -> bool:
    return "logout failed twice" in msg or "sign_out_failed_other_games_running" in msg


def worker_loop(client: ClientHandle, tasks: Queue, results: Queue) -> None:
    try:
        client.start()
    except Exception as exc:
        logger.error(f"[{client.name}] Старт клиента не удался: {exc}", exc_info=True)
        results.put(
            {
                "client": client.name,
                "status": "FAIL_START",
                "error": str(exc),
                "proxy": client.proxy,
            }
        )
        return

    while True:
        try:
            account = tasks.get(timeout=TASK_POLL_S)
        except Empty:
            break
        if account is None:
            break

        try:
            client.ensure_ready()
            results.put(process_account_on_client(client, account))
        except Exception as exc:
            message = str(exc)
            if _is_logout_block(message):
                logger.warning(
                    f"[{client.name}] Logout заблокирован активной игрой -> рестарт"
                )
                try:
                    client.restart()
                    results.put(
                        {
                            "user": account[0],
                            "status": "OK_LOGOUT_RESTART",
                            "proxy": client.proxy,
                        }
                    )
                    continue
                except Exception as restart_exc:
                    logger.error(
                        f"[{client.name}] Рестарт клиента не удался: {restart_exc}",
                        exc_info=True,
                    )

            logger.error(
                f"[{client.name}] FAIL [{account[0]}]: {exc}", exc_info=True
            )
            results.put(
                {
                    "user": account[0],
                    "status": "FAIL",
                    "error": message,
                    "proxy": client.proxy,
                }
            )
            try:
                client.restart()
            except Exception as restart_exc:
                logger.error(
                    f"[{client.name}] Рестарт клиента не удался: {restart_exc}",
                    exc_info=True,
                )
