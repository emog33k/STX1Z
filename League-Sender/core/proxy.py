import logging
import os
import random
from itertools import cycle
from pathlib import Path

import requests

from core.config import CFG

logger = logging.getLogger(__name__)

VERIFY_SSL = False
OK_STATUSES = (200, 204, 301, 302)


def _normalize(entry: str) -> str:
    entry = entry.strip()
    if not entry or entry.startswith("#"):
        return ""
    if "://" in entry:
        return entry
    return "http://" + entry


def _as_requests_proxies(proxy: str) -> dict[str, str]:
    return {"http": proxy, "https": proxy}


def load_proxies(path: str) -> list[str]:
    file_path = Path(path)
    if not file_path.is_file():
        return []
    proxies: list[str] = []
    for line in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        entry = _normalize(line)
        if entry:
            proxies.append(entry)
    return proxies


def validate_proxy(proxy: str, timeout: float = 5.0) -> bool:
    try:
        resp = requests.get(
            CFG.google_probe_url,
            proxies=_as_requests_proxies(proxy),
            timeout=timeout,
            allow_redirects=False,
            verify=VERIFY_SSL,
        )
        return resp.status_code in OK_STATUSES
    except requests.RequestException:
        return False


def filter_valid_proxies(proxies: list[str], timeout: float = 5.0) -> list[str]:
    return [proxy for proxy in proxies if validate_proxy(proxy, timeout=timeout)]


class ProxyPool:
    def __init__(self, proxies: list[str], mode: str | None = None) -> None:
        self._proxies = list(dict.fromkeys(proxies))
        self._mode = (mode or os.getenv("PROXY_MODE", "roundrobin")).lower()
        self._cycle = cycle(self._proxies) if self._mode == "roundrobin" else None

    def get(self) -> str | None:
        if not self._proxies:
            return None
        if self._mode == "roundrobin" and self._cycle is not None:
            return next(self._cycle)
        return random.choice(self._proxies)
