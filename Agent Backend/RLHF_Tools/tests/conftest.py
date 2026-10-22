"""Offline test fixtures: a scratch sqlite file standing in for the shared
MySQL database, materializing BOTH the legacy schema (db/legacy_schema.py --
mirroring ennvault-existing's tables) and the new agentic schema
(db/new_schema.py), per the "unit tests + mocked I/O, no live creds" decision.
"""
from __future__ import annotations

import pytest

import db.session as db_session
from config.settings import get_settings


@pytest.fixture(autouse=True)
def sqlite_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DB_URL_OVERRIDE", f"sqlite:///{db_path}")
    get_settings.cache_clear()

    db_session._engine = None
    db_session._SessionLocal = None

    db_session.create_legacy_tables_for_tests()
    db_session.create_new_tables()

    yield

    db_session._engine = None
    db_session._SessionLocal = None
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def chroma_dir(tmp_path, monkeypatch):
    persist_dir = tmp_path / "chroma"
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(persist_dir))
    get_settings.cache_clear()
    yield persist_dir
