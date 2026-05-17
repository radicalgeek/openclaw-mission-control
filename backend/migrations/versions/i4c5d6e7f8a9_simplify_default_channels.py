"""Simplify default board channels.

Revision ID: i4c5d6e7f8a9
Revises: h3b4c5d6e7f8
Create Date: 2026-05-17 19:10:00.000000

"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "i4c5d6e7f8a9"
down_revision = "h3b4c5d6e7f8"
branch_labels = None
depends_on = None


_CI_CD = {
    "name": "CI/CD Alerts",
    "slug": "ci-cd-alerts",
    "description": "Build, test, deployment, and release pipeline alerts",
    "webhook_source_filter": "cicd",
    "position": 0,
}

_OBSERVABILITY = {
    "name": "Observability Alerts",
    "slug": "observability-alerts",
    "description": "Runtime health, monitoring, and production incident alerts",
    "webhook_source_filter": "observability",
    "position": 1,
}

_GENERAL = {
    "name": "General",
    "slug": "general",
    "description": "Project discussion and coordination",
    "webhook_source_filter": None,
    "position": 2,
}

_LEGACY_DEFAULT_SLUGS = (
    "deployment-alerts",
    "test-run-alerts",
    "development",
    "devops",
    "testing",
    "architecture",
)


def _upsert_channel(
    conn: sa.Connection,
    board_id: object,
    *,
    existing_slug: str | None,
    definition: dict[str, object],
    channel_type: str,
    is_readonly: bool,
    now: datetime,
) -> None:
    slug = str(definition["slug"])
    existing = conn.execute(
        sa.text(
            """
            SELECT id
            FROM channels
            WHERE board_id = :board_id
              AND (slug = :slug OR (:existing_slug IS NOT NULL AND slug = :existing_slug))
            ORDER BY CASE WHEN slug = :slug THEN 0 ELSE 1 END
            LIMIT 1
            """
        ),
        {"board_id": board_id, "slug": slug, "existing_slug": existing_slug},
    ).fetchone()

    if existing is not None:
        conn.execute(
            sa.text(
                """
                UPDATE channels
                   SET name = :name,
                       slug = :slug,
                       channel_type = :channel_type,
                       description = :description,
                       is_readonly = :is_readonly,
                       webhook_source_filter = :webhook_source_filter,
                       position = :position,
                       is_archived = false,
                       updated_at = :now
                 WHERE id = :id
                """
            ),
            {
                "id": existing[0],
                "name": definition["name"],
                "slug": slug,
                "channel_type": channel_type,
                "description": definition["description"],
                "is_readonly": is_readonly,
                "webhook_source_filter": definition["webhook_source_filter"],
                "position": definition["position"],
                "now": now,
            },
        )
        return

    conn.execute(
        sa.text(
            """
            INSERT INTO channels
                (id, board_id, name, slug, channel_type, description,
                 is_archived, is_readonly, webhook_source_filter, webhook_secret,
                 position, created_at, updated_at)
            VALUES
                (:id, :board_id, :name, :slug, :channel_type, :description,
                 false, :is_readonly, :webhook_source_filter, :webhook_secret,
                 :position, :now, :now)
            """
        ),
        {
            "id": uuid.uuid4(),
            "board_id": board_id,
            "name": definition["name"],
            "slug": slug,
            "channel_type": channel_type,
            "description": definition["description"],
            "is_readonly": is_readonly,
            "webhook_source_filter": definition["webhook_source_filter"],
            "webhook_secret": secrets.token_urlsafe(32),
            "position": definition["position"],
            "now": now,
        },
    )


def upgrade() -> None:
    """Converge existing boards to CI/CD, Observability, and General channels."""
    conn = op.get_bind()
    now = datetime.utcnow()

    board_ids = [
        row[0]
        for row in conn.execute(
            sa.text("SELECT id FROM boards WHERE is_archived = false OR is_archived IS NULL")
        ).fetchall()
    ]

    for board_id in board_ids:
        _upsert_channel(
            conn,
            board_id,
            existing_slug="build-alerts",
            definition=_CI_CD,
            channel_type="alert",
            is_readonly=True,
            now=now,
        )
        _upsert_channel(
            conn,
            board_id,
            existing_slug="production-alerts",
            definition=_OBSERVABILITY,
            channel_type="alert",
            is_readonly=True,
            now=now,
        )
        _upsert_channel(
            conn,
            board_id,
            existing_slug=None,
            definition=_GENERAL,
            channel_type="discussion",
            is_readonly=False,
            now=now,
        )

    conn.execute(
        sa.text(
            """
            UPDATE channels
               SET is_archived = true,
                   updated_at = :now
             WHERE slug IN :slugs
               AND channel_type != 'direct'
            """
        ).bindparams(sa.bindparam("slugs", expanding=True)),
        {"slugs": _LEGACY_DEFAULT_SLUGS, "now": now},
    )


def downgrade() -> None:
    """Restore the previous channel names and unarchive legacy defaults when present."""
    conn = op.get_bind()
    now = datetime.utcnow()

    conn.execute(
        sa.text(
            """
            UPDATE channels
               SET name = 'Build Alerts',
                   slug = 'build-alerts',
                   description = 'CI/CD build results and failures',
                   webhook_source_filter = 'build',
                   position = 0,
                   updated_at = :now
             WHERE slug = 'ci-cd-alerts'
            """
        ),
        {"now": now},
    )
    conn.execute(
        sa.text(
            """
            UPDATE channels
               SET name = 'Production Alerts',
                   slug = 'production-alerts',
                   description = 'Production incidents, errors, and health checks',
                   webhook_source_filter = 'production',
                   position = 3,
                   updated_at = :now
             WHERE slug = 'observability-alerts'
            """
        ),
        {"now": now},
    )
    conn.execute(
        sa.text(
            """
            UPDATE channels
               SET is_archived = false,
                   updated_at = :now
             WHERE slug IN :slugs
               AND channel_type != 'direct'
            """
        ).bindparams(sa.bindparam("slugs", expanding=True)),
        {"slugs": _LEGACY_DEFAULT_SLUGS, "now": now},
    )
