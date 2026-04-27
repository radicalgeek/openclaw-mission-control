"""Merge branding-overrides and telemetry migration heads.

Revision ID: merge_branding_telemetry_2026
Revises: c0d1e2f3a4b5, t4d5e6f7a8b9
Create Date: 2026-04-21 00:00:00.000000

"""

from __future__ import annotations

# revision identifiers, used by Alembic.
revision = "merge_branding_telemetry_2026"
down_revision = ("c0d1e2f3a4b5", "t4d5e6f7a8b9")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Merge migration — no schema changes.
    pass


def downgrade() -> None:
    # Merge migration — no schema changes.
    pass
