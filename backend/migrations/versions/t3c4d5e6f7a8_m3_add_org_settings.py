"""M3: Add settings JSONB column to organizations for governance config.

Revision ID: t3c4d5e6f7a8
Revises: t2b3c4d5e6f7
Create Date: 2026-04-20 00:03:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "t3c4d5e6f7a8"
down_revision = "t2b3c4d5e6f7"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table_name)}
    return column_name in cols


def upgrade() -> None:
    if not _has_column("organizations", "settings"):
        op.add_column(
            "organizations",
            sa.Column("settings", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("organizations", "settings")
