"""AgentScope-first runner for Connor.ai agents."""

from __future__ import annotations

import asyncio
import json
from types import UnionType
from collections.abc import Callable
from typing import Any, get_args, get_origin

from agentscope.agent import Agent, ReActConfig
from agentscope.message import AssistantMsg, Msg, UserMsg
from agentscope.model import ChatModelBase
from pydantic import BaseModel
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agents.agentscope_tools import AgentScopeToolBridge
from app.agents.config import AgentRoleConfig
from app.agents.outputs import ClustererOutput, ReviewerOutput, ScoutOutput, WriterOutput
from app.agents.registry import AgentRoleRegistry
from app.agents.schemas import AgentRunRequest, AgentRunResult, AgentScopeExecutionError
from app.domain import CandidateCategory, EvidenceStrength, ReviewDecision, SignalStatus, TraceEventType, TraceStatus
from app.services import TraceService
from app.tools import ToolExecutor, ToolRegistry


AgentScopeModelFactory = Callable[[AgentRoleConfig], ChatModelBase]


class AgentRunner:
    """Run one Connor.ai role through an AgentScope Agent."""

    def __init__(
        self,
        session: Session,
        *,
        role_registry: AgentRoleRegistry,
        tool_registry: ToolRegistry,
        model_factory: AgentScopeModelFactory,
        trace_service: TraceService | None = None,
    ):
        self.session = session
        self.role_registry = role_registry
        self.tool_registry = tool_registry
        self.model_factory = model_factory
        self.trace_service = trace_service or TraceService(session)
        self.tool_executor = ToolExecutor(
            session,
            registry=tool_registry,
            trace_service=self.trace_service,
        )

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        """Synchronous wrapper for worker/test contexts without an event loop.

        NOTE: ``asyncio.run()`` must be called from the main thread on some platforms
        (Python 3.14+ enforces this on Windows). If this method is ever invoked from
        a worker thread, replace ``asyncio.run()`` with an explicit
        ``threading.Thread`` + ``new_event_loop()`` pattern, or migrate all callers to
        ``run_async()`` directly.
        """

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # NOTE: asyncio.run() must be called from the main thread when using
            # SQLite (check_same_thread). For production PostgreSQL deployments,
            # this is not a constraint. If this method is ever invoked from a
            # worker thread on Python 3.14+ Windows, replace with a
            # threading.Thread + new_event_loop() pattern and ensure the DB
            # driver supports cross-thread connections.
            try:
                return asyncio.run(self.run_async(request))
            except RuntimeError as exc:
                if "cannot be called from a worker thread" in str(exc).lower():
                    raise AgentScopeExecutionError(
                        "AgentRunner.run() called from a worker thread, which is "
                        "not supported with the current database driver. Use "
                        "AgentRunner.run_async() instead, or switch to PostgreSQL."
                    ) from exc
                raise
        raise AgentScopeExecutionError(
            "AgentRunner.run() cannot be called from an active event loop; "
            "use AgentRunner.run_async() instead."
        )

    async def run_async(self, request: AgentRunRequest) -> AgentRunResult:
        """Run one AgentScope agent turn with Connor tracing and artifacts."""

        config = self.role_registry.require(request.agent_role)
        start_event = self.trace_service.record_event(
            run_id=request.run_id,
            phase=request.phase,
            agent_role=request.agent_role,
            event_type=TraceEventType.AGENT_STARTED,
            status=TraceStatus.STARTED,
            summary=f"{config.display_name} started AgentScope task.",
            input_payload={
                "task": request.task,
                "context": request.context,
                "allowed_tool_names": config.allowed_tool_names,
                "agentscope": True,
            },
        )

        bridge = AgentScopeToolBridge(
            tool_registry=self.tool_registry,
            tool_executor=self.tool_executor,
            run_id=request.run_id,
            phase=request.phase,
            agent_role=request.agent_role,
            max_tool_calls=config.execution.max_tool_calls,
        )
        no_tools = bool(request.context.get("no_tools", False))

        try:
            agent = self._create_agent(config, bridge, no_tools=no_tools)
            coro = agent.reply(self._build_user_message(request, config))
            if config.execution.timeout_seconds is not None:
                response = await asyncio.wait_for(coro, timeout=config.execution.timeout_seconds)
            else:
                response = await coro
            output_text = self._extract_text(response)
            react_max_iters_repaired = False
            deterministic_structured_fallback = False
            if self._is_react_max_iters_response(output_text):
                fallback_payload = self._deterministic_react_limit_fallback(
                    request=request,
                    config=config,
                    bridge=bridge,
                    original_output_text=output_text,
                )
                if fallback_payload is not None:
                    output_text = json.dumps(fallback_payload, ensure_ascii=False)
                    response = AssistantMsg(name=agent.name, content=output_text)
                    deterministic_structured_fallback = True
                else:
                    response = await self._finalize_after_react_limit(
                        request=request,
                        config=config,
                        bridge=bridge,
                        original_output_text=output_text,
                    )
                    output_text = self._extract_text(response)
                react_max_iters_repaired = True
            structured_output_repaired = False
            try:
                structured_payload = self._normalize_payload_for_model(
                    config.output_model,
                    self._extract_structured_payload(response, output_text),
                )
                structured_payload = self._repair_payload_with_context(
                    config.output_model,
                    structured_payload,
                    request.context,
                )
                structured_output = config.output_model.model_validate(structured_payload)
            except (AgentScopeExecutionError, ValidationError, json.JSONDecodeError) as exc:
                response = await self._repair_structured_output(
                    request=request,
                    config=config,
                    bridge=bridge,
                    output_text=output_text,
                    error=exc,
                )
                output_text = self._extract_text(response)
                try:
                    structured_payload = self._normalize_payload_for_model(
                        config.output_model,
                        self._extract_structured_payload(response, output_text),
                    )
                    structured_payload = self._repair_payload_with_context(
                        config.output_model,
                        structured_payload,
                        request.context,
                    )
                    structured_output = config.output_model.model_validate(structured_payload)
                except (AgentScopeExecutionError, ValidationError, json.JSONDecodeError) as repair_exc:
                    fallback_payload = self._deterministic_structured_fallback(
                        request=request,
                        config=config,
                        error=repair_exc,
                    )
                    if fallback_payload is None:
                        raise
                    output_text = json.dumps(fallback_payload, ensure_ascii=False)
                    structured_payload = self._normalize_payload_for_model(
                        config.output_model,
                        fallback_payload,
                    )
                    structured_payload = self._repair_payload_with_context(
                        config.output_model,
                        structured_payload,
                        request.context,
                    )
                    structured_output = config.output_model.model_validate(structured_payload)
                    deterministic_structured_fallback = True
                structured_output_repaired = True
            completion_event = self.trace_service.record_event(
                run_id=request.run_id,
                phase=request.phase,
                agent_role=request.agent_role,
                event_type=TraceEventType.AGENT_COMPLETED,
                status=TraceStatus.SUCCEEDED,
                summary=f"{config.display_name} completed AgentScope task.",
                reasoning_summary=structured_output.reasoning_summary,
                output_payload=structured_output.model_dump(mode="json"),
                metadata={
                    "tool_call_count": bridge.executed_result_count(),
                    "output_model": config.output_model.__name__,
                    "agentscope_agent": agent.name,
                    "no_tools": no_tools,
                    "react_max_iters_repaired": react_max_iters_repaired,
                    "structured_output_repaired": structured_output_repaired,
                    "deterministic_structured_fallback": deterministic_structured_fallback,
                },
            )
            return AgentRunResult(
                run_id=request.run_id,
                phase=request.phase,
                agent_role=request.agent_role,
                output_text=output_text,
                structured_output=structured_output,
                tool_results=bridge.executed_results_snapshot(),
                start_trace_event=start_event,
                completion_trace_event=completion_event,
            )
        except asyncio.TimeoutError as exc:
            timeout_message = (
                f"{config.display_name} AgentScope task timed out after "
                f"{config.execution.timeout_seconds} second(s)."
            )
            self.trace_service.record_event(
                run_id=request.run_id,
                phase=request.phase,
                agent_role=request.agent_role,
                event_type=TraceEventType.ERROR,
                status=TraceStatus.FAILED,
                summary=f"{config.display_name} timed out during AgentScope task.",
                error=timeout_message,
                metadata={
                    "exception_type": "TimeoutError",
                    "agentscope": True,
                    "timeout_seconds": config.execution.timeout_seconds,
                },
            )
            fallback_payload = self._deterministic_structured_fallback(
                request=request,
                config=config,
                error=exc,
            )
            if fallback_payload is not None:
                output_text = json.dumps(fallback_payload, ensure_ascii=False)
                structured_payload = self._normalize_payload_for_model(
                    config.output_model,
                    fallback_payload,
                )
                structured_payload = self._repair_payload_with_context(
                    config.output_model,
                    structured_payload,
                    request.context,
                )
                structured_output = config.output_model.model_validate(structured_payload)
                completion_event = self.trace_service.record_event(
                    run_id=request.run_id,
                    phase=request.phase,
                    agent_role=request.agent_role,
                    event_type=TraceEventType.AGENT_COMPLETED,
                    status=TraceStatus.SUCCEEDED,
                    summary=(
                        f"{config.display_name} completed with deterministic fallback "
                        "after timeout."
                    ),
                    reasoning_summary=structured_output.reasoning_summary,
                    output_payload=structured_output.model_dump(mode="json"),
                    metadata={
                        "tool_call_count": bridge.executed_result_count(),
                        "output_model": config.output_model.__name__,
                        "agentscope_agent": getattr(locals().get("agent"), "name", None),
                        "no_tools": no_tools,
                        "timeout_fallback": True,
                        "structured_output_repaired": False,
                        "deterministic_structured_fallback": True,
                    },
                )
                self.session.flush()
                return AgentRunResult(
                    run_id=request.run_id,
                    phase=request.phase,
                    agent_role=request.agent_role,
                    output_text=output_text,
                    structured_output=structured_output,
                    tool_results=bridge.executed_results_snapshot(),
                    start_trace_event=start_event,
                    completion_trace_event=completion_event,
                )
            self.session.flush()
            raise AgentScopeExecutionError(timeout_message) from exc
        except Exception as exc:
            error_message = str(exc) or f"{type(exc).__name__} raised during AgentScope task."
            self.trace_service.record_event(
                run_id=request.run_id,
                phase=request.phase,
                agent_role=request.agent_role,
                event_type=TraceEventType.ERROR,
                status=TraceStatus.FAILED,
                summary=f"{config.display_name} failed AgentScope task.",
                error=error_message,
                metadata={
                    "exception_type": type(exc).__name__,
                    "agentscope": True,
                },
            )
            self.session.flush()
            if isinstance(exc, ValidationError):
                raise
            if isinstance(exc, AgentScopeExecutionError):
                raise
            raise AgentScopeExecutionError(error_message) from exc
        finally:
            await bridge.aclose()

    async def _finalize_after_react_limit(
        self,
        *,
        request: AgentRunRequest,
        config: AgentRoleConfig,
        bridge: AgentScopeToolBridge,
        original_output_text: str | None,
    ) -> Msg:
        """Force a structured JSON answer after AgentScope exhausts ReAct iterations."""

        self.trace_service.record_event(
            run_id=request.run_id,
            phase=request.phase,
            agent_role=request.agent_role,
            event_type=TraceEventType.AGENT_DECISION,
            status=TraceStatus.STARTED,
            summary=(
                f"{config.display_name} reached ReAct iteration limit; "
                "starting no-tool structured finalization."
            ),
            input_payload={
                "tool_call_count": bridge.executed_result_count(),
                "evidence_ids": bridge.executed_evidence_ids(),
                "original_output_text": original_output_text,
            },
            metadata={
                "agentscope_react_limit": True,
                "repair_mode": "no_tool_finalization",
            },
        )

        finalizer = self._create_agent(config, bridge, no_tools=True)
        coro = finalizer.reply(self._build_finalization_message(request, config, bridge))
        if config.execution.timeout_seconds is not None:
            response = await asyncio.wait_for(coro, timeout=config.execution.timeout_seconds)
        else:
            response = await coro

        self.trace_service.record_event(
            run_id=request.run_id,
            phase=request.phase,
            agent_role=request.agent_role,
            event_type=TraceEventType.AGENT_DECISION,
            status=TraceStatus.SUCCEEDED,
            summary=(
                f"{config.display_name} completed no-tool structured finalization "
                "after ReAct iteration limit."
            ),
            output_payload={
                "output_preview": (self._extract_text(response) or "")[:500],
            },
            metadata={
                "agentscope_react_limit": True,
                "repair_mode": "no_tool_finalization",
            },
        )
        return response

    def _deterministic_react_limit_fallback(
        self,
        *,
        request: AgentRunRequest,
        config: AgentRoleConfig,
        bridge: AgentScopeToolBridge,
        original_output_text: str | None,
    ) -> dict[str, Any] | None:
        """Build a conservative role-safe output when ReAct stops after tool use."""

        if config.output_model is not ScoutOutput:
            return None
        payload = self._fallback_scout_payload(request, bridge)
        if payload is None:
            return None
        self.trace_service.record_event(
            run_id=request.run_id,
            phase=request.phase,
            agent_role=request.agent_role,
            event_type=TraceEventType.AGENT_DECISION,
            status=TraceStatus.SUCCEEDED,
            summary=(
                f"{config.display_name} used deterministic Scout fallback after "
                "ReAct iteration limit."
            ),
            reasoning_summary=(
                "The Scout had already produced tool evidence but did not return "
                "structured JSON before the ReAct iteration boundary."
            ),
            input_payload={
                "tool_call_count": bridge.executed_result_count(),
                "evidence_ids": bridge.executed_evidence_ids(),
                "original_output_text": original_output_text,
            },
            output_payload=payload,
            metadata={
                "agentscope_react_limit": True,
                "repair_mode": "deterministic_scout_fallback",
            },
        )
        return payload

    @staticmethod
    def _fallback_scout_payload(
        request: AgentRunRequest,
        bridge: AgentScopeToolBridge,
    ) -> dict[str, Any] | None:
        evidence_items = [
            item
            for result in bridge.executed_results_snapshot()
            for item in result.evidence_items
        ]
        if not evidence_items:
            return {
                "summary": "Scout reached the ReAct boundary without usable tool evidence.",
                "reasoning_summary": (
                    "No tool evidence was available, so the safe fallback is to ask "
                    "for follow-up rather than create a candidate."
                ),
                "candidate_drafts": [],
                "followup_queries": ["Run a narrower source query for this Scout role."],
                "metadata": {"deterministic_scout_fallback": True},
            }

        first = evidence_items[0]
        evidence_ids = [item.id for item in evidence_items[:5]]
        category, signal_status = AgentRunner._fallback_scout_category_status(
            request.agent_role,
            first.strength,
        )
        title = first.title or first.snippet or f"{request.agent_role.value} source signal"
        snippet = first.snippet or title
        followup = f"Verify and monitor source updates for: {title}"
        draft: dict[str, Any] = {
            "category": category.value,
            "signal_status": signal_status.value,
            "claim_summary": f"Source signal: {title}",
            "entities": [],
            "tickers": AgentRunner._fallback_tickers(title, snippet),
            "topics": AgentRunner._fallback_scout_topics(request.agent_role),
            "evidence_ids": evidence_ids,
            "uncertainty": "medium",
            "evidence_strength": AgentRunner._fallback_evidence_strength(
                request.agent_role,
                first.strength,
            ).value,
            "why_it_matters": (
                "The source returned a bounded item relevant to this Scout role, "
                "but the model hit its ReAct boundary before writing a full judgment."
            ),
            "potential_impact": (
                "Requires follow-up before stronger conclusions; preserve as a "
                "trackable signal with source lineage."
            ),
            "followup_questions": [followup],
            "metadata": {"deterministic_scout_fallback": True},
        }
        if category == CandidateCategory.TECH_FINANCE and not (
            draft["tickers"] or draft["potential_impact"]
        ):
            draft["potential_impact"] = "Potential AI infrastructure or market impact requires follow-up."

        return {
            "summary": f"Deterministically created one Scout candidate from {len(evidence_items)} evidence item(s).",
            "reasoning_summary": (
                "Fallback used existing tool evidence and conservative uncertainty "
                "because ReAct reached its iteration boundary."
            ),
            "evidence_ids": evidence_ids,
            "candidate_drafts": [draft],
            "followup_queries": [followup],
            "metadata": {"deterministic_scout_fallback": True},
        }

    @staticmethod
    def _fallback_scout_category_status(
        role: Any,
        strength: EvidenceStrength,
    ) -> tuple[CandidateCategory, SignalStatus]:
        if role.value == "code_model_scout":
            return CandidateCategory.CODE_MODEL, SignalStatus.CODE_ANOMALY
        if role.value == "research_scout":
            return CandidateCategory.RESEARCH, SignalStatus.RESEARCHER_HINT
        if role.value == "official_scout":
            return CandidateCategory.OFFICIAL_UPDATE, SignalStatus.OFFICIAL_CONFIRMATION
        if role.value == "finance_scout":
            if strength in {EvidenceStrength.OFFICIAL, EvidenceStrength.STRONG}:
                return CandidateCategory.TECH_FINANCE, SignalStatus.CONFIRMED_FACT
            return CandidateCategory.TECH_FINANCE, SignalStatus.SINGLE_SOURCE_SIGNAL
        return CandidateCategory.EARLY_SIGNAL, SignalStatus.COMMUNITY_RUMOR

    @staticmethod
    def _fallback_evidence_strength(
        role: Any,
        strength: EvidenceStrength,
    ) -> EvidenceStrength:
        if role.value == "official_scout":
            return EvidenceStrength.OFFICIAL
        if role.value == "finance_scout" and strength == EvidenceStrength.UNKNOWN:
            return EvidenceStrength.MODERATE
        return strength if strength != EvidenceStrength.UNKNOWN else EvidenceStrength.WEAK

    @staticmethod
    def _fallback_scout_topics(role: Any) -> list[str]:
        topics_by_role = {
            "social_scout": ["community_signal"],
            "code_model_scout": ["code_model_signal"],
            "research_scout": ["research_signal"],
            "official_scout": ["official_update"],
            "finance_scout": ["tech_finance"],
        }
        return topics_by_role.get(role.value, ["frontier_signal"])

    @staticmethod
    def _fallback_tickers(*texts: str) -> list[str]:
        known_tickers = {
            "NVIDIA": "NVDA",
            "NVDA": "NVDA",
            "AMD": "AMD",
            "TSMC": "TSM",
            "TSM": "TSM",
            "ASML": "ASML",
            "Broadcom": "AVGO",
            "AVGO": "AVGO",
            "Microsoft": "MSFT",
            "MSFT": "MSFT",
            "Google": "GOOGL",
            "Alphabet": "GOOGL",
            "Meta": "META",
            "Amazon": "AMZN",
            "Oracle": "ORCL",
        }
        joined = " ".join(texts)
        return AgentRunner._dedupe_strings(
            [ticker for marker, ticker in known_tickers.items() if marker.lower() in joined.lower()]
        )

    def _deterministic_structured_fallback(
        self,
        *,
        request: AgentRunRequest,
        config: AgentRoleConfig,
        error: Exception,
    ) -> dict[str, Any] | None:
        """Build a conservative structured fallback for roles with safe rules."""

        if config.output_model is ClustererOutput:
            candidate_context = request.context.get("candidate_context")
            if not isinstance(candidate_context, list) or not candidate_context:
                return None
            payload = self._fallback_clusterer_payload(candidate_context)
            summary = "Clusterer used deterministic fallback after AgentScope JSON repair failed."
            reasoning_summary = (
                "AgentScope produced malformed JSON twice; harness grouped candidates "
                "conservatively by category and leading entity/ticker/topic."
            )
        elif config.output_model is WriterOutput:
            writing_context = request.context.get("writing_context")
            if not isinstance(writing_context, dict):
                return None
            payload = self._fallback_writer_payload(writing_context, request.context)
            if payload is None:
                return None
            summary = "Writer used deterministic fallback after AgentScope JSON repair failed."
            reasoning_summary = (
                "AgentScope produced malformed report JSON twice; harness rendered a "
                "conservative report from selected clusters, evaluations, and evidence."
            )
        else:
            return None

        self.trace_service.record_event(
            run_id=request.run_id,
            phase=request.phase,
            agent_role=request.agent_role,
            event_type=TraceEventType.AGENT_DECISION,
            status=TraceStatus.SUCCEEDED,
            summary=summary,
            reasoning_summary=reasoning_summary,
            output_payload=payload,
            metadata={
                "repair_mode": "deterministic_structured_fallback",
                "exception_type": type(error).__name__,
            },
        )
        return payload

    @staticmethod
    def _fallback_clusterer_payload(candidate_context: list[dict[str, Any]]) -> dict[str, Any]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for candidate in candidate_context:
            if not isinstance(candidate, dict):
                continue
            category = str(candidate.get("category") or CandidateCategory.OTHER.value)
            entities = candidate.get("entities") if isinstance(candidate.get("entities"), list) else []
            tickers = candidate.get("tickers") if isinstance(candidate.get("tickers"), list) else []
            topics = candidate.get("topics") if isinstance(candidate.get("topics"), list) else []
            key_label = str((tickers or entities or topics or ["misc"])[0]).lower()
            grouped.setdefault((category, key_label), []).append(candidate)

        cluster_drafts: list[dict[str, Any]] = []
        for (category, key_label), candidates in list(grouped.items())[:8]:
            candidate_ids = [
                str(candidate["id"])
                for candidate in candidates
                if candidate.get("id")
            ][:6]
            evidence_ids = AgentRunner._dedupe_strings(
                [
                    str(evidence_id)
                    for candidate in candidates
                    for evidence_id in (
                        candidate.get("evidence_ids")
                        if isinstance(candidate.get("evidence_ids"), list)
                        else []
                    )
                ]
            )[:10]
            claim = str(candidates[0].get("claim_summary") or key_label)
            entities = AgentRunner._dedupe_strings(
                [
                    str(entity)
                    for candidate in candidates
                    for entity in (
                        candidate.get("entities")
                        if isinstance(candidate.get("entities"), list)
                        else []
                    )
                ]
            )
            tickers = AgentRunner._dedupe_strings(
                [
                    str(ticker)
                    for candidate in candidates
                    for ticker in (
                        candidate.get("tickers")
                        if isinstance(candidate.get("tickers"), list)
                        else []
                    )
                ]
            )
            topics = AgentRunner._dedupe_strings(
                [
                    str(topic)
                    for candidate in candidates
                    for topic in (
                        candidate.get("topics")
                        if isinstance(candidate.get("topics"), list)
                        else []
                    )
                ]
            )
            if not candidate_ids:
                continue
            cluster_drafts.append(
                {
                    "category": category,
                    "title": AgentRunner._fallback_title(category, key_label, claim),
                    "canonical_claim": claim,
                    "candidate_ids": candidate_ids,
                    "evidence_ids": evidence_ids,
                    "entities": entities[:8],
                    "tickers": tickers[:8],
                    "topics": topics[:8],
                    "metadata": {
                        "deterministic_fallback": True,
                        "fallback_group_key": key_label,
                    },
                }
            )

        return {
            "summary": f"Deterministically grouped {len(candidate_context)} candidates.",
            "reasoning_summary": (
                "Fallback grouped candidates by category and leading entity, ticker, "
                "or topic after AgentScope JSON output could not be repaired."
            ),
            "cluster_drafts": cluster_drafts,
            "metadata": {"deterministic_fallback": True},
        }

    @staticmethod
    def _fallback_writer_payload(
        writing_context: dict[str, Any],
        request_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        selected_clusters = writing_context.get("selected_clusters")
        if not isinstance(selected_clusters, list) or not selected_clusters:
            return None

        sections_by_id: dict[str, dict[str, Any]] = {}
        overview: list[str] = []
        tomorrow_focus: list[str] = []
        for cluster in selected_clusters:
            if not isinstance(cluster, dict):
                continue
            evidence_ids = cluster.get("evidence_ids")
            cluster_id = cluster.get("id")
            category = str(cluster.get("category") or CandidateCategory.OTHER.value)
            if not cluster_id or not isinstance(evidence_ids, list) or not evidence_ids:
                continue
            bucket = str(cluster.get("report_bucket") or AgentRunner._fallback_report_bucket(category))
            section = sections_by_id.setdefault(
                bucket,
                {
                    "section_id": bucket,
                    "title": AgentRunner._fallback_section_title(bucket),
                    "items": [],
                },
            )
            title = str(cluster.get("title") or cluster.get("canonical_claim") or cluster_id)
            claim = str(cluster.get("canonical_claim") or title)
            required_followups = AgentRunner._dedupe_strings(
                [
                    str(item)
                    for item in (
                        cluster.get("required_followups")
                        if isinstance(cluster.get("required_followups"), list)
                        else []
                    )
                    if str(item).strip()
                ]
            )
            missing_evidence = AgentRunner._dedupe_strings(
                [
                    str(item)
                    for item in (
                        cluster.get("missing_evidence")
                        if isinstance(cluster.get("missing_evidence"), list)
                        else []
                    )
                    if str(item).strip()
                ]
            )
            followups = (required_followups or missing_evidence or ["Track source updates."])[:5]
            tomorrow_focus.extend(followups[:2])
            overview.append(title)
            item = {
                "title": title[:180],
                "category": category,
                "status_label": AgentRunner._fallback_status_label(category, cluster),
                "core_information": claim,
                "why_it_matters": AgentRunner._fallback_why_it_matters(cluster),
                "potential_impact": AgentRunner._fallback_potential_impact(cluster),
                "key_data": AgentRunner._fallback_key_data(cluster),
                "tickers": (
                    cluster.get("tickers")
                    if isinstance(cluster.get("tickers"), list)
                    else []
                ),
                "evidence_ids": [str(evidence_id) for evidence_id in evidence_ids],
                "cluster_ids": [str(cluster_id)],
                "followup_points": followups,
                "metadata": {"deterministic_fallback": True},
            }
            if category == CandidateCategory.EARLY_SIGNAL.value:
                item["uncertainty_label"] = "unconfirmed; requires follow-up"
            section["items"].append(item)

        sections = [section for section in sections_by_id.values() if section["items"]]
        if not sections:
            return None

        focus = AgentRunner._dedupe_strings(tomorrow_focus)[:5]
        if not focus:
            focus = ["Review selected clusters for source updates."]
        report_date = str(request_context.get("report_date") or "unknown date")
        return {
            "summary": "Deterministically drafted report from selected clusters.",
            "reasoning_summary": (
                "Fallback report includes every selected cluster with caveats and "
                "source lineage after model JSON could not be parsed."
            ),
            "markdown_preview": None,
            "report_drafts": [
                {
                    "title": f"Connor.ai Daily Intelligence — {report_date}",
                    "sections": sections,
                    "overview_judgments": overview[:3],
                    "tomorrow_focus": focus,
                    "metadata": {"deterministic_fallback": True},
                }
            ],
            "metadata": {"deterministic_fallback": True},
        }

    @staticmethod
    def _fallback_report_bucket(category: str) -> str:
        if category in {
            CandidateCategory.CONFIRMED_EVENT.value,
            CandidateCategory.OFFICIAL_UPDATE.value,
        }:
            return "confirmed_events"
        if category == CandidateCategory.TECH_FINANCE.value:
            return "tech_finance"
        return "early_signals"

    @staticmethod
    def _fallback_section_title(bucket: str) -> str:
        titles = {
            "early_signals": "Early Signals",
            "confirmed_events": "Confirmed Events",
            "tech_finance": "Tech-Finance",
        }
        return titles.get(bucket, bucket.replace("_", " ").title())

    @staticmethod
    def _fallback_status_label(category: str, cluster: dict[str, Any]) -> str:
        policy = str(cluster.get("write_policy") or "")
        if category in {
            CandidateCategory.CONFIRMED_EVENT.value,
            CandidateCategory.OFFICIAL_UPDATE.value,
        }:
            return "Confirmed; details may need follow-up"
        if category == CandidateCategory.TECH_FINANCE.value:
            return "Tech-finance signal; verify extracted figures"
        if policy == "write_with_caveat":
            return "Unconfirmed signal; write with caveat"
        return "Unconfirmed signal"

    @staticmethod
    def _fallback_why_it_matters(cluster: dict[str, Any]) -> str:
        decisions = cluster.get("evaluation_decisions")
        topics = cluster.get("topics")
        parts = []
        if isinstance(decisions, list) and decisions:
            parts.append(f"Evaluator decisions: {', '.join(str(item) for item in decisions)}.")
        if isinstance(topics, list) and topics:
            parts.append(f"Relevant topics: {', '.join(str(item) for item in topics[:5])}.")
        parts.append("Connor selected this cluster for daily intelligence coverage.")
        return " ".join(parts)

    @staticmethod
    def _fallback_potential_impact(cluster: dict[str, Any]) -> str:
        tickers = cluster.get("tickers")
        if isinstance(tickers, list) and tickers:
            return f"Potentially relevant to {', '.join(str(item) for item in tickers)}."
        return "Potential impact depends on confirmation, adoption, or follow-up evidence."

    @staticmethod
    def _fallback_key_data(cluster: dict[str, Any]) -> list[str]:
        values = []
        for key in ("missing_evidence", "required_followups"):
            items = cluster.get(key)
            if isinstance(items, list):
                values.extend(str(item) for item in items if str(item).strip())
        return AgentRunner._dedupe_strings(values)[:5]

    @staticmethod
    def _fallback_title(category: str, key_label: str, claim: str) -> str:
        cleaned_key = key_label.replace("_", " ").strip() or "misc"
        if cleaned_key == "misc":
            return claim[:80]
        return f"{cleaned_key.title()} {category.replace('_', ' ')} cluster"

    @staticmethod
    def _dedupe_strings(values: list[str]) -> list[str]:
        deduped: list[str] = []
        for value in values:
            if value not in deduped:
                deduped.append(value)
        return deduped

    async def _repair_structured_output(
        self,
        *,
        request: AgentRunRequest,
        config: AgentRoleConfig,
        bridge: AgentScopeToolBridge,
        output_text: str | None,
        error: Exception,
    ) -> Msg:
        """Ask the same role to repair malformed or schema-invalid JSON once."""

        self.trace_service.record_event(
            run_id=request.run_id,
            phase=request.phase,
            agent_role=request.agent_role,
            event_type=TraceEventType.AGENT_DECISION,
            status=TraceStatus.STARTED,
            summary=f"{config.display_name} started structured output repair.",
            input_payload={
                "error": str(error),
                "output_excerpt": self._excerpt(output_text),
            },
            metadata={
                "repair_mode": "structured_output_repair",
                "exception_type": type(error).__name__,
            },
        )

        repair_agent = self._create_agent(config, bridge, no_tools=True)
        coro = repair_agent.reply(
            self._build_structured_repair_message(
                request=request,
                config=config,
                bridge=bridge,
                output_text=output_text,
                error=error,
            )
        )
        if config.execution.timeout_seconds is not None:
            response = await asyncio.wait_for(coro, timeout=config.execution.timeout_seconds)
        else:
            response = await coro

        self.trace_service.record_event(
            run_id=request.run_id,
            phase=request.phase,
            agent_role=request.agent_role,
            event_type=TraceEventType.AGENT_DECISION,
            status=TraceStatus.SUCCEEDED,
            summary=f"{config.display_name} completed structured output repair.",
            output_payload={
                "output_preview": (self._extract_text(response) or "")[:500],
            },
            metadata={"repair_mode": "structured_output_repair"},
        )
        return response

    def _create_agent(
        self,
        config: AgentRoleConfig,
        bridge: AgentScopeToolBridge,
        *,
        no_tools: bool = False,
    ) -> Agent:
        allowed_tool_names = [] if no_tools or config.execution.max_tool_calls == 0 else config.allowed_tool_names
        return Agent(
            name=config.role.value,
            system_prompt=config.system_prompt,
            model=self.model_factory(config),
            toolkit=bridge.create_toolkit(allowed_tool_names) if allowed_tool_names else None,
            react_config=ReActConfig(max_iters=config.execution.max_iters, stop_on_reject=True),
        )

    @staticmethod
    def _build_user_message(request: AgentRunRequest, config: AgentRoleConfig) -> Msg:
        no_tools = request.context.get("no_tools", False)
        tool_policy = request.context.get("tool_use_policy", "")

        if no_tools:
            output_rule = (
                "Generate your response directly as a single JSON object matching "
                "required_output_schema. Do NOT call any tools. Use your knowledge "
                "to produce the structured output. Put reasoning only in "
                "reasoning_summary."
            )
            payload = {
                "task": request.task,
                "context": request.context,
                "required_output_schema": config.output_model.model_json_schema(),
                "output_rule": output_rule,
            }
        else:
            output_rule = (
                "Return the final answer as a single JSON object matching "
                "required_output_schema. Put reasoning only in reasoning_summary, "
                "as a concise summary, never as hidden chain-of-thought. "
                f"You may call at most {config.execution.max_tool_calls} tool(s). "
                "After any successful tool returns evidence_ids, stop calling tools "
                "and produce the final JSON. Copy evidence_ids exactly from tool "
                "results; never invent evidence_ids. If tools return no useful "
                "evidence, return followup_queries and leave candidate_drafts empty."
            )
            if tool_policy:
                output_rule = f"{output_rule} TOOL USE POLICY: {tool_policy}"
            payload = {
                "task": request.task,
                "context": request.context,
                "available_tools": config.allowed_tool_names,
                "required_output_schema": config.output_model.model_json_schema(),
                "output_rule": output_rule,
            }

        return UserMsg(
            name="connor_harness",
            content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )

    @staticmethod
    def _build_structured_repair_message(
        *,
        request: AgentRunRequest,
        config: AgentRoleConfig,
        bridge: AgentScopeToolBridge,
        output_text: str | None,
        error: Exception,
    ) -> Msg:
        output_rule = (
            "Your previous answer could not be parsed or validated. Do NOT call "
            "tools. Return exactly one valid JSON object matching "
            "required_output_schema, with no Markdown fences and no commentary. "
            "Do not include fields outside the schema. For long arrays, keep only "
            "the highest-value items needed to satisfy the task and keep each item "
            "compact. Use only IDs present in context, tool_results, or the "
            "previous output excerpt; never invent IDs. Put reasoning only in "
            "reasoning_summary."
        )
        payload = {
            "task": request.task,
            "context": {
                **request.context,
                "no_tools": True,
                "structured_output_repair": True,
            },
            "tool_results": bridge.agent_visible_tool_results(),
            "available_evidence_ids": bridge.executed_evidence_ids(),
            "required_output_schema": config.output_model.model_json_schema(),
            "previous_output_excerpt": AgentRunner._excerpt(output_text),
            "validation_error": str(error),
            "output_rule": output_rule,
        }
        return UserMsg(
            name="connor_harness",
            content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )

    @staticmethod
    def _build_finalization_message(
        request: AgentRunRequest,
        config: AgentRoleConfig,
        bridge: AgentScopeToolBridge,
    ) -> Msg:
        output_rule = (
            "You are in finalization mode after tool exploration. Do NOT call "
            "tools. Return exactly one JSON object matching required_output_schema; "
            "do not wrap it in Markdown. Use only evidence_ids listed in "
            "tool_results. Copy evidence_ids exactly. If tool_results contain no "
            "useful evidence, return followup_queries and leave draft lists empty. "
            "Put reasoning only in reasoning_summary as a concise summary."
        )
        payload = {
            "task": request.task,
            "context": {
                **request.context,
                "no_tools": True,
                "tool_finalization_repair": True,
            },
            "tool_results": bridge.agent_visible_tool_results(),
            "available_evidence_ids": bridge.executed_evidence_ids(),
            "required_output_schema": config.output_model.model_json_schema(),
            "output_rule": output_rule,
        }
        return UserMsg(
            name="connor_harness",
            content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )

    @staticmethod
    def _extract_text(response: Msg) -> str | None:
        text = response.get_text_content()
        return text if text else None

    @staticmethod
    def _extract_structured_payload(response: Msg, output_text: str | None) -> dict[str, Any]:
        if isinstance(response.metadata, dict):
            structured_output = response.metadata.get("structured_output")
            if isinstance(structured_output, dict):
                return structured_output

        if output_text is None:
            raise AgentScopeExecutionError("AgentScope response did not contain text output.")

        return AgentRunner._parse_json_object(output_text)

    @classmethod
    def _normalize_payload_for_model(
        cls,
        model_cls: type[BaseModel],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Move model-produced unknown fields into metadata.extra_fields."""

        if not isinstance(payload, dict):
            return payload

        fields = model_cls.model_fields
        normalized: dict[str, Any] = {}
        extra_fields: dict[str, Any] = {}
        for key, value in payload.items():
            field = fields.get(key)
            if field is None:
                extra_fields[key] = value
                continue
            normalized[key] = cls._normalize_value_for_annotation(field.annotation, value)

        if extra_fields and "metadata" in fields:
            metadata = normalized.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            existing_extra_fields = metadata.get("extra_fields")
            merged_extra_fields = (
                {**existing_extra_fields, **extra_fields}
                if isinstance(existing_extra_fields, dict)
                else extra_fields
            )
            normalized["metadata"] = {
                **metadata,
                "extra_fields": merged_extra_fields,
            }

        return normalized

    @classmethod
    def _repair_payload_with_context(
        cls,
        model_cls: type[BaseModel],
        payload: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if model_cls is WriterOutput:
            return cls._repair_writer_payload_lineage(payload, context)
        if model_cls is ReviewerOutput:
            return cls._repair_reviewer_payload_consistency(payload)
        return payload

    @classmethod
    def _repair_reviewer_payload_consistency(cls, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return payload

        repaired = dict(payload)
        if not str(repaired.get("summary") or "").strip():
            repaired["summary"] = cls._fallback_reviewer_summary(repaired)
        review_drafts = []
        any_revise = False
        synthesized_changes: list[str] = []
        for draft in repaired.get("review_drafts", []):
            if not isinstance(draft, dict):
                continue
            next_draft = dict(draft)
            issues = [
                cls._repair_review_issue_payload(issue)
                for issue in (
                    next_draft.get("issues")
                    if isinstance(next_draft.get("issues"), list)
                    else []
                )
                if isinstance(issue, dict)
            ]
            if issues:
                next_draft["issues"] = issues
            required_changes = (
                next_draft.get("required_changes")
                if isinstance(next_draft.get("required_changes"), list)
                else []
            )
            decision = str(next_draft.get("decision") or "").lower()
            has_changes = bool(issues or required_changes)

            if decision == ReviewDecision.PASS.value and has_changes:
                next_draft["decision"] = ReviewDecision.REVISE.value
                any_revise = True
                metadata = next_draft.get("metadata")
                if not isinstance(metadata, dict):
                    metadata = {}
                next_draft["metadata"] = {
                    **metadata,
                    "normalized_decision_from": ReviewDecision.PASS.value,
                    "normalized_decision_reason": "pass review draft included issues or required changes",
                }
            elif decision == ReviewDecision.REJECT.value and has_changes:
                next_draft["decision"] = ReviewDecision.REVISE.value
                any_revise = True
                metadata = next_draft.get("metadata")
                if not isinstance(metadata, dict):
                    metadata = {}
                next_draft["metadata"] = {
                    **metadata,
                    "normalized_decision_from": ReviewDecision.REJECT.value,
                    "normalized_decision_reason": (
                        "reject review draft included actionable issues or required changes"
                    ),
                }
            elif decision == ReviewDecision.REVISE.value:
                any_revise = True
            elif decision == ReviewDecision.REOPEN_COLLECT.value and not has_changes:
                next_draft["required_changes"] = [
                    "Reviewer requested reopening collection without specific required changes."
                ]
                metadata = next_draft.get("metadata")
                if not isinstance(metadata, dict):
                    metadata = {}
                next_draft["metadata"] = {
                    **metadata,
                    "normalized_decision_from": ReviewDecision.REOPEN_COLLECT.value,
                    "normalized_decision_reason": (
                        "reopen_collect review draft lacked issues or required changes"
                    ),
                }
                has_changes = True

            if next_draft.get("decision") == ReviewDecision.REVISE.value and not required_changes:
                issue_changes = cls._review_issue_change_titles(issues)
                if issue_changes:
                    next_draft["required_changes"] = issue_changes
                    required_changes = issue_changes
            synthesized_changes.extend(str(change) for change in required_changes if str(change).strip())
            review_drafts.append(next_draft)

        if review_drafts:
            repaired["review_drafts"] = review_drafts
        if any_revise:
            if repaired.get("decision") in {
                ReviewDecision.PASS.value,
                ReviewDecision.REJECT.value,
            }:
                repaired["metadata"] = {
                    **(repaired.get("metadata") if isinstance(repaired.get("metadata"), dict) else {}),
                    "normalized_decision_from": repaired.get("decision"),
                    "normalized_decision_reason": (
                        "one or more review drafts require revision"
                    ),
                }
            repaired["decision"] = ReviewDecision.REVISE.value
            if not repaired.get("required_changes") and synthesized_changes:
                repaired["required_changes"] = cls._dedupe_strings(synthesized_changes)
        return repaired

    @staticmethod
    def _fallback_reviewer_summary(payload: dict[str, Any]) -> str:
        decision = str(payload.get("decision") or ReviewDecision.REVISE.value)
        if decision == ReviewDecision.PASS.value:
            return "Reviewer passed the report."
        return "Reviewer requested revisions."

    @classmethod
    def _repair_review_issue_payload(cls, issue: dict[str, Any]) -> dict[str, Any]:
        repaired = dict(issue)
        extra_fields = cls._metadata_extra_fields(repaired)

        title = cls._first_non_empty_string(
            repaired.get("title"),
            repaired.get("summary"),
            repaired.get("issue"),
            repaired.get("problem"),
            repaired.get("required_change"),
            extra_fields.get("title"),
            extra_fields.get("summary"),
            extra_fields.get("issue"),
            extra_fields.get("problem"),
            extra_fields.get("required_change"),
            extra_fields.get("finding"),
        )
        body = cls._first_non_empty_string(
            repaired.get("body"),
            repaired.get("description"),
            repaired.get("details"),
            repaired.get("recommendation"),
            repaired.get("fix"),
            extra_fields.get("body"),
            extra_fields.get("description"),
            extra_fields.get("details"),
            extra_fields.get("recommendation"),
            extra_fields.get("fix"),
            title,
        )
        priority = cls._coerce_review_issue_priority(
            repaired.get("priority", extra_fields.get("priority"))
        )

        if title:
            repaired["title"] = title[:160]
        if body:
            repaired["body"] = body
        repaired["priority"] = priority

        if "metadata" not in repaired or not isinstance(repaired["metadata"], dict):
            repaired["metadata"] = {}
        repaired["metadata"] = {
            **repaired["metadata"],
            "normalized_issue_shape": True,
        }
        return repaired

    @staticmethod
    def _metadata_extra_fields(payload: dict[str, Any]) -> dict[str, Any]:
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            return {}
        extra_fields = metadata.get("extra_fields")
        return extra_fields if isinstance(extra_fields, dict) else {}

    @staticmethod
    def _first_non_empty_string(*values: Any) -> str | None:
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, list):
                joined = "; ".join(str(item).strip() for item in value if str(item).strip())
                if joined:
                    return joined
            if isinstance(value, dict):
                joined = "; ".join(
                    f"{key}: {val}"
                    for key, val in value.items()
                    if str(key).strip() and str(val).strip()
                )
                if joined:
                    return joined
        return None

    @staticmethod
    def _coerce_review_issue_priority(value: Any) -> int:
        if isinstance(value, int):
            return max(0, min(3, value))
        if isinstance(value, float):
            return max(0, min(3, int(value)))
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized.isdigit():
                return max(0, min(3, int(normalized)))
            if normalized in {"critical", "high", "p0", "p1"}:
                return 1
            if normalized in {"medium", "moderate", "p2"}:
                return 2
            if normalized in {"low", "minor", "p3"}:
                return 3
        return 2

    @staticmethod
    def _review_issue_change_titles(issues: list[Any]) -> list[str]:
        changes: list[str] = []
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            title = issue.get("title") or issue.get("body")
            if title:
                changes.append(str(title))
        return AgentRunner._dedupe_strings(changes)

    @classmethod
    def _repair_writer_payload_lineage(
        cls,
        payload: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        writing_context = context.get("writing_context")
        if not isinstance(writing_context, dict):
            return payload
        selected_clusters = writing_context.get("selected_clusters")
        if not isinstance(selected_clusters, list):
            return payload
        evidence_by_cluster = {
            cluster.get("id"): cluster.get("evidence_ids")
            for cluster in selected_clusters
            if isinstance(cluster, dict) and isinstance(cluster.get("evidence_ids"), list)
        }

        repaired = dict(payload)
        report_drafts = []
        for report in repaired.get("report_drafts", []):
            if not isinstance(report, dict):
                continue
            next_report = dict(report)
            sections = []
            for section in next_report.get("sections", []):
                if not isinstance(section, dict):
                    continue
                next_section = dict(section)
                items = []
                for item in next_section.get("items", []):
                    if not isinstance(item, dict):
                        continue
                    next_item = dict(item)
                    cluster_ids = (
                        next_item.get("cluster_ids")
                        if isinstance(next_item.get("cluster_ids"), list)
                        else []
                    )
                    if not cluster_ids:
                        continue
                    evidence_ids = (
                        next_item.get("evidence_ids")
                        if isinstance(next_item.get("evidence_ids"), list)
                        else []
                    )
                    if not evidence_ids:
                        evidence_ids = cls._dedupe_strings(
                            [
                                str(evidence_id)
                                for cluster_id in cluster_ids
                                for evidence_id in (evidence_by_cluster.get(cluster_id) or [])
                            ]
                        )
                        if evidence_ids:
                            metadata = next_item.get("metadata")
                            if not isinstance(metadata, dict):
                                metadata = {}
                            next_item["metadata"] = {
                                **metadata,
                                "repaired_missing_evidence_ids": True,
                            }
                            next_item["evidence_ids"] = evidence_ids
                    if next_item.get("evidence_ids"):
                        items.append(next_item)
                if items:
                    next_section["items"] = items
                    sections.append(next_section)
            if sections:
                next_report["sections"] = sections
                report_drafts.append(next_report)
        repaired["report_drafts"] = report_drafts
        return repaired

    @classmethod
    def _normalize_value_for_annotation(cls, annotation: Any, value: Any) -> Any:
        origin = get_origin(annotation)
        args = get_args(annotation)

        if origin is list and args and isinstance(value, list):
            return [cls._normalize_value_for_annotation(args[0], item) for item in value]

        if origin in {UnionType, getattr(__import__("typing"), "Union")}:
            for arg in args:
                model_cls = cls._model_class_from_annotation(arg)
                if model_cls is not None and isinstance(value, dict):
                    return cls._normalize_payload_for_model(model_cls, value)
            return value

        model_cls = cls._model_class_from_annotation(annotation)
        if model_cls is not None and isinstance(value, dict):
            return cls._normalize_payload_for_model(model_cls, value)

        return value

    @staticmethod
    def _model_class_from_annotation(annotation: Any) -> type[BaseModel] | None:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return annotation
        return None

    @staticmethod
    def _is_react_max_iters_response(output_text: str | None) -> bool:
        if not output_text:
            return False
        return (
            "Executed maximum iterations of reasoning-acting loop" in output_text
            and "without finishing" in output_text
        )

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any]:
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()

        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            start = stripped.find("{")
            end = stripped.rfind("}")
            if start < 0 or end < start:
                snippet = stripped[:200].replace("\n", " ")
                raise AgentScopeExecutionError(
                    f"AgentScope response did not contain a JSON object. "
                    f"Response starts with: {snippet}"
                ) from None
            payload = json.loads(stripped[start : end + 1])

        if not isinstance(payload, dict):
            raise AgentScopeExecutionError("AgentScope response JSON must be an object.")
        return payload

    @staticmethod
    def _excerpt(value: str | None, *, limit: int = 8000) -> str | None:
        if value is None or len(value) <= limit:
            return value
        head_length = limit // 2
        tail_length = limit - head_length
        return (
            value[:head_length]
            + "\n...[truncated for repair prompt]...\n"
            + value[-tail_length:]
        )
