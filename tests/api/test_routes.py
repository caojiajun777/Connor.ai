"""FastAPI dashboard contract tests."""

from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import create_app
from app.api.dependencies import get_db_session
from app.db.base import Base
from app.db import models  # noqa: F401
from app.domain import RunPhase, RunStatus
from app.repositories import (
    ArchivedSignalRepository,
    CandidateRepository,
    DailyReportRepository,
    EvaluationRepository,
    EventClusterRepository,
    EvidenceRepository,
    IntelligenceThreadRepository,
    RunRepository,
    TraceEventRepository,
    WatchlistRepository,
)
from tests.domain.fixtures import (
    RUN_ID,
    daily_report_fixture,
    early_signal_bundle,
    run_state_fixture,
    tech_finance_bundle,
)


def test_create_daily_run_endpoint() -> None:
    with _client_context() as (client, _session):
        response = client.post(
            "/runs/daily",
            json={
                "report_date": "2026-07-04",
                "objective": "Generate Connor.ai daily report.",
                "run_id": "run_2026_07_04",
                "enabled_sources": ["github", "hacker_news"],
            },
        )

        assert response.status_code == 201
        payload = response.json()
        assert payload["run"]["id"] == "run_2026_07_04"
        assert payload["run"]["status"] == "scheduled"
        assert payload["counts"]["trace_events"] == 1

        duplicate = client.post(
            "/runs/daily",
            json={
                "report_date": "2026-07-04",
                "objective": "Generate Connor.ai daily report.",
                "run_id": "run_2026_07_04",
            },
        )
        assert duplicate.status_code == 409


def test_dashboard_read_endpoints() -> None:
    with _client_context() as (client, session):
        _persist_dashboard_fixture(session)

        run_response = client.get(f"/runs/{RUN_ID}")
        assert run_response.status_code == 200
        run_payload = run_response.json()
        assert run_payload["latest_report_id"] == "report_2026_07_03"
        assert run_payload["counts"]["clusters"] == 2
        assert run_payload["counts"]["watchlist"] == 1

        trace_response = client.get(f"/runs/{RUN_ID}/trace")
        assert trace_response.status_code == 200
        trace_payload = trace_response.json()
        assert trace_payload["events"][0]["id"] == "trace_eval_openai_reasoning"

        clusters_response = client.get(f"/runs/{RUN_ID}/clusters")
        assert clusters_response.status_code == 200
        assert len(clusters_response.json()["clusters"]) == 2

        report_response = client.get("/reports/report_2026_07_03")
        assert report_response.status_code == 200
        report_payload = report_response.json()
        assert report_payload["full_markdown"].startswith("# Connor.ai Daily Intelligence")
        assert report_payload["full_json"]["sections"][0]["section_id"] == "early_signals"
        assert report_payload["evidence_map"][0]["report_item_id"] == "item_openai_reasoning_api"

        watchlist_response = client.get("/watchlist", params={"status": "active"})
        assert watchlist_response.status_code == 200
        assert watchlist_response.json()["watchlist"][0]["id"] == "watch_openai_reasoning_api"

        threads_response = client.get("/threads")
        assert threads_response.status_code == 200
        assert threads_response.json()["threads"][0]["id"] == "thread_openai_reasoning_api"

        thread_response = client.get("/threads/thread_openai_reasoning_api")
        assert thread_response.status_code == 200
        assert thread_response.json()["thread"]["title"] == "OpenAI reasoning-control API evolution"


def test_api_returns_404_for_missing_objects() -> None:
    with _client_context() as (client, _session):
        assert client.get("/runs/missing").status_code == 404
        assert client.get("/reports/missing").status_code == 404
        assert client.get("/threads/missing").status_code == 404


@contextmanager
def _client_context():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    app = create_app()

    def override_session():
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    with SessionLocal() as seed_session:
        with TestClient(app) as client:
            yield client, seed_session


def _persist_dashboard_fixture(db_session) -> None:
    run = run_state_fixture().model_copy(
        update={
            "phase": RunPhase.FINALIZED,
            "status": RunStatus.COMPLETED,
            "report_id": "report_2026_07_03",
        }
    )
    RunRepository(db_session).add(run)

    early = early_signal_bundle()
    finance = tech_finance_bundle()
    EvidenceRepository(db_session).add_many(early["evidence"])
    EvidenceRepository(db_session).add_many(finance["evidence"])
    CandidateRepository(db_session).add(early["candidate"])
    CandidateRepository(db_session).add(finance["candidate"])
    EventClusterRepository(db_session).add(early["cluster"])
    EventClusterRepository(db_session).add(finance["cluster"])
    EvaluationRepository(db_session).add(early["evaluation"])
    EvaluationRepository(db_session).add(finance["evaluation"])
    WatchlistRepository(db_session).add(early["watch"])
    ArchivedSignalRepository(db_session).add(early["archive"])
    IntelligenceThreadRepository(db_session).add(early["thread"])
    TraceEventRepository(db_session).add(early["trace"])
    DailyReportRepository(db_session).add(daily_report_fixture())
    db_session.commit()
