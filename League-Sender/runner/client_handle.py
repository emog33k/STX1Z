import logging
import time

from core.config import CFG
from services.riot_client import find_ux_for_pid, kill_client_family, spawn_riot_client

logger = logging.getLogger(__name__)

UX_TIMEOUT_S = 90


class ClientHandle:
    def __init__(self, name: str, proxy: str | None) -> None:
        self.name = name
        self.proxy = proxy
        self.pid: int | None = None
        self.ctime: float | None = None
        self.ux_port: int | None = None
        self.ux_rtok: str | None = None

    def start(self) -> None:
        self.pid, self.ctime = spawn_riot_client()
        time.sleep(CFG.spawn_stagger_s)
        self.ux_port, self.ux_rtok = find_ux_for_pid(
            self.pid, since_time=self.ctime, timeout_s=UX_TIMEOUT_S
        )

    def restart(self) -> None:
        logger.warning(f"[{self.name}] Перезапуск клиента")
        if self.ctime:
            try:
                killed = kill_client_family(since_time=self.ctime)
                logger.info(f"[{self.name}] Закрыто процессов семьи: {killed}")
            except (OSError, RuntimeError) as exc:
                logger.debug(f"[{self.name}] kill_client_family err: {exc}")
        self.start()

    def ensure_ready(self) -> None:
        if not (self.ux_port and self.ux_rtok):
            self.restart()
