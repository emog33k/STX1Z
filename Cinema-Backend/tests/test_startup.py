import logging

import app.main as main_module
from app.db.models import Title
from app.repositories.uow import SqlAlchemyUnitOfWork


def test_warns_when_auth_disabled(monkeypatch, caplog):
    monkeypatch.setattr(main_module.settings, "auth_required", False)
    with caplog.at_level(logging.WARNING):
        main_module._log_startup_warnings()
    assert any("AUTH_REQUIRED=false" in record.message for record in caplog.records)


def test_warns_when_admin_list_is_empty(monkeypatch, caplog):
    monkeypatch.setattr(main_module.settings, "auth_required", True)
    monkeypatch.setattr(main_module.settings, "admin_ids", set())
    with caplog.at_level(logging.WARNING):
        main_module._log_startup_warnings()
    assert any("ADMIN_IDS" in record.message for record in caplog.records)


def test_warns_when_cors_is_empty(monkeypatch, caplog):
    monkeypatch.setattr(main_module.settings, "cors_origins", [])
    with caplog.at_level(logging.WARNING):
        main_module._log_startup_warnings()
    assert any("CORS_ORIGINS" in record.message for record in caplog.records)


def test_prepare_schema_checks_revision(migrated_db):
    main_module._prepare_schema()


def test_prepare_schema_can_upgrade_on_start(monkeypatch, caplog):
    calls = []
    monkeypatch.setattr(main_module.settings, "auto_upgrade_db", True)
    monkeypatch.setattr(main_module, "upgrade_to_head", lambda: calls.append("upgrade"))
    monkeypatch.setattr(main_module, "ensure_schema_is_current", lambda engine: calls.append("check"))
    with caplog.at_level(logging.WARNING):
        main_module._prepare_schema()
    assert calls == ["upgrade", "check"]
    assert any("AUTO_UPGRADE_DB" in record.message for record in caplog.records)


def test_unit_of_work_refresh_reloads_attribute(db_session):
    uow = SqlAlchemyUnitOfWork(db_session)
    title = Title(type="movie", name="A", embed_url="https://p.tv/1")
    db_session.add(title)
    uow.commit()

    title.name = "изменено в памяти"
    uow.refresh(title, ["name"])
    assert title.name == "A"


def test_unit_of_work_refresh_without_attribute_list(db_session):
    uow = SqlAlchemyUnitOfWork(db_session)
    title = Title(type="movie", name="B", embed_url="https://p.tv/2")
    db_session.add(title)
    uow.commit()
    uow.refresh(title)
    assert title.id is not None


def test_unit_of_work_flush_does_not_commit(db_session):
    uow = SqlAlchemyUnitOfWork(db_session)
    db_session.add(Title(type="movie", name="C", embed_url="https://p.tv/3"))
    uow.flush()
    uow.rollback()
    assert db_session.query(Title).filter(Title.name == "C").count() == 0
