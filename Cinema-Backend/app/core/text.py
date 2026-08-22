import re
import unicodedata

_SLUG_SEPARATORS_RE = re.compile(r"[\s_]+")
_SPACES_RE = re.compile(r"\s+")
_INVALID_CHARS_RE = re.compile(r"[^\w\-]+")
_MULTIPLE_DASH_RE = re.compile(r"-{2,}")

MAX_SLUG_LENGTH = 64
MAX_NAME_LENGTH = 255


def make_slug(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name).strip().casefold()
    normalized = _SLUG_SEPARATORS_RE.sub("-", normalized)
    normalized = _INVALID_CHARS_RE.sub("", normalized)
    normalized = _MULTIPLE_DASH_RE.sub("-", normalized).strip("-")
    if not normalized:
        raise ValueError(f"Не собрать slug из {name!r}")
    return normalized[:MAX_SLUG_LENGTH]


def normalize_name(name: str) -> str:
    normalized = _SPACES_RE.sub(" ", unicodedata.normalize("NFKC", name).strip().casefold())
    return normalized[:MAX_NAME_LENGTH]


def has_slug(name: str) -> bool:
    try:
        make_slug(name)
    except ValueError:
        return False
    return True
