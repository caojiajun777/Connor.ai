"""Programmatic quality gates for collect and writing loops."""

from __future__ import annotations

from app.domain import DailyReport, EvaluationResult, EventCluster, ReviewResult, RunState
from app.domain.enums import (
    CandidateCategory,
    EvaluationDecision,
    ReportStatus,
    ReviewDecision,
    WritePolicy,
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

WRITEABLE_DECISIONS = {
    EvaluationDecision.SELECT_CONFIRMED,
    EvaluationDecision.SELECT_EARLY_SIGNAL,
    EvaluationDecision.FOLLOWUP_NOW,
    EvaluationDecision.FOLLOWUP_LATER,
}

WRITEABLE_POLICIES = {
    WritePolicy.WRITE_NOW,
    WritePolicy.WRITE_WITH_CAVEAT,
}

REPORT_BUCKETS = {
    "early_signals": {
        CandidateCategory.EARLY_SIGNAL,
        CandidateCategory.RESEARCH,
        CandidateCategory.CODE_MODEL,
    },
    "confirmed_events": {
        CandidateCategory.CONFIRMED_EVENT,
        CandidateCategory.OFFICIAL_UPDATE,
    },
    "tech_finance": {
        CandidateCategory.TECH_FINANCE,
    },
}

REQUIRED_REPORT_BUCKET_ORDER = [
    "early_signals",
    "confirmed_events",
    "tech_finance",
]


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
        selected_cluster_ids, coverage_metadata = self._add_report_bucket_coverage(
            full_state,
            selected_cluster_ids,
        )
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
            "watchlist_count": len(full_state.watchlist),
            "archive_count": len(full_state.archives),
            "thread_count": len(full_state.threads),
            "selected_cluster_count": len(selected_cluster_ids),
            "min_selected_items": self.config.min_selected_items,
            "min_report_body_items": self._min_report_body_items(),
            "followup_query_count": len(followup_queries),
            "collect_rounds": run.loop_counters.collect_rounds,
            "followup_rounds": run.loop_counters.followup_rounds,
            **coverage_metadata["bucket_counts"],
        }

        if len(selected_cluster_ids) >= self._min_report_body_items():
            return CollectGateDecision(
                outcome=CollectGateOutcome.ENTER_WRITING,
                reasoning_summary=(
                    "Collect gate found enough selected clusters to enter the writing loop."
                ),
                selected_cluster_ids=selected_cluster_ids,
                followup_queries=followup_queries,
                metrics=metrics,
                metadata=coverage_metadata,
            )

        if len(selected_cluster_ids) >= self.config.min_selected_items:
            if (
                followup_queries
                and run.loop_counters.followup_rounds < run.budgets.max_followup_rounds
            ):
                return CollectGateDecision(
                    outcome=CollectGateOutcome.FOLLOWUP_NOW,
                    reasoning_summary=(
                        "Collect gate has publishable material but needs more body-item "
                        "breadth for production-quality reporting."
                    ),
                    selected_cluster_ids=selected_cluster_ids,
                    followup_queries=followup_queries,
                    metrics=metrics,
                    risk_flags=["insufficient_report_body_breadth"],
                    metadata=coverage_metadata,
                )
            if run.loop_counters.collect_rounds < run.budgets.max_collect_rounds:
                return CollectGateDecision(
                    outcome=CollectGateOutcome.CONTINUE_COLLECTING,
                    reasoning_summary=(
                        "Collect gate has enough selected material for a minimal report, "
                        "but production-quality body breadth is still below threshold."
                    ),
                    selected_cluster_ids=selected_cluster_ids,
                    followup_queries=followup_queries,
                    metrics=metrics,
                    risk_flags=["insufficient_report_body_breadth"],
                    metadata=coverage_metadata,
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
            missing = self._final_report_missing_requirements(report, full_state)
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
            if run.loop_counters.review_rounds < self.config.max_writing_revisions:
                return WritingGateDecision(
                    outcome=WritingGateOutcome.REVISE,
                    reasoning_summary="Reviewer requested revision and revision budget remains.",
                    report_id=report.id,
                    review_result_id=review.id,
                    required_changes=review.required_changes
                    or [issue.title for issue in review.issues],
                    metrics=metrics,
                )
            missing = self._final_report_missing_requirements(report, full_state)
            if not missing and not self._has_blocking_review_issue(review):
                return WritingGateDecision(
                    outcome=WritingGateOutcome.FINALIZE,
                    reasoning_summary=(
                        "Revision budget is exhausted, but deterministic final "
                        "requirements pass and remaining review findings are non-blocking."
                    ),
                    report_id=report.id,
                    review_result_id=review.id,
                    risk_flags=["finalized_with_non_blocking_review_findings"],
                    metrics={
                        **metrics,
                        "deterministic_finalize_after_revision_budget": True,
                    },
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

    def _selected_cluster_ids(
        self,
        run: RunState,
        selected_evaluations: list[EvaluationResult],
    ) -> list[str]:
        selected = list(run.selected_cluster_ids)
        for evaluation in selected_evaluations:
            if evaluation.cluster_id not in selected:
                selected.append(evaluation.cluster_id)
        return selected

    def _add_report_bucket_coverage(
        self,
        full_state: FullRunState,
        selected_cluster_ids: list[str],
    ) -> tuple[list[str], dict]:
        selected = list(selected_cluster_ids)
        selected_set = set(selected)
        added: list[str] = []
        available_by_bucket = self._available_writeable_clusters_by_bucket(full_state)

        for bucket in REQUIRED_REPORT_BUCKET_ORDER:
            available = available_by_bucket.get(bucket, [])
            if not available:
                continue
            if any(cluster.id in selected_set for cluster in available):
                continue
            cluster = available[0]
            selected.append(cluster.id)
            selected_set.add(cluster.id)
            added.append(cluster.id)

        bucket_counts = {
            f"selected_{bucket}_count": sum(
                1
                for cluster in full_state.clusters
                if cluster.id in selected_set and self._report_bucket(cluster.category) == bucket
            )
            for bucket in REQUIRED_REPORT_BUCKET_ORDER
        }
        bucket_counts.update(
            {
                f"available_{bucket}_count": len(available_by_bucket.get(bucket, []))
                for bucket in REQUIRED_REPORT_BUCKET_ORDER
            }
        )
        return selected, {
            "coverage_added_cluster_ids": added,
            "bucket_counts": bucket_counts,
            "required_report_buckets": REQUIRED_REPORT_BUCKET_ORDER,
        }

    def _available_writeable_clusters_by_bucket(
        self,
        full_state: FullRunState,
    ) -> dict[str, list[EventCluster]]:
        evaluations_by_cluster = self._evaluations_by_cluster(full_state.evaluations)
        grouped: dict[str, list[tuple[float, EventCluster]]] = {
            bucket: [] for bucket in REQUIRED_REPORT_BUCKET_ORDER
        }
        for cluster in full_state.clusters:
            bucket = self._report_bucket(cluster.category)
            if bucket is None:
                continue
            evaluations = evaluations_by_cluster.get(cluster.id, [])
            writeable_evaluations = [
                evaluation
                for evaluation in evaluations
                if self._evaluation_is_writeable(evaluation)
            ]
            if not writeable_evaluations:
                continue
            score = max(evaluation.total_score for evaluation in writeable_evaluations)
            grouped[bucket].append((score, cluster))

        return {
            bucket: [
                cluster
                for _score, cluster in sorted(
                    candidates,
                    key=lambda item: (item[0], item[1].created_at),
                    reverse=True,
                )
            ]
            for bucket, candidates in grouped.items()
        }

    @staticmethod
    def _evaluation_is_writeable(evaluation: EvaluationResult) -> bool:
        if evaluation.write_policy is not None:
            return evaluation.write_policy in WRITEABLE_POLICIES
        return evaluation.decision in WRITEABLE_DECISIONS

    @staticmethod
    def _evaluations_by_cluster(
        evaluations: list[EvaluationResult],
    ) -> dict[str, list[EvaluationResult]]:
        grouped: dict[str, list[EvaluationResult]] = {}
        for evaluation in evaluations:
            grouped.setdefault(evaluation.cluster_id, []).append(evaluation)
        return grouped

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

    def _final_report_missing_requirements(
        self,
        report: DailyReport,
        full_state: FullRunState,
    ) -> list[str]:
        missing: list[str] = []
        if not report.full_markdown:
            missing.append("missing_full_markdown")
        if not report.sections:
            missing.append("missing_sections")
        if not report.evidence_map:
            missing.append("missing_evidence_map")
        if not report.full_json.get("tomorrow_focus"):
            missing.append("missing_tomorrow_focus")
        body_item_count = self._report_body_item_count(report)
        min_body_items = self._min_report_body_items()
        if body_item_count < min_body_items:
            missing.append(
                f"insufficient_report_body_items:{body_item_count}/{min_body_items}"
            )
        if report.status == ReportStatus.FAILED:
            missing.append("report_status_failed")
        if self.config.require_report_bucket_coverage:
            missing.extend(self._missing_selected_cluster_coverage(report, full_state))
        return missing

    def _min_report_body_items(self) -> int:
        return self.config.min_report_body_items or self.config.min_selected_items

    @staticmethod
    def _report_body_item_count(report: DailyReport) -> int:
        return sum(
            1
            for section in report.sections
            if section.section_id != "watchlist"
            for item in section.items
            if item.category != CandidateCategory.WATCHLIST_UPDATE
        )

    @staticmethod
    def _has_blocking_review_issue(review: ReviewResult) -> bool:
        return any(issue.priority <= 1 for issue in review.issues)

    def _missing_selected_cluster_coverage(
        self,
        report: DailyReport,
        full_state: FullRunState,
    ) -> list[str]:
        selected_ids = set(full_state.run.selected_cluster_ids)
        if not selected_ids:
            return []

        clusters_by_id = {
            cluster.id: cluster
            for cluster in full_state.clusters
            if cluster.id in selected_ids
        }
        item_cluster_ids = set()
        for section in report.sections:
            for item in section.items:
                item_bucket = self._report_bucket(item.category)
                for cluster_id in item.cluster_ids:
                    cluster = clusters_by_id.get(cluster_id)
                    if cluster is None:
                        continue
                    if item_bucket is not None and item_bucket == self._report_bucket(cluster.category):
                        item_cluster_ids.add(cluster_id)
        missing = [
            f"missing_selected_cluster:{cluster_id}"
            for cluster_id in sorted(selected_ids - item_cluster_ids)
        ]

        buckets_required = {
            self._report_bucket(cluster.category)
            for cluster in full_state.clusters
            if cluster.id in selected_ids
        }
        item_categories = {
            item.category
            for section in report.sections
            for item in section.items
        }
        for bucket in REQUIRED_REPORT_BUCKET_ORDER:
            if bucket not in buckets_required:
                continue
            categories = REPORT_BUCKETS[bucket]
            if not item_categories.intersection(categories):
                missing.append(f"missing_report_bucket:{bucket}")
        return missing

    @staticmethod
    def _report_bucket(category: CandidateCategory) -> str | None:
        for bucket, categories in REPORT_BUCKETS.items():
            if category in categories:
                return bucket
        return None

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
