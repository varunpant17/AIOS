from threading import RLock
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


_lock = RLock()
_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_database_url: str | None = None
logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def get_db():
    with _lock:
        factory = _session_factory
    if factory is None:
        raise RuntimeError("Database resources are not initialized; application lifespan is not active.")
    db = factory()
    try:
        yield db
    finally:
        db.close()


def initialize_database(database_url: str | None = None) -> Engine:
    """Create the shared SQLAlchemy engine and verify connectivity at startup."""
    global _engine, _session_factory, _database_url
    url = database_url or settings.DATABASE_URL
    with _lock:
        if _engine is not None and _database_url != url:
            raise RuntimeError("Database resources are already initialized with different configuration.")
        if _engine is None:
            _engine = create_engine(url, echo=False, pool_pre_ping=True)
            _session_factory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
            _database_url = url
        engine = _engine
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        dispose_database()
        raise
    return engine


def check_database() -> bool:
    """Perform a real lightweight query; return false if the DB is unavailable."""
    with _lock:
        engine = _engine
    if engine is None:
        return False
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("Database readiness probe failed (exception_type=%s).", type(exc).__name__)
        return False


def dispose_database() -> None:
    """Dispose and clear the engine owned by the application lifecycle."""
    global _engine, _session_factory, _database_url
    with _lock:
        engine = _engine
        _engine = None
        _session_factory = None
        _database_url = None
    if engine is not None:
        engine.dispose()
