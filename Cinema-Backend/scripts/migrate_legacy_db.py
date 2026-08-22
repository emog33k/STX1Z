import argparse
import contextlib
import logging
import os
import re
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.text import make_slug
from app.enums import MAX_YEAR, MIN_YEAR

logger = logging.getLogger("migrate")

_GENRE_SPLIT_RE = re.compile(r"[,/;|]")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Перенос данных из старой схемы каталога в новую"
    )
    parser.add_argument("--source", required=True, type=Path, help="старый database.db")
    parser.add_argument("--target", required=True, type=Path, help="новый файл БД")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="разобрать данные и показать отчёт, ничего не записывая",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def read_legacy(source: Path) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    if not source.exists():
        raise SystemExit(f"Файл {source} не найден")

    conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "titles" not in tables:
            raise SystemExit(f"В {source} нет таблицы titles — это не та база")

        title_columns = {row["name"] for row in conn.execute("PRAGMA table_info(titles)")}
        titles = [dict(row) for row in conn.execute("SELECT * FROM titles")]

        episodes: dict[int, list[dict[str, Any]]] = defaultdict(list)
        if "episodes" in tables:
            episode_columns = {row["name"] for row in conn.execute("PRAGMA table_info(episodes)")}
            season_column = (
                "season_id"
                if "season_id" in episode_columns
                else ("season_number" if "season_number" in episode_columns else None)
            )
            for row in conn.execute("SELECT * FROM episodes ORDER BY id"):
                item = dict(row)
                item["_season"] = item.get(season_column) if season_column else None
                episodes[item["title_id"]].append(item)

        episode_count = sum(len(v) for v in episodes.values())
        logger.info(
            f"Прочитано: {len(titles)} тайтлов, {episode_count} эпизодов "
            f"(колонки тайтла: {', '.join(sorted(title_columns))})"
        )
        return titles, episodes
    finally:
        conn.close()


def split_genres(raw: Any) -> list[str]:
    if not raw or not isinstance(raw, str):
        return []
    return [part.strip() for part in _GENRE_SPLIT_RE.split(raw) if part.strip()]


def normalize_year(raw: Any) -> int | None:
    try:
        year = int(raw)
    except (TypeError, ValueError):
        return None
    if MIN_YEAR <= year <= MAX_YEAR:
        return year
    logger.warning(f"Год {raw!r} вне диапазона — записан как NULL")
    return None


def normalize_episodes(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    used: set[tuple[int, int]] = set()
    next_free: dict[int, int] = defaultdict(lambda: 1)

    for row in rows:
        season = row.get("_season")
        season_number = int(season) if isinstance(season, int) and season >= 1 else 1

        raw_number = row.get("episode_number")
        number = int(raw_number) if isinstance(raw_number, int) and raw_number >= 1 else None

        if number is None or (season_number, number) in used:
            candidate = next_free[season_number]
            while (season_number, candidate) in used:
                candidate += 1
            if number is not None:
                logger.warning(
                    f"Эпизод id={row.get('id')}: номер "
                    f"s{season_number}e{number} занят, назначен e{candidate}"
                )
            number = candidate

        used.add((season_number, number))
        next_free[season_number] = max(next_free[season_number], number + 1)

        name = (row.get("name") or "").strip() or f"Серия {number}"
        result.append(
            {"season_number": season_number, "episode_number": number, "name": name}
        )

    result.sort(key=lambda item: (item["season_number"], item["episode_number"]))
    return result


def setup_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, OSError):
            stream.reconfigure(encoding="utf-8", errors="replace")


def prepare_titles(
    titles: list[dict[str, Any]], episodes_by_title: dict[int, list[dict[str, Any]]]
) -> tuple[list[dict[str, Any]], list[str]]:
    prepared: list[dict[str, Any]] = []
    notes: list[str] = []

    for row in titles:
        name = (row.get("name") or "").strip()
        if not name:
            notes.append(f"id={row.get('id')}: пустое название")
            continue

        title_type = (row.get("type") or "").strip().lower()
        if title_type not in ("movie", "series"):
            title_type = "series" if episodes_by_title.get(row.get("id")) else "movie"
            notes.append(f"id={row.get('id')}: тип {row.get('type')!r} -> {title_type}")

        prepared.append({
            "type": title_type,
            "name": name,
            "description": (row.get("description") or "").strip() or None,
            "poster_url": (row.get("poster_url") or "").strip() or None,
            "backdrop_url": (row.get("backdrop_url") or "").strip() or None,
            "year": normalize_year(row.get("year")),
            "embed_url": (row.get("embed_url") or "").strip() or None,
            "genres": split_genres(row.get("genres")),
            "episodes": normalize_episodes(episodes_by_title.get(row.get("id"), [])),
        })

    return prepared, notes


def collect_genres(prepared: list[dict[str, Any]]) -> dict[str, str]:
    by_slug: dict[str, str] = {}
    for item in prepared:
        for genre in item["genres"]:
            by_slug.setdefault(make_slug(genre), genre)
    return by_slug


def report(prepared: list[dict[str, Any]], genres: dict[str, str], notes: list[str]) -> None:
    names = sorted(genres.values())
    episodes = sum(len(item["episodes"]) for item in prepared)
    no_embed = [item["name"] for item in prepared if not item["embed_url"]]

    logger.info(f"К переносу: {len(prepared)} тайтлов, {episodes} эпизодов")
    logger.info(f"Жанров найдено: {len(names)} ({', '.join(names) or '-'})")
    for note in notes:
        logger.warning(f"Замечание: {note}")
    if no_embed:
        logger.warning(
            f"Без embed_url останутся {len(no_embed)} тайтлов: "
            f"{', '.join(no_embed[:5])}. API не даст их сохранить "
            f"через PUT/PATCH, пока ссылка не проставлена."
        )


def write_titles(prepared: list[dict[str, Any]], genres: dict[str, str], target: Path) -> None:
    os.environ["DATABASE_URL"] = f"sqlite:///{target.as_posix()}"
    os.environ.setdefault("AUTH_REQUIRED", "false")
    os.environ.setdefault("DEBUG", "true")

    from app.db.base import SessionLocal, engine
    from app.db.models import Episode, Genre, Title
    from app.db.schema_state import upgrade_to_head

    upgrade_to_head(os.environ["DATABASE_URL"])

    session = SessionLocal()
    try:
        genre_objects = {
            slug: Genre(slug=slug, name=name) for slug, name in genres.items()
        }
        session.add_all(genre_objects.values())
        session.flush()

        for item in prepared:
            title = Title(
                type=item["type"],
                name=item["name"],
                description=item["description"],
                poster_url=item["poster_url"],
                backdrop_url=item["backdrop_url"],
                year=item["year"],
                embed_url=item["embed_url"],
            )
            title.genres = [genre_objects[make_slug(g)] for g in item["genres"]]
            for episode in item["episodes"]:
                title.episodes.append(Episode(**episode))
            session.add(title)

        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Перенос прерван, целевая база оставлена в исходном виде")
        raise
    finally:
        session.close()
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_console()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(message)s",
    )

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    titles, episodes_by_title = read_legacy(args.source)
    prepared, notes = prepare_titles(titles, episodes_by_title)
    genres = collect_genres(prepared)
    report(prepared, genres, notes)

    if args.dry_run:
        logger.info("Режим --dry-run: запись не выполнялась")
        return 0

    if args.target.exists():
        raise SystemExit(f"Файл {args.target} уже существует — укажите новый путь")

    write_titles(prepared, genres, args.target)

    logger.info(f"Готово: {args.source} -> {args.target}")
    logger.info("Проверьте результат, затем замените рабочий файл базы.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
