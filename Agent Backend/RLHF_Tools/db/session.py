"""Engine/session factory.

One connection strategy, unlike ennvault-existing's two parallel ones
(app/setttings/config.py's hardcoded pymysql vs. app/api/*/db.py's env-driven
mysql.connector -- audit section 11/7). Everything here goes through
SQLAlchemy against `settings.database_url`, which defaults to real MySQL but
can be pointed at sqlite for offline dev/tests via DB_URL_OVERRIDE.
"""
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import get_settings
from db.legacy_schema import LegacyBase
from db.new_schema import NewBase

_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
        _engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


@contextmanager
def session_scope() -> Session:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_new_tables() -> None:
    """Creates only the net-new agentic tables (db/new_schema.py).

    Never call create_all() against LegacyBase -- those tables are owned by
    ennvault-existing and already exist in production; this is here purely so
    tests can spin up a throwaway sqlite fixture with both schemas (see
    tests/conftest.py).
    """
    NewBase.metadata.create_all(get_engine())


def create_legacy_tables_for_tests() -> None:
    """Test-only: materializes the legacy schema in a scratch sqlite DB so unit
    tests can exercise the Invoice-DB MCP server without a real MySQL instance.
    """
    LegacyBase.metadata.create_all(get_engine())
