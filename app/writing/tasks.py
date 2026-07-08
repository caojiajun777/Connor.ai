"""Context builders for Writer, Reviewer, and Editor tasks."""

from __future__ import annotations

from typing import Any

from app.domain import (
    CandidateCategory,
    DailyReport,
    EvaluationDecision,
    EvaluationResult,
    EvidenceItem,
    EventCluster,
    WritePolicy,
)
from app.repositories.runs import FullRunState

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
        evaluations_by_cluster = WritingTaskFactory._evaluations_by_cluster(
            full_state.evaluations
        )
        evidence_ids = {
            evidence_id
            for cluster in selected_clusters
            for evidence_id in cluster.evidence_ids
        }
        # Compute source diversity for quality contract (Phase 15B)
        source_types = {
            evidence.source_type.value
            for evidence in full_state.evidence
            if evidence.id in evidence_ids
        }
        source_count = len(source_types)
        required_buckets = WritingTaskFactory._required_report_buckets(selected_clusters)
        return {
            "selected_cluster_ids": selected_cluster_ids,
            "selected_clusters": [
                WritingTaskFactory._cluster_summary(
                    cluster,
                    evaluations_by_cluster.get(cluster.id, []),
                )
                for cluster in selected_clusters
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
            "report_quality_contract": {
                "required_buckets": required_buckets,
                "required_sections": [
                    "0. overview",
                    *required_buckets,
                    "watchlist",
                    "tomorrow_focus",
                ],
                "selected_cluster_rule": (
                    "Every selected cluster must appear in at least one report item. "
                    "If a selected cluster still needs data, write it with caveats "
                    "instead of dropping it."
                ),
                "confirmed_event_rule": (
                    "Confirmed official updates must appear in Confirmed Events even "
                    "when benchmark details or rollout metrics need follow-up."
                ),
                "tech_finance_rule": (
                    "Tech-Finance clusters with filings but missing extracted numbers "
                    "must still be written as caveated finance items with ticker, "
                    "impact-chain, missing-data, and follow-up fields."
                ),
                "source_link_rule": (
                    "Every human-facing report item must cite its supporting sources. "
                    "Use the evidence titles and URLs supplied in supporting_evidence; "
                    "never leave a body item without a source line."
                ),
                "detail_depth_rule": (
                    "Do not write one-line summaries. For every body item, write "
                    "core_information as 2-4 substantive sentences grounded in evidence "
                    "snippets, why_it_matters as at least 2 sentences explaining the "
                    "technical/business implication, and potential_impact as a concrete "
                    "chain of effects when available. Include key numbers, dates, model "
                    "names, company names, benchmark names, and caveats from the sources."
                ),
            },
            "uncertainty_rule": (
                "Early Signals must be explicitly labeled as unconfirmed/gray/rumor-style "
                "signals and must never be written as confirmed facts."
            ),
            # Phase 15B: source diversity and impact chain rules
            "source_diversity_rule": (
                "Cover at least 2 distinct source types across the report. "
                "A single-source report needs explicit justification in the overview."
            ),
            "available_source_types": sorted(source_types),
            "source_type_count": source_count,
            "source_diversity_warning": (
                None
                if source_count >= 2
                else "WARNING: Only one source type available. Justify why this is sufficient."
            ),
            "impact_chain_rule": (
                "Every report item must connect the signal to a specific market, "
                "product, or competitive implication. Avoid generic language like "
                "'this could impact AI' without naming what specifically changes."
            ),
            "followup_specificity_rule": (
                "Follow-up points must reference specific entities, products, or "
                "metrics. Avoid generic placeholders like 'monitor for updates'; "
                "instead say 'Monitor NVDAs Q2 FY2026 earnings call for data-center "
                "revenue guidance'."
            ),
            "human_report_language_rule": (
                "Write the human-facing report body in Chinese. Preserve English "
                "company, model, product, paper, ticker, and API names. Do not "
                "include internal IDs such as cluster_ids, evidence_ids, watchlist_ids, "
                "write_policy, trace_timeline, or source-diversity gate text in "
                "human Markdown; keep those only in JSON/evidence_map."
            ),
        }

    @staticmethod
    def reviewer_context(full_state: FullRunState) -> dict:
        report = WritingTaskFactory._latest(full_state.reports)
        selected_cluster_ids = full_state.run.selected_cluster_ids or [
            cluster.id for cluster in full_state.clusters if cluster.selected
        ]
        report_cluster_ids = WritingTaskFactory._report_cluster_ids(report)
        relevant_cluster_ids = WritingTaskFactory._dedupe(
            [*selected_cluster_ids, *report_cluster_ids]
        )
        relevant_evidence_ids = WritingTaskFactory._review_evidence_ids(
            report=report,
            clusters=full_state.clusters,
            relevant_cluster_ids=relevant_cluster_ids,
        )
        evaluations_by_cluster = WritingTaskFactory._evaluations_by_cluster(
            full_state.evaluations
        )
        return {
            "report": (
                WritingTaskFactory._report_review_summary(report)
                if report is not None
                else None
            ),
            "selected_cluster_ids": selected_cluster_ids,
            "reported_cluster_ids": report_cluster_ids,
            "missing_selected_cluster_ids": [
                cluster_id
                for cluster_id in selected_cluster_ids
                if cluster_id not in set(report_cluster_ids)
            ],
            "review_focus": [
                "Do not allow early signals to be written as confirmed facts.",
                "Verify Markdown and JSON section consistency.",
                "Verify every report item has evidence_map coverage.",
                "Verify every selected cluster appears in at least one report item.",
                "Verify Tech-Finance items include data, tickers, and impact chain.",
                "Verify follow-up points are concrete.",
            ],
            "evidence": [
                WritingTaskFactory._evidence_summary(evidence)
                for evidence in full_state.evidence
                if evidence.id in relevant_evidence_ids
            ],
            "clusters": [
                WritingTaskFactory._cluster_summary(
                    cluster,
                    evaluations_by_cluster.get(cluster.id, []),
                )
                for cluster in full_state.clusters
                if cluster.id in relevant_cluster_ids
            ],
            "trace_event_ids": [event.id for event in full_state.trace_events[-80:]],
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
    def _cluster_summary(cluster: EventCluster, evaluations: list[EvaluationResult]) -> dict:
        bucket = WritingTaskFactory._report_bucket(cluster.category)
        return {
            "id": cluster.id,
            "category": cluster.category.value,
            "report_bucket": bucket,
            "write_policy": WritingTaskFactory._write_policy(evaluations),
            "title": cluster.title,
            "canonical_claim": cluster.canonical_claim,
            "evidence_ids": cluster.evidence_ids,
            "tickers": cluster.tickers,
            "topics": cluster.topics,
            "selected": cluster.selected,
            "evaluation_decisions": [
                evaluation.decision.value for evaluation in evaluations
            ],
            "required_followups": WritingTaskFactory._dedupe(
                [
                    followup
                    for evaluation in evaluations
                    for followup in evaluation.required_followups
                ]
            ),
            "missing_evidence": WritingTaskFactory._dedupe(
                [
                    evidence
                    for evaluation in evaluations
                    for evidence in evaluation.missing_evidence
                ]
            ),
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
    def _report_review_summary(report: DailyReport) -> dict[str, Any]:
        json_sections = report.full_json.get("sections", []) if report.full_json else []
        json_section_ids = [
            section.get("section_id")
            for section in json_sections
            if isinstance(section, dict)
        ]
        return {
            "id": report.id,
            "status": report.status.value,
            "title": report.title,
            "section_ids": [section.section_id for section in report.sections],
            "full_json_section_ids": json_section_ids,
            "overview_judgments": report.metadata.get("overview_judgments", []),
            "tomorrow_focus": report.full_json.get("tomorrow_focus", [])
            if report.full_json
            else [],
            "sections": [
                {
                    "section_id": section.section_id,
                    "title": section.title,
                    "items": [
                        {
                            "item_id": item.item_id,
                            "title": item.title,
                            "category": item.category.value,
                            "status_label": item.status_label,
                            "core_information": item.core_information,
                            "why_it_matters": item.why_it_matters,
                            "potential_impact": item.potential_impact,
                            "key_data": item.key_data,
                            "tickers": item.tickers,
                            "evidence_ids": item.evidence_ids,
                            "cluster_ids": item.cluster_ids,
                            "followup_points": item.followup_points,
                            "uncertainty_label": item.uncertainty_label,
                        }
                        for item in section.items
                    ],
                }
                for section in report.sections
            ],
            "evidence_map": [
                entry.model_dump(mode="json") for entry in report.evidence_map
            ],
            "watchlist_updates": [
                update.model_dump(mode="json") for update in report.watchlist_updates
            ],
            "full_markdown_available": bool(report.full_markdown),
            "full_markdown_length": len(report.full_markdown or ""),
        }

    @staticmethod
    def _report_cluster_ids(report: DailyReport | None) -> list[str]:
        if report is None:
            return []
        return WritingTaskFactory._dedupe(
            [
                cluster_id
                for section in report.sections
                for item in section.items
                for cluster_id in item.cluster_ids
            ]
        )

    @staticmethod
    def _review_evidence_ids(
        *,
        report: DailyReport | None,
        clusters: list[EventCluster],
        relevant_cluster_ids: list[str],
    ) -> list[str]:
        evidence_ids: list[str] = []
        if report is not None:
            evidence_ids.extend(
                evidence_id
                for section in report.sections
                for item in section.items
                for evidence_id in item.evidence_ids
            )
            evidence_ids.extend(
                evidence_id
                for entry in report.evidence_map
                for evidence_id in entry.evidence_ids
            )
        relevant = set(relevant_cluster_ids)
        evidence_ids.extend(
            evidence_id
            for cluster in clusters
            if cluster.id in relevant
            for evidence_id in cluster.evidence_ids
        )
        return WritingTaskFactory._dedupe(evidence_ids)

    @staticmethod
    def _latest(items):
        if not items:
            return None
        return sorted(items, key=lambda item: item.created_at)[-1]

    @staticmethod
    def _evaluations_by_cluster(
        evaluations: list[EvaluationResult],
    ) -> dict[str, list[EvaluationResult]]:
        grouped: dict[str, list[EvaluationResult]] = {}
        for evaluation in evaluations:
            grouped.setdefault(evaluation.cluster_id, []).append(evaluation)
        return grouped

    @staticmethod
    def _required_report_buckets(clusters: list[EventCluster]) -> list[str]:
        buckets: list[str] = []
        for cluster in clusters:
            bucket = WritingTaskFactory._report_bucket(cluster.category)
            if bucket is not None and bucket not in buckets:
                buckets.append(bucket)
        return buckets

    @staticmethod
    def _report_bucket(category: CandidateCategory) -> str | None:
        for bucket, categories in REPORT_BUCKETS.items():
            if category in categories:
                return bucket
        return None

    @staticmethod
    def _write_policy(evaluations: list[EvaluationResult]) -> str:
        # Use persisted calibrated write_policy when available (Phase 15B).
        # Fall back to decision-based derivation for older records.
        calibrated = [
            eval_.write_policy
            for eval_ in evaluations
            if eval_.write_policy is not None
        ]
        if calibrated:
            policy_priority = [
                WritePolicy.DO_NOT_WRITE,
                WritePolicy.ARCHIVE,
                WritePolicy.CONTEXT_ONLY,
                WritePolicy.WRITE_WITH_CAVEAT,
                WritePolicy.WRITE_NOW,
            ]
            for policy in policy_priority:
                if policy in calibrated:
                    return policy.value
            return WritePolicy.CONTEXT_ONLY.value

        # Legacy fallback for records without persisted write_policy
        decisions = {evaluation.decision for evaluation in evaluations}
        if decisions.intersection(
            {
                EvaluationDecision.SELECT_CONFIRMED,
                EvaluationDecision.SELECT_EARLY_SIGNAL,
            }
        ):
            return WritePolicy.WRITE_NOW.value
        if EvaluationDecision.REJECT in decisions:
            return WritePolicy.DO_NOT_WRITE.value
        if EvaluationDecision.ARCHIVE in decisions:
            return WritePolicy.ARCHIVE.value
        if decisions.intersection(
            {
                EvaluationDecision.FOLLOWUP_NOW,
                EvaluationDecision.FOLLOWUP_LATER,
                EvaluationDecision.SHORT_WATCH,
            }
        ):
            return WritePolicy.WRITE_WITH_CAVEAT.value
        return WritePolicy.CONTEXT_ONLY.value

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        deduped: list[str] = []
        for value in values:
            if value not in deduped:
                deduped.append(value)
        return deduped
