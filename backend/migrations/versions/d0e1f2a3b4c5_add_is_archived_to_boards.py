"""Add is_archived column to boards table.

Revision ID: d0e1f2a3b4c5
Revises: merge_all_heads_2026
Create Date: 2026-04-21 00:01:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d0e1f2a3b4c5"
down_revision = "merge_all_heads_2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add is_archived to boards with a default of false."""
    op.add_column(
        "boards",
        sa.Column(
            "is_archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        op.f("ix_boards_is_archived"),
        "boards",
        ["is_archived"],
        unique=False,
    )


def downgrade() -> None:
    """Remove is_archived from boards."""
    op.drop_index(op.f("ix_boards_is_archived"), table_name="boards")
    op.drop_column("boards", "is_archived")
