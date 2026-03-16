"""merge all migration heads

Revision ID: merge_all_heads_2026
Revises: a9b1c2d3e4f7, b05c7b628636, b4338be78eec, d1e2f3a4b5c6, fa6e83f8d9a1
Create Date: 2026-03-16 08:22:00.000000

"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "merge_all_heads_2026"
down_revision = ("a9b1c2d3e4f7", "b05c7b628636", "b4338be78eec", "d1e2f3a4b5c6", "fa6e83f8d9a1")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This is a merge migration - no schema changes
    pass


def downgrade() -> None:
    # This is a merge migration - no schema changes
    pass
