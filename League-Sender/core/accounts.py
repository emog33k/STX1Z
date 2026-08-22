from pathlib import Path

_SEPARATORS = (":", ";", ",", " ")


def _parse_pair(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    for sep in _SEPARATORS:
        if sep in line:
            login, password = line.split(sep, 1)
            login, password = login.strip(), password.strip()
            if login and password:
                return login, password
    return None


def load_accounts(path: str) -> list[tuple[str, str]]:
    file_path = Path(path)
    if not file_path.is_file():
        return []
    accounts: list[tuple[str, str]] = []
    for line in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        pair = _parse_pair(line)
        if pair:
            accounts.append(pair)
    return accounts
