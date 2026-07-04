"""Public API request and response schemas."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import Field

from app.domain import RunBudgets, SourceType
from app.domain.base import ConnorBaseModel, NonEmptyStr


class DailyRunCreateRequest(ConnorBaseModel):
    """Request body for creating a scheduled daily run."""

    report_date: date
    objective: NonEmptyStr
    run_id: str | None = None
    budgets: RunBudgets | None = None
    enabled_sources: list[SourceType] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ObjectEnvelope(ConnorBaseModel):
    """Public object envelope with type and payload."""

    object_type: NonEmptyStr
    id: NonEmptyStr
    payload: dict[str, Any]


class RunCounts(ConnorBaseModel):
    """Dashboard counts for a run."""

    evidence: int
    candidates: int
    clusters: int
    evaluations: int
    watchlist: int
    archives: int
    threads: int
    reports: int
    trace_events: int
    tool_calls: int
    model_calls: int
    artifacts: int
    review_results: int
    review_issues: int


class RunDetailResponse(ConnorBaseModel):
    """Dashboard-ready full run state."""

    run: dict[str, Any]
    counts: RunCounts
    evidence: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    clusters: list[dict[str, Any]]
    evaluations: list[dict[str, Any]]
    watchlist: list[dict[str, Any]]
    archives: list[dict[str, Any]]
    threads: list[dict[str, Any]]
    reports: list[dict[str, Any]]
    review_results: list[dict[str, Any]]
    review_issues: list[dict[str, Any]]
    latest_report_id: str | None = None


class TraceTimelineResponse(ConnorBaseModel):
    """Replayable trace timeline response."""

    run_id: NonEmptyStr
    events: list[dict[str, Any]]
    tool_calls: dict[str, dict[str, Any]]
    model_calls: dict[str, dict[str, Any]]
    artifacts: dict[str, dict[str, Any]]


class ClusterListResponse(ConnorBaseModel):
    """Run cluster list response."""

    run_id: NonEmptyStr
    clusters: list[dict[str, Any]]


class ReportResponse(ConnorBaseModel):
    """Dashboard-ready report response."""

    report: dict[str, Any]
    full_markdown: str | None
    full_json: dict[str, Any]
    evidence_map: list[dict[str, Any]]
    watchlist_updates: list[dict[str, Any]]
    trace_timeline_ids: list[str]


class WatchlistListResponse(ConnorBaseModel):
    """Watchlist list response."""

    watchlist: list[dict[str, Any]]


class ThreadListResponse(ConnorBaseModel):
    """Thread list response."""

    threads: list[dict[str, Any]]


class ThreadResponse(ConnorBaseModel):
    """Single intelligence thread response."""

    thread: dict[str, Any]
