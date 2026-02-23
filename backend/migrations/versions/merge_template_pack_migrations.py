"""Merge agent_template_packs migration branch with main chain.

Merges the e7a3f1d9c2b8 branch (add_agent_template_packs from feat/agent-template-packs)
with the existing merge_heads_to_unify head.

Revision ID: merge_template_pack_migrations
Revises: merge_heads_to_unify, e7a3f1d9c2b8
Create Date: 2026-02-23 17:50:00

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "merge_template_pack_migrations"
down_revision: Union[str, tuple, None] = ("merge_heads_to_unify", "e7a3f1d9c2b8")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
