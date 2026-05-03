"""Add graduation workflow fields: plan.decomposition_target, task.plan_id, board.context.

Revision ID: g1a2b3c4d5e6
Revises: merge_branding_telemetry_2026
Create Date: 2026-04-29 10:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "g1a2b3c4d5e6"
down_revision = "merge_branding_telemetry_2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add fields supporting the graduation workflow."""

    # ── plans.decomposition_target ────────────────────────────────────────────
    op.add_column(
        "plans",
        sa.Column(
            "decomposition_target",
            sa.String(),
            nullable=False,
            server_default=sa.text("'board_lead'"),
        ),
    )

    # ── tasks.plan_id ─────────────────────────────────────────────────────────
    op.add_column(
        "tasks",
        sa.Column("plan_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tasks_plan_id",
        "tasks",
        "plans",
        ["plan_id"],
        ["id"],
    )
    op.create_index(op.f("ix_tasks_plan_id"), "tasks", ["plan_id"], unique=False)

    # ── boards.context ────────────────────────────────────────────────────────
    op.add_column(
        "boards",
        sa.Column("context", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Revert graduation workflow fields."""

    op.drop_column("boards", "context")

    op.drop_index(op.f("ix_tasks_plan_id"), table_name="tasks")
    op.drop_constraint("fk_tasks_plan_id", "tasks", type_="foreignkey")
    op.drop_column("tasks", "plan_id")

    op.drop_column("plans", "decomposition_target")
