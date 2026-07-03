"""Trace service tests."""

import pytest
from pydantic import ValidationError

from app.domain import (
    AgentRole,
    ModelCallStatus,
    ObjectType,
    RunPhase,
    ToolCallStatus,
    TraceEventType,
    TraceStatus,
)
from app.repositories import RunRepository
from app.services import ArtifactService, TraceService
from tests.domain.fixtures import BASE_TIME, early_signal_bundle, run_state_fixture


def test_trace_service_records_events_calls_and_reconstructs_timeline(db_session, tmp_path) -> None:
    RunRepository(db_session).add(run_state_fixture())
    artifact_service = ArtifactService(db_session, artifact_root=tmp_path, inline_max_bytes=10_000)
    trace_service = TraceService(db_session, artifact_service=artifact_service)
    candidate = early_signal_bundle()["candidate"]

    phase_start = trace_service.phase_started(
        run_id="run_2026_07_03",
        phase=RunPhase.SCOUTING,
        summary="Scouting phase started.",
    )
    decision = trace_service.agent_decision(
        run_id="run_2026_07_03",
        phase=RunPhase.SCOUTING,
        agent_role=AgentRole.SOCIAL_SCOUT,
        summary="Social Scout decided to follow a community API signal.",
        reasoning_summary="The signal was specific, relevant, and trackable.",
        metadata={"topic": "OpenAI reasoning API"},
    )
    created = trace_service.object_created(
        run_id="run_2026_07_03",
        phase=RunPhase.SCOUTING,
        agent_role=AgentRole.SOCIAL_SCOUT,
        event_type=TraceEventType.CANDIDATE_CREATED,
        created_object=candidate,
        summary="Created early-signal candidate.",
    )
    tool_call, tool_trace = trace_service.record_tool_call(
        run_id="run_2026_07_03",
        phase=RunPhase.SCOUTING,
        agent_role=AgentRole.CODE_MODEL_SCOUT,
        tool_name="github_search",
        source_type="github",
        query="reasoning control OpenAI API",
        status=ToolCallStatus.SUCCEEDED,
        request_payload={"query": "reasoning control OpenAI API"},
        response_payload={"items": [{"title": "OpenAI wrapper commit"}]},
        started_at=BASE_TIME,
        ended_at=BASE_TIME,
        duration_ms=50,
    )
    model_call, model_trace = trace_service.record_model_call(
        run_id="run_2026_07_03",
        phase=RunPhase.EVALUATING,
        agent_role=AgentRole.FRONTIER_EVALUATOR,
        model_provider="openai",
        model_name="gpt-test",
        status=ModelCallStatus.SUCCEEDED,
        prompt_payload={"task": "evaluate frontier signal"},
        response_payload={"decision": "select_early_signal"},
        started_at=BASE_TIME,
        ended_at=BASE_TIME,
        duration_ms=75,
        input_tokens=120,
        output_tokens=40,
    )
    db_session.commit()

    timeline = trace_service.reconstruct_timeline("run_2026_07_03")

    assert [event.seq for event in timeline.events] == [0, 1, 2, 3, 4]
    assert timeline.events[0].id == phase_start.id
    assert timeline.events[1].id == decision.id
    assert timeline.events[2].created_object_refs[0].object_type == ObjectType.CANDIDATE
    assert timeline.events[2].created_object_refs[0].object_id == candidate.id
    assert timeline.events[3].id == tool_trace.id
    assert timeline.events[4].id == model_trace.id

    assert tool_call.id in timeline.tool_calls
    assert model_call.id in timeline.model_calls
    assert timeline.events_by_phase[RunPhase.SCOUTING] == timeline.events[:4]
    assert timeline.events_by_agent[AgentRole.SOCIAL_SCOUT][0].id == decision.id
    assert len(timeline.artifacts) == 4


def test_trace_service_records_error_events(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    trace_service = TraceService(db_session)

    event = trace_service.record_event(
        run_id="run_2026_07_03",
        phase=RunPhase.SCOUTING,
        event_type=TraceEventType.ERROR,
        status=TraceStatus.FAILED,
        summary="Tool failed.",
        error="Timeout",
    )

    assert event.status == TraceStatus.FAILED
    assert event.error == "Timeout"


def test_trace_service_rejects_failed_tool_call_without_error(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    trace_service = TraceService(db_session)

    with pytest.raises(ValidationError):
        trace_service.record_tool_call(
            run_id="run_2026_07_03",
            phase=RunPhase.SCOUTING,
            agent_role=AgentRole.CODE_MODEL_SCOUT,
            tool_name="github_search",
            status=ToolCallStatus.FAILED,
        )

