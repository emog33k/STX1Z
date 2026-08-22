import logging
import os
import re
import subprocess
import time
from pathlib import Path

import psutil

from core.config import CFG

logger = logging.getLogger(__name__)

ELECTRON_LOG_DIR = Path(
    os.path.expandvars(r"%LOCALAPPDATA%\Riot Games\Riot Client\Logs\Riot Client Electron Logs")
)
TAIL_MAX_FILES = 12
TAIL_MAX_BYTES = 12000
UX_POLL_S = 0.5
KILL_GRACE_S = 0.8
POST_KILL_PAUSE_S = 0.4
CLOSE_ALL_PAUSE_S = 1.0
SPAWN_SETTLE_S = 0.3

_PORT_RE = re.compile(r"--app-port=(\d+)")
_PASS_RE = re.compile(r"--remoting-auth-token=([\w\-]+)")

_RE_DB_BIND = re.compile(r"DataBinding\)\s*port:\s*(\d+),\s*token:\s*([A-Za-z0-9_\-]+)")
_RE_ARGS_LINE = re.compile(r"Starting RiotClientUx electron with args\s*{\s*([^}]+)}", re.S)
_RE_GET_ARGS = re.compile(r"\(ipcRenderer\)\s*get-args\s*{\s*([^}]+)}", re.S)
_RE_KV = re.compile(r"(\w+):\s*'([^']*)'|(\w+):\s*([\w\-\./:]+)")

_CLIENT_FAMILY = frozenset({
    "RiotClientServices.exe",
    "RiotClientCrashHandler.exe",
    "RiotClientUx.exe",
    "RiotClientUxRender.exe",
    "LeagueClient.exe",
    "LeagueClientUx.exe",
    "LeagueClientUxRender.exe",
    "LeagueClientCrashHandler.exe",
    "LeagueClientCrashHandler64.exe",
})


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


def _terminate(proc: psutil.Process, grace: float) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=grace)
    except (psutil.TimeoutExpired, psutil.Error):
        try:
            proc.kill()
            proc.wait(timeout=grace)
        except psutil.Error:
            pass


def kill_client_family(since_time: float, grace: float = KILL_GRACE_S) -> int:
    killed = 0
    for proc in psutil.process_iter(["pid", "name", "create_time"]):
        try:
            name = proc.info["name"]
            if name not in _CLIENT_FAMILY:
                continue
            ctime = float(proc.info.get("create_time") or 0.0)
            if ctime < (since_time - 0.75):
                continue
            _terminate(psutil.Process(proc.info["pid"]), grace)
            logger.info(f"Закрыт процесс {name} (PID={proc.info['pid']})")
            killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    time.sleep(POST_KILL_PAUSE_S)
    return killed


def find_lcu_pid_by_port_token(port: int, token: str) -> int | None:
    for proc in psutil.process_iter(["name", "pid", "cmdline"]):
        try:
            if proc.info["name"] != "LeagueClientUx.exe":
                continue
            parsed = _parse_lcu_from_proc(proc)
            if parsed == (port, token):
                return proc.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def close_lcu_by_port_token(port: int, token: str, gentle_timeout: float = 8.0) -> bool:
    pid = find_lcu_pid_by_port_token(port, token)
    if not pid:
        logger.info("LCU PID не найден по port/token (возможно уже закрыт)")
        return True

    try:
        proc = psutil.Process(pid)
        proc.terminate()
        try:
            proc.wait(timeout=gentle_timeout)
            logger.info(f"LCU PID={pid} завершён (terminate)")
            return True
        except psutil.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2.0)
            logger.info(f"LCU PID={pid} завершён (kill)")
            return True
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        logger.info(f"LCU PID={pid} уже отсутствует: {exc}")
        return True


def close_all_riot_clients() -> int:
    killed = 0
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["name"] in _CLIENT_FAMILY:
                psutil.Process(proc.info["pid"]).kill()
                logger.info(f"Закрыт процесс {proc.info['name']} (PID={proc.info['pid']})")
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    time.sleep(CLOSE_ALL_PAUSE_S)
    return killed


def spawn_riot_client() -> tuple[int, float]:
    exe = CFG.riot_services_exe
    if not Path(exe).is_file():
        raise FileNotFoundError(f"Не найден {exe}")
    proc = subprocess.Popen(
        [exe, "--allow-multiple-clients"],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
    time.sleep(SPAWN_SETTLE_S)
    try:
        ctime = psutil.Process(proc.pid).create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        ctime = time.time()
    logger.info(f"Старт клиента: {exe} --allow-multiple-clients")
    logger.info(f"Запущен Riot Client, PID={proc.pid} (ожидаем UX)")
    return proc.pid, ctime


def _parse_kv_block(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for match in _RE_KV.finditer(text):
        if match.group(1) is not None:
            result[match.group(1)] = match.group(2)
        else:
            result[match.group(3)] = match.group(4)
    return result


def _file_tail(path: Path, max_bytes: int = TAIL_MAX_BYTES) -> str:
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            return f.read().decode("utf-8", errors="ignore")
    except OSError:
        return ""


def _electron_log_files() -> list[Path]:
    try:
        files = [p for p in ELECTRON_LOG_DIR.iterdir() if p.suffix == ".log"]
    except FileNotFoundError:
        return []
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:TAIL_MAX_FILES]


def _port_token_from_kv(kv: dict[str, str]) -> tuple[int, str] | None:
    token = kv.get("remotingAuthToken") or kv.get("remotingauthtoken")
    if "appPort" not in kv or not token:
        return None
    return int(kv["appPort"]), token


def _scan_ux_in_text(text: str) -> tuple[int, str] | None:
    db_match = _RE_DB_BIND.search(text)
    if db_match:
        return int(db_match.group(1)), db_match.group(2)
    for pattern in (_RE_ARGS_LINE, _RE_GET_ARGS):
        block = pattern.search(text)
        if not block:
            continue
        parsed = _port_token_from_kv(_parse_kv_block(block.group(1)))
        if parsed:
            return parsed
    return None


def find_ux_for_pid(pid: int, since_time: float, timeout_s: int = 90) -> tuple[int, str]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for path in _electron_log_files():
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime + 0.001 < since_time:
                continue
            text = _file_tail(path)

            if (
                f"appPid: {pid}" not in text
                and f"check if process {pid} is running" not in text
            ):
                continue

            parsed = _scan_ux_in_text(text)
            if parsed:
                port, token = parsed
                logger.info(f"UX найден: port={port} token={token} file={path.name}")
                return port, token
        time.sleep(UX_POLL_S)
    raise TimeoutError(f"Не найден UX для PID={pid} за {timeout_s}с")
