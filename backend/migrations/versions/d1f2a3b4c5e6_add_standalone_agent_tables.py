"""Add standalone agent support: agent_type, installed_skills, agent_webhooks, agent_webhook_payloads, agent_board_access.

Revision ID: d1f2a3b4c5e6
Revises: c1d2e3f4a5b6
Create Date: 2026-04-04 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d1f2a3b4c5e6"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add agent_type column and backfill
    op.add_column(
        "agents",
        sa.Column("agent_type", sa.String(32), nullable=False, server_default="board_worker"),
    )
    op.execute(
        """
        UPDATE agents
        SET agent_type = CASE
            WHEN board_id IS NULL AND is_board_lead = FALSE THEN 'gateway_main'
            WHEN is_board_lead = TRUE THEN 'board_lead'
            ELSE 'board_worker'
        END
        """
    )
    op.create_index("ix_agents_agent_type", "agents", ["agent_type"])

    # 2. Add installed_skills column
    op.add_column(
        "agents",
        sa.Column("installed_skills", sa.JSON, nullable=True),
    )

    # 3. Create agent_webhooks table
    op.create_table(
        "agent_webhooks",
        sa.Column("id", sa.Uuid, primary_key=True, nullable=False),
        sa.Column("agent_id", sa.Uuid, nullable=False, index=True),
        sa.Column("organization_id", sa.Uuid, nullable=False, index=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("secret", sa.Text, nullable=True),
        sa.Column("signature_header", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_webhooks_enabled", "agent_webhooks", ["enabled"])

    # 4. Create agent_webhook_payloads table
    op.create_table(
        "agent_webhook_payloads",
        sa.Column("id", sa.Uuid, primary_key=True, nullable=False),
        sa.Column("agent_id", sa.Uuid, nullable=False, index=True),
        sa.Column("webhook_id", sa.Uuid, nullable=False, index=True),
        sa.Column("payload", sa.JSON, nullable=True),
        sa.Column("headers", sa.JSON, nullable=True),
        sa.Column("source_ip", sa.Text, nullable=True),
        sa.Column("content_type", sa.Text, nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["webhook_id"], ["agent_webhooks.id"], ondelete="CASCADE"),
    )

    # 5. Create agent_board_access table
    op.create_table(
        "agent_board_access",
        sa.Column("id", sa.Uuid, primary_key=True, nullable=False),
        sa.Column("agent_id", sa.Uuid, nullable=False, index=True),
        sa.Column("board_id", sa.Uuid, nullable=False, index=True),
        sa.Column("access_level", sa.String(16), nullable=False, server_default="read"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("agent_id", "board_id", name="uq_agent_board_access"),
    )
    op.create_index("ix_agent_board_access_access_level", "agent_board_access", ["access_level"])


def downgrade() -> None:
    op.drop_table("agent_board_access")
    op.drop_table("agent_webhook_payloads")
    op.drop_table("agent_webhooks")
    op.drop_column("agents", "installed_skills")
    op.drop_index("ix_agents_agent_type", table_name="agents")
    op.drop_column("agents", "agent_type")
