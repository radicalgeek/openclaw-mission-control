"""add_sprint_backlog_tables

Revision ID: a3b4c5d6e7f8
Revises: e1f2a3b4c5d6
Create Date: 2026-04-01 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a3b4c5d6e7f8"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add sprints, sprint_tickets, sprint_webhooks tables and new columns."""

    # ---- sprints ----------------------------------------------------------------
    op.create_table(
        "sprints",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("board_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("goal", sa.String(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sprints_board_id", "sprints", ["board_id"])
    op.create_index("ix_sprints_organization_id", "sprints", ["organization_id"])
    op.create_index("ix_sprints_status", "sprints", ["status"])
    op.create_index("ix_sprints_slug", "sprints", ["slug"])
    op.create_index("ix_sprints_position", "sprints", ["position"])
    # Partial unique index: only one active sprint per board at a time
    op.execute(
        "CREATE UNIQUE INDEX ix_sprints_board_id_active "
        "ON sprints (board_id) WHERE status = 'active'"
    )

    # ---- sprint_tickets ---------------------------------------------------------
    op.create_table(
        "sprint_tickets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sprint_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["sprint_id"], ["sprints.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_sprint_tickets_task_id"),
    )
    op.create_index("ix_sprint_tickets_sprint_id", "sprint_tickets", ["sprint_id"])
    op.create_index("ix_sprint_tickets_task_id", "sprint_tickets", ["task_id"])

    # ---- sprint_webhooks --------------------------------------------------------
    op.create_table(
        "sprint_webhooks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("board_id", sa.UUID(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("secret", sa.String(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sprint_webhooks_board_id", "sprint_webhooks", ["board_id"])
    op.create_index("ix_sprint_webhooks_organization_id", "sprint_webhooks", ["organization_id"])

    # ---- boards: new columns ----------------------------------------------------
    op.add_column(
        "boards",
        sa.Column(
            "auto_advance_sprint",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )

    # ---- tasks: new columns -----------------------------------------------------
    op.add_column(
        "tasks",
        sa.Column(
            "is_backlog",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "tasks",
        sa.Column("sprint_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tasks_sprint_id",
        "tasks",
        "sprints",
        ["sprint_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_tasks_is_backlog", "tasks", ["is_backlog"])
    op.create_index("ix_tasks_sprint_id", "tasks", ["sprint_id"])

    # ---- plans: new column ------------------------------------------------------
    op.add_column(
        "plans",
        sa.Column("decomposed_tickets", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Remove sprint tables and new columns."""
    # plans
    op.drop_column("plans", "decomposed_tickets")

    # tasks
    op.drop_index("ix_tasks_sprint_id", table_name="tasks")
    op.drop_index("ix_tasks_is_backlog", table_name="tasks")
    op.drop_constraint("fk_tasks_sprint_id", "tasks", type_="foreignkey")
    op.drop_column("tasks", "sprint_id")
    op.drop_column("tasks", "is_backlog")

    # boards
    op.drop_column("boards", "auto_advance_sprint")

    # sprint_webhooks
    op.drop_index("ix_sprint_webhooks_organization_id", table_name="sprint_webhooks")
    op.drop_index("ix_sprint_webhooks_board_id", table_name="sprint_webhooks")
    op.drop_table("sprint_webhooks")

    # sprint_tickets
    op.drop_index("ix_sprint_tickets_task_id", table_name="sprint_tickets")
    op.drop_index("ix_sprint_tickets_sprint_id", table_name="sprint_tickets")
    op.drop_table("sprint_tickets")

    # sprints
    op.execute("DROP INDEX IF EXISTS ix_sprints_board_id_active")
    op.drop_index("ix_sprints_position", table_name="sprints")
    op.drop_index("ix_sprints_slug", table_name="sprints")
    op.drop_index("ix_sprints_status", table_name="sprints")
    op.drop_index("ix_sprints_organization_id", table_name="sprints")
    op.drop_index("ix_sprints_board_id", table_name="sprints")
    op.drop_table("sprints")
