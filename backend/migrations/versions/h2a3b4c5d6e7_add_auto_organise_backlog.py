"""add_auto_organise_backlog_to_boards

Revision ID: h2a3b4c5d6e7
Revises: g1a2b3c4d5e6
Create Date: 2026-05-04 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "h2a3b4c5d6e7"
down_revision = "g1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add auto_organise_backlog column to boards."""
    op.add_column(
        "boards",
        sa.Column(
            "auto_organise_backlog",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    """Remove auto_organise_backlog column from boards."""
    op.drop_column("boards", "auto_organise_backlog")
