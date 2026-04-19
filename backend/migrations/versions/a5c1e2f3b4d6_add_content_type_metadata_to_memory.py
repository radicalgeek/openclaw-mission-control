"""Add content_type and metadata columns to board_memory and board_group_memory.

Revision ID: a5c1e2f3b4d6
Revises: d1f2a3b4c5e6
Create Date: 2026-04-11 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a5c1e2f3b4d6"
down_revision = "d1f2a3b4c5e6"
branch_labels = None
depends_on = None


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    """Add content_type (VARCHAR, default 'text') and metadata (JSONB) to memory tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_board_memory = _column_names(inspector, "board_memory")
    if "content_type" not in existing_board_memory:
        op.add_column(
            "board_memory",
            sa.Column(
                "content_type",
                sa.String(length=50),
                nullable=False,
                server_default="text",
            ),
        )
    if "metadata" not in existing_board_memory:
        op.add_column(
            "board_memory",
            sa.Column("metadata", sa.JSON(), nullable=True),
        )

    existing_group_memory = _column_names(inspector, "board_group_memory")
    if "content_type" not in existing_group_memory:
        op.add_column(
            "board_group_memory",
            sa.Column(
                "content_type",
                sa.String(length=50),
                nullable=False,
                server_default="text",
            ),
        )
    if "metadata" not in existing_group_memory:
        op.add_column(
            "board_group_memory",
            sa.Column("metadata", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    """Remove content_type and metadata columns from memory tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_group_memory = _column_names(inspector, "board_group_memory")
    if "metadata" in existing_group_memory:
        op.drop_column("board_group_memory", "metadata")
    if "content_type" in existing_group_memory:
        op.drop_column("board_group_memory", "content_type")

    existing_board_memory = _column_names(inspector, "board_memory")
    if "metadata" in existing_board_memory:
        op.drop_column("board_memory", "metadata")
    if "content_type" in existing_board_memory:
        op.drop_column("board_memory", "content_type")
