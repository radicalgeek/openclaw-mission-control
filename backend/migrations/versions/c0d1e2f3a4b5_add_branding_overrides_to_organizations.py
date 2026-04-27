"""Add branding_overrides column to organizations table.

Revision ID: b1c2d3e4f5a6
Revises: a5c1e2f3b4d6
Create Date: 2026-04-18 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c0d1e2f3a4b5"
down_revision = "a5c1e2f3b4d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("branding_overrides", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizations", "branding_overrides")
