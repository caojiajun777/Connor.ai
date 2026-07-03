"""Database column types."""

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB


def json_payload_type() -> JSON:
    """Use JSONB on PostgreSQL while keeping SQLite-compatible tests."""

    return JSON().with_variant(JSONB(), "postgresql")
