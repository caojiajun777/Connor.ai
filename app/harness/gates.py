"""Programmatic quality gates for collect and writing loops."""

from __future__ import annotations

from app.domain import DailyReport, EvaluationResult, ReviewResult, RunState
from app.domain.enums import (
    EvaluationDecision,
    ReportStatus,
    ReviewDecision,
)
from app.harness.config import HarnessConfig
from app.harness.decisions import (
    CollectGateDecision,
    CollectGateOutcome,
    WritingGateDecision,
    WritingGateOutcome,
)
from app.repositories.runs import FullRunState


SELECT_DECISIONS = {
    EvaluationDecision.SELECT_CONFIRMED,
    EvaluationDecision.SELECT_EARLY_SIGNAL,
}

FOLLOWUP_DECISIONS = {
    EvaluationDecision.FOLLOWUP_NOW,
    EvaluationDecision.FOLLOWUP_LATER,
}


class QualityGateService:
    """Apply deterministic harness-level quality gates."""

    def __init__(self, config: HarnessConfig | None = None):
        self.config = config or HarnessConfig()

    def evaluate_collect(self, full_state: FullRunState) -> CollectGateDecision:
        """Decide whether collection can advance to writing or needs another action."""

        run = full_state.run
        selected_evaluations = [
            evaluation
            for evaluation in full_state.evaluations
            if evaluation.decision in SELECT_DECISIONS
        ]
        selected_cluster_ids = self._selected_cluster_ids(run, selected_evaluations)
        followup_queries = self._followup_queries(full_state.evaluations)
        recluster_ids = [
            evaluation.cluster_id
            for evaluation in full_state.evaluations
            if evaluation.decision == EvaluationDecision.RECLUSTER
        ]
        metrics = {
            "evidence_count": len(full_state.evidence),
            "candidate_count": len(full_state.candidates),
            "cluster_count": len(full_state.clusters),
            "evaluation_count": len(full_state.evaluations),
            "selected_cluster_count": len(selected_cluster_ids),
            "followup_query_count": len(followup_queries),
            "collect_rounds": run.loop_counters.collect_rounds,
            "followup_rounds": run.loop_counters.followup_rounds,
        }

        if len(selected_cluster_ids) >= self.config.min_selected_items:
            return CollectGateDecision(
                outcome=CollectGateOutcome.ENTER_WRITING,
                reasoning_summary=(
                    "Collect gate found enough selected clusters to enter the writing loop."
                ),
                selected_cluster_ids=selected_cluster_ids,
                followup_queries=followup_queries,
                metrics=metrics,
            )

        if recluster_ids and run.loop_counters.collect_rounds < run.budgets.max_collect_rounds:
            return CollectGateDecision(
                outcome=CollectGateOutcome.RECLUSTER,
                reasoning_summary="Evaluator results indicate clustering issues that can still be retried.",
                recluster_cluster_ids=recluster_ids,
                risk_flags=["recluster_requested"],
                metrics=metrics,
            )

        if (
            followup_queries
            and run.loop_counters.followup_rounds < run.budgets.max_followup_rounds
            and run.loop_counters.collect_rounds < run.budgets.max_collect_rounds
        ):
            return CollectGateDecision(
                outcome=CollectGateOutcome.FOLLOWUP_NOW,
                reasoning_summary="Collect gate needs targeted follow-up before writing.",
                followup_queries=followup_queries,
                metrics=metrics,
            )

        if run.loop_counters.collect_rounds < run.budgets.max_collect_rounds:
            return CollectGateDecision(
                outcome=CollectGateOutcome.CONTINUE_COLLECTING,
                reasoning_summary="Collect gate has not selected enough material, but budget remains.",
                metrics=metrics,
                risk_flags=["insufficient_selected_items"],
            )

        risk_flags = [
            "collect_budget_exhausted",
            "insufficient_selected_items",
        ]
        outcome = (
            CollectGateOutcome.NEEDS_MANUAL_REVIEW
            if self.config.manual_review_on_failure
            else CollectGateOutcome.FAIL
        )
        return CollectGateDecision(
            outcome=outcome,
            reasoning_summary="Collect gate exhausted its collection budget without enough selected items.",
            risk_flags=risk_flags,
            metrics=metrics,
        )

    def evaluate_writing(self, full_state: FullRunState) -> WritingGateDecision:
        """Decide the next writing-loop action from reports and reviews."""

        run = full_state.run
        report = self._latest_report(full_state.reports)
        review = self._latest_review(full_state.review_results)
        metrics = {
            "report_count": len(full_state.reports),
            "review_count": len(full_state.review_results),
            "writing_rounds": run.loop_counters.writing_rounds,
            "review_rounds": run.loop_counters.review_rounds,
        }

        if report is None:
            return self._writing_failure(
                "Writing gate has no draft report to review.",
                ["missing_report"],
                metrics,
            )

        metrics.update(
            {
                "report_section_count": len(report.sections),
                "report_evidence_map_count": len(report.evidence_map),
            }
        )

        if review is None:
            return WritingGateDecision(
                outcome=WritingGateOutcome.REVIEW_DRAFT,
                reasoning_summary="Writing gate found a draft report that still needs review.",
                report_id=report.id,
                metrics=metrics,
            )

        if review.decision == ReviewDecision.PASS:
            missing = self._final_report_missing_requirements(report)
            if missing:
                return self._writing_failure(
                    "Reviewer passed the report, but final report requirements are missing.",
                    missing,
                    metrics,
                    report_id=report.id,
                    review_result_id=review.id,
                )
            return WritingGateDecision(
                outcome=WritingGateOutcome.FINALIZE,
                reasoning_summary="Reviewer passed the report and final report requirements are present.",
                report_id=report.id,
                review_result_id=review.id,
                metrics=metrics,
            )

        if review.decision == ReviewDecision.REOPEN_COLLECT:
            if run.loop_counters.collect_rounds < run.budgets.max_collect_rounds:
                return WritingGateDecision(
                    outcome=WritingGateOutcome.REOPEN_COLLECT,
                    reasoning_summary="Reviewer found missing evidence that requires reopening collection.",
                    report_id=report.id,
                    review_result_id=review.id,
                    reopen_collect_reasons=review.required_changes
                    or [issue.title for issue in review.issues],
                    metrics=metrics,
                )
            return self._writing_failure(
                "Reviewer requested collection reopen, but collect budget is exhausted.",
                ["collect_budget_exhausted", "review_requested_reopen_collect"],
                metrics,
                report_id=report.id,
                review_result_id=review.id,
            )

        if review.decision == ReviewDecision.REVISE:
            if run.loop_counters.review_rounds <= self.config.max_writing_revisions:
                return WritingGateDecision(
                    outcome=WritingGateOutcome.REVISE,
                    reasoning_summary="Reviewer requested revision and revision budget remains.",
                    report_id=report.id,
                    review_result_id=review.id,
                    required_changes=review.required_changes
                    or [issue.title for issue in review.issues],
                    metrics=metrics,
                )
            return self._writing_failure(
                "Writing revision budget exhausted before reviewer pass.",
                ["writing_revision_budget_exhausted"],
                metrics,
                report_id=report.id,
                review_result_id=review.id,
            )

        return self._writing_failure(
            "Reviewer rejected the report.",
            ["review_rejected_report"],
            metrics,
            report_id=report.id,
            review_result_id=review.id,
        )

    @staticmethod
    def _selected_cluster_ids(
        run: RunState,
        selected_evaluations: list[EvaluationResult],
    ) -> list[str]:
        selected = list(run.selected_cluster_ids)
        for evaluation in selected_evaluations:
            if evaluation.cluster_id not in selected:
                selected.append(evaluation.cluster_id)
        return selected

    @staticmethod
    def _followup_queries(evaluations: list[EvaluationResult]) -> list[str]:
        queries: list[str] = []
        for evaluation in evaluations:
            if evaluation.decision in FOLLOWUP_DECISIONS or evaluation.missing_evidence:
                queries.extend(evaluation.required_followups)
                queries.extend(evaluation.missing_evidence)
        deduped: list[str] = []
        for query in queries:
            if query and query not in deduped:
                deduped.append(query)
        return deduped

    @staticmethod
    def _latest_report(reports: list[DailyReport]) -> DailyReport | None:
        if not reports:
            return None
        return sorted(reports, key=lambda report: report.created_at)[-1]

    @staticmethod
    def _latest_review(reviews: list[ReviewResult]) -> ReviewResult | None:
        if not reviews:
            return None
        return sorted(reviews, key=lambda review: review.created_at)[-1]

    @staticmethod
    def _final_report_missing_requirements(report: DailyReport) -> list[str]:
        missing: list[str] = []
        if not report.full_markdown:
            missing.append("missing_full_markdown")
        if not report.sections:
            missing.append("missing_sections")
        if not report.evidence_map:
            missing.append("missing_evidence_map")
        if report.status == ReportStatus.FAILED:
            missing.append("report_status_failed")
        return missing

    def _writing_failure(
        self,
        reasoning_summary: str,
        risk_flags: list[str],
        metrics: dict[str, int | float],
        *,
        report_id: str | None = None,
        review_result_id: str | None = None,
    ) -> WritingGateDecision:
        outcome = (
            WritingGateOutcome.NEEDS_MANUAL_REVIEW
            if self.config.manual_review_on_failure
            else WritingGateOutcome.FAIL
        )
        return WritingGateDecision(
            outcome=outcome,
            reasoning_summary=reasoning_summary,
            report_id=report_id,
            review_result_id=review_result_id,
            risk_flags=risk_flags,
            metrics=metrics,
        )
