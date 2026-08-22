import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import CFG

logger = logging.getLogger(__name__)

ERRORS_HEADERS = ["ts", "user", "status", "error", "details", "proxy"]
AUDIT_HEADERS = [
    "ts",
    "user",
    "total_friends",
    "sent_ok",
    "sent_fail",
    "duplicates_in_list",
    "skipped_dupe",
    "verify_mismatch",
    "proxy",
]


def _ensure_csv(path: str, headers: list[str]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if not file_path.exists() or file_path.stat().st_size == 0:
        with file_path.open("w", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerow(headers)


def _append_csv(path: str, row: dict[str, Any]) -> None:
    file_path = Path(path)
    if not file_path.exists() or file_path.stat().st_size == 0:
        _ensure_csv(path, list(row.keys()))
    with file_path.open("a", newline="", encoding="utf-8") as stream:
        csv.DictWriter(stream, fieldnames=list(row.keys())).writerow(row)


def init_audit_files() -> None:
    _ensure_csv(CFG.errors_file, ERRORS_HEADERS)
    _ensure_csv(CFG.audit_file, AUDIT_HEADERS)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_result(item: dict[str, Any]) -> None:
    ts = _now_iso()
    status = item.get("status", "")
    user = item.get("user", "")
    proxy = item.get("proxy")
    metrics = item.get("metrics") or {}

    if metrics.get("verify_mismatch", 0) > 0:
        _append_csv(
            CFG.errors_file,
            {
                "ts": ts,
                "user": user,
                "status": "POST_VERIFY_MISMATCH",
                "error": "После отправки текст не появился в истории",
                "details": f"verify_mismatch={metrics.get('verify_mismatch', 0)}",
                "proxy": proxy,
            },
        )

    if metrics:
        _append_csv(
            CFG.audit_file,
            {
                "ts": ts,
                "user": user,
                "total_friends": metrics.get("total_friends", 0),
                "sent_ok": metrics.get("sent_ok", 0),
                "sent_fail": metrics.get("sent_fail", 0),
                "duplicates_in_list": metrics.get("duplicates_in_list", 0),
                "skipped_dupe": metrics.get("skipped_dupe", 0),
                "verify_mismatch": metrics.get("verify_mismatch", 0),
                "proxy": proxy,
            },
        )

        if (
            CFG.send_messages
            and metrics.get("total_friends", 0) > 0
            and metrics.get("sent_ok", 0) == 0
        ):
            _append_csv(
                CFG.errors_file,
                {
                    "ts": ts,
                    "user": user,
                    "status": "NO_DELIVERIES",
                    "error": "Все отправки вернули FAIL или ложно-OK",
                    "details": (
                        f"friends={metrics.get('total_friends')} ok=0 "
                        f"fail={metrics.get('sent_fail', 0)}"
                    ),
                    "proxy": proxy,
                },
            )

    if status in {"FAIL", "FAIL_START"}:
        _append_csv(
            CFG.errors_file,
            {
                "ts": ts,
                "user": user,
                "status": status,
                "error": item.get("error", ""),
                "details": "",
                "proxy": proxy,
            },
        )
