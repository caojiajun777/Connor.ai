"""Shared context and persistence helpers for loop harnesses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.agents import AgentRunner
from app.agents.config import AgentRoleConfig as _AgentRoleConfig
from app.domain import ArtifactKind, RunPhase, RunState, RunStatus, TraceEventType, TraceStatus
from app.domain.base import utc_now
from app.harness.config import HarnessConfig
from app.repositories import RunRepository
from app.services import ArtifactService, TraceService

#: Model factory signature — takes a role config and returns an AgentScope ChatModel.
ModelFactory = Callable[[_AgentRoleConfig], Any]


@dataclass
class HarnessContext:
    """Runtime dependencies shared by collect, writing, and daily harnesses."""

    session: Session
    agent_runner: AgentRunner | None = None
    config: HarnessConfig | None = None
    trace_service: TraceService | None = None
    artifact_service: ArtifactService | None = None
    model_factory: ModelFactory | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.config = self.config or HarnessConfig()
        self.artifact_service = self.artifact_service or ArtifactService(self.session)
        self.trace_service = self.trace_service or TraceService(
            self.session,
            artifact_service=self.artifact_service,
        )
        self.runs = RunRepository(self.session)

    def persist_run(self, run: RunState) -> RunState:
        """Merge the latest run state into persistence."""

        updated = run.model_copy(update={"updated_at": utc_now()})
        self.runs.add(updated)
        self.checkpoint()
        return updated

    def checkpoint(self) -> None:
        """Flush, and optionally commit, a durable harness checkpoint."""

        self.session.flush()
        if self.config.commit_checkpoints:
            self.session.commit()

    def transition_run(
        self,
        run: RunState,
        *,
        phase: RunPhase,
        status: RunStatus | None = None,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> RunState:
        """Persist a run phase/status transition and trace it."""

        next_run = run.model_copy(
            update={
                "phase": phase,
                "status": status or run.status,
                "metadata": {**run.metadata, **(metadata or {})},
                "updated_at": utc_now(),
            }
        )
        self.runs.add(next_run)
        self.trace_service.phase_started(
            run_id=run.id,
            phase=phase,
            summary=summary,
        )
        self.checkpoint()
        return next_run

    def complete_phase(self, *, run_id: str, phase: RunPhase, summary: str) -> None:
        self.trace_service.phase_completed(run_id=run_id, phase=phase, summary=summary)
        self.checkpoint()

    def fail_run(
        self,
        run: RunState,
        *,
        error_summary: str,
        phase: RunPhase | None = None,
        error_detail: str | None = None,
    ) -> RunState:
        failed = run.model_copy(
            update={
                "phase": phase or RunPhase.FAILED,
                "status": RunStatus.FAILED,
                "error_summary": error_summary,
                "updated_at": utc_now(),
            }
        )
        self.runs.add(failed)
        self.trace_service.record_event(
            run_id=run.id,
            phase=phase or RunPhase.FAILED,
            event_type=TraceEventType.ERROR,
            status=TraceStatus.FAILED,
            summary="Run failed.",
            error=error_detail or error_summary,
            metadata={"harness": True},
        )
        self.checkpoint()
        return failed

    def archive_snapshot(
        self,
        *,
        run_id: str,
        phase: RunPhase,
        label: str,
        payload: dict[str, Any] | list[Any],
        kind: ArtifactKind = ArtifactKind.NORMALIZED_PAYLOAD,
    ):
        """Store a harness snapshot artifact and link it through trace."""

        artifact = self.artifact_service.store_payload(
            run_id=run_id,
            kind=kind,
            payload=payload,
            metadata={"label": label, "phase": phase.value, "harness": True},
        )
        self.trace_service.record_event(
            run_id=run_id,
            phase=phase,
            event_type=TraceEventType.AGENT_DECISION,
            summary=f"Archived harness snapshot: {label}.",
            created_objects=[artifact],
            output_payload={
                "artifact_id": artifact.id,
                "label": label,
                "kind": artifact.kind.value,
            },
            metadata={"snapshot_label": label, "artifact_id": artifact.id},
        )
        self.checkpoint()
        return artifact
