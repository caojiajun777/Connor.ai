"""Tool executor tests."""

from app.domain import (
    AgentRole,
    EvidenceStrength,
    SourceAccessLevel,
    SourceType,
    ToolCallStatus,
    ToolEnvelope,
    TraceEventType,
)
from app.repositories import EvidenceRepository, RunRepository
from app.services import TraceService
from app.tools import (
    ToolExecutionContext,
    ToolExecutor,
    ToolRegistry,
    ToolSpec,
    create_default_tool_registry,
)
from tests.domain.fixtures import BASE_TIME, RUN_ID, run_state_fixture


def test_executor_runs_manual_seed_and_persists_evidence_trace_and_artifacts(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    registry = create_default_tool_registry()
    executor = ToolExecutor(db_session, registry=registry)

    result = executor.execute(
        tool_name="manual_seed",
        context=ToolExecutionContext(
            run_id=RUN_ID,
            phase="scouting",
            agent_role=AgentRole.ORCHESTRATOR,
            query="seed OpenAI API signal",
            params={
                "retrieved_at": BASE_TIME,
                "seed_reason": "test fixture",
                "items": [
                    {
                        "title": "Manual OpenAI reasoning API signal",
                        "url": "https://example.com/openai-reasoning-signal",
                        "snippet": "A manually curated signal about possible reasoning API controls.",
                        "raw_hash": "sha256:manual-openai",
                    }
                ],
            },
        ),
    )
    db_session.commit()

    assert result.tool_call.status == ToolCallStatus.SUCCEEDED
    assert result.trace_event.tool_call_id == result.tool_call.id
    assert result.evidence_trace_event is not None
    assert result.evidence_trace_event.event_type == TraceEventType.EVIDENCE_CREATED
    assert len(result.evidence_items) == 1

    evidence = EvidenceRepository(db_session).require(result.evidence_items[0].id)
    assert evidence.source_type == SourceType.MANUAL
    assert evidence.access_level == SourceAccessLevel.INTERNAL
    assert evidence.strength == EvidenceStrength.MODERATE
    assert evidence.raw_artifact_ref == result.tool_call.response_artifact_ref

    timeline = TraceService(db_session).reconstruct_timeline(RUN_ID)
    assert [event.seq for event in timeline.events] == [0, 1]
    assert len(timeline.artifacts) == 2


def test_executor_generates_stable_evidence_ids_for_same_input(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    registry = create_default_tool_registry()
    executor = ToolExecutor(db_session, registry=registry)
    context = ToolExecutionContext(
        run_id=RUN_ID,
        phase="scouting",
        agent_role=AgentRole.SOCIAL_SCOUT,
        query="mock query",
        params={
            "items": [
                {
                    "title": "Same result",
                    "url": "https://example.com/same",
                    "snippet": "Same snippet",
                    "raw_hash": "sha256:same",
                }
            ]
        },
    )

    first = executor.execute(tool_name="mock_search", context=context)
    second = executor.execute(tool_name="mock_search", context=context)

    assert first.evidence_items[0].id == second.evidence_items[0].id


def test_executor_converts_tool_exception_to_failed_envelope_and_trace(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    registry = ToolRegistry()

    def exploding_tool(context: ToolExecutionContext):
        raise RuntimeError("boom")

    registry.register(
        ToolSpec(
            name="exploding",
            description="Explodes",
            source_type=SourceType.OTHER,
            allowed_agent_roles=frozenset({AgentRole.SOCIAL_SCOUT}),
        ),
        exploding_tool,
    )
    executor = ToolExecutor(db_session, registry=registry)

    result = executor.execute(
        tool_name="exploding",
        context=ToolExecutionContext(
            run_id=RUN_ID,
            phase="scouting",
            agent_role=AgentRole.SOCIAL_SCOUT,
            query="fail",
        ),
    )

    assert result.tool_call.status == ToolCallStatus.FAILED
    assert result.tool_call.error == "boom"
    assert result.envelope.errors[0].code == "tool_execution_error"
    assert result.evidence_items == []
    assert result.evidence_trace_event is None


def test_executor_treats_invalid_envelope_as_failed_tool_call(db_session) -> None:
    RunRepository(db_session).add(run_state_fixture())
    registry = ToolRegistry()

    def invalid_tool(context: ToolExecutionContext) -> ToolEnvelope:
        return ToolEnvelope(
            tool_name="wrong_name",
            source_type=SourceType.OTHER,
            query=context.query,
        )

    registry.register(
        ToolSpec(
            name="expected_name",
            description="Returns wrong envelope name",
            source_type=SourceType.OTHER,
            allowed_agent_roles=frozenset({AgentRole.SOCIAL_SCOUT}),
        ),
        invalid_tool,
    )
    executor = ToolExecutor(db_session, registry=registry)

    result = executor.execute(
        tool_name="expected_name",
        context=ToolExecutionContext(
            run_id=RUN_ID,
            phase="scouting",
            agent_role=AgentRole.SOCIAL_SCOUT,
            query="invalid",
        ),
    )

    assert result.tool_call.status == ToolCallStatus.FAILED
    assert result.envelope.tool_name == "expected_name"
    assert result.envelope.errors
    assert result.evidence_items == []

