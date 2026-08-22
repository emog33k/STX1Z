import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
RES_DIR = BASE_DIR / "resources"

load_dotenv(BASE_DIR / ".env")


def _env_bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    accounts_file: str = str(RES_DIR / "accounts.txt")
    proxies_file: str = str(RES_DIR / "proxy.txt")

    concurrency: int = int(os.getenv("CONCURRENCY", "2"))
    close_clients_at_start: bool = _env_bool("CLOSE_CLIENTS_AT_START", True)
    spawn_stagger_s: float = float(os.getenv("SPAWN_STAGGER_S", "3.0"))

    sdk_version: str = os.getenv("SDK_VERSION", "25.7.1.6086")
    client_id: str = os.getenv("CLIENT_ID", "riot-client")
    user_agent: str = field(default="", init=False)

    riot_services_exe: str = os.getenv(
        "RIOT_SERVICES_EXE",
        r"C:\Riot Games\Riot Client\RiotClientServices.exe",
    )

    send_messages: bool = _env_bool("SEND_MESSAGES", True)
    message_text: str = os.getenv("MESSAGE_TEXT", "meow")
    patchline: str = os.getenv("PATCHLINE", "live")

    google_probe_url: str = os.getenv(
        "GOOGLE_PROBE_URL", "https://www.google.com/generate_204"
    )
    proxy_required: bool = _env_bool("PROXY_REQUIRED", False)
    http_timeout: float = float(os.getenv("HTTP_TIMEOUT", "15"))

    errors_file: str = str(BASE_DIR / "errors.csv")
    audit_file: str = str(BASE_DIR / "messages_audit.csv")
    log_file: str = str(BASE_DIR / "riot_ux_lcu.log")
    log_level_console: str = os.getenv("LOG_LEVEL_CONSOLE", "INFO")
    log_level_file: str = os.getenv("LOG_LEVEL_FILE", "DEBUG")

    message_delay_s: float = float(os.getenv("MESSAGE_DELAY_S", "1.2"))

    def __post_init__(self) -> None:
        ua = (
            f"RiotGamesApi/{self.sdk_version} rso-authenticator "
            f"(Windows;10;;Professional, x64) riot-client/0"
        )
        object.__setattr__(self, "user_agent", ua)


CFG = Config()
