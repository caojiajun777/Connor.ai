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
    min_selected_items: int = Field(default=1, ge=0)
    manual_review_on_failure: bool = True
    archive_gate_snapshots: bool = True
    archive_loop_snapshots: bool = True
    materialize_scout_candidates: bool = True
    materialize_clusterer_outputs: bool = True
    materialize_evaluator_outputs: bool = True
    bootstrap_single_agent_clusters: bool = True
    bootstrap_single_agent_evaluations: bool = True
