"""FastAPI dependencies."""

from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.db.session import get_session


def get_db_session() -> Iterator[Session]:
    """Yield the request-scoped database session."""

    yield from get_session()
