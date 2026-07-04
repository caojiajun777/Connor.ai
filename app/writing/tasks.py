"""Context builders for Writer, Reviewer, and Editor tasks."""

from __future__ import annotations

from app.domain import EvaluationResult, EvidenceItem, EventCluster, ReviewResult, RunState
from app.repositories.runs import FullRunState


class WritingTaskFactory:
    """Build compact writing-loop contexts from persisted run state."""

    @staticmethod
    def writer_context(full_state: FullRunState) -> dict:
        run = full_state.run
        selected_cluster_ids = run.selected_cluster_ids or [
            cluster.id for cluster in full_state.clusters if cluster.selected
        ]
        selected_clusters = [
            cluster for cluster in full_state.clusters if cluster.id in selected_cluster_ids
        ]
        evidence_ids = {
            evidence_id
            for cluster in selected_clusters
            for evidence_id in cluster.evidence_ids
        }
        return {
            "selected_cluster_ids": selected_cluster_ids,
            "selected_clusters": [
                WritingTaskFactory._cluster_summary(cluster) for cluster in selected_clusters
            ],
            "supporting_evidence": [
                WritingTaskFactory._evidence_summary(evidence)
                for evidence in full_state.evidence
                if evidence.id in evidence_ids
            ],
            "selected_evaluations": [
                WritingTaskFactory._evaluation_summary(evaluation)
                for evaluation in full_state.evaluations
                if evaluation.cluster_id in selected_cluster_ids
            ],
            "watchlist": [item.model_dump(mode="json") for item in full_state.watchlist],
            "archives": [item.model_dump(mode="json") for item in full_state.archives],
            "threads": [item.model_dump(mode="json") for item in full_state.threads],
            "required_report_outputs": [
                "full_markdown",
                "full_json",
                "evidence_map",
                "watchlist_updates",
                "trace_timeline",
            ],
            "uncertainty_rule": (
                "Early Signals must be explicitly labeled as unconfirmed/gray/rumor-style "
                "signals and must never be written as confirmed facts."
            ),
        }

    @staticmethod
    def reviewer_context(full_state: FullRunState) -> dict:
        report = WritingTaskFactory._latest(full_state.reports)
        return {
            "report": report.model_dump(mode="json") if report is not None else None,
            "review_focus": [
                "Do not allow early signals to be written as confirmed facts.",
                "Verify Markdown and JSON section consistency.",
                "Verify every report item has evidence_map coverage.",
                "Verify Tech-Finance items include data, tickers, and impact chain.",
                "Verify follow-up points are concrete.",
            ],
            "evidence": [item.model_dump(mode="json") for item in full_state.evidence],
            "clusters": [item.model_dump(mode="json") for item in full_state.clusters],
            "trace_event_ids": [event.id for event in full_state.trace_events],
        }

    @staticmethod
    def editor_context(full_state: FullRunState) -> dict:
        report = WritingTaskFactory._latest(full_state.reports)
        review = WritingTaskFactory._latest(full_state.review_results)
        return {
            "report": report.model_dump(mode="json") if report is not None else None,
            "latest_review": review.model_dump(mode="json") if review is not None else None,
            "review_issues": [
                issue.model_dump(mode="json")
                for issue in full_state.review_issues
                if report is not None and issue.report_id == report.id
            ],
            "editor_rule": (
                "Revise only within the evidence boundary; keep early signals uncertain "
                "unless official evidence exists."
            ),
        }

    @staticmethod
    def _cluster_summary(cluster: EventCluster) -> dict:
        return {
            "id": cluster.id,
            "category": cluster.category.value,
            "title": cluster.title,
            "canonical_claim": cluster.canonical_claim,
            "evidence_ids": cluster.evidence_ids,
            "tickers": cluster.tickers,
            "topics": cluster.topics,
            "selected": cluster.selected,
        }

    @staticmethod
    def _evidence_summary(evidence: EvidenceItem) -> dict:
        return {
            "id": evidence.id,
            "source_type": evidence.source_type.value,
            "title": evidence.title,
            "url": evidence.url,
            "snippet": evidence.snippet,
            "strength": evidence.strength.value,
        }

    @staticmethod
    def _evaluation_summary(evaluation: EvaluationResult) -> dict:
        return {
            "id": evaluation.id,
            "cluster_id": evaluation.cluster_id,
            "evaluator_type": evaluation.evaluator_type.value,
            "decision": evaluation.decision.value,
            "total_score": evaluation.total_score,
            "reasoning_summary": evaluation.reasoning_summary,
            "required_followups": evaluation.required_followups,
            "missing_evidence": evaluation.missing_evidence,
        }

    @staticmethod
    def _latest(items):
        if not items:
            return None
        return sorted(items, key=lambda item: item.created_at)[-1]
