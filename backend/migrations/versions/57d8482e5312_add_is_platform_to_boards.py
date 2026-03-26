"""add is_platform to boards

Revision ID: 57d8482e5312
Revises: c4a1f2e8d9b3
Create Date: 2026-03-26 11:25:57.108320

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "57d8482e5312"
down_revision = "c4a1f2e8d9b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add is_platform column to boards with index."""
    op.add_column(
        "boards",
        sa.Column(
            "is_platform",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        op.f("ix_boards_is_platform"),
        "boards",
        ["is_platform"],
        unique=False,
    )
    op.alter_column("boards", "is_platform", server_default=None)


def downgrade() -> None:
    """Remove is_platform column and index from boards."""
    op.drop_index(op.f("ix_boards_is_platform"), table_name="boards")
    op.drop_column("boards", "is_platform")
