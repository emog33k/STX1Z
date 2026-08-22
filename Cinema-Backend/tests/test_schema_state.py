import pytest
from sqlalchemy import create_engine

from app.db.base import engine
from app.db.schema_state import (
    SchemaOutOfDateError,
    current_revision,
    ensure_schema_is_current,
    head_revision,
    upgrade_to_head,
)


def test_head_revision_exists():
    assert head_revision()


def test_test_database_is_on_head(migrated_db):
    assert current_revision(engine) == head_revision()


def test_ensure_passes_on_current_schema(migrated_db):
    ensure_schema_is_current(engine)


def test_unmigrated_database_is_rejected(tmp_path):
    fresh = create_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    try:
        with pytest.raises(SchemaOutOfDateError, match="alembic upgrade head"):
            ensure_schema_is_current(fresh)
    finally:
        fresh.dispose()


def test_upgrade_creates_full_schema(tmp_path):
    from sqlalchemy import inspect

    url = f"sqlite:///{(tmp_path / 'new.db').as_posix()}"
    upgrade_to_head(url)
    fresh = create_engine(url)
    try:
        tables = set(inspect(fresh).get_table_names())
        assert {"titles", "episodes", "genres", "title_genres", "alembic_version"} <= tables
    finally:
        fresh.dispose()


def test_upgrade_applies_unique_constraint(tmp_path):
    from sqlalchemy import inspect

    url = f"sqlite:///{(tmp_path / 'constraints.db').as_posix()}"
    upgrade_to_head(url)
    fresh = create_engine(url)
    try:
        constraints = inspect(fresh).get_unique_constraints("titles")
        names = {c["name"] for c in constraints}
        assert "uq_titles_name_year_type" in names
    finally:
        fresh.dispose()
