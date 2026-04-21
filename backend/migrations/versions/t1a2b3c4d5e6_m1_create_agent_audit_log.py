"""M1: Create agent_audit_log table for structured agent audit trail.

Revision ID: t1a2b3c4d5e6
Revises: t0a1b2c3d4e5
Create Date: 2026-04-20 00:01:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "t1a2b3c4d5e6"
down_revision = "t0a1b2c3d4e5"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if not _has_table("agent_audit_log"):
        op.create_table(
            "agent_audit_log",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("organization_id", sa.Uuid(), nullable=False),
            sa.Column("gateway_id", sa.Uuid(), nullable=True),
            sa.Column("board_id", sa.Uuid(), nullable=True),
            sa.Column("agent_id", sa.Uuid(), nullable=True),
            sa.Column("task_id", sa.Uuid(), nullable=True),
            sa.Column("session_key", sa.Text(), nullable=True),
            sa.Column("thread_id", sa.Uuid(), nullable=True),
            sa.Column("sprint_id", sa.Uuid(), nullable=True),
            sa.Column("event_category", sa.String(64), nullable=False),
            sa.Column("event_action", sa.String(128), nullable=False),
            sa.Column("detail", sa.JSON(), nullable=True),
            sa.Column("token_input", sa.Integer(), nullable=True),
            sa.Column("token_output", sa.Integer(), nullable=True),
            sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
            sa.Column("model_id", sa.Text(), nullable=True),
            sa.Column("correlation_id", sa.Text(), nullable=True),
            sa.Column("source", sa.String(64), nullable=False, server_default="product_foundry"),
            sa.Column("actor_type", sa.String(32), nullable=False, server_default="system"),
            sa.Column("actor_id", sa.Uuid(), nullable=True),
            sa.Column("ip_address", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["organization_id"], ["organizations.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["gateway_id"], ["gateways.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["board_id"], ["boards.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["sprint_id"], ["sprints.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_agent_audit_log_organization_id", "agent_audit_log", ["organization_id"])
        op.create_index("ix_agent_audit_log_agent_id", "agent_audit_log", ["agent_id"])
        op.create_index("ix_agent_audit_log_board_id", "agent_audit_log", ["board_id"])
        op.create_index("ix_agent_audit_log_event_category", "agent_audit_log", ["event_category"])
        op.create_index("ix_agent_audit_log_event_action", "agent_audit_log", ["event_action"])
        op.create_index("ix_agent_audit_log_created_at", "agent_audit_log", ["created_at"])
        op.create_index("ix_agent_audit_log_correlation_id", "agent_audit_log", ["correlation_id"])
        op.create_index("ix_agent_audit_log_source", "agent_audit_log", ["source"])


def downgrade() -> None:
    op.drop_table("agent_audit_log")
