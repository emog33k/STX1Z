import sys
import threading
import time
from queue import Empty, Queue

from core.accounts import load_accounts
from core.config import CFG
from core.logging_setup import setup_logging
from core.proxy import ProxyPool, filter_valid_proxies, load_proxies
from runner.audit import init_audit_files, write_result
from runner.client_handle import ClientHandle
from runner.worker import worker_loop
from services.riot_client import close_all_riot_clients

logger = setup_logging()

PROXY_VALIDATE_TIMEOUT_S = 5.0
CLOSE_PAUSE_S = 2.0
RESULT_POLL_S = 0.3
DRAIN_PAUSE_S = 0.2


def _start_workers(
    worker_count: int,
    proxypool: ProxyPool | None,
    tasks: Queue,
    results: Queue,
) -> list[threading.Thread]:
    threads: list[threading.Thread] = []
    for index in range(worker_count):
        proxy = proxypool.get() if proxypool else None
        client = ClientHandle(
            name=f"CLIENT[{index + 1}/{worker_count}]", proxy=proxy
        )
        thread = threading.Thread(
            target=worker_loop,
            args=(client, tasks, results),
            name=client.name,
            daemon=True,
        )
        thread.start()
        threads.append(thread)
    return threads


def main() -> None:
    init_audit_files()

    if CFG.close_clients_at_start:
        killed = close_all_riot_clients()
        logger.info(f"Закрыто клиентов: {killed}")
        time.sleep(CLOSE_PAUSE_S)

    accounts = load_accounts(CFG.accounts_file)
    if not accounts:
        logger.error(f"Файл аккаунтов пуст или не найден: {CFG.accounts_file}")
        sys.exit(1)

    raw_proxies = load_proxies(CFG.proxies_file)
    valid_proxies = filter_valid_proxies(raw_proxies, timeout=PROXY_VALIDATE_TIMEOUT_S)
    logger.info(f"Прокси: всего={len(raw_proxies)} валид={len(valid_proxies)}")
    if CFG.proxy_required and not valid_proxies:
        logger.error("proxy_required=True, но валидных прокси нет")
        sys.exit(2)
    proxypool = ProxyPool(valid_proxies) if valid_proxies else None

    worker_count = max(1, CFG.concurrency)
    tasks: Queue = Queue()
    for account in accounts:
        tasks.put(account)
    for _ in range(worker_count):
        tasks.put(None)

    results: Queue = Queue()
    threads = _start_workers(worker_count, proxypool, tasks, results)

    alive = True
    while alive:
        alive = any(thread.is_alive() for thread in threads)
        try:
            item = results.get(timeout=RESULT_POLL_S)
        except Empty:
            continue
        logger.info(f"Результат: {item}")
        write_result(item)

    time.sleep(DRAIN_PAUSE_S)
    while True:
        try:
            item = results.get_nowait()
        except Empty:
            break
        logger.info(f"Результат: {item}")
        write_result(item)

    logger.info("Готово")


if __name__ == "__main__":
    main()
