"""add_thread_owner_board_id

Adds owner_board_id to threads to track which board initiated cross-board
threads in the platform Support channel. Used by channel routing to enforce
thread-level privacy (a board lead only receives dispatches for threads
their board started).

Revision ID: b1c2d3e4f5a6
Revises: 57d8482e5312
Create Date: 2026-03-28 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b1c2d3e4f5a6"
down_revision = "57d8482e5312"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add owner_board_id column to threads table."""
    op.add_column(
        "threads",
        sa.Column("owner_board_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_threads_owner_board_id",
        "threads",
        ["owner_board_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_threads_owner_board_id_boards",
        "threads",
        "boards",
        ["owner_board_id"],
        ["id"],
    )


def downgrade() -> None:
    """Remove owner_board_id column from threads table."""
    op.drop_constraint("fk_threads_owner_board_id_boards", "threads", type_="foreignkey")
    op.drop_index("ix_threads_owner_board_id", table_name="threads")
    op.drop_column("threads", "owner_board_id")
