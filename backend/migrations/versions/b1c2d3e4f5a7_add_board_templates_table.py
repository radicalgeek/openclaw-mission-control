"""add_board_templates_table

Revision ID: b1c2d3e4f5a7
Revises: a3b4c5d6e7f8
Create Date: 2026-04-04 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b1c2d3e4f5a7"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add board_templates table for DB-stored per-board and org-level template overrides."""
    op.create_table(
        "board_templates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("board_id", sa.UUID(), nullable=True),
        sa.Column("file_name", sa.String(), nullable=False),
        sa.Column("template_content", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["board_id"], ["boards.id"], ondelete="CASCADE", name="fk_board_templates_board_id"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "board_id",
            "file_name",
            name="uq_board_templates_org_board_file",
        ),
    )
    op.create_index("ix_board_templates_organization_id", "board_templates", ["organization_id"])
    op.create_index("ix_board_templates_board_id", "board_templates", ["board_id"])
    op.create_index("ix_board_templates_file_name", "board_templates", ["file_name"])


def downgrade() -> None:
    """Drop board_templates table."""
    op.drop_index("ix_board_templates_file_name", table_name="board_templates")
    op.drop_index("ix_board_templates_board_id", table_name="board_templates")
    op.drop_index("ix_board_templates_organization_id", table_name="board_templates")
    op.drop_table("board_templates")
