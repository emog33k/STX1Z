import logging
from logging.handlers import RotatingFileHandler

import urllib3

from core.config import CFG

LOG_FORMAT = (
    "%(asctime)s | %(levelname)-7s | %(processName)s | %(name)s | "
    "%(funcName)s:%(lineno)d – %(message)s"
)
LOG_MAX_BYTES = 3_000_000
LOG_BACKUPS = 3


def setup_logging() -> logging.Logger:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    file_handler = RotatingFileHandler(
        CFG.log_file, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt="%H:%M:%S"))
    file_handler.setLevel(getattr(logging, CFG.log_level_file, logging.DEBUG))
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt="%H:%M:%S"))
    console_handler.setLevel(getattr(logging, CFG.log_level_console, logging.INFO))
    root.addHandler(console_handler)

    return logging.getLogger("RiotAuth")
