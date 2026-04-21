"""M4+M5: Add budget_usd to boards and agents.

Revision ID: t4d5e6f7a8b9
Revises: t3c4d5e6f7a8
Create Date: 2026-04-20 00:04:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "t4d5e6f7a8b9"
down_revision = "t3c4d5e6f7a8"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table_name)}
    return column_name in cols


def upgrade() -> None:
    if not _has_column("boards", "budget_usd"):
        op.add_column(
            "boards",
            sa.Column("budget_usd", sa.Numeric(12, 6), nullable=True),
        )
    if not _has_column("agents", "budget_usd"):
        op.add_column(
            "agents",
            sa.Column("budget_usd", sa.Numeric(12, 6), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("agents", "budget_usd")
    op.drop_column("boards", "budget_usd")
