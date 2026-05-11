"""add_sprint_review_gate

Revision ID: h3b4c5d6e7f8
Revises: h2a3b4c5d6e7
Create Date: 2026-05-11 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "h3b4c5d6e7f8"
down_revision = "h2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create sprint review verdict table."""
    op.create_table(
        "sprint_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("sprint_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("findings", sa.JSON(), nullable=True),
        sa.Column("created_ticket_ids", sa.JSON(), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["sprint_id"], ["sprints.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sprint_id", "role", name="uq_sprint_reviews_sprint_role"),
    )
    op.create_index(op.f("ix_sprint_reviews_agent_id"), "sprint_reviews", ["agent_id"])
    op.create_index(op.f("ix_sprint_reviews_board_id"), "sprint_reviews", ["board_id"])
    op.create_index(
        op.f("ix_sprint_reviews_organization_id"),
        "sprint_reviews",
        ["organization_id"],
    )
    op.create_index(op.f("ix_sprint_reviews_role"), "sprint_reviews", ["role"])
    op.create_index(op.f("ix_sprint_reviews_sprint_id"), "sprint_reviews", ["sprint_id"])
    op.create_index(op.f("ix_sprint_reviews_status"), "sprint_reviews", ["status"])


def downgrade() -> None:
    """Drop sprint review verdict table."""
    op.drop_index(op.f("ix_sprint_reviews_status"), table_name="sprint_reviews")
    op.drop_index(op.f("ix_sprint_reviews_sprint_id"), table_name="sprint_reviews")
    op.drop_index(op.f("ix_sprint_reviews_role"), table_name="sprint_reviews")
    op.drop_index(op.f("ix_sprint_reviews_organization_id"), table_name="sprint_reviews")
    op.drop_index(op.f("ix_sprint_reviews_board_id"), table_name="sprint_reviews")
    op.drop_index(op.f("ix_sprint_reviews_agent_id"), table_name="sprint_reviews")
    op.drop_table("sprint_reviews")
