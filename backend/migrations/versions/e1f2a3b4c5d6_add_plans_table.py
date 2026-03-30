"""add_plans_table

Revision ID: e1f2a3b4c5d6
Revises: b1c2d3e4f5a6
Create Date: 2026-03-30 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision = "e1f2a3b4c5d6"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the plans table for board-scoped planning documents."""
    op.create_table(
        "plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("content", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("session_key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("messages", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_plans_board_id"), "plans", ["board_id"], unique=False)
    op.create_index(op.f("ix_plans_status"), "plans", ["status"], unique=False)
    op.create_index(op.f("ix_plans_slug"), "plans", ["slug"], unique=False)
    op.create_index(op.f("ix_plans_task_id"), "plans", ["task_id"], unique=False)
    op.create_index(op.f("ix_plans_created_by_user_id"), "plans", ["created_by_user_id"], unique=False)


def downgrade() -> None:
    """Drop the plans table."""
    op.drop_index(op.f("ix_plans_created_by_user_id"), table_name="plans")
    op.drop_index(op.f("ix_plans_task_id"), table_name="plans")
    op.drop_index(op.f("ix_plans_slug"), table_name="plans")
    op.drop_index(op.f("ix_plans_status"), table_name="plans")
    op.drop_index(op.f("ix_plans_board_id"), table_name="plans")
    op.drop_table("plans")
