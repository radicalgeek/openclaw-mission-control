"""Unify all migration heads - bridge from orphaned merge_all_heads_2026.

This migration serves as a bridge from the orphaned 'merge_all_heads_2026' 
revision (which exists in the database but not in the codebase) to the actual
current migration heads. It unifies all parallel branches.

Revision ID: merge_all_heads_2026
Revises: b4338be78eec, c3d4e5f6a7b8, e7a3f1d9c2b8, merge_template_pack_migrations
Create Date: 2026-03-17 02:20:00

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "merge_all_heads_2026"
down_revision: Union[str, tuple, None] = (
    "b4338be78eec",  # add_composite_indexes_for_task_listing
    "c3d4e5f6a7b8",  # add_skill_config_to_agent_template_packs
    "e7a3f1d9c2b8",  # add_agent_template_packs  
    "merge_template_pack_migrations"  # previous merge
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No-op merge migration
    pass


def downgrade() -> None:
    # No-op merge migration
    pass
