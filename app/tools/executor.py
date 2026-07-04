"""Tool execution wrapper with tracing, artifacts, and evidence persistence."""

from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError
from app.core.ids import deterministic_id
from sqlalchemy.orm import Session

from app.domain import (
    AgentRole,
    EvidenceItem,
    ToolCallStatus,
    ToolEnvelope,
    ToolError,
)
from app.domain.base import utc_now
from app.repositories import EvidenceRepository
from app.services import TraceService
from app.tools.base import ToolExecutionContext, ToolExecutionResult, ToolSpec
from app.tools.registry import ToolRegistry
from app.domain.enums import TraceEventType


class ToolExecutor:
    """Execute registered tools through the Connor.ai contract."""

    def __init__(
        self,
        session: Session,
        *,
        registry: ToolRegistry,
        trace_service: TraceService | None = None,
    ):
        self.session = session
        self.registry = registry
        self.trace_service = trace_service or TraceService(session)
        self.evidence_repository = EvidenceRepository(session)

    def execute(
        self,
        *,
        tool_name: str,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        """Run a registered tool, persist call/evidence, and write trace records."""

        registered = self.registry.require_allowed(tool_name, context.agent_role)
        spec = registered.spec
        started_at = utc_now()
        start = time.perf_counter()

        try:
            raw_result = registered.func(context)
            envelope = self._validate_envelope(spec, raw_result)
            status = self._status_for_envelope(envelope)
            error = self._error_summary(envelope) if status != ToolCallStatus.SUCCEEDED else None
        except Exception as exc:
            envelope = self._error_envelope(spec, context, exc)
            status = ToolCallStatus.FAILED
            error = str(exc)

        ended_at = utc_now()
        duration_ms = int((time.perf_counter() - start) * 1000)
        response_payload = envelope.model_dump(mode="json")

        tool_call, trace_event = self.trace_service.record_tool_call(
            run_id=context.run_id,
            phase=context.phase,
            agent_role=context.agent_role,
            tool_name=spec.name,
            source_type=spec.source_type,
            query=context.query,
            status=status,
            request_payload={
                "tool_name": spec.name,
                "query": context.query,
                "params": context.params,
                "agent_role": context.agent_role.value,
            },
            response_payload=response_payload,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            error=error,
            metadata={
                "source_type": spec.source_type.value,
                "item_count": len(envelope.items),
                "error_count": len(envelope.errors),
            },
        )

        if tool_call.response_artifact_ref is not None:
            envelope = envelope.model_copy(
                update={"raw_artifact_ref": tool_call.response_artifact_ref}
            )

        evidence_items = self._persist_evidence(spec, context, envelope)
        evidence_trace_event = None
        if evidence_items:
            evidence_trace_event = self.trace_service.record_event(
                run_id=context.run_id,
                phase=context.phase,
                agent_role=context.agent_role,
                event_type=TraceEventType.EVIDENCE_CREATED,
                summary=f"Tool {spec.name} created {len(evidence_items)} evidence item(s).",
                created_objects=evidence_items,
                metadata={
                    "tool_name": spec.name,
                    "tool_call_id": tool_call.id,
                    "evidence_ids": [item.id for item in evidence_items],
                },
            )

        return ToolExecutionResult(
            spec=spec,
            envelope=envelope,
            evidence_items=evidence_items,
            tool_call=tool_call,
            trace_event=trace_event,
            evidence_trace_event=evidence_trace_event,
        )

    def _persist_evidence(
        self,
        spec: ToolSpec,
        context: ToolExecutionContext,
        envelope: ToolEnvelope,
    ) -> list[EvidenceItem]:
        evidence_items = envelope.to_evidence_items(
            run_id=context.run_id,
            evidence_id_factory=lambda index, item: self._evidence_id(spec, context, index, item),
            source_name=spec.default_source_name or spec.name,
            access_level=spec.default_access_level,
            strength=spec.default_evidence_strength,
        )
        self.evidence_repository.add_many(evidence_items)
        return evidence_items

    @staticmethod
    def _validate_envelope(spec: ToolSpec, raw_result: ToolEnvelope | dict[str, Any]) -> ToolEnvelope:
        envelope = raw_result if isinstance(raw_result, ToolEnvelope) else ToolEnvelope.model_validate(raw_result)
        if envelope.tool_name != spec.name:
            raise ValueError(f"tool returned envelope for {envelope.tool_name}, expected {spec.name}")
        if envelope.source_type != spec.source_type:
            raise ValueError(
                f"tool {spec.name} returned source_type {envelope.source_type}, expected {spec.source_type}"
            )
        return envelope

    @staticmethod
    def _status_for_envelope(envelope: ToolEnvelope) -> ToolCallStatus:
        if envelope.errors and not envelope.items:
            return ToolCallStatus.FAILED
        return ToolCallStatus.SUCCEEDED

    @staticmethod
    def _error_summary(envelope: ToolEnvelope) -> str | None:
        if not envelope.errors:
            return None
        return "; ".join(f"{error.code}: {error.message}" for error in envelope.errors)

    @staticmethod
    def _error_envelope(spec: ToolSpec, context: ToolExecutionContext, exc: Exception) -> ToolEnvelope:
        error_code = "validation_error" if isinstance(exc, ValidationError) else "tool_execution_error"
        return ToolEnvelope(
            tool_name=spec.name,
            source_type=spec.source_type,
            query=context.query,
            retrieved_at=utc_now(),
            errors=[
                ToolError(
                    code=error_code,
                    message=str(exc),
                    retryable=False,
                )
            ],
            metadata={"exception_type": type(exc).__name__},
        )

    @staticmethod
    def _evidence_id(spec: ToolSpec, context: ToolExecutionContext, index: int, item) -> str:
        fingerprint_payload = {
            "run_id": context.run_id,
            "tool_name": spec.name,
            "source_type": spec.source_type.value,
            "index": index,
            "raw_hash": item.raw_hash,
            "url": item.url,
            "title": item.title,
            "snippet": item.snippet,
        }
        safe_tool_name = "".join(
            character if character.isalnum() else "_" for character in spec.name.lower()
        )
        return deterministic_id(f"ev_{safe_tool_name}", fingerprint_payload)

