"""Database engine and session helpers.

Supports PostgreSQL (production) and SQLite (tests / dev fallback).
Connection pooling is configured per backend.  The engine is created lazily
so that test suites importing this module do not need a running database.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


SessionLocal = sessionmaker(autoflush=False, autocommit=False, future=True)
"""Module-level session factory.  ``bind`` is set on first :func:`get_engine` call."""


def create_engine_from_url(url: str | None = None) -> Engine:
    """Create a SQLAlchemy engine from config or an explicit URL."""

    database_url = url or get_settings().database_url
    connect_args: dict = {}
    engine_kwargs: dict = {"future": True}

    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    elif "postgresql" in database_url:
        engine_kwargs.update(
            pool_size=10,
            max_overflow=20,
            pool_recycle=3600,
            pool_pre_ping=True,
        )

    engine_instance = create_engine(
        database_url,
        connect_args=connect_args,
        **engine_kwargs,
    )

    if database_url.startswith("sqlite"):
        @event.listens_for(engine_instance, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record):  # noqa: ARG001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine_instance


_engine: Engine | None = None


def get_engine() -> Engine:
    """Return the module-level SQLAlchemy engine, creating it on first call."""
    global _engine
    if _engine is None:
        _engine = create_engine_from_url()
        SessionLocal.configure(bind=_engine)
    return _engine


def get_session() -> Iterator[Session]:
    """Yield a database session for FastAPI-style dependencies."""

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
