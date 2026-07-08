"""Tiered data-retention cleanup for Connor.ai databases.

Keeps the database (PostgreSQL or SQLite) from growing
unbounded by applying per-table retention windows.

Run manually:  ``python -m app.cli cleanup``
Or after a run: ``python -m app.cli run --cleanup``
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (  # noqa: E402
    ArtifactRecord,
    CandidateItemRecord,
    DailyReportRecord,
    EvaluationResultRecord,
    EvidenceItemRecord,
    EventClusterRecord,
    ModelCallRecordORM,
    ReportEvaluationRecord,
    RunRecord,
    ToolCallRecordORM,
    TraceEventRecord,
)
from app.domain.base import utc_now


def cleanup_expired_data(session: Session, *, dry_run: bool = False) -> dict:
    """Remove or archive data older than configured retention windows.

    Returns a dict with per-table counters.
    """

    settings = get_settings()
    now = utc_now()
    result: dict[str, int] = {}

    # ---- trace events (debug detail, short retention) ----
    if settings.trace_retention_days > 0:
        cutoff = now - timedelta(days=settings.trace_retention_days)
        stmt = delete(TraceEventRecord).where(TraceEventRecord.created_at < cutoff)
        if not dry_run:
            result["trace_events_deleted"] = session.execute(stmt).rowcount
        else:
            result["trace_events_would_delete"] = session.execute(
                select(TraceEventRecord.id).where(TraceEventRecord.created_at < cutoff)
            ).fetchall().__len__()

    # ---- model call records (cost auditing, medium retention) ----
    if settings.model_call_retention_days > 0:
        cutoff = now - timedelta(days=settings.model_call_retention_days)
        stmt = delete(ModelCallRecordORM).where(ModelCallRecordORM.created_at < cutoff)
        if not dry_run:
            result["model_calls_deleted"] = session.execute(stmt).rowcount
        else:
            result["model_calls_would_delete"] = session.execute(
                select(ModelCallRecordORM.id).where(ModelCallRecordORM.created_at < cutoff)
            ).fetchall().__len__()

    # ---- artifacts: clear inline content, keep file references ----
    if settings.artifact_retention_days > 0:
        cutoff = now - timedelta(days=settings.artifact_retention_days)
        if not dry_run:
            result["artifacts_inline_cleared"] = session.execute(
                update(ArtifactRecord)
                .where(ArtifactRecord.created_at < cutoff)
                .where(ArtifactRecord.inline_content.isnot(None))
                .values(inline_content=None)
            ).rowcount
        else:
            result["artifacts_would_clear_inline"] = session.execute(
                select(ArtifactRecord.id)
                .where(ArtifactRecord.created_at < cutoff)
                .where(ArtifactRecord.inline_content.isnot(None))
            ).fetchall().__len__()

    # ---- full-run data: archive old runs ----
    if settings.data_retention_days > 0:
        cutoff = now - timedelta(days=settings.data_retention_days)
        old_run_ids = session.execute(
            select(RunRecord.id).where(RunRecord.created_at < cutoff)
        ).scalars().all()

        if not dry_run:
            for run_id in old_run_ids:
                for model in [
                    EvidenceItemRecord,
                    CandidateItemRecord,
                    EventClusterRecord,
                    EvaluationResultRecord,
                    ReportEvaluationRecord,
                    ToolCallRecordORM,
                    ModelCallRecordORM,
                    DailyReportRecord,
                    TraceEventRecord,
                    ArtifactRecord,
                ]:
                    session.execute(delete(model).where(model.run_id == run_id))
            result["runs_archived"] = len(old_run_ids)
            result["archived_run_ids"] = [str(rid) for rid in old_run_ids[:20]]
        else:
            result["runs_would_archive"] = len(old_run_ids)

    if not dry_run:
        session.commit()

    return result
