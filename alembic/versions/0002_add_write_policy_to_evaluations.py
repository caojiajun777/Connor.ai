"""add write_policy to evaluations

Revision ID: 0002_add_write_policy_to_evaluations
Revises: 0001_initial_persistence_schema
Create Date: 2026-07-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_add_write_policy_to_evaluations"
down_revision: str | None = "0001_initial_persistence_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evaluation_results",
        sa.Column("write_policy", sa.String(64), nullable=True, index=True),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evaluation_results_write_policy",
        table_name="evaluation_results",
    )
    op.drop_column("evaluation_results", "write_policy")
