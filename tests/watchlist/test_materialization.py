"""Watchlist Agent output materialization tests."""

from __future__ import annotations

from app.agents import AgentRunResult
from app.agents.outputs import ArchiveDraft, WatchlistAgentOutput, WatchlistDraft
from app.domain import (
    AgentRole,
    ArchiveReason,
    ConfidenceLevel,
    LaterOutcome,
    PriorityLevel,
    RunPhase,
    ThreadTimelineEntry,
    TraceEventType,
    WatchTier,
    WatchStatus,
)
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
from app.watchlist.materialization import WatchlistOutputMaterializer
from tests.domain.fixtures import BASE_TIME, RUN_ID, early_signal_bundle, run_state_fixture


def test_watchlist_draft_creates_watch_item_thread_and_trace(db_session) -> None:
    context = HarnessContext(db_session)
    run = run_state_fixture()
    context.runs.add(run)
    early = _persist_early_bundle(db_session, include_watch=False)

    result = AgentRunResult(
        run_id=RUN_ID,
        phase=RunPhase.WATCHLIST_UPDATE,
        agent_role=AgentRole.WATCHLIST_AGENT,
        structured_output=WatchlistAgentOutput(
            summary="Watchlist Agent opened one short watch.",
            watchlist_drafts=[
                WatchlistDraft(
                    watchlist_id="watch_agent_openai_reasoning",
                    source_evaluation_id=early["evaluation"].id,
                    cluster_ids=[early["cluster"].id],
                    topic="OpenAI reasoning-control API watch",
                    thesis="OpenAI may be exposing finer-grained reasoning controls.",
                    watch_tier=WatchTier.SHORT,
                    priority=PriorityLevel.HIGH,
                    ttl_days=7,
                    reactivation_rules=["Reactivate on official API changelog evidence."],
                    open_questions=["Is this public API or gray rollout behavior?"],
                    evidence_ids=[item.id for item in early["evidence"]],
                )
            ],
        ),
    )

    materialized = WatchlistOutputMaterializer(context).materialize(
        run=run,
        phase=RunPhase.WATCHLIST_UPDATE,
        agent_role=AgentRole.WATCHLIST_AGENT,
        result=result,
    )

    watch = WatchlistRepository(db_session).require("watch_agent_openai_reasoning")
    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)

    assert materialized.watchlist_ids == ["watch_agent_openai_reasoning"]
    assert watch.status == WatchStatus.ACTIVE
    assert watch.watch_tier == WatchTier.SHORT
    assert watch.thread_id is not None
    assert watch.metadata["source_evaluation_id"] == early["evaluation"].id
    assert IntelligenceThreadRepository(db_session).require(watch.thread_id)
    assert TraceEventType.WATCHLIST_UPDATED in [event.event_type for event in timeline.events]
    assert TraceEventType.THREAD_UPDATED in [event.event_type for event in timeline.events]


def test_archive_draft_archives_existing_watch_item(db_session) -> None:
    context = HarnessContext(db_session)
    run = run_state_fixture()
    context.runs.add(run)
    early = _persist_early_bundle(db_session, include_watch=True)

    result = AgentRunResult(
        run_id=RUN_ID,
        phase=RunPhase.WATCHLIST_UPDATE,
        agent_role=AgentRole.WATCHLIST_AGENT,
        structured_output=WatchlistAgentOutput(
            summary="Watchlist Agent archived one stale watch.",
            archive_drafts=[
                ArchiveDraft(
                    archive_id="arch_agent_openai_reasoning",
                    original_watchlist_id=early["watch"].id,
                    original_cluster_id=early["cluster"].id,
                    thread_id=early["thread"].id,
                    archive_reason=ArchiveReason.NO_NEW_SIGNAL,
                    final_state="No official confirmation appeared during the watch window.",
                    reactivation_hint="Reactivate on official docs or first-party SDK commits.",
                    evidence_ids=[item.id for item in early["evidence"]],
                )
            ],
        ),
    )

    materialized = WatchlistOutputMaterializer(context).materialize(
        run=run,
        phase=RunPhase.WATCHLIST_UPDATE,
        agent_role=AgentRole.WATCHLIST_AGENT,
        result=result,
    )

    archive = ArchivedSignalRepository(db_session).require("arch_agent_openai_reasoning")
    watch = WatchlistRepository(db_session).require(early["watch"].id)
    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)

    assert materialized.archive_ids == ["arch_agent_openai_reasoning"]
    assert archive.archive_reason == ArchiveReason.NO_NEW_SIGNAL
    assert archive.thread_id == early["thread"].id
    assert watch.status == WatchStatus.ARCHIVED
    assert TraceEventType.ARCHIVE_CREATED in [event.event_type for event in timeline.events]
    assert TraceEventType.THREAD_UPDATED in [event.event_type for event in timeline.events]


def test_watchlist_materializer_clamps_ttl_to_tier_window(db_session) -> None:
    context = HarnessContext(db_session)
    run = run_state_fixture()
    context.runs.add(run)
    early = _persist_early_bundle(db_session, include_watch=False)

    result = AgentRunResult(
        run_id=RUN_ID,
        phase=RunPhase.WATCHLIST_UPDATE,
        agent_role=AgentRole.WATCHLIST_AGENT,
        structured_output=WatchlistAgentOutput(
            summary="Watchlist Agent opened one short watch with oversized ttl.",
            watchlist_drafts=[
                WatchlistDraft(
                    watchlist_id="watch_agent_openai_reasoning",
                    source_evaluation_id=early["evaluation"].id,
                    topic="OpenAI reasoning-control API watch",
                    thesis="OpenAI may be exposing finer-grained reasoning controls.",
                    watch_tier=WatchTier.SHORT,
                    ttl_days=30,
                    reactivation_rules=["Reactivate on official API changelog evidence."],
                    evidence_ids=[item.id for item in early["evidence"]],
                )
            ],
        ),
    )

    WatchlistOutputMaterializer(context).materialize(
        run=run,
        phase=RunPhase.WATCHLIST_UPDATE,
        agent_role=AgentRole.WATCHLIST_AGENT,
        result=result,
    )

    watch = WatchlistRepository(db_session).require("watch_agent_openai_reasoning")
    assert watch.ttl_days == 7
    assert watch.metadata["normalized_ttl_days_from"] == 30
    assert watch.metadata["normalized_ttl_days_to"] == 7


def test_thread_timeline_merge_keeps_same_event_with_different_time() -> None:
    first = ThreadTimelineEntry(
        event_at=BASE_TIME,
        summary="Same signal updated.",
        confidence_at_time=ConfidenceLevel.LOW,
        later_outcome=LaterOutcome.PENDING,
        cluster_id="cl_openai_reasoning_api",
    )
    second = first.model_copy(update={"event_at": BASE_TIME.replace(hour=13)})

    merged = WatchlistOutputMaterializer._merge_timeline([first], [second])

    assert merged == [first, second]


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
