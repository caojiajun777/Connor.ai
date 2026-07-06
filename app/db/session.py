"""Database engine and session helpers."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def create_engine_from_url(url: str | None = None) -> Engine:
    """Create a SQLAlchemy engine from config or an explicit URL."""

    database_url = url or get_settings().database_url
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine_instance = create_engine(database_url, connect_args=connect_args, future=True)

    if database_url.startswith("sqlite"):
        from sqlalchemy import event

        @event.listens_for(engine_instance, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ARG001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine_instance


engine = create_engine_from_url()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_session() -> Iterator[Session]:
    """Yield a database session for FastAPI-style dependencies."""

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

