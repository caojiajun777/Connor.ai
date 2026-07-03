"""initial persistence schema

Revision ID: 0001_initial_persistence_schema
Revises:
Create Date: 2026-07-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_initial_persistence_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def json_payload_type() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def common_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", json_payload_type(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    ]


def create_common_indexes(table_name: str) -> None:
    op.create_index(f"ix_{table_name}_created_at", table_name, ["created_at"])


def upgrade() -> None:
    op.create_table(
        "runs",
        *common_columns(),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("phase", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
    )
    create_common_indexes("runs")
    op.create_index("ix_runs_report_date", "runs", ["report_date"])
    op.create_index("ix_runs_phase", "runs", ["phase"])
    op.create_index("ix_runs_status", "runs", ["status"])

    op.create_table(
        "evidence_items",
        *common_columns(),
        sa.Column("run_id", sa.String(length=128), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=True),
        sa.Column("access_level", sa.String(length=64), nullable=False),
        sa.Column("strength", sa.String(length=64), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_hash", sa.String(length=255), nullable=True),
    )
    create_common_indexes("evidence_items")
    for column in ["run_id", "source_type", "source_name", "strength", "retrieved_at", "raw_hash"]:
        op.create_index(f"ix_evidence_items_{column}", "evidence_items", [column])

    op.create_table(
        "candidate_items",
        *common_columns(),
        sa.Column("run_id", sa.String(length=128), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("signal_status", sa.String(length=64), nullable=True),
        sa.Column("claim_summary", sa.Text(), nullable=False),
        sa.Column("created_by_agent", sa.String(length=64), nullable=False),
        sa.Column("uncertainty", sa.String(length=64), nullable=False),
        sa.Column("evidence_strength", sa.String(length=64), nullable=False),
    )
    create_common_indexes("candidate_items")
    for column in ["run_id", "category", "signal_status", "created_by_agent", "evidence_strength"]:
        op.create_index(f"ix_candidate_items_{column}", "candidate_items", [column])

    op.create_table(
        "event_clusters",
        *common_columns(),
        sa.Column("run_id", sa.String(length=128), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("canonical_claim", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
    )
    create_common_indexes("event_clusters")
    for column in ["run_id", "category", "dedupe_key", "selected"]:
        op.create_index(f"ix_event_clusters_{column}", "event_clusters", [column])

    op.create_table(
        "evaluation_results",
        *common_columns(),
        sa.Column("run_id", sa.String(length=128), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cluster_id", sa.String(length=128), nullable=False),
        sa.Column("evaluator_type", sa.String(length=64), nullable=False),
        sa.Column("created_by_agent", sa.String(length=64), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column("decision", sa.String(length=64), nullable=False),
        sa.Column("reasoning_summary", sa.Text(), nullable=False),
    )
    create_common_indexes("evaluation_results")
    for column in ["run_id", "cluster_id", "evaluator_type", "created_by_agent", "total_score", "decision"]:
        op.create_index(f"ix_evaluation_results_{column}", "evaluation_results", [column])

    op.create_table(
        "watchlist_items",
        *common_columns(),
        sa.Column("run_id", sa.String(length=128), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("watch_tier", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.String(length=64), nullable=False),
        sa.Column("ttl_days", sa.Integer(), nullable=False),
        sa.Column("watch_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_signal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("thread_id", sa.String(length=128), nullable=True),
    )
    create_common_indexes("watchlist_items")
    for column in ["run_id", "watch_tier", "status", "priority", "watch_until", "thread_id"]:
        op.create_index(f"ix_watchlist_items_{column}", "watchlist_items", [column])

    op.create_table(
        "archived_signals",
        *common_columns(),
        sa.Column("run_id", sa.String(length=128), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_cluster_id", sa.String(length=128), nullable=True),
        sa.Column("original_watchlist_id", sa.String(length=128), nullable=True),
        sa.Column("thread_id", sa.String(length=128), nullable=True),
        sa.Column("archive_reason", sa.String(length=64), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("final_state", sa.Text(), nullable=False),
    )
    create_common_indexes("archived_signals")
    for column in ["run_id", "original_cluster_id", "original_watchlist_id", "thread_id", "archive_reason", "archived_at"]:
        op.create_index(f"ix_archived_signals_{column}", "archived_signals", [column])

    op.create_table(
        "intelligence_threads",
        *common_columns(),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("importance", sa.String(length=64), nullable=False),
        sa.Column("current_thesis", sa.Text(), nullable=False),
    )
    create_common_indexes("intelligence_threads")
    for column in ["status", "importance"]:
        op.create_index(f"ix_intelligence_threads_{column}", "intelligence_threads", [column])

    op.create_table(
        "daily_reports",
        *common_columns(),
        sa.Column("run_id", sa.String(length=128), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=True),
    )
    create_common_indexes("daily_reports")
    for column in ["run_id", "report_date", "status", "quality_score"]:
        op.create_index(f"ix_daily_reports_{column}", "daily_reports", [column])

    op.create_table(
        "trace_events",
        *common_columns(),
        sa.Column("run_id", sa.String(length=128), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", sa.String(length=128), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(length=64), nullable=False),
        sa.Column("agent_role", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("tool_call_id", sa.String(length=128), nullable=True),
        sa.Column("model_call_id", sa.String(length=128), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    create_common_indexes("trace_events")
    for column in ["run_id", "parent_id", "seq", "phase", "agent_role", "event_type", "status", "tool_call_id", "model_call_id"]:
        op.create_index(f"ix_trace_events_{column}", "trace_events", [column])

    op.create_table(
        "artifacts",
        *common_columns(),
        sa.Column("run_id", sa.String(length=128), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("storage", sa.String(length=64), nullable=False),
        sa.Column("uri", sa.Text(), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
    )
    create_common_indexes("artifacts")
    for column in ["run_id", "kind", "storage", "sha256"]:
        op.create_index(f"ix_artifacts_{column}", "artifacts", [column])

    op.create_table(
        "tool_calls",
        *common_columns(),
        sa.Column("run_id", sa.String(length=128), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_role", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=True),
        sa.Column("query", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("trace_event_id", sa.String(length=128), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    create_common_indexes("tool_calls")
    for column in ["run_id", "agent_role", "tool_name", "source_type", "status", "started_at", "trace_event_id"]:
        op.create_index(f"ix_tool_calls_{column}", "tool_calls", [column])

    op.create_table(
        "model_calls",
        *common_columns(),
        sa.Column("run_id", sa.String(length=128), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_role", sa.String(length=64), nullable=False),
        sa.Column("model_provider", sa.String(length=128), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("trace_event_id", sa.String(length=128), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    create_common_indexes("model_calls")
    for column in ["run_id", "agent_role", "model_provider", "model_name", "status", "started_at", "trace_event_id"]:
        op.create_index(f"ix_model_calls_{column}", "model_calls", [column])

    op.create_table(
        "review_results",
        *common_columns(),
        sa.Column("run_id", sa.String(length=128), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_id", sa.String(length=128), nullable=False),
        sa.Column("reviewer_agent", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=64), nullable=False),
        sa.Column("reasoning_summary", sa.Text(), nullable=False),
    )
    create_common_indexes("review_results")
    for column in ["run_id", "report_id", "reviewer_agent", "decision"]:
        op.create_index(f"ix_review_results_{column}", "review_results", [column])

    op.create_table(
        "review_issues",
        *common_columns(),
        sa.Column("run_id", sa.String(length=128), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_id", sa.String(length=128), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("report_item_id", sa.String(length=128), nullable=True),
    )
    create_common_indexes("review_issues")
    for column in ["run_id", "report_id", "priority", "report_item_id"]:
        op.create_index(f"ix_review_issues_{column}", "review_issues", [column])


def downgrade() -> None:
    for table_name in [
        "review_issues",
        "review_results",
        "model_calls",
        "tool_calls",
        "artifacts",
        "trace_events",
        "daily_reports",
        "intelligence_threads",
        "archived_signals",
        "watchlist_items",
        "evaluation_results",
        "event_clusters",
        "candidate_items",
        "evidence_items",
        "runs",
    ]:
        op.drop_table(table_name)
