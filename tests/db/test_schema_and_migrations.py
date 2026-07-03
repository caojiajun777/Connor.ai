"""Database metadata and Alembic migration tests."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.config import get_settings
from app.db.base import Base
from app.db import models  # noqa: F401


EXPECTED_TABLES = {
    "runs",
    "evidence_items",
    "candidate_items",
    "event_clusters",
    "evaluation_results",
    "watchlist_items",
    "archived_signals",
    "intelligence_threads",
    "daily_reports",
    "trace_events",
    "artifacts",
    "tool_calls",
    "model_calls",
    "review_results",
    "review_issues",
}


def test_orm_metadata_contains_phase_2_tables() -> None:
    assert EXPECTED_TABLES.issubset(set(Base.metadata.tables))


def test_alembic_upgrade_creates_phase_2_tables(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "alembic_phase2.db"
    monkeypatch.setenv("CONNOR_DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    get_settings.cache_clear()

    config = Config(str(Path("alembic.ini")))
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    inspector = inspect(engine)
    assert EXPECTED_TABLES.issubset(set(inspector.get_table_names()))

    trace_columns = {column["name"] for column in inspector.get_columns("trace_events")}
    assert {"run_id", "seq", "phase", "event_type", "payload"}.issubset(trace_columns)

    get_settings.cache_clear()

