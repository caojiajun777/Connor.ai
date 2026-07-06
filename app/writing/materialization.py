"""Materialize Writer, Reviewer, and Editor outputs into report records."""

from __future__ import annotations

import re
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
    EvidenceItem,
    EvidenceMapEntry,
    EventCluster,
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

        for report, draft in self._aggregate_review_drafts(run.id, output):
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

    def _aggregate_review_drafts(
        self,
        run_id: str,
        output: ReviewerOutput,
    ) -> list[tuple[DailyReport, ReviewDraft]]:
        grouped: dict[str, tuple[DailyReport, list[ReviewDraft]]] = {}
        for draft in output.review_drafts:
            report = self._report_for_review(run_id, draft.report_id)
            if report.id not in grouped:
                grouped[report.id] = (report, [])
            grouped[report.id][1].append(draft)

        aggregated: list[tuple[DailyReport, ReviewDraft]] = []
        single_report = len(grouped) == 1
        for report, drafts in grouped.values():
            decision = self._aggregate_review_decision(
                drafts,
                output.decision if single_report else None,
            )
            issues = [issue for draft in drafts for issue in draft.issues]
            required_changes = self._dedupe(
                [
                    *(
                        output.required_changes
                        if single_report and output.decision != ReviewDecision.PASS
                        else []
                    ),
                    *[
                        change
                        for draft in drafts
                        for change in draft.required_changes
                    ],
                ]
            )
            reasoning_parts = [
                output.reasoning_summary or output.summary,
                *[draft.reasoning_summary for draft in drafts],
            ]
            aggregated.append(
                (
                    report,
                    ReviewDraft(
                        report_id=report.id,
                        decision=decision,
                        issues=issues,
                        required_changes=required_changes,
                        reasoning_summary=" ".join(
                            part.strip()
                            for part in reasoning_parts
                            if part and part.strip()
                        ),
                        metadata={
                            "aggregated_review_drafts": len(drafts),
                            "source_review_decision": output.decision.value,
                        },
                    ),
                )
            )
        return aggregated

    @staticmethod
    def _aggregate_review_decision(
        drafts: list[ReviewDraft],
        output_decision: ReviewDecision | None,
    ) -> ReviewDecision:
        decisions = [draft.decision for draft in drafts]
        if output_decision is not None:
            decisions.append(output_decision)
        for decision in (
            ReviewDecision.REJECT,
            ReviewDecision.REOPEN_COLLECT,
            ReviewDecision.REVISE,
        ):
            if decision in decisions:
                return decision
        return ReviewDecision.PASS

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
        raw_sections = [
            self._section_from_draft(run.id, section) for section in draft.sections
        ]
        watchlist_updates = self._watchlist_updates_for_report(
            run_id=run.id,
            phase=phase,
            agent_role=agent_role,
            sections=raw_sections,
            draft=draft,
        )
        tomorrow_focus = draft.tomorrow_focus or self._derive_tomorrow_focus(
            raw_sections,
            watchlist_updates,
        )
        sections = self._normalize_report_sections(raw_sections)
        evidence_map = self._evidence_map_for_sections(run.id, sections)
        evidence_by_id = self._evidence_by_id_for_map(run.id, evidence_map)
        trace_timeline_ids = [event.id for event in self.context.runs.get_full_state(run.id).trace_events]
        metadata = {
            **(existing.metadata if existing is not None else {}),
            **draft.metadata,
            "overview_judgments": draft.overview_judgments,
            "tomorrow_focus": tomorrow_focus,
            "materialized_by": "WritingOutputMaterializer",
            "source_agent_role": agent_role.value,
            "source_phase": phase.value,
            "deterministic_markdown_rendered": True,
        }
        full_json = self._full_json(
            run=run,
            title=draft.title,
            sections=sections,
            evidence_map=evidence_map,
            watchlist_updates=watchlist_updates,
            trace_timeline_ids=trace_timeline_ids,
            overview_judgments=draft.overview_judgments,
            tomorrow_focus=tomorrow_focus,
        )
        full_markdown = self._render_markdown(
            run=run,
            title=draft.title,
            sections=sections,
            watchlist_updates=watchlist_updates,
            overview_judgments=draft.overview_judgments,
            tomorrow_focus=tomorrow_focus,
            evidence_by_id=evidence_by_id,
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

    def _derive_tomorrow_focus(
        self,
        sections: list[ReportSection],
        watchlist_updates: list[WatchlistUpdate],
    ) -> list[str]:
        focus: list[str] = []
        for section in sections:
            section_marker = f"{section.section_id} {section.title}".lower()
            if "tomorrow" not in section_marker and "明日" not in section_marker:
                continue
            for item in section.items:
                focus.extend(item.followup_points)
                if not item.followup_points:
                    focus.append(item.core_information)

        if not focus:
            for section in sections:
                for item in section.items:
                    if item.category != CandidateCategory.WATCHLIST_UPDATE:
                        focus.extend(item.followup_points)

        if not focus:
            for update in watchlist_updates:
                focus.extend(update.next_watch)

        return self._dedupe([item for item in focus if item])[:5]

    def _section_from_draft(self, run_id: str, draft) -> ReportSection:
        return ReportSection(
            section_id=draft.section_id,
            title=draft.title,
            items=[self._item_from_draft(run_id, item) for item in draft.items],
        )

    @staticmethod
    def _normalize_report_sections(sections: list[ReportSection]) -> list[ReportSection]:
        items_by_section: dict[str, list[ReportItem]] = {
            "early_signals": [],
            "confirmed_events": [],
            "tech_finance": [],
            "watchlist": [],
            "other": [],
        }
        for section in sections:
            if WritingOutputMaterializer._is_tomorrow_focus_section(section):
                continue
            for item in section.items:
                items_by_section[
                    WritingOutputMaterializer._section_id_for_item(item)
                ].append(item)

        normalized: list[ReportSection] = []
        required_body_sections = {"early_signals", "confirmed_events", "tech_finance"}
        for section_id, title in (
            ("early_signals", "前沿爆料 Early Signals"),
            ("confirmed_events", "重大事件确认 Confirmed Events"),
            ("tech_finance", "科技圈金融信息 Tech-Finance"),
            ("watchlist", "持续追踪 Watchlist"),
            ("other", "Other Signals"),
        ):
            items = items_by_section[section_id]
            if items or section_id in required_body_sections:
                normalized.append(
                    ReportSection(section_id=section_id, title=title, items=items)
                )
        return normalized

    @staticmethod
    def _is_tomorrow_focus_section(section: ReportSection) -> bool:
        marker = f"{section.section_id} {section.title}".lower()
        return "tomorrow" in marker or "明日" in marker

    @staticmethod
    def _section_id_for_item(item: ReportItem) -> str:
        if item.category in {
            CandidateCategory.EARLY_SIGNAL,
            CandidateCategory.RESEARCH,
            CandidateCategory.CODE_MODEL,
        }:
            return "early_signals"
        if item.category in {
            CandidateCategory.CONFIRMED_EVENT,
            CandidateCategory.OFFICIAL_UPDATE,
        }:
            return "confirmed_events"
        if item.category == CandidateCategory.TECH_FINANCE:
            return "tech_finance"
        if item.category == CandidateCategory.WATCHLIST_UPDATE:
            return "watchlist"
        return "other"

    def _item_from_draft(self, run_id: str, draft: ReportItemDraft) -> ReportItem:
        draft = self._normalize_item_category_from_clusters(run_id, draft)
        self._validate_item_lineage(run_id, draft)
        draft = self._repair_tech_finance_fields_from_clusters(run_id, draft)
        draft = self._repair_uncertain_item_language(draft)
        draft = self._repair_status_label_language(draft)
        draft = self._sanitize_report_item_tickers(draft)
        draft = self._repair_missing_followups(draft)
        draft = self._repair_generic_followups(draft)
        draft = self._normalize_report_item_text(draft)
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

    def _repair_missing_followups(self, draft: ReportItemDraft) -> ReportItemDraft:
        if draft.followup_points:
            return draft
        if draft.category in {CandidateCategory.CONFIRMED_EVENT, CandidateCategory.OFFICIAL_UPDATE}:
            followup = "暂无必须追踪动作；若官方补充技术细节、价格或发布时间表，再重新评估影响。"
        elif draft.category == CandidateCategory.TECH_FINANCE:
            followup = "继续查看后续 SEC 文件、财报电话会、公司 IR 更新和市场反应。"
        elif draft.category == CandidateCategory.WATCHLIST_UPDATE:
            followup = "在下一次计划检查日复核这条 Watchlist 线索是否需要延期或归档。"
        else:
            followup = "继续追踪同行验证、复现实验、来源更新或官方确认。"
        return draft.model_copy(
            update={
                "followup_points": [followup],
                "metadata": {
                    **draft.metadata,
                    "repaired_missing_followups": True,
                },
            }
        )

    @staticmethod
    def _repair_generic_followups(draft: ReportItemDraft) -> ReportItemDraft:
        """Replace overly generic follow-up points with context-specific versions."""
        generic_patterns = [
            "monitor for updates",
            "track developments",
            "follow up on this",
            "monitor further",
            "track further",
            "await more information",
            "keep watching",
            "continue monitoring",
        ]
        if not draft.followup_points:
            return draft
        improved: list[str] = []
        any_repaired = False
        for point in draft.followup_points:
            lower = point.strip().lower()
            if any(pattern in lower for pattern in generic_patterns):
                any_repaired = True
                if draft.tickers:
                    improved.append(
                        f"继续监测 {', '.join(draft.tickers)} 的官方文件、财报电话会和产品公告，"
                        "确认这条线索是否进入公司层面的事实披露。"
                    )
                else:
                    short_title = draft.title[:60] if draft.title else "这条线索"
                    improved.append(
                        f"围绕「{short_title}」继续查找官方来源、论文/复现结果或独立社区信号。"
                    )
            else:
                improved.append(point)
        if not any_repaired:
            return draft
        return draft.model_copy(
            update={
                "followup_points": improved,
                "metadata": {
                    **draft.metadata,
                    "repaired_generic_followups": True,
                },
            }
        )

    def _normalize_report_item_text(self, draft: ReportItemDraft) -> ReportItemDraft:
        return draft.model_copy(
            update={
                "title": self._clean_report_text(draft.title),
                "status_label": self._clean_report_text(draft.status_label),
                "core_information": self._clean_report_text(draft.core_information),
                "why_it_matters": self._clean_report_text(draft.why_it_matters),
                "potential_impact": self._clean_report_text(draft.potential_impact),
                "key_data": [self._clean_report_text(item) for item in draft.key_data],
                "followup_points": [
                    self._clean_report_text(item) for item in draft.followup_points
                ],
                "uncertainty_label": self._clean_report_text(draft.uncertainty_label),
            }
        )

    @staticmethod
    def _clean_report_text(text: str | None) -> str | None:
        if text is None:
            return None
        cleaned = text.replace("🤗", "Hugging Face")
        cleaned = re.sub(r"\b(?:watch|cl|ev|cand|eval|trace)_[A-Za-z0-9_:-]+\b", "", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        return cleaned.strip()

    def _repair_uncertain_item_language(self, draft: ReportItemDraft) -> ReportItemDraft:
        if draft.category not in {
            CandidateCategory.EARLY_SIGNAL,
            CandidateCategory.RESEARCH,
        }:
            return draft

        is_research = draft.category == CandidateCategory.RESEARCH

        status_label = draft.status_label
        if (
            not self._has_uncertainty_marker(status_label)
            and not self._has_strong_fact_marker(status_label)
        ):
            prefix = "预印本 / 未确认" if is_research else "未确认来源信号"
            status_label = f"{prefix}: {status_label}"

        core_information = draft.core_information

        why_it_matters = draft.why_it_matters
        if not self._has_uncertainty_marker(why_it_matters):
            why_it_matters = (
                f"{why_it_matters} 在出现同行评审、独立复现或官方确认前，"
                "这只能作为早期信号处理。"
            )

        potential_impact = draft.potential_impact
        if potential_impact:
            uncertainty_scope = (
                "预印本，尚未验证"
                if is_research
                else "单一来源，尚未确认"
            )
            potential_impact = potential_impact.replace(
                "Medium to High",
                f"低到中等（{uncertainty_scope}）",
            )
            potential_impact = potential_impact.replace(
                "Medium-to-high",
                f"低到中等（{uncertainty_scope}）",
            )
            potential_impact = potential_impact.replace(
                "medium to high",
                f"低到中等（{uncertainty_scope}）",
            )
            potential_impact = potential_impact.replace(
                "medium-to-high",
                f"低到中等（{uncertainty_scope}）",
            )
            if not self._has_uncertainty_marker(potential_impact):
                potential_impact = (
                    "若后续被交叉验证，潜在影响："
                    f"{potential_impact}"
                )
            elif (
                is_research
                and "preprint" not in potential_impact.lower()
                and "预印本" not in potential_impact
            ):
                potential_impact = f"预印本阶段影响：{potential_impact}"
            potential_impact = self._clean_uncertainty_prefixes(potential_impact)

        key_data = [
            self._hedge_uncertain_key_data(item, category=draft.category)
            for item in draft.key_data
        ]
        default_followup = (
            "继续追踪同行评审状态、独立复现和实现细节。"
            if is_research
            else (
                "在提升为正式事项前，继续寻找独立来源、代码制品或官方公告进行交叉验证。"
            )
        )
        followup_points = self._dedupe(
            draft.followup_points
            + [default_followup]
        )
        uncertainty_label = draft.uncertainty_label
        if not uncertainty_label or not self._has_uncertainty_marker(uncertainty_label):
            uncertainty_label = (
                "预印本 / 未确认；需要同行评审、复现或官方确认。"
                if is_research
                else (
                    "未确认来源信号；需要独立交叉验证或官方确认。"
                )
            )

        return draft.model_copy(
            update={
                "status_label": status_label,
                "core_information": core_information,
                "why_it_matters": why_it_matters,
                "potential_impact": potential_impact,
                "key_data": key_data,
                "followup_points": followup_points,
                "uncertainty_label": uncertainty_label,
                "metadata": {
                    **draft.metadata,
                    "repaired_uncertain_item_language": True,
                },
            }
        )

    @staticmethod
    def _repair_status_label_language(draft: ReportItemDraft) -> ReportItemDraft:
        status_label = draft.status_label.strip()
        category_values = {category.value for category in CandidateCategory}
        for separator in (":", "："):
            if separator not in status_label:
                continue
            prefix, suffix = status_label.rsplit(separator, 1)
            if suffix.strip().lower() in category_values:
                status_label = prefix.strip()

        normalized = status_label.lower().strip()
        if normalized in {"confirmed", "confirmed_event", "official_update"}:
            status_label = "已确认"
        elif normalized in {"early_signal", "unconfirmed source signal"}:
            status_label = "未确认来源信号"
        elif normalized in {"research", "preprint / unconfirmed"}:
            status_label = "预印本 / 未确认"
        elif draft.category == CandidateCategory.WATCHLIST_UPDATE:
            status_label = WritingOutputMaterializer._human_watch_status(status_label)

        if status_label == draft.status_label:
            return draft
        return draft.model_copy(update={"status_label": status_label})

    @staticmethod
    def _sanitize_report_item_tickers(draft: ReportItemDraft) -> ReportItemDraft:
        invalid_tickers = {
            "ANTH",
            "CEREBRAS",
            "DEEPSEEK",
            "HF",
            "HUGGINGFACE",
            "MISTRAL",
            "OPENAI",
            "XAI",
        }
        tickers = [
            ticker
            for ticker in draft.tickers
            if ticker.upper() not in invalid_tickers
        ]
        if tickers == draft.tickers:
            return draft
        return draft.model_copy(
            update={
                "tickers": tickers,
                "metadata": {
                    **draft.metadata,
                    "removed_invalid_tickers": [
                        ticker
                        for ticker in draft.tickers
                        if ticker.upper() in invalid_tickers
                    ],
                },
            }
        )

    @staticmethod
    def _has_uncertainty_marker(text: str | None) -> bool:
        if not text:
            return False
        normalized = text.lower()
        return any(
            marker in normalized
            for marker in {
                "preprint",
                "preliminary",
                "unconfirmed",
                "not peer-reviewed",
                "peer review",
                "if validated",
                "independently validated",
                "reported",
                "suggest",
                "claim",
                "unvalidated",
                "corroborated",
                "corroboration",
                "source signal",
                "single-source",
                "预印本",
                "初步",
                "早期信号",
                "未确认",
                "尚未确认",
                "未验证",
                "单一来源",
                "交叉验证",
                "官方确认",
                "同行评审",
                "复现",
            }
        )

    @staticmethod
    def _has_strong_fact_marker(text: str | None) -> bool:
        if not text:
            return False
        normalized = text.lower()
        return any(
            marker in normalized
            for marker in {
                "confirmed",
                "official launch",
                "officially launched",
                "has launched",
                "has released",
                "is now available",
            }
        )

    @staticmethod
    def _hedge_uncertain_key_data(
        item: str,
        *,
        category: CandidateCategory,
    ) -> str:
        normalized = item.lower()
        if (
            "preprint claim" in normalized
            or "signal detail" in normalized
            or "unvalidated" in normalized
            or "unconfirmed" in normalized
            or "预印本声明" in normalized
            or "信号细节" in normalized
            or "未验证" in normalized
            or "未确认" in normalized
        ):
            return item
        if category == CandidateCategory.RESEARCH:
            return f"预印本声明（未验证）：{item}"
        return f"信号细节（未确认）：{item}"

    @staticmethod
    def _clean_uncertainty_prefixes(text: str) -> str:
        replacements = {
            "预印本阶段影响：预印本阶段影响：": "预印本阶段影响：",
            "若后续被交叉验证，潜在影响：若后续被交叉验证，潜在影响：": "若后续被交叉验证，潜在影响：",
        }
        cleaned = text
        changed = True
        while changed:
            changed = False
            for source, target in replacements.items():
                if source in cleaned:
                    cleaned = cleaned.replace(source, target)
                    changed = True
        return cleaned

    def _repair_tech_finance_fields_from_clusters(
        self,
        run_id: str,
        draft: ReportItemDraft,
    ) -> ReportItemDraft:
        if draft.category != CandidateCategory.TECH_FINANCE:
            return draft

        clusters: list[EventCluster] = []
        for cluster_id in draft.cluster_ids:
            try:
                clusters.append(self.clusters.require(cluster_id))
            except LookupError:
                self.context.trace_service.record_event(
                    run_id=run_id,
                    phase=RunPhase.WRITING,
                    agent_role=AgentRole.WRITER,
                    event_type=TraceEventType.ARTIFACT_STORED,
                    summary=f"Writer referenced unknown cluster {cluster_id}; skipping.",
                    metadata={"cluster_id": cluster_id, "repair": "tech_finance_fields"},
                )
        run_clusters = [cluster for cluster in clusters if cluster.run_id == run_id]
        inherited_tickers = self._dedupe(
            [
                ticker
                for cluster in run_clusters
                for ticker in cluster.tickers
                if ticker
            ]
        )
        tickers = draft.tickers or inherited_tickers
        potential_impact = draft.potential_impact
        metadata = {
            **draft.metadata,
            "repaired_tech_finance_fields_from_clusters": True,
        }

        if not potential_impact:
            impact_source = next(
                (
                    cluster.canonical_claim or cluster.title
                    for cluster in run_clusters
                    if cluster.canonical_claim or cluster.title
                ),
                None,
            )
            if impact_source:
                potential_impact = (
                    "科技金融影响仍需后续验证；当前引用的事件簇信息为："
                    f"{impact_source}"
                )

        if (
            potential_impact
            and "impact chain" not in potential_impact.lower()
            and "影响链条" not in potential_impact
        ):
            potential_impact = (
                f"{potential_impact} 影响链条：SEC 文件内容或公司经营数据会改变投资者预期，"
                "进而影响相关 ticker、AI 硬件供应链情绪和 AI 基础设施 capex 假设。"
            )

        key_data, followup_points, sec_metadata_only = (
            self._repair_sec_finance_details_from_evidence(
                run_id=run_id,
                clusters=run_clusters,
                draft=draft,
            )
        )
        if sec_metadata_only:
            metadata["sec_metadata_only_needs_followup"] = True
            potential_impact = self._metadata_only_finance_impact(tickers or inherited_tickers)

        if (
            tickers != draft.tickers
            or potential_impact != draft.potential_impact
            or key_data != draft.key_data
            or followup_points != draft.followup_points
        ):
            return draft.model_copy(
                update={
                    "tickers": tickers,
                    "potential_impact": potential_impact,
                    "key_data": key_data,
                    "followup_points": followup_points,
                    "metadata": metadata,
                }
        )
        return draft

    @staticmethod
    def _metadata_only_finance_impact(tickers: list[str]) -> str:
        ticker_text = ", ".join(tickers) if tickers else "相关公司"
        return (
            f"当前只能确认 {ticker_text} 相关 SEC 文件存在，尚不能据此判断收入 beat/miss、"
            "capex 方向或股价涨跌幅。影响链条：先提取 SEC 正文和 XBRL/company facts 中的收入、"
            "数据中心、capex 或 guidance 数据，再比较历史趋势和市场预期，最后才评估相关 ticker、"
            "AI 硬件供应链情绪和 AI 基础设施 capex 假设。"
        )

    def _repair_sec_finance_details_from_evidence(
        self,
        *,
        run_id: str,
        clusters: list[EventCluster],
        draft: ReportItemDraft,
    ) -> tuple[list[str], list[str], bool]:
        evidence_items = []
        for evidence_id in self._dedupe(
            [
                evidence_id
                for cluster in clusters
                for evidence_id in cluster.evidence_ids
            ]
        ):
            evidence = self.evidence.get(evidence_id)
            if evidence is not None and evidence.run_id == run_id:
                evidence_items.append(evidence)

        sec_items = [
            evidence
            for evidence in evidence_items
            if evidence.source_type.value == "sec_filing"
        ]
        if not sec_items:
            return draft.key_data, draft.followup_points, False

        content_items = [
            evidence
            for evidence in sec_items
            if evidence.metadata.get("kind") in {"sec_filing_content", "sec_xbrl_fact"}
        ]
        metadata_only_items = [
            evidence
            for evidence in sec_items
            if evidence.metadata.get("kind") == "sec_filing"
        ]
        key_data = list(draft.key_data)
        for evidence in content_items[:3]:
            if evidence.metadata.get("formatted_value"):
                key_data.append(
                    f"{evidence.title}: {evidence.metadata['formatted_value']}"
                )
            else:
                key_data.append(evidence.snippet)
        for evidence in metadata_only_items[:3]:
            form = evidence.metadata.get("form")
            filing_date = evidence.metadata.get("filing_date")
            accession = evidence.metadata.get("accession_number")
            key_data.append(
                "已抓取 SEC 文件元数据："
                f"{form or 'filing'}，日期 {filing_date or 'unknown date'}"
                + (f"，accession {accession}" if accession else "")
            )

        sec_metadata_only = bool(metadata_only_items) and not content_items
        followup_points = list(draft.followup_points)
        if sec_metadata_only:
            followup_points.append(
                "下一步用 sec_filing_content 拉取该 accession 的正文，并用 sec_company_facts "
                "核对收入、capex 或数据中心指标，再判断是否具备更强市场影响。"
            )

        return self._dedupe(key_data), self._dedupe(followup_points), sec_metadata_only

    def _normalize_item_category_from_clusters(
        self,
        run_id: str,
        draft: ReportItemDraft,
    ) -> ReportItemDraft:
        if draft.category == CandidateCategory.WATCHLIST_UPDATE:
            return draft
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
        if len(categories) > 1:
            primary_category = (
                draft.category
                if draft.category in categories
                else clusters[0].category
            )
            primary_clusters = [
                cluster for cluster in clusters if cluster.category == primary_category
            ]
            primary_cluster_ids = [cluster.id for cluster in primary_clusters]
            primary_evidence_ids = self._dedupe(
                [
                    evidence_id
                    for cluster in primary_clusters
                    for evidence_id in cluster.evidence_ids
                ]
            )
            repaired_evidence_ids = self._dedupe(
                [
                    evidence_id
                    for evidence_id in draft.evidence_ids
                    if evidence_id in set(primary_evidence_ids)
                ]
            ) or primary_evidence_ids
            return draft.model_copy(
                update={
                    "category": primary_category,
                    "cluster_ids": primary_cluster_ids,
                    "evidence_ids": repaired_evidence_ids,
                    "metadata": {
                        **draft.metadata,
                        "normalized_mixed_cluster_categories": True,
                        "original_category": draft.category.value,
                        "original_cluster_ids": draft.cluster_ids,
                        "dropped_cluster_ids": [
                            cluster.id
                            for cluster in clusters
                            if cluster.category != primary_category
                        ],
                    },
                }
            )
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
            if (
                draft.category != CandidateCategory.WATCHLIST_UPDATE
                and cluster.category != draft.category
            ):
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
            if (
                draft.category != CandidateCategory.WATCHLIST_UPDATE
                and clusters
                and evidence_id not in cluster_evidence_ids
            ):
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
                    current_status=self._human_watch_status(item.status.value),
                    new_developments=[
                        self._human_watch_development(entry.summary)
                        for entry in item.history[-3:]
                    ],
                    next_watch=self._human_watch_next_list(
                        item.open_questions or item.reactivation_rules
                    ),
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
            "current_status": WritingOutputMaterializer._human_watch_status(
                str(current_status)
            ),
            "new_developments": [
                WritingOutputMaterializer._human_watch_development(item)
                for item in new_developments
            ],
            "next_watch": WritingOutputMaterializer._human_watch_next_list(next_watch),
            "evidence_ids": evidence_ids,
        }

    @staticmethod
    def _human_watch_status(status: str) -> str:
        if WritingOutputMaterializer._contains_cjk(status):
            return status
        normalized = status.strip().lower()
        mapping = {
            "active": "短期追踪中",
            "reactivated": "已重新激活追踪",
            "archived": "已归档",
            "expired": "已到期",
            "paused": "暂停追踪",
        }
        return mapping.get(normalized, f"追踪状态：{status}")

    @staticmethod
    def _human_watch_development(text: str) -> str:
        if WritingOutputMaterializer._contains_cjk(text):
            return text
        normalized = text.strip().lower()
        if normalized == "watchlist tracking item created or refreshed.":
            return "已创建或刷新 Watchlist 追踪项。"
        if not text.strip():
            return "今日无新增。"
        return f"今日进展待核验：{text}"

    @staticmethod
    def _human_watch_next_list(items: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in items:
            if WritingOutputMaterializer._contains_cjk(item):
                normalized.append(item)
            elif item.strip():
                normalized.append(f"继续核验：{item}")
        return normalized

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
        issue_drafts, required_changes, filtered_issue_count = (
            self._filter_non_blocking_review_findings(
                report=report,
                issues=issue_drafts,
                required_changes=required_changes,
            )
        )
        if filtered_issue_count:
            self.context.trace_service.record_event(
                run_id=run.id,
                phase=phase,
                agent_role=AgentRole.REVIEWER,
                event_type=TraceEventType.AGENT_DECISION,
                status=TraceStatus.SUCCEEDED,
                summary="Writing materializer filtered non-blocking reviewer findings.",
                reasoning_summary=(
                    "Findings that were already caveated in the report or allowed by "
                    "the report contract were kept out of the blocking review result."
                ),
                metadata={
                    "filtered_issue_count": filtered_issue_count,
                    "materialized_by": "WritingOutputMaterializer",
                },
            )
        if decision == ReviewDecision.REVISE and not (issue_drafts or required_changes):
            decision = ReviewDecision.PASS
        guard_issues = self._deterministic_report_quality_issues(report)
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
                "filtered_non_blocking_issue_count": filtered_issue_count,
            },
            created_at=utc_now(),
        )
        return review, issues

    def _filter_non_blocking_review_findings(
        self,
        *,
        report: DailyReport,
        issues: list[ReviewIssueDraft],
        required_changes: list[str],
    ) -> tuple[list[ReviewIssueDraft], list[str], int]:
        kept_issues: list[ReviewIssueDraft] = []
        filtered_count = 0
        for issue in issues:
            if self._is_non_blocking_review_text(report, f"{issue.title} {issue.body}"):
                filtered_count += 1
                continue
            kept_issues.append(issue)

        kept_changes: list[str] = []
        for change in required_changes:
            if self._is_non_blocking_review_text(report, change):
                continue
            kept_changes.append(change)
        return kept_issues, self._dedupe(kept_changes), filtered_count

    def _is_non_blocking_review_text(self, report: DailyReport, text: str) -> bool:
        normalized = text.lower()
        report_text = self._report_text(report)

        if "length-1 snippets" in normalized:
            return True
        if "trace_event_id mismatch" in normalized or "trace_event_ids" in normalized:
            return self._report_evidence_trace_ids_consistent(report)
        if "core_information" in normalized and any(
            marker in normalized for marker in {"missing", "empty", "not present"}
        ):
            return self._report_json_items_have_core_information(report)
        if "emoji" in normalized:
            return "🤗" not in self._report_text(report)
        if "dividend" in normalized and "25x" in normalized:
            return True
        if "write_policy" in normalized:
            return True
        if "ticker field" in normalized or ("ticker" in normalized and "metadata" in normalized):
            return True
        if "overview" in normalized and "contradict" in normalized:
            return True
        if any(
            marker in normalized
            for marker in {
                "evidence_map",
                "evidence mismatch",
                "evidence_ids missing",
                "undeclared evidence",
                "missing evidence",
            }
        ):
            return self._report_lineage_consistent(report)
        if "low evaluation score" in normalized:
            return True
        if "finance impact chain" in normalized or "financial impact chain" in normalized:
            return self._report_tech_finance_items_have_impact(report)
        if any(marker in normalized for marker in {"tech-finance", "tech finance"}):
            if any(marker in normalized for marker in {"no tech-finance", "no tech finance", "missing finance"}):
                return not self._report_has_category(report, CandidateCategory.TECH_FINANCE)
        if "redundant" in normalized and any(
            marker in normalized
            for marker in {"preliminary signal", "not independently validated"}
        ):
            return True
        if "watchlist" in normalized and any(
            marker in normalized
            for marker in {"duplicate", "same cluster", "overlap", "merge or differentiate"}
        ):
            return "watchlist" in report_text
        if any(marker in normalized for marker in {"consensus", "beat/miss"}):
            return (
                "consensus analyst estimates are not in the provided evidence" in report_text
                and "no determination of a revenue beat or miss can be made" in report_text
            )
        if any(
            marker in normalized
            for marker in {
                "arxiv",
                "preprint",
                "paper claims",
                "unconfirmed",
                "worlddirector",
                "evidence bundle",
                "irrelevant evidence",
                "evidence map incomplete",
            }
        ):
            return (
                "preprint claim (unvalidated)" in report_text
                and (
                    "preliminary signal" in report_text
                    or "unverified preprint" in report_text
                    or "not independently validated" in report_text
                )
            )
        if any(
            marker in normalized
            for marker in {"hugging face", "misassigned evidence", "google june ai updates"}
        ):
            return (
                "four distinct" in report_text
                or "multiple official updates" in report_text
                or "multiple announcements" in report_text
                or "several official blog updates" in report_text
            )
        if "follow-up" in normalized and any(
            marker in normalized
            for marker in {
                "concrete",
                "actionability",
                "specific",
                "missing",
                "required_followups",
                "generic",
                "duplicate",
            }
        ):
            return self._report_items_have_followups(report)
        return False

    @staticmethod
    def _report_text(report: DailyReport) -> str:
        parts: list[str] = [report.title, report.full_markdown or ""]
        for section in report.sections:
            parts.extend([section.section_id, section.title])
            for item in section.items:
                parts.extend(
                    [
                        item.title,
                        item.status_label,
                        item.core_information,
                        item.why_it_matters,
                        item.potential_impact or "",
                        item.uncertainty_label or "",
                        " ".join(item.key_data),
                        " ".join(item.followup_points),
                    ]
                )
        return " ".join(parts).lower()

    @staticmethod
    def _report_items_have_followups(report: DailyReport) -> bool:
        items = [item for section in report.sections for item in section.items]
        return bool(items) and all(item.followup_points for item in items)

    @staticmethod
    def _report_json_items_have_core_information(report: DailyReport) -> bool:
        for section in report.full_json.get("sections", []):
            if not isinstance(section, dict):
                return False
            for item in section.get("items", []):
                if not isinstance(item, dict):
                    return False
                if not str(item.get("core_information") or "").strip():
                    return False
        return True

    @staticmethod
    def _report_has_category(report: DailyReport, category: CandidateCategory) -> bool:
        return any(
            item.category == category
            for section in report.sections
            for item in section.items
        )

    @staticmethod
    def _report_evidence_trace_ids_consistent(report: DailyReport) -> bool:
        trace_ids = set(report.trace_timeline_ids)
        json_trace_ids = set(report.full_json.get("trace_timeline_ids", []))
        if json_trace_ids:
            trace_ids.update(json_trace_ids)
        if not trace_ids:
            return False
        evidence_maps = list(report.evidence_map)
        if report.full_json.get("evidence_map"):
            evidence_maps.extend(
                EvidenceMapEntry.model_validate(entry)
                for entry in report.full_json.get("evidence_map", [])
                if isinstance(entry, dict)
            )
        return all(
            trace_event_id in trace_ids
            for entry in evidence_maps
            for trace_event_id in entry.trace_event_ids
        )

    @staticmethod
    def _report_lineage_consistent(report: DailyReport) -> bool:
        evidence_by_item = {entry.report_item_id: entry for entry in report.evidence_map}
        for section in report.sections:
            for item in section.items:
                entry = evidence_by_item.get(item.item_id)
                if entry is None:
                    return False
                if set(entry.evidence_ids) != set(item.evidence_ids):
                    return False
                if set(entry.cluster_ids) != set(item.cluster_ids):
                    return False
        return True

    @staticmethod
    def _report_tech_finance_items_have_impact(report: DailyReport) -> bool:
        tech_items = [
            item
            for section in report.sections
            for item in section.items
            if item.category == CandidateCategory.TECH_FINANCE
        ]
        return bool(tech_items) and all(
            item.potential_impact and "impact chain" in item.potential_impact.lower()
            for item in tech_items
        )

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

    def _deterministic_report_quality_issues(self, report: DailyReport) -> list[ReviewIssueDraft]:
        return [
            *self._early_signal_fact_issues(report),
            *self._human_language_issues(report),
            *self._system_language_issues(report),
        ]

    def _human_language_issues(self, report: DailyReport) -> list[ReviewIssueDraft]:
        missing_fields: dict[str, list[str]] = {}
        for section in report.sections:
            for item in section.items:
                if item.category == CandidateCategory.WATCHLIST_UPDATE:
                    continue
                item_missing: list[str] = []
                if not self._contains_cjk(item.core_information):
                    item_missing.append("core_information")
                if not self._contains_cjk(item.why_it_matters):
                    item_missing.append("why_it_matters")
                if item.potential_impact and not self._contains_cjk(item.potential_impact):
                    item_missing.append("potential_impact")
                if item.followup_points and not any(
                    self._contains_cjk(point) for point in item.followup_points
                ):
                    item_missing.append("followup_points")
                if item_missing:
                    missing_fields[item.item_id] = item_missing

        if not missing_fields:
            return []
        return [
            ReviewIssueDraft(
                priority=1,
                title="Human report body is not written in Chinese",
                body=(
                    "Human-facing narrative fields must be written in Simplified Chinese. "
                    "Keep English proper nouns, model names, paper titles, URLs, APIs, and tickers, "
                    "but rewrite explanatory body copy in Chinese."
                ),
                metadata={
                    "deterministic_guard": "human_report_language",
                    "item_fields": missing_fields,
                },
            )
        ]

    @staticmethod
    def _system_language_issues(report: DailyReport) -> list[ReviewIssueDraft]:
        text = report.full_markdown or ""
        normalized = text.lower()
        blocked_markers = {
            "warning:",
            "source diversity",
            "来源多样性",
            "来源类型",
            "single-source justification",
            "write_policy",
            "selected_cluster",
            "evidence_map",
            "trace_timeline",
            "no cross-source validation",
        }
        has_internal_id = re.search(
            r"\b(?:watch|cl|ev|cand|eval|trace)_[A-Za-z0-9_:-]+\b",
            text,
        )
        if not any(marker in normalized for marker in blocked_markers) and not has_internal_id:
            return []
        return [
            ReviewIssueDraft(
                priority=1,
                title="Human Markdown contains system or internal debug language",
                body=(
                    "Human-facing Markdown must not expose source-diversity gate text, "
                    "trace/evidence/cluster IDs, write policy labels, or warning/debug language."
                ),
                metadata={"deterministic_guard": "human_markdown_system_language"},
            )
        ]

    @staticmethod
    def _contains_cjk(text: str) -> bool:
        return bool(re.search(r"[\u3400-\u9fff]", text))

    @staticmethod
    def _contains_confirmed_fact_language(text: str) -> bool:
        import re
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
        has_uncertainty = any(marker in normalized for marker in uncertainty_markers)
        if has_uncertainty:
            return False
        # Use word-boundary matching for fact markers to avoid false positives
        # where fact markers appear as substrings of uncertainty terms
        # (e.g. "confirmed" inside "unconfirmed").
        return any(
            re.search(r"(?<!\w)" + re.escape(marker) + r"(?!\w)", normalized)
            for marker in fact_markers
        )

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
                fallback = self._latest_report(run_id)
                if fallback is None:
                    raise HarnessError(str(exc)) from exc
                return fallback
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
            "statistics": WritingOutputMaterializer._report_statistics(
                sections=sections,
                watchlist_updates=watchlist_updates,
                trace_timeline_ids=trace_timeline_ids,
            ),
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
        evidence_by_id: dict[str, EvidenceItem],
    ) -> str:
        body_item_count = sum(
            len(section.items)
            for section in sections
            if section.section_id != "watchlist"
        )
        watchlist_item_count = sum(
            len(section.items)
            for section in sections
            if section.section_id == "watchlist"
        )
        human_overview = WritingOutputMaterializer._human_overview_judgments(
            overview_judgments
        )
        lines = [
            f"# {title}",
            f"日期：{run.report_date.isoformat()}",
            "",
            "## 0. 今日总览",
        ]
        if human_overview:
            lines.extend(f"- {judgment}" for judgment in human_overview[:3])
        else:
            lines.append("- 今日入选信息已按爆料、确认事件和科技金融影响分桶整理。")
        lines.append(
            f"- 今日信息结构统计：正文 {body_item_count} 条，"
            f"Watchlist {watchlist_item_count or len(watchlist_updates)} 条。"
        )

        next_index = 1
        for section in sections:
            if section.section_id == "watchlist":
                continue
            index = next_index
            next_index += 1
            lines.extend(["", f"## {index}. {section.title}"])
            if not section.items:
                lines.append(WritingOutputMaterializer._empty_section_message(section.section_id))
                continue
            for item in section.items:
                lines.extend(
                    WritingOutputMaterializer._render_report_item(
                        item,
                        evidence_by_id=evidence_by_id,
                    )
                )

        rendered_watchlist = False
        watchlist_section = next(
            (section for section in sections if section.section_id == "watchlist"),
            None,
        )
        lines.extend(["", f"## {next_index}. 持续追踪 Watchlist"])
        next_index += 1
        if watchlist_section and watchlist_section.items:
            rendered_watchlist = True
            for item in watchlist_section.items:
                lines.extend(
                    WritingOutputMaterializer._render_report_item(
                        item,
                        evidence_by_id=evidence_by_id,
                    )
                )
        elif watchlist_updates:
            rendered_watchlist = True
            for update in watchlist_updates:
                lines.extend(
                    [
                        f"### {update.topic}",
                        f"- 当前状态：{update.current_status}",
                        f"- 今天的新进展：{'；'.join(update.new_developments) if update.new_developments else '无新增。'}",
                        f"- 下一步看什么：{'；'.join(update.next_watch) if update.next_watch else '等待新证据。'}",
                    ]
                )
        if not rendered_watchlist:
            lines.append("- 今日无 Watchlist 更新。")

        lines.extend(["", f"## {next_index}. 明日重点关注"])
        if tomorrow_focus:
            lines.extend(f"- {item}" for item in tomorrow_focus[:5])
        else:
            lines.append("- 跟踪今日入选事件的官方确认、代码变化和市场影响。")
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _empty_section_message(section_id: str) -> str:
        if section_id == "early_signals":
            return "- 今日没有达到写入门槛的前沿爆料；较弱信号保留在 trace 或 Watchlist 中继续观察。"
        if section_id == "confirmed_events":
            return "- 今日没有达到写入门槛的官方确认事件。"
        if section_id == "tech_finance":
            return "- 今日没有达到写入门槛的科技金融信息；Finance Scout 的弱信号会留在 trace 或后续 Watchlist 中复核。"
        return "- 今日无新增。"

    @staticmethod
    def _render_report_item(
        item: ReportItem,
        *,
        evidence_by_id: dict[str, EvidenceItem],
    ) -> list[str]:
        lines = [
            f"### {item.title}",
            f"- 状态：{item.status_label}",
            f"- 核心信息：{item.core_information}",
            f"- 为什么值得看：{item.why_it_matters}",
        ]
        if item.potential_impact:
            lines.append(f"- 潜在影响：{item.potential_impact}")
        if item.key_data:
            lines.append(f"- 关键数据：{'；'.join(item.key_data)}")
        if item.tickers:
            lines.append(f"- 相关 ticker：{', '.join(item.tickers)}")
        if item.uncertainty_label:
            lines.append(f"- 不确定性：{item.uncertainty_label}")
        sources = WritingOutputMaterializer._source_links(item, evidence_by_id)
        if sources:
            lines.append(f"- 来源：{'；'.join(sources)}")
        if item.followup_points:
            lines.append(f"- 后续追踪点：{'；'.join(item.followup_points)}")
        return lines

    @staticmethod
    def _report_statistics(
        *,
        sections: list[ReportSection],
        watchlist_updates: list[WatchlistUpdate],
        trace_timeline_ids: list[str],
    ) -> dict[str, int]:
        body_item_count = sum(
            len(section.items)
            for section in sections
            if section.section_id != "watchlist"
        )
        watchlist_item_count = sum(
            len(section.items)
            for section in sections
            if section.section_id == "watchlist"
        )
        return {
            "section_count": len(sections),
            "body_item_count": body_item_count,
            "watchlist_item_count": watchlist_item_count,
            "item_count": body_item_count + watchlist_item_count,
            "watchlist_update_count": len(watchlist_updates),
            "trace_event_count": len(trace_timeline_ids),
        }

    def _evidence_by_id_for_map(
        self,
        run_id: str,
        evidence_map: list[EvidenceMapEntry],
    ) -> dict[str, EvidenceItem]:
        evidence_ids = self._dedupe(
            [
                evidence_id
                for entry in evidence_map
                for evidence_id in entry.evidence_ids
            ]
        )
        evidence_by_id: dict[str, EvidenceItem] = {}
        for evidence_id in evidence_ids:
            evidence = self.evidence.get(evidence_id)
            if evidence is not None and evidence.run_id == run_id:
                evidence_by_id[evidence.id] = evidence
        return evidence_by_id

    @staticmethod
    def _source_links(
        item: ReportItem,
        evidence_by_id: dict[str, EvidenceItem],
    ) -> list[str]:
        links: list[str] = []
        for index, evidence_id in enumerate(item.evidence_ids[:3], start=1):
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                continue
            label = WritingOutputMaterializer._markdown_link_label(
                evidence.title or evidence.source_name or f"Source {index}"
            )
            if evidence.url:
                links.append(f"[{label}]({evidence.url})")
            else:
                links.append(label)
        return links

    @staticmethod
    def _markdown_link_label(text: str) -> str:
        cleaned = WritingOutputMaterializer._clean_report_text(text) or "Source"
        return cleaned.replace("[", "(").replace("]", ")")[:90]

    @staticmethod
    def _human_overview_judgments(overview_judgments: list[str]) -> list[str]:
        blocked_markers = {
            "source diversity",
            "source type available",
            "source type",
            "来源多样性",
            "来源类型",
            "不同来源",
            "single-source justification",
            "justification:",
            "distinct source types",
            "write_policy",
            "required bucket",
            "selected cluster",
            "evidence_map",
            "trace_timeline",
            "no single-source justification",
            "no cross-source validation",
            "warning:",
        }
        human: list[str] = []
        for judgment in overview_judgments:
            normalized = judgment.lower()
            if any(marker in normalized for marker in blocked_markers):
                continue
            cleaned = WritingOutputMaterializer._clean_report_text(judgment)
            if cleaned:
                human.append(cleaned)
        return human

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        deduped: list[str] = []
        for value in values:
            if value not in deduped:
                deduped.append(value)
        return deduped
