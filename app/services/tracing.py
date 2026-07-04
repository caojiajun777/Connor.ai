"""Trace service for runtime event recording and timeline reconstruction."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.ids import random_id

from app.db.models import TraceEventRecord
from app.domain import (
    AgentRole,
    ArchivedSignal,
    Artifact,
    ArtifactKind,
    ArtifactRef,
    ArtifactStorage,
    CandidateItem,
    DailyReport,
    EvaluationResult,
    EvidenceItem,
    EventCluster,
    IntelligenceThread,
    ModelCallRecord,
    ModelCallStatus,
    ObjectRef,
    ObjectType,
    ReviewResult,
    RunPhase,
    ToolCallRecord,
    ToolCallStatus,
    TraceEvent,
    TraceEventType,
    TraceStatus,
    WatchlistItem,
)
from app.domain.base import DomainModel, utc_now
from app.repositories import (
    ArtifactRepository,
    ModelCallRepository,
    ToolCallRepository,
    TraceEventRepository,
)
from app.services.artifacts import ArtifactService


DOMAIN_OBJECT_TYPES: dict[type[BaseModel], ObjectType] = {
    EvidenceItem: ObjectType.EVIDENCE,
    CandidateItem: ObjectType.CANDIDATE,
    EventCluster: ObjectType.CLUSTER,
    EvaluationResult: ObjectType.EVALUATION,
    WatchlistItem: ObjectType.WATCHLIST,
    ArchivedSignal: ObjectType.ARCHIVE,
    IntelligenceThread: ObjectType.THREAD,
    DailyReport: ObjectType.REPORT,
    ReviewResult: ObjectType.REVIEW,
    TraceEvent: ObjectType.TRACE_EVENT,
    ToolCallRecord: ObjectType.TOOL_CALL,
    ModelCallRecord: ObjectType.MODEL_CALL,
    Artifact: ObjectType.ARTIFACT,
}


@dataclass(frozen=True)
class TraceTimeline:
    """Reconstructed run timeline with linked persisted records."""

    run_id: str
    events: list[TraceEvent]
    tool_calls: dict[str, ToolCallRecord]
    model_calls: dict[str, ModelCallRecord]
    artifacts: dict[str, Artifact]

    @property
    def events_by_phase(self) -> dict[RunPhase, list[TraceEvent]]:
        grouped: dict[RunPhase, list[TraceEvent]] = {}
        for event in self.events:
            grouped.setdefault(event.phase, []).append(event)
        return grouped

    @property
    def events_by_agent(self) -> dict[AgentRole, list[TraceEvent]]:
        grouped: dict[AgentRole, list[TraceEvent]] = {}
        for event in self.events:
            if event.agent_role is not None:
                grouped.setdefault(event.agent_role, []).append(event)
        return grouped


class TraceService:
    """High-level APIs for writing replayable trace records."""

    _seq_locks_guard: ClassVar[threading.Lock] = threading.Lock()
    _seq_locks: ClassVar[dict[str, threading.Lock]] = {}

    def __init__(
        self,
        session: Session,
        *,
        artifact_service: ArtifactService | None = None,
    ):
        self.session = session
        self.artifacts = artifact_service or ArtifactService(session)
        self.trace_repository = TraceEventRepository(session)
        self.tool_calls = ToolCallRepository(session)
        self.model_calls = ModelCallRepository(session)
        self.artifact_repository = ArtifactRepository(session)

    def record_event(
        self,
        *,
        run_id: str,
        phase: RunPhase,
        event_type: TraceEventType,
        summary: str,
        agent_role: AgentRole | None = None,
        status: TraceStatus = TraceStatus.SUCCEEDED,
        parent_id: str | None = None,
        reasoning_summary: str | None = None,
        tool_call_id: str | None = None,
        model_call_id: str | None = None,
        input_payload: str | bytes | dict[str, Any] | list[Any] | None = None,
        output_payload: str | bytes | dict[str, Any] | list[Any] | None = None,
        created_objects: list[BaseModel | ObjectRef] | None = None,
        duration_ms: int | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
        event_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> TraceEvent:
        """Create and persist a TraceEvent with optional input/output artifacts."""

        input_ref = self._store_trace_payload(
            run_id=run_id,
            payload=input_payload,
            direction="input",
        )
        output_ref = self._store_trace_payload(
            run_id=run_id,
            payload=output_payload,
            direction="output",
        )
        with self._sequence_lock_for_run(run_id):
            event = TraceEvent(
                id=event_id or self._new_id("trace"),
                run_id=run_id,
                parent_id=parent_id,
                seq=self._next_seq_unlocked(run_id),
                phase=phase,
                agent_role=agent_role,
                event_type=event_type,
                status=status,
                summary=summary,
                reasoning_summary=reasoning_summary,
                tool_call_id=tool_call_id,
                model_call_id=model_call_id,
                input_artifact_ref=input_ref,
                output_artifact_ref=output_ref,
                created_object_refs=self._object_refs(created_objects or []),
                duration_ms=duration_ms,
                error=error,
                metadata=metadata or {},
                created_at=occurred_at or utc_now(),
            )
            self.trace_repository.add(event)
            self.session.flush()
        return event

    def phase_started(self, *, run_id: str, phase: RunPhase, summary: str) -> TraceEvent:
        return self.record_event(
            run_id=run_id,
            phase=phase,
            event_type=TraceEventType.PHASE_STARTED,
            status=TraceStatus.STARTED,
            summary=summary,
        )

    def phase_completed(self, *, run_id: str, phase: RunPhase, summary: str) -> TraceEvent:
        return self.record_event(
            run_id=run_id,
            phase=phase,
            event_type=TraceEventType.PHASE_COMPLETED,
            status=TraceStatus.SUCCEEDED,
            summary=summary,
        )

    def agent_decision(
        self,
        *,
        run_id: str,
        phase: RunPhase,
        agent_role: AgentRole,
        summary: str,
        reasoning_summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> TraceEvent:
        return self.record_event(
            run_id=run_id,
            phase=phase,
            agent_role=agent_role,
            event_type=TraceEventType.AGENT_DECISION,
            summary=summary,
            reasoning_summary=reasoning_summary,
            metadata=metadata,
        )

    def object_created(
        self,
        *,
        run_id: str,
        phase: RunPhase,
        event_type: TraceEventType,
        created_object: BaseModel | ObjectRef,
        summary: str,
        agent_role: AgentRole | None = None,
    ) -> TraceEvent:
        return self.record_event(
            run_id=run_id,
            phase=phase,
            agent_role=agent_role,
            event_type=event_type,
            summary=summary,
            created_objects=[created_object],
        )

    def record_tool_call(
        self,
        *,
        run_id: str,
        phase: RunPhase,
        agent_role: AgentRole,
        tool_name: str,
        status: ToolCallStatus,
        source_type: str | None = None,
        query: str | None = None,
        request_payload: str | bytes | dict[str, Any] | list[Any] | None = None,
        response_payload: str | bytes | dict[str, Any] | list[Any] | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        duration_ms: int | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[ToolCallRecord, TraceEvent]:
        """Persist a tool call record and its corresponding trace event."""

        trace_id = self._new_id("trace")
        request_ref = self._store_artifact(
            run_id=run_id,
            kind=ArtifactKind.NORMALIZED_PAYLOAD,
            payload=request_payload,
        )
        response_ref = self._store_artifact(
            run_id=run_id,
            kind=ArtifactKind.RAW_TOOL_RESPONSE,
            payload=response_payload,
        )
        tool_call = ToolCallRecord(
            id=self._new_id("tool"),
            run_id=run_id,
            agent_role=agent_role,
            tool_name=tool_name,
            source_type=source_type,
            query=query,
            status=status,
            started_at=started_at or utc_now(),
            ended_at=ended_at,
            duration_ms=duration_ms,
            trace_event_id=trace_id,
            request_artifact_ref=request_ref,
            response_artifact_ref=response_ref,
            error=error,
            metadata=metadata or {},
            created_at=started_at or utc_now(),
        )
        self.tool_calls.add(tool_call)

        trace_status = self._trace_status_from_tool_status(status)
        event_type = (
            TraceEventType.TOOL_CALL_COMPLETED
            if trace_status != TraceStatus.STARTED
            else TraceEventType.TOOL_CALL_STARTED
        )
        trace = self.record_event(
            run_id=run_id,
            phase=phase,
            agent_role=agent_role,
            event_type=event_type,
            status=trace_status,
            summary=f"Tool call {tool_name} {status.value}.",
            tool_call_id=tool_call.id,
            duration_ms=duration_ms,
            error=error,
            metadata={"query": query, **(metadata or {})},
            event_id=trace_id,
            occurred_at=ended_at or started_at,
        )
        return tool_call, trace

    def record_model_call(
        self,
        *,
        run_id: str,
        phase: RunPhase,
        agent_role: AgentRole,
        model_provider: str,
        model_name: str,
        status: ModelCallStatus,
        prompt_payload: str | bytes | dict[str, Any] | list[Any] | None = None,
        response_payload: str | bytes | dict[str, Any] | list[Any] | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        duration_ms: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[ModelCallRecord, TraceEvent]:
        """Persist a model call record and its corresponding trace event."""

        trace_id = self._new_id("trace")
        prompt_ref = self._store_artifact(
            run_id=run_id,
            kind=ArtifactKind.MODEL_PROMPT,
            payload=prompt_payload,
        )
        response_ref = self._store_artifact(
            run_id=run_id,
            kind=ArtifactKind.MODEL_OUTPUT,
            payload=response_payload,
        )
        model_call = ModelCallRecord(
            id=self._new_id("model"),
            run_id=run_id,
            agent_role=agent_role,
            model_provider=model_provider,
            model_name=model_name,
            status=status,
            started_at=started_at or utc_now(),
            ended_at=ended_at,
            duration_ms=duration_ms,
            trace_event_id=trace_id,
            prompt_artifact_ref=prompt_ref,
            response_artifact_ref=response_ref,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error=error,
            metadata=metadata or {},
            created_at=started_at or utc_now(),
        )
        self.model_calls.add(model_call)

        trace_status = self._trace_status_from_model_status(status)
        event_type = (
            TraceEventType.MODEL_CALL_COMPLETED
            if trace_status != TraceStatus.STARTED
            else TraceEventType.MODEL_CALL_STARTED
        )
        trace = self.record_event(
            run_id=run_id,
            phase=phase,
            agent_role=agent_role,
            event_type=event_type,
            status=trace_status,
            summary=f"Model call {model_provider}/{model_name} {status.value}.",
            model_call_id=model_call.id,
            duration_ms=duration_ms,
            error=error,
            metadata=metadata,
            event_id=trace_id,
            occurred_at=ended_at or started_at,
        )
        return model_call, trace

    def reconstruct_timeline(self, run_id: str) -> TraceTimeline:
        """Reconstruct a run timeline with linked call and artifact records."""

        events = self.trace_repository.list_timeline(run_id)
        tool_calls = {call.id: call for call in self.tool_calls.list_by_run(run_id)}
        model_calls = {call.id: call for call in self.model_calls.list_by_run(run_id)}
        artifacts = {artifact.id: artifact for artifact in self.artifact_repository.list_by_run(run_id)}
        return TraceTimeline(
            run_id=run_id,
            events=events,
            tool_calls=tool_calls,
            model_calls=model_calls,
            artifacts=artifacts,
        )

    def _store_trace_payload(
        self,
        *,
        run_id: str,
        payload: str | bytes | dict[str, Any] | list[Any] | None,
        direction: str,
    ) -> ArtifactRef | None:
        if payload is None:
            return None
        return self.artifacts.store_payload(
            run_id=run_id,
            kind=ArtifactKind.TRACE_PAYLOAD,
            payload=payload,
            metadata={"direction": direction},
        ).ref

    def _store_artifact(
        self,
        *,
        run_id: str,
        kind: ArtifactKind,
        payload: str | bytes | dict[str, Any] | list[Any] | None,
    ) -> ArtifactRef | None:
        if payload is None:
            return None
        return self.artifacts.store_payload(
            run_id=run_id,
            kind=kind,
            payload=payload,
        ).ref

    def _next_seq_unlocked(self, run_id: str) -> int:
        self.session.flush()
        stmt = select(func.max(TraceEventRecord.seq)).where(TraceEventRecord.run_id == run_id)
        current = self.session.scalar(stmt)
        return 0 if current is None else int(current) + 1

    @classmethod
    def _sequence_lock_for_run(cls, run_id: str) -> threading.Lock:
        with cls._seq_locks_guard:
            lock = cls._seq_locks.get(run_id)
            if lock is None:
                lock = threading.Lock()
                cls._seq_locks[run_id] = lock
            return lock

    @classmethod
    def _object_refs(cls, objects: list[BaseModel | ObjectRef]) -> list[ObjectRef]:
        refs: list[ObjectRef] = []
        for obj in objects:
            if isinstance(obj, ObjectRef):
                refs.append(obj)
                continue
            refs.append(cls.object_ref_for(obj))
        return refs

    @staticmethod
    def object_ref_for(obj: BaseModel) -> ObjectRef:
        object_type = DOMAIN_OBJECT_TYPES.get(type(obj))
        if object_type is None:
            if isinstance(obj, DomainModel):
                raise ValueError(f"no ObjectType mapping for {type(obj).__name__}")
            raise TypeError("created objects must be domain models or ObjectRef values")
        return ObjectRef(object_type=object_type, object_id=obj.id)

    @staticmethod
    def _trace_status_from_tool_status(status: ToolCallStatus) -> TraceStatus:
        if status == ToolCallStatus.RUNNING:
            return TraceStatus.STARTED
        if status == ToolCallStatus.SKIPPED:
            return TraceStatus.SKIPPED
        if status == ToolCallStatus.SUCCEEDED:
            return TraceStatus.SUCCEEDED
        return TraceStatus.FAILED

    @staticmethod
    def _trace_status_from_model_status(status: ModelCallStatus) -> TraceStatus:
        if status == ModelCallStatus.RUNNING:
            return TraceStatus.STARTED
        if status == ModelCallStatus.SKIPPED:
            return TraceStatus.SKIPPED
        if status == ModelCallStatus.SUCCEEDED:
            return TraceStatus.SUCCEEDED
        return TraceStatus.FAILED

    @staticmethod
    def _new_id(prefix: str) -> str:
        return random_id(prefix)
