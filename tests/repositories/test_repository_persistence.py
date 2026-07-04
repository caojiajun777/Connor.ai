"""Repository persistence and reconstruction tests."""

from datetime import timedelta

from app.domain import (
    AgentRole,
    Artifact,
    ArtifactKind,
    ArtifactStorage,
    ModelCallRecord,
    ModelCallStatus,
    ReviewDecision,
    ReviewIssue,
    ReviewResult,
    RunPhase,
    RunStatus,
    ToolCallRecord,
    ToolCallStatus,
    TraceEvent,
    TraceEventType,
    TraceStatus,
)
from app.repositories import (
    ArtifactRepository,
    ModelCallRepository,
    ReviewIssueRepository,
    ReviewResultRepository,
    RunRepository,
    ToolCallRepository,
    TraceEventRepository,
)
from tests.domain.fixtures import (
    BASE_TIME,
    RUN_ID,
    confirmed_event_bundle,
    daily_report_fixture,
    early_signal_bundle,
    run_state_fixture,
    tech_finance_bundle,
)


def persist_representative_run(session) -> RunRepository:
    repo = RunRepository(session)
    run = run_state_fixture()
    repo.add(run)

    for bundle_factory in [early_signal_bundle, confirmed_event_bundle, tech_finance_bundle]:
        bundle = bundle_factory()
        repo.evidence.add_many(bundle["evidence"])
        repo.candidates.add(bundle["candidate"])
        repo.clusters.add(bundle["cluster"])
        repo.evaluations.add(bundle["evaluation"])
        if "watch" in bundle:
            repo.watchlist.add(bundle["watch"])
        if "archive" in bundle:
            repo.archives.add(bundle["archive"])
        if "thread" in bundle:
            repo.threads.add(bundle["thread"])
        if "trace" in bundle:
            repo.traces.add(bundle["trace"])

    report = daily_report_fixture()
    repo.reports.add(report)

    tool_call = ToolCallRecord(
        id="tool_github_search_1",
        run_id=RUN_ID,
        agent_role=AgentRole.CODE_MODEL_SCOUT,
        tool_name="github_search",
        source_type="github",
        query="reasoning control OpenAI API",
        status=ToolCallStatus.SUCCEEDED,
        started_at=BASE_TIME,
        ended_at=BASE_TIME + timedelta(seconds=1),
        duration_ms=1000,
        trace_event_id="trace_tool_github_search_1",
        created_at=BASE_TIME,
    )
    model_call = ModelCallRecord(
        id="model_frontier_eval_1",
        run_id=RUN_ID,
        agent_role=AgentRole.FRONTIER_EVALUATOR,
        model_provider="openai",
        model_name="gpt-test",
        status=ModelCallStatus.SUCCEEDED,
        started_at=BASE_TIME,
        ended_at=BASE_TIME + timedelta(seconds=2),
        duration_ms=2000,
        trace_event_id="trace_eval_openai_reasoning",
        input_tokens=100,
        output_tokens=50,
        created_at=BASE_TIME,
    )
    artifact = Artifact(
        id="artifact_raw_github_search_1",
        run_id=RUN_ID,
        kind=ArtifactKind.RAW_TOOL_RESPONSE,
        storage=ArtifactStorage.INLINE,
        inline_content={"items": [{"title": "OpenAI wrapper commit"}]},
        content_type="application/json",
        sha256="sha256:artifact",
        size_bytes=128,
        created_at=BASE_TIME,
    )
    review_issue = ReviewIssue(
        id="review_issue_1",
        run_id=RUN_ID,
        report_id=report.id,
        priority=2,
        title="Clarify early-signal uncertainty",
        body="The draft should state that the OpenAI API signal is not officially confirmed.",
        report_item_id="item_openai_reasoning_api",
        evidence_ids=["ev_openai_hn_reasoning"],
        created_at=BASE_TIME,
    )
    review_result = ReviewResult(
        id="review_result_1",
        run_id=RUN_ID,
        report_id=report.id,
        decision=ReviewDecision.REVISE,
        issues=[review_issue],
        required_changes=["Add explicit unconfirmed label to OpenAI API signal."],
        reasoning_summary="The report is useful but needs stricter uncertainty language.",
        created_at=BASE_TIME,
    )
    trace = TraceEvent(
        id="trace_tool_github_search_1",
        run_id=RUN_ID,
        seq=2,
        phase=RunPhase.SCOUTING,
        agent_role=AgentRole.CODE_MODEL_SCOUT,
        event_type=TraceEventType.TOOL_CALL_COMPLETED,
        status=TraceStatus.SUCCEEDED,
        summary="GitHub search completed and returned one relevant wrapper commit.",
        tool_call_id=tool_call.id,
        created_at=BASE_TIME,
    )

    ToolCallRepository(session).add(tool_call)
    ModelCallRepository(session).add(model_call)
    ArtifactRepository(session).add(artifact)
    ReviewIssueRepository(session).add(review_issue)
    ReviewResultRepository(session).add(review_result)
    TraceEventRepository(session).add(trace)

    session.commit()
    return repo


def test_repository_round_trips_core_domain_objects(db_session) -> None:
    repo = persist_representative_run(db_session)

    run = repo.require(RUN_ID)
    assert run.status == RunStatus.RUNNING

    evidence = repo.evidence.require("ev_openai_hn_reasoning")
    assert evidence.source_type == "hacker_news"

    candidate = repo.candidates.require("cand_openai_reasoning_api")
    assert candidate.evidence_ids == ["ev_openai_hn_reasoning", "ev_openai_wrapper_commit"]

    cluster = repo.clusters.get_by_dedupe_key("openai:reasoning-control-api")
    assert cluster is not None
    assert cluster.id == "cl_openai_reasoning_api"

    report = repo.reports.require("report_2026_07_03")
    assert report.evidence_map[0].report_item_id == "item_openai_reasoning_api"


def test_full_run_state_reconstructs_persisted_children(db_session) -> None:
    repo = persist_representative_run(db_session)

    full_state = repo.get_full_state(RUN_ID)

    assert full_state.run.id == RUN_ID
    assert len(full_state.evidence) == 4
    assert len(full_state.candidates) == 3
    assert len(full_state.clusters) == 3
    assert len(full_state.evaluations) == 3
    assert len(full_state.watchlist) == 1
    assert len(full_state.archives) == 1
    assert len(full_state.threads) == 1
    assert len(full_state.reports) == 1
    assert [event.seq for event in full_state.trace_events] == [1, 2]
    assert len(full_state.tool_calls) == 1
    assert len(full_state.model_calls) == 1
    assert len(full_state.artifacts) == 1
    assert len(full_state.review_results) == 1
    assert len(full_state.review_issues) == 1



def test_watchlist_repository_lists_only_active_due_items(db_session) -> None:
    from datetime import timedelta

    from app.domain import PriorityLevel, WatchStatus, WatchTier, WatchlistItem
    from app.repositories import RunRepository, WatchlistRepository

    RunRepository(db_session).add(run_state_fixture())
    repo = WatchlistRepository(db_session)
    due = WatchlistItem(
        id="watch_due",
        run_id=RUN_ID,
        topic="Due watch",
        thesis="This active watch is due for review.",
        watch_tier=WatchTier.SHORT,
        status=WatchStatus.ACTIVE,
        priority=PriorityLevel.HIGH,
        ttl_days=3,
        watch_until=BASE_TIME - timedelta(minutes=1),
        revisit_cadence_days=1,
        reactivation_rules=["Reactivate on new evidence."],
        created_at=BASE_TIME - timedelta(days=2),
    )
    future = due.model_copy(
        update={
            "id": "watch_future",
            "topic": "Future watch",
            "watch_until": BASE_TIME + timedelta(days=1),
        }
    )
    cooling = due.model_copy(
        update={
            "id": "watch_cooling_due",
            "topic": "Cooling watch",
            "status": WatchStatus.COOLING,
        }
    )
    repo.add_many([due, future, cooling])
    db_session.flush()

    assert [item.id for item in repo.list_active_due(before=BASE_TIME)] == ["watch_due"]


def test_full_run_state_reconstruction_uses_batched_child_payload_query(db_session) -> None:
    from sqlalchemy import event

    repo = persist_representative_run(db_session)
    statements = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", before_cursor_execute)
    try:
        full_state = repo.get_full_state(RUN_ID)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", before_cursor_execute)

    assert len(full_state.evidence) == 4
    assert len(full_state.threads) == 1
    assert len(statements) <= 4

