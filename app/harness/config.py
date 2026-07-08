"""Configuration for Connor loop harness boundaries."""

from pydantic import Field

from app.domain.base import ConnorBaseModel


class HarnessConfig(ConnorBaseModel):
    """Programmatic loop boundaries and quality thresholds."""

    max_scout_tasks_per_round: int = Field(default=5, gt=0)
    max_cluster_tasks_per_round: int = Field(default=1, gt=0)
    max_evaluator_tasks_per_round: int = Field(default=3, gt=0)
    max_watchlist_tasks_per_round: int = Field(default=1, gt=0)
    max_writing_revisions: int = Field(default=2, ge=0)
    min_selected_items: int = Field(default=2, gt=0)
    min_report_body_items: int | None = Field(default=None, gt=0)
    require_report_bucket_coverage: bool = True

    # Score-based quality thresholds (Phase 17)
    min_avg_evaluation_score: float = Field(default=5.0, ge=0, le=10)
    min_single_cluster_score: float = Field(default=3.0, ge=0, le=10)
    bucket_coverage_min_score: float = Field(default=4.0, ge=0, le=10)

    manual_review_on_failure: bool = True
    archive_gate_snapshots: bool = True
    archive_loop_snapshots: bool = True
    materialize_scout_candidates: bool = True
    materialize_clusterer_outputs: bool = True
    materialize_evaluator_outputs: bool = True
    materialize_watchlist_outputs: bool = True
    materialize_writing_outputs: bool = True
    expire_due_watchlist_items: bool = True
    auto_materialize_watchlist_from_evaluations: bool = True
    bootstrap_single_agent_clusters: bool = True
    bootstrap_single_agent_evaluations: bool = True
    continue_on_scout_agent_error: bool = True
    continue_on_watchlist_agent_error: bool = True
    commit_checkpoints: bool = False

    # Scout parallelization
    parallelize_scouts: bool = True

    # LLM-as-Judge report quality evaluation
    enable_report_judge: bool = True
    report_judge_min_score: float = Field(default=6.0, ge=0, le=10)
