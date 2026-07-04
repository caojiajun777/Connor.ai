"""Watchlist lifecycle policy tests."""

from __future__ import annotations

from datetime import timedelta

from app.domain import ArchiveReason, EvaluationDecision, RunPhase, TraceEventType, WatchStatus, WatchTier
from app.domain.base import utc_now
from app.harness import HarnessContext
from app.repositories import (
    ArchivedSignalRepository,
    CandidateRepository,
    EvaluationRepository,
    EventClusterRepository,
    EvidenceRepository,
    IntelligenceThreadRepository,
    WatchlistRepository,
)
from app.services import TraceService
from app.watchlist.lifecycle import WatchlistLifecycleService
from tests.domain.fixtures import RUN_ID, early_signal_bundle, run_state_fixture


def test_sync_evaluation_memory_creates_default_short_watch(db_session) -> None:
    context = HarnessContext(db_session)
    run = run_state_fixture()
    context.runs.add(run)
    early = _persist_early_bundle(db_session, include_watch=False)

    result = WatchlistLifecycleService(context).sync_evaluation_memory(
        run=run,
        phase=RunPhase.WATCHLIST_UPDATE,
    )

    watches = WatchlistRepository(db_session).list_by_run(RUN_ID)
    threads = IntelligenceThreadRepository(db_session).list_by_statuses(
        ["active", "dormant", "archived", "resolved"]
    )
    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)

    assert len(result.watchlist_ids) == 1
    assert len(watches) == 1
    assert watches[0].watch_tier == WatchTier.SHORT
    assert watches[0].ttl_days == 7
    assert watches[0].cluster_ids == [early["cluster"].id]
    assert watches[0].metadata["source_evaluation_id"] == early["evaluation"].id
    assert len(threads) == 1
    assert TraceEventType.WATCHLIST_UPDATED in [event.event_type for event in timeline.events]
    assert TraceEventType.THREAD_UPDATED in [event.event_type for event in timeline.events]


def test_expire_due_items_archives_watch_and_updates_thread(db_session) -> None:
    context = HarnessContext(db_session)
    run = run_state_fixture()
    context.runs.add(run)
    early = _persist_early_bundle(db_session, include_watch=True)
    db_session.flush()
    now = utc_now()
    due_watch = early["watch"].model_copy(
        update={
            "created_at": now - timedelta(days=3),
            "watch_until": now - timedelta(hours=1),
            "status": WatchStatus.ACTIVE,
        }
    )
    WatchlistRepository(db_session).add(due_watch)

    result = WatchlistLifecycleService(context).expire_due_items(
        run=run,
        phase=RunPhase.WATCHLIST_UPDATE,
    )

    expired_watch = WatchlistRepository(db_session).require(due_watch.id)
    archives = ArchivedSignalRepository(db_session).list_by_run(RUN_ID)
    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)

    assert len(result.archive_ids) == 1
    assert expired_watch.status == WatchStatus.EXPIRED
    assert any(archive.archive_reason == ArchiveReason.TTL_EXPIRED for archive in archives)
    assert any(archive.original_watchlist_id == due_watch.id for archive in archives)
    assert TraceEventType.ARCHIVE_CREATED in [event.event_type for event in timeline.events]
    assert TraceEventType.THREAD_UPDATED in [event.event_type for event in timeline.events]


def test_sync_evaluation_memory_uses_archive_cluster_lineage_for_dedupe(db_session) -> None:
    context = HarnessContext(db_session)
    run = run_state_fixture()
    context.runs.add(run)
    early = early_signal_bundle()
    EvidenceRepository(db_session).add_many(early["evidence"])
    CandidateRepository(db_session).add(early["candidate"])
    EventClusterRepository(db_session).add(early["cluster"])
    ArchivedSignalRepository(db_session).add(early["archive"])
    EvaluationRepository(db_session).add(
        early["evaluation"].model_copy(
            update={
                "id": "eval_archive_without_metadata",
                "decision": EvaluationDecision.ARCHIVE,
                "total_score": 4.0,
                "required_followups": [],
                "metadata": {},
            }
        )
    )

    result = WatchlistLifecycleService(context).sync_evaluation_memory(
        run=run,
        phase=RunPhase.WATCHLIST_UPDATE,
    )
    archives = ArchivedSignalRepository(db_session).list_by_run(RUN_ID)

    assert result.archive_ids == []
    assert len(archives) == 1
    assert archives[0].original_cluster_id == early["cluster"].id


def _persist_early_bundle(db_session, *, include_watch: bool) -> dict[str, object]:
    bundle = early_signal_bundle()
    EvidenceRepository(db_session).add_many(bundle["evidence"])
    CandidateRepository(db_session).add(bundle["candidate"])
    EventClusterRepository(db_session).add(bundle["cluster"])
    EvaluationRepository(db_session).add(bundle["evaluation"])
    if include_watch:
        WatchlistRepository(db_session).add(bundle["watch"])
        ArchivedSignalRepository(db_session).add(bundle["archive"])
        IntelligenceThreadRepository(db_session).add(bundle["thread"])
    return bundle
