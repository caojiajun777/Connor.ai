"""FastAPI routes for the Connor.ai dashboard contract."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session
from app.api.schemas import (
    ClusterListResponse,
    DailyRunCreateRequest,
    ReportResponse,
    RunCounts,
    RunDetailResponse,
    ThreadListResponse,
    ThreadResponse,
    TraceTimelineResponse,
    WatchlistListResponse,
)
from app.domain import ThreadStatus, WatchStatus
from app.harness import DailyRunHarness
from app.repositories import (
    DailyReportRepository,
    EventClusterRepository,
    IntelligenceThreadRepository,
    RunRepository,
    WatchlistRepository,
)
from app.services import TraceService

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/runs/daily",
    response_model=RunDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_daily_run(request: DailyRunCreateRequest, session: SessionDep) -> RunDetailResponse:
    """Create a scheduled daily run without executing agent loops."""

    run_repository = RunRepository(session)
    if request.run_id is not None and run_repository.get(request.run_id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"run already exists: {request.run_id}",
        )

    harness = DailyRunHarness(session)
    try:
        run = harness.create_run(
            report_date=request.report_date,
            objective=request.objective,
            run_id=request.run_id,
            budgets=request.budgets,
            enabled_sources=request.enabled_sources,
            metadata=request.metadata,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="run already exists or violates persistence constraints",
        ) from exc
    except Exception:
        session.rollback()
        raise
    full_state = RunRepository(session).get_full_state(run.id)
    return _run_detail(full_state)


@router.get("/runs/{run_id}", response_model=RunDetailResponse)
def get_run(run_id: str, session: SessionDep) -> RunDetailResponse:
    """Return a full dashboard-ready run state."""

    try:
        full_state = RunRepository(session).get_full_state(run_id)
    except LookupError as exc:
        raise _not_found("run", run_id) from exc
    return _run_detail(full_state)


@router.get("/runs/{run_id}/trace", response_model=TraceTimelineResponse)
def get_run_trace(run_id: str, session: SessionDep) -> TraceTimelineResponse:
    """Return the replayable trace timeline for a run."""

    _require_run(session, run_id)
    timeline = TraceService(session).reconstruct_timeline(run_id)
    return TraceTimelineResponse(
        run_id=run_id,
        events=[_dump(event) for event in timeline.events],
        tool_calls={key: _dump(value) for key, value in timeline.tool_calls.items()},
        model_calls={key: _dump(value) for key, value in timeline.model_calls.items()},
        artifacts={key: _dump(value) for key, value in timeline.artifacts.items()},
    )


@router.get("/runs/{run_id}/clusters", response_model=ClusterListResponse)
def get_run_clusters(run_id: str, session: SessionDep) -> ClusterListResponse:
    """Return event clusters for a run."""

    _require_run(session, run_id)
    clusters = EventClusterRepository(session).list_by_run(run_id)
    return ClusterListResponse(run_id=run_id, clusters=[_dump(cluster) for cluster in clusters])


@router.get("/reports/{report_id}", response_model=ReportResponse)
def get_report(report_id: str, session: SessionDep) -> ReportResponse:
    """Return a rendered report and all dashboard render payloads."""

    try:
        report = DailyReportRepository(session).require(report_id)
    except LookupError as exc:
        raise _not_found("report", report_id) from exc
    return ReportResponse(
        report=_dump(report),
        full_markdown=report.full_markdown,
        full_json=report.full_json,
        evidence_map=[entry.model_dump(mode="json") for entry in report.evidence_map],
        watchlist_updates=[entry.model_dump(mode="json") for entry in report.watchlist_updates],
        trace_timeline_ids=report.trace_timeline_ids,
    )


@router.get("/watchlist", response_model=WatchlistListResponse)
def list_watchlist(
    session: SessionDep,
    run_id: str | None = None,
    status_filter: Annotated[list[WatchStatus] | None, Query(alias="status")] = None,
) -> WatchlistListResponse:
    """Return watchlist items, optionally filtered by run and status."""

    repository = WatchlistRepository(session)
    if run_id is not None:
        _require_run(session, run_id)
        items = repository.list_by_run(run_id)
    elif status_filter:
        items = repository.list_by_statuses([item.value for item in status_filter])
    else:
        items = repository.list_all()
    if run_id is not None and status_filter:
        allowed = {item.value for item in status_filter}
        items = [item for item in items if item.status.value in allowed]
    return WatchlistListResponse(watchlist=[_dump(item) for item in items])


@router.get("/threads", response_model=ThreadListResponse)
def list_threads(
    session: SessionDep,
    status_filter: Annotated[list[ThreadStatus] | None, Query(alias="status")] = None,
) -> ThreadListResponse:
    """Return intelligence threads, optionally filtered by status."""

    repository = IntelligenceThreadRepository(session)
    if status_filter:
        threads = repository.list_by_statuses([item.value for item in status_filter])
    else:
        threads = repository.list_all()
    return ThreadListResponse(threads=[_dump(thread) for thread in threads])


@router.get("/threads/{thread_id}", response_model=ThreadResponse)
def get_thread(thread_id: str, session: SessionDep) -> ThreadResponse:
    """Return one intelligence thread."""

    try:
        thread = IntelligenceThreadRepository(session).require(thread_id)
    except LookupError as exc:
        raise _not_found("thread", thread_id) from exc
    return ThreadResponse(thread=_dump(thread))


def _require_run(session: Session, run_id: str):
    try:
        return RunRepository(session).require(run_id)
    except LookupError as exc:
        raise _not_found("run", run_id) from exc


def _run_detail(full_state) -> RunDetailResponse:
    return RunDetailResponse(
        run=_dump(full_state.run),
        counts=RunCounts(
            evidence=len(full_state.evidence),
            candidates=len(full_state.candidates),
            clusters=len(full_state.clusters),
            evaluations=len(full_state.evaluations),
            watchlist=len(full_state.watchlist),
            archives=len(full_state.archives),
            threads=len(full_state.threads),
            reports=len(full_state.reports),
            trace_events=len(full_state.trace_events),
            tool_calls=len(full_state.tool_calls),
            model_calls=len(full_state.model_calls),
            artifacts=len(full_state.artifacts),
            review_results=len(full_state.review_results),
            review_issues=len(full_state.review_issues),
        ),
        evidence=[_dump(item) for item in full_state.evidence],
        candidates=[_dump(item) for item in full_state.candidates],
        clusters=[_dump(item) for item in full_state.clusters],
        evaluations=[_dump(item) for item in full_state.evaluations],
        watchlist=[_dump(item) for item in full_state.watchlist],
        archives=[_dump(item) for item in full_state.archives],
        threads=[_dump(item) for item in full_state.threads],
        reports=[_dump(item) for item in full_state.reports],
        review_results=[_dump(item) for item in full_state.review_results],
        review_issues=[_dump(item) for item in full_state.review_issues],
        latest_report_id=full_state.run.report_id,
    )


def _dump(obj) -> dict:
    return obj.model_dump(mode="json")


def _not_found(kind: str, object_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"{kind} not found: {object_id}",
    )
