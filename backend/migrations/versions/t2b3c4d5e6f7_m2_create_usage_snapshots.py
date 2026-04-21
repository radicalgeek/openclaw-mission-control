"""M2: Create usage_snapshots table for token and cost tracking.

Revision ID: t2b3c4d5e6f7
Revises: t1a2b3c4d5e6
Create Date: 2026-04-20 00:02:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "t2b3c4d5e6f7"
down_revision = "t1a2b3c4d5e6"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if not _has_table("usage_snapshots"):
        op.create_table(
            "usage_snapshots",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("organization_id", sa.Uuid(), nullable=False),
            sa.Column("gateway_id", sa.Uuid(), nullable=False),
            sa.Column("agent_id", sa.Uuid(), nullable=True),
            sa.Column("session_key", sa.Text(), nullable=True),
            sa.Column("model_id", sa.Text(), nullable=False, server_default="unknown"),
            sa.Column("prompt_tokens", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("completion_tokens", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("total_tokens", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
            sa.Column(
                "snapshot_type",
                sa.String(32),
                nullable=False,
                server_default="periodic",
            ),
            sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["organization_id"], ["organizations.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["gateway_id"], ["gateways.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_usage_snapshots_organization_id", "usage_snapshots", ["organization_id"])
        op.create_index("ix_usage_snapshots_gateway_id", "usage_snapshots", ["gateway_id"])
        op.create_index("ix_usage_snapshots_agent_id", "usage_snapshots", ["agent_id"])
        op.create_index("ix_usage_snapshots_captured_at", "usage_snapshots", ["captured_at"])
        op.create_index("ix_usage_snapshots_snapshot_type", "usage_snapshots", ["snapshot_type"])


def downgrade() -> None:
    op.drop_table("usage_snapshots")
