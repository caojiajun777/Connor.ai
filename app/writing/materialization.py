"""Materialize Writer, Reviewer, and Editor outputs into report records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agents.outputs import (
    EditorOutput,
    ReportDraft,
    ReportItemDraft,
    ReviewDraft,
    ReviewIssueDraft,
    ReviewerOutput,
    WriterOutput,
)
from app.agents.schemas import AgentRunResult
from app.core.ids import IdPrefix, deterministic_id, random_id
from app.domain import (
    AgentRole,
    CandidateCategory,
    DailyReport,
    EvidenceMapEntry,
    ObjectType,
    ReportItem,
    ReportSection,
    ReportStatus,
    ReviewDecision,
    ReviewIssue,
    ReviewResult,
    RunPhase,
    RunState,
    TraceEventType,
    TraceStatus,
    WatchlistUpdate,
)
from app.domain.base import utc_now
from app.exceptions import HarnessError
from app.repositories import (
    DailyReportRepository,
    EvidenceRepository,
    EventClusterRepository,
    ReviewIssueRepository,
    ReviewResultRepository,
    RunRepository,
)
from app.services import TraceService


class WritingMaterializationContext(Protocol):
    """Context interface required by WritingOutputMaterializer."""

    session: Session
    trace_service: TraceService
    runs: RunRepository

    def persist_run(self, run: RunState) -> RunState:
        """Persist an updated RunState."""


@dataclass
class WritingMaterializationResult:
    """Domain objects created or updated from one writing-loop agent result."""

    report_ids: list[str] = field(default_factory=list)
    review_result_ids: list[str] = field(default_factory=list)
    review_issue_ids: list[str] = field(default_factory=list)


class WritingOutputMaterializer:
    """Persist Writer, Reviewer, and Editor structured drafts into Connor state."""

    def __init__(self, context: WritingMaterializationContext):
        self.context = context
        self.reports = DailyReportRepository(context.session)
        self.reviews = ReviewResultRepository(context.session)
        self.issues = ReviewIssueRepository(context.session)
        self.evidence = EvidenceRepository(context.session)
        self.clusters = EventClusterRepository(context.session)

    def materialize(
        self,
        *,
        run: RunState,
        phase: RunPhase,
        agent_role: AgentRole,
        result: AgentRunResult,
    ) -> WritingMaterializationResult:
        """Materialize one writing-loop AgentScope result."""

        self.context.session.flush()
        output = result.structured_output
        if isinstance(output, WriterOutput):
            if phase != RunPhase.WRITING or agent_role != AgentRole.WRITER:
                raise HarnessError("WriterOutput can only be materialized in writing phase by writer")
            return self._materialize_report_drafts(
                run=run,
                phase=phase,
                agent_role=agent_role,
                drafts=output.report_drafts,
                edited=False,
            )

        if isinstance(output, ReviewerOutput):
            if phase not in {RunPhase.REVIEWING, RunPhase.FINAL_REVIEW} or agent_role != AgentRole.REVIEWER:
                raise HarnessError(
                    "ReviewerOutput can only be materialized in reviewing/final_review phase by reviewer"
                )
            return self._materialize_review_drafts(
                run=run,
                phase=phase,
                agent_role=agent_role,
                output=output,
            )

        if isinstance(output, EditorOutput):
            if phase != RunPhase.EDITING or agent_role != AgentRole.EDITOR:
                raise HarnessError("EditorOutput can only be materialized in editing phase by editor")
            return self._materialize_report_drafts(
                run=run,
                phase=phase,
                agent_role=agent_role,
                drafts=output.revised_report_drafts,
                edited=True,
            )

        return WritingMaterializationResult()

    def _materialize_report_drafts(
        self,
        *,
        run: RunState,
        phase: RunPhase,
        agent_role: AgentRole,
        drafts: list[ReportDraft],
        edited: bool,
    ) -> WritingMaterializationResult:
        materialized = WritingMaterializationResult()
        if not drafts:
            return materialized

        for draft in drafts:
            report = self._create_or_update_report(
                run=run,
                phase=phase,
                agent_role=agent_role,
                draft=draft,
                edited=edited,
            )
            self.reports.add(report)
            materialized.report_ids.append(report.id)
            trace_event = self.context.trace_service.record_event(
                run_id=run.id,
                phase=phase,
                agent_role=agent_role,
                event_type=TraceEventType.REPORT_EDITED if edited else TraceEventType.REPORT_DRAFTED,
                status=TraceStatus.SUCCEEDED,
                summary=(
                    f"{agent_role.value} materialized revised report: {report.id}"
                    if edited
                    else f"{agent_role.value} materialized draft report: {report.id}"
                ),
                created_objects=[report],
                output_payload=report.model_dump(mode="json"),
                metadata={
                    "report_id": report.id,
                    "materialized_by": "WritingOutputMaterializer",
                    "edited": edited,
                },
            )
            report = self._append_report_trace(report, trace_event.id)
            self.reports.add(report)

        self._update_run_report_metadata(run.id, agent_role, phase, materialized.report_ids)
        self.context.session.flush()
        return materialized

    def _materialize_review_drafts(
        self,
        *,
        run: RunState,
        phase: RunPhase,
        agent_role: AgentRole,
        output: ReviewerOutput,
    ) -> WritingMaterializationResult:
        materialized = WritingMaterializationResult()
        if not output.review_drafts:
            return materialized

        for draft in output.review_drafts:
            report = self._report_for_review(run.id, draft.report_id)
            review, issues = self._create_review(run=run, phase=phase, report=report, draft=draft)
            for issue in issues:
                self.issues.add(issue)
                materialized.review_issue_ids.append(issue.id)
            self.reviews.add(review)
            materialized.review_result_ids.append(review.id)
            self.reports.add(self._update_report_after_review(report, review))
            self.context.trace_service.record_event(
                run_id=run.id,
                phase=phase,
                agent_role=agent_role,
                event_type=TraceEventType.REVIEW_COMPLETED,
                status=TraceStatus.SUCCEEDED,
                summary=f"Reviewer materialized review: {review.decision.value}",
                reasoning_summary=review.reasoning_summary,
                created_objects=[review],
                output_payload=review.model_dump(mode="json"),
                metadata={
                    "report_id": report.id,
                    "review_result_id": review.id,
                    "decision": review.decision.value,
                    "materialized_by": "WritingOutputMaterializer",
                },
            )

        self._update_run_review_metadata(run.id, materialized.review_result_ids)
        self.context.session.flush()
        return materialized

    def _create_or_update_report(
        self,
        *,
        run: RunState,
        phase: RunPhase,
        agent_role: AgentRole,
        draft: ReportDraft,
        edited: bool,
    ) -> DailyReport:
        existing = self._existing_report_for_draft(run.id, draft, edited)
        report_id = existing.id if existing is not None else self._new_report_id(run, draft, agent_role)
        sections = [self._section_from_draft(run.id, section) for section in draft.sections]
        evidence_map = self._evidence_map_for_sections(run.id, sections)
        watchlist_updates = self._watchlist_updates_for_report(
            run_id=run.id,
            phase=phase,
            agent_role=agent_role,
            sections=sections,
            draft=draft,
        )
        trace_timeline_ids = [event.id for event in self.context.runs.get_full_state(run.id).trace_events]
        metadata = {
            **(existing.metadata if existing is not None else {}),
            **draft.metadata,
            "overview_judgments": draft.overview_judgments,
            "tomorrow_focus": draft.tomorrow_focus,
            "materialized_by": "WritingOutputMaterializer",
            "source_agent_role": agent_role.value,
            "source_phase": phase.value,
        }
        full_json = self._full_json(
            run=run,
            title=draft.title,
            sections=sections,
            evidence_map=evidence_map,
            watchlist_updates=watchlist_updates,
            trace_timeline_ids=trace_timeline_ids,
            overview_judgments=draft.overview_judgments,
            tomorrow_focus=draft.tomorrow_focus,
        )
        full_markdown = draft.full_markdown or self._render_markdown(
            run=run,
            title=draft.title,
            sections=sections,
            watchlist_updates=watchlist_updates,
            overview_judgments=draft.overview_judgments,
            tomorrow_focus=draft.tomorrow_focus,
        )
        now = utc_now()
        return DailyReport(
            id=report_id,
            run_id=run.id,
            report_date=run.report_date,
            title=draft.title,
            status=ReportStatus.DRAFT,
            full_markdown=full_markdown,
            full_json=full_json,
            sections=sections,
            evidence_map=evidence_map,
            watchlist_updates=watchlist_updates,
            trace_timeline_ids=trace_timeline_ids,
            review_result_ids=existing.review_result_ids if existing is not None else [],
            quality_score=draft.quality_score,
            metadata=metadata,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now if existing is not None else None,
        )

    def _section_from_draft(self, run_id: str, draft) -> ReportSection:
        return ReportSection(
            section_id=draft.section_id,
            title=draft.title,
            items=[self._item_from_draft(run_id, item) for item in draft.items],
        )

    def _item_from_draft(self, run_id: str, draft: ReportItemDraft) -> ReportItem:
        draft = self._normalize_item_category_from_clusters(run_id, draft)
        self._validate_item_lineage(run_id, draft)
        item_id = draft.item_id or deterministic_id(
            "item",
            {
                "run_id": run_id,
                "title": draft.title,
                "cluster_ids": draft.cluster_ids,
                "evidence_ids": draft.evidence_ids,
            },
            length=16,
        )
        return ReportItem(
            item_id=item_id,
            title=draft.title,
            category=draft.category,
            status_label=draft.status_label,
            core_information=draft.core_information,
            why_it_matters=draft.why_it_matters,
            potential_impact=draft.potential_impact,
            key_data=draft.key_data,
            tickers=draft.tickers,
            evidence_ids=draft.evidence_ids,
            cluster_ids=draft.cluster_ids,
            followup_points=draft.followup_points,
            uncertainty_label=draft.uncertainty_label,
        )

    def _normalize_item_category_from_clusters(
        self,
        run_id: str,
        draft: ReportItemDraft,
    ) -> ReportItemDraft:
        clusters = []
        for cluster_id in draft.cluster_ids:
            try:
                cluster = self.clusters.require(cluster_id)
            except LookupError as exc:
                raise HarnessError(str(exc)) from exc
            if cluster.run_id != run_id:
                raise HarnessError(f"report item cluster {cluster_id} does not belong to run {run_id}")
            clusters.append(cluster)
        categories = {cluster.category for cluster in clusters}
        if len(categories) == 1:
            category = next(iter(categories))
            if category != draft.category:
                return draft.model_copy(update={"category": category})
        return draft

    def _validate_item_lineage(self, run_id: str, draft: ReportItemDraft) -> None:
        clusters = []
        cluster_evidence_ids: set[str] = set()
        for cluster_id in draft.cluster_ids:
            try:
                cluster = self.clusters.require(cluster_id)
            except LookupError as exc:
                raise HarnessError(str(exc)) from exc
            if cluster.run_id != run_id:
                raise HarnessError(f"report item cluster {cluster_id} does not belong to run {run_id}")
            if cluster.category != draft.category:
                raise HarnessError(
                    f"report item {draft.title} category does not match cluster {cluster_id}"
                )
            clusters.append(cluster)
            cluster_evidence_ids.update(cluster.evidence_ids)

        for evidence_id in draft.evidence_ids:
            try:
                evidence = self.evidence.require(evidence_id)
            except LookupError as exc:
                raise HarnessError(str(exc)) from exc
            if evidence.run_id != run_id:
                raise HarnessError(f"report item evidence {evidence_id} does not belong to run {run_id}")
            if clusters and evidence_id not in cluster_evidence_ids:
                raise HarnessError(
                    f"report item evidence {evidence_id} is not linked to its cited clusters"
                )

    def _evidence_map_for_sections(
        self,
        run_id: str,
        sections: list[ReportSection],
    ) -> list[EvidenceMapEntry]:
        entries: list[EvidenceMapEntry] = []
        for section in sections:
            for item in section.items:
                entries.append(
                    EvidenceMapEntry(
                        report_item_id=item.item_id,
                        evidence_ids=item.evidence_ids,
                        cluster_ids=item.cluster_ids,
                        trace_event_ids=self._trace_ids_for_item(
                            run_id=run_id,
                            evidence_ids=item.evidence_ids,
                            cluster_ids=item.cluster_ids,
                        ),
                    )
                )
        return entries

    def _trace_ids_for_item(
        self,
        *,
        run_id: str,
        evidence_ids: list[str],
        cluster_ids: list[str],
    ) -> list[str]:
        object_ids = set(evidence_ids) | set(cluster_ids)
        trace_ids: list[str] = []
        for event in self.context.runs.get_full_state(run_id).trace_events:
            if event.metadata.get("cluster_id") in cluster_ids:
                trace_ids.append(event.id)
                continue
            for ref in event.created_object_refs:
                if ref.object_id in object_ids and ref.object_type in {
                    ObjectType.EVIDENCE,
                    ObjectType.CLUSTER,
                    ObjectType.EVALUATION,
                }:
                    trace_ids.append(event.id)
                    break
        return self._dedupe(trace_ids)

    def _watchlist_updates_for_report(
        self,
        *,
        run_id: str,
        phase: RunPhase,
        agent_role: AgentRole,
        sections: list[ReportSection],
        draft: ReportDraft,
    ) -> list[WatchlistUpdate]:
        if draft.watchlist_updates:
            normalized_updates, normalized_count, skipped_count = (
                self._watchlist_updates_from_draft(run_id, draft.watchlist_updates)
            )
            if normalized_count or skipped_count:
                self.context.trace_service.record_event(
                    run_id=run_id,
                    phase=phase,
                    agent_role=agent_role,
                    event_type=TraceEventType.AGENT_DECISION,
                    status=TraceStatus.SUCCEEDED,
                    summary="Writing materializer normalized draft watchlist updates.",
                    reasoning_summary=(
                        "The writer returned watchlist update fields in watchlist-item "
                        "shape; materialization mapped them into report update shape."
                    ),
                    metadata={
                        "normalized_count": normalized_count,
                        "skipped_count": skipped_count,
                        "materialized_by": "WritingOutputMaterializer",
                    },
                )
            if normalized_updates:
                return normalized_updates

        cluster_ids = {
            cluster_id
            for section in sections
            for item in section.items
            for cluster_id in item.cluster_ids
        }
        updates: list[WatchlistUpdate] = []
        for item in self.context.runs.get_full_state(run_id).watchlist:
            if not cluster_ids.intersection(item.cluster_ids):
                continue
            updates.append(
                WatchlistUpdate(
                    watchlist_id=item.id,
                    topic=item.topic,
                    current_status=item.status.value,
                    new_developments=[entry.summary for entry in item.history[-3:]],
                    next_watch=item.open_questions or item.reactivation_rules,
                    evidence_ids=item.evidence_ids,
                )
            )
        return updates

    def _watchlist_updates_from_draft(
        self,
        run_id: str,
        raw_updates: list[dict],
    ) -> tuple[list[WatchlistUpdate], int, int]:
        full_state = self.context.runs.get_full_state(run_id)
        watchlist_by_id = {item.id: item for item in full_state.watchlist}

        updates: list[WatchlistUpdate] = []
        normalized_count = 0
        skipped_count = 0
        for raw_update in raw_updates:
            if not isinstance(raw_update, dict):
                skipped_count += 1
                continue
            try:
                updates.append(WatchlistUpdate.model_validate(raw_update))
                continue
            except ValidationError:
                pass

            normalized = self._normalize_watchlist_update(raw_update, watchlist_by_id)
            if normalized is None:
                skipped_count += 1
                continue
            try:
                updates.append(WatchlistUpdate.model_validate(normalized))
                normalized_count += 1
            except ValidationError:
                skipped_count += 1
        return updates, normalized_count, skipped_count

    @staticmethod
    def _normalize_watchlist_update(
        raw_update: dict,
        watchlist_by_id: dict[str, object],
    ) -> dict | None:
        watchlist_id = raw_update.get("watchlist_id") or raw_update.get("id")
        if not isinstance(watchlist_id, str) or not watchlist_id.strip():
            return None

        existing = watchlist_by_id.get(watchlist_id)
        existing_topic = getattr(existing, "topic", None)
        existing_status = getattr(getattr(existing, "status", None), "value", None)
        existing_evidence_ids = getattr(existing, "evidence_ids", None)
        existing_open_questions = getattr(existing, "open_questions", None)
        existing_reactivation_rules = getattr(existing, "reactivation_rules", None)

        topic = (
            raw_update.get("topic")
            or raw_update.get("title")
            or raw_update.get("thesis")
            or existing_topic
        )
        current_status = (
            raw_update.get("current_status")
            or raw_update.get("status")
            or existing_status
            or "active"
        )
        new_developments = WritingOutputMaterializer._string_list(
            raw_update.get("new_developments")
            or raw_update.get("developments")
            or raw_update.get("today_new")
            or raw_update.get("thesis")
        )
        next_watch = WritingOutputMaterializer._string_list(
            raw_update.get("next_watch")
            or raw_update.get("open_questions")
            or raw_update.get("followup_points")
            or existing_open_questions
            or existing_reactivation_rules
        )
        evidence_ids = WritingOutputMaterializer._string_list(
            raw_update.get("evidence_ids") or existing_evidence_ids
        )

        return {
            "watchlist_id": watchlist_id,
            "topic": topic,
            "current_status": current_status,
            "new_developments": new_developments,
            "next_watch": next_watch,
            "evidence_ids": evidence_ids,
        }

    @staticmethod
    def _string_list(value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item is not None and str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value]
        return []

    def _create_review(
        self,
        *,
        run: RunState,
        phase: RunPhase,
        report: DailyReport,
        draft: ReviewDraft,
    ) -> tuple[ReviewResult, list[ReviewIssue]]:
        review_id = draft.review_result_id or random_id(
            IdPrefix.REVIEW,
            parts=[run.id, report.id, phase.value],
            length=16,
        )
        decision = draft.decision
        issue_drafts = list(draft.issues)
        required_changes = list(draft.required_changes)
        guard_issues = self._early_signal_fact_issues(report)
        if decision == ReviewDecision.PASS and guard_issues:
            decision = ReviewDecision.REVISE
            issue_drafts.extend(guard_issues)
            required_changes.extend(issue.title for issue in guard_issues)

        issues = [
            self._issue_from_draft(run=run, report=report, review_id=review_id, draft=issue)
            for issue in issue_drafts
        ]
        review = ReviewResult(
            id=review_id,
            run_id=run.id,
            report_id=report.id,
            reviewer_agent=AgentRole.REVIEWER,
            decision=decision,
            issues=issues,
            required_changes=self._dedupe(required_changes),
            reasoning_summary=(
                "Deterministic uncertainty guard converted pass to revise."
                if draft.decision == ReviewDecision.PASS and decision == ReviewDecision.REVISE
                else draft.reasoning_summary
            ),
            metadata={
                **draft.metadata,
                "materialized_by": "WritingOutputMaterializer",
                "source_decision": draft.decision.value,
            },
            created_at=utc_now(),
        )
        return review, issues

    def _issue_from_draft(
        self,
        *,
        run: RunState,
        report: DailyReport,
        review_id: str,
        draft: ReviewIssueDraft,
    ) -> ReviewIssue:
        return ReviewIssue(
            id=random_id(IdPrefix.ISSUE, parts=[run.id, report.id], length=16),
            run_id=run.id,
            report_id=report.id,
            priority=draft.priority,
            title=draft.title,
            body=draft.body,
            report_item_id=draft.report_item_id,
            evidence_ids=draft.evidence_ids,
            metadata={
                **draft.metadata,
                "review_result_id": review_id,
                "materialized_by": "WritingOutputMaterializer",
            },
            created_at=utc_now(),
        )

    def _early_signal_fact_issues(self, report: DailyReport) -> list[ReviewIssueDraft]:
        issues: list[ReviewIssueDraft] = []
        for section in report.sections:
            for item in section.items:
                if item.category != CandidateCategory.EARLY_SIGNAL:
                    continue
                if self._contains_confirmed_fact_language(
                    item.status_label
                ) or self._contains_confirmed_fact_language(item.core_information):
                    issues.append(
                        ReviewIssueDraft(
                            priority=1,
                            title="Early signal is written with confirmed-fact language",
                            body=(
                                "Early Signals must stay explicitly uncertain; revise status and "
                                "core wording so the item is not framed as officially confirmed."
                            ),
                            report_item_id=item.item_id,
                            evidence_ids=item.evidence_ids,
                            metadata={"deterministic_guard": "early_signal_fact_language"},
                        )
                    )
        return issues

    @staticmethod
    def _contains_confirmed_fact_language(text: str) -> bool:
        normalized = text.strip().lower()
        uncertainty_markers = {
            # English
            "unconfirmed",
            "not confirmed",
            "not yet confirmed",
            "rumor",
            "reported",
            "signal",
            # Chinese
            "未确认",
            "尚未确认",
            "灰度",
            # Japanese
            "未確認",
            "確認されていない",
            "噂",
            # Korean
            "미확인",
            "확인되지 않음",
            "루머",
        }
        if any(marker in normalized for marker in uncertainty_markers):
            return False
        fact_markers = {
            # English
            "confirmed",
            "officially confirmed",
            "has launched",
            "has released",
            # Chinese
            "已确认",
            "正式确认",
            "已经发布",
            "事实",
            # Japanese
            "確認済み",
            "正式に確認",
            "リリース済み",
            # Korean
            "확인됨",
            "공식 확인",
            "출시됨",
        }
        return any(marker in normalized for marker in fact_markers)

    def _update_report_after_review(self, report: DailyReport, review: ReviewResult) -> DailyReport:
        status = ReportStatus.UNDER_REVIEW
        if review.decision == ReviewDecision.REVISE:
            status = ReportStatus.NEEDS_REVISION
        if review.decision == ReviewDecision.REJECT:
            status = ReportStatus.FAILED
        return report.model_copy(
            update={
                "status": status,
                "review_result_ids": self._dedupe(report.review_result_ids + [review.id]),
                "updated_at": utc_now(),
            }
        )

    def _existing_report_for_draft(
        self,
        run_id: str,
        draft: ReportDraft,
        edited: bool,
    ) -> DailyReport | None:
        if draft.report_id:
            report = self.reports.get(draft.report_id)
            if report is not None and report.run_id != run_id:
                raise HarnessError(f"report {draft.report_id} does not belong to run {run_id}")
            return report
        if edited:
            return self._latest_report(run_id)
        return None

    def _report_for_review(self, run_id: str, report_id: str | None) -> DailyReport:
        if report_id:
            try:
                report = self.reports.require(report_id)
            except LookupError as exc:
                raise HarnessError(str(exc)) from exc
            if report.run_id != run_id:
                raise HarnessError(f"report {report_id} does not belong to run {run_id}")
            return report
        report = self._latest_report(run_id)
        if report is None:
            raise HarnessError("review materialization requires an existing report")
        return report

    def _latest_report(self, run_id: str) -> DailyReport | None:
        reports = self.reports.list_by_run(run_id)
        if not reports:
            return None
        return sorted(reports, key=lambda report: report.created_at)[-1]

    def _new_report_id(
        self,
        run: RunState,
        draft: ReportDraft,
        agent_role: AgentRole,
    ) -> str:
        return draft.report_id or deterministic_id(
            IdPrefix.REPORT,
            {
                "run_id": run.id,
                "report_date": run.report_date.isoformat(),
                "writing_round": run.loop_counters.writing_rounds,
                "agent_role": agent_role.value,
            },
            length=16,
        )

    def _update_run_report_metadata(
        self,
        run_id: str,
        agent_role: AgentRole,
        phase: RunPhase,
        report_ids: list[str],
    ) -> None:
        if not report_ids:
            return
        run = self.context.runs.require(run_id)
        previous = run.metadata.get("writing_materialization", [])
        if not isinstance(previous, list):
            previous = [previous]
        updated = run.model_copy(
            update={
                "report_id": report_ids[-1],
                "metadata": {
                    **run.metadata,
                    "writing_materialization": [
                        *previous,
                        {
                            "agent_role": agent_role.value,
                            "phase": phase.value,
                            "report_ids": report_ids,
                        },
                    ],
                },
            }
        )
        self.context.persist_run(updated)

    def _update_run_review_metadata(self, run_id: str, review_result_ids: list[str]) -> None:
        if not review_result_ids:
            return
        run = self.context.runs.require(run_id)
        previous = run.metadata.get("review_materialization", [])
        if not isinstance(previous, list):
            previous = [previous]
        updated = run.model_copy(
            update={
                "metadata": {
                    **run.metadata,
                    "review_materialization": [
                        *previous,
                        {"review_result_ids": review_result_ids},
                    ],
                },
            }
        )
        self.context.persist_run(updated)

    @staticmethod
    def _full_json(
        *,
        run: RunState,
        title: str,
        sections: list[ReportSection],
        evidence_map: list[EvidenceMapEntry],
        watchlist_updates: list[WatchlistUpdate],
        trace_timeline_ids: list[str],
        overview_judgments: list[str],
        tomorrow_focus: list[str],
    ) -> dict:
        return {
            "title": title,
            "report_date": run.report_date.isoformat(),
            "overview_judgments": overview_judgments,
            "statistics": {
                "section_count": len(sections),
                "item_count": sum(len(section.items) for section in sections),
                "watchlist_update_count": len(watchlist_updates),
                "trace_event_count": len(trace_timeline_ids),
            },
            "sections": [section.model_dump(mode="json") for section in sections],
            "evidence_map": [entry.model_dump(mode="json") for entry in evidence_map],
            "watchlist_updates": [update.model_dump(mode="json") for update in watchlist_updates],
            "trace_timeline_ids": trace_timeline_ids,
            "tomorrow_focus": tomorrow_focus,
        }

    @staticmethod
    def _append_report_trace(report: DailyReport, trace_event_id: str) -> DailyReport:
        trace_timeline_ids = WritingOutputMaterializer._dedupe(
            report.trace_timeline_ids + [trace_event_id]
        )
        full_json = {
            **report.full_json,
            "trace_timeline_ids": trace_timeline_ids,
            "statistics": {
                **report.full_json.get("statistics", {}),
                "trace_event_count": len(trace_timeline_ids),
            },
        }
        return report.model_copy(
            update={
                "trace_timeline_ids": trace_timeline_ids,
                "full_json": full_json,
                "updated_at": utc_now(),
            }
        )

    @staticmethod
    def _render_markdown(
        *,
        run: RunState,
        title: str,
        sections: list[ReportSection],
        watchlist_updates: list[WatchlistUpdate],
        overview_judgments: list[str],
        tomorrow_focus: list[str],
    ) -> str:
        lines = [
            f"# {title}",
            f"日期：{run.report_date.isoformat()}",
            "",
            "## 0. 今日总览",
        ]
        if overview_judgments:
            lines.extend(f"- {judgment}" for judgment in overview_judgments[:3])
        else:
            lines.append("- 今日报告由 Connor.ai 写作循环生成。")
        lines.append(
            f"- 今日信息结构统计：{sum(len(section.items) for section in sections)} 条入选信息，"
            f"{len(watchlist_updates)} 条 Watchlist 更新。"
        )

        for index, section in enumerate(sections, start=1):
            lines.extend(["", f"## {index}. {section.title}"])
            if not section.items:
                lines.append("- 今日无新增。")
                continue
            for item in section.items:
                lines.extend(
                    [
                        f"### {item.title}",
                        f"- 状态：{item.status_label}",
                        f"- 核心信息：{item.core_information}",
                        f"- 为什么值得看：{item.why_it_matters}",
                    ]
                )
                if item.potential_impact:
                    lines.append(f"- 潜在影响：{item.potential_impact}")
                if item.key_data:
                    lines.append(f"- 关键数据：{'；'.join(item.key_data)}")
                if item.tickers:
                    lines.append(f"- 相关 ticker：{', '.join(item.tickers)}")
                if item.uncertainty_label:
                    lines.append(f"- 不确定性：{item.uncertainty_label}")
                if item.followup_points:
                    lines.append(f"- 后续追踪点：{'；'.join(item.followup_points)}")

        lines.extend(["", "## 4. 持续追踪 Watchlist"])
        if watchlist_updates:
            for update in watchlist_updates:
                lines.extend(
                    [
                        f"### {update.topic}",
                        f"- 当前状态：{update.current_status}",
                        f"- 今天的新进展：{'；'.join(update.new_developments) if update.new_developments else '无新增。'}",
                        f"- 下一步看什么：{'；'.join(update.next_watch) if update.next_watch else '等待新证据。'}",
                    ]
                )
        else:
            lines.append("- 今日无 Watchlist 更新。")

        lines.extend(["", "## 5. 明日重点关注"])
        if tomorrow_focus:
            lines.extend(f"- {item}" for item in tomorrow_focus[:5])
        else:
            lines.append("- 跟踪今日入选事件的官方确认、代码变化和市场影响。")
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        deduped: list[str] = []
        for value in values:
            if value not in deduped:
                deduped.append(value)
        return deduped
